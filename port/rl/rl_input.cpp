/*
 * rl_input.cpp -- M7q input-state diagnostic: JSON rendering.
 *
 * The snapshot itself is filled by typed decomp code (sc1pbonusstage.c, PORT
 * only), because FTStruct, GObj and DObj must never be mirrored or
 * offset-walked from C++. This file only turns the copy into JSON. It reads
 * nothing from the game, holds no state and is never called unless
 * SSB64_RL_INPUT=1.
 */
#include "rl/rl_input.h"

nlohmann::json rlInputDiagToJson(const RLInputDiag &d) {
	using json = nlohmann::json;
	json j;
	j["contract"] = RL_INPUT_CONTRACT_ID;
	j["input_schema"] = d.input_schema;
	j["input_tick"] = d.input_tick;
	j["scene_active"] = d.scene_active;
	j["live"] = d.live;
	j["valid"] = d.valid;
	j["stick_x"] = d.stick_x;
	j["stick_y"] = d.stick_y;
	j["button_hold"] = d.button_hold;
	j["button_tap"] = d.button_tap;
	j["button_release"] = d.button_release;
	j["tap_stick_x"] = d.tap_stick_x;
	j["tap_stick_y"] = d.tap_stick_y;
	j["hold_stick_x"] = d.hold_stick_x;
	j["hold_stick_y"] = d.hold_stick_y;
	j["tics_since_last_z"] = d.tics_since_last_z;
	j["anim_frame"] = d.anim_frame;
	j["anim_speed"] = d.anim_speed;
	j["motion_flag1"] = d.motion_flag1;
	return j;
}
