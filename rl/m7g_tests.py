"""M7g-a permanent tests: crossing-fixture contract, capture/import tooling, replay verification.

Unit cases (no game):
    unit_fixture_contract    m7g_fixture self-test (geometry derivation, script format, exact Track 1 import,
                             digests, evidence + classification on synthetic traces, fixture document validation)
    unit_geometry_frozen     decoded stage lines and derived regions equal the frozen table below; M7f's region
                             constants agree with the derived boundaries
    unit_import_formats      script / JSON Track 1 / JSON native / draft / M4 artifact imported exactly; the 7.43 TAS
                             (.btti) rejected naming its 8 non-Track 1 rows; nothing clamped
    unit_input_mapping       keyboard and XInput mapping truth tables, button priority, keymap validation
    unit_fixture_schema      docs/rl_crossing_fixture_m7g.schema.json agrees with the Python contract
    unit_build_document_assembly  PLUMBING ONLY: build_fixture's positive path with `verify` stubbed by the historical
                             TAS evidence -> the assembled document passes the validator and the full JSON schema;
                             the same crossing declared as the other route is KEPT as declared with a 'mismatch'
                             route flagged for review; a relabelled source is refused; an existing fixture is never
                             overwritten (written to STUB_NOT_A_FIXTURE, never rl/fixtures)
    unit_fixture_files       every rl/fixtures/m7g/*.json passes document validation (none exist yet: reported)
    unit_training_isolation  no training/evaluation module imports the m7g fixture/capture modules
    unit_historical_evidence evidence extractor on the M7f equivalence traces (read-only): the TAS crosses over the
                             ledge from the moving platform, none of the eight policy/random fixtures crosses, every
                             grounded step matches a decoded floor line
Game cases (fresh BattleShip processes, private runtime directories, one at a time):
    game_capture_scripted    scripted provider through the live capture loop (pause, frame advance, quit): autosave,
                             draft, script export, tick alignment, cleanup, user configuration untouched
    game_capture_visible     visible window, normal vs --realtime pacing: identical native trajectory
    game_capture_resume      resume at tick T: prefix replayed from tick 0 in the same fresh process, sequence joined
    game_verify_matrix       full verification matrix on a captured Track 1 sequence: cold x2, no-render, visible,
                             diagnostic off, parked 12 s, real M7c cold + promoted standby -> identical; not crossed
    game_build_refuses       `build` of a non-crossing draft writes no fixture, names the failed checks and leaves
                             every file of the capture recording byte-identical (size, mtime, sha256)
    game_capture_error       an error mid-session (window closed) still leaves draft, summary and an importable
                             autosave with every recorded action, and no process
    game_detector_control    the 7.43 TAS (raw rows; never a fixture) replayed: native left entry at consumed 359
                             over the ledge from the moving platform, IDs 6/8/1 after crossing, 10/446/447, 21 unsent
    game_m7a_seven_target    the only 7-target historical episode (M7a pilot, Track 1) reproduced exactly with target
                             IDs: {0,2,3,4,5,7,9}, never left of x -1650 -> not a crossing
    game_historical_six      an M7e six-target artifact through the quick matrix: identical, not crossed

Usage: python rl/m7g_tests.py [unit|game|<case> ...] [--root runs/m7g/_tests_<utc>]
Exit 0 all pass, 1 any failure.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7g_capture as cap  # noqa: E402
import m7g_fixture as fx  # noqa: E402

REPO_ROOT = RL_DIR.parent
TAS = REPO_ROOT / "tas_input_2" / "mario_743.btti"
TAS_NON_TRACK1_ROWS = [94, 143, 144, 177, 181, 215, 377, 434]
M7A_SEVEN = REPO_ROOT / "runs/m7a_pilot_n5/workers/w01/artifacts/episode_20260922T021311Z_50bbb545"
M7A_SEVEN_DIGEST = "9911103d8e65a8e0c971b43d16d5db7119bbc02f55f88e8e046936bb26a8dc18"
M7E_SIX = REPO_ROOT / ("runs/m7e/_eval/m7e_s0_v2/curve_t001228800/stochastic/workers/w02/artifacts/"
                       "episode_20260923T014311Z_3e92f774")
M7F_EQUIV = REPO_ROOT / "runs" / "m7f" / "_equiv" / "post_on"
SCHEMA_DOC = REPO_ROOT / "docs" / "rl_crossing_fixture_m7g.schema.json"

# Frozen decode of decomp/src/relocData/124_GRBonus1MarioFile2.c (index, group, kind, points, flags).
FROZEN_LINES = [
    (0, 1, "floor", [(-2100, 3000), (-1200, 3000)], 0), (1, 1, "floor", [(2100, -450), (3300, -450)], 0),
    (2, 1, "floor", [(2100, -1500), (1200, -1500)], 0x4000), (3, 1, "floor", [(-3900, -1950), (-2700, -1950)], 0),
    (4, 1, "floor", [(-1800, -2550), (2100, -2550)], 0), (5, 1, "ceil", [(-3600, -4050), (-3900, -4050)], 0),
    (6, 1, "ceil", [(2400, -2850), (-2100, -2850)], 0), (7, 1, "ceil", [(-3000, -2250), (-3900, -2250)], 0),
    (8, 1, "ceil", [(3300, -750), (2400, -750)], 0), (9, 1, "ceil", [(-1200, 2700), (-1800, 2700)], 0),
    (10, 1, "rwall", [(3300, -450), (3300, -750)], 0), (11, 1, "rwall", [(2400, -750), (2400, -2850)], 0),
    (12, 1, "rwall", [(-1200, 3000), (-1200, 2700)], 0), (13, 1, "rwall", [(-1800, 2700), (-1800, -2550)], 0),
    (14, 1, "rwall", [(-2700, -1950), (-2700, -2850), (-3600, -3750), (-3600, -4050)], 0),
    (15, 1, "lwall", [(-3900, -2250), (-3900, -1950)], 0),
    (16, 1, "lwall", [(-3900, -4050), (-3900, -3750), (-3000, -2850), (-3000, -2250)], 0),
    (17, 1, "lwall", [(-2100, -2850), (-2100, 3000)], 0), (18, 1, "lwall", [(2100, -2550), (2100, -450)], 0),
    (19, 2, "floor", [(600, 300), (-600, 300)], 0x4000),
]


class CheckFailed(AssertionError):
    pass


def check(cond: bool, message: str) -> None:
    if not cond:
        raise CheckFailed(message)


class Suite:
    def __init__(self, root: Path):
        self.root = root

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d


# -- unit -------------------------------------------------------------------------------------------------

def unit_fixture_contract(s: Suite) -> Dict[str, Any]:
    check(fx.self_test() == 0, "m7g_fixture self-test failed")
    return {"self_test": "PASS"}


def unit_geometry_frozen(s: Suite) -> Dict[str, Any]:
    import m7f_targets as mt

    geo = fx.decode_stage_geometry()
    got = [(ln.index, ln.group, ln.kind, [tuple(int(v) for v in p) for p in ln.points], ln.flags) for ln in geo.lines]
    check(got == FROZEN_LINES, f"decoded lines differ from the frozen table: {got}")
    d = geo.derived
    check((d["left_boundary_x"], d["wall_right_face_x"], d["wall_top_y"]) == (-2100.0, -1800.0, 3000.0), str(d))
    check((mt.WALL_LEFT_FACE_X, mt.WALL_RIGHT_FACE_X) == (d["left_boundary_x"], d["wall_right_face_x"]),
          "M7f region constants disagree with the derived boundaries")
    check(d["moving_platform_surface_y_range"] == [1800.0, 3600.0] and d["moving_platform_x_span"] == [2100.0, 3300.0],
          "moving platform span")
    return {"lines": len(got), "derived": d, "source_sha256": geo.source_sha256}


def unit_import_formats(s: Suite) -> Dict[str, Any]:
    d = s.dir("unit_import_formats")
    seq = [(0, 0)] * 3 + [(2, 3)] * 2 + [(6, 7)] + [(4, 4)] * 4
    native = fx.track1_to_native(seq)
    (d / "a.txt").write_text(fx.format_script(seq), encoding="utf-8")
    (d / "b.json").write_text(json.dumps([list(a) for a in seq]), encoding="utf-8")
    (d / "c.json").write_text(json.dumps([list(r) for r in native]), encoding="utf-8")
    (d / "d.json").write_text(json.dumps(fx.make_draft(seq, {"kind": "imported"})), encoding="utf-8")
    kinds = {}
    for name in ("a.txt", "b.json", "c.json", "d.json"):
        got, meta = fx.load_sequence(d / name)
        check(got == seq, f"{name}: imported sequence differs")
        kinds[name] = meta["kind"]
    bad = json.loads((d / "d.json").read_text(encoding="utf-8"))
    bad["sequence"]["track1_digest"] = "0" * 64
    (d / "e.json").write_text(json.dumps(bad), encoding="utf-8")
    try:
        fx.load_sequence(d / "e.json")
        raise CheckFailed("draft with a wrong digest accepted")
    except fx.FixtureError:
        pass
    (d / "f.json").write_text(json.dumps([list(r) for r in native[:4]] + [[0, 81, 0]]), encoding="utf-8")
    try:
        fx.load_sequence(d / "f.json")
        raise CheckFailed("analog stick 81 accepted")
    except fx.FixtureError as exc:
        check("native row 4" in str(exc), str(exc))
    (d / "g.json").write_text(json.dumps([list(r) for r in native[:2]] + [[0, 80.7, 0]]), encoding="utf-8")
    try:
        fx.load_sequence(d / "g.json")
        raise CheckFailed("float stick 80.7 truncated into Track 1")
    except fx.FixtureError as exc:
        check("native row 2" in str(exc), str(exc))
    # Windows encodings: UTF-8 with BOM and UTF-16 (PowerShell redirection) are read, not rejected
    text = fx.format_script(seq)
    (d / "h_bom.txt").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    (d / "i_utf16.txt").write_bytes(text.encode("utf-16"))
    for name in ("h_bom.txt", "i_utf16.txt"):
        check(fx.load_sequence(d / name)[0] == seq, f"{name} not read")
    # the capture autosave (session.jsonl) is importable, so a crashed session is never lost
    log_lines = [json.dumps({"format": fx.CAPTURE_LOG_FORMAT, "action_contract": fx.track1_contract(),
                             "input": "keyboard", "resumed_from": None})]
    log_lines += [json.dumps({"i": i, "s": a[0], "b": a[1], "consumed_tick": i}) for i, a in enumerate(seq)]
    (d / "j_session.jsonl").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    got, meta = fx.load_sequence(d / "j_session.jsonl")
    check(got == seq and meta["source_kind"] == "user_recorded", f"autosave import {meta.get('source_kind')}")
    # no tool overwrites an existing file or writes into a non-empty directory (a captured draft is never destroyed)
    victim = d / "d.json"
    snapshot = victim.read_bytes()
    for argv in (["import", str(d / "a.txt"), "--out", str(victim)], ["export-script", str(d / "a.txt"), "--out",
                                                                      str(victim)]):
        try:
            cap.main(argv)
            raise CheckFailed(f"{argv[0]} overwrote an existing file")
        except SystemExit as exc:
            check("refusing to overwrite" in str(exc), str(exc))
    check(victim.read_bytes() == snapshot, "the existing file changed")
    import m7g_crossing as cr

    try:
        cr.verify(seq, d)  # d holds files: refused before any process is launched
        raise CheckFailed("verify wrote into a non-empty directory")
    except RuntimeError as exc:
        check("not empty" in str(exc), str(exc))
    try:
        fx.load_sequence(TAS)
        raise CheckFailed("the 7.43 TAS was accepted as a Track 1 sequence")
    except fx.FixtureError as exc:
        check("native row 94" in str(exc), f"first non-Track 1 row not named: {exc}")
    from btti_replay import read_btti_rows

    rows = [(r.buttons, r.stick_x, r.stick_y) for r in read_btti_rows(str(TAS))]
    check(fx.non_track1_rows(rows) == TAS_NON_TRACK1_ROWS, f"TAS non-Track 1 rows {fx.non_track1_rows(rows)}")
    art = None
    if M7E_SIX.is_dir():
        aseq, ameta = fx.load_sequence(M7E_SIX)
        check(fx.native_action_digest(fx.track1_to_native(aseq)) == ameta["recorded_native_action_digest"],
              "artifact import does not reproduce the recorded native_action_digest")
        art = {"length": len(aseq), "digest": ameta["recorded_native_action_digest"][:16]}
    return {"kinds": kinds, "tas_non_track1_rows": TAS_NON_TRACK1_ROWS, "artifact": art or "not present (skipped)"}


def unit_input_mapping(s: Suite) -> Dict[str, Any]:
    km = cap.validate_keymap(cap.DEFAULT_KEYMAP)

    def kb(down, prev=(), pr=None):
        return cap.keyboard_controls(set(down), set(prev), km, pr or cap.ButtonPriority())

    dirs = {(): 0, ("RIGHT",): 1, ("RIGHT", "UP"): 2, ("UP",): 3, ("LEFT", "UP"): 4, ("LEFT",): 5,
            ("LEFT", "DOWN"): 6, ("DOWN",): 7, ("RIGHT", "DOWN"): 8, ("LEFT", "RIGHT"): 0, ("UP", "DOWN"): 0,
            ("LEFT", "RIGHT", "UP"): 3}
    for keys, idx in dirs.items():
        check(kb(keys).stick == idx, f"keys {keys} -> stick {kb(keys).stick}, expected {idx}")
    for name, key in km["buttons"].items():
        check(kb([key]).button == cap.BUTTON_INDEX[name], f"button {name}")
    pr = cap.ButtonPriority()
    check(kb(["X"], pr=pr).button == 1 and kb(["X", "SPACE"], ["X"], pr).button == 3
          and kb(["X", "SPACE"], ["X", "SPACE"], pr).button == 3 and kb(["X"], ["X", "SPACE"], pr).button == 1,
          "most-recently-pressed button priority")
    check(kb(["CTRL", "Q"], ["CTRL"]).quit and not kb(["CTRL", "Q"], ["CTRL", "Q"]).quit and not kb(["Q"]).quit,
          "Ctrl+Q fires once on the press edge only")
    check(kb(["P"]).pause_toggle and not kb(["P"], ["P"]).pause_toggle and kb(["PERIOD"]).advance, "controls")
    for bad in ({**cap.DEFAULT_KEYMAP, "buttons": {**cap.DEFAULT_KEYMAP["buttons"], "A": "C"}},
                {**cap.DEFAULT_KEYMAP, "stick": {**cap.DEFAULT_KEYMAP["stick"], "up": "NOPE"}},
                {**cap.DEFAULT_KEYMAP, "buttons": {k: v for k, v in cap.DEFAULT_KEYMAP["buttons"].items() if k != "Z"}}):
        try:
            cap.validate_keymap(bad)
            raise CheckFailed(f"invalid keymap accepted: {bad}")
        except ValueError:
            pass
    sectors = {(32767, 0): 1, (23170, 23170): 2, (0, 32767): 3, (-23170, 23170): 4, (-32767, 0): 5,
               (-23170, -23170): 6, (0, -32767): 7, (23170, -23170): 8, (10000, 0): 0, (0, -10000): 0}
    for (lx, ly), idx in sectors.items():
        check(cap.xinput_stick(lx, ly, 0) == idx, f"xinput ({lx},{ly}) -> {cap.xinput_stick(lx, ly, 0)}")
    check(cap.xinput_stick(0, 0, cap.XI["DPAD_LEFT"] | cap.XI["DPAD_UP"]) == 4
          and cap.xinput_stick(32767, 0, cap.XI["DPAD_DOWN"]) == 7, "D-pad overrides the stick")
    pr = cap.ButtonPriority()
    c = cap.xinput_controls(0, 0, cap.XI["A"] | cap.XI["START"], 0, 0, pr)
    check(c.button == 1 and c.pause_toggle and not cap.xinput_controls(0, 0, cap.XI["START"], 0, cap.XI["START"],
                                                                         pr).pause_toggle, "xinput edges")
    check(cap.xinput_controls(0, 0, 0, 200, 0, cap.ButtonPriority()).button == 7, "left trigger = Z")
    return {"keyboard_directions": len(dirs), "xinput_sectors": len(sectors)}


def unit_fixture_schema(s: Suite) -> Dict[str, Any]:
    doc = json.loads(SCHEMA_DOC.read_text(encoding="utf-8"))
    check(doc["properties"]["contract"]["const"] == fx.FIXTURE_CONTRACT, "schema contract const")
    check(sorted(doc["required"]) == sorted(fx.FIXTURE_TOP_KEYS), f"schema required keys {doc['required']}")
    check(doc.get("additionalProperties") is False, "schema must forbid additional top-level keys")
    check(doc["properties"]["crossing"]["enum"] == list(fx.CROSSINGS), "crossing enum")
    check(doc["properties"]["source"]["properties"]["kind"]["enum"] == list(fx.SOURCES), "source enum")
    check(doc["properties"]["action_contract"]["const"] == fx.track1_contract(), "action contract")
    check(doc["properties"]["usage_restrictions"]["const"] == fx.USAGE_RESTRICTIONS, "usage restrictions")
    start = doc["properties"]["start"]["properties"]
    check(start["tick"]["const"] == 0 and start["hidden_prefix"]["const"] is False, "start constraints")
    return {"required": len(doc["required"])}


def schema_problems(instance: Any, schema: Mapping[str, Any], where: str = "$") -> List[str]:
    """The JSON Schema keywords docs/rl_crossing_fixture_m7g.schema.json uses (no third-party dependency):
    type, const, enum, pattern, minimum, maximum, required, properties, additionalProperties false, items,
    prefixItems, minItems, maxItems."""
    import re

    out: List[str] = []
    types = schema.get("type")
    if types is not None:
        tl = types if isinstance(types, list) else [types]
        ok = {"object": isinstance(instance, dict), "array": isinstance(instance, list),
              "string": isinstance(instance, str), "null": instance is None, "boolean": isinstance(instance, bool),
              "integer": isinstance(instance, int) and not isinstance(instance, bool),
              "number": isinstance(instance, (int, float)) and not isinstance(instance, bool)}
        if not any(ok[t] for t in tl):
            return [f"{where}: type {type(instance).__name__} not in {tl}"]
    if "const" in schema and (instance != schema["const"] or type(instance) is not type(schema["const"])):
        out.append(f"{where}: {instance!r} != const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        out.append(f"{where}: {instance!r} not in {schema['enum']}")
    if "pattern" in schema and isinstance(instance, str) and not re.search(schema["pattern"], instance):
        out.append(f"{where}: {instance!r} does not match {schema['pattern']}")
    if "minimum" in schema and isinstance(instance, (int, float)) and instance < schema["minimum"]:
        out.append(f"{where}: {instance} < {schema['minimum']}")
    if "maximum" in schema and isinstance(instance, (int, float)) and instance > schema["maximum"]:
        out.append(f"{where}: {instance} > {schema['maximum']}")
    if isinstance(instance, dict):
        out += [f"{where}: missing {k}" for k in schema.get("required", []) if k not in instance]
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            out += [f"{where}: unexpected {k}" for k in instance if k not in props]
        for k, sub in props.items():
            if k in instance:
                out += schema_problems(instance[k], sub, f"{where}.{k}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            out.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            out.append(f"{where}: more than {schema['maxItems']} items")
        for i, item in enumerate(instance):
            pre = schema.get("prefixItems")
            if pre and i < len(pre):
                out += schema_problems(item, pre[i], f"{where}[{i}]")
            elif "items" in schema:
                out += schema_problems(item, schema["items"], f"{where}[{i}]")
            if len(out) > 20:
                break
    return out


def unit_build_document_assembly(s: Suite) -> Dict[str, Any]:
    """PLUMBING TEST ONLY: exercises build_fixture's positive path (document assembly, source rules, validator,
    schema) with `verify` stubbed by the native evidence of the historical TAS trace, because no crossing Track 1
    sequence exists yet. The output goes to a STUB_NOT_A_FIXTURE directory in the test root, never rl/fixtures;
    it is not evidence of anything."""
    import m7f_trace as tr
    import m7g_crossing as cr

    p = M7F_EQUIV / "tas_no_render_raphnet.json.gz"
    if not p.is_file():
        return {"skipped": "historical TAS trace not present"}
    t = tr.read_trace(p)
    geo = fx.decode_stage_geometry()
    ev = fx.crossing_evidence(geo, t["initial"], t["steps"], submitted=len(t["steps"]))
    n = len(t["steps"])
    d = s.dir("unit_build_document_assembly")
    stub_dir = d / "STUB_NOT_A_FIXTURE"
    draft = fx.make_draft([(0, 0)] * n, {"kind": "independently_searched", "note": "STUB: plumbing test only"})
    (d / "draft").mkdir()
    (d / "draft" / "draft.json").write_text(json.dumps(draft), encoding="utf-8")
    names = ["cold_nrr", "cold_nrr_r2", "cold_nr", "visible", "diag_off", "parked", "standby_ep1_cold_start",
             "standby_ep2_standby_promoted"]

    def stub_verify(seq: Any, out: Path, **_kw: Any) -> Dict[str, Any]:
        return {"checks": {"all_actions_consumed": {"ok": True}, "native_left_region_entry": {"ok": True}},
                "classification": fx.classify_crossing(ev, geo), "crossed": True, "user_config_unchanged": True,
                "leftover_battleship": [], "gameplay_config": fx.gameplay_config(cr.USER_CONFIG),
                "executable_sha256": "0" * 64, "revisions": {"head": "stub"}, "utc": "stub",
                "geometry": fx.geometry_summary(geo), "evidence": ev, "executions": len(names), "replay_ok": True,
                "runs": {k: {"submitted": n, "trajectory_digest": "stub", "policy_obs_v1_digest": "stub",
                             "returns": {}} for k in names}}

    schema = json.loads(SCHEMA_DOC.read_text(encoding="utf-8"))
    original = cr.verify
    cr.verify = stub_verify
    try:
        path, rep = cr.build_fixture(d / "draft" / "draft.json", "upper_moving_platform", "independently_searched",
                                     out_root=d / "verify", fixture_dir=stub_dir)
        # a genuine crossing declared as the other route is written AS DECLARED and flagged, never dropped/relabelled
        kept, rep2 = cr.build_fixture(d / "draft" / "draft.json", "lower_precision", "independently_searched",
                                      out_root=d / "verify2", fixture_dir=d / "STUB_NOT_A_FIXTURE_mismatch")
        try:  # the same recording can never be both a lower and an upper fixture
            cr.build_fixture(d / "draft" / "draft.json", "lower_precision", "independently_searched",
                             out_root=d / "verify5", fixture_dir=stub_dir)
            raise CheckFailed("one sequence preserved as both crossings")
        except fx.FixtureError as exc:
            check("already preserved as another crossing" in str(exc), str(exc))
        mislabel, rep3 = cr.build_fixture(d / "draft" / "draft.json", "upper_moving_platform", "user_recorded",
                                          out_root=d / "verify3", fixture_dir=d / "STUB_mislabel")
        before = path.read_bytes() if path else b""
        try:
            cr.build_fixture(d / "draft" / "draft.json", "upper_moving_platform", "independently_searched",
                             out_root=d / "verify4", fixture_dir=stub_dir)
            raise CheckFailed("an existing fixture was rebuilt over")
        except fx.FixtureError as exc:
            check("not overwritten" in str(exc), str(exc))
    finally:
        cr.verify = original
    check(path is not None and path.parent == stub_dir, f"positive path wrote no document: {rep['build']}")
    check(path.read_bytes() == before, "the existing fixture changed")
    doc = json.loads(path.read_text(encoding="utf-8"))
    check(fx.validate_fixture_document(doc) == [], f"assembled document invalid: {fx.validate_fixture_document(doc)}")
    sp = schema_problems(doc, schema)
    check(not sp, f"assembled document violates the JSON schema: {sp}")
    check(doc["route"]["agreement"] == "confirmed" and not doc["route"]["review_required"], str(doc["route"]))
    check(kept is not None and kept.name.startswith("lower_precision_"), f"mismatched crossing not kept: {rep2['build']}")
    kdoc = json.loads(kept.read_text(encoding="utf-8"))
    check(kdoc["crossing"] == "lower_precision" and kdoc["route"]["agreement"] == "mismatch"
          and kdoc["route"]["review_required"] and kdoc["route"]["classifier"]["identity"] == "upper_moving_platform"
          and kdoc["route"]["takeoff"]["surface"] == "moving_platform"
          and fx.validate_fixture_document(kdoc) == [] and not schema_problems(kdoc, schema),
          f"kept mismatch document: {kdoc['route']}")
    check(len(kdoc["evidence"]["trajectory"]["rows"]) == n and kdoc["evidence"]["surface_runs"], "trajectory evidence")
    check(mislabel is None and any("contradicts" in x for x in rep3["build"]["problems"]), "source relabel accepted")
    check("\\" not in json.dumps(doc["source"]) + json.dumps(doc["provenance"].get("verification_dir")),
          "machine-specific backslash paths in the document")
    return {"confirmed": path.name, "kept_for_review": kept.name, "schema_ok": True,
            "note": "stubbed verify; STUB_NOT_A_FIXTURE output only"}


def unit_fixture_files(s: Suite) -> Dict[str, Any]:
    from m7g_crossing import FIXTURE_DIR

    files = sorted(FIXTURE_DIR.glob("*.json")) if FIXTURE_DIR.is_dir() else []
    out = {}
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        problems = fx.validate_fixture_document(doc)
        check(not problems, f"{f.name}: {problems}")
        check(f.stem == doc["fixture_id"], f"{f.name}: file name != fixture_id")
        out[f.name] = {"crossing": doc["crossing"], "length": doc["sequence"]["length"],
                       "route_agreement": doc["route"]["agreement"], "review_required": doc["route"]["review_required"],
                       "takeoff": (doc["route"]["takeoff"] or {}).get("surface")}
    digests = [json.loads(f.read_text(encoding="utf-8"))["sequence"]["native_action_digest"] for f in files]
    check(len(digests) == len(set(digests)), "one sequence is preserved under more than one fixture (lower and upper "
                                             "fixtures must stay distinct)")
    by_crossing = {c: sum(1 for v in out.values() if v["crossing"] == c) for c in fx.CROSSINGS}
    return {"fixtures": out, "by_crossing": by_crossing,
            "status": "no fixture captured yet (fixture validation BLOCKED on user input)" if not files else "validated"}


def unit_training_isolation(s: Suite) -> Dict[str, Any]:
    import re

    # any module name of the M7g-a tooling, or a path to the fixture directory in any separator / Path-join form
    pattern = re.compile(r"m7g_(fixture|capture|crossing)|FIXTURE_DIR|fixtures['\"\s,/\\()]*m7g", re.IGNORECASE)
    files = [p for p in RL_DIR.rglob("*.py") if "__pycache__" not in p.parts and not p.name.startswith("m7g_")]
    files += list((RL_DIR / "configs").rglob("*.toml")) + list((REPO_ROOT / "tools").glob("*.py"))
    offenders = sorted(str(p.relative_to(REPO_ROOT)) for p in files
                       if pattern.search(p.read_text(encoding="utf-8", errors="replace")))
    check(not offenders, f"files outside M7g-a reference the crossing fixtures: {offenders}")
    probe = ['FIXTURE_DIR = RL_DIR / "fixtures" / "m7g"', "rl\\\\fixtures\\\\m7g\\\\a.json", "import m7g_fixture"]
    check(all(pattern.search(t) for t in probe), "isolation pattern misses a known reference form")
    return {"checked": len(files), "offenders": offenders}


def unit_historical_evidence(s: Suite) -> Dict[str, Any]:
    import m7f_trace as tr

    files = sorted(M7F_EQUIV.glob("*.json.gz")) if M7F_EQUIV.is_dir() else []
    if not files:
        return {"skipped": f"{M7F_EQUIV} not present (historical run data is not in a fresh clone)"}
    names = [p.name for p in files]
    check(sum(n.startswith("fx_") for n in names) == 8 and sum(n.startswith("tas_") for n in names) == 3,
          f"the M7f equivalence set is incomplete: {names}")
    geo = fx.decode_stage_geometry()
    out = {}
    grounded = 0
    for p in files:
        t = tr.read_trace(p)
        ev = fx.crossing_evidence(geo, t["initial"], t["steps"])
        grounded += sum(1 for st in t["steps"] if fx.classify_ground(geo, st["observation"]) is not None)
        check(ev["ground_unmatched_steps"] == 0, f"{p.name}: grounded step on no decoded floor {ev['ground_unmatched_first']}")
        if p.name.startswith("tas_"):
            check(ev["crossed"] and ev["first_left_entry"]["consumed_tick"] == 359
                  and fx.classify_crossing(ev, geo)["identity"] == "upper_moving_platform"
                  and ev["moving_platform"]["riding_steps"] > 0, f"{p.name}: TAS evidence {ev['first_left_entry']}")
        else:
            check(not ev["crossed"] and ev["min_x"]["x"] >= -1650.0, f"{p.name}: unexpected crossing")
        out[p.name] = {"crossed": ev["crossed"], "min_x": ev["min_x"]["x"]}
    return {"traces": out, "grounded_steps_matched": grounded}


# -- game -------------------------------------------------------------------------------------------------

def _no_battleship() -> None:
    from m7_runtime import list_processes_named

    others = list_processes_named()
    check(not others, f"BattleShip already running: {others}")


C = cap.Controls
SCRIPT = ([C(stick=5)] * 40 + [C(stick=5, button=3)] * 2 + [C(stick=5)] * 20 + [C(pause_toggle=True)] + [C()] * 5
          + [C(stick=1, advance=True)] * 3 + [C(pause_toggle=True)] + [C(stick=1, button=1)] * 10 + [C()] * 20)
SCRIPT_ACTIONS = 40 + 2 + 20 + 3 + 1 + 10 + 20  # the resume poll steps too; paused polls without advance do not


def _capture(s: Suite, name: str, script: Sequence[Any], **kw: Any) -> Dict[str, Any]:
    _no_battleship()
    from m7_runtime import list_processes_named

    summary = cap.capture(cap.ScriptedInput(script), s.root / name, quiet=True, **kw)
    check(not list_processes_named(), "capture left a BattleShip process running")
    check(summary["user_config_unchanged"], "user configuration changed")
    return summary


def game_capture_scripted(s: Suite) -> Dict[str, Any]:
    summ = _capture(s, "capture_scripted", SCRIPT, mode="no_render_raphnet")
    out = s.root / "capture_scripted"
    check(summ["actions"] == SCRIPT_ACTIONS and summ["end_reason"] == "quit" and summ["pauses"] == 1
          and summ["advances"] == 3, f"summary {summ['actions']} {summ['end_reason']} {summ['pauses']} {summ['advances']}")
    lines = (out / "session.jsonl").read_text(encoding="utf-8").splitlines()
    check(len(lines) == SCRIPT_ACTIONS + 1 and all(json.loads(l)["consumed_tick"] == i for i, l in enumerate(lines[1:])),
          "autosave log is not one line per consumed tick")
    seq, meta = fx.load_sequence(out / "draft.json")
    check(fx.parse_script((out / "draft.txt").read_text(encoding="utf-8")) == seq, "script export != draft")
    expect = [a.action for a in SCRIPT[:62]] + [(1, 0)] * 3 + [(0, 0)] + [(1, 1)] * 10 + [(0, 0)] * 20
    check(seq == expect, "recorded Track 1 sequence differs from the provider's actions")
    trace = __import__("m7g_crossing").read_gz(out / "capture_trace.json.gz")
    check([r["consumed_tick"] for r in trace["steps"]] == list(range(SCRIPT_ACTIONS)), "capture ticks")
    check(trace["initial"]["observation"]["input_tick"] == 0 and "targets" in trace["initial"], "tick-0 observe")
    return {"actions": summ["actions"], "track1_digest": summ["track1_digest"][:16],
            "trajectory_digest": summ["trajectory_digest"][:16], "step_ms_median": summ["step_ms_median"]}


def game_capture_visible(s: Suite) -> Dict[str, Any]:
    script = [C(stick=1)] * 60 + [C(stick=2, button=3)] * 3 + [C(stick=1)] * 57
    a = _capture(s, "capture_visible", script, mode="normal")
    b = _capture(s, "capture_visible_realtime", script, mode="normal", realtime=True)
    check(a["actions"] == b["actions"] == 120, "action counts")
    check(a["trajectory_digest"] == b["trajectory_digest"], "realtime pacing changed the native trajectory")
    return {"visible_step_ms_median": a["step_ms_median"], "realtime_step_ms_median": b["step_ms_median"],
            "trajectory_digest": a["trajectory_digest"][:16]}


def game_capture_resume(s: Suite) -> Dict[str, Any]:
    base = _capture(s, "resume_base", [C(stick=1)] * 50 + [C(stick=3, button=0)] * 5 + [C(stick=5)] * 45,
                    mode="no_render_raphnet")
    # the capture pauses at the hand-over; the player resumes with P, then plays 30 ticks
    res = _capture(s, "resume_cont", [C()] * 3 + [C(pause_toggle=True, stick=5, button=2)]
                   + [C(stick=5, button=2)] * 9 + [C()] * 20, mode="no_render_raphnet",
                   resume=((REPO_ROOT / base["draft"]), 55))
    full, _ = fx.load_sequence((REPO_ROOT / base["draft"]))
    new, _ = fx.load_sequence((REPO_ROOT / res["draft"]))
    check(res["prefix_replayed"] == 55 and new[:55] == full[:55] and len(new) == 85 and res["pauses"] == 1,
          f"joined sequence: prefix {res['prefix_replayed']} length {len(new)} pauses {res['pauses']}")
    check(new[55:] == [(5, 2)] * 10 + [(0, 0)] * 20, "nothing may be recorded while paused at the hand-over")
    import m7g_crossing as cr

    ta, tb = cr.read_gz(s.root / "resume_base" / "capture_trace.json.gz"), cr.read_gz(
        s.root / "resume_cont" / "capture_trace.json.gz")
    check(fx.trajectory_digest(ta["initial"], ta["steps"][:55]) == fx.trajectory_digest(tb["initial"], tb["steps"][:55]),
          "the replayed prefix did not reproduce the original trajectory")
    draft = json.loads((REPO_ROOT / res["draft"]).read_text(encoding="utf-8"))
    check(draft["source"]["resumed_from"]["prefix_length"] == 55 and draft["start"]["hidden_prefix"] is False,
          "resume provenance")
    return {"prefix": 55, "length": len(new)}


def game_verify_matrix(s: Suite) -> Dict[str, Any]:
    import m7g_crossing as cr

    summ = _capture(s, "verify_capture", SCRIPT, mode="no_render_raphnet")
    seq, _ = fx.load_sequence((REPO_ROOT / summ["draft"]))
    rep = cr.verify(seq, s.root / "verify_matrix", capture_trajectory_digest=summ["trajectory_digest"])
    _no_battleship()
    failed = [n for n, c in rep["checks"].items() if not c["ok"]]
    check(rep["replay_ok"] and failed == ["native_left_region_entry"], f"failed checks {failed}")
    check(rep["executions"] == 8 and len({r["trajectory_digest"] for r in rep["runs"].values()}) == 1, "8 identical runs")
    check(rep["user_config_unchanged"] and not rep["leftover_battleship"], "integrity")
    return {"executions": rep["executions"], "trajectory_digest": rep["runs"]["cold_nrr"]["trajectory_digest"][:16],
            "returns": rep["runs"]["cold_nrr"]["returns"], "crossed": rep["crossed"], "checks": len(rep["checks"])}


def game_build_refuses(s: Suite) -> Dict[str, Any]:
    import m7g_crossing as cr

    import hashlib

    summ = _capture(s, "refuse_capture", [C(stick=1)] * 30, mode="no_render_raphnet")
    cap_dir = s.root / "refuse_capture"

    def fingerprint() -> Dict[str, Any]:  # every file of the capture recording (runtime copy excluded: not evidence)
        return {str(p.relative_to(cap_dir)): (p.stat().st_size, p.stat().st_mtime_ns,
                                             hashlib.sha256(p.read_bytes()).hexdigest())
                for p in sorted(cap_dir.rglob("*")) if p.is_file() and "runtime" not in p.relative_to(cap_dir).parts}

    before = fingerprint()
    fixtures = s.dir("refuse_fixture_dir")
    path, rep = cr.build_fixture((REPO_ROOT / summ["draft"]), "lower_precision", "imported",
                                 out_root=s.root / "refuse_verify", fixture_dir=fixtures)
    check(path is None and not any(fixtures.iterdir()), "a fixture was written for a non-crossing sequence")
    probs = rep["build"]["problems"]
    check("native_left_region_entry" in probs
          and any("contradicts the draft's recorded source kind 'scripted'" in p for p in probs), f"problems {probs}")
    check(rep["build"]["route"]["classifier"]["identity"] is None, "route recorded for the refused sequence")
    after = fingerprint()
    check(before == after and {"draft.json", "draft.txt", "session.jsonl", "capture_trace.json.gz", "summary.json"}
          <= set(after), f"the failed build touched the capture recording: {set(before) ^ set(after)}")
    # a build whose verification output would land inside the capture directory is refused before anything runs
    try:
        cr.build_fixture(cap_dir / "draft.json", "lower_precision", "imported", out_root=cap_dir / "v",
                         fixture_dir=fixtures)
        raise CheckFailed("verification output inside the capture directory accepted")
    except fx.FixtureError as exc:
        check("inside the draft's directory" in str(exc), str(exc))
    seq, _ = fx.load_sequence(cap_dir / "draft.json")
    try:  # no tool writes inside a capture recording, even into a new sub-directory or a new file name
        cr.verify(seq, cap_dir / "sub")
        raise CheckFailed("verify output inside the capture recording accepted")
    except fx.FixtureError as exc:
        check("inside the capture recording" in str(exc), str(exc))
    for argv in (["import", str(cap_dir / "draft.json"), "--out", str(cap_dir / "reimported.json")],
                 ["export-script", str(cap_dir / "draft.json"), "--out", str(cap_dir / "copy.txt")]):
        try:
            cap.main(argv)
            raise CheckFailed(f"{argv[0]} wrote inside the capture recording")
        except SystemExit as exc:
            check("inside the capture recording" in str(exc), str(exc))
    check(fingerprint() == before and not (cap_dir / "sub").exists(), "a refused tool touched the capture recording")
    return {"problems": probs, "capture_files_unchanged": len(after)}


class _FailingInput(cap.ScriptedInput):
    """Plays a script, then raises as if the game window had been closed mid-session."""

    def poll(self) -> "cap.Controls":
        if self.i >= len(self.controls):
            raise ConnectionError("simulated: game window closed")
        return super().poll()


def game_capture_error(s: Suite) -> Dict[str, Any]:
    _no_battleship()
    from m7_runtime import list_processes_named

    out = s.root / "capture_error"
    try:
        cap.capture(_FailingInput([C(stick=1)] * 25), out, mode="no_render_raphnet", quiet=True)
        raise CheckFailed("the capture swallowed the error")
    except ConnectionError:
        pass
    check(not list_processes_named(), "capture left a BattleShip process running after an error")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    seq, _ = fx.load_sequence(out / "draft.json")
    auto, _ = fx.load_sequence(out / "session.jsonl")
    check(summary["end_reason"].startswith("error: ConnectionError") and seq == auto == [(1, 0)] * 25,
          f"draft after an error: {summary['end_reason']} {len(seq)}")
    return {"end_reason": summary["end_reason"], "actions_kept": len(seq)}


def game_detector_control(s: Suite) -> Dict[str, Any]:
    import m7g_crossing as cr
    from btti_replay import read_btti_rows

    _no_battleship()
    rows = [(r.buttons, r.stick_x, r.stick_y) for r in read_btti_rows(str(TAS))]
    tr = cr.replay(rows, s.root / "detector_control", mode="no_render_raphnet")
    geo = fx.decode_stage_geometry()
    ev = fx.crossing_evidence(geo, tr["initial"], tr["steps"], submitted=tr["submitted"])
    cls = fx.classify_crossing(ev, geo)
    check(not tr["problems"] and tr["submitted"] == 447 and tr["unsent"] == 21, f"{tr['problems']} {tr['submitted']}")
    check(tr["result"]["targets_broken"] == 10 and tr["result"]["completion_time_passed"] == 446
          and tr["result"]["completion_input_tick"] == 447 and tr["steps"][-1]["consumed_tick"] == 446, "clear clocks")
    check(ev["crossed"] and ev["first_left_entry"]["consumed_tick"] == 359 and ev["crossing_path"] == "over_ledge",
          f"left entry {ev['first_left_entry']}")
    check(cls["identity"] == "upper_moving_platform" and ev["moving_platform"]["riding_steps"] > 0, str(cls))
    check(ev["targets"]["broken_after_first_left_entry"] == [6, 8, 1] and ev["targets"]["diag_ok"], str(ev["targets"]))
    return {"first_left_entry": ev["first_left_entry"], "min_x": ev["min_x"]["x"], "classification": cls,
            "note": "detector control only; the TAS is not Track 1 and is never a fixture or demonstration"}


def game_m7a_seven_target(s: Suite) -> Dict[str, Any]:
    import m7g_crossing as cr
    from run_artifacts import read_artifact

    if not M7A_SEVEN.is_dir():
        return {"skipped": "historical M7a artifact not present"}
    _no_battleship()
    seq, meta = fx.load_sequence(M7A_SEVEN)
    rows = fx.track1_to_native(seq)
    tr = cr.replay(rows, s.root / "m7a_seven", mode="no_render_raphnet")
    check(tr["action_digest"] == M7A_SEVEN_DIGEST == meta["recorded_native_action_digest"], "digest")
    final = {k: v for k, v in read_artifact(M7A_SEVEN).metadata["final_observation"].items() if k != "host_frame"}
    got = {k: v for k, v in tr["steps"][-1]["observation"].items() if k != "host_frame"}
    check(final == got, "final observation not reproduced")
    ev = fx.crossing_evidence(fx.decode_stage_geometry(), tr["initial"], tr["steps"])
    check(sorted(ev["targets"]["broken_ids"]) == [0, 2, 3, 4, 5, 7, 9] and not ev["crossed"]
          and ev["min_x"]["x"] == -1650.0 and ev["terminal"]["kind"] == "native_failure", str(ev["targets"]))
    return {"actions": len(seq), "broken_ids": ev["targets"]["broken_ids"], "min_x": ev["min_x"]["x"]}


def game_historical_six(s: Suite) -> Dict[str, Any]:
    import m7g_crossing as cr

    if not M7E_SIX.is_dir():
        return {"skipped": "historical M7e artifact not present"}
    _no_battleship()
    seq, _ = fx.load_sequence(M7E_SIX)
    rep = cr.verify(seq, s.root / "historical_six", quick=True)
    check(rep["replay_ok"] and not rep["crossed"], f"{rep['checks']}")
    check(sorted(rep["evidence"]["targets"]["broken_ids"]) == [0, 3, 4, 5, 7, 9], "six-target set")
    return {"length": len(seq), "broken_ids": rep["evidence"]["targets"]["broken_ids"]}


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_fixture_contract": unit_fixture_contract, "unit_geometry_frozen": unit_geometry_frozen,
    "unit_import_formats": unit_import_formats, "unit_input_mapping": unit_input_mapping,
    "unit_fixture_schema": unit_fixture_schema, "unit_build_document_assembly": unit_build_document_assembly,
    "unit_fixture_files": unit_fixture_files,
    "unit_training_isolation": unit_training_isolation, "unit_historical_evidence": unit_historical_evidence,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "game_capture_scripted": game_capture_scripted, "game_capture_visible": game_capture_visible,
    "game_capture_resume": game_capture_resume, "game_verify_matrix": game_verify_matrix,
    "game_build_refuses": game_build_refuses, "game_capture_error": game_capture_error,
    "game_detector_control": game_detector_control,
    "game_m7a_seven_target": game_m7a_seven_target, "game_historical_six": game_historical_six,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*", help="case names, 'unit' or 'game' (default: all)")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    names: List[str] = []
    for c in args.cases or list(ALL_CASES):
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        ap.error(f"unknown cases {unknown}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / "m7g" / f"_tests_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(n in GAME_CASES for n in names):
        import os

        from m7_runtime import install_kill_on_close_job

        leaked = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
        if leaked:
            raise SystemExit(f"SSB64_* variables in the environment would leak into every child: {leaked}")
        install_kill_on_close_job()
    suite = Suite(root)
    results: Dict[str, Any] = {}
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            results[name] = {"status": "PASS", "seconds": round(time.perf_counter() - t0, 1), "details": details}
        except Exception as exc:
            results[name] = {"status": "FAIL", "seconds": round(time.perf_counter() - t0, 1),
                             "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-2000:]}
        print(f"{results[name]['status']}  {name}  ({results[name]['seconds']} s)"
              + (f"  {results[name].get('error')}" if results[name]["status"] != "PASS" else ""), flush=True)
    ok = all(r["status"] == "PASS" for r in results.values())
    (root / "m7g_tests_results.json").write_text(json.dumps({"schema": "battleship_m7g_tests_v1", "utc": stamp,
                                                             "results": results, "ok": ok}, indent=1) + "\n",
                                                 encoding="utf-8", newline="\n")
    print(f"m7g_tests: {sum(r['status'] == 'PASS' for r in results.values())}/{len(results)} PASS -> {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
