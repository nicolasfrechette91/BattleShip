#ifndef PORT_RL_H
#define PORT_RL_H

/*
 * rl.h -- BattleShip reinforcement-learning foundation (M1a).
 *
 * C-compatible on purpose: the decomp (scmanager.c) and the port C++ both
 * include it. Only builtin types appear here -- the decomp's shim headers
 * shadow <stddef.h>/<stdint.h>, and the port C++ must not include decomp
 * headers.
 *
 * M1a scope: boot straight into Mario's Break the Targets, write one JSON
 * result when the stage is cleared, optionally exit cleanly afterwards.
 * Everything is off unless SSB64_RL_BTT=1. The configuration is parsed once,
 * by rlConfigInit(), and cached; nothing else in port/rl reads the
 * environment.
 *
 *   SSB64_RL_BTT=1            enable the RL Mario BTT episode
 *   SSB64_RL_RESULT_PATH=<f>  where the result JSON is written
 *   SSB64_RL_EXIT_ON_END=1    request a clean exit after the result is
 *                             written successfully
 *
 * Input comes from the existing SSB64_BTT_INPUT text replay; the save file
 * is isolated with the existing SSB64_SAVE_PATH override. Neither is handled
 * here.
 */

#ifdef __cplusplus
extern "C" {
#endif

/* Facts only the decomp can state reliably, captured by rlBootApply() from the
 * real decomp types and consumed by the episode monitor (rl_result.cpp).
 * The port never mirrors decomp struct layouts. */
typedef struct RLGameFacts
{
	const unsigned char *scene_curr;          /* &gSCManagerSceneData.scene_curr */
	unsigned char scene_bonus_stage;          /* nSCKind1PBonusStage */
	const unsigned char *bonus1_target_count; /* &gGRCommonStruct.bonus1.target_count */
	const void *battle_state_ref;             /* &gSCManagerBattleState (an SCBattleState **) */
	unsigned int battle_time_passed_offset;   /* byte offset of SCBattleState::time_passed */

} RLGameFacts;

/* Parse and cache the RL environment configuration. Must run before
 * PortGameInit(): scManagerRunLoop() consults the cached result. */
void rlConfigInit(void);

/* Boot hook, called by scManagerRunLoop() after its own scene setup.
 * With RL disabled, or once the override has already been applied, it does
 * nothing and returns 0. Otherwise it explicitly selects Mario / BTT /
 * player 0 / costume 0 in the scene handoff so the game dispatches straight
 * into Mario BTT, records the facts the monitor needs, latches (one episode
 * per process; never reset) and returns non-zero. Depends only on the cached
 * configuration, so it is safe whenever scene selection runs relative to
 * PortGameInit(). */
int rlBootApply(unsigned char *scene_curr, unsigned char *scene_prev, unsigned char *player,
                unsigned char *bonus_fkind, unsigned char *bonus_costume, unsigned char scene_bonus_stage,
                unsigned char scene_bonus1_players, unsigned char fkind_mario, const unsigned char *bonus1_target_count,
                const void *battle_state_ref, unsigned int battle_time_passed_offset);

/* Register the per-frame episode monitor. Must run after PortGameInit(). */
void rlRuntimeRegister(void);

/* -- Internal seams between rl_boot.cpp and rl_result.cpp ------------------ */

int rlIsEnabled(void);
const char *rlResultPath(void); /* empty string when unset */
int rlExitOnEnd(void);
void rlResultBind(const RLGameFacts *facts);

#ifdef __cplusplus
}
#endif

#endif /* PORT_RL_H */
