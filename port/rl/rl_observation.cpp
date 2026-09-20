/*
 * rl_observation.cpp -- passive observation snapshot (M1b).
 *
 * One listener on GamePostUpdateEvent captures a whole RLObservation into a
 * cached struct; rlObservationGet() hands out a copy. That is the entire
 * subsystem.
 *
 * Why the snapshot is taken here and only here: port/gameloop.cpp fires
 * GamePostUpdateEvent after port_resume_service_threads() has run this host
 * update's controller read, game logic and display-list submission, so the
 * game state is settled and internally consistent. Capturing once at that
 * point gives M1c a coherent view of one completed simulation update, instead
 * of letting arbitrary callers walk live game structures at arbitrary times.
 *
 * The split of work is deliberate:
 *   - everything game-owned is read by rlGameFillObservation(), which lives in
 *     typed decomp code, because FTStruct / SCBattleState / MPCollData must
 *     never be mirrored or offset-walked from C++;
 *   - the three port-owned fields (schema, host frame, input tick) are filled
 *     here.
 *
 * M1b is read-only by construction: nothing in this file writes to game
 * memory, consumes input, advances a clock or steps the simulation.
 * syNetInputGetTick() is a plain getter over sSYNetInputTick (netinput.c).
 *
 * No synchronisation: capture and read both happen on the main thread, and
 * M1b has no IPC, no client and no second thread. If M1c introduces a
 * cross-thread protocol, the synchronisation question belongs there.
 */
#include "rl/rl.h"

#include "hooks/Events.h"
#include "port_log.h"

#include <cstdint>
#include <cstring>

extern "C" uint32_t syNetInputGetTick(void);

namespace {

RLObservation sObservation;
bool sHasObservation = false;

/* Counts GamePostUpdateEvent callbacks since rlObservationRegister(). This is
 * the same quantity M1a reports as the diagnostic "host_frames" in its result
 * JSON: both counters start at zero when rlRuntimeRegister() installs the two
 * listeners, and both increment unconditionally on every dispatch of the same
 * event, so they cannot drift apart. It is kept local rather than shared so
 * the frozen M1a result path is left untouched. */
uint32_t sHostFrames = 0;

void OnGamePostUpdate(IEvent *) {
	sHostFrames++;

	RLObservation obs;
	std::memset(&obs, 0, sizeof(obs));

	/* Game-owned fields, read from typed decomp code. Leaves the zeros in
	 * place (btt_active / fighter_valid false) whenever the scene, the battle
	 * state or the fighter is not available. */
	rlGameFillObservation(&obs);

	/* Port-owned fields. input_tick is syNetInputGetTick() verbatim: at this
	 * point it already names the NEXT controller frame, one past the row the
	 * update that just completed consumed. It is never decremented -- the
	 * validated baseline clears at time_passed=446 / input_tick=447. */
	obs.observation_schema = RL_OBSERVATION_SCHEMA;
	obs.host_frame = sHostFrames;
	obs.input_tick = syNetInputGetTick();

	sObservation = obs;
	sHasObservation = true;

	/* M1c: hand this exact snapshot to the stepping state machine
	 * (rl_step.cpp) so a step result pairs with the capture of the update
	 * that consumed its action. It copies under its own mutex for other
	 * threads; rlObservationGet() itself stays main-thread only. No-op unless
	 * interactive stepping is enabled. */
	rlStepOnObservation(&obs);
}

} // namespace

extern "C" void rlObservationRegister(void) {
	if (!rlIsEnabled()) {
		return;
	}
	REGISTER_LISTENER(GamePostUpdateEvent, EVENT_PRIORITY_NORMAL, OnGamePostUpdate);
	port_log("SSB64 RL: observation capture registered schema=%u\n", (unsigned)RL_OBSERVATION_SCHEMA);
}

extern "C" int rlObservationGet(RLObservation *out) {
	if (out == nullptr || !sHasObservation) {
		return 0;
	}
	*out = sObservation;
	return 1;
}
