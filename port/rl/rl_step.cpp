/*
 * rl_step.cpp -- interactive one-action / one-tick native stepping (M1c).
 *
 * The primitive: a caller submits exactly one validated raw controller frame,
 * exactly one native input tick consumes it through the same netinput path
 * the text replay uses, exactly one simulation update runs, the M1b snapshot
 * of that update becomes the step result, and the host then parks again.
 *
 * HOW THE PARK FREEZES GAME TIME. Nothing in the game reads wall-clock time
 * for gameplay: the BTT timer adds sySchedulerGetTicCount() deltas, and that
 * counter increments once per INTR_VRETRACE, which only exists because
 * PortPushFrame() posts it. So while the host gate is closed (see
 * rlStepHostGateClosed) PortPushFrame() posts no VRETRACE, rotates no
 * framebuffer and resumes no coroutine; it only pumps window events and
 * re-presents the last framebuffer. Every frame the gate lets through is a
 * complete normal frame. The game therefore sees exactly the free-running
 * sequence of frames with the parked ones deleted, and the game coroutine
 * never waits anywhere it would not wait in a free run: it sits at the
 * taskman game-tic receive, as always.
 *
 * WHERE EACH TRANSITION RUNS.
 *   - rlStepSubmit / rlStepPoll / rlStepWait: any thread (M1d will call them
 *     from a transport thread; rlStepWait refuses the main thread because the
 *     main thread has to keep pumping frames).
 *   - Inactive -> WaitingForAction: main thread, in rlStepOnObservation(),
 *     when the M1b snapshot first shows the BTT battle with game_status
 *     neither Wait nor Pause. That is the post-update of the update that set
 *     Go, and the next controller read is the one the replay uses for row 0
 *     (sc1PBonusStageFuncReadReplay applies the same predicate to the same
 *     field, and no game code runs between a post-update and the next read).
 *   - ActionReady -> ActionConsumed: game coroutine, in rlStepControllerRead()
 *     called by the BTT controller callback at the read for tick T.
 *   - ActionConsumed -> ObservationReady: main thread, in
 *     rlStepOnObservation(), when the snapshot reports input_tick == T + 1.
 *   - ObservationReady -> WaitingForAction / EpisodeEnded / Stopping: the
 *     collecting thread, inside rlStepPoll / rlStepWait.
 *   - EpisodeEnded + SSB64_RL_EXIT_ON_END: the collecting thread only records
 *     the request; rlStepHostUpdate() performs Window::Close() on the main
 *     thread at the next PortPushFrame entry, with the gate still closed, so
 *     no gameplay tick runs between collection and shutdown.
 *
 * SYNCHRONISATION. One std::mutex and one std::condition_variable. The game
 * coroutine is a fiber on the main thread; it takes the mutex only for a few
 * instructions and never across a yield. No sleeps, no timers: the wake-up
 * of a parked host is the next PortPushFrame() iteration, which the existing
 * present / pacing path already runs once per VI period.
 *
 * Out of scope here by design: transport, Python, rewards, resets, frame
 * caps, stall detection, Track 1 discretisation, RNG.
 */
#include "rl/rl.h"

#include "coroutine.h"
#include "port_log.h"

#include <libultraship/libultraship.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <thread>

namespace {

std::mutex sMutex;
std::condition_variable sCond;

/* --- protected by sMutex --------------------------------------------------- */
RLStepState sState = RL_STEP_DISABLED;

RLAction sPending;          /* valid in ActionReady */
uint32_t sConsumedTick = 0; /* valid from ActionConsumed on */
RLStepResult sResult;       /* valid in ObservationReady */
bool sResultFinal = false;  /* sResult shows targets_remaining == 0 */
RLObservation sLatest;      /* newest M1b snapshot, copied under the mutex for other threads */
bool sHasLatest = false;
uint32_t sStepCount = 0;
bool sStopRequested = false;
bool sExitRequested = false; /* deferred SSB64_RL_EXIT_ON_END, performed by rlStepHostUpdate() */
bool sExitPerformed = false;
uint32_t sParkedRun = 0;     /* consecutive parked host iterations, diagnostic */
bool sFallbackLogged = false;

/* --- M4 timing diagnostic (SSB64_RL_TIMING=1), protected by sMutex ---------
 * Stamps only: nothing below is read by a transition. sTimingInFlight collects
 * the stamps of the step being processed (zeroed at submit); sTimingLast is
 * the copy of the most recently collected step that rlStepGetLastTiming()
 * hands out. sTimingEnabled is written once by rlStepRegister(). */
bool sTimingEnabled = false;
RLStepTiming sTimingInFlight;
RLStepTiming sTimingLast;
bool sHasTimingLast = false;

/* --- M7f target-identity diagnostic (SSB64_RL_TARGET_DIAG=1), protected by
 * sMutex. Handed in by the M1b capture together with its observation, so each
 * copy below is exactly as old as the observation it sits next to: sLatest-
 * Targets with sLatest, sResultTargets with sResult, and sTargetsLast is the
 * copy of the most recently collected result (sTargetsLastStep its step
 * count). Never read by a transition. */
RLTargetDiag sLatestTargets;
bool sHasLatestTargets = false;
RLTargetDiag sResultTargets;
bool sHasResultTargets = false;
RLTargetDiag sTargetsLast;
uint32_t sTargetsLastStep = 0;
bool sHasTargetsLast = false;

/* --- main-thread-only, written once by rlStepRegister() before any other
 *     thread that uses this module can exist ----------------------------- */
std::atomic<bool> sRegistered{false};
std::thread::id sMainThread;

const char *stateName(RLStepState s) {
	switch (s) {
	case RL_STEP_DISABLED:
		return "Disabled";
	case RL_STEP_INACTIVE:
		return "Inactive";
	case RL_STEP_WAITING_FOR_ACTION:
		return "WaitingForAction";
	case RL_STEP_ACTION_READY:
		return "ActionReady";
	case RL_STEP_ACTION_CONSUMED:
		return "ActionConsumed";
	case RL_STEP_OBSERVATION_READY:
		return "ObservationReady";
	case RL_STEP_EPISODE_ENDED:
		return "EpisodeEnded";
	case RL_STEP_STOPPING:
		return "Stopping";
	default:
		return "?";
	}
}

/* Another game update is forbidden in exactly these states. */
bool gateClosedLocked() {
	return sState == RL_STEP_WAITING_FOR_ACTION || sState == RL_STEP_OBSERVATION_READY ||
	       sState == RL_STEP_EPISODE_ENDED;
}

/* M4: steady-clock reading for the timing stamps. Safe from any thread and
 * from the game coroutine (a fiber on the main thread); tens of nanoseconds. */
uint64_t nowNs() {
	return (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(
	           std::chrono::steady_clock::now().time_since_epoch())
	    .count();
}

/* Same clean-exit path M1a uses: Window::Close() clears the running flag and
 * the main loop in port.cpp exits. Main thread only. */
bool requestCleanExit() {
	auto ctx = Ship::Context::GetInstance();
	if (!ctx) {
		return false;
	}
	auto window = ctx->GetWindow();
	if (!window) {
		return false;
	}
	window->Close();
	return true;
}

void fillCommonLocked(RLStepResult *out) {
	std::memset(out, 0, sizeof(*out));
	out->step_schema = RL_STEP_SCHEMA;
	out->state = (uint32_t)sState;
	out->step_count = sStepCount;
}

int pollLocked(RLStepResult *out) {
	switch (sState) {
	case RL_STEP_OBSERVATION_READY: {
		*out = sResult;
		RLStepState next;
		if (sStopRequested) {
			next = RL_STEP_STOPPING;
		} else if (sResultFinal) {
			next = RL_STEP_EPISODE_ENDED;
			if (rlStepExitOnEnd()) {
				/* Recorded here, performed by rlStepHostUpdate() on the main
				 * thread; the gate stays closed in between. */
				sExitRequested = true;
			}
		} else {
			next = RL_STEP_WAITING_FOR_ACTION;
		}
		sState = next;
		out->state = (uint32_t)next;
		if (sTimingEnabled) {
			/* M4: the step is complete from the caller's point of view. */
			sTimingInFlight.collected_ns = nowNs();
			sTimingInFlight.step_count = out->step_count;
			sTimingLast = sTimingInFlight;
			sHasTimingLast = true;
		}
		if (sHasResultTargets) {
			/* M7f: the target snapshot of the same capture as this result. */
			sTargetsLast = sResultTargets;
			sTargetsLastStep = out->step_count;
			sHasTargetsLast = true;
		}
		if (next != RL_STEP_WAITING_FOR_ACTION) {
			port_log("SSB64 RL Step: result collected step=%u consumed_tick=%u input_tick=%u "
			         "time_passed=%u targets=%u -> %s%s\n",
			         out->step_count, out->consumed_tick, out->observation.input_tick,
			         out->observation.time_passed, out->observation.targets_remaining, stateName(next),
			         sExitRequested ? " (exit deferred to main thread)" : "");
		}
		sCond.notify_all();
		return RL_STEP_OK;
	}
	case RL_STEP_WAITING_FOR_ACTION:
		fillCommonLocked(out);
		if (sHasLatest) {
			out->observation = sLatest;
		}
		return RL_STEP_READY;
	case RL_STEP_INACTIVE:
	case RL_STEP_ACTION_READY:
	case RL_STEP_ACTION_CONSUMED:
		fillCommonLocked(out);
		return RL_STEP_PENDING;
	case RL_STEP_EPISODE_ENDED:
		fillCommonLocked(out);
		return RL_STEP_ERR_EPISODE_ENDED;
	case RL_STEP_STOPPING:
		fillCommonLocked(out);
		return RL_STEP_ERR_STOPPING;
	case RL_STEP_DISABLED:
	default:
		fillCommonLocked(out);
		return RL_STEP_ERR_DISABLED;
	}
}

} // namespace

/* -- Caller API ------------------------------------------------------------- */

extern "C" int rlStepValidateAction(const RLAction *action) {
	if (action == nullptr) {
		return RL_STEP_ERR_NULL;
	}
	const unsigned int buttons = action->buttons;
	if (buttons == 0u) {
		return RL_STEP_OK;
	}
	if ((buttons & ~(unsigned int)RL_BUTTONS_PERMITTED) != 0u) {
		return RL_STEP_ERR_INVALID_ACTION; /* Start, D-pad or an undefined bit */
	}
	if ((buttons & (buttons - 1u)) != 0u) {
		return RL_STEP_ERR_INVALID_ACTION; /* more than one button */
	}
	return RL_STEP_OK;
}

extern "C" int rlStepSubmit(const RLAction *action) {
	if (action == nullptr) {
		return RL_STEP_ERR_NULL;
	}
	const int valid = rlStepValidateAction(action);
	if (valid != RL_STEP_OK) {
		return valid;
	}

	std::lock_guard<std::mutex> lock(sMutex);
	switch (sState) {
	case RL_STEP_WAITING_FOR_ACTION:
		sPending = *action;
		sState = RL_STEP_ACTION_READY;
		if (sTimingEnabled) {
			/* M4: a new step starts here; every other stamp of it is zero
			 * until its site runs, so a missing stamp reads as 0. */
			std::memset(&sTimingInFlight, 0, sizeof(sTimingInFlight));
			sTimingInFlight.timing_schema = RL_TIMING_SCHEMA;
			sTimingInFlight.submit_ns = nowNs();
		}
		sCond.notify_all();
		return RL_STEP_OK;
	case RL_STEP_INACTIVE:
		return RL_STEP_ERR_NOT_READY;
	case RL_STEP_ACTION_READY:
	case RL_STEP_ACTION_CONSUMED:
	case RL_STEP_OBSERVATION_READY:
		return RL_STEP_ERR_BUSY;
	case RL_STEP_EPISODE_ENDED:
		return RL_STEP_ERR_EPISODE_ENDED;
	case RL_STEP_STOPPING:
		return RL_STEP_ERR_STOPPING;
	case RL_STEP_DISABLED:
	default:
		return RL_STEP_ERR_DISABLED;
	}
}

extern "C" int rlStepPoll(RLStepResult *out) {
	if (out == nullptr) {
		return RL_STEP_ERR_NULL;
	}
	std::lock_guard<std::mutex> lock(sMutex);
	return pollLocked(out);
}

extern "C" int rlStepWait(RLStepResult *out) {
	if (out == nullptr) {
		return RL_STEP_ERR_NULL;
	}
	if (sRegistered.load() && std::this_thread::get_id() == sMainThread) {
		return RL_STEP_ERR_MAIN_THREAD;
	}
	std::unique_lock<std::mutex> lock(sMutex);
	for (;;) {
		const int r = pollLocked(out);
		if (r != RL_STEP_PENDING) {
			return r;
		}
		sCond.wait(lock);
	}
}

extern "C" int rlStepGetState(void) {
	std::lock_guard<std::mutex> lock(sMutex);
	return (int)sState;
}

/* M3: non-consuming read of sLatest, the copy rlStepOnObservation() keeps
 * under the mutex for other threads. Deliberately not routed through
 * pollLocked(): that path collects an ObservationReady result and moves the
 * state machine, and this query must never do either. */
extern "C" int rlStepGetLatestObservation(RLObservation *out) {
	if (out == nullptr) {
		return 0;
	}
	std::lock_guard<std::mutex> lock(sMutex);
	if (!sHasLatest) {
		return 0;
	}
	*out = sLatest;
	return 1;
}

/* M7f: the same non-consuming read, plus the target snapshot handed in with
 * that observation, under one lock so the pair cannot be torn while the host
 * runs free (Inactive) or serves a step. */
extern "C" int rlStepGetLatestObservationTargets(RLObservation *obs, RLTargetDiag *targets) {
	if (obs == nullptr || targets == nullptr) {
		return 0;
	}
	std::lock_guard<std::mutex> lock(sMutex);
	if (!sHasLatest || !sHasLatestTargets) {
		return 0;
	}
	*obs = sLatest;
	*targets = sLatestTargets;
	return 1;
}

extern "C" int rlStepGetLastTargets(RLTargetDiag *out, uint32_t *step_count) {
	if (out == nullptr || step_count == nullptr) {
		return 0;
	}
	std::lock_guard<std::mutex> lock(sMutex);
	if (!sHasTargetsLast) {
		return 0;
	}
	*out = sTargetsLast;
	*step_count = sTargetsLastStep;
	return 1;
}

/* -- Decomp-facing (game coroutine) ---------------------------------------- */

extern "C" int rlStepControllerRead(uint32_t tick, uint16_t *buttons, int8_t *stick_x, int8_t *stick_y) {
	if (buttons == nullptr || stick_x == nullptr || stick_y == nullptr) {
		return 0;
	}
	for (;;) {
		{
			std::lock_guard<std::mutex> lock(sMutex);
			switch (sState) {
			case RL_STEP_ACTION_READY:
				*buttons = sPending.buttons;
				*stick_x = sPending.stick_x;
				*stick_y = sPending.stick_y;
				sConsumedTick = tick;
				sState = RL_STEP_ACTION_CONSUMED;
				if (sTimingEnabled) {
					sTimingInFlight.consumed_ns = nowNs(); /* M4: the accepting read only */
				}
				return 1;
			case RL_STEP_DISABLED:
			case RL_STEP_EPISODE_ENDED:
			case RL_STEP_STOPPING:
				return 0;
			case RL_STEP_INACTIVE:
				/* Not expected: the main thread closes the gate one frame
				 * earlier from the M1b snapshot. Close it from here instead
				 * so no tick can run on stale input. */
				if (!sFallbackLogged) {
					port_log("SSB64 RL Step: ERROR: controller read for tick %u reached before activation; "
					         "parking the game coroutine\n",
					         tick);
				}
				sFallbackLogged = true;
				sState = RL_STEP_WAITING_FOR_ACTION;
				sCond.notify_all();
				break;
			default:
				/* WaitingForAction / ActionConsumed / ObservationReady: the
				 * host gate should have kept this frame from running. */
				if (!sFallbackLogged) {
					port_log("SSB64 RL Step: ERROR: controller read for tick %u reached in state %s; "
					         "parking the game coroutine\n",
					         tick, stateName(sState));
				}
				sFallbackLogged = true;
				break;
			}
		}
		/* Fallback park: yield this coroutine (never the main thread). The
		 * mutex is not held across the yield. */
		port_coroutine_yield();
	}
}

/* -- Main-thread seams ------------------------------------------------------ */

extern "C" void rlStepOnObservation(const RLObservation *obs) {
	rlStepOnObservationTargets(obs, nullptr);
}

extern "C" void rlStepOnObservationTargets(const RLObservation *obs, const RLTargetDiag *targets) {
	if (!sRegistered.load() || obs == nullptr) {
		return;
	}
	std::lock_guard<std::mutex> lock(sMutex);
	sLatest = *obs;
	sHasLatest = true;
	if (targets != nullptr) {
		/* M7f: travels with the observation it was captured with. */
		sLatestTargets = *targets;
		sHasLatestTargets = true;
	} else {
		sHasLatestTargets = false; /* never pair a newer observation with an older snapshot */
	}

	switch (sState) {
	case RL_STEP_ACTION_CONSUMED:
		if (obs->input_tick == sConsumedTick) {
			/* The read did not complete within this host iteration. The gate
			 * stays open; the next full frame finishes it. Not expected
			 * during BTT (bonus stages never block in draw). */
			port_log("SSB64 RL Step: tick %u not yet consumed at post-update; running another frame\n",
			         sConsumedTick);
			break;
		}
		if (obs->input_tick != sConsumedTick + 1u) {
			port_log("SSB64 RL Step: ERROR: input_tick=%u after consuming tick %u (expected %u)\n",
			         obs->input_tick, sConsumedTick, sConsumedTick + 1u);
		}
		sStepCount++;
		std::memset(&sResult, 0, sizeof(sResult));
		sResult.step_schema = RL_STEP_SCHEMA;
		sResult.step_count = sStepCount;
		sResult.consumed_tick = sConsumedTick;
		sResult.observation = *obs;
		sResultFinal = (obs->btt_active != 0u && obs->targets_remaining == 0u);
		sHasResultTargets = (targets != nullptr);
		if (targets != nullptr) {
			sResultTargets = *targets; /* M7f: paired exactly like the observation */
		}
		sState = RL_STEP_OBSERVATION_READY;
		if (sTimingEnabled) {
			sTimingInFlight.observation_ns = nowNs(); /* M4 */
		}
		if (sResultFinal) {
			port_log("SSB64 RL Step: final observation ready step=%u consumed_tick=%u input_tick=%u "
			         "time_passed=%u\n",
			         sStepCount, sConsumedTick, obs->input_tick, obs->time_passed);
		}
		sCond.notify_all();
		break;

	case RL_STEP_INACTIVE:
		/* Same predicate sc1PBonusStageFuncReadReplay applies at the next
		 * controller read, evaluated on the snapshot of the update that just
		 * completed. Nothing runs in between, so the next read is native tick
		 * 0: the boundary at which the validated replay consumes row 0. */
		if (obs->btt_active != 0u && obs->game_status != RL_GAME_STATUS_WAIT &&
		    obs->game_status != RL_GAME_STATUS_PAUSE) {
			sState = RL_STEP_WAITING_FOR_ACTION;
			port_log("SSB64 RL Step: interactive stepping active: game_status=%u input_tick=%u time_passed=%u "
			         "targets=%u fighter_valid=%u\n",
			         obs->game_status, obs->input_tick, obs->time_passed, obs->targets_remaining,
			         obs->fighter_valid);
			sCond.notify_all();
		}
		break;

	default:
		break;
	}
}

extern "C" int rlStepHostUpdate(void) {
	if (!sRegistered.load()) {
		return 0;
	}
	bool doExit = false;
	bool closed;
	{
		std::lock_guard<std::mutex> lock(sMutex);
		closed = gateClosedLocked();
		if (sExitRequested && !sExitPerformed) {
			sExitPerformed = true;
			doExit = true;
		}
		if (sTimingEnabled && !closed && (sState == RL_STEP_ACTION_READY || sState == RL_STEP_ACTION_CONSUMED)) {
			/* M4: an unparked iteration serving the in-flight step. The first
			 * one is the gate-open stamp (with the parked run that preceded it,
			 * read before it is reset below); the count makes a step that
			 * needed more than one host frame visible instead of looking like
			 * one slow frame. */
			if (sTimingInFlight.gate_open_ns == 0u) {
				sTimingInFlight.gate_open_ns = nowNs();
				sTimingInFlight.parked_iterations = sParkedRun;
			}
			sTimingInFlight.host_iterations++;
		}
		if (closed) {
			sParkedRun++;
		} else if (sParkedRun != 0u) {
			if (sParkedRun >= 30u) {
				port_log("SSB64 RL Step: resumed after %u parked host iterations\n", sParkedRun);
			}
			sParkedRun = 0;
		}
	}
	if (doExit) {
		if (requestCleanExit()) {
			port_log("SSB64 RL Step: deferred clean exit requested after the final step result was collected\n");
		} else {
			port_log("SSB64 RL Step: ERROR: deferred exit requested but no window available to close\n");
		}
	}
	return closed ? 1 : 0;
}

extern "C" int rlStepHostGateClosed(void) {
	if (!sRegistered.load()) {
		return 0;
	}
	std::lock_guard<std::mutex> lock(sMutex);
	return gateClosedLocked() ? 1 : 0;
}

/* M6 no-render mode: the parked host iteration has nothing to present, so
 * instead of spinning it sleeps on the M1c condition variable until the gate
 * can open (rlStepSubmit notifies), a deferred exit is pending (pollLocked
 * notifies after recording it) or shutdown began (rlRuntimeShutdown
 * notifies), bounded by timeout_ms so the caller keeps pumping window events.
 * The game coroutine is a fiber on this thread and cannot run while the gate
 * is closed anyway, so nothing game-owned can be waiting on the main thread
 * here. No state is changed. */
extern "C" int rlStepHostWaitParked(unsigned int timeout_ms) {
	if (!sRegistered.load()) {
		return 0;
	}
	std::unique_lock<std::mutex> lock(sMutex);
	auto wakeup = []() { return !gateClosedLocked() || (sExitRequested && !sExitPerformed) || sStopRequested; };
	if (!wakeup()) {
		sCond.wait_for(lock, std::chrono::milliseconds(timeout_ms), wakeup);
	}
	return gateClosedLocked() ? 1 : 0;
}

/* -- M4 timing diagnostic ---------------------------------------------------- */

extern "C" void rlStepNoteFrameLogicDone(void) {
	if (!sRegistered.load() || !sTimingEnabled) {
		return;
	}
	std::lock_guard<std::mutex> lock(sMutex);
	/* Only the iteration whose read consumed the action reaches this point in
	 * ActionConsumed; the first such iteration is the one that ran the game
	 * update of the tick. A later multi-iteration frame leaves it alone. */
	if (sState == RL_STEP_ACTION_CONSUMED && sTimingInFlight.logic_done_ns == 0u) {
		sTimingInFlight.logic_done_ns = nowNs();
	}
}

extern "C" int rlStepGetLastTiming(RLStepTiming *out) {
	if (out == nullptr) {
		return 0;
	}
	std::lock_guard<std::mutex> lock(sMutex);
	if (!sTimingEnabled || !sHasTimingLast) {
		return 0;
	}
	*out = sTimingLast;
	return 1;
}

extern "C" void rlRuntimeShutdown(void) {
	if (!sRegistered.load()) {
		return;
	}
	{
		std::lock_guard<std::mutex> lock(sMutex);
		sStopRequested = true;
		if (sState != RL_STEP_OBSERVATION_READY) {
			sState = RL_STEP_STOPPING;
		}
		port_log("SSB64 RL Step: shutdown state=%s steps=%u\n", stateName(sState), sStepCount);
		sCond.notify_all();
	}
}

extern "C" void rlStepRegister(void) {
	sMainThread = std::this_thread::get_id();
	if (!rlStepIsEnabled()) {
		port_log("SSB64 RL Step: interactive stepping disabled\n");
		return;
	}
	{
		std::lock_guard<std::mutex> lock(sMutex);
		sState = RL_STEP_INACTIVE;
		sTimingEnabled = rlTimingIsEnabled() != 0; /* M4 diagnostic, opt-in */
	}
	sRegistered.store(true);
	port_log("SSB64 RL Step: interactive stepping enabled schema=%u exit_on_end=%d timing=%d\n",
	         (unsigned)RL_STEP_SCHEMA, rlStepExitOnEnd(), sTimingEnabled ? 1 : 0);
}
