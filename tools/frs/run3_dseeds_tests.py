#!/usr/bin/env python3
"""Tests of the D -> frontier hand-off and the ported readiness override (owner 2026-11-14; docs/frs_option_d_design_2026-11-11.md section 6.7).
Zero native ticks: the unit tests run in process on synthetic D folders; the e2e tests run D and run 3 on the fake game (rl/m8_rd_fakegame.py)
in guarded children, on the synthetic runs 1 + 2 of tools/frs/crossing_search_run3_tests.py; the real tests read the lab's folders only.

    python -B tools/frs/run3_dseeds_tests.py            every test
    python -B tools/frs/run3_dseeds_tests.py unit       in-process tests only
    python -B tools/frs/run3_dseeds_tests.py e2e        D and run 3 on the fake game
    python -B tools/frs/run3_dseeds_tests.py real       the lab's D folders and run 3 chain (zero ticks; skipped when the lab is absent)

The owner's test list (2026-11-14):
    H1  each refusal reason of a D folder (contract, status, every integrity field, M1), --accept-run, a D folder given twice, a D folder as
        --inherit                                                                              (unit_h1_admission, unit_h1_twice_and_inherit)
    H2  a niche that does not re-derive from D's own lineage is refused                       (unit_h2_niche)
    H3  seed selection by level and bound, a stable seed-set digest                           (unit_h3_selection)
    H4  key collisions: new key, faster than the frontier's cell, slower or equal, two D folders (unit_h4_keep_rule)
    H5  a seed's fused first dispatch: equal -> its end record stored; altered -> mismatch, quarantined (e2e_h5_h6_seeded_night, e2e_h5_mismatch)
    H6  seed rows at the open; a later plan inheriting the seeded night re-derives the niches  (e2e_h5_h6_seeded_night)
    H7  `run` refuses --seeds-from folders and an override that differ from the saved plan    (unit_h7_run_flags)
    H8  --best-from a D folder: a faster verified clear becomes the best (source order:<name>, bound recomputed, an equal text replay
        required); a D folder without one changes nothing                                     (unit_h8_best_source, e2e_h8_best_from_d)
    H9  the digests: run 3's manifest holds run3_dseeds.py; T-M1 (tools/frs/order_search_tests.py) the new pair   (unit_h9_manifest)
    old older run 3 folders (another recorded code digest) still load                          (e2e_old_folder_loads, real_chain_plan)
    override  the ported rule, and the open: admitted with the free-commit problem alone, refused otherwise   (unit_override_rule, e2e_h5_h6_seeded_night)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RL = REPO / "rl"
for _p in (RL, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import crossing_search as cs  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import run3_dseeds as ds  # noqa: E402
import run3_load as rl3  # noqa: E402
import run3_select as rs  # noqa: E402
from infra_testlib import check, cleanup, run_suite, tmpdir  # noqa: E402

LAB = Path(os.environ.get("RUN3_TEST_LAB", "C:/BattleShip_lab"))


def _raises(fn, *a, **k) -> Optional[str]:
    try:
        fn(*a, **k)
    except (cs.SearchError, rl3.LoadError) as exc:
        return str(exc)
    return None


# -- synthetic D folders ------------------------------------------------------------------------------------------------------------------------


def _hex(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _words(tag: str, n: int) -> bytes:
    return bytes(int(_hex(f"{tag}{i}")[:2], 16) % 10 for i in range(n))


def _mask(broken: Sequence[int]) -> int:
    return ds.ROOT_MASK & ~sum(1 << t for t in broken)


def d_rows() -> Dict[str, Any]:
    """A small D lineage from the tick-0 root: level 1 at 10 (target 4), level 3 at 30 (3 then 0), level 6 at 60 (9, 7, 5: set 326), a second
    level-6 key at 90 by another order (5, 7, 9), a level-5 cell at 50. Every row as D writes it; dispatch rows with their breaks."""
    rows: List[Dict[str, Any]] = []
    disp: List[Dict[str, Any]] = []

    def add(cid: int, parent: Optional[int], n: Optional[int], tick: int, broken: Sequence[int], x: int, breaks: Sequence[Sequence[int]], niche: Optional[str]) -> None:
        pw = bytes.fromhex(rows[parent]["words_hex"]) if parent is not None else b""
        words = pw + _words(f"c{cid}", tick - len(pw))
        m = _mask(broken)
        r = {"ev": "new", "cid": cid, "key": [x, 1, "A0" if cid else "G", m, -1 if cid else 4], "level": 10 - bin(m).count("1"), "tick": tick, "lead": 0,
             "digest": mcell.words_digest(words), "end_digest": _hex(f"e{cid}"), "chain": _hex(f"h{cid}"), "words_hex": words.hex(), "n": n or 0}
        r["origin"] = {"kind": "root"} if parent is None else {"kind": "burst", "parent": parent, "k": 0, "offset": 0, "n": n, "parent_digest": rows[parent]["digest"]}
        if niche is not None:
            r["niche"] = niche
        rows.append(r)
        if n is not None:
            disp.append({"kind": "burst", "n": n, "cid": parent, "breaks_after_start": [list(b) for b in breaks]})

    add(0, None, None, 0, [], 0, [], None)
    add(1, 0, 1, 10, [4], 1, [[5, 4]], "1023:4")
    add(2, 1, 2, 30, [4, 3, 0], 2, [[25, 3], [28, 0]], "1023:4-3-0")
    add(3, 2, 3, 60, [4, 3, 0, 9, 7, 5], 3, [[40, 9], [50, 7], [55, 5]], "1023:4-3-0-9-7-5")
    add(4, 2, 4, 90, [4, 3, 0, 5, 7, 9], 4, [[70, 5], [75, 7], [80, 9]], "1023:4-3-0-5-7-9")
    add(5, 2, 5, 50, [4, 3, 0, 9, 5], 5, [[40, 9], [45, 5]], "1023:4-3-0-9-5")
    return {"rows": rows, "dispatches": disp}


CLEAN_INTEGRITY = {"guard_violations_main": [], "lab_code_changed_during_run": [], "battleship_left": [], "tick0_unequal_jobs": 0, "prefix_mismatches": 0,
                   "order_code_digest": "d" * 64, "order_code_digest_end": "d" * 64, "order_code_changed_during_run": [], "root_equal": True,
                   "milestones_not_verified": []}


def write_d_folder(root: Path, name: str, *, status: str = "WALL_CAP", integrity: Optional[Mapping[str, Any]] = None, m1: bool = True,
                   contract: str = ds.ORDER_CONTRACT, data: Optional[Mapping[str, Any]] = None, verifications: Sequence[Mapping[str, Any]] = (),
                   text: Sequence[Mapping[str, Any]] = (), archive_id: str = "frs_order_v1|seed99") -> Path:
    d = Path(root) / name
    (d / "run").mkdir(parents=True, exist_ok=True)
    data = data or d_rows()
    rec = {"contract": contract, "mode": "lab"}
    (d / "plan.json").write_text(json.dumps(dict(rec, archive_id=archive_id)), encoding="utf-8")
    (d / "run" / "config.json").write_text(json.dumps(rec), encoding="utf-8")
    (d / "run" / "summary.json").write_text(json.dumps(dict(rec, status=status, utc_start="2026-11-14T00:00:00Z", utc_end="2026-11-14T08:00:00Z",
                                                             integrity=dict(CLEAN_INTEGRITY, **(integrity or {})),
                                                             order={"gate_m1": {"met": m1, "verified": m1, "tick": 60 if m1 else None}})), encoding="utf-8")
    (d / "run" / "cells.jsonl").write_text("".join(json.dumps(r) + "\n" for r in data["rows"]), encoding="utf-8")
    (d / "run" / "dispatches.jsonl").write_text("".join(json.dumps(r) + "\n" for r in data["dispatches"]), encoding="utf-8")
    if verifications:
        (d / "run" / "verifications.jsonl").write_text("".join(json.dumps(r) + "\n" for r in verifications), encoding="utf-8")
    if text:
        (d / "run" / "text_replays.jsonl").write_text("".join(json.dumps(r) + "\n" for r in text), encoding="utf-8")
    return d


# -- unit -------------------------------------------------------------------------------------------------------------------------------------


def unit_h1_admission() -> Dict[str, Any]:
    """H1: a D folder is admitted only with D's contract, a clean status, a clean integrity record and a verified M1; --accept-run admits the
    rest, with the reasons recorded."""
    t = tmpdir("dseeds_h1_")
    try:
        ok = ds.read_d_folder(write_d_folder(t, "order_ok"))
        check(not ok["accepted_non_clean"] and ok["m1"]["verified"] is True and ok["status"] == "WALL_CAP", f"a clean D folder is admitted: {ok['admission_problems']}")
        bad = {"status": dict(status="SEARCH_INCOMPLETE"), "m1": dict(m1=False)}
        for k, v in (("guard_violations_main", ["x"]), ("prefix_mismatches", 1), ("tick0_unequal_jobs", 2), ("battleship_left", [1]),
                     ("order_code_changed_during_run", ["f"]), ("lab_code_changed_during_run", ["f"]), ("milestones_not_verified", ["M1"]),
                     ("root_equal", False), ("order_code_digest_end", "e" * 64)):
            bad[f"integrity_{k}"] = dict(integrity={k: v})
        refused, accepted = {}, {}
        for name, kw in bad.items():
            d = write_d_folder(t, f"order_{name}", **kw)
            refused[name] = _raises(ds.read_d_folder, d)
            a = ds.read_d_folder(d, accepted=[d])
            accepted[name] = a["accepted_non_clean"] and bool(a["admission_problems"])
        check(all(refused.values()) and all("--accept-run" in v for v in refused.values()), f"every reason refused: {[k for k, v in refused.items() if not v]}")
        check(all(accepted.values()), f"--accept-run admits each, recorded: {accepted}")
        wrong = write_d_folder(t, "order_wrong_contract", contract="frs_crossing_search_run3_v1")
        r = _raises(ds.read_d_folder, wrong, accepted=[wrong])
        check(r and "is not a frs_order_search_v1" in r, f"another contract is refused even with --accept-run: {r}")
        empty = t / "order_empty"
        empty.mkdir()
        check("missing" in (_raises(ds.read_d_folder, empty) or ""), "a folder without D's files")
        return {"refused": sorted(refused), "accepted_with_reasons": sum(accepted.values())}
    finally:
        cleanup(t)


def unit_h1_twice_and_inherit() -> Dict[str, Any]:
    """H1: a D folder given twice within --seeds-from or --best-from is refused; a D folder given as --inherit is refused by its contract
    (run 3's reader), as before; the contract constant equals D's."""
    import crossing_search_run3 as C
    import order_search as O

    check(ds.ORDER_CONTRACT == O.ORDER_CONTRACT, "run3_dseeds.ORDER_CONTRACT is D's")
    t = tmpdir("dseeds_h1b_")
    try:
        d = write_d_folder(t, "order_a")
        e = write_d_folder(t, "order_b")
        check(C.d_folders_twice([d, e], [d]) == [] and C.d_folders_twice([d, e, d]) == [str(d)] and C.d_folders_twice([], [e, Path(str(e).upper())]),
              "twice within one flag is found; once in each flag is not")
        r = _raises(C.read_best_source, d, 100, "A")
        check(r and "frs_crossing_search_run3_v1" in r, f"a D folder as --inherit (run 3's reader) is refused: {r}")
        return {"inherit_refusal": r[-80:]}
    finally:
        cleanup(t)


def unit_h2_niche() -> Dict[str, Any]:
    """H2: every seed's niche re-derives from D's own lineage (root 1023, the burst breaks in tick order); an altered niche is refused, and so are
    altered words."""
    t = tmpdir("dseeds_h2_")
    try:
        D = ds.read_d_folder(write_d_folder(t, "order_ok"))
        seeds, rep = ds.d_seeds(D, 1000)
        check([s["niche"] for s in seeds] == ["1023:4-3-0-9-7-5", "1023:4-3-0-5-7-9"], f"the niches: {[s['niche'] for s in seeds]}")
        data = d_rows()
        data["rows"][3]["niche"] = "1023:4-3-0-9-5-7"
        D2 = ds.read_d_folder(write_d_folder(t, "order_alt", data=data))
        r = _raises(ds.d_seeds, D2, 1000)
        check(r and "niche" in r and "not the recorded" in r, f"an altered niche is refused: {r}")
        data = d_rows()
        data["rows"][4]["words_hex"] = data["rows"][4]["words_hex"][:-2] + "01"
        r2 = _raises(ds.d_seeds, ds.read_d_folder(write_d_folder(t, "order_words", data=data)), 1000)
        check(r2 and "words" in r2, f"altered words are refused: {r2}")
        check(rl3.niche_of_label("1023:4-3-0") == (1023, (4, 3, 0)) and rl3.niche_of_label("1023:") == (1023, ()), "niche labels parse")
        check(all(_raises(rl3.niche_of_label, x) for x in ("1023", "x:1", "1023:1--2", "1023:01")), "non-canonical labels are refused")
        return {"niches": [s["niche"] for s in seeds], "stats": rep["niche_stats"]}
    finally:
        cleanup(t)


def unit_h3_selection() -> Dict[str, Any]:
    """H3: final representatives at level >= 6 inside the bound only (the level-5 cell never, the tick-90 cell only when the bound admits it);
    a replaced row counts once with its last representative; the seed-set digest is stable."""
    t = tmpdir("dseeds_h3_")
    try:
        data = d_rows()
        r3 = dict(data["rows"][3])
        r3.update({"ev": "replaced"})
        data["rows"].append(r3)                                  # the same representative written again: still one seed
        D = ds.read_d_folder(write_d_folder(t, "order_ok", data=data))
        s80, rep80 = ds.d_seeds(D, 80)
        s100, rep100 = ds.d_seeds(D, 100)
        check([s["d_cid"] for s in s80] == [3] and rep80["beyond_bound"] == 1 and rep80["per_level"] == {"6": 1}, f"bound 80: {rep80}")
        check([s["d_cid"] for s in s100] == [3, 4] and rep100["beyond_bound"] == 0 and rep100["finals"] == 6, f"bound 100: {rep100}")
        check(all(s["level"] >= ds.SEED_MIN_LEVEL for s in s100), "no seed below level 6")
        recs = [dict(verdict="new", cid=i, folder=s["folder"], d_cid=s["d_cid"], digest=s["digest"], tick=s["tick"]) for i, s in enumerate(s100)]
        check(ds.seed_set_digest(recs) == ds.seed_set_digest([dict(r) for r in recs]) and ds.seed_set_digest(recs) != ds.seed_set_digest(recs[::-1]),
              "the seed-set digest is a function of the records, in order")
        check(rep100["fsid"] < 0 and rep100["fsid"] == ds.seed_fsid(D), "a negative, stable lineage root id")
        return {"bound_80": len(s80), "bound_100": len(s100), "fsid": rep100["fsid"]}
    finally:
        cleanup(t)


def unit_h4_keep_rule() -> Dict[str, Any]:
    """H4: the archive's keep rule on the plan's rows: a new key gets the next cell id; a strictly earlier tick replaces the frontier's
    representative (cell id kept, replaced + 1, claimed clears dropped, niche moved to D's, the previous representative recorded); an equal
    or later tick is dropped (LATER); between two D folders the faster wins, a tie goes to the folder given first."""
    K1 = [3, 1, "A0", 326, -1]
    final = {0: {"cid": 0, "key": [0, 0, "G", 1023, 4], "level": 0, "tick": 0, "digest": "r0", "origin": {"kind": "seed", "fsid": 7}, "seen": 0, "replaced": 0},
             1: {"cid": 1, "key": K1, "level": 6, "tick": 70, "digest": "f1", "origin": {"kind": "burst"}, "seen": 4, "replaced": 2},
             2: {"cid": 2, "key": [9, 9, "A0", 326, -1], "level": 6, "tick": 40, "digest": "f2", "origin": {"kind": "burst"}, "seen": 0, "replaced": 0}}
    niches: Dict[int, Any] = {0: (1023, ()), 1: (1023, (5, 9, 7, 4, 3, 0)), 2: (1023, (5, 9, 7, 4, 3, 0))}
    cleared = {1: 3}
    origins: Dict[Any, Any] = {}

    def seed(folder: str, d_cid: int, key: Sequence[Any], tick: int, niche: str) -> Dict[str, Any]:
        return {"folder": folder, "d_archive_id": folder, "d_cid": d_cid, "digest": f"{folder}{d_cid}", "key": list(key), "level": 6, "tick": tick,
                "words_hex": "00" * tick, "end_digest": "e" * 64, "chain": "c" * 64, "niche": niche}

    A = ({"fsid": -11}, [seed("A", 1, K1, 60, "1023:4-3-0-9-7-5"), seed("A", 2, [5, 1, "A0", 326, -1], 65, "1023:4-3-0-5-7-9"),
                         seed("A", 3, [9, 9, "A0", 326, -1], 40, "1023:4-3-0-9-5-7")])
    B = ({"fsid": -12}, [seed("B", 1, K1, 61, "1023:9-0-4-3-5-7"), seed("B", 2, [5, 1, "A0", 326, -1], 65, "1023:9-0-4-3-5-7"),
                         seed("B", 3, [6, 1, "A0", 326, -1], 50, "1023:9-0-4-3-5-7")])
    recs, counts = ds.insert_seeds(final, origins, cleared, niches, [A, B], lambda lv, t: 1000 - t)
    by = {(r["folder"], r["d_cid"]): r for r in recs}
    check(by[("A", 1)]["verdict"] == "replaced" and by[("A", 1)]["cid"] == 1 and final[1]["digest"] == "A1" and final[1]["replaced"] == 3
          and final[1]["seen"] == 4 and 1 not in cleared and niches[1] == (1023, (4, 3, 0, 9, 7, 5)) and by[("A", 1)]["previous"]["tick"] == 70
          and by[("A", 1)]["previous"]["niche"] == "1023:5-9-7-4-3-0", f"faster than the frontier's: replaced, moved, clears dropped: {by[('A', 1)]}")
    check(by[("B", 1)]["verdict"] == "later" and by[("B", 1)]["existing_tick"] == 60, "a slower seed of another folder on the same key: LATER")
    check(by[("A", 3)]["verdict"] == "later" and final[2]["digest"] == "f2", "an equal tick: LATER, the frontier's cell unchanged")
    check(by[("B", 3)]["verdict"] == "new" and by[("B", 3)]["cid"] == 3 and by[("A", 2)]["verdict"] == "new" and by[("A", 2)]["cid"] == 4
          and by[("B", 2)]["verdict"] == "later", "new keys get the next ids in tick order; a tie goes to the folder given first")
    check(final[3]["origin"] == {"kind": "seed", "fsid": -12, "source": "order", "folder": "B", "d_archive_id": "B", "d_cid": 3, "d_digest": "B3",
                                 "niche": "1023:9-0-4-3-5-7"} and final[3]["lead"] == 950 and rl3.is_d_seed(final[3]["origin"]), f"the seed origin: {final[3]}")
    check(origins[(1, "A1")]["fsid"] == -11 and (3, "B3") in origins and counts == {"new": 2, "replaced": 1, "later": 3}, f"counts {counts}")
    return {"counts": counts}


def unit_h7_run_flags() -> Dict[str, Any]:
    """H7: `run` refuses --seeds-from folders and a readiness override that differ from the saved plan's; the same flags pass."""
    import crossing_search_run3 as C
    import run3_search as r3

    a, b = Path("C:/lab/order_a"), Path("C:/lab/order_b")
    ov = r3.readiness_override_record(7000, "owner declined PC restart; 16 GB machine")
    saved = {"run3": {"best_from": [], "seeds_from": [{"dir": str(a)}, {"dir": str(b)}]}, "readiness_override": ov}
    check(C.plan_flag_problems(saved, [], [], [], seeds_from=[a, b], readiness_override=ov) is None, "the same flags pass")
    cases = {"seeds_dropped": C.plan_flag_problems(saved, [], [], [], seeds_from=[a], readiness_override=ov),
             "seeds_order": C.plan_flag_problems(saved, [], [], [], seeds_from=[b, a], readiness_override=ov),
             "override_dropped": C.plan_flag_problems(saved, [], [], [], seeds_from=[a, b]),
             "override_other": C.plan_flag_problems(saved, [], [], [], seeds_from=[a, b], readiness_override=r3.readiness_override_record(7500, "x")),
             "override_added": C.plan_flag_problems({"run3": {}}, [], [], [], readiness_override=ov)}
    check(all(cases.values()) and "--seeds-from" in cases["seeds_dropped"] and "override" in cases["override_dropped"], f"refusals: {cases}")
    check(C.plan_flag_problems({"run3": {"best_from": []}}, [], []) is None, "an old plan without seeds or override passes with no flags")
    return {"refused": sorted(cases)}


def unit_override_rule() -> Dict[str, Any]:
    """The ported override: the record (both flags, between 1 and the registered minimum) and the verdict (only free commit, at least N)."""
    import order_search as O
    import run3_search as r3

    ov = r3.readiness_override_record(7000, " owner reason ")
    check(ov == O.readiness_override_record(7000, " owner reason "), "the same record as D's")
    check(r3.readiness_override_record(None, "") is None and all(_raises(r3.readiness_override_record, *x) for x in ((7000, ""), (None, "r"), (0, "r"), (10240, "r"))),
          "both flags together, 1 .. registered - 1")
    mem = lambda free: {"commit_free_mb": free, "available_mb": 8000.0}  # noqa: E731
    fc = "free commit 7600 MB < 10240 MB"
    cases = {"ok_registered": ({"ok": True, "problems": []}, None), "ok_with_override": ({"ok": True, "problems": []}, ov),
             "free_commit_only": ({"ok": False, "problems": [fc], "memory": mem(7600.0)}, ov),
             "free_commit_below": ({"ok": False, "problems": ["free commit 6900 MB < 10240 MB"], "memory": mem(6900.0)}, ov),
             "other_problem": ({"ok": False, "problems": [fc, "free disk on C: 3 GiB < 5 GiB"], "memory": mem(7600.0)}, ov),
             "no_override": ({"ok": False, "problems": [fc], "memory": mem(7600.0)}, None)}
    got = {k: r3.readiness_verdict(*v) for k, v in cases.items()}
    want = {k: O.readiness_verdict(*v) for k, v in cases.items()}
    check(got == want, "the same verdicts as D's")
    check([k for k, (adm, _u) in got.items() if adm] == ["ok_registered", "ok_with_override", "free_commit_only"]
          and got["free_commit_only"][1]["applied"] is True and got["ok_with_override"][1]["applied"] is False, f"verdicts: {got}")
    return {"admitted": [k for k, (adm, _u) in got.items() if adm]}


def unit_h8_best_source() -> Dict[str, Any]:
    """H8 (shape): an admitted D folder as a --best-from source: its verified clears, its text replays by dispatch, its best; nothing when it has
    none. read_best_source_any picks the reader by the folder's plan."""
    import crossing_search_run3 as C

    t = tmpdir("dseeds_h8_")
    try:
        v = {"kind": "clear", "verdict": "VERIFIED", "n": 7, "completion_input_tick": 500, "words_digest": "w"}
        d = write_d_folder(t, "order_clear", verifications=[v, dict(v, n=9, verdict="NOT_VERIFIED", completion_input_tick=400)], text=[{"n": 7, "equal": True}])
        X = C.read_best_source_any(d, 1000, "A")
        check(X["kind"] == "order" and X["verified"] == 1 and X["best_in_folder"] == 500 and X["text"][7]["equal"] is True, f"the D source: {X}")
        Y = C.read_best_source_any(write_d_folder(t, "order_none"), 1000, "A")
        check(Y["verified"] == 0 and Y["best_in_folder"] is None and Y["verifications"] == [], "a D folder without clears")
        r = _raises(C.read_best_source_any, write_d_folder(t, "order_bad", m1=False), 1000, "A")
        check(r and "M1 not verified" in r, f"--best-from applies the admission rule: {r}")
        return {"best_in_folder": X["best_in_folder"]}
    finally:
        cleanup(t)


def unit_h9_manifest() -> Dict[str, Any]:
    """H9: run 3's manifest holds run3_dseeds.py (an entry module imports it) and D's holds it too; D's T-M1 pair is the frontier code's."""
    import order_search as O
    import order_search_tests as OT
    import run3_manifest as rm

    m = rm.run3_code_manifest()
    om = O.order_code_manifest()
    check("tools/frs/run3_dseeds.py" in m and "tools/frs/run3_dseeds.py" in om and "rl/frs_machine.py" in m, "the new module is in both manifests")
    # D = run 3's 55 + D's three modules (order_search, order_select and, since the hitter record of 2026-11-19, order_worker)
    check(len(m) == 55 and len(om) == 58, f"files: run 3 {len(m)}, D {len(om)}")
    check(rm.code_digest(m) in OT.RUN3_DIGESTS, f"T-M1: run 3 {rm.code_digest(m)[:8]} is one of {[k[:8] for k in OT.RUN3_DIGESTS]}")
    return {"run3": rm.code_digest(m)[:8], "run3_files": len(m), "d": O.code_digest(om)[:8], "d_files": len(om)}


# -- e2e: D and run 3 on the fake game -------------------------------------------------------------------------------------------------------


CHILD = ("import json, sys\nfrom pathlib import Path\nsys.path.insert(0, %r); sys.path.insert(0, %r)\nimport frs_guard as g\n"
         "g.LabGuard.install(Path(%r))\nimport run3_dseeds_tests as T\nprint(json.dumps(T.%s(json.loads(%r)), default=str))\n")
FREE_COMMIT_ONLY = {"ok": False, "problems": ["free commit 7600 MB < 10240 MB"], "memory": {"commit_free_mb": 7600.0, "available_mb": 8000.0}}


def run_child(fn: str, lab: Path, args: Mapping[str, Any], timeout: float = 1800.0) -> Dict[str, Any]:
    code = CHILD % (str(RL), str(HERE), str(lab), fn, json.dumps(args))
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(lab))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(f"{fn}: child failed: {(r.stderr or r.stdout)[-3000:]}")


def seeded_child(a: Mapping[str, Any]) -> Dict[str, Any]:
    """crossing_search_run3_tests.engine3_child with the hand-off flags: `plan` in process, then what `run` does (the plan child), then a run 3
    night on the fake game. `readiness`: "ok" or "free_commit_only" (the open's readiness, injected)."""
    import crossing_search_run3 as C
    import crossing_search_run3_tests as CT
    import frs_guard as g
    import frs_machine as fm
    import frs_run as fr
    import frs_verify as fv
    import m8_rd_stub as stub
    import run3_export as rx
    import run3_manifest as rm
    import run3_search as r3
    import run3_search_tests as r3t

    lab, out, run1, run2, exe = Path(a["lab"]), Path(a["out"]), Path(a["run1"]), Path(a["run2"]), Path(a["exe"])
    run_dir = out / "run"
    params = C.Params3(**dict(a["params"], level_weights=tuple(a["params"].get("level_weights") or ())))
    code = rm.code_digest(rm.run3_code_manifest())
    paths ={k: [Path(x) for x in a.get(k) or []] for k in ("inherit", "accept_runs", "seeds_from", "best_from")}
    ov = r3.readiness_override_record(a.get("min_commit_free_mb"), a.get("override_reason") or "")
    C.plan_and_write(lab, run1, run2, out, params, stub.analyse, code_digest=code, readiness_override=ov, **paths)
    P = C.plan_via_child(lab, run1, run2, out, params, code_digest=code, analyse="stub", readiness_override=ov, **paths)
    frozen = {"frozen_sha256": a["frozen"], "exe_copy_sha256": a["exe_copy"]}
    fk = {"exe": a["exe"], "frozen": a["frozen"]}

    def spec(rank: int) -> Dict[str, Any]:
        return dict(r3t.worker_spec(lab, fk, rank, int(a["port_base"]), run_dir / "failures", dict(CT.FLAGS)), guard=g.LabGuard.spec(), run3_selfcheck=True)

    ready = dict(FREE_COMMIT_ONLY) if a.get("readiness") == "free_commit_only" else {"ok": True, "problems": []}
    env = fr.LabEnv(worker_spec=spec, replay=fv.make_real_replay(exe, lab / f"replays_{out.name}", CT.FLAGS, frozen), analyse=stub.analyse,
                    readiness=lambda: dict(ready), battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                    wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="real", sample_s=0.25, row_every_s=0.5,
                    caps=dict(fm.CAPS_MB, main_private=1e9))
    cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=run1, n_workers=3, max_ticks=10 ** 9, max_wall_s=1200.0, expect_code=None,
                          stop_grace_s=60.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0, seed_parallel=3)
    text = rx.make_text_replay(exe, run_dir / "text_replays")
    rc = C.Run3Night(cfg, env, P, params, text_replay=text, anomaly_build={"exe": "fake", "platform": sys.platform}).run()
    x = P["plan"]["run3"]
    return {"code": rc, "violations": g.LabGuard.violations[:3], "bound": P["bound"], "best": {k: v for k, v in P["best"].items() if k != "words"},
            "e7": P["plan"]["e7"], "inherited": P["plan"]["archive"]["inherited"], "readiness_override": P["plan"].get("readiness_override"),
            "seeds_from": x.get("seeds_from"), "d_seeds": x.get("d_seeds"), "d_seed_counts": x.get("d_seed_counts"), "d_seed_set_digest": x.get("d_seed_set_digest"),
            "start_groups": [r["group"] for r in x["start"]], "niche_stats": x.get("niche_stats"), "inherit": x.get("inherit")}


class HBench:
    """Run 3's fake-game bench (synthetic runs 1 + 2, crossing_search_run3_tests.bench), one D night on the same fake world (D's own e2e
    child, tools/frs/order_search_tests.order_child, fake frontier best 3,000), then seeded run 3 nights by name."""

    def __init__(self) -> None:
        import crossing_search_run3_tests as CT
        import order_search_tests as OT

        self.CT, self.OT = CT, OT
        self.b = CT.bench()
        self.lab = self.b.lab
        self.d_out = self.lab / "order_h_d"
        if not (self.d_out / "run" / "summary.json").is_file():
            frontier = OT.write_fake_frontier(self.lab, 3000)
            self.b.port += 1000
            self.d_res = OT.run_child("order_child", self.lab, {"lab": str(self.lab), "out": str(self.d_out), "frontier": str(frontier), "exe": self.b.fk["exe"],
                                                                "frozen": self.b.fk["frozen"], "exe_copy": self.b.fk["exe_copy"], "port_base": self.b.port,
                                                                "engine": dict(OT.E_ENGINE)})
        else:
            self.d_res = {"code": 0, "reused": True}
        self.d_summary = json.loads((self.d_out / "run" / "summary.json").read_text(encoding="utf-8"))
        self.runs: Dict[str, Dict[str, Any]] = {}

    def run(self, name: str, prm: Optional[Mapping[str, Any]] = None, **extra: Any) -> Dict[str, Any]:
        if name in self.runs:
            return self.runs[name]
        b = self.b
        out = self.lab / f"run3_h_{name}"
        b.port += 1000
        args = dict({"lab": str(self.lab), "out": str(out), "run1": str(b.run1), "run2": str(b.run2), "exe": b.fk["exe"], "frozen": b.fk["frozen"],
                     "exe_copy": b.fk["exe_copy"], "params": dict(prm or SEEDED_PARAMS), "port_base": b.port}, **extra)
        res = run_child("seeded_child", self.lab, args)
        d = out / "run"
        res["dir"] = d
        rd = self.CT.read_jsonl
        if (d / "summary.json").is_file():
            res.update({"summary": json.loads((d / "summary.json").read_text(encoding="utf-8")), "config": json.loads((d / "config.json").read_text(encoding="utf-8")),
                        "cells": rd(d / "cells.jsonl"), "dispatches": rd(d / "dispatches.jsonl"), "run_log": rd(d / "run_log.jsonl")})
        self.runs[name] = res
        return res


SEEDED_PARAMS = {"max_segments": 3, "max_dispatches": 200, "rng_seed": 11, "check_slots": 1, "summary_every_s": 0.0, "summary_every_dispatches": 50,
                 "level_weights": [0.05, 0.05, 0.05, 0.85]}
_HB: Optional[HBench] = None


def hbench() -> HBench:
    global _HB
    if _HB is None:
        _HB = HBench()
    return _HB


def e2e_h5_h6_seeded_night() -> Dict[str, Any]:
    """H5, H6 and the override at the open, on the fake game. D's night reaches level 6 in the fake world and is admitted; a run 3 night seeded
    from it (and taking it as --best-from) opens under the owner override with free commit the only readiness problem; its cells.jsonl starts
    with one row per kept seed (origin source order, niche, group); dispatched seeds are fused and their end records stored (no mismatch);
    the same readiness without the override is refused at the open; a later plan inheriting the seeded night re-derives every niche."""
    import crossing_search_run3 as C
    import m8_rd_stub as stub
    import run3_manifest as rm

    h = hbench()
    ds_sum = h.d_summary
    check(h.d_res.get("code") == 0 and ds_sum["order"]["gate_m1"]["verified"] is True, f"the D night: {h.d_res} M1 {ds_sum['order']['gate_m1']}")
    S = h.run("seeded", seeds_from=[str(h.d_out)], best_from=[str(h.d_out)], readiness="free_commit_only", min_commit_free_mb=7000,
              override_reason="test: free commit only")
    s = S["summary"]
    counts = S["d_seed_counts"]
    kept = [r for r in S["d_seeds"] if r["verdict"] in ("new", "replaced")]
    check(S["code"] == 0 and not S["violations"] and s["status"] in ("DISPATCH_CAP", "WALL_CAP"), f"the seeded night: {S['code']} {s['status']}")
    check(kept and counts["new"] + counts["replaced"] == len(kept), f"seeds kept at the plan: {counts}")
    ov = s["run3"]["readiness_override"]
    check(ov and ov["applied"] is True and ov["commit_free_mb"] == 7600.0 and S["config"]["readiness_override"]["applied"] is True
          and any("READINESS OVERRIDE (owner)" in str(r.get("msg") or r.get("event") or r) for r in S["run_log"]), f"the override at the open: {ov}")
    head = S["cells"][:len(kept)]
    check([r["cid"] for r in head] == [r["cid"] for r in kept] and all(rl3.is_d_seed(r["origin"]) and r["n"] == 0 and r["niche"] and r["group"] for r in head),
          "the seed rows come first, one per kept seed, with origin, niche and group")
    check(all(r["niche"] == k["niche"] and r["group"].startswith(f"{r['level']}|{r['key'][3]}|") for r, k in zip(head, kept)), "each row's niche is D's")
    sd = s["run3"]["d_seeds"]
    e = s["run3"]["end_records"]
    check(sd["dispatched"] >= 1 and sd["end_record_stored"] >= 1 and sd["quarantined"] == 0 and e["fused_mismatch"] == 0, f"fused seeds: {sd} {e}")
    stored = [r for r in S["cells"] if r.get("ev") == "end_record" and r["cid"] in {k["cid"] for k in kept}]
    check(len(stored) == sd["end_record_stored"] or sd["replaced_since"], f"an end_record row per stored seed: {len(stored)} vs {sd}")
    refused = h.run("refused", seeds_from=[str(h.d_out)], readiness="free_commit_only")
    check(refused["code"] == cs.EXIT["REFUSED"] and not (refused["dir"]).exists(), f"without the override the same readiness is refused: {refused['code']}")
    params = C.Params3(**dict(SEEDED_PARAMS, level_weights=tuple(SEEDED_PARAMS["level_weights"])))
    P2 = C.build_plan(h.lab, h.b.run1, h.b.run2, params, stub.analyse, code_digest=rm.code_digest(rm.run3_code_manifest()), inherit=[S["dir"].parent])
    rep = P2["plan"]["run3"]["inherit"][0]
    seeded_rows = sum(1 for r in S["cells"] if r.get("ev") in ("new", "replaced"))
    check(rep["rows"] == rep["niche_equal"] == seeded_rows and P2["plan"]["run3"]["niche_stats"].get("d_seed_roots", 0) >= 1,
          f"a later plan inheriting the seeded night re-derives every niche: {rep} {P2['plan']['run3']['niche_stats']}")
    for k in kept:
        c = P2["archive"].cells[int(k["cid"])]
        check(c.digest == k["digest"] or c.tick < k["tick"], f"seed cell {k['cid']} carried into the later plan")
    return {"d_m1": ds_sum["order"]["gate_m1"], "seeds": counts, "seed_ticks": [k["tick"] for k in kept], "bound": S["bound"], "d_seeds_night": sd,
            "fused": {k: e[k] for k in ("fused", "fused_ok", "fused_mismatch")}, "override": {k: ov[k] for k in ("applied", "commit_free_mb")},
            "later_plan_inherited": P2["plan"]["archive"]["inherited"]}


def e2e_h5_mismatch() -> Dict[str, Any]:
    """H5: a D folder whose seeds' recorded end-record digests are altered (a copy; the plan does not read them): every dispatched seed's fused
    prefix check fails, the cell is quarantined, fused_mismatch counts it, and more than the limit is SEARCH_INVALID (run 2's rule)."""
    h = hbench()
    alt = h.lab / "order_h_d_altered"
    if not alt.exists():
        shutil.copytree(h.d_out, alt)
        rows = [json.loads(x) for x in (alt / "run" / "cells.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        for r in rows:
            if r.get("ev") in ("new", "replaced") and int(r.get("level", 0)) >= ds.SEED_MIN_LEVEL:
                r["end_digest"] = "0" * 64
        (alt / "run" / "cells.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    M = h.run("mismatch", seeds_from=[str(alt)])
    s = M["summary"]
    e = s["run3"]["end_records"]
    sd = s["run3"]["d_seeds"]
    check(e["fused_mismatch"] >= 1 and sd["quarantined"] >= 1 and sd["end_record_stored"] == 0, f"altered seeds: mismatch, quarantined: {e} {sd}")
    check(s["status"] in ("SEARCH_INVALID", "DISPATCH_CAP", "WALL_CAP") and (s["status"] != "SEARCH_INVALID" or "mismatch" in str(s.get("stop")) or "quarantine" in str(s.get("stop"))),
          f"the status follows run 2's mismatch limit: {s['status']} {s.get('stop')}")
    return {"status": s["status"], "fused_mismatch": e["fused_mismatch"], "quarantined": sd["quarantined"]}


def e2e_h8_best_from_d() -> Dict[str, Any]:
    """H8 on the plan: --best-from the D night of the bench. A D folder with a verified clear faster than the frontier's best becomes the best
    (source order:<name>, the bound recomputed) only with an equal text replay; a copy without its text replays is refused; a D folder whose
    clears are not faster leaves the best and the bound unchanged (recorded)."""
    import crossing_search_run2 as r2
    import crossing_search_run3 as C
    import m8_rd_stub as stub
    import run3_manifest as rm

    h = hbench()
    params = C.Params3(**dict(SEEDED_PARAMS, level_weights=tuple(SEEDED_PARAMS["level_weights"])))
    code = rm.code_digest(rm.run3_code_manifest())
    base = C.build_plan(h.lab, h.b.run1, h.b.run2, params, stub.analyse, code_digest=code)
    P = C.build_plan(h.lab, h.b.run1, h.b.run2, params, stub.analyse, code_digest=code, best_from=[h.d_out])
    X = P["plan"]["run3"]["best_from"][0]
    dbest = X["best_in_folder"]
    out: Dict[str, Any] = {"frontier_best": base["best"]["completion_input_tick"], "d_best": dbest, "d_verified": X["verified"]}
    if dbest is not None and dbest < base["best"]["completion_input_tick"]:
        check(P["best"]["source"] == f"order:{h.d_out.name}" and P["bound"] < base["bound"] and P["best"]["completion_input_tick"] == dbest,
              f"a faster D clear is the best: {P['best']['source']} {P['bound']} vs {base['bound']}")
        cut = h.lab / "order_h_d_no_text"
        if not cut.exists():
            shutil.copytree(h.d_out, cut)
            (cut / "run" / "text_replays.jsonl").unlink(missing_ok=True)
        r = _raises(C.build_plan, h.lab, h.b.run1, h.b.run2, params, stub.analyse, code_digest=code, best_from=[cut])
        check(r and "text replay" in r, f"without an equal text replay a D best is refused: {r}")
        out["case"] = "faster"
    else:
        check(P["best"]["source"] == base["best"]["source"] and P["bound"] == base["bound"], "a D folder without a faster clear changes nothing")
        out["case"] = "not faster"
    # the faster case on a synthetic copy when the bench's D night is not faster: the frontier's own best row (runs 1 + 2), written into a D
    # folder copy, is the best by its identity and needs that folder's equal text replay
    R1 = r2.read_run1(h.b.run1)
    v2 = list(rl3.read_jsonl(h.b.run2 / "run" / "verifications.jsonl")) if (h.b.run2 / "run" / "verifications.jsonl").is_file() else []
    v0 = next(v for v in list(R1["verifications"]) + v2 if v.get("kind") == "clear" and v.get("verdict") == "VERIFIED"
              and int(v["n"]) == base["best"]["n"] and v.get("words_digest") == base["best"]["words_digest"])
    syn = h.lab / "order_h_d_syn_best"
    if not syn.exists():
        shutil.copytree(h.d_out, syn)
    (syn / "run" / "verifications.jsonl").write_text(json.dumps(v0) + "\n", encoding="utf-8")
    (syn / "run" / "text_replays.jsonl").write_text(json.dumps({"n": v0["n"], "equal": True}) + "\n", encoding="utf-8")
    P3 = C.build_plan(h.lab, h.b.run1, h.b.run2, params, stub.analyse, code_digest=code, best_from=[syn])
    check(P3["best"]["source"] == f"order:{syn.name}" and P3["bound"] == base["bound"], f"the best row found in a D folder is labelled order:: {P3['best']['source']}")
    (syn / "run" / "text_replays.jsonl").write_text(json.dumps({"n": v0["n"], "equal": False}) + "\n", encoding="utf-8")
    r3_ = _raises(C.build_plan, h.lab, h.b.run1, h.b.run2, params, stub.analyse, code_digest=code, best_from=[syn])
    check(r3_ and "text replay" in r3_, f"a D best without an equal text replay is refused: {r3_}")
    out["synthetic"] = P3["best"]["source"]
    # a truly faster clear: a verified clear of the bench's run 3 night A (faster than the start's best by construction: claims are replayed
    # only when faster) with its equal text replay, written into a D folder copy -> the best and a lower bound
    A = h.b.run("a")
    fast = [v for v in A["verifications"] if v.get("verdict") == "VERIFIED" and int(v["completion_input_tick"]) < base["best"]["completion_input_tick"]]
    eq = {int(t["n"]): t for t in A["text"] if t.get("equal") is True}
    fast = [v for v in fast if int(v["n"]) in eq]
    if fast:
        vf = min(fast, key=lambda v: (int(v["completion_input_tick"]), int(v["completion_time_passed"]), int(v["n"])))
        fd = h.lab / "order_h_d_faster"
        if not fd.exists():
            shutil.copytree(h.d_out, fd)
        (fd / "run" / "verifications.jsonl").write_text(json.dumps(vf) + "\n", encoding="utf-8")
        (fd / "run" / "text_replays.jsonl").write_text(json.dumps(eq[int(vf["n"])]) + "\n", encoding="utf-8")
        P4 = C.build_plan(h.lab, h.b.run1, h.b.run2, params, stub.analyse, code_digest=code, best_from=[fd])
        check(P4["best"]["source"] == f"order:{fd.name}" and P4["best"]["completion_input_tick"] == int(vf["completion_input_tick"]) and P4["bound"] < base["bound"],
              f"a faster D clear is the best and lowers the bound: {P4['best']['source']} {P4['best']['completion_input_tick']} bound {P4['bound']} vs {base['bound']}")
        out["faster_synthetic"] = {"best": P4["best"]["completion_input_tick"], "bound": P4["bound"], "base_bound": base["bound"]}
    else:
        out["faster_synthetic"] = "no faster verified clear with an equal text replay in run A"
    return out


def e2e_old_folder_loads() -> Dict[str, Any]:
    """Older folders stay readable: a copy of a bench run 3 folder whose plan, config and summary record another run 3 code digest (as a folder
    planned before fix B and the hand-off) is inherited by a plan of today's code; the loaders compare each folder's own open and close."""
    import crossing_search_run3 as C
    import m8_rd_stub as stub
    import run3_manifest as rm

    h = hbench()
    A = h.b.run("a")
    adir = A["dir"].parent
    old = h.lab / "run3_h_old_digest"
    if not old.exists():
        shutil.copytree(adir, old)
        for rel, edit in (("plan.json", lambda p: p["run3"].update(code_digest="73cbde95" + "0" * 56)),
                          ("run/summary.json", lambda s: s["integrity"].update(run3_code_digest="73cbde95" + "0" * 56, run3_code_digest_end="73cbde95" + "0" * 56))):
            p = json.loads((old / rel).read_text(encoding="utf-8"))
            edit(p)
            (old / rel).write_text(json.dumps(p), encoding="utf-8")
    now = rm.code_digest(rm.run3_code_manifest())
    P = C.build_plan(h.lab, h.b.run1, h.b.run2, C.Params3(**dict(SEEDED_PARAMS, level_weights=tuple(SEEDED_PARAMS["level_weights"]))), stub.analyse, code_digest=now, inherit=[old])
    rep = P["plan"]["run3"]["inherit"][0]
    check(rep["rows"] == rep["niche_equal"] and P["plan"]["run3"]["code_digest"] == now, f"an older folder loads under today's code: {rep}")
    return {"rows": rep["rows"], "today": now[:8]}


UNIT = {f.__name__: f for f in (unit_h1_admission, unit_h1_twice_and_inherit, unit_h2_niche, unit_h3_selection, unit_h4_keep_rule, unit_h7_run_flags,
                                unit_override_rule, unit_h8_best_source, unit_h9_manifest)}
E2E = {f.__name__: f for f in (e2e_h5_h6_seeded_night, e2e_h5_mismatch, e2e_h8_best_from_d, e2e_old_folder_loads)}


# -- real: the lab's folders, zero ticks ------------------------------------------------------------------------------------------------------

D_REAL = ("order_2026-11-13_pilot2", "order_2026-11-14_night2")
CHAIN = ("crossing_2026-11-06_run3", "crossing_2026-11-10_run3b", "crossing_2026-11-11_run3c_smoke2", "crossing_2026-11-11_run3c")
CHAIN_PARAMS = {"max_segments": 6, "rng_seed": 1, "max_cells": 600000, "check_slots": 2, "summary_every_s": 600.0, "level_weights": (0.20, 0.35, 0.35, 0.10)}


def _lab_present() -> bool:
    return all((LAB / n / "run" / "summary.json").is_file() for n in D_REAL + CHAIN) and (LAB / "import" / "import_manifest.json").is_file()


def real_d_folders() -> Dict[str, Any]:
    """The lab's two D nights are admitted (WALL_CAP, M1 verified); their level-6 cells are the seeds (pilot 2: 23 at 353..408, night 2: 24 at
    351..405 inside bound 882), every niche re-derived from D's own lineage equal to the recorded one; the smoke and pilot 1 (no verified M1)
    are refused."""
    if not _lab_present():
        return {"skipped": f"no lab at {LAB}"}
    out = {}
    for n in D_REAL:
        D = ds.read_d_folder(LAB / n)
        seeds, rep = ds.d_seeds(D, 882)
        check(not D["accepted_non_clean"] and D["m1"]["verified"] and rep["beyond_bound"] == 0 and seeds and all(s["level"] == 6 for s in seeds),
              f"{n}: admitted, level-6 seeds: {rep}")
        out[n] = {"seeds": len(seeds), "ticks": [min(s["tick"] for s in seeds), max(s["tick"] for s in seeds)], "niches": sorted({s["niche"] for s in seeds}),
                  "m1": D["m1"]["tick"]}
    check(out["order_2026-11-13_pilot2"]["seeds"] == 23 and out["order_2026-11-14_night2"]["seeds"] == 24
          and out["order_2026-11-13_pilot2"]["niches"] == ["1023:9-0-4-3-5-7"] and out["order_2026-11-14_night2"]["niches"] == ["1023:0-3-9-4-5-7"], f"{out}")
    for n in ("order_2026-11-13_smoke", "order_2026-11-13_pilot"):
        if (LAB / n / "run" / "summary.json").is_file():
            r = _raises(ds.read_d_folder, LAB / n)
            check(r and "M1 not verified" in r, f"{n} refused: {r}")
    return out


def real_chain_plan() -> Dict[str, Any]:
    """The frontier smoke's plan, built in process (zero ticks, nothing written): runs 1 + 2, the run 3 chain (four folders planned under older
    run 3 digests: they load under today's code), both D nights as --seeds-from and --best-from, the owner override. Best 907 (night 3), bound
    882; every D seed kept or dropped by the keep rule; D's two groups in the start table; D's best sources recorded with no clear."""
    if not _lab_present():
        return {"skipped": f"no lab at {LAB}"}
    import crossing_search_run3 as C
    import run3_manifest as rm
    import run3_search as r3

    ov = r3.readiness_override_record(7000, "owner declined PC restart; 16 GB machine")
    P = C.build_plan(LAB, LAB / "crossing_2026-10-15", LAB / "crossing_2026-10-15_run2", C.Params3(**CHAIN_PARAMS), code_digest=rm.code_digest(rm.run3_code_manifest()),
                     inherit=[LAB / n for n in CHAIN], seeds_from=[LAB / n for n in D_REAL], best_from=[LAB / n for n in D_REAL], readiness_override=ov)
    p = P["plan"]
    x = p["run3"]
    counts = x["d_seed_counts"]
    groups = {r["group"]: r for r in x["start"]}
    dg = {g: {k: groups[g][k] for k in ("eligible", "anchors", "share", "rho")} for g in groups if g.endswith(("1023:9-0-4-3-5-7", "1023:0-3-9-4-5-7"))}
    check(P["best"]["completion_input_tick"] == 907 and P["bound"] == 882 and P["best"]["source"] == "run3:crossing_2026-11-11_run3c", f"best {P['best']['source']} {P['bound']}")
    check(sum(counts.values()) == 47 and counts["new"] + counts["replaced"] >= 1, f"every seed decided: {counts}")
    check(len(dg) == 2 and all(v["eligible"] >= 1 for v in dg.values()), f"D's two groups start eligible: {dg}")
    check(all(r["rows"] == r["niche_equal"] for r in x["inherit"]) and [Path(r["dir"]).name for r in x["inherit"]] == list(CHAIN), "the chain loads, niches equal")
    check([X["verified"] for X in x["best_from"]] == [0, 0] and p["readiness_override"] == ov, f"D best sources and the override recorded: {x['best_from']}")
    lv6 = [r for r in x["d_seeds"] if r["verdict"] == "replaced"]
    return {"counts": counts, "d_groups": dg, "replaced_prev": [(r["previous"]["tick"], r["tick"]) for r in lv6][:6], "groups": len(x["start"]),
            "eligible_per_level": {k: v.get("eligible") for k, v in p["archive"]["per_level"].items() if int(k) >= 6}, "inherited": p["archive"]["inherited"],
            "seed_set": x["d_seed_set_digest"][:16], "archive_set": p["archive_set_digest"][:16]}


REAL = {f.__name__: f for f in (real_d_folders, real_chain_plan)}

if __name__ == "__main__":
    args = sys.argv[1:]
    groups = {"unit": UNIT, "e2e": E2E, "real": REAL}
    tests = dict(groups[args[0]]) if args[:1] and args[0] in groups else dict(UNIT, **E2E, **REAL)
    rest = [x for x in args if x not in groups]
    try:
        code = run_suite("run3 hand-off tests", tests, rest)
    finally:
        import crossing_search_run3_tests as _CT
        if _CT._BENCH is not None:
            _CT._BENCH.close()
    sys.exit(code)
