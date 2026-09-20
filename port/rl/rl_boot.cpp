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
	bool exitOnEnd = false;
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
	sConfig.exitOnEnd = envIsOne("SSB64_RL_EXIT_ON_END");
	if (const char *resultPath = std::getenv("SSB64_RL_RESULT_PATH")) {
		sConfig.resultPath = resultPath;
	}

	port_log("SSB64 RL: enabled episode=btt_mario result=%s exit_on_end=%d\n",
	         sConfig.resultPath.empty() ? "<unset>" : sConfig.resultPath.c_str(), sConfig.exitOnEnd ? 1 : 0);
	if (sConfig.resultPath.empty()) {
		port_log("SSB64 RL: SSB64_RL_RESULT_PATH is not set; no result can be written\n");
	}
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
