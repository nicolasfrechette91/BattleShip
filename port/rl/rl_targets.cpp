/*
 * rl_targets.cpp -- M7f target-identity diagnostic: JSON rendering.
 *
 * The bookkeeping itself lives in the decomp (sc1pbonusstage.c, PORT only):
 * the spawn loop and itTargetCommonProcDamage are the only places that know
 * which target is which, and rlGameFillTargets() copies that table out with a
 * read-only item-link cross-check. This file only turns the copy into JSON.
 * It reads nothing from the game, holds no state and is never called unless
 * SSB64_RL_TARGET_DIAG=1.
 */
#include "rl/rl_targets.h"

nlohmann::json rlTargetDiagToJson(const RLTargetDiag &d) {
	using json = nlohmann::json;
	json j;
	j["contract"] = RL_TARGET_CONTRACT_ID;
	j["target_schema"] = d.target_schema;
	j["input_tick"] = d.input_tick;
	j["scene_active"] = d.scene_active;
	j["scene_entries"] = d.scene_entries;
	j["spawn_count"] = d.spawn_count;
	j["remaining_mask"] = d.remaining_mask;
	j["break_count"] = d.break_count;
	j["anomaly_flags"] = d.anomaly_flags;
	j["link_checked"] = d.link_checked;
	j["link_live_targets"] = d.link_live_targets;
	j["link_unmatched"] = d.link_unmatched;

	json records = json::array();
	const uint32_t n = d.spawn_count < RL_TARGET_COUNT ? d.spawn_count : RL_TARGET_COUNT;
	for (uint32_t i = 0; i < n; i++) {
		const RLTargetRecord &t = d.targets[i];
		json r;
		r["id"] = i;
		r["animated"] = t.animated;
		r["spawn"] = json::array({t.spawn_x, t.spawn_y, t.spawn_z});
		r["break_order"] = t.break_order;
		r["break_input_tick"] = t.break_input_tick;
		r["break_time_passed"] = t.break_time_passed;
		r["break"] = json::array({t.break_x, t.break_y, t.break_z});
		records.push_back(r);
	}
	j["records"] = records;
	return j;
}
