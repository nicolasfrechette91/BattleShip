/*
 * rl_input.h -- M7q input-state diagnostic (latched controller state, tap
 * counters, Z timer, animation progress), port C++ side.
 *
 * The JSON rendering of RLInputDiag (port/rl/rl.h) for the transport's
 * "input" object. C++ only; the C-compatible declarations live in rl.h.
 */
#ifndef PORT_RL_INPUT_H
#define PORT_RL_INPUT_H

#include "rl/rl.h"

#include <nlohmann/json.hpp>

/* Wire identifier of the diagnostic contract; bump together with
 * RL_INPUT_SCHEMA whenever a field changes meaning. */
#define RL_INPUT_CONTRACT_ID "btt_input_state_v1"

/* RLInputDiag, field for field. Integers stay JSON integers; the two floats
 * carry the exact float value (widened to double, as the observation does).
 *
 *   {"contract", "input_schema", "input_tick", "scene_active", "live", "valid",
 *    "stick_x", "stick_y", "button_hold", "button_tap", "button_release",
 *    "tap_stick_x", "tap_stick_y", "hold_stick_x", "hold_stick_y",
 *    "tics_since_last_z", "anim_frame", "anim_speed", "motion_flag1"} */
nlohmann::json rlInputDiagToJson(const RLInputDiag &diag);

#endif /* PORT_RL_INPUT_H */
