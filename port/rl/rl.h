#ifndef PORT_RL_H
#define PORT_RL_H

/*
 * rl.h -- BattleShip reinforcement-learning foundation (M1a + M1b).
 *
 * C-compatible on purpose: the decomp (scmanager.c) and the port C++ both
 * include it. No decomp type ever appears here: the port C++ must not include
 * decomp headers, and nothing in port/ mirrors a decomp struct layout.
 *
 * <stdint.h> is safe from both sides and is the one header this file needs.
 * decomp/include holds shims for <stddef.h>/<stdlib.h>/<string.h>/... but
 * deliberately none for <stdint.h>, and ssb_types.h already pulls the real
 * <stdint.h> into every PORT decomp TU. The port C++ target does not have
 * decomp/include on its search path at all.
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
 * M1b scope: a passive, read-only observation snapshot (RLObservation),
 * captured once per GamePostUpdateEvent and handed out by value. M1b adds no
 * configuration, no action injection, no IPC and no rewards.
 *
 * Input comes from the existing SSB64_BTT_INPUT text replay; the save file
 * is isolated with the existing SSB64_SAVE_PATH override. Neither is handled
 * here.
 */

#include <stdint.h>

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

/* -- M1b: passive observation snapshot ------------------------------------- */

#define RL_OBSERVATION_SCHEMA 1u

/*
 * One coherent, read-only snapshot of the Mario BTT episode.
 *
 * Plain data, explicit widths, no pointers: nothing here refers to game-owned
 * memory, so a copy stays valid for as long as the caller keeps it. Native
 * narrow fields (game_status is u8, jumps_used is u8) are widened into stable
 * observation types; no compiler-dependent enum crosses this boundary.
 *
 * TIMING CONTRACT. The snapshot is captured once per GamePostUpdateEvent,
 * which port/gameloop.cpp fires after port_resume_service_threads() has run
 * that host update's controller read, game logic and display-list submission.
 * The fighter, battle and target state therefore reflect one *completed*
 * simulation update.
 *
 * The three clocks are sampled independently and keep their native meanings.
 * They are NOT normalised against each other and no equality between them may
 * be assumed:
 *
 *   host_frame  -- number of GamePostUpdateEvent callbacks observed since
 *                  rlObservationRegister(). Host-side diagnostic only. It is
 *                  not a game tick and can advance on host updates where the
 *                  game simulation did not advance at all.
 *   input_tick  -- syNetInputGetTick() verbatim. At this point in the frame
 *                  syNetInputFuncRead() has already published and consumed the
 *                  row for the update that just ran and then incremented the
 *                  counter, so this is the index of the NEXT controller frame.
 *                  It is deliberately one past the consumed row and is never
 *                  decremented or reinterpreted as a "current" input frame.
 *   time_passed -- SCBattleState::time_passed, the in-game match tic counter.
 *                  It advances only while the stage timer runs, so it stays 0
 *                  through the READY/GO wait.
 *
 * The validated scripted baseline clears with time_passed == 446 and
 * input_tick == 447 in the same snapshot. That difference is correct and must
 * survive.
 *
 * VALIDITY. btt_active is 1 only while the Break the Targets bonus-stage scene
 * is the current scene AND the battle-state pointer is non-NULL. The
 * bonus-stage target count lives in a union shared by every stage, so when
 * btt_active is 0 the BTT-specific fields (time_passed, game_status,
 * targets_remaining) are deterministic zeros and must NOT be read as live BTT
 * state. Likewise every fighter field is a deterministic zero unless
 * fighter_valid is 1; zero is never asserted to be a real gameplay value.
 */
typedef struct RLObservation
{
	uint32_t observation_schema; /* RL_OBSERVATION_SCHEMA */

	uint32_t host_frame;  /* GamePostUpdateEvent callbacks since registration (diagnostic) */
	uint32_t input_tick;  /* syNetInputGetTick(): index of the NEXT controller frame */
	uint32_t time_passed; /* SCBattleState::time_passed, in-game match tics */
	uint32_t game_status; /* SCBattleState::game_status, widened SCBattleGameStatus */

	uint32_t btt_active;        /* 1 = BTT scene current and battle state present */
	uint32_t targets_remaining; /* gGRCommonStruct.bonus1.target_count, counts 10 -> 0 */

	uint32_t fighter_valid; /* 1 = every field below is a real gameplay value */

	float position_x; /* fighter TopN translate x */
	float position_y; /* fighter TopN translate y */

	float air_velocity_x; /* FTStruct::physics.vel_air.x, native aerial self-induced velocity */
	float air_velocity_y; /* FTStruct::physics.vel_air.y, native aerial self-induced velocity */

	float ground_velocity_x; /* FTStruct::physics.vel_ground.x, native grounded self-induced
	                          * velocity. Not a total or effective velocity: knockback, jostle
	                          * and animation velocities are separate native fields and are not
	                          * folded in. Use ground_air_state to decide which of the native
	                          * velocity representations currently applies. */

	int32_t facing_direction;  /* FTStruct::lr: -1 left, 0 centre, +1 right */
	int32_t ground_air_state;  /* FTStruct::ga: 0 = ground, 1 = air (nMPKinetics*) */
	int32_t fighter_status_id; /* FTStruct::status_id, current action state id */

	uint32_t jumps_used; /* FTStruct::jumps_used, widened */

} RLObservation;

/* Fill the game-owned fields of *out from the real decomp types. Defined by
 * the decomp (scmanager.c, PORT only) because FTStruct / SCBattleState /
 * MPCollData must never be mirrored or offset-walked on the port side.
 *
 * Strictly read-only: it advances nothing, consumes no input, polls no
 * controller and mutates no game or battle state. The caller zero-initialises
 * *out first, so every early return leaves deterministic zeros with
 * btt_active / fighter_valid false. Handles out == NULL. It never writes the
 * port-owned fields (observation_schema, host_frame, input_tick) and never
 * exposes a game-owned pointer. */
void rlGameFillObservation(RLObservation *out);

/* Register the observation capture on GamePostUpdateEvent. Called by
 * rlRuntimeRegister(); no-op unless RL is enabled. */
void rlObservationRegister(void);

/* Copy the most recently captured snapshot into *out.
 *
 * Passive: it does not update the game, pump an event loop, poll a controller,
 * advance a replay cursor, tick the simulation or touch fighter / battle
 * state. Calling it repeatedly without an intervening game update returns the
 * same snapshot every time.
 *
 * Returns 0 if out is NULL, or if no snapshot has been captured yet (i.e.
 * before the first GamePostUpdateEvent), leaving *out untouched. Returns
 * non-zero once a snapshot exists and has been copied.
 *
 * The return value means ONLY "a snapshot exists". It says nothing about
 * whether BTT is active, whether the fighter is valid, whether an episode is
 * running or whether a result is available -- a snapshot taken outside the BTT
 * scene is still a perfectly valid snapshot. Read btt_active and
 * fighter_valid for those questions. */
int rlObservationGet(RLObservation *out);

#ifdef __cplusplus
}
#endif

#endif /* PORT_RL_H */
