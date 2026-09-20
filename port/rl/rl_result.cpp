/*
 * rl_result.cpp -- per-frame episode monitor and one-shot JSON result (M1a).
 *
 * The monitor runs on GamePostUpdateEvent, once per host frame, after that
 * frame's game logic has settled. On the first frame in which the Mario BTT
 * stage reports zero remaining targets it writes the result and, if
 * configured, requests a clean exit. Native M1a reports game facts only: a
 * run that never clears writes nothing.
 *
 * Two clocks are reported and never conflated:
 *   completion_time_passed -- SCBattleState::time_passed, the in-game stage
 *                             timer (446 for the scripted baseline)
 *   completion_input_tick  -- syNetInputGetTick(), the controller input
 *                             cursor, reported as-is (447 for the baseline)
 * Both are sampled in the same observation as the target count reaching
 * zero, so the *_final fields equal the completion_* fields.
 */
#include "rl/rl.h"

#include "hooks/Events.h"
#include "port_log.h"

#include <libultraship/libultraship.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <system_error>

extern "C" uint32_t syNetInputGetTick(void);

namespace {

RLGameFacts sFacts;
bool sBound = false;

bool sStageReady = false; // target_count seen non-zero, i.e. the stage initialised it
unsigned int sTargetsTotal = 0;
bool sResultLatched = false; // set on the single write attempt, success or not
uint32_t sHostFrames = 0;

uint32_t readTimePassed() {
	/* battle_state_ref is &gSCManagerBattleState, a decomp pointer object of a
	 * different pointer type; copy its bytes rather than dereferencing it
	 * through an incompatible type. */
	const unsigned char *state = nullptr;
	std::memcpy(&state, sFacts.battle_state_ref, sizeof(state));
	if (state == nullptr) {
		return 0;
	}
	uint32_t value = 0;
	std::memcpy(&value, state + sFacts.battle_time_passed_offset, sizeof(value));
	return value;
}

/* Writes contents to path.tmp, closes it, then renames it over path, so a
 * reader never sees a partial file. Returns true only if every step worked. */
bool writeFileAtomically(const std::string &path, const std::string &contents) {
	namespace fs = std::filesystem;
	if (path.empty()) {
		return false;
	}

	std::error_code ec;
	const fs::path finalPath(path);
	if (finalPath.has_parent_path()) {
		fs::create_directories(finalPath.parent_path(), ec);
	}
	fs::path tmpPath = finalPath;
	tmpPath += ".tmp";

	std::ofstream out(tmpPath, std::ios::binary | std::ios::trunc);
	if (!out) {
		return false;
	}
	out << contents;
	out.flush();
	out.close();
	if (out.fail()) {
		fs::remove(tmpPath, ec);
		return false;
	}

	fs::rename(tmpPath, finalPath, ec);
	if (ec) {
		fs::remove(tmpPath, ec);
		return false;
	}
	return true;
}

/* Existing clean-shutdown path: Window::Close() clears the running flag and the
 * main loop in port.cpp exits, exactly as the SSB64_MAX_FRAMES debug aid does. */
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

void writeClearResult(uint32_t timePassed, uint32_t inputCursor) {
	std::ostringstream json;
	json << "{\n";
	json << "  \"result_schema\": 1,\n";
	json << "  \"outcome\": \"clear\",\n";
	json << "  \"targets_broken\": " << sTargetsTotal << ",\n";
	json << "  \"completion_time_passed\": " << timePassed << ",\n";
	json << "  \"completion_input_tick\": " << inputCursor << ",\n";
	json << "  \"time_passed_final\": " << timePassed << ",\n";
	json << "  \"input_cursor_final\": " << inputCursor << ",\n";
	json << "  \"host_frames\": " << sHostFrames << "\n";
	json << "}\n";

	const char *path = rlResultPath();
	if (!writeFileAtomically(path, json.str())) {
		/* No valid result exists, so do not exit as though one did. */
		port_log("SSB64 RL: ERROR: failed to write result path=%s; not exiting\n",
		         path[0] != '\0' ? path : "<unset>");
		std::fprintf(stderr, "SSB64 RL: failed to write result path=%s\n", path[0] != '\0' ? path : "<unset>");
		return;
	}

	port_log("SSB64 RL: result written path=%s outcome=clear targets_broken=%u time_passed=%u "
	         "input_cursor=%u host_frames=%u\n",
	         path, sTargetsTotal, timePassed, inputCursor, sHostFrames);

	if (rlExitOnEnd()) {
		if (requestCleanExit()) {
			port_log("SSB64 RL: clean exit requested\n");
		} else {
			port_log("SSB64 RL: ERROR: result written but no window available to close\n");
		}
	}
}

void OnGamePostUpdate(IEvent *) {
	sHostFrames++;
	if (sResultLatched || !sBound) {
		return;
	}
	/* gGRCommonStruct is a union shared by every stage, so only trust it while
	 * the bonus stage scene is the one running. */
	if (*sFacts.scene_curr != sFacts.scene_bonus_stage) {
		return;
	}

	const unsigned int targetsRemaining = *sFacts.bonus1_target_count;
	if (!sStageReady) {
		if (targetsRemaining == 0) {
			return; // stage has not initialised its target count yet
		}
		sStageReady = true;
		sTargetsTotal = targetsRemaining;
		port_log("SSB64 RL: stage ready targets=%u\n", sTargetsTotal);
	}
	if (targetsRemaining != 0) {
		return;
	}

	/* Cleared. Exactly one write attempt is ever made: the latch is set before
	 * the attempt, so a failure is never retried with later-frame values. */
	sResultLatched = true;
	writeClearResult(readTimePassed(), syNetInputGetTick());
}

} // namespace

extern "C" void rlResultBind(const RLGameFacts *facts) {
	sFacts = *facts;
	sBound = true;
}

extern "C" void rlRuntimeRegister(void) {
	if (!rlIsEnabled()) {
		return;
	}
	REGISTER_LISTENER(GamePostUpdateEvent, EVENT_PRIORITY_NORMAL, OnGamePostUpdate);
	port_log("SSB64 RL: episode monitor registered\n");
	/* M1b observation capture. Read-only and independent of the monitor above,
	 * so the relative dispatch order of the two listeners does not matter. */
	rlObservationRegister();
	/* M1c interactive stepping. Registers no listener of its own: it is fed
	 * by the M1b capture and by the PortPushFrame() hook. No-op unless
	 * SSB64_RL_STEP=1. */
	rlStepRegister();
}
