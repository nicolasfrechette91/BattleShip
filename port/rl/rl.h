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
 * M1c scope: an interactive one-action / one-tick native stepping primitive
 * (RLAction, RLStepResult, rlStep*). Opt-in, native API only, no transport:
 *
 *   SSB64_RL_STEP=1           enable interactive stepping. Requires
 *                             SSB64_RL_BTT=1. Ignored, with a log line, when
 *                             SSB64_BTT_INPUT is set: the replay keeps
 *                             precedence for player 0 and is left untouched.
 *
 * M1d scope: an opt-in, single-client, loopback-only TCP transport
 * (rl_transport.cpp) that lets an external process (the Python client in
 * rl/battleship_client.py) call the M1c primitive. Newline-delimited JSON,
 * protocol version RL_PROTOCOL_VERSION. No reset, no rewards, no launcher:
 *
 *   SSB64_RL_PORT=<1..65535>  listen on 127.0.0.1:<port>. Requires effective
 *                             interactive stepping (SSB64_RL_STEP=1 and no
 *                             SSB64_BTT_INPUT); otherwise ignored with a log
 *                             line. Unset: no socket, no thread, nothing.
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

/* -- M1c: interactive one-action / one-tick native stepping ---------------- */

#define RL_STEP_SCHEMA 1u

/*
 * Native N64 controller button bits, restated from decomp/include/PR/os.h
 * (CONT_A .. CONT_F) because the port C++ cannot include decomp headers.
 * decomp/src/sc/sc1pmode/sc1pbonusstage.c cross-checks every value against
 * A_BUTTON, B_BUTTON, ... at compile time, so they cannot silently diverge.
 */
#define RL_BUTTON_A          0x8000u /* CONT_A */
#define RL_BUTTON_B          0x4000u /* CONT_B */
#define RL_BUTTON_Z          0x2000u /* CONT_G */
#define RL_BUTTON_START      0x1000u /* CONT_START -- always rejected */
#define RL_BUTTON_DPAD_UP    0x0800u /* CONT_UP    -- always rejected */
#define RL_BUTTON_DPAD_DOWN  0x0400u /* CONT_DOWN  -- always rejected */
#define RL_BUTTON_DPAD_LEFT  0x0200u /* CONT_LEFT  -- always rejected */
#define RL_BUTTON_DPAD_RIGHT 0x0100u /* CONT_RIGHT -- always rejected */
#define RL_BUTTON_L          0x0020u /* CONT_L */
#define RL_BUTTON_R          0x0010u /* CONT_R */
#define RL_BUTTON_C_UP       0x0008u /* CONT_E */
#define RL_BUTTON_C_DOWN     0x0004u /* CONT_D */
#define RL_BUTTON_C_LEFT     0x0002u /* CONT_C */
#define RL_BUTTON_C_RIGHT    0x0001u /* CONT_F */

/* The only bits a submitted action may carry, and at most one of them at a
 * time. 0x00C0 has no native definition and is rejected as unknown. */
#define RL_BUTTONS_PERMITTED                                                                               \
	(RL_BUTTON_A | RL_BUTTON_B | RL_BUTTON_Z | RL_BUTTON_L | RL_BUTTON_R | RL_BUTTON_C_UP | RL_BUTTON_C_DOWN | \
	 RL_BUTTON_C_LEFT | RL_BUTTON_C_RIGHT)

/* SCBattleGameStatus values used by the activation predicate below, restated
 * from decomp/src/sc/scdef.h and cross-checked there at compile time. */
#define RL_GAME_STATUS_WAIT  0u
#define RL_GAME_STATUS_GO    1u
#define RL_GAME_STATUS_PAUSE 2u

/*
 * One raw player-0 controller frame, in the exact native representation the
 * netinput pipeline publishes (SYNetInputFrame.buttons / stick_x / stick_y,
 * i.e. SYController.button_hold and stick_range): the N64 button word and the
 * raw signed 8-bit stick axes. No transform, no discretisation: any value in
 * the int8_t range is passed through verbatim, which is the same rule the
 * text replay parser applies (-128..127).
 *
 * VALIDITY (rlStepValidateAction): buttons must be 0 or exactly one bit of
 * RL_BUTTONS_PERMITTED. Start, the D-pad, undefined bits and any multi-button
 * word are rejected and never enter the stepping path.
 */
typedef struct RLAction
{
	uint16_t buttons; /* N64 button word, see RL_BUTTON_* */
	int8_t stick_x;   /* raw analog x, native s8 */
	int8_t stick_y;   /* raw analog y, native s8 */

} RLAction;

/*
 * The stepping state machine. One variable, owned by rl_step.cpp under one
 * mutex. Transitions:
 *
 *   Disabled           SSB64_RL_STEP unset, RL off, or a replay is configured.
 *                      Terminal.
 *   Inactive           enabled; BTT has not yet reached its first
 *                      input-consuming update (boot, READY/GO). The host runs
 *                      free. -> WaitingForAction on the main thread, at the
 *                      GamePostUpdateEvent whose snapshot first shows
 *                      btt_active with game_status neither Wait nor Pause:
 *                      that is the update right before native tick 0, the same
 *                      boundary at which the validated replay consumes row 0.
 *   WaitingForAction   HOST GATE CLOSED. Nothing game-visible runs.
 *                      -> ActionReady on rlStepSubmit().
 *   ActionReady        gate open; the next host iteration runs one full normal
 *                      frame. -> ActionConsumed on the game coroutine when the
 *                      BTT controller read takes the action for tick T.
 *   ActionConsumed     gate open until the update completes.
 *                      -> ObservationReady at the GamePostUpdateEvent whose
 *                      snapshot reports input_tick == T + 1.
 *   ObservationReady   HOST GATE CLOSED. -> WaitingForAction, EpisodeEnded or
 *                      Stopping when the caller collects the result.
 *   EpisodeEnded       HOST GATE CLOSED until shutdown. Entered when the
 *                      collected result shows targets_remaining == 0. No
 *                      further gameplay tick runs. Terminal for M1c.
 *   Stopping           shutdown began. Terminal. An uncollected result is still
 *                      returned once by rlStepPoll / rlStepWait.
 *
 * While the gate is closed PortPushFrame() only pumps window events and
 * re-presents the last framebuffer: no VRETRACE is posted and no coroutine is
 * resumed, so sySchedulerGetTicCount(), time_passed, the netinput tick,
 * fighter state and target state cannot change however long the caller waits.
 */
typedef enum RLStepState
{
	RL_STEP_DISABLED = 0,
	RL_STEP_INACTIVE,
	RL_STEP_WAITING_FOR_ACTION,
	RL_STEP_ACTION_READY,
	RL_STEP_ACTION_CONSUMED,
	RL_STEP_OBSERVATION_READY,
	RL_STEP_EPISODE_ENDED,
	RL_STEP_STOPPING

} RLStepState;

/*
 * Result of one step, handed out by value. For RL_STEP_OK the observation is
 * the M1b snapshot captured at the GamePostUpdateEvent of the update that
 * consumed the action, and observation.input_tick == consumed_tick + 1 by
 * construction. For RL_STEP_READY (parked, no result) the observation is the
 * latest snapshot, i.e. the state the next action will act upon. time_passed
 * is reported verbatim and is not asserted against any other clock: the first
 * BTT action starts the timer and leaves time_passed at 0.
 */
typedef struct RLStepResult
{
	uint32_t step_schema;   /* RL_STEP_SCHEMA */
	uint32_t state;         /* RLStepState after the call returned */
	uint32_t step_count;    /* steps completed so far (this one included for RL_STEP_OK) */
	uint32_t consumed_tick; /* RL_STEP_OK only: native input tick T the action was consumed at */

	RLObservation observation;

} RLStepResult;

/* Return codes shared by the rlStep* calls. */
#define RL_STEP_OK                0  /* result collected into *out */
#define RL_STEP_READY             1  /* parked, waiting for an action; *out holds the latest snapshot */
#define RL_STEP_PENDING           2  /* rlStepPoll only: nothing to collect yet */
#define RL_STEP_ERR_NULL          (-1)
#define RL_STEP_ERR_DISABLED      (-2)
#define RL_STEP_ERR_INVALID_ACTION (-3) /* rlStepValidateAction failed; nothing changed */
#define RL_STEP_ERR_NOT_READY     (-4) /* Inactive: BTT has not reached its first input tick */
#define RL_STEP_ERR_BUSY          (-5) /* an action is in flight or a result is uncollected */
#define RL_STEP_ERR_EPISODE_ENDED (-6)
#define RL_STEP_ERR_STOPPING      (-7)
#define RL_STEP_ERR_MAIN_THREAD   (-8) /* rlStepWait must not be called on the main thread */

/* Pure validation of the raw-frame rule above. Never touches the state. */
int rlStepValidateAction(const RLAction *action);

/* Submit exactly one action. Accepted only in WaitingForAction, so no pending
 * action can ever be overwritten and no action is consumed twice. Any thread. */
int rlStepSubmit(const RLAction *action);

/* Non-blocking. RL_STEP_OK collects the pending result (exactly once),
 * RL_STEP_READY reports the parked state with the latest snapshot,
 * RL_STEP_PENDING means the step is in flight or BTT is not there yet. Any
 * thread; out->state is always filled. */
int rlStepPoll(RLStepResult *out);

/* rlStepPoll that blocks while the answer would be RL_STEP_PENDING. Must be
 * called from a thread other than the main thread (which has to keep pumping
 * PortPushFrame), otherwise it returns RL_STEP_ERR_MAIN_THREAD. Returns
 * RL_STEP_ERR_STOPPING when shutdown begins. */
int rlStepWait(RLStepResult *out);

/* Current RLStepState. Any thread. */
int rlStepGetState(void);

/* Copy the newest M1b snapshot this module has been handed (the same copy
 * rlStepPoll reports for RL_STEP_READY) into *out. Pure query under the M1c
 * mutex, any thread: it reads the state machine's cached snapshot only and
 * never changes the state, collects a result, opens the host gate, submits
 * an action or touches the game. Returns 1 when a snapshot exists and was
 * copied, 0 when none has been captured yet (or out is NULL); *out is left
 * untouched in that case.
 *
 * Meaning of the copy depends on the state and is for the caller to judge:
 * in WaitingForAction it is the state the next action will act upon (at
 * step_count 0: the post-update of the update that set Go, i.e. the state
 * before native tick 0); in EpisodeEnded it is the terminal snapshot of the
 * last collected result. Added for M3 so a fresh episode's initial
 * observation can be read without consuming tick 0. */
int rlStepGetLatestObservation(RLObservation *out);

/* -- M1c decomp-facing call-outs (sc1pbonusstage.c, PORT only) ------------- */

/* 1 when interactive stepping is enabled by configuration. */
int rlStepIsEnabled(void);

/* Called by the BTT controller callback, on the game coroutine, at a read
 * that would consume native input tick `tick`. Returns 1 and fills the action
 * to stage for that tick when one is ActionReady; returns 0 when stepping does
 * not apply to this read (Disabled, EpisodeEnded, Stopping) so the caller
 * falls back to its stock read. Never blocks the main thread. */
int rlStepControllerRead(uint32_t tick, uint16_t *buttons, int8_t *stick_x, int8_t *stick_y);

/* -- M1c host-facing hooks (gameloop.cpp / port.cpp) ----------------------- */

/* Main-thread lifecycle hook, called once at the top of PortPushFrame().
 * Performs the deferred SSB64_RL_EXIT_ON_END clean-exit request when the
 * final result has been collected, then returns rlStepHostGateClosed(). */
int rlStepHostUpdate(void);

/* Pure query: 1 while another game update is forbidden (WaitingForAction,
 * ObservationReady, EpisodeEnded). 0 whenever stepping is disabled. */
int rlStepHostGateClosed(void);

/* Called by main() right after the main loop exits: moves the state machine
 * to Stopping (keeping an uncollected result collectable once) and wakes any
 * blocked rlStepWait() caller so shutdown cannot deadlock on it. */
void rlRuntimeShutdown(void);

/* -- M1d: external transport (loopback TCP, newline-delimited JSON) -------- */

/*
 * Wire protocol version. Every request and every response carries
 * "protocol": RL_PROTOCOL_VERSION. The transport is plumbing only: it maps
 * three operations (ping, status, step) onto rlStepPoll / rlStepSubmit /
 * rlStepWait and serialises RLStepResult / RLObservation field-for-field.
 * It never derives, rewrites or normalises a native field, never touches
 * game memory and never advances the game by itself; M1c stays the single
 * authority for validation, one-action/one-tick pairing and host gating.
 */
#define RL_PROTOCOL_VERSION 1u

/* Loopback TCP port from SSB64_RL_PORT; 0 when the transport is disabled
 * (unset, invalid, or interactive stepping not effective). */
int rlTransportPort(void);

/* Bind 127.0.0.1:rlTransportPort() and start the one transport worker
 * thread. Called by rlRuntimeRegister() on the main thread; no-op when
 * rlTransportPort() == 0. A bind failure is logged and leaves the game
 * running without a transport. */
void rlTransportStart(void);

/* Stop accepting, unblock the worker, join it and release the sockets.
 * Called by main() right after rlRuntimeShutdown(), which is what releases a
 * worker blocked in rlStepWait(). No-op when the transport never started. */
void rlTransportShutdown(void);

/* -- M4: opt-in stepping timing diagnostic (measurement only) -------------- */

/*
 *   SSB64_RL_TIMING=1         record steady-clock stamps for every step and
 *                             report them in the step response ("timing"
 *                             object, additive to protocol 1). Requires
 *                             effective interactive stepping; otherwise
 *                             ignored. Unset: nothing is stamped and every
 *                             response is byte-identical to a build without
 *                             this diagnostic.
 *
 * The stamps are std::chrono::steady_clock readings in nanoseconds taken
 * inside the game process. Only differences between them are meaningful; a
 * zero means "this stamp was not taken for this step". They are recorded
 * inside the existing M1c locked regions, feed back into no transition, and
 * touch neither the observation nor the result. What each interval contains
 * is documented in docs/rl_measurements_m4.md; in particular
 * consumed_ns -> logic_done_ns is the game update of the tick without any
 * rendering, and logic_done_ns -> observation_ns is the display-list render
 * plus the paced present.
 */
#define RL_TIMING_SCHEMA 1u

typedef struct RLStepTiming
{
	uint32_t timing_schema; /* RL_TIMING_SCHEMA */
	uint32_t step_count;    /* the step these stamps belong to */

	uint64_t submit_ns;      /* rlStepSubmit accepted the action (submitting thread) */
	uint64_t gate_open_ns;   /* first PortPushFrame entry that ran a frame for this step (main thread) */
	uint64_t consumed_ns;    /* rlStepControllerRead handed the action to the BTT read (game coroutine) */
	uint64_t logic_done_ns;  /* PortPushFrame: game logic of that update complete, display list not yet
	                          * drained (main thread, rlStepNoteFrameLogicDone) */
	uint64_t observation_ns; /* rlStepOnObservation paired the result (main thread, after render + present) */
	uint64_t collected_ns;   /* rlStepPoll / rlStepWait handed the result to the collector */

	uint32_t host_iterations;   /* unparked PortPushFrame entries that served this step (1 normally) */
	uint32_t parked_iterations; /* parked host iterations immediately before the gate-open iteration */

} RLStepTiming;

/* 1 when SSB64_RL_TIMING=1 and interactive stepping is effective (rl_boot.cpp). */
int rlTimingIsEnabled(void);

/* Copy the stamps of the most recently collected step into *out. Pure query
 * under the M1c mutex, any thread. Returns 1 when the diagnostic is enabled
 * and a step has been collected, 0 otherwise (*out untouched). */
int rlStepGetLastTiming(RLStepTiming *out);

/* Main-thread hook, called by PortPushFrame() after port_resume_service_threads()
 * and before port_drain_pending_display_list(). Records logic_done_ns for the
 * in-flight step. No-op unless stepping is registered and the diagnostic is
 * enabled; never changes state. */
void rlStepNoteFrameLogicDone(void);

/* -- M6: opt-in training no-render mode (throughput only) ------------------ */

/*
 *   SSB64_RL_NO_RENDER=1      training-only host mode: while interactive
 *                             stepping is effective, PortPushFrame() discards
 *                             the staged display list instead of rendering
 *                             it, never presents a swap-chain image (neither
 *                             the frame present nor the parked idle present)
 *                             and therefore never runs the backend's
 *                             presentation pacing; a parked host iteration
 *                             blocks on the M1c condition variable (bounded
 *                             wait, see rlStepHostWaitParked) instead of
 *                             re-presenting the cached framebuffer. Requires
 *                             effective interactive stepping (SSB64_RL_STEP=1
 *                             and no SSB64_BTT_INPUT); otherwise ignored with
 *                             a log line, so replay mode and ordinary play
 *                             are untouched. Unset: the visual path below is
 *                             the default and is byte-for-byte the pre-M6
 *                             frame.
 *
 * The window and the graphics backend stay alive (the Win32/SDL event pump
 * still runs every iteration, so the close button and the deferred clean
 * exit keep working); the window is simply never repainted. This is a
 * no-render / no-present / no-pacing mode, not a headless process. Nothing
 * game-owned changes: the game update, the controller read, the display-list
 * build and GamePostUpdateEvent run exactly as before; only the Fast3D walk
 * of the finished display list and the presents are omitted.
 */

/* 1 when SSB64_RL_NO_RENDER=1 and interactive stepping is effective (rl_boot.cpp). */
int rlNoRenderIsEnabled(void);

/* Main-thread parked wait for the no-render mode, called by PortPushFrame()
 * on a parked iteration instead of the paced idle present. Blocks on the M1c
 * condition variable for at most timeout_ms while the host gate is closed and
 * no deferred exit is pending; rlStepSubmit, result collection and shutdown
 * all notify it, so a submitted action is served without waiting out the
 * timeout. Returns 1 when the gate is still closed on return, 0 otherwise.
 * Never changes state; a no-op (returns 0) when stepping is not registered. */
int rlStepHostWaitParked(unsigned int timeout_ms);

/* -- M6 follow-up: opt-in process-local Raphnet adapter bypass -------------- */

/*
 *   SSB64_RAPHNET_DISABLE=1   training-only: libultraship's
 *                             ControlDeck::PreInitRaphnet reads this variable
 *                             itself and skips native Raphnet N64 USB adapter
 *                             support for the process (no hidapi open, no
 *                             per-read USB poll), the same state as the
 *                             gControllers.Raphnet.Enabled=0 kill switch but
 *                             without reading, registering or writing that
 *                             console variable, so nothing can be persisted
 *                             into the user's configuration. The variable is
 *                             kept only while interactive stepping is
 *                             effective (SSB64_RL_STEP=1 and no
 *                             SSB64_BTT_INPUT): otherwise rlConfigInit()
 *                             removes it from this process's environment
 *                             before the game boots and logs that it was
 *                             ignored, so an ordinary launch, a native replay
 *                             and a non-stepping RL run keep the configured
 *                             adapter path. Independent of SSB64_RL_NO_RENDER:
 *                             each is set explicitly by the launcher.
 *
 * The RL input path never depends on the adapter: rlStepControllerRead()
 * supplies player 0 for every gameplay tick and the native controller read of
 * the controller thread only feeds the stock (unused) pad. Bypassing the
 * adapter therefore changes no action, observation, tick or timing semantics;
 * it removes host work only.
 */

/* 1 when SSB64_RAPHNET_DISABLE=1 was kept for this process (effective interactive stepping), 0 otherwise. */
int rlRaphnetDisableIsEnabled(void);

/* -- M7f: opt-in target-identity diagnostic (btt_target_identity_v1) ------- */

/*
 *   SSB64_RL_TARGET_DIAG=1    record which Break-the-Targets target breaks
 *                             when, under a stable per-target ID, and report
 *                             it: a top-level "targets" object in the observe
 *                             and step responses (paired with the reply's
 *                             observation), "target_diag": true in status,
 *                             and a trailing "target_identity" object in a
 *                             clear's result JSON. Requires SSB64_RL_BTT=1;
 *                             works with interactive stepping and with the
 *                             native SSB64_BTT_INPUT replay (result JSON
 *                             only). Unset: the two decomp hooks return at
 *                             once and every reply, log line and result file
 *                             is byte-identical to a build without it.
 *
 * STABLE ID. Target i is the i-th target sc1PBonusStageMakeTargets creates:
 * loop index i reads the stage file's target DObjDesc[i + 1] (entry 0 is the
 * skipped root), i.e. the ID is the position of the target's descriptor in
 * ROM stage data. It never depends on a pointer, an allocation, a host frame,
 * the render or controller backend, the startup mode or the timing, so it is
 * the same in every process, mode and replay path. The decomp keeps the item
 * GObj of each target only to recognise which live target itTargetCommonProc-
 * Damage is breaking; that handle is compared, never dereferenced after the
 * break, and never leaves the decomp.
 *
 * Nothing here is part of RLObservation (schema 1), the step result (schema
 * 1), the policy observation or any reward: the diagnostic reads game state
 * and writes only PORT-only memory. See docs/rl_target_identity_m7f.md.
 */
#define RL_TARGET_DIAG_SCHEMA 1u

/* SCBATTLE_BONUSGAME_TASK_MAX, restated; sc1pbonusstage.c cross-checks it at compile time. */
#define RL_TARGET_COUNT 10u

/* RLTargetDiag.anomaly_flags. None of these occurs in normal play; each one
 * means the identity bookkeeping disagrees with the game and must be
 * investigated, never corrected. */
#define RL_TARGET_ANOMALY_SPAWN_OVERFLOW (1u << 0) /* more than RL_TARGET_COUNT spawns in one scene entry */
#define RL_TARGET_ANOMALY_UNKNOWN_BREAK  (1u << 1) /* ProcDamage for an item absent from the spawn table */
#define RL_TARGET_ANOMALY_REPEAT_BREAK   (1u << 2) /* ProcDamage for an ID already broken */
#define RL_TARGET_ANOMALY_COUNT_GUARD    (1u << 3) /* break while target_count was already 0 (PORT guard path) */
#define RL_TARGET_ANOMALY_LINK_MISMATCH  (1u << 4) /* capture-time link walk disagrees with remaining_mask */

typedef struct RLTargetRecord
{
	uint32_t animated; /* 1 = an anim joint was attached at spawn: the target moves */
	float spawn_x;     /* DObjDesc translate from the stage file */
	float spawn_y;
	float spawn_z;

	uint32_t break_order;       /* 1..RL_TARGET_COUNT in break order; 0 while unbroken */
	uint32_t break_input_tick;  /* syNetInputGetTick() inside the breaking update (= consumed_tick + 1) */
	uint32_t break_time_passed; /* SCBattleState::time_passed inside the breaking update */
	float break_x;              /* root DObj translate at the break (where the target actually was) */
	float break_y;
	float break_z;

} RLTargetRecord;

typedef struct RLTargetDiag
{
	uint32_t target_schema; /* RL_TARGET_DIAG_SCHEMA */
	uint32_t input_tick;    /* port stamp at the capture; equals the paired observation's input_tick */

	uint32_t scene_active;   /* 1 = BTT scene current and battle state present (the btt_active guard) */
	uint32_t scene_entries;  /* spawn-table resets (BTT scene entries) since process start */
	uint32_t spawn_count;    /* targets recorded by the spawn loop in this scene entry */
	uint32_t remaining_mask; /* bit i set = target i spawned and not broken (the one authoritative mask) */
	uint32_t break_count;    /* break events recorded in this scene entry */
	uint32_t anomaly_flags;  /* RL_TARGET_ANOMALY_* */

	uint32_t link_checked;      /* 1 = the item-link cross-check ran: scene active and its object links still
	                             * populated (gcEjectAll at the end of the scene task empties them); 0 otherwise,
	                             * with both link_* counts 0 */
	uint32_t link_live_targets; /* live target items on the item link at the capture (link_checked only) */
	uint32_t link_unmatched;    /* of those, items that are not an unbroken spawn-table entry */

	RLTargetRecord targets[RL_TARGET_COUNT];

} RLTargetDiag;

/* 1 when SSB64_RL_TARGET_DIAG=1 and SSB64_RL_BTT=1 (rl_boot.cpp). Also read
 * by the decomp hooks, which do nothing while it is 0. */
int rlTargetDiagIsEnabled(void);

/* Fill *out from the decomp's PORT-only target table (sc1pbonusstage.c) plus
 * a read-only walk of the item link. Strictly read-only towards the game;
 * never writes the port-owned stamp (input_tick). Handles out == NULL. */
void rlGameFillTargets(RLTargetDiag *out);

/* Copy the target snapshot paired with the most recently collected step into
 * *out. Pure query under the M1c mutex, any thread. Returns 1 when the
 * diagnostic is enabled and a paired snapshot exists, and stores its step
 * count in *step_count; 0 otherwise (*out untouched). */
int rlStepGetLastTargets(RLTargetDiag *out, uint32_t *step_count);

/* rlStepGetLatestObservation plus the target snapshot captured at the same
 * post-update, copied under one lock so the pair can never be torn. Returns 1
 * when both exist (diagnostic enabled), 0 otherwise (outputs untouched). */
int rlStepGetLatestObservationTargets(RLObservation *obs, RLTargetDiag *targets);

/* -- Internal seams inside port/rl ----------------------------------------- */

void rlStepRegister(void);                             /* from rlRuntimeRegister() */
void rlStepOnObservation(const RLObservation *obs);    /* from the M1b capture, main thread */
/* M7f: same, with the target snapshot of the same capture (NULL when the diagnostic is off). */
void rlStepOnObservationTargets(const RLObservation *obs, const RLTargetDiag *targets);
int rlStepExitOnEnd(void);                             /* SSB64_RL_EXIT_ON_END deferred to M1c */

#ifdef __cplusplus
}
#endif

#endif /* PORT_RL_H */
