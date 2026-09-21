/*
 * rl_boot.cpp -- cached RL configuration and direct boot into Mario BTT (M1a).
 *
 * rlConfigInit() is the single authority for RL configuration: it reads the
 * environment once and caches the result. Everything else (rlBootApply, the
 * episode monitor) consults the cache.
 *
 * The scene handoff structs belong to the decomp, so the boot writes go
 * through pointers the decomp passes in; nothing here mirrors a decomp layout.
 * unlock_mask / fighter_mask are never touched: Mario's BTT is reached by
 * setting the scene handoff directly, not by unlocking anything.
 */
#include "rl/rl.h"

#include "port_log.h"

#include <cstdlib>
#include <cstring>
#include <string>

namespace {

struct RLConfig {
	bool enabled = false;
	bool exitOnEnd = false;     /* M1a clean exit, performed by rl_result.cpp */
	bool step = false;          /* M1c interactive stepping (SSB64_RL_STEP=1) */
	bool stepExitOnEnd = false; /* SSB64_RL_EXIT_ON_END while stepping: deferred to rl_step.cpp */
	int transportPort = 0;      /* M1d loopback TCP port (SSB64_RL_PORT), 0 = no transport */
	bool timing = false;        /* M4 stepping timing diagnostic (SSB64_RL_TIMING=1), measurement only */
	bool noRender = false;      /* M6 training no-render mode (SSB64_RL_NO_RENDER=1), host-side only */
	std::string resultPath;
};

RLConfig sConfig;

/* Deliberately outside RLConfig so rlConfigInit() can never reset it: M1a runs
 * one episode per process, and later scene selections must not be overridden. */
bool sBootApplied = false;

bool envIsOne(const char *name) {
	const char *env = std::getenv(name);
	return env != nullptr && std::strcmp(env, "1") == 0;
}

} // namespace

extern "C" void rlConfigInit(void) {
	sConfig = RLConfig{};

	if (!envIsOne("SSB64_RL_BTT")) {
		return;
	}
	sConfig.enabled = true;
	const bool exitOnEndEnv = envIsOne("SSB64_RL_EXIT_ON_END");
	const bool stepEnv = envIsOne("SSB64_RL_STEP");
	const bool replayConfigured = std::getenv("SSB64_BTT_INPUT") != nullptr;

	/* M1c precedence rule: a configured replay owns player 0, so interactive
	 * stepping never activates beside it and the replay path stays untouched. */
	sConfig.step = stepEnv && !replayConfigured;

	/* M1c compatibility rule for the M1a exit: while stepping, the final step
	 * result must stay collectable, so the exit is not performed by the M1a
	 * monitor but by rl_step.cpp on the main thread after collection. With
	 * stepping disabled the M1a behaviour is exactly as before. */
	sConfig.exitOnEnd = exitOnEndEnv && !sConfig.step;
	sConfig.stepExitOnEnd = exitOnEndEnv && sConfig.step;

	/* M4 timing diagnostic: stamps exist only for interactive steps, so the
	 * flag is meaningless (and ignored) without effective stepping. */
	sConfig.timing = envIsOne("SSB64_RL_TIMING") && sConfig.step;

	/* M6 no-render mode: a host-side throughput mode for process-backed
	 * stepping only. Without effective stepping there is no caller to pace
	 * against, so the flag is ignored (and said so below) and the ordinary
	 * visual path, replay included, is untouched. */
	const bool noRenderEnv = envIsOne("SSB64_RL_NO_RENDER");
	sConfig.noRender = noRenderEnv && sConfig.step;
	if (const char *resultPath = std::getenv("SSB64_RL_RESULT_PATH")) {
		sConfig.resultPath = resultPath;
	}

	/* M1d transport: only meaningful with effective interactive stepping, and
	 * only a strict decimal 1..65535 is accepted. Anything else leaves the
	 * transport off (no socket, no thread) and says so in the log. */
	const char *portEnv = std::getenv("SSB64_RL_PORT");
	if (portEnv != nullptr && portEnv[0] != '\0') {
		char *end = nullptr;
		const long value = std::strtol(portEnv, &end, 10);
		const bool numeric = end != nullptr && end != portEnv && *end == '\0';
		if (!numeric || value < 1 || value > 65535) {
			port_log("SSB64 RL Transport: SSB64_RL_PORT=%s is not a port in 1..65535; transport disabled\n",
			         portEnv);
		} else if (!sConfig.step) {
			port_log("SSB64 RL Transport: SSB64_RL_PORT set but interactive stepping is not effective; "
			         "transport disabled\n");
		} else {
			sConfig.transportPort = (int)value;
		}
	}

	port_log("SSB64 RL: enabled episode=btt_mario result=%s exit_on_end=%d step=%d transport_port=%d no_render=%d\n",
	         sConfig.resultPath.empty() ? "<unset>" : sConfig.resultPath.c_str(), exitOnEndEnv ? 1 : 0,
	         sConfig.step ? 1 : 0, sConfig.transportPort, sConfig.noRender ? 1 : 0);
	if (sConfig.resultPath.empty()) {
		port_log("SSB64 RL: SSB64_RL_RESULT_PATH is not set; no result can be written\n");
	}
	if (stepEnv && replayConfigured) {
		port_log("SSB64 RL Step: SSB64_BTT_INPUT is set; the replay keeps precedence and interactive stepping "
		         "is disabled\n");
	}
	if (sConfig.stepExitOnEnd) {
		port_log("SSB64 RL Step: SSB64_RL_EXIT_ON_END deferred until the final step result is collected\n");
	}
	if (sConfig.timing) {
		port_log("SSB64 RL Timing: step timing diagnostic enabled schema=%u (stamps only; no behaviour change)\n",
		         (unsigned)RL_TIMING_SCHEMA);
	}
	if (noRenderEnv && !sConfig.step) {
		port_log("SSB64 RL NoRender: SSB64_RL_NO_RENDER=1 ignored: interactive stepping is not effective; "
		         "normal rendering and presentation kept\n");
	} else if (sConfig.noRender) {
		port_log("SSB64 RL NoRender: training no-render mode enabled: display lists discarded, no presents, "
		         "no presentation pacing, parked host waits on the step condition variable\n");
	}
}

extern "C" int rlNoRenderIsEnabled(void) {
	return sConfig.noRender ? 1 : 0;
}

extern "C" int rlTimingIsEnabled(void) {
	return sConfig.timing ? 1 : 0;
}

extern "C" int rlStepIsEnabled(void) {
	return sConfig.step ? 1 : 0;
}

extern "C" int rlStepExitOnEnd(void) {
	return sConfig.stepExitOnEnd ? 1 : 0;
}

extern "C" int rlTransportPort(void) {
	return sConfig.transportPort;
}

extern "C" int rlIsEnabled(void) {
	return sConfig.enabled ? 1 : 0;
}

extern "C" const char *rlResultPath(void) {
	return sConfig.resultPath.c_str();
}

extern "C" int rlExitOnEnd(void) {
	return sConfig.exitOnEnd ? 1 : 0;
}

extern "C" int rlBootApply(unsigned char *scene_curr, unsigned char *scene_prev, unsigned char *player,
                           unsigned char *bonus_fkind, unsigned char *bonus_costume,
                           unsigned char scene_bonus_stage, unsigned char scene_bonus1_players,
                           unsigned char fkind_mario, const unsigned char *bonus1_target_count,
                           const void *battle_state_ref, unsigned int battle_time_passed_offset) {
	if (!sConfig.enabled || sBootApplied) {
		return 0;
	}
	sBootApplied = true;

	/* Same handoff the Bonus-1 character select performs before it loads the
	 * bonus stage: scene_prev selects BTT (vs BTP), bonus_fkind picks Mario's
	 * map, and player / bonus_costume are selected explicitly (port 0,
	 * costume 0) rather than inherited from the default scene data. */
	*scene_prev = scene_bonus1_players;
	*scene_curr = scene_bonus_stage;
	*player = 0;
	*bonus_fkind = fkind_mario;
	*bonus_costume = 0;

	RLGameFacts facts;
	facts.scene_curr = scene_curr;
	facts.scene_bonus_stage = scene_bonus_stage;
	facts.bonus1_target_count = bonus1_target_count;
	facts.battle_state_ref = battle_state_ref;
	facts.battle_time_passed_offset = battle_time_passed_offset;
	rlResultBind(&facts);

	port_log("SSB64 RL: boot override -> scene=%d prev=%d player=%d fkind=%d costume=%d\n",
	         (int)*scene_curr, (int)*scene_prev, (int)*player, (int)*bonus_fkind, (int)*bonus_costume);
	return 1;
}
