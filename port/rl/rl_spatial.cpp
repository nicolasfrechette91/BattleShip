/*
 * rl_spatial.cpp -- M7g structured-spatial diagnostic: JSON rendering.
 *
 * The snapshot itself is filled by typed decomp code (sc1pbonusstage.c, PORT
 * only), because the collision arrays, DObjs and MPCollData must never be
 * mirrored or offset-walked from C++. This file only turns the copy into
 * JSON. It reads nothing from the game, holds no state and is never called
 * unless SSB64_RL_SPATIAL=1.
 */
#include "rl/rl_spatial.h"

nlohmann::json rlSpatialDiagToJson(const RLSpatialDiag &d, bool with_lines) {
	using json = nlohmann::json;
	json j;
	j["contract"] = RL_SPATIAL_CONTRACT_ID;
	j["spatial_schema"] = d.spatial_schema;
	j["input_tick"] = d.input_tick;
	j["scene_active"] = d.scene_active;
	j["live"] = d.live;
	j["update_tic"] = d.update_tic;
	j["anomaly_flags"] = d.anomaly_flags;
	j["map_bounds"] = json::array({d.map_bound_top, d.map_bound_bottom, d.map_bound_right, d.map_bound_left});
	j["camera_bounds"] =
	    json::array({d.camera_bound_top, d.camera_bound_bottom, d.camera_bound_right, d.camera_bound_left});

	json groups = json::array();
	const uint32_t ng = d.group_count < RL_SPATIAL_MAX_GROUPS ? d.group_count : RL_SPATIAL_MAX_GROUPS;
	for (uint32_t i = 0; i < ng; i++) {
		const RLSpatialGroup &g = d.groups[i];
		json gj;
		gj["id"] = i;
		gj["present"] = g.present;
		gj["status"] = g.status;
		gj["translated"] = g.translated;
		gj["translate"] = json::array({g.translate_x, g.translate_y});
		gj["speed"] = json::array({g.speed_x, g.speed_y});
		groups.push_back(gj);
	}
	j["groups"] = groups;

	const RLSpatialFighter &f = d.fighter;
	json fj;
	fj["valid"] = f.valid;
	fj["floor_line_id"] = f.floor_line_id;
	fj["ceil_line_id"] = f.ceil_line_id;
	fj["lwall_line_id"] = f.lwall_line_id;
	fj["rwall_line_id"] = f.rwall_line_id;
	fj["mask_curr"] = f.mask_curr;
	fj["floor_dist"] = f.floor_dist;
	fj["carry"] = json::array({f.carry_x, f.carry_y});
	fj["coll"] = json::array({f.coll_top, f.coll_center, f.coll_bottom, f.coll_width});
	j["fighter"] = fj;

	j["target_live_mask"] = d.target_live_mask;
	json targets = json::array();
	for (uint32_t i = 0; i < RL_TARGET_COUNT; i++) {
		targets.push_back(json::array({d.target_x[i], d.target_y[i]}));
	}
	j["target_positions"] = targets;

	if (with_lines) {
		json lines = json::array();
		const uint32_t nl = d.line_count < RL_SPATIAL_MAX_LINES ? d.line_count : RL_SPATIAL_MAX_LINES;
		for (uint32_t i = 0; i < nl; i++) {
			const RLSpatialLine &l = d.lines[i];
			json lj;
			lj["id"] = i;
			lj["type"] = l.line_type;
			lj["group"] = l.group;
			lj["flags"] = l.flags;
			lj["vertex_total"] = l.vertex_total;
			json vertices = json::array();
			const uint32_t nv = l.vertex_count < RL_SPATIAL_MAX_LINE_VERTICES ? l.vertex_count
			                                                                  : RL_SPATIAL_MAX_LINE_VERTICES;
			for (uint32_t k = 0; k < nv; k++) {
				vertices.push_back(json::array({l.x[k], l.y[k]}));
			}
			lj["vertices"] = vertices;
			lines.push_back(lj);
		}
		j["lines"] = lines;
	}
	return j;
}
