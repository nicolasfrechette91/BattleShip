/*
 * rl_targets.h -- M7f target-identity diagnostic, port C++ side.
 *
 * One JSON rendering of RLTargetDiag (port/rl/rl.h) shared by the transport
 * (the "targets" object of observe / step replies) and the M1a result writer
 * (the "target_identity" object of a clear's result JSON), so the two can
 * never drift apart. C++ only; the C-compatible declarations live in rl.h.
 */
#ifndef PORT_RL_TARGETS_H
#define PORT_RL_TARGETS_H

#include "rl/rl.h"

#include <nlohmann/json.hpp>

/* Wire identifier of the diagnostic contract; bump together with
 * RL_TARGET_DIAG_SCHEMA whenever a field changes meaning. */
#define RL_TARGET_CONTRACT_ID "btt_target_identity_v1"

/* RLTargetDiag, field for field. Integers stay JSON integers; floats carry
 * the exact float value (widened to double, as the observation does). The
 * per-target records form a list in ID order: {"id", "animated", "spawn":
 * [x, y, z], "break_order", "break_input_tick", "break_time_passed",
 * "break": [x, y, z]}. Only the first spawn_count records are emitted. */
nlohmann::json rlTargetDiagToJson(const RLTargetDiag &diag);

#endif /* PORT_RL_TARGETS_H */
