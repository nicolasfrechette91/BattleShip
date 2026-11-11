#!/usr/bin/env python3
"""Tests for tools/glitch/states (no ROM, no game). Run: python -I tools/glitch/states/test_states.py

  - parser units on synthetic C: preprocessor, motion-macro word counts, motion-file offsets (with a data array in
    between), script timelines (waits, async waits, loops, goto), hitbox windows, AObjEvent16 stream lengths,
    status descriptors, the call graph (param setters, handler arrays, fighter-specific guards);
  - the state signals on synthetic traces with a synthetic table: one test per event kind, and no event on a clean trace;
  - the displayed clock against the game's digit algorithm;
  - facts read in the real decomp (skipped when the decomp submodule is absent).
What they do not cover: real lab traces, the real game, MSVC.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import decomp_states as ds  # noqa: E402
import state_detect as sd  # noqa: E402
import detect  # noqa: E402

REPO = HERE.parent.parent.parent
DECOMP = REPO / "decomp"
HAVE_DECOMP = (DECOMP / "src" / "ft" / "ftmain.c").exists()


def src(text: str, rel: str = "x.c", defines=None) -> ds.SourceFile:
    raw = text.splitlines()
    pre = ds.preprocess(raw, defines or {"REGION_US": 1})
    return ds.SourceFile(Path(rel), rel, raw, ds.strip_comments("\n".join(pre)).split("\n"))


FTDEF = r"""
#define ftMotionCommandEnd() GC_FIELDSET(nFTMotionEventEnd, 26, 6)
#define ftMotionCommandWait(frames) (GC_FIELDSET(nFTMotionEventSyncWait, 26, 6) | GC_FIELDSET(frames, 0, 26))
#define ftMotionCommandWaitAsync(frames) (GC_FIELDSET(nFTMotionEventAsyncWait, 26, 6) | GC_FIELDSET(frames, 0, 26))
#define ftMotionCommandSetFlag1(val) (GC_FIELDSET(nFTMotionEventSetFlag1, 26, 6) | GC_FIELDSET(val, 0, 26))
#define ftMotionCommandGotoS1() GC_FIELDSET(nFTMotionEventGoto, 26, 6)
#define ftMotionCommandGotoS2(addr) ((uintptr_t)addr)
#define ftMotionCommandGoto(addr) ftMotionCommandGotoS1(), ftMotionCommandGotoS2(addr)
#define ftMotionCommandLoopBegin(count) (GC_FIELDSET(nFTMotionEventLoopBegin, 26, 6) | GC_FIELDSET(count, 0, 26))
#define ftMotionCommandLoopEnd() GC_FIELDSET(nFTMotionEventLoopEnd, 26, 6)
#define ftMotionCommandClearAttackCollAll() GC_FIELDSET(nFTMotionEventClearAttackCollAll, 26, 6)
#define ftMotionCommandMakeAttackCollS1(aid, gid, jid, dmg, reb, ele) (0)
#define ftMotionCommandMakeAttackCollS2(sz, ox) (0)
#define ftMotionCommandMakeAttackCollS3(oy, oz) (0)
#define ftMotionCommandMakeAttackCollS4(ang, kbs, kbw, ga) (0)
#define ftMotionCommandMakeAttackCollS5(sd, fl, fk, kbb) (0)
#define ftMotionCommandMakeAttackColl(aid, gid, jid, dmg, reb, elem, sz, ox, oy, oz, ang, kbs, kbw, ga, sd, fl, fk, kbb) \
ftMotionCommandMakeAttackCollS1(aid, gid, jid, dmg, reb, elem), ftMotionCommandMakeAttackCollS2(sz, ox), ftMotionCommandMakeAttackCollS3(oy, oz), ftMotionCommandMakeAttackCollS4(ang, kbs, kbw, ga), ftMotionCommandMakeAttackCollS5(sd, fl, fk, kbb)
"""

MOTION = r"""
ftMotionCommand dTest_0x0000[] = {
	ftMotionCommandWait(2),
	ftMotionCommandSetFlag1(1),
	ftMotionCommandEnd(),
};
FTThrowHitDesc dTest_0x000C[] = {
	{ 1, 2, 3, 4, 5, 6, 7 },
};
ftMotionCommand dTest_Hit[] = {
	ftMotionCommandWaitAsync(3),
	ftMotionCommandLoopBegin(2),
	ftMotionCommandMakeAttackColl(0, 0, 1, 7, 0, 0, 100, 0, 0, 0, 90, 0, 0, 3, 0, 1, 1, 0),
	ftMotionCommandWait(2),
	ftMotionCommandClearAttackCollAll(),
	ftMotionCommandWait(1),
	ftMotionCommandLoopEnd(),
	ftMotionCommandSetFlag1(0),
	ftMotionCommandGoto(dTest_0x0000),
};
"""


class ParserTests(unittest.TestCase):
    def test_preprocessor_branches_keep_line_numbers(self):
        text = "a\n#ifdef PORT\nport\n#else\nn64\n#endif\n#if defined(REGION_US)\nus\n#else\njp\n#endif\nz"
        n64 = ds.preprocess(text.split("\n"), {"REGION_US": 1})
        port = ds.preprocess(text.split("\n"), {"REGION_US": 1, "PORT": 1})
        self.assertEqual(len(n64), len(text.split("\n")))
        self.assertEqual([l for l in n64 if l], ["a", "n64", "us", "z"])
        self.assertEqual([l for l in port if l], ["a", "port", "us", "z"])

    def test_macro_word_counts(self):
        m = ds.motion_macro_words(src(FTDEF, "ftdef.h"))
        self.assertEqual(m["ftMotionCommandWait"][1], 1)
        self.assertEqual(m["ftMotionCommandGoto"][1], 2)
        self.assertEqual(m["ftMotionCommandMakeAttackColl"][1], 5)

    def test_motion_offsets_across_a_data_array(self):
        macros = ds.motion_macro_words(src(FTDEF, "ftdef.h"))
        scripts, problems = ds.parse_motion_file(src(MOTION, "202.c"), macros)
        self.assertEqual(problems, [])
        self.assertEqual([(s.name, s.offset) for s in scripts], [("dTest_0x0000", 0), ("dTest_Hit", 0x0C + 28)])

    def test_offset_mismatch_is_reported(self):
        macros = ds.motion_macro_words(src(FTDEF, "ftdef.h"))
        bad = MOTION.replace("dTest_0x000C", "dTest_Data").replace("dTest_Hit", "dTest_0x0040")
        _, problems = ds.parse_motion_file(src(bad, "202.c"), macros)
        self.assertTrue(problems)

    def test_script_timeline_loops_and_goto(self):
        macros = ds.motion_macro_words(src(FTDEF, "ftdef.h"))
        scripts, _ = ds.parse_motion_file(src(MOTION, "202.c"), macros)
        by = {s.name: s for s in scripts}
        sim = ds.simulate_script(by, by["dTest_Hit"])
        ev = [(e["frame"], e["event"]) for e in sim["events"]]
        self.assertEqual(ev[:4], [(3, "hitbox_on"), (5, "hitbox_off_all"), (6, "hitbox_on"), (8, "hitbox_off_all")])
        self.assertIn((9, "flag1"), ev)          # after the loop: 3 + 2*(2+1)
        self.assertIn((11, "flag1"), ev)         # the goto target's flag at +2
        self.assertEqual(sim["end"], "end")
        self.assertEqual(ds.hitbox_windows(sim["events"]), [[3, 4], [6, 7]])

    def test_anim_stream_length(self):
        body = ("ftAnimSetValRateBlockT(FT_ANIM_ROTX | FT_ANIM_ROTY, 5), 1, 2, 3, 4,"
                "ftAnimSetValAfter(FT_ANIM_TRAY), 9, ftAnimBlock(0, 10), ftAnimEnd(),")
        info = ds.anim_stream_length(ds.anim_words(body))
        self.assertEqual(info["frames"], 15)
        self.assertFalse(info["loops"])
        loop = ds.anim_stream_length(ds.anim_words("ftAnimBlock(0, 4), ftAnimLoop(0x6800, -4), ftAnimEnd(),"))
        self.assertTrue(loop["loops"])
        big = ds.anim_stream_length(ds.anim_words("ftAnimBlock(0, 0x8001), ftAnimEnd(),"))
        self.assertTrue(big["payload_bit15"])

    def test_status_descriptors(self):
        text = """
	// Status 20 (0x14): KneeBend
	{
		nFTCommonMotionKneeBend,			// Script ID
		nFTMotionAttackIDNone,
		0, FALSE, nMPKineticsGround, FALSE, nFTStatusAttackIDNone,
		ftCommonKneeBendProcUpdate,			// Proc Update
		ftCommonKneeBendProcInterrupt,
		ftPhysicsApplyGroundVelFriction,
		mpCommonSetFighterFallOnGroundBreak
	},
"""
        d = ds.parse_status_descs(src(text, "s.h"), 0)
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0].sid, d[0].name, d[0].motion), (20, "KneeBend", "nFTCommonMotionKneeBend"))
        self.assertEqual(d[0].procs["interrupt"], "ftCommonKneeBendProcInterrupt")

    def test_call_graph_param_setter_and_guard(self):
        code = """
void ftCommonLandingSetStatusParam(GObj *fighter_gobj, s32 status_id, f32 anim_speed)
{
    ftMainSetStatus(fighter_gobj, status_id, 0.0F, anim_speed, FTSTATUS_PRESERVE_NONE);
}

void ftCommonLandingSetStatus(GObj *fighter_gobj)
{
    ftCommonLandingSetStatusParam(fighter_gobj, nFTCommonStatusLandingHeavy, 0.5F);
}

void ftCommonOtherSetStatus(GObj *fighter_gobj)
{
    if (fp->fkind == nFTKindLink)
    {
        ftMainSetStatus(fighter_gobj, nFTCommonStatusWait, 35.0F, 1.0F, FTSTATUS_PRESERVE_NONE);
    }
    ftMainSetStatus(fighter_gobj, nFTCommonStatusFall, 0.0F, 1.0F, FTSTATUS_PRESERVE_NONE);
    ftMainPlayAnimEventsAll(fighter_gobj);
}

void ftCommonCheckThing(GObj *fighter_gobj, void (*proc)(GObj*))
{
    ftCommonLandingSetStatus(fighter_gobj);
}
"""
        m = ds.Model(Path("."), {"REGION_US": 1})
        sf = src(code)
        m.funcs, m.macros = ds.index_functions([sf])
        m.status_ids = {"nFTCommonStatusWait": 10, "nFTCommonStatusFall": 26, "nFTCommonStatusLandingHeavy": 32}
        for f in m.funcs.values():
            for _, args in ds.find_calls(f.body, "ftMainSetStatus"):
                if len(args) > 1 and args[1] in f.params:
                    m.param_setters[f.name] = f.params.index(args[1])
        self.assertEqual(m.funcs["ftCommonCheckThing"].params, ["fighter_gobj", "proc"])
        self.assertEqual(m.param_setters, {"ftCommonLandingSetStatusParam": 1})
        self.assertIn(32, m.targets("ftCommonCheckThing"))
        sets = m.direct_sets(m.funcs["ftCommonLandingSetStatus"])
        self.assertEqual(sets[0]["anim_speed"], "0.5F")
        other = m.funcs["ftCommonOtherSetStatus"]
        offs = [s["offset"] for s in m.direct_sets(other)]
        self.assertEqual(m.fkind_guard(other, offs[0]), ["nFTKindLink"])
        self.assertEqual(m.fkind_guard(other, offs[1]), [])


# ----------------------------------------------------------------------------------------------------------------------
# Synthetic traces
# ----------------------------------------------------------------------------------------------------------------------

def status(name, anim=None, loops=False, entry=None, exits=None, stale=(), script=None):
    return {"name": name, "motion": {"anim": None if anim is None and not loops else
                                             {"joints": 5, "loops": loops, "length_last_joint": None if loops else anim}},
            "entry": entry or [{"continuation": False, "double_advance": False, "frame_begin_value": 0.0, "fkind_guard": []}],
            "exits": exits or {}, "stale_flag_candidates": list(stale), "script": script}


DBL = [{"continuation": False, "double_advance": True, "frame_begin_value": 0.0, "fkind_guard": []}]
CONT = [{"continuation": True, "double_advance": False, "frame_begin_value": None, "fkind_guard": []}]

TABLE = {
    "statuses": {
        "10": status("Wait", loops=True),
        "20": status("KneeBend", anim=7),
        "22": status("JumpF", anim=40, exits={"update": {"targets": {"26": []}}}),
        "24": status("JumpAerialF", anim=60),
        "26": status("Fall", loops=True),
        "31": status("LandingLight", anim=7),
        "58": status("FallSpecial", loops=True),
        "59": status("LandingFallSpecial", anim=7),
        "156": status("EscapeF", anim=32, entry=DBL, stale=["flag1"],
                      script={"events": [{"frame": 20, "event": "flag1", "value": 1}]}),
        "209": status("AttackAirN", anim=50, entry=DBL, exits={"update": {"targets": {"26": []}}}),
        "219": status("LandingAirNull", anim=7),
        "227": status("SpecialLw", anim=87, entry=CONT),
        "228": status("SpecialAirLw", anim=83, entry=DBL + CONT,
                      script={"events": [{"frame": 43, "event": "flag2", "value": 1}]}),
    },
    "edges": [{"from": a, "to": b, "via": v} for a, b, v in [
        (10, 20, "interrupt"), (20, 22, "update"), (22, 24, "interrupt"), (22, 26, "update"), (22, 209, "interrupt"),
        (24, 26, "update"), (26, 209, "interrupt"), (26, 31, "map"), (26, 10, "map"), (209, 26, "update"),
        (209, 10, "map"), (209, 31, "map"), (209, 219, "map"), (31, 10, "update"), (10, 156, "interrupt"),
        (156, 10, "update"), (26, 228, "interrupt"), (228, 227, "map"), (227, 228, "physics"), (228, 26, "update"),
        (58, 59, "map"), (58, 10, "map"), (59, 10, "update"), (26, 58, "update")]],
}


def tick(i, **kw):
    """One reply. kw: status, ga, x, y, vx, vy, tics, anim, speed, flag1, jumps, hitlag, attack, tap, hold, stick,
    zlast, mask, carry, tp (time_passed), remaining, tmask, weapons, facing."""
    st = kw.get("status", 10)
    r = {"consumed_tick": None if i < 0 else i,
         "observation": {"position_x": kw.get("x", 0.0), "position_y": kw.get("y", 0.0), "air_velocity_x": kw.get("vx", 0.0),
                         "air_velocity_y": kw.get("vy", 0.0), "ground_air_state": kw.get("ga", 0), "fighter_status_id": st,
                         "fighter_valid": 1, "btt_active": 1, "input_tick": i + 1, "jumps_used": kw.get("jumps", 0),
                         "time_passed": kw.get("tp", max(i, 0)), "targets_remaining": kw.get("remaining", 10),
                         "facing_direction": kw.get("facing", 1)},
         "spatial": {"fighter": {"floor_line_id": -1, "lwall_line_id": -1, "rwall_line_id": -1, "ceil_line_id": -1,
                                 "mask_curr": kw.get("mask", 0), "carry": kw.get("carry", [0, 0]), "coll": [320, 190, 0, 150]},
                     "groups": [], "target_live_mask": kw.get("tmask", 1), "target_positions": [[5000, 5000]]},
         "entity": {"fighter": {"hitlag_tics": kw.get("hitlag", 0), "attack_active": kw.get("attack", 0),
                                "status_total_tics": kw.get("tics", 0), "jumps_max": 2},
                    "weapons": kw.get("weapons", [])},
         "input": {"stick_x": kw.get("stick", (0, 0))[0], "stick_y": kw.get("stick", (0, 0))[1],
                   "button_tap": kw.get("tap", 0), "button_hold": kw.get("hold", 0), "button_release": 0,
                   "tics_since_last_z": kw.get("zlast", 65536), "anim_frame": kw.get("anim", 0.0),
                   "anim_speed": kw.get("speed", 1.0), "motion_flag1": kw.get("flag1", 0)},
         "targets": {"remaining_mask": kw.get("tmask", 1), "records": []}}
    return r


def trace(rows):
    """rows: list of kw dicts for ticks -1 (initial), 0, 1, ..."""
    replies = [tick(i - 1, **kw) for i, kw in enumerate(rows)]
    replies[0]["spatial"]["lines"] = [{"id": 0, "type": 0, "group": 1, "flags": 0, "vertex_total": 2,
                                       "vertices": [[-9000, -9000], [-8000, -9000]]}]
    return {"initial": replies[0], "steps": replies[1:]}


def run(rows):
    events, summary = sd.scan(trace(rows), TABLE, source={"trace": "synthetic"})
    return sorted({e["kind"] for e in events}), events, summary


def instance(status, n, start_anim=0.0, speed=1.0, **kw):
    return [dict(status=status, tics=k, anim=start_anim + k * speed, speed=speed, **kw) for k in range(n)]


class SignalTests(unittest.TestCase):
    def test_clean_trace(self):
        rows = [dict(status=10, anim=5.0)] + [dict(status=10, tics=k + 1, anim=6.0 + k) for k in range(5)]
        rows += instance(20, 3, ga=0)
        rows += instance(22, 4, ga=1, jumps=1)
        kinds, ev, s = run(rows)
        self.assertEqual(kinds, [])
        self.assertIn("transition:Wait>KneeBend", s["counts"])

    def test_events_follow_the_v1_format(self):
        rows = [dict(status=10)] + [dict(status=10, tics=1, tp=5)]
        kinds, ev, _ = run(rows)
        self.assertEqual(kinds, ["timer_tick_mismatch"])
        e = ev[0]
        for k in ("schema", "event_id", "kind", "mechanisms", "step", "step_from", "step_to", "input_tick",
                  "consumed_tick", "score", "source", "fighter", "evidence", "platform_sensitive", "detector", "needs_replay"):
            self.assertIn(k, e)
        self.assertEqual(e["schema"], "btt_glitch_event_v1")
        self.assertEqual(e["detector"]["name"], "tools/glitch/states/state_detect.py")
        self.assertEqual(e["evidence"]["displayed"], "00:00.09")

    def test_timer_stops_on_the_completion_tick(self):
        rows = [dict(status=10)] + [dict(status=10, tics=k + 1, anim=float(k)) for k in range(4)]
        rows[4]["remaining"] = 0
        rows[4]["tmask"] = 0
        kinds, _, s = run(rows)
        self.assertEqual(kinds, [])
        self.assertEqual(s["counts"]["completion_tick"], 3)

    def test_unlisted_transition_and_same_tick_chain(self):
        rows = [dict(status=20)] + [dict(status=24, ga=1, tics=0, jumps=2)]      # KneeBend > JumpF > JumpAerialF
        kinds, _, s = run(rows)
        self.assertEqual(kinds, [])
        self.assertIn("chain:KneeBend>JumpF>JumpAerialF", s["counts"])
        rows = [dict(status=10)] + [dict(status=24, ga=1, tics=0)]               # Wait > JumpAerialF: no path
        kinds, _, _ = run(rows)
        self.assertIn("status_transition_unlisted", kinds)

    def test_entry_frames(self):
        ok = [dict(status=10)] + instance(209, 3, start_anim=1.0, ga=1)          # +1 entry
        self.assertNotIn("entry_frame_unexpected", run(ok)[0])
        bad = [dict(status=10)] + instance(209, 3, start_anim=4.0, ga=1)
        self.assertIn("entry_frame_unexpected", run(bad)[0])
        cont = [dict(status=228, ga=1, anim=10.0, tics=9)] + instance(227, 2, start_anim=11.0)
        self.assertNotIn("entry_frame_unexpected", run(cont)[0])

    def test_anim_clock_skew(self):
        rows = [dict(status=10)] + instance(22, 3, ga=1)
        rows.append(dict(status=22, ga=1, tics=3, anim=5.0))
        self.assertIn("anim_clock_skew", run(rows)[0])
        frozen = [dict(status=10)] + instance(22, 3, ga=1)
        frozen.append(dict(status=22, ga=1, tics=3, anim=2.0, hitlag=4))
        self.assertNotIn("anim_clock_skew", run(frozen)[0])

    def test_status_shorter_than_nominal(self):
        rows = [dict(status=10)] + instance(209, 30, start_anim=1.0, ga=1) + [dict(status=26, ga=1)]
        self.assertIn("status_shorter_than_nominal", run(rows)[0])
        rows = [dict(status=10)] + instance(209, 49, start_anim=1.0, ga=1) + [dict(status=26, ga=1)]
        kinds, _, s = run(rows)
        self.assertNotIn("status_shorter_than_nominal", kinds)
        self.assertEqual(s["counts"].get("instance_ok"), 1)

    def test_jumps(self):
        rows = [dict(status=26, ga=1, jumps=2), dict(status=26, ga=1, jumps=1, tics=1)]
        self.assertIn("jumps_restored_in_air", run(rows)[0])
        rows = [dict(status=26, ga=1, jumps=2), dict(status=26, ga=1, jumps=3, tics=1)]
        self.assertIn("jumps_over_max", run(rows)[0])
        rows = [dict(status=26, ga=1, jumps=2), dict(status=31, ga=0, jumps=0)]
        self.assertEqual(run(rows)[0], [])

    def test_tornado_charge(self):
        B = sd.BUTTON_B
        spent = [dict(status=26, ga=1)] + instance(228, 45, start_anim=1.0, ga=1, vy=-5.0)       # passes anim 43
        spent += [dict(status=26, ga=1, vy=-10.0), dict(status=228, ga=1, anim=1.0, vy=-8.0)]
        spent += [dict(status=228, ga=1, tics=1, anim=2.0, vy=12.0, tap=B)]                       # rise while spent
        self.assertIn("special_limit_rearm_unexpected", run(spent)[0])
        landed = [dict(status=26, ga=1)] + instance(228, 45, start_anim=1.0, ga=1, vy=-5.0)
        landed += [dict(status=31, ga=0), dict(status=10, ga=0, tics=0), dict(status=228, ga=1, anim=1.0, vy=-8.0)]
        landed += [dict(status=228, ga=1, tics=1, anim=2.0, vy=12.0, tap=B)]
        kinds, _, s = run(landed)
        self.assertNotIn("special_limit_rearm_unexpected", kinds)
        self.assertEqual(s["counts"].get("tornado:rise_tap"), 1)

    def test_landing_branches(self):
        lag = [dict(status=209, ga=1, anim=10.0, flag1=50), dict(status=219, ga=0, flag1=50, vy=-30.0)]
        kinds, _, s = run(lag)
        self.assertEqual(kinds, [])
        self.assertIn("landing:lag", s["counts"])
        skip = [dict(status=209, ga=1, anim=10.0), dict(status=10, ga=0, vy=-10.0)]
        kinds, _, s = run(skip)
        self.assertEqual(kinds, [])
        self.assertIn("landing:skip", s["counts"])
        zc = [dict(status=209, ga=1, anim=10.0, flag1=50), dict(status=31, ga=0, flag1=50, vy=-30.0, zlast=3)]
        self.assertIn("landing:zcancel", run(zc)[2]["counts"])
        bad = [dict(status=209, ga=1, anim=10.0, flag1=50), dict(status=10, ga=0, flag1=50, vy=-30.0)]
        self.assertIn("landing_branch_mismatch", run(bad)[0])
        fs = [dict(status=58, ga=1), dict(status=10, ga=0, vy=-5.0)]
        self.assertIn("fallspecial_landing_lag_skipped", run(fs)[0])

    def test_hitlag_and_breaks(self):
        body_no_lag = [dict(status=209, ga=1, anim=5.0, tmask=3, attack=1), dict(status=209, ga=1, tics=1, anim=6.0, tmask=1, attack=1)]
        self.assertIn("break_hitlag_mismatch", run(body_no_lag)[0])
        body_lag = [dict(status=209, ga=1, anim=5.0, tmask=3, attack=1), dict(status=209, ga=1, tics=1, anim=6.0, tmask=1, attack=1, hitlag=7)]
        kinds, _, s = run(body_lag)
        self.assertNotIn("break_hitlag_mismatch", kinds)
        self.assertIn("break:hitlag=7", s["counts"])
        fb = {"serial": 1, "kind": 0, "translate": [0, 0], "velocity": [0, 0]}
        weapon_lag = [dict(status=26, ga=1, tmask=3, weapons=[fb]), dict(status=26, ga=1, tics=1, tmask=1, hitlag=6, weapons=[fb])]
        self.assertIn("break_hitlag_mismatch", run(weapon_lag)[0])
        frozen = [dict(status=209, ga=1, anim=5.0, tmask=3, hitlag=5), dict(status=209, ga=1, tics=1, anim=5.0, tmask=1, hitlag=4)]
        self.assertIn("break_during_hitlag", run(frozen)[0])

    def test_ceiling_velocity_kept(self):
        rows = [dict(status=22, ga=1, y=100.0, vy=20.0)] + [dict(status=22, ga=1, tics=k + 1, anim=float(k + 1), y=100.0,
                                                                vy=20.0 - 2.4 * k, mask=sd.MAP_FLAG_CEIL) for k in range(4)]
        self.assertIn("ceiling_velocity_kept", run(rows)[0])

    def test_stale_flag_at_entry(self):
        rows = [dict(status=10, flag1=1)] + instance(156, 2, start_anim=1.0, flag1=1)
        self.assertIn("stale_flag_at_entry", run(rows)[0])
        rows = [dict(status=10, flag1=0)] + instance(156, 2, start_anim=1.0, flag1=0)
        self.assertNotIn("stale_flag_at_entry", run(rows)[0])

    def test_no_input_block_disables_the_input_signals(self):
        tr = trace([dict(status=26, ga=1)] + instance(209, 3, start_anim=4.0, ga=1))
        for r in [tr["initial"]] + tr["steps"]:
            r.pop("input")
        events, summary = sd.scan(tr, TABLE)
        self.assertEqual(events, [])
        self.assertIn("states:no_input_block", summary["counts"])

    def test_hook_through_detect_py(self):
        tr = trace([dict(status=10)] + [dict(status=10, tics=1, tp=5)])
        p = detect.Params(state_table=TABLE)
        det = detect.Detector(tr, None, p, {"trace": "synthetic"})
        det.run()
        self.assertIn("timer_tick_mismatch", {e["kind"] for e in det.events})


class CliTests(unittest.TestCase):
    def test_cli_end_to_end(self):
        import gzip
        import glitch
        import mario_states
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tr = trace([dict(status=26, ga=1, jumps=2), dict(status=26, ga=1, jumps=1, tics=1)])
            path = d / "t.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(tr, f)
            table = d / "table.json"
            table.write_text(json.dumps(TABLE), encoding="utf-8")
            out = d / "ev.jsonl"
            self.assertEqual(mario_states.main(["detect", "--trace", str(path), "--table", str(table), "--out", str(out)]), 0)
            kinds = {json.loads(l)["kind"] for l in out.read_text().splitlines()}
            self.assertEqual(kinds, {"jumps_restored_in_air"})
            out2 = d / "ev2.jsonl"
            self.assertEqual(glitch.main(["detect", "--trace", str(path), "--states", str(table), "--out", str(out2)]), 0)
            kinds2 = {json.loads(l)["kind"] for l in out2.read_text().splitlines()}
            self.assertIn("jumps_restored_in_air", kinds2)
            self.assertTrue(json.loads(out2.with_suffix(".summary.json").read_text()))


class ClockTests(unittest.TestCase):
    def test_displayed_time(self):
        self.assertEqual(sd.displayed_time(446), "00:07.43")    # the 468-row baseline (CLAUDE.md)
        self.assertEqual(sd.displayed_time(1244), "00:20.73")   # the 1,245-tick lab clear (time_passed = tick - 1)
        self.assertEqual(sd.displayed_time(479), "00:07.99")
        self.assertEqual(sd.displayed_time(480), "00:08.00")
        self.assertEqual({sd.displayed_time(r)[-1] for r in range(6)}, {"0", "1", "3", "5", "7", "9"})
        self.assertEqual([sd.displayed_time(r)[-2:] for r in range(6)], ["00", "01", "03", "05", "07", "09"])


@unittest.skipUnless(HAVE_DECOMP, "decomp submodule not checked out")
class DecompFacts(unittest.TestCase):
    """Facts read in the code, checked against the extracted table (STATE_MACHINE_CANDIDATES.md)."""

    @classmethod
    def setUpClass(cls):
        cls.t = ds.build_table(DECOMP)
        cls.s = {int(k): v for k, v in cls.t["statuses"].items()}

    def ev(self, sid, event, value=None):
        return [e["frame"] for e in (self.s[sid]["script"] or {}).get("events", []) if e["event"] == event and
                (value is None or e.get("value") == value)]

    def edge(self, a, b):
        return any(e["from"] == a and e["to"] == b for e in self.t["edges"])

    def test_no_problems(self):
        self.assertEqual(self.t["problems"], [])

    def test_attributes(self):
        a = self.t["attributes"]
        self.assertEqual((a["kneebend_anim_length"], a["jumps_max"], a["gravity"]), (3.0, 2, 2.4))

    def test_tornado_scripts(self):
        self.assertEqual(self.ev(228, "flag3", 1), [0])
        self.assertEqual(self.ev(228, "flag3", 0), [43])
        self.assertEqual(self.ev(228, "flag2", 1), [43])
        self.assertEqual(self.ev(227, "flag2"), [])
        entries = {e["setter"]: e for e in self.s[228]["entry"]}
        self.assertTrue(entries["ftMarioSpecialLwSetStatus"]["double_advance"])
        self.assertIn("jumps_used=1", entries["ftMarioSpecialLwSetStatus"]["implied"])
        self.assertTrue(entries["ftMarioSpecialLwSwitchStatusAir"]["continuation"])

    def test_super_jump_punch(self):
        for sid in (225, 226):
            self.assertEqual(self.ev(sid, "air_jump_max"), [6])
            self.assertEqual(self.ev(sid, "flag1", 1), [6])
            self.assertTrue(all(e["double_advance"] for e in self.s[sid]["entry"]))
            self.assertEqual(self.s[sid]["duration"]["ends_on_tick"], [39])
        self.assertTrue(self.edge(225, 58) and self.edge(226, 59))
        self.assertEqual(self.s[59]["duration"]["ends_on_tick"], [25])     # 7 frames at speed 0.28

    def test_fireball(self):
        self.assertEqual(self.ev(223, "flag0", 1), [16])
        self.assertTrue(any(e["continuation"] for e in self.s[224]["entry"]))

    def test_aerials_and_landing(self):
        for sid in range(209, 214):
            self.assertTrue(any(e["double_advance"] for e in self.s[sid]["entry"]))
        self.assertEqual(self.ev(209, "flag1", 50), [3])
        for t in (10, 31, 219):
            self.assertTrue(self.edge(209, t))
        self.assertTrue(self.edge(20, 225) and self.edge(20, 207))          # jump squat: up-B, up-smash
        self.assertTrue(self.edge(22, 24) and self.edge(26, 228))

    def test_dash_roll_stale_flag(self):
        self.assertIn("flag1", self.s[156]["stale_flag_candidates"])
        hooks = {h["hook"] for e in self.s[156]["entry"] for h in e["exit_hooks"]}
        self.assertIn("ftCommonEscapeProcStatus", hooks)
        self.assertTrue(self.edge(15, 156))

    def test_port_animation_paths_absent_for_mario(self):
        for sid, st in self.s.items():
            if st["btt"].get("reachable"):
                anim = st["motion"].get("anim") or {}
                self.assertFalse(anim.get("payload_bit15"), st["name"])
                self.assertFalse(st["motion"].get("event32_anim"), st["name"])

    def test_reachability(self):
        self.assertTrue(self.s[158]["btt"]["reachable"])    # shield break
        self.assertFalse(self.s[84]["btt"]["reachable"])    # ledge
        self.assertTrue(self.s[66]["btt"]["reachable"])     # StopCeil

    def test_markdown_renders(self):
        md = ds.render_markdown(self.t)
        self.assertIn("| 228 | SpecialAirLw |", md)
        self.assertNotIn("| 84 |", md)


if __name__ == "__main__":
    unittest.main(verbosity=1)
