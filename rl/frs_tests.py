"""Fast-route lab (frs) tests: zero native ticks (the synthetic stub world stands in for the game).

    python -B rl/frs_tests.py               every test
    python -B rl/frs_tests.py unit          the unit tests
    python -B rl/frs_tests.py e2e           the synthetic end-to-end runs
    python -B rl/frs_tests.py only <name>   the tests whose name contains <name>

Guard tests that arm the audit hook run in child processes (a hook cannot be removed). Design: logs/frs_prep/phase1_plan.md section 9.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

RL = Path(__file__).resolve().parent
REPO = RL.parent
sys.path.insert(0, str(RL))

import frs_guard as g  # noqa: E402

TESTS: List[Tuple[str, str, Callable[[], Optional[Dict[str, Any]]]]] = []


def unit(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("unit", fn.__name__, fn))
    return fn


def e2e(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("e2e", fn.__name__, fn))
    return fn


def check(cond: Any, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


CREATED: List[Path] = []


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"frs_{tag}_"))
    CREATED.append(p)
    return p


def run_child(code: str, timeout: float = 120.0) -> Dict[str, Any]:
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(RL))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(f"child failed: rc={r.returncode} stderr={r.stderr[-1500:]} stdout={r.stdout[-500:]}")


# =============================================================================================================================================
# frs_guard
# =============================================================================================================================================


@unit
def unit_guard_lab_root_matrix() -> Dict[str, Any]:
    t = tmpdir("g1")
    repo, ev1, ev2 = t / "repo", t / "ev1", t / "ev2"
    for d in (repo, ev1, ev2, repo / "runs"):
        d.mkdir(parents=True)
    ev = (ev1, ev2)
    ok = g.validate_lab_root(t / "lab", repo, ev)
    check(ok == Path(os.path.abspath(t / "lab")), "a plain folder beside the checkout is accepted")
    refused = {"checkout": repo, "inside_checkout": repo / "sub", "ancestor_of_checkout": t, "runs_component": t / "x" / "runs" / "y",
               "RUNS_component": t / "x" / "RUNS", "evidence": ev1, "inside_evidence": ev2 / "a", "relative": Path("lab_rel")}
    got = {}
    for name, p in refused.items():
        try:
            g.validate_lab_root(p, repo, ev)
            got[name] = "accepted"
        except g.LabRootError as exc:
            got[name] = str(exc)
    check(all(v != "accepted" for v in got.values()), f"every forbidden root is refused: {got}")
    # the real defaults
    check(g.validate_lab_root(g.DEFAULT_LAB_ROOT) == Path(os.path.abspath(g.DEFAULT_LAB_ROOT)), "C:/BattleShip_lab is accepted")
    real_refused = [g.REPO, g.REPO / "logs", g.REPO / "runs" / "x", Path("D:/BattleShip_runs_backup/x"), Path("D:/BattleShip_source_snapshots"),
                    Path("D:/BattleShip_exe_archive/a/b"), Path("C:/"), Path("C:/Users"), Path("D:/"), Path("C:/lab/Runs/n1")]
    for p in real_refused:
        try:
            g.validate_lab_root(p)
            raise AssertionError(f"{p} was accepted")
        except g.LabRootError:
            pass
    lab = t / "lab"
    check(g.validate_run_dir(lab / "lab_runs" / "a", lab) == Path(os.path.abspath(lab / "lab_runs" / "a")), "a run folder inside the lab root")
    for p in (lab, t / "elsewhere", lab / "runs" / "a"):
        try:
            g.validate_run_dir(p, lab)
            raise AssertionError(f"run folder {p} was accepted")
        except g.LabRootError:
            pass
    shutil.rmtree(t, ignore_errors=True)
    return {"refused": len(refused) + len(real_refused)}


GUARD_CHILD = r'''
import json, os, shutil, sys
from pathlib import Path
sys.path.insert(0, {rl!r})
import frs_guard as g
repo, lab, ev, out = Path({repo!r}), Path({lab!r}), Path({ev!r}), Path({out!r})
allowed = Path({allowed!r})
g.LabGuard.install(lab, repo=repo, evidence=[ev], allowed_reads=[allowed])
res = {{}}
def attempt(name, fn):
    try:
        fn(); res[name] = "allowed"
    except PermissionError as e:
        res[name] = "refused" if "frs lab guard" in str(e) else "perm"
    except Exception as e:
        res[name] = type(e).__name__
attempt("write_in", lambda: open(lab / "a.txt", "w").close())
attempt("mkdir_in", lambda: os.mkdir(lab / "d_in"))
attempt("write_out", lambda: open(out / "b.txt", "w").close())
attempt("append_out", lambda: open(out / "b2.txt", "a").close())
attempt("readwrite_out", lambda: open(out / "pre.txt", "r+").close())
attempt("osopen_out", lambda: os.close(os.open(out / "c.txt", os.O_CREAT | os.O_WRONLY)))
attempt("mkdir_out", lambda: os.mkdir(out / "d"))
attempt("replace_out", lambda: os.replace(lab / "a.txt", out / "e.txt"))
attempt("rename_from_out", lambda: os.rename(out / "pre.txt", lab / "stolen.txt"))
attempt("copy_out", lambda: shutil.copyfile(lab / "a.txt", out / "f.txt"))
attempt("copytree_out", lambda: shutil.copytree(lab / "d_in", out / "tree"))
attempt("remove_out", lambda: os.remove(out / "pre.txt"))
attempt("rmtree_out", lambda: shutil.rmtree(out / "predir"))
attempt("write_repo", lambda: open(repo / "x.txt", "w").close())
attempt("read_out", lambda: open(out / "pre.txt").read())
attempt("read_repo", lambda: open(repo / "code.py").read())
attempt("read_runs", lambda: open(repo / "runs" / "evidence.json").read())
attempt("list_runs", lambda: os.listdir(repo / "runs"))
attempt("scandir_runs", lambda: list(os.scandir(repo / "runs")))
attempt("read_ev", lambda: open(ev / "e.json").read())
attempt("read_fragment_tas", lambda: open(out / "tas_input" / "x.bin").read())
attempt("read_fragment_btti", lambda: open(out / "y.btti").read())
attempt("read_fragment_recordings", lambda: open(out / "replay" / "recordings" / "z.json").read())
attempt("read_allowed", lambda: open(allowed).read())
res["violations"] = len(g.LabGuard.violations)
res["out_listing"] = sorted(os.listdir(out))
res["repo_listing"] = sorted(os.listdir(repo))
print(json.dumps(res))
'''


@unit
def unit_guard_hook_writes_and_reads() -> Dict[str, Any]:
    t = tmpdir("g2")
    repo, lab, ev, out = t / "repo", t / "lab", t / "ev", t / "out"
    for d in (repo / "runs", lab, ev, out / "predir", out / "tas_input", out / "replay" / "recordings"):
        d.mkdir(parents=True)
    for f, s in ((repo / "code.py", "x = 1\n"), (repo / "runs" / "evidence.json", "{}"), (repo / "runs" / "allowed.json", "{}"),
                 (ev / "e.json", "{}"), (out / "pre.txt", "pre"), (out / "tas_input" / "x.bin", "t"), (out / "y.btti", "b"),
                 (out / "replay" / "recordings" / "z.json", "{}")):
        f.write_text(s, encoding="utf-8")
    res = run_child(GUARD_CHILD.format(rl=str(RL), repo=str(repo), lab=str(lab), ev=str(ev), out=str(out), allowed=str(repo / "runs" / "allowed.json")))
    want_allowed = ("write_in", "mkdir_in", "read_out", "read_repo", "read_allowed")
    want_refused = ("write_out", "append_out", "readwrite_out", "osopen_out", "mkdir_out", "replace_out", "rename_from_out", "copy_out",
                    "copytree_out", "remove_out", "rmtree_out", "write_repo", "read_runs", "list_runs", "scandir_runs", "read_ev",
                    "read_fragment_tas", "read_fragment_btti", "read_fragment_recordings")
    bad = {k: res.get(k) for k in want_allowed if res.get(k) != "allowed"}
    bad.update({k: res.get(k) for k in want_refused if res.get(k) != "refused"})
    check(not bad, f"guard outcomes differ: {bad}")
    check(res["out_listing"] == ["pre.txt", "predir", "replay", "tas_input", "y.btti"], f"nothing was written outside the lab root: {res['out_listing']}")
    check(res["repo_listing"] == ["code.py", "runs"], f"nothing was written in the checkout: {res['repo_listing']}")
    check(res["violations"] == len(want_refused), f"every refusal is recorded: {res['violations']}")
    shutil.rmtree(t, ignore_errors=True)
    return {"allowed": len(want_allowed), "refused": len(want_refused)}


@unit
def unit_guard_selftest_real_checkout() -> Dict[str, Any]:
    """The self-check's step 3 on the real checkout: a write under logs/ and a read under runs/ are refused, nothing is created."""
    t = tmpdir("g3")
    lab = t / "lab"
    lab.mkdir()
    rep = g.guard_selftest(lab)
    check(rep["ok"], f"guard self-test: {rep}")
    shutil.rmtree(t, ignore_errors=True)
    return {"child": rep["child"]}


NULL_CHILD = r'''
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, {rl!r})
import frs_guard as g
lab, out = Path({lab!r}), Path({out!r})
g.LabGuard.install(lab)
res = {{}}
try:
    r = subprocess.run([sys.executable, "-c", "print(1)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res["devnull_launch"] = "allowed" if r.returncode == 0 else f"rc {{r.returncode}}"
except PermissionError as e:
    res["devnull_launch"] = "refused"
try:
    with open(os.devnull, "w") as f:
        f.write("x")
    res["devnull_open"] = "allowed"
except PermissionError:
    res["devnull_open"] = "refused"
try:
    open(out / "notnul.txt", "w").close()
    res["file_outside"] = "allowed"
except PermissionError:
    res["file_outside"] = "refused"
res["violations"] = len(g.LabGuard.violations)
print(json.dumps(res))
'''


@unit
def unit_guard_allows_only_the_null_device() -> Dict[str, Any]:
    """Every process launch opens the OS null device read-write (subprocess.DEVNULL): allowed; any real file outside stays refused (the
    defect found by the first smoke attempt, 2026-10-14)."""
    t = tmpdir("gnul")
    (t / "lab").mkdir()
    (t / "out").mkdir()
    res = run_child(NULL_CHILD.format(rl=str(RL), lab=str(t / "lab"), out=str(t / "out")))
    check(res == {"devnull_launch": "allowed", "devnull_open": "allowed", "file_outside": "refused", "violations": 1}, f"{res}")
    check(not (t / "out" / "notnul.txt").exists(), "nothing written outside")
    import frs_guard as gg

    check(gg.LabGuard.is_null_device(os.devnull) and gg.LabGuard.is_null_device("\\\\.\\nul" if os.name == "nt" else os.devnull)
          and not gg.LabGuard.is_null_device("C:/x/nul_file") and not gg.LabGuard.is_null_device(str(t / "nul")), "only the device itself")
    return res


@unit
def unit_guard_fragments_superset() -> None:
    import m8_rd_worker as mw

    check(set(mw.FORBIDDEN_FRAGMENTS) < set(g.FORBIDDEN_FRAGMENTS) and "replay/recordings" in g.FORBIDDEN_FRAGMENTS,
          "the lab fragments are the worker's plus the human recordings")


@unit
def unit_guard_lock_and_writers() -> Dict[str, Any]:
    t = tmpdir("g4")
    lock = g.LabLock(t, "test")
    lock.acquire()
    second = g.LabLock(t, "test2")
    try:
        second.acquire()
        raise AssertionError("a second lock was granted while the first holder is alive")
    except g.LabRootError:
        pass
    lock.release()
    check(not (t / "lab.lock").exists(), "release removes the lock")
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    (t / "lab.lock").write_text(json.dumps({"pid": p.pid, "utc": "x", "what": "dead"}), encoding="utf-8")
    check(not g.pid_alive(p.pid), "a finished process is not alive")
    l3 = g.LabLock(t, "takeover")
    l3.acquire()
    check(l3.stale is not None and l3.stale["pid"] == p.pid, "a stale lock is taken over and reported")
    l3.release()
    fs = g.LabFS(t)
    fs.write_text(t / "a" / "b.txt", "x\r\ny\r\n")
    check((t / "a" / "b.txt").read_bytes() == b"x\ny\n", "LF only")
    fs.write_json(t / "c.json", {"k": 1})
    fs.append_jsonl(t / "d.jsonl", {"k": 1})
    fs.append_jsonl(t / "d.jsonl", {"k": 2})
    check(b"\r" not in (t / "c.json").read_bytes() + (t / "d.jsonl").read_bytes(), "json writers are LF")
    try:
        fs.write_text(t.parent / "outside_frs.txt", "x")
        raise AssertionError("LabFS wrote outside its root")
    except g.LabRootError:
        pass
    shutil.rmtree(t, ignore_errors=True)
    return {"stale_pid": p.pid}


# =============================================================================================================================================
# frs_machine
# =============================================================================================================================================


@unit
def unit_machine_budget_readiness_and_snapshot() -> Dict[str, Any]:
    import frs_machine as fm
    import m8_rd_session as ses

    check(fm.READINESS == ses.READINESS, "readiness thresholds are the registered ones")
    check(fm.CAPS_MB == {"main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024,
                         "system_commit_free_min": 2048} and fm.MAX_BATTLESHIP == 10, f"registered caps: {fm.CAPS_MB}")
    sb = fm.soft_budget()
    check(sb == {"main_private": 2560, "tree_private": 8192, "tree_working_set": 3584, "system_available_min": 1536,
                 "system_commit_free_min": 3072}, f"soft budget: {sb}")
    t = tmpdir("m1")
    good = fm.readiness(t, memory=lambda: {"available_mb": 8000.0, "commit_free_mb": 20000.0}, disk=lambda p: 50.0)
    check(good["ok"], f"ready: {good}")
    bad = fm.readiness(t, memory=lambda: {"available_mb": 4000.0, "commit_free_mb": 10000.0}, disk=lambda p: 4.0)
    check(not bad["ok"] and len(bad["problems"]) >= 4, f"refusals: {bad['problems']}")
    snap = fm.tree_snapshot()
    check(snap is not None and snap["main_private_mb"] > 0 and snap["processes"] >= 1 and snap["system_commit_free_mb"] > 0, f"snapshot {snap}")
    check(fm.main_private_mb() and fm.memory_status()["available_mb"] > 0, "own private bytes and system memory")
    shutil.rmtree(t, ignore_errors=True)
    return {"main_mb": snap["main_private_mb"], "tree_mb": snap["tree_private_mb"]}


@unit
def unit_machine_sampler_breaches_and_projection() -> Dict[str, Any]:
    import frs_machine as fm

    base = {"main_private_mb": 900.0, "tree_private_mb": 3000.0, "tree_working_set_mb": 2000.0, "processes": 12, "battleship": 10,
            "system_available_mb": 6000.0, "system_commit_free_mb": 9000.0}
    seq = [dict(base), dict(base, battleship=11), dict(base), dict(base, battleship=11), dict(base, battleship=12),
           dict(base, main_private_mb=2600.0), dict(base, main_private_mb=3100.0)]
    clock = {"t": 0.0}
    rows: List[Dict[str, Any]] = []
    cells = {"n": 1000}
    s = fm.Sampler(rows.append, snapshot=lambda: seq.pop(0) if seq else None, row_every=2.0, now=lambda: clock["t"],
                   extra=lambda: {"cells": cells["n"]})
    states = []
    for _ in range(7):
        s.sample()
        clock["t"] += 1.0
        cells["n"] += 100
        states.append((bool(s.proc_breach), bool(s.soft_breach), bool(s.hard_breach)))
    check(states[1] == (False, False, False) and states[3] == (False, False, False), f"one sample above the process cap is not a stop: {states}")
    check(states[4][0] and not states[4][1], f"two consecutive samples above the cap: {states}")
    check(states[5] == (True, True, False) and states[6] == (True, True, True), f"soft budget before the registered cap: {states}")
    check(len(rows) == 4 and all("cells" in r for r in rows), f"a row every 2 s: {len(rows)}")
    rep = s.report()
    check(rep["peak"]["main_private_mb"] == 3100.0 and rep["peak"]["battleship"] == 12, f"peaks {rep['peak']}")
    series = [{"t_s": i * 60.0, "cells": 50000 + 100 * i, "main_private_mb": 800.0 + 0.02 * 100 * i} for i in range(30)]
    pr = fm.projection(series, load_mb=780.0, load_cells=50000, explore_s=29 * 60.0, soft_main_mb=2560, cap_main_mb=3072)
    check(abs(pr["mb_per_1000_new_cells"] - 20.0) < 1e-6, f"slope {pr}")
    check(abs(pr["cells_per_explore_h"] - 6000.0) < 1e-6 and abs(pr["growth_mb_per_explore_h"] - 120.0) < 1e-6, f"growth {pr}")
    check(pr["projected_main_mb"] == {"8h": 1760.0, "24h": 3680.0, "48h": 6560.0}, f"projection {pr['projected_main_mb']}")
    check(pr["bytes_per_cell_at_load"] == round(780.0 * 2 ** 20 / 50000), "bytes per cell at load")
    return {"hours_to_soft": pr["hours_to_soft_budget"], "hours_to_cap": pr["hours_to_cap"]}


# =============================================================================================================================================
# frs_archive
# =============================================================================================================================================


def syn_ref(t: int = 150, session: str = "sd2", cid: int = 11, digest: str = "c" * 64) -> Dict[str, Any]:
    import m8_sd2_select as s6

    return s6.record_reference_block(completion_input_tick=t, completion_time_passed=t - 1, native_action_digest=digest, words=t, cid=cid,
                                     iteration=3, kind="clear", session=session, source="synthetic")


def synth6(seed: str = "frs6", n: Sequence[int] = (40, 50, 50, 50, 50, 50), floor_min: float = 1500.0) -> Any:
    """A six-part synthetic archive (rd1 under v1 ... sd2 under v4), keyed and deterministic (the registered test helpers' generator)."""
    import m8_rd2_tests as t2
    import m8_rd_tests as t1
    import m8_sd2_select as s6

    rng = t2.Krng(seed)
    a = s6.Archive6("syn6", floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    it = 0
    t2.drive2(a, rng, n[0], it, v2=False)
    it += n[0]
    a.begin_v2(it, "lines")
    t2.drive2(a, rng, n[1], it, v2=True)
    it += n[1]
    a.begin_rd3(it, "lines")
    t2.drive2(a, rng, n[2], it, v2=True)
    it += n[2]
    a.begin_rd4(it, "lines")
    t2.drive2(a, rng, n[3], it, v2=True)
    it += n[3]
    a.begin_sd1(it, "lines", syn_ref(200, "rd4", 7), 24)
    t2.drive2(a, rng, n[4], it, v2=True)
    it += n[4]
    a.begin_sd2(it, "lines", syn_ref(170, "sd1", 9), 24)
    t2.drive2(a, rng, n[5], it, v2=True)
    return a


def lab_of(seed: str = "frs6", *, e6: bool = False, label: str = "t1", t_rec: int = 150, margin: int = 24) -> Any:
    import frs_archive as fa

    lab = fa.LabArchive.from_archive6(synth6(seed), e6=e6)
    lab.configure_lab(first_iteration=lab.next_iteration(), draw_id=fa.draw_id_for(lab.archive_id, label), record_reference=syn_ref(t_rec),
                      margin=margin)
    return lab


@unit
def unit_archive_e6_equality_and_census() -> Dict[str, Any]:
    import frs_archive as fa

    a6 = synth6()
    lab = lab_of(e6=True)
    cen = fa.e6_census(lab, a6, draws=150)
    check(cen["equal_probabilities"] and cen["same_draws"] == 150, f"E6 on: the lab selects exactly as sd2's Archive6: {cen}")
    check(cen["bound_flags_e6_on"] > 0 and cen["made_eligible"] > 0 and cen["lost_eligibility"] == 0, f"E6 off only adds eligibility: {cen}")
    check(not lab.e6 and not any(lab.bound), "E6 off clears every bound flag")
    lab2 = lab_of(e6=True)
    before = [lab2.doom_v2(c) for c in lab2.cells]
    flags = list(lab2.bound)
    lab2.set_e6(False)
    after = [lab2.doom_v2(c) for c in lab2.cells]
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    check(all(flags[i] for i in changed) and changed, "the E6 switch changes doom only where the bound flag was set")
    check(lab2.desc == synth6().desc, "E5 (descent) flags are untouched")
    return {k: cen[k] for k in ("eligible_on", "eligible_off", "made_eligible", "bound_flags_e6_on")}


@unit
def unit_archive_lab_session_and_persistence() -> Dict[str, Any]:
    import frs_archive as fa
    import m8_sd2_select as s6

    lab = fa.LabArchive.from_archive6(synth6(), e6=False)
    nxt = lab.next_iteration()
    ev = lab.begin_lab(run_id="r", draw_id=fa.draw_id_for(lab.archive_id, "n1r1"), record_reference=syn_ref(150), margin=24,
                       explore={"contract": "x"})
    check(ev["first_iteration"] == nxt and ev["bound_max_L"] == 150 - 24 - 1 and ev["mode"] == "lab" and ev["e6"] is False, f"event {ev}")
    check(lab.draw_for(nxt) == "syn6_frs_n1r1" and lab.draw_for(nxt - 1) == lab.draw_id_sd2, "draw ids by iteration")
    check(lab.bound_for(nxt + 5) == 125 and lab.bound_for(nxt - 1) == lab.bound_max_L(), "bounds by iteration")
    probs = lab.lab_probabilities()
    check(probs and all(lab.cells[c].L <= 125 for c in probs if c != 0), "E7 at the lab bound")
    for bad in ("N1", "a b", "", "x" * 30):
        try:
            fa.draw_id_for("a", bad)
            raise AssertionError(f"label {bad!r} accepted")
        except fa.LabArchiveError:
            pass
    try:
        lab.begin_lab(run_id="r", draw_id="d", record_reference=syn_ref(150), margin=24, explore={})
        raise AssertionError("a second lab session was accepted")
    except fa.LabArchiveError:
        pass
    c = lab.dispatch(nxt, 0)
    lab.quarantine(c.id, nxt, "prefix_end") if c.id != 0 else None
    t = tmpdir("a2")
    lab.write_lab(t / "archive", {"checkpoint_seq": 1})
    try:
        s6.Archive6.read_dir(t / "archive")
        raise AssertionError("the registered loader accepted a lab archive")
    except s6.Select6Error:
        pass
    back, meta = fa.LabArchive.read_lab_dir(t / "archive")
    check(meta["frs_mode"] == "lab" and meta["mode"] == 2 and back.lab_bound_L == 125 and back.draw_id_lab == "syn6_frs_n1r1" and back.e6 is False
          and back.import_counts == lab.import_counts and len(back.cells) == len(lab.cells), "the lab archive reloads")
    shutil.rmtree(t, ignore_errors=True)
    return {"first_iteration": nxt, "eligible": len(probs)}


@unit
def unit_archive_quarantine() -> None:
    import frs_archive as fa

    lab = lab_of()
    it = lab.next_iteration()
    elig = [c for cs in lab.eligible_levels().values() for c in cs if c.id != 0]
    c = elig[0]
    lab.apply_dispatch(it, c.id, 0)
    lab.quarantine(c.id, it, "prefix_end")
    check(not lab.eligible(c) and c.id not in lab.lab_probabilities() and it not in lab._pending, "a quarantined cell is ineligible")
    check(lab.events[-1] == {"ev": "fail", "it": it, "why": "quarantine: prefix_end"}, f"ledger fail event {lab.events[-1]}")
    try:
        lab.quarantine(0, it + 1, "x")
        raise AssertionError("cell 0 was quarantined")
    except fa.LabArchiveError:
        pass
    check(set(fa.QUARANTINE_KINDS) == {"prefix_end", "prefix_ended", "terminal_expected"}, "the quarantinable mismatch kinds")


@unit
def unit_archive_continuation_trigger_table() -> Dict[str, Any]:
    lab = lab_of()
    c = next(c for c in lab.cells if c.id > 0 and c.L > 5)
    k = list(c.key)
    new_key = [99, 99, "G", 1023, 4]
    rows = {"new": [(c.L + 10, new_key)], "shorter": [(c.L - 1, k)], "equal": [(c.L, k)], "longer": [(c.L + 3, k)], "none": [],
            "mixed": [(c.L + 3, k), (c.L - 2, k)]}
    got = {name: lab.continuation_decision(r) for name, r in rows.items()}
    check([got[n]["go"] for n in ("new", "shorter", "equal", "longer", "none", "mixed")] == [True, True, False, False, False, True], f"{got}")
    check(got["shorter"]["max_gain"] == 1 and got["mixed"]["max_gain"] == 2 and got["new"]["new"] == 1, f"{got}")
    return {n: got[n]["go"] for n in got}


@unit
def unit_archive_continued_job_is_one_burst() -> Dict[str, Any]:
    """A continued job with a fall at word 300 is ingested as ONE burst: the fall dooms reaches made in its first segment (E5 descent, own
    burst) and its last 60 ticks (E4); the same reaches in a 120-word length-ended job are not doomed."""
    import m8_rd2_tests as t2
    import m8_rd_tests as t1

    def run(n: int, end: str) -> Dict[str, Any]:
        lab = lab_of()
        it = lab.next_iteration()
        start = lab.dispatch(it, 0)
        L = start.L
        reaches = [t1.reach(L + 20, (40, 40, "G", 1023, 3), t2.end17(12100.0, 12000.0, status=t2.STATUS["G"], ga=0, t=L + 20)),
                   t1.reach(L + 100, (41, 41, "A2", 1023, -1), t2.end17(12400.0, 12350.0, t=L + 100))]
        if n > 120:
            reaches.append(t1.reach(L + 250, (42, 42, "A1", 1023, -1), t2.end17(12700.0, 12650.0, jumps=2, t=L + 250)))
        res = t1.result(it, start, bytes(n), reaches, end, 0)
        info = lab.ingest(res)
        b = lab.bursts[info["burst"]]
        cells = {tuple(lab.cells[r[1]].key)[:2]: lab.cells[r[1]] for r in b.reaches}
        return {"n": len(b.words), "fall_tick": b.fall_tick, "doom": {str(k): lab.doom_v2(c) for k, c in cells.items()}}

    long = run(300, "fall")
    short = run(120, "length")
    check(long["n"] == 300 and long["fall_tick"] is not None, f"one burst of 300 words: {long}")
    check(long["doom"] == {"(40, 40)": False, "(41, 41)": True, "(42, 42)": True}, f"the late fall dooms the first segment's airborne reach: {long}")
    check(short["doom"] == {"(40, 40)": False, "(41, 41)": False}, f"a length-ended 120-word job dooms nothing: {short}")
    return {"long": long["doom"], "short": short["doom"]}


@unit
def unit_archive_stream_prefix_and_provenance() -> Dict[str, Any]:
    import frs_archive as fa
    import m8_rd_explore as mx
    import m8_rd_tests as t1

    for i in range(500):
        d, it = f"syn_frs_k{i % 7}", 1000 + i
        s480 = fa.stream_words(d, it, 480)
        s120 = bytes(mx.words(lambda idx: mx.explore_key(d, it, idx), 120))
        check(len(s480) == 480 and s480[:120] == s120 and fa.stream_words(d, it, 200) == s480[:200], f"stream prefix at key {i}")
    lab = lab_of(label="p1")
    it = lab.next_iteration()
    start = lab.dispatch(it, 0)
    words = fa.stream_words(lab.draw_id_lab, it, 240)
    info = lab.ingest(t1.result(it, start, words, [t1.reach(start.L + 7, (50, 50, "G", 1023, 4))], "length", 0))
    b = lab.bursts[info["burst"]]
    check(lab.provenance(b) and lab.lineage_provenance(b.id)["ok"], "a lab burst re-derives from its keys")
    lp = lab.lineage_provenance(b.id)
    check(lp["lab_bursts"] == 1 and lp["inherited_bursts"] == lp["bursts"] - 1, f"lineage split {lp}")
    b.words = bytes([(words[0] + 1) % 72]) + words[1:]
    check(not lab.provenance(b) and not lab.lineage_provenance(b.id)["ok"], "a tampered word fails provenance")
    old = lab.bursts[0]
    check(not lab.provenance(old), "an inherited burst is never a lab burst")
    return {"lineage": lp}


@unit
def unit_archive_reference_block() -> None:
    import frs_archive as fa

    meta = {"completion_clocks": {"completion_input_tick": 1885, "completion_time_passed": 1884}, "native_action_digest": "a" * 64,
            "words": 1885, "candidate": {"cid": 77, "kind": "clear"}, "iteration": 5, "session": "sd2"}
    rr = fa.record_reference_from_route(meta, "import/reference/metadata.json")
    check(rr["completion_input_tick"] == 1885 and rr["cid"] == 77 and rr["source"].startswith("import/"), f"{rr}")
    try:
        fa.record_reference_from_route(dict(meta, words=1884), "x")
        raise AssertionError("a reference whose words differ from its clock was accepted")
    except Exception as exc:  # noqa: BLE001 - the registered validator's error type
        check("word count" in str(exc), f"{exc}")


# =============================================================================================================================================
# frs_worker (in-process, on the synthetic stub world)
# =============================================================================================================================================


def stub_ctx(world: str = "easy", ask: Any = None, inject: Optional[Mapping[str, Any]] = None) -> Any:
    import frs_worker as fw
    import m8_rd_cells as mcell
    import m8_rd_stub as stub

    return fw.LabJobContext(stub.StubBackend({"rank": 0, "world": world, "inject": dict(inject or {})}), None, mcell.Classifier(), 0, None, ask)


def stub_archive(n_jobs: int = 40, world: str = "easy", aid: str = "stubA") -> Tuple[Any, Dict[str, Any]]:
    """A small v1 archive explored IN the stub world (so every prefix replays there), and its tick-0 pin."""
    import m8_rd_archive as march
    import m8_rd_worker as mw

    ctx = stub_ctx(world)
    t0 = mw.run_tick0(ctx, {"pin": None})
    pin = {"obs": t0["obs"], "digest": t0["digest"], "chain": t0["chain"], "key": t0["key"], "lines": t0["lines"], "mask": t0["mask"]}
    a = march.Archive(aid)
    a.init_cell0(tuple(t0["key"]), t0["obs"], bytes.fromhex(t0["digest"]), bytes.fromhex(t0["chain"]))
    for it in range(n_jobs):
        c = a.dispatch(it, 0)
        res = mw.run_iterate(ctx, iterate_job(a, c, it, pin, aid))
        a.ingest(dict(res, cum_before=0, session="t"))
    return a, pin


def iterate_job(a: Any, c: Any, it: int, pin: Mapping[str, Any], draw: str, *, seg: Optional[int] = None, max_seg: int = 1,
                window: int = 20) -> Dict[str, Any]:
    import frs_worker as fw
    import m8_rd_explore as mx

    s = seg or mx.BURST_WORDS
    job = {"kind": "iterate", "iteration": it, "cell": c.id, "rep": (c.burst, c.offset), "words": a.cell_words(c), "end": c.end,
           "end_digest": c.end_digest, "chain": c.chain, "terminal": c.terminal, "pin": dict(pin), "archive_id": draw,
           "burst_words": s, "allowance": c.L + s * max_seg}
    if seg is not None or max_seg != 1:
        job.update({"kind": fw.JOB_KIND, "segment_words": s, "max_segments": max_seg, "window": window})
    return job


VOLATILE = ("kind", "wall_s", "step_s", "ask_s", "startup", "pid", "worker_contract", "decisions", "segments", "tick0", "mode", "final_chain")


@unit
def unit_worker_one_segment_equals_run_iterate() -> Dict[str, Any]:
    import frs_worker as fw
    import m8_rd_explore as mx
    import m8_rd_worker as mw

    ends: Dict[str, int] = {}
    jobs = 0
    for world in ("easy", "hard"):
        a, pin = stub_archive(60, world)
        plan = [(c, 5000 + n, "stubA_frs_x") for n, c in enumerate([c for c in a.cells if not c.terminal][:30])]
        # the archive's own fall bursts, re-run from their (unchanged) start representative with their own key: the fall path
        plan += [(a.cells[b.start_cell], b.iteration, "stubA") for b in a.bursts
                 if b.end_reason == "fall" and (a.cells[b.start_cell].burst, a.cells[b.start_cell].offset) == tuple(b.start_rep)][:10]
        for c, it, draw in plan:
            base = mw.run_iterate(stub_ctx(world), iterate_job(a, c, it, pin, draw))
            job = dict(iterate_job(a, c, it, pin, draw), kind=fw.JOB_KIND, segment_words=mx.BURST_WORDS, max_segments=1, window=20)
            asked: List[Any] = []
            mine = fw.run_iterate_frs(stub_ctx(world, ask=lambda p: asked.append(p) or True), job)
            diff = sorted(k for k in set(base) | set(mine) if k not in VOLATILE and base.get(k) != mine.get(k))
            check(not diff, f"{world} cell {c.id}: run_iterate_frs differs from run_iterate in {diff}")
            check(not asked and mine["decisions"] == [], "one segment never asks")
            check(base["tick0"].get("equal") and mine["tick0"].get("equal"), "tick-0 pin equal")
            ends[base["end_reason"]] = ends.get(base["end_reason"], 0) + 1
            jobs += 1
    check(set(ends) - {"length"}, f"the equivalence covers a non-length ending too: {ends}")
    return {"jobs": jobs, "end_reasons": ends}


@unit
def unit_worker_continuation_yes_and_no() -> Dict[str, Any]:
    import frs_archive as fa
    import frs_worker as fw
    import m8_rd_explore as mx
    import m8_rd_worker as mw

    a, pin = stub_archive(30)
    draw = "stubA_frs_y"
    cells = [c for c in a.cells if not c.terminal][:20]
    full = 0
    for n, c in enumerate(cells):
        it = 7000 + n
        asked: List[Dict[str, Any]] = []
        yes = fw.run_iterate_frs(stub_ctx(ask=lambda p: asked.append(p) or True), iterate_job(a, c, it, pin, draw, seg=120, max_seg=4))
        n_w = len(yes["words"])
        check(yes["words"] == fa.stream_words(draw, it, n_w), f"cell {c.id}: the continued burst is the first {n_w} words of the stream")
        if yes["end_reason"] == "length":
            full += 1
            check(n_w == 480 and [d["segment"] for d in yes["decisions"]] == [1, 2, 3] and all(d["go"] for d in yes["decisions"]), f"{yes['decisions']}")
            check(yes["segments"] == 4 and yes["ticks"] == c.L + 480, "four segments, one job")
        else:
            check(len(asked) == n_w // 120 - (1 if n_w % 120 == 0 else 0) or len(asked) == n_w // 120, f"asks before the end: {len(asked)} for {n_w}")
        for p in asked:
            lo = c.L + p["words"] - 20
            check(all(r[0] > lo for r in p["reaches"]), "the payload holds only the last 20 words' reaches")
            check(p["iteration"] == it and p["cell"] == c.id and p["L"] == c.L, "payload identity")
        no = fw.run_iterate_frs(stub_ctx(ask=lambda p: False), iterate_job(a, c, it, pin, draw, seg=120, max_seg=4))
        base = mw.run_iterate(stub_ctx(), iterate_job(a, c, it, pin, draw))
        diff = sorted(k for k in set(base) | set(no) if k not in VOLATILE and base.get(k) != no.get(k))
        check(not diff, f"cell {c.id}: always-no differs from the 120-word job in {diff}")
        check(len(no["decisions"]) == (1 if base["end_reason"] == "length" else 0), f"one refused boundary: {no['decisions']}")
        tmo = fw.run_iterate_frs(stub_ctx(ask=lambda p: None), iterate_job(a, c, it, pin, draw, seg=120, max_seg=4))
        check(tmo["words"] == no["words"] and all(not d["answered"] and not d["go"] for d in tmo["decisions"]), "no answer = no")
    check(full > 0, "at least one job ran four full segments")
    check(fw.explore_digest(fw.explore_description(120, 4, 20)) != fw.explore_digest(fw.explore_description(120, 1, 20)), "contract digest")
    return {"jobs": len(cells), "full_480": full}


@unit
def unit_worker_mismatch_kinds() -> Dict[str, Any]:
    import frs_archive as fa
    import frs_worker as fw

    a, pin = stub_archive(25)
    c = next(c for c in a.cells if c.L >= 5 and not c.terminal)
    r = fw.run_job(stub_ctx(inject={"mismatch_job": [1], "mismatch_tick": 1}), iterate_job(a, c, 9000, pin, "d", seg=120, max_seg=4))
    check(r["kind"] == "mismatch" and r["mismatch"] in fa.QUARANTINE_KINDS and r["cell"] == c.id, f"a corrupted prefix: {r.get('mismatch')}")
    bad_pin = dict(pin, digest="0" * 64)
    r2 = fw.run_job(stub_ctx(), iterate_job(a, c, 9001, bad_pin, "d", seg=120, max_seg=4))
    check(r2["kind"] == "mismatch" and r2["mismatch"] == "tick0" and r2["mismatch"] not in fa.QUARANTINE_KINDS, f"tick-0 pin: {r2.get('mismatch')}")
    r3 = fw.run_job(stub_ctx(inject={"bad_consumed_job": 1}), iterate_job(a, c, 9002, pin, "d", seg=120, max_seg=4))
    check(r3["kind"] == "mismatch" and r3["mismatch"] == "consumed_tick", f"consumed tick: {r3.get('mismatch')}")
    return {"prefix": r["mismatch"], "pin": r2["mismatch"], "consumed": r3["mismatch"]}


# =============================================================================================================================================
# frs_verify (stub replays stand in for the fresh native processes)
# =============================================================================================================================================


_CLEAR_CACHE: Dict[str, Any] = {}


def stub_clear(world: str = "easy") -> Tuple[bytes, Dict[str, Any]]:
    """The words of a clear found by exploring the stub world, and the in-run claim (clocks, digest, chain) of its job."""
    import m8_rd_cells as mcell
    import m8_rd_stub as stub
    import frs_verify as fv

    if world not in _CLEAR_CACHE:
        a, _pin = stub_archive(300, world)
        b = next(b for b in a.bursts if b.end_reason == "clear")
        words = a.rep_words(*b.start_rep) + bytes(b.words)
        tr = stub.replay_trace(world, words)
        claim = {"words_digest": mcell.words_digest(words), "completion_input_tick": tr["result"]["completion_input_tick"],
                 "completion_time_passed": tr["result"]["completion_time_passed"], "chain": fv.chain_of(tr["initial"], tr["steps"]).hex()}
        _CLEAR_CACHE[world] = (words, claim)
    return _CLEAR_CACHE[world]


def stub_replay(world: str = "easy", tamper_second: bool = False, fail: int = 0) -> Any:
    import m8_rd_stub as stub

    calls = {"n": 0}

    def replay(words: bytes, label: str, slot: int) -> Dict[str, Any]:
        calls["n"] += 1
        if calls["n"] <= fail:
            raise RuntimeError("injected: the process did not start")
        tr = stub.replay_trace(world, words, label)
        if tamper_second and "_r2" in label:
            tr["steps"][-1] = dict(tr["steps"][-1], observation=dict(tr["steps"][-1]["observation"], position_x=1.5))
        return tr

    replay.calls = calls  # type: ignore[attr-defined]
    return replay


@unit
def unit_verify_verdicts_on_stub_clears() -> Dict[str, Any]:
    import frs_verify as fv
    import m8_rd_stub as stub

    words, claim = stub_clear("easy")
    ok = fv.verify_twice(stub_replay(), stub.analyse, words, claim, "c1", 0)
    check(ok["verdict"] == fv.VERIFIED and ok["r1"]["targets"] == 10 and ok["completion_input_tick"] == len(words), f"verified: {ok['verdict']} {ok['reasons']}")
    bad_clock = fv.verify_twice(stub_replay(), stub.analyse, words, dict(claim, completion_input_tick=len(words) - 1), "c2", 0)
    check(bad_clock["verdict"] == fv.NONDETERMINISTIC and "completion_input_tick" in bad_clock["reasons"][0], f"{bad_clock['reasons']}")
    bad_chain = fv.verify_twice(stub_replay(), stub.analyse, words, dict(claim, chain="0" * 64), "c3", 0)
    check(bad_chain["verdict"] == fv.NONDETERMINISTIC, "an in-run chain that differs is nondeterminism")
    differ = fv.verify_twice(stub_replay(tamper_second=True), stub.analyse, words, claim, "c4", 0)
    check(differ["verdict"] == fv.NONDETERMINISTIC and any("replay 2 differs" in r for r in differ["reasons"]), f"{differ['reasons']}")
    retry = fv.verify_twice(stub_replay(fail=1), stub.analyse, words, claim, "c5", 0)
    check(retry["verdict"] == fv.VERIFIED and len(retry["errors"]) == 1, "one failed start is retried in a fresh process")
    err = fv.verify_twice(stub_replay(fail=10), stub.analyse, words, claim, "c6", 0)
    check(err["verdict"] == fv.ERROR, "a replay that cannot run is an error, never a clear")
    short = fv.verify_twice(stub_replay(), stub.analyse, words[:-5], dict(claim, words_digest=__import__("m8_rd_cells").words_digest(words[:-5])), "c7", 0)
    check(short["verdict"] == fv.NONDETERMINISTIC and short["r1"]["outcome"] != "clear", "words that do not clear are not verified")
    return {"clear_ticks": len(words), "verdicts": [x["verdict"] for x in (ok, bad_clock, bad_chain, differ, retry, err, short)]}


@unit
def unit_verify_tick0_reference_and_stop_after_failure() -> Dict[str, Any]:
    import gzip as gz
    import frs_verify as fv
    import m8_rd_cells as mcell
    import m8_rd_stub as stub

    a, pin = stub_archive(5, "easy")
    t0 = stub.replay_trace("easy", b"")
    check(fv.tick0_check(t0, pin)["ok"], "the stub tick-0 record equals its pin")
    check(not fv.tick0_check(t0, dict(pin, digest="0" * 64))["ok"] and not fv.tick0_check(None, pin)["ok"], "a different pin fails")
    words, claim = stub_clear("easy")
    tr = stub.replay_trace("easy", words)
    tr["extra_env"] = dict(fv.FLAGS_VERIFY)
    t = tmpdir("v2")
    ref = t / "reference"
    ref.mkdir()
    (ref / "metadata.json").write_text(json.dumps({"words": len(words), "native_action_digest": mcell.words_digest(words)}), encoding="utf-8")
    with open(ref / "actions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for i, w in enumerate(words):
            b, x, y = mcell.TRIPLES[w]
            f.write(json.dumps({"buttons": b, "stick_x": x, "stick_y": y, "consumed_tick": i}) + "\n")
    with gz.open(ref / "trace.json.gz", "wt", encoding="utf-8") as f:
        json.dump(tr, f)
    R = fv.load_reference(ref, stub.analyse)
    check(not R["problems"] and R["words"] == words and R["expected"]["outcome"] == "clear", f"{R['problems']}")
    row = fv.evaluate(stub.replay_trace("easy", words), words, stub.analyse)
    rc = fv.reference_check(row, R)
    check(rc["ok"], f"the reference replays exactly: {rc}")
    row2 = fv.evaluate(stub.replay_trace("easy", words[:-1]), words[:-1], stub.analyse)
    check(not fv.reference_check(row2, R)["ok"], "a shorter replay is not the reference")
    tr_bad = dict(tr, extra_env=dict(fv.FLAGS_EXPLORE))
    with gz.open(ref / "trace.json.gz", "wt", encoding="utf-8") as f:
        json.dump(tr_bad, f)
    check(fv.load_reference(ref, stub.analyse)["problems"], "a reference trace made without the verify flags is refused")
    # StopAfterFailure: iteration ends after a native-failure reply
    acts = fv.StopAfterFailure([(0, 0, 0, i) for i in range(10)])
    seen = []
    for k, x in enumerate(acts):
        seen.append(x)
        acts.last = {"observation": {"game_status": mcell.GAME_STATUS_END if k == 3 else 0, "btt_active": 1, "targets_remaining": 5},
                     "state": mcell.STATE_WAITING}
    check(len(acts) == 10 and len(seen) == 4, f"submission stops after the failure reply: {len(seen)} of {len(acts)}")
    check(fv.FLAGS_VERIFY == {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "SSB64_RL_ENTITY": "1",
                              "SSB64_RL_TARGET_DIAG": "1", "SSB64_RL_INPUT": "1"}, "the verify flag set (S8)")
    shutil.rmtree(t, ignore_errors=True)
    return {"reference_ticks": len(words), "acts_seen": len(seen)}


# =============================================================================================================================================
# frs_run: synthetic end-to-end runs (stub world; the engine runs in a guarded child process, its workers are real spawned processes)
# =============================================================================================================================================


def build_stub_import(imp: Path, world: str = "easy", parts: Sequence[int] = (60, 40, 40, 40, 40, 60)) -> Dict[str, Any]:
    """A six-session archive (rd1 under v1 ... sd2 under v4) explored IN the stub world, written like sd2's closing archive, with the
    archive's own shortest clear as the reference route. THE WORLD IS SYNTHETIC."""
    import frs_verify as fv
    import gzip as gz
    import m8_rd_cells as mcell
    import m8_rd_stub as stub
    import m8_rd_worker as mw
    import m8_sd2_select as s6

    ctx = stub_ctx(world)
    t0 = mw.run_tick0(ctx, {"pin": None})
    pin = {"obs": t0["obs"], "digest": t0["digest"], "chain": t0["chain"], "key": t0["key"], "lines": t0["lines"], "mask": t0["mask"]}
    a = s6.Archive6("stubL", floor_min=-2550.0)
    a.init_cell0(tuple(t0["key"]), t0["obs"], bytes.fromhex(t0["digest"]), bytes.fromhex(t0["chain"]))
    state = {"it": 0, "cum": 0}

    def drive(n: int) -> None:
        for _ in range(n):
            it = state["it"]
            c = a.dispatch(it, 0)
            res = mw.run_iterate(ctx, iterate_job(a, c, it, pin, a.draw_for(it)))
            a.ingest(dict(res, cum_before=state["cum"], session="syn"))
            state["cum"] += res["ticks"]
            state["it"] += 1

    far = syn_ref(3000)
    drive(parts[0])
    a.begin_v2(state["it"], "lines")
    drive(parts[1])
    a.begin_rd3(state["it"], "lines")
    drive(parts[2])
    a.begin_rd4(state["it"], "lines")
    drive(parts[3])
    a.begin_sd1(state["it"], "lines", dict(far, session="rd4"), 24)
    drive(parts[4])
    a.begin_sd2(state["it"], "lines", dict(far, session="sd1"), 24)
    drive(parts[5])
    clears = [b for b in a.bursts if b.end_reason == "clear"]
    while not clears:
        drive(40)
        clears = [b for b in a.bursts if b.end_reason == "clear"]
    b = min(clears, key=lambda b: b.start_L + len(b.words))
    words = a.rep_words(*b.start_rep) + bytes(b.words)
    tr = stub.replay_trace(world, words)
    tr["extra_env"] = dict(fv.FLAGS_VERIFY)
    (imp / "archive").mkdir(parents=True)
    task = {"id": "synthetic_stub_world", "character": "none", "stage": "stub"}
    a.write_files(imp / "archive", {"pin_tick0": pin, "task": task, "checkpoint_seq": 1})
    ref = imp / "reference"
    ref.mkdir()
    meta = {"task": task, "schema": "m8_rd_route_v1", "session": "sd2", "native_action_digest": mcell.words_digest(words), "words": len(words),
            "candidate": {"kind": "clear", "cid": b.id}, "iteration": b.iteration,
            "completion_clocks": {"completion_input_tick": tr["result"]["completion_input_tick"], "completion_time_passed": tr["result"]["completion_time_passed"]}}
    (ref / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    with open(ref / "actions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for i, w in enumerate(words):
            bb, x, y = mcell.TRIPLES[w]
            f.write(json.dumps({"buttons": bb, "stick_x": x, "stick_y": y, "consumed_tick": i}) + "\n")
    with gz.open(ref / "trace.json.gz", "wt", encoding="utf-8") as f:
        json.dump(tr, f)
    (imp / "import_manifest.json").write_text(json.dumps({"mode": "lab", "synthetic": True}), encoding="utf-8")
    return {"cells": len(a.cells), "bursts": len(a.bursts), "reference_ticks": len(words)}


RUN_CHILD = r'''
import json, sys, time
from pathlib import Path
sys.path.insert(0, {rl!r})
import frs_guard as g
lab = Path({lab!r})
g.LabGuard.install(lab)
import frs_machine as fm
import frs_run as fr
import frs_tests as T
import m8_rd_stub as stub
world = {world!r}
run_dir = lab / "lab_runs" / {run_id!r}
inject = {inject!r}
soft = {soft!r}
snap_state = {{"n": 0}}
def snapshot():
    s = fm.tree_snapshot()
    snap_state["n"] += 1
    if soft is not None and s is not None and snap_state["n"] >= soft:
        s = dict(s, main_private_mb=99999.0 if {hard!r} else 2700.0)
    return s
caps = dict(fm.CAPS_MB, main_private=1e9) if not {hard!r} else None
env = fr.LabEnv(worker_spec=lambda rank: {{"rank": rank, "backend": {backend!r}, "world": world, "inject": inject.get(str(rank), {{}}),
                                           "failure_dir": str(run_dir / "failures"), "guard": g.LabGuard.spec(), "outside": {outside!r}}},
                replay=lambda words, label, slot: stub.replay_trace(world, words, label), analyse=stub.analyse,
                readiness=lambda: {{"ok": True, "problems": []}}, battleship_pids=lambda: [], snapshot=snapshot, import_problems=lambda: [],
                wait_no_battleship=lambda t: [], code_manifest=lambda: {{"rl/frs_run.py": g.sha256_file(Path({rl!r}) / "frs_run.py")}},
                backend="stub", sample_s=0.25, row_every_s=0.5, caps=caps, soft=(dict(fm.soft_budget(), main_private=2560) if soft is not None else None))
cfg = fr.LabRunConfig(lab_root=lab, run_dir=run_dir, run_id={run_id!r}, arm={arm!r}, label="t1", wall_s={wall!r}, open_reserve_s=8.0,
                      close_reserve_s=12.0, n_workers=3, progress_every_s=3.0, drain_grace_s=5.0, stop_grace_s=10.0, close_write_reserve_s=4.0,
                      quarantine_limit=3)
code = fr.Runner(cfg, env).run()
print(json.dumps({{"code": code, "violations": g.LabGuard.violations[:3]}}))
'''


class WritingStubBackend:
    """Test backend: the stub world, but its first acquire tries to write a file OUTSIDE the lab root (the worker's guard must refuse it)."""

    def __init__(self, spec: Mapping[str, Any]):
        import m8_rd_stub as stub

        self._b = stub.StubBackend(spec)
        self.outside = Path(spec["outside"])
        self.tried = False

    def acquire(self, wait_timeout: float = 0.0) -> Any:
        if not self.tried:
            self.tried = True
            with open(self.outside, "w") as f:
                f.write("must never exist")
        return self._b.acquire(wait_timeout)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._b, name)


_IMPORT_CACHE: Dict[str, Any] = {}


def e2e_lab(tag: str) -> Path:
    """A fresh lab root holding a copy of the synthetic import (built once per test session)."""
    if "dir" not in _IMPORT_CACHE:
        src = tmpdir("imp")
        _IMPORT_CACHE["info"] = build_stub_import(src / "import")
        _IMPORT_CACHE["dir"] = src
    lab = tmpdir(f"lab_{tag}")
    shutil.copytree(_IMPORT_CACHE["dir"] / "import", lab / "import")
    return lab


def run_e2e(lab: Path, *, arm: str, run_id: str, wall: float = 40.0, inject: Optional[Mapping[str, Any]] = None, soft: Optional[int] = None,
            hard: bool = False, backend: str = "m8_rd_stub:StubBackend", outside: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    code = RUN_CHILD.format(rl=str(RL), lab=str(lab), world="easy", run_id=run_id, inject=dict(inject or {}), soft=soft, hard=hard, arm=arm, wall=wall,
                            backend=backend, outside=outside)
    out = run_child(code, timeout=wall + 240)
    summ = json.loads((lab / "lab_runs" / run_id / "summary.json").read_text(encoding="utf-8"))
    return out, summ


def untracked_snapshot() -> List[str]:
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True, cwd=str(REPO))
    return sorted(ln for ln in r.stdout.splitlines() if "frs_" not in ln or not ln.startswith("??"))


@e2e
def e2e_control_run() -> Dict[str, Any]:
    import frs_archive as fa

    before = untracked_snapshot()
    lab = e2e_lab("ctl")
    out, s = run_e2e(lab, arm="CONTROL", run_id="ctl")
    check(out["code"] == 0 and s["status"] == "COMPLETED" and not out["violations"], f"CONTROL run: {out} {s['status']} {s['stop']}")
    check(s["clears"]["reference"] == "exact", f"the reference re-verified in-run: {s['clears']}")
    check(s["work"]["jobs"] > 50 and s["continuation"]["boundaries"] == 0, f"work {s['work']} cont {s['continuation']}")
    check(set(s["continuation"]["jobs_by_words"]) <= {"0", "120"}, f"CONTROL bursts are at most 120 words: {s['continuation']['jobs_by_words']}")
    check(all(r["verdict"] == "VERIFIED" for r in s["clears"]["rows"]), f"every verification passed: {s['clears']['rows'][:3]}")
    check(s["integrity"]["lab_bursts_bad"] == 0 and s["integrity"]["lab_bursts_rederived"] > 50, f"every lab burst re-derives: {s['integrity']}")
    back, meta = fa.LabArchive.read_lab_dir(lab / "lab_runs" / "ctl" / "archive")
    check(meta["frs_mode"] == "lab" and len(back.cells) == s["archive"]["cells_end"] and back.e6 is False, "the closing lab archive reloads")
    run_dir = lab / "lab_runs" / "ctl"
    for f in ("summary.json", "report.md", "config.json", "iterations.jsonl", "verifications.jsonl", "memory.jsonl", "run_log.jsonl"):
        check((run_dir / f).is_file() and b"\r" not in (run_dir / f).read_bytes(), f"{f} written, LF")
    idx = (lab / "frs_lab_index.md").read_text(encoding="utf-8")
    check(idx.startswith("# Fast-route lab index") and idx.count("| ctl |") == 1, "one index row")
    check(untracked_snapshot() == before, "nothing was written in the checkout")
    return {"jobs": s["work"]["jobs"], "clears": s["clears"]["verified"], "disp_h": s["throughput"]["dispatches_per_h"],
            "proj": s["memory"]["projection"].get("mb_per_1000_new_cells")}


@e2e
def e2e_cont_run() -> Dict[str, Any]:
    lab = e2e_lab("cont")
    out, s = run_e2e(lab, arm="CONT", run_id="cont")
    c = s["continuation"]
    check(out["code"] == 0 and s["status"] == "COMPLETED", f"CONT run: {out} {s['stop']}")
    check(c["boundaries"] > 0 and 0 < c["continued"] <= c["boundaries"], f"continuation fired: {c}")
    check(any(int(k) > 120 for k in c["jobs_by_words"]) and max(int(k) for k in c["jobs_by_words"]) <= 480, f"continued jobs: {c['jobs_by_words']}")
    check(s["integrity"]["lab_bursts_bad"] == 0 and s["clears"]["reference"] == "exact", f"{s['integrity']}")
    rows = [json.loads(ln) for ln in (lab / "lab_runs" / "cont" / "iterations.jsonl").read_text(encoding="utf-8").splitlines()]
    cont_rows = [r for r in rows if r["cont"]]
    check(all(len(r["cont"]) == sum(x[5] for x in r["cont"]) + (1 if r["end"] == "length" and r["n"] < 480 else 0) for r in cont_rows),
          "a job asked once per boundary it reached and stopped at the first no")
    check(all(r["n"] == 120 * (1 + sum(x[5] for x in r["cont"])) for r in cont_rows if r["end"] == "length"), "length-ended jobs are whole segments")
    return {"boundaries": c["boundaries"], "continued": c["continued"], "by_words": c["jobs_by_words"], "jobs": s["work"]["jobs"]}


@e2e
def e2e_quarantine_limit_is_invalid() -> Dict[str, Any]:
    lab = e2e_lab("q")
    inj = {str(r): {"mismatch_job": 1, "mismatch_tick": 1} for r in range(3)}
    out, s = run_e2e(lab, arm="CONT", run_id="q", inject=inj, wall=40.0)
    check(out["code"] == 3 and s["status"] == "LAB_INVALID" and s["quarantine"]["count"] >= 4 and s["stop"]["reason"] == "4 quarantines > 3",
          f"{out} {s['status']} {s['quarantine']} {s['stop']}")
    q = [json.loads(ln) for ln in (lab / "lab_runs" / "q" / "quarantine.jsonl").read_text(encoding="utf-8").splitlines()]
    check(len(q) == s["quarantine"]["count"] and all(r["kind"] == "prefix_end" for r in q), f"quarantine rows {q}")
    return {"quarantines": s["quarantine"]["count"], "stop": s["stop"]["reason"]}


@e2e
def e2e_memory_budget_stops_cleanly() -> Dict[str, Any]:
    lab = e2e_lab("mem")
    out, s = run_e2e(lab, arm="CONTROL", run_id="mem", soft=40, wall=60.0)
    check(out["code"] == 0 and s["status"] == "MEMORY_BUDGET" and "memory budget" in s["stop"]["reason"], f"{out} {s['status']} {s['stop']}")
    check(s["integrity"]["lab_bursts_bad"] == 0 and (lab / "lab_runs" / "mem" / "archive" / "manifest.sha256").is_file(), "closed cleanly")
    lab2 = e2e_lab("hard")
    out2, s2 = run_e2e(lab2, arm="CONTROL", run_id="hard", soft=40, hard=True, wall=60.0)
    check(out2["code"] == 4 and s2["status"] == "LAB_INCOMPLETE" and "registered memory cap" in s2["stop"]["reason"], f"{out2} {s2['stop']}")
    return {"soft_stop_explore_s": s["phase_wall_s"]["explore"], "hard": s2["stop"]["reason"][:60]}


@e2e
def e2e_worker_write_outside_is_refused() -> Dict[str, Any]:
    lab = e2e_lab("w")
    outside = lab.parent / f"frs_outside_{os.getpid()}.txt"
    out, s = run_e2e(lab, arm="CONTROL", run_id="w", backend="frs_tests:WritingStubBackend", outside=str(outside), wall=40.0)
    check(not outside.exists(), "the worker could not write outside the lab root")
    check(out["code"] == 3 and s["status"] == "LAB_INVALID", f"a worker guard violation makes the run invalid: {out} {s['status']} {s['stop']}")
    return {"stop": s["stop"]["reason"][:100]}


FAKE_RUN_CHILD = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, {rl!r})
import frs_guard as g
lab = Path({lab!r})
g.LabGuard.install(lab)
import frs_machine as fm, frs_run as fr, frs_verify as fv, m8_rd_stub as stub
from m7_runtime import install_kill_on_close_job
install_kill_on_close_job()
exe_dir = lab / "import" / "exe"
exe = exe_dir / "BattleShip.cmd"
frozen = json.loads((lab / "import" / "frozen_runtime.json").read_text(encoding="utf-8"))
run_dir = lab / "lab_runs" / "fake"
fake = {{"FAKEGAME_WORLD": "easy", "FAKEGAME_BOOT_S": "0.2", "FAKEGAME_LOG": str(lab / "fake.log")}}
def spec(rank):
    return {{"rank": rank, "root": str(run_dir / "workers" / f"w{{rank:02d}}"), "executable": str(exe), "flags": dict(fv.FLAGS_EXPLORE, **fake),
            "frozen_dir": str(exe_dir), "frozen_sha256": dict(frozen["frozen_sha256"]), "exe_sha256": frozen["exe_copy_sha256"]["BattleShip.cmd"],
            "runtime_sha256": dict(frozen["runtime_files"]), "port_base": 30000, "port_size": 250, "failure_dir": str(run_dir / "failures"),
            "guard": g.LabGuard.spec(), "timeouts": {{"startup": 30.0, "ready": 30.0, "request": 15.0, "exit": 15.0}}}}
env = fr.LabEnv(worker_spec=spec, replay=fv.make_real_replay(exe, run_dir / "vw", dict(fv.FLAGS_VERIFY, **fake), frozen), analyse=stub.analyse,
                readiness=lambda: {{"ok": True, "problems": []}}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot,
                import_problems=lambda: fv.frozen_exe_problems(exe_dir, frozen), wait_no_battleship=lambda t: [],
                code_manifest=lambda: {{"rl/frs_run.py": g.sha256_file(Path({rl!r}) / "frs_run.py")}}, backend="fakegame", caps=dict(fm.CAPS_MB, main_private=1e9))
cfg = fr.LabRunConfig(lab_root=lab, run_dir=run_dir, run_id="fake", arm="CONT", label="f1", wall_s={wall!r}, open_reserve_s=20.0, close_reserve_s=30.0,
                      n_workers=2, progress_every_s=10.0, drain_grace_s=10.0, stop_grace_s=20.0, close_write_reserve_s=10.0)
code = fr.Runner(cfg, env).run()
print(json.dumps({{"code": code, "violations": g.LabGuard.violations[:3]}}))
'''


@e2e
def e2e_real_lifecycle_with_fake_game() -> Dict[str, Any]:
    """The REAL launch path under the guard (battleship_process, m7_standby, the real backend, run_stepping_trace with the verify flags), a fake
    game behind the real M1d client (rl/m8_rd_fakegame.py, the stub world): the path the smoke run takes, without the game."""
    import frs_guard as gg

    lab = e2e_lab("fake")
    exe_dir = lab / "import" / "exe"
    exe_dir.mkdir(parents=True)
    for n in ("f3d.o2r", "BattleShip.o2r", "gamecontrollerdb.txt"):
        (exe_dir / n).write_bytes(b"fake")
    (exe_dir / "BattleShip.cmd").write_text(f'@"{sys.executable}" -B "{RL / "m8_rd_fakegame.py"}"\r\n', encoding="utf-8")
    (exe_dir / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"frozen": "FROZEN-CONFIG"}}), encoding="utf-8")
    (exe_dir / "imgui.ini").write_text("[frozen]\n", encoding="utf-8")
    sha = lambda n: gg.sha256_file(exe_dir / n)  # noqa: E731
    frozen = {"exe_copy_sha256": {n: sha(n) for n in ("BattleShip.cmd", "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")},
              "runtime_files": {n: sha(n) for n in ("BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")},
              "frozen_sha256": {n: sha(n) for n in ("BattleShip.cfg.json", "imgui.ini")}}
    (lab / "import" / "frozen_runtime.json").write_text(json.dumps(frozen), encoding="utf-8")
    wall = 100.0
    out = run_child(FAKE_RUN_CHILD.format(rl=str(RL), lab=str(lab), wall=wall), timeout=wall + 300)
    s = json.loads((lab / "lab_runs" / "fake" / "summary.json").read_text(encoding="utf-8"))
    check(out["code"] == 0 and s["status"] == "COMPLETED" and not out["violations"], f"{out} {s['status']} {s['stop']}")
    check(s["clears"]["reference"] == "exact", f"the reference replays exactly through run_stepping_trace: {s['clears']['rows'][:1]}")
    check(s["work"]["jobs"] >= 5 and s["work"]["tick0_unequal"] == 0 and s["integrity"]["lab_bursts_bad"] == 0, f"{s['work']} {s['integrity']}")
    logs = [json.loads(x) for x in (lab / "fake.log").read_text(encoding="utf-8").splitlines() if x.strip()]
    cfg_hash = sha("BattleShip.cfg.json")
    check(logs and all(r.get("cfg_sha256") in (cfg_hash, None) for r in logs if "cfg_sha256" in r), "every fake process saw the frozen configuration")
    return {"jobs": s["work"]["jobs"], "launches": len(logs), "verified": s["clears"]["verified"], "cont": [s["continuation"]["continued"],
            s["continuation"]["boundaries"]], "open_s": s["phase_wall_s"].get("open"), "close_s": s["phase_wall_s"].get("close")}


@unit
def unit_run_code_manifest() -> Dict[str, Any]:
    import frs_run as fr

    m1 = fr.code_manifest()
    m2 = fr.code_manifest()
    check(m1 == m2 and fr.code_digest(m1) == fr.code_digest(m2), "the code manifest is deterministic")
    must = {"rl/frs_guard.py", "rl/frs_run.py", "rl/frs_worker.py", "rl/m8_sd2_select.py", "rl/m8_rd_worker.py", "rl/m7f_trace.py", "rl/m7n_crossing.py",
            "rl/battleship_process.py", "rl/m7_standby.py"}
    check(must <= set(m1), f"missing: {sorted(must - set(m1))}")
    check(not any(k.startswith("runs/") for k in m1), "no evidence file")
    check(fr.ARMS["CONTROL"]["max_segments"] == 1 and fr.ARMS["CONT"]["max_segments"] == 4
          and {k: v for k, v in fr.ARMS["CONT"].items() if k != "max_segments"} == {k: v for k, v in fr.ARMS["CONTROL"].items() if k != "max_segments"},
          "the arms differ only in continuation")
    return {"files": len(m1), "digest": fr.code_digest(m1)[:16]}


# =============================================================================================================================================
# frs_lab: the planner, the import (on a fake source tree), the source guard
# =============================================================================================================================================


@unit
def unit_lab_planner() -> Dict[str, Any]:
    import frs_lab as fl

    lay = fl.night_layout(6, 75.0, "n1")
    check([r["arm"] for r in lay] == ["CONTROL", "CONT", "CONT", "CONTROL", "CONTROL", "CONT"], f"ABBA order: {lay}")
    check([r["label"] for r in lay] == ["n1r1", "n1r1", "n1r2", "n1r2", "n1r3", "n1r3"], "one label per pair")
    check([r["start_offset_min"] for r in lay] == [5.0, 81.0, 157.0, 233.0, 309.0, 385.0], f"offsets {lay}")
    check([r["arm"] for r in fl.night_layout(4, 60.0, "x")] == ["CONTROL", "CONT", "CONT", "CONTROL"]
          and [r["arm"] for r in fl.night_layout(8, 50.0, "x")] == ["CONTROL", "CONT", "CONT", "CONTROL"] * 2, "ABBA for 4 and 8")
    for bad in (1, 3, 5):
        try:
            fl.night_layout(bad, 60.0, "x")
            raise AssertionError(f"{bad} runs accepted")
        except SystemExit:
            pass
    t = tmpdir("plan")
    lab = t / "lab"
    r = subprocess.run([sys.executable, "-B", str(RL / "frs_lab.py"), "plan", "--lab-root", str(lab), "--night", "n1", "--runs", "6", "--wall-min", "75"],
                       capture_output=True, text=True, cwd=str(REPO))
    check(r.returncode == 0, f"plan: {r.stdout[-800:]} {r.stderr[-800:]}")
    sh = (lab / "nights" / "n1" / "night.sh").read_bytes()
    plan = json.loads((lab / "nights" / "n1" / "plan.json").read_text(encoding="utf-8"))
    check(b"\r" not in sh and plan["total_min"] == 5 + 6 * 76 and plan["explore_min"] == 65.0, f"plan {plan['total_min']} {plan['explore_min']}")
    txt = sh.decode("utf-8")
    runs = [ln for ln in txt.splitlines() if " run --lab-root" in ln]
    check(len(runs) == 6 and all(f"--expect-code {plan['code_digest']}" in ln and "--wall-min 75 " in ln for ln in runs), "six pinned run lines")
    check(txt.index("selfcheck") < txt.index(" run --lab-root") and "NIGHT COMPLETE" in txt and txt.count("exit 1; }") == 7, "self-check first, stops on non-zero")
    bash = shutil.which("bash")
    if bash:
        rb = subprocess.run([bash, "-n", str(lab / "nights" / "n1" / "night.sh")], capture_output=True, text=True)
        check(rb.returncode == 0, f"bash -n: {rb.stderr}")
    r2 = subprocess.run([sys.executable, "-B", str(RL / "frs_lab.py"), "plan", "--lab-root", str(lab), "--night", "n1", "--runs", "6", "--wall-min", "75"],
                        capture_output=True, text=True, cwd=str(REPO))
    check(r2.returncode == 2, "a night folder is never overwritten")
    r3 = subprocess.run([sys.executable, "-B", str(RL / "frs_lab.py"), "plan", "--lab-root", str(lab), "--night", "n2", "--runs", "6", "--hours", "8"],
                        capture_output=True, text=True, cwd=str(REPO))
    p3 = json.loads((lab / "nights" / "n2" / "plan.json").read_text(encoding="utf-8"))
    check(r3.returncode == 0 and p3["wall_min"] == 78.0 and p3["total_min"] <= 480, f"--hours 8: {p3['wall_min']}")
    for bad_root in (str(REPO / "x"), "C:/", str(REPO / "runs" / "lab")):
        rb = subprocess.run([sys.executable, "-B", str(RL / "frs_lab.py"), "plan", "--lab-root", bad_root, "--night", "z", "--runs", "2", "--wall-min", "30"],
                            capture_output=True, text=True, cwd=str(REPO))
        check(rb.returncode != 0 and "refused" in (rb.stdout + rb.stderr), f"lab root {bad_root} refused")
    shutil.rmtree(t, ignore_errors=True)
    return {"total_min": plan["total_min"], "bash_checked": bool(bash)}


IMPORT_CHILD = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, {rl!r})
import frs_lab as fl, frs_verify as fv, m8_rd_stub as stub
src = Path({src!r})
fl.ARCHIVE_SRC, fl.ROUTE_SRC, fl.RUNTIME_SRC = src / "archive", src / "route", src / "runtime"
fl.PINNED_EXE_SHA256 = {pinned!r}
fv.real_analyse = stub.analyse
print(json.dumps({{"code": fl.cmd_import(Path({lab!r}))}}))
'''


@unit
def unit_lab_import_on_fake_tree() -> Dict[str, Any]:
    import frs_guard as gg

    t = tmpdir("imp")
    if "dir" not in _IMPORT_CACHE:
        e2e_lab("warm")
    syn = _IMPORT_CACHE["dir"] / "import"
    src = t / "src"
    shutil.copytree(syn / "archive", src / "archive")
    shutil.copytree(syn / "reference", src / "route")
    (src / "runtime" / "exe" / ".tcc").mkdir(parents=True)
    files = {"BattleShip.exe": b"exe", "BattleShip.o2r": b"o2r", "f3d.o2r": b"f3d", "gamecontrollerdb.txt": b"db", "config.yml": b"y"}
    for n, b in files.items():
        (src / "runtime" / "exe" / n).write_bytes(b)
    (src / "runtime" / "exe" / ".tcc" / "lib.h").write_bytes(b"h")
    (src / "runtime" / "BattleShip.cfg.json").write_bytes(b"{}")
    (src / "runtime" / "imgui.ini").write_bytes(b"[x]")
    sha = lambda p: gg.sha256_file(p)  # noqa: E731
    fz = {"frozen_sha256": {"BattleShip.cfg.json": sha(src / "runtime" / "BattleShip.cfg.json"), "imgui.ini": sha(src / "runtime" / "imgui.ini")},
          "exe_copy_sha256": {n: sha(src / "runtime" / "exe" / n) for n in files},
          "runtime_files": {n: sha(src / "runtime" / "exe" / n) for n in ("BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")}}
    (src / "runtime" / "frozen_runtime.json").write_text(json.dumps(fz), encoding="utf-8")
    exe_sha = fz["exe_copy_sha256"]["BattleShip.exe"]

    def imp(lab: Path, pinned: str) -> int:
        return run_child(IMPORT_CHILD.format(rl=str(RL), src=str(src), lab=str(lab), pinned=pinned))["code"]

    lab = t / "lab"
    check(imp(lab, "0" * 64) == 2 and not (lab / "import").exists() and list(lab.glob("import_refused_*.json")), "a wrong executable hash is refused")
    check(imp(lab, exe_sha) == 0 and (lab / "import" / "import_manifest.json").is_file(), "the import")
    man = json.loads((lab / "import" / "import_manifest.json").read_text(encoding="utf-8"))
    check({"exe/BattleShip.exe", "exe/BattleShip.cfg.json", "exe/imgui.ini", "exe/.tcc/lib.h", "frozen_runtime.json", "archive/cells.jsonl",
           "reference/actions.jsonl"} <= set(man["copies"]), f"copies {sorted(man['copies'])[:12]}")
    check(man["reference"]["completion_input_tick"] == _IMPORT_CACHE["info"]["reference_ticks"] and man["mode"] == "lab", "reference block")
    check(imp(lab, exe_sha) == 2, "a second import is refused")
    import frs_lab as fl

    check(fl.import_problems(lab) == [], "the copies re-hash")
    (lab / "import" / "exe" / "config.yml").write_bytes(b"changed")
    check(fl.import_problems(lab) == ["exe/config.yml differs from the import manifest"], f"{fl.import_problems(lab)}")
    (src / "runtime" / "imgui.ini").write_bytes(b"[changed]")
    lab2 = t / "lab2"
    check(imp(lab2, exe_sha) == 2 and not (lab2 / "import").exists(), "a frozen file that differs from frozen_runtime.json is refused")
    shutil.rmtree(t, ignore_errors=True)
    return {"copies": len(man["copies"])}


@unit
def unit_index_header_matches_tracked_file() -> Dict[str, Any]:
    import frs_report as frep

    doc = (REPO / "docs" / "frs_lab_index.md").read_text(encoding="utf-8")
    hdr = frep.index_header().splitlines()
    check(doc.startswith(hdr[0] + "\n\n" + hdr[2]), "the tracked index starts with the runner's title and intro")
    check(hdr[4] in doc.splitlines() and hdr[5] in doc.splitlines(), "the tracked index has the runner's table header: copied rows line up")
    check("No KEEP or DROP decision is taken from night 1" in doc and "mechanism and spread check" in doc, "night 1 is pre-registered")
    return {"columns": len(frep.INDEX_COLUMNS)}


SOURCE_INT_ALLOW = {1000: "per 1,000 cells; ms per s", 1024: "memory headroom MB", 1500: "log text truncation", 2000: "log text truncation",
                    3000: "log text truncation", 3600: "seconds per hour", 4096: "0x1000 PROCESS_QUERY_LIMITED_INFORMATION",
                    9000: "verification replay index base (m8_rd_session uses 9000 + cid)", 30000: "the registered worker port base",
                    50_000_000: "the safety tick cap"}


@unit
def unit_source_guard_and_lf() -> Dict[str, Any]:
    import ast

    files = sorted(RL.glob("frs_*.py"))
    check(len(files) == 9, f"nine frs modules: {[f.name for f in files]}")
    for f in files + sorted((REPO / "docs").glob("frs_*.md")):
        check(b"\r" not in f.read_bytes(), f"{f.name} has CR bytes")
    lits: Dict[str, List[int]] = {}
    for f in files:
        if f.name == "frs_tests.py":
            continue
        src = f.read_text(encoding="utf-8")
        low = src.lower()
        frags = ("import random", "random.", "seed(") if f.name == "frs_guard.py" else             ("tas_input", "mario_743", ".btti", "replay/recordings", "import random", "random.", "seed(")   # frs_guard defines the forbidden list
        for frag in frags:
            if frag in low:
                raise AssertionError(f"{f.name} contains {frag!r}")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool) and node.value >= 1000:
                lits.setdefault(f.name, []).append(node.value)
    bad = {f: [v for v in vs if v not in SOURCE_INT_ALLOW] for f, vs in lits.items()}
    bad = {f: v for f, v in bad.items() if v}
    check(not bad, f"integer literals >= 1000 outside the named allowlist (no cid, coordinate, route tick or census number): {bad}")
    return {"files": len(files), "literals": {f: sorted(set(v)) for f, v in lits.items()}}


# =============================================================================================================================================
# runner
# =============================================================================================================================================


def main(argv: Sequence[str]) -> int:
    sel = argv[1] if len(argv) > 1 else "all"
    pick = [t for t in TESTS if sel == "all" or t[0] == sel or (sel == "only" and len(argv) > 2 and argv[2] in t[1])]
    passed = 0
    t_all = time.perf_counter()
    for kind, name, fn in pick:
        t0 = time.perf_counter()
        try:
            info = fn()
            passed += 1
            extra = json.dumps(info, default=str, separators=(",", ":"))[:240] if info else ""
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s) {extra}", flush=True)
        except Exception as exc:  # noqa: BLE001 - reported per test
            print(f"FAIL {name} ({time.perf_counter() - t0:.1f} s): {type(exc).__name__}: {exc}"[:3000], flush=True)
            print(traceback.format_exc()[-2500:], flush=True)
    for p in CREATED:
        shutil.rmtree(p, ignore_errors=True)
    print(f"frs tests: {passed}/{len(pick)} passed in {time.perf_counter() - t_all:.0f} s")
    return 0 if passed == len(pick) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
