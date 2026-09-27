/*
 * rl_entity.cpp -- M7n entity diagnostic: JSON rendering.
 *
 * The snapshot itself is filled by typed decomp code (sc1pbonusstage.c, PORT
 * only), because FTStruct, WPStruct and the object links must never be
 * mirrored or offset-walked from C++. This file only turns the copy into
 * JSON. It reads nothing from the game, holds no state and is never called
 * unless SSB64_RL_ENTITY=1.
 */
#include "rl/rl_entity.h"

nlohmann::json rlEntityDiagToJson(const RLEntityDiag &d) {
	using json = nlohmann::json;
	json j;
	j["contract"] = RL_ENTITY_CONTRACT_ID;
	j["entity_schema"] = d.entity_schema;
	j["input_tick"] = d.input_tick;
	j["scene_active"] = d.scene_active;
	j["live"] = d.live;
	j["anomaly_flags"] = d.anomaly_flags;

	const RLEntityFighter &f = d.fighter;
	json fj;
	fj["valid"] = f.valid;
	fj["status_total_tics"] = f.status_total_tics;
	fj["hitlag_tics"] = f.hitlag_tics;
	fj["jumps_max"] = f.jumps_max;
	fj["attack_active"] = f.attack_active;
	fj["cliff_hold"] = f.cliff_hold;
	fj["shield_active"] = f.shield_active;
	fj["fastfall"] = f.fastfall;
	fj["hitstun"] = f.hitstun;
	j["fighter"] = fj;

	j["weapon_total"] = d.weapon_total;
	json weapons = json::array();
	const uint32_t n = d.weapon_count < RL_ENTITY_MAX_WEAPONS ? d.weapon_count : RL_ENTITY_MAX_WEAPONS;
	for (uint32_t i = 0; i < n; i++) {
		const RLEntityWeapon &w = d.weapons[i];
		json wj;
		wj["serial"] = w.serial;
		wj["kind"] = w.kind;
		wj["owned"] = w.owned;
		wj["lr"] = w.lr;
		wj["ga"] = w.ga;
		wj["lifetime"] = w.lifetime;
		wj["attack_state"] = w.attack_state;
		wj["translate"] = json::array({w.x, w.y});
		wj["velocity"] = json::array({w.vel_x, w.vel_y});
		weapons.push_back(wj);
	}
	j["weapons"] = weapons;
	return j;
}
