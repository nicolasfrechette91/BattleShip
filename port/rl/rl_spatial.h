/*
 * rl_spatial.h -- M7g structured-spatial diagnostic, port C++ side.
 *
 * The JSON rendering of RLSpatialDiag (port/rl/rl.h) for the transport's
 * "spatial" object. C++ only; the C-compatible declarations live in rl.h.
 */
#ifndef PORT_RL_SPATIAL_H
#define PORT_RL_SPATIAL_H

#include "rl/rl.h"

#include <nlohmann/json.hpp>

/* Wire identifier of the diagnostic contract; bump together with
 * RL_SPATIAL_SCHEMA whenever a field changes meaning. */
#define RL_SPATIAL_CONTRACT_ID "btt_spatial_v1"

/* RLSpatialDiag, field for field. Integers stay JSON integers; floats carry
 * the exact float value (widened to double, as the observation does).
 *
 *   {"contract", "spatial_schema", "input_tick", "scene_active", "live",
 *    "update_tic", "anomaly_flags",
 *    "map_bounds": [top, bottom, right, left], "camera_bounds": [...],
 *    "groups": [{"id", "present", "status", "translated", "translate": [x, y],
 *                "speed": [x, y]}, ...]            (group_count entries),
 *    "fighter": {"valid", "floor_line_id", "ceil_line_id", "lwall_line_id",
 *                "rwall_line_id", "mask_curr", "floor_dist", "carry": [x, y],
 *                "coll": [top, center, bottom, width]},
 *    "target_live_mask", "target_positions": [[x, y] x RL_TARGET_COUNT],
 *    "lines": [{"id", "type", "group", "flags", "vertex_total",
 *               "vertices": [[x, y], ...]}, ...]  (only when with_lines)}
 *
 * with_lines is true for observe responses only: the line table never changes
 * after the stage's collision init, so step responses leave it out. */
nlohmann::json rlSpatialDiagToJson(const RLSpatialDiag &diag, bool with_lines);

#endif /* PORT_RL_SPATIAL_H */
