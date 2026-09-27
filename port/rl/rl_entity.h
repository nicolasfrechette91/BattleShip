/*
 * rl_entity.h -- M7n entity diagnostic (agent action progress + projectiles),
 * port C++ side.
 *
 * The JSON rendering of RLEntityDiag (port/rl/rl.h) for the transport's
 * "entity" object. C++ only; the C-compatible declarations live in rl.h.
 */
#ifndef PORT_RL_ENTITY_H
#define PORT_RL_ENTITY_H

#include "rl/rl.h"

#include <nlohmann/json.hpp>

/* Wire identifier of the diagnostic contract; bump together with
 * RL_ENTITY_SCHEMA whenever a field changes meaning. */
#define RL_ENTITY_CONTRACT_ID "btt_entity_v1"

/* RLEntityDiag, field for field. Integers stay JSON integers; floats carry
 * the exact float value (widened to double, as the observation does).
 *
 *   {"contract", "entity_schema", "input_tick", "scene_active", "live",
 *    "anomaly_flags",
 *    "fighter": {"valid", "status_total_tics", "hitlag_tics", "jumps_max",
 *                "attack_active", "cliff_hold", "shield_active", "fastfall",
 *                "hitstun"},
 *    "weapon_total",
 *    "weapons": [{"serial", "kind", "owned", "lr", "ga", "lifetime",
 *                 "attack_state", "translate": [x, y], "velocity": [x, y]},
 *                ...]                                 (weapon_count entries)} */
nlohmann::json rlEntityDiagToJson(const RLEntityDiag &diag);

#endif /* PORT_RL_ENTITY_H */
