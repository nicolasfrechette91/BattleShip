#!/usr/bin/env python3
"""Fast-route lab (frs) command line. Lab mode: exploratory, unregistered; writes only under the lab root.

    python -B rl/frs_lab.py import    --lab-root C:/BattleShip_lab            one-time hashed copy of sd2's closing archive, its best verified clear
                                                                            and the frozen runtime (the only command that reads runs/)
    python -B rl/frs_lab.py selfcheck --lab-root C:/BattleShip_lab [--out DIR] pins, guards, readiness, E6 equality and census, tick-0 pin,
                                                                            reference replay (a few minutes)
    python -B rl/frs_lab.py run       --lab-root C:/BattleShip_lab --arm CONTROL|CONT --wall-min 75 --label n1r1 [--run-dir DIR] [--expect-code SHA]
                                      [--open-reserve-min 4] [--close-reserve-min 6]
    python -B rl/frs_lab.py plan      --lab-root C:/BattleShip_lab --night n1 --runs 6 (--hours 8 | --wall-min 75)   writes nights/<night>/night.sh
    python -B rl/frs_lab.py smoke     --lab-root C:/BattleShip_lab [--date YYYY-MM-DD]   self-check + one short CONT run, 10 minutes in all
    python -B rl/frs_lab.py report    --run-dir DIR

Exit codes: 0 completed (or memory budget), 2 refused (nothing launched), 3 LAB_INVALID / self-check FAIL, 4 LAB_INCOMPLETE. Light top-level
imports only: spawned workers re-import this module. Design: logs/frs_prep/phase1_plan.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import frs_guard as g  # noqa: E402

REPO = g.REPO
# the one-time import's sources (read by `import` only)
ARCHIVE_SRC = REPO / "runs" / "m8_rd_sd2" / "archive"
ROUTE_SRC = REPO / "runs" / "m8_rd_sd2" / "routes" / "T_clear_best"
RUNTIME_SRC = REPO / "runs" / "m8_rd" / "archive" / "runtime"
ARCHIVE_FILES = ("archive_meta.json", "cells.jsonl", "bursts.bin", "bursts.idx.jsonl", "events.jsonl", "manifest.sha256")
ROUTE_FILES = ("metadata.json", "actions.jsonl", "trace.json.gz")
RUNTIME_FILES = ("frozen_runtime.json", "BattleShip.cfg.json", "imgui.ini")
PINNED_EXE_SHA256 = "30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee"     # the registered executable (owner's import condition)
ABBA = ("CONTROL", "CONT", "CONT", "CONTROL")
SELFCHECK_MIN = 5
GAP_MIN = 1
SMOKE_TOTAL_S = 600.0


def out_line(obj: Any) -> None:
    print(json.dumps(obj, separators=(",", ":"), default=str), flush=True)


def lab_root_arg(p: str) -> Path:
    try:
        return g.validate_lab_root(Path(p))
    except g.LabRootError as exc:
        raise SystemExit(str(exc))


def git_state() -> Dict[str, Any]:
    def git(*a: str) -> str:
        r = subprocess.run(["git", *a], capture_output=True, text=True, cwd=str(REPO))
        return r.stdout.strip()

    st = [ln for ln in git("status", "--porcelain", "--untracked-files=all").splitlines() if ln.strip()]
    return {"head": git("rev-parse", "HEAD"), "status_lines": len(st), "tracked_changes": [ln for ln in st if not ln.startswith("??")][:10]}


# -- import --------------------------------------------------------------------------------------------------------------------------------


def import_sources() -> Dict[str, List[Path]]:
    exe = sorted(p for p in (RUNTIME_SRC / "exe").rglob("*") if p.is_file())
    return {"archive": [ARCHIVE_SRC / n for n in ARCHIVE_FILES], "reference": [ROUTE_SRC / n for n in ROUTE_FILES],
            "runtime": [RUNTIME_SRC / n for n in RUNTIME_FILES], "exe": exe}


def import_plan(src: Mapping[str, List[Path]], imp: Path) -> List[tuple]:
    """(source, destination) pairs: the archive, the reference route, the exe copy, the frozen config BESIDE the exe, frozen_runtime.json."""
    pairs = [(p, imp / "archive" / p.name) for p in src["archive"]] + [(p, imp / "reference" / p.name) for p in src["reference"]]
    pairs += [(p, imp / "exe" / p.relative_to(RUNTIME_SRC / "exe")) for p in src["exe"]]
    pairs += [(RUNTIME_SRC / "BattleShip.cfg.json", imp / "exe" / "BattleShip.cfg.json"), (RUNTIME_SRC / "imgui.ini", imp / "exe" / "imgui.ini"),
              (RUNTIME_SRC / "frozen_runtime.json", imp / "frozen_runtime.json")]
    return pairs


def source_problems(sha: Mapping[Path, str]) -> List[str]:
    """The owner's refusal rule: the executable is 30a3913b and every file matches frozen_runtime.json; the archive matches its manifest."""
    probs: List[str] = []
    fz = json.loads((RUNTIME_SRC / "frozen_runtime.json").read_text(encoding="utf-8"))
    exe_sha = sha.get(RUNTIME_SRC / "exe" / "BattleShip.exe")
    if exe_sha != PINNED_EXE_SHA256:
        probs.append(f"BattleShip.exe sha256 {exe_sha} is not the pinned {PINNED_EXE_SHA256}")
    for n, h in fz["exe_copy_sha256"].items():
        if sha.get(RUNTIME_SRC / "exe" / n) != h:
            probs.append(f"exe/{n} differs from frozen_runtime.json")
    for n, h in fz["runtime_files"].items():
        if sha.get(RUNTIME_SRC / "exe" / n) != h:
            probs.append(f"runtime file exe/{n} differs from frozen_runtime.json")
    for n, h in fz["frozen_sha256"].items():
        if sha.get(RUNTIME_SRC / n) != h:
            probs.append(f"frozen {n} differs from frozen_runtime.json")
    man = {ln.split()[1]: ln.split()[0] for ln in (ARCHIVE_SRC / "manifest.sha256").read_text(encoding="utf-8").splitlines() if ln.strip()}
    for n in ARCHIVE_FILES:
        if n != "manifest.sha256" and sha.get(ARCHIVE_SRC / n) != man.get(n):
            probs.append(f"archive {n} differs from the archive manifest")
    return probs


def cmd_import(lab: Path) -> int:
    imp, tmp = lab / "import", lab / "import.tmp"
    if imp.exists():
        print(f"refused: {imp} exists (the import is one-time and never overwritten)")
        return 2
    src = import_sources()
    allp = [p for v in src.values() for p in v]
    missing = [str(p) for p in allp if not p.is_file()]
    if missing or not src["exe"]:
        print(f"refused: missing import sources: {missing[:5]}")
        return 2
    lab.mkdir(parents=True, exist_ok=True)
    g.LabGuard.install(lab, allowed_reads=allp)
    lock = g.LabLock(lab, "import")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    fs = g.LabFS(lab)
    try:
        if tmp.exists():
            shutil.rmtree(tmp)
        sha = {p: g.sha256_file(p) for p in allp}
        probs = source_problems(sha)
        if probs:
            fs.write_json(lab / f"import_refused_{g.utc_compact()}.json", {"mode": "lab", "utc": g.utc(), "problems": probs})
            print(f"refused: {probs}")
            return 2
        copies: Dict[str, str] = {}
        sources: Dict[str, str] = {}
        for s, d in import_plan(src, tmp):
            fs.mkdir(d.parent)
            shutil.copyfile(s, d)
            h = g.sha256_file(d)
            if h != sha[s]:
                print(f"refused: the copy of {s} differs from its source")
                return 2
            copies[d.relative_to(tmp).as_posix()] = h
            sources[s.relative_to(REPO).as_posix() if g.under(g.norm(s), g.norm(REPO)) else s.as_posix()] = sha[s]
        import m8_rd_archive as march
        import frs_archive as fa
        import frs_verify as fv

        bad = march.verify_manifest(tmp / "archive")
        ref = fv.load_reference(tmp / "reference", fv.real_analyse)
        if bad or ref["problems"]:
            print(f"refused: archive manifest {bad[:3]}, reference {ref['problems']}")
            return 2
        meta = json.loads((tmp / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
        rr = fa.record_reference_from_route(ref["meta"], "import/reference/metadata.json")
        man = {"mode": "lab", "schema": "frs_lab_import_v1", "utc": g.utc(), "git": git_state(), "sources": sources, "copies": copies,
               "exe_sha256": sha[RUNTIME_SRC / "exe" / "BattleShip.exe"], "archive": {k: meta.get(k) for k in ("archive_id", "cells", "bursts", "events",
                                                                                                                  "checkpoint_seq", "draw_id")},
               "pin_tick0": meta.get("pin_tick0"), "task": meta.get("task"), "reference": rr,
               "reference_expected": {k: ref["expected"][k] for k in ("completion_input_tick", "completion_time_passed", "final_chain", "ticks")}}
        fs.write_json(tmp / "import_manifest.json", man)
        os.replace(tmp, imp)
        out_line({"import": str(imp), "files": len(copies), "archive": man["archive"], "reference": [rr["completion_input_tick"], rr["completion_time_passed"]],
                  "exe": man["exe_sha256"][:16], "import_manifest_sha256": g.sha256_file(imp / "import_manifest.json")[:16]})
        return 0
    finally:
        lock.release()


def import_problems(lab: Path) -> List[str]:
    """Every copied file re-hashed against the import manifest (the archive, the reference, the exe copy, the frozen config)."""
    imp = lab / "import"
    mp = imp / "import_manifest.json"
    if not mp.is_file():
        return ["no import manifest: run the import first"]
    man = json.loads(mp.read_text(encoding="utf-8"))
    probs = [f"{rel} differs from the import manifest" for rel, h in man["copies"].items()
             if not (imp / rel).is_file() or g.sha256_file(imp / rel) != h]
    return probs


# -- the real environment ---------------------------------------------------------------------------------------------------------------------


def real_env(lab: Path, run_dir: Path) -> Any:
    import frs_machine as fm
    import frs_run as fr
    import frs_verify as fv
    from m7_runtime import BATTLESHIP_IMAGE, wait_until_no_process

    imp = lab / "import"
    frozen = json.loads((imp / "frozen_runtime.json").read_text(encoding="utf-8"))
    exe = imp / "exe" / "BattleShip.exe"

    def spec(rank: int) -> Dict[str, Any]:
        return {"rank": rank, "root": str(run_dir / "workers" / f"w{rank:02d}"), "executable": str(exe), "flags": dict(fv.FLAGS_EXPLORE),
                "frozen_dir": str(imp / "exe"), "frozen_sha256": dict(frozen["frozen_sha256"]), "exe_sha256": frozen["exe_copy_sha256"]["BattleShip.exe"],
                "runtime_sha256": dict(frozen["runtime_files"]), "port_base": 30000, "port_size": 250, "failure_dir": str(run_dir / "failures"),
                "guard": g.LabGuard.spec()}

    return fr.LabEnv(worker_spec=spec, replay=fv.make_real_replay(exe, run_dir / "vw", fv.FLAGS_VERIFY, frozen), analyse=fv.real_analyse,
                     readiness=lambda: fm.readiness(lab), battleship_pids=fm.battleship_pids, snapshot=fm.tree_snapshot,
                     import_problems=lambda: import_problems(lab) + fv.frozen_exe_problems(imp / "exe", frozen),
                     wait_no_battleship=lambda t: wait_until_no_process(BATTLESHIP_IMAGE, timeout=t), code_manifest=fr.code_manifest, backend="real")


# -- run ----------------------------------------------------------------------------------------------------------------------------------------


def cmd_run(a: argparse.Namespace) -> int:
    lab = lab_root_arg(a.lab_root)
    import frs_archive as fa

    if a.arm not in ("CONTROL", "CONT"):
        raise SystemExit(f"refused: arm {a.arm!r} (CONTROL or CONT)")
    if not fa.LABEL_RE.match(a.label):
        raise SystemExit(f"refused: label {a.label!r} (1-24 lower-case letters or digits)")
    if not 0 < a.wall_min <= 24 * 60:
        raise SystemExit(f"refused: wall {a.wall_min} min")
    run_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')}_{a.arm}_{a.label}"
    try:
        run_dir = g.validate_run_dir(Path(a.run_dir) if a.run_dir else lab / "lab_runs" / run_id, lab)
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    if run_dir.exists():
        print(f"refused: {run_dir} exists (never overwritten)")
        return 2
    if not (lab / "import" / "import_manifest.json").is_file():
        print("refused: no import (run `import` first)")
        return 2
    g.LabGuard.install(lab)
    lock = g.LabLock(lab, f"run {run_id}")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    try:
        import frs_run as fr
        from m7_runtime import install_kill_on_close_job

        install_kill_on_close_job()
        cfg = fr.LabRunConfig(lab_root=lab, run_dir=run_dir, run_id=run_id, arm=a.arm, label=a.label, wall_s=60.0 * a.wall_min,
                              open_reserve_s=60.0 * a.open_reserve_min, close_reserve_s=60.0 * a.close_reserve_min, n_workers=a.workers,
                              expect_code=a.expect_code)
        if cfg.explore_s <= 0:
            print("refused: the wall leaves no exploration time after the reserves")
            return 2
        code = fr.Runner(cfg, real_env(lab, run_dir)).run()
        print(f"exit {code}: {run_dir / 'report.md'}")
        return code
    finally:
        lock.release()


# -- self-check ------------------------------------------------------------------------------------------------------------------------------


def cmd_selfcheck(lab: Path, out: Optional[Path]) -> int:
    out = out or lab / "selfcheck" / g.utc_compact()
    try:
        out = g.validate_run_dir(out, lab)
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    if out.exists():
        print(f"refused: {out} exists")
        return 2
    t0 = time.monotonic()
    lab.mkdir(parents=True, exist_ok=True)
    steps: Dict[str, Any] = {}
    steps["3_guard_selftest"] = g.guard_selftest(lab)                    # before this process arms its own guard (the parent cleans up)
    g.LabGuard.install(lab)
    lock = g.LabLock(lab, "selfcheck")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    fs = g.LabFS(lab)
    fs.mkdir(out)
    verdict = "PASS"
    try:
        import gc

        import frs_archive as fa
        import frs_machine as fm
        import frs_run as fr
        import frs_verify as fv
        from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process

        steps["1_lab_root"] = {"lab_root": str(lab), "lock": "held", "git": git_state(), "python": sys.executable}
        imp = lab / "import"
        frozen = json.loads((imp / "frozen_runtime.json").read_text(encoding="utf-8")) if (imp / "frozen_runtime.json").is_file() else None
        probs = import_problems(lab) + (fv.frozen_exe_problems(imp / "exe", frozen) if frozen else ["no frozen_runtime.json"])
        steps["2_import"] = {"ok": not probs, "problems": probs[:6]}
        ready = fm.readiness(lab)
        steps["4_readiness"] = ready
        pids = fm.battleship_pids()
        steps["5_no_battleship"] = {"ok": pids == [], "pids": pids}
        if not ready["ok"] or pids != []:
            verdict = "REFUSED"
        if probs or not steps["3_guard_selftest"]["ok"]:
            verdict = "FAIL"
        if verdict == "PASS":
            t = time.monotonic()
            lab_a, meta, a6 = fa.LabArchive.read_import(imp / "archive", e6=True)
            load_s = time.monotonic() - t
            mb = fm.main_private_mb()
            ref = fv.load_reference(imp / "reference", fv.real_analyse)
            rr = fa.record_reference_from_route(ref["meta"], "import/reference/metadata.json")
            lab_a.configure_lab(first_iteration=lab_a.next_iteration(), draw_id=fa.draw_id_for(lab_a.archive_id, "selfcheck"), record_reference=rr,
                                margin=fr.MARGIN)
            cen = fa.e6_census(lab_a, a6, draws=200)
            cells = len(lab_a.cells)
            steps["6_archive"] = {"ok": bool(cen["equal_probabilities"] and cen["same_draws"] == cen["draws"] and cen["lost_eligibility"] == 0),
                                  "load_s": round(load_s, 1), "main_private_mb_after_load": round(mb, 1) if mb else None,
                                  "bytes_per_cell_at_load": round(mb * 2 ** 20 / cells) if mb else None, "cells": cells, "bursts": len(lab_a.bursts),
                                  "bound_max_L": lab_a.lab_bound_L, "reference": [rr["completion_input_tick"], rr["completion_time_passed"]], "census": cen}
            pin = dict(meta["pin_tick0"])
            del lab_a, a6
            gc.collect()
            if not steps["6_archive"]["ok"]:
                verdict = "FAIL"
            install_kill_on_close_job()
            exe = imp / "exe" / "BattleShip.exe"
            r_explore = fv.make_real_replay(exe, out / "vw", fv.FLAGS_EXPLORE, frozen)
            tr, err = fv.replay_with_retry(r_explore, b"", "tick0", 0)
            steps["7_tick0_pin"] = dict(fv.tick0_check(tr, pin), errors=err)
            if not steps["7_tick0_pin"]["ok"]:
                verdict = "FAIL"
            r_verify = fv.make_real_replay(exe, out / "vw", fv.FLAGS_VERIFY, frozen)
            tr2, err2 = fv.replay_with_retry(r_verify, ref["words"], "reference", 0)
            row = fv.evaluate(tr2, ref["words"], fv.real_analyse)
            fv.save_trace(out / "traces" / "reference.json.gz", tr2)
            steps["8_reference"] = dict(fv.reference_check(row, ref), errors=err2, startup_s=row.get("startup_s"), stepping_s=row.get("stepping_s"))
            if not steps["8_reference"]["ok"]:
                verdict = "FAIL"
        left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
        steps["9_no_battleship_left"] = {"ok": left == [], "pids": left}
        if left:
            verdict = "FAIL" if verdict == "PASS" else verdict
    except Exception as exc:  # noqa: BLE001 - a crashed self-check is a FAIL with its reason
        import traceback

        steps["error"] = f"{type(exc).__name__}: {exc}"[:600]
        steps["trace"] = traceback.format_exc()[-2000:]
        verdict = "FAIL"
    finally:
        rec = {"mode": "lab", "utc": g.utc(), "verdict": verdict, "wall_s": round(time.monotonic() - t0, 1), "steps": steps}
        fs.write_json(out / "selfcheck.json", rec)
        lock.release()
    for k in sorted(steps):
        v = steps[k]
        short = {kk: vv for kk, vv in v.items() if kk not in ("census", "git", "trace", "child", "expected", "thresholds")} if isinstance(v, dict) else v
        out_line({k: short})
    if isinstance(steps.get("6_archive"), dict):
        cen = steps["6_archive"]["census"]
        out_line({"e6_census": {k: cen[k] for k in ("equal_probabilities", "same_draws", "draws", "eligible_on", "eligible_off", "made_eligible",
                                                    "bound_flags_e6_on")}})
        for lv, d in cen["per_level"].items():
            out_line({"level": lv, **d})
    print(f"SELF-CHECK {verdict} in {rec['wall_s']:.0f} s: {out / 'selfcheck.json'}")
    return {"PASS": 0, "REFUSED": 2}.get(verdict, 3)


# -- the night planner -----------------------------------------------------------------------------------------------------------------------


def night_layout(runs: int, wall_min: float, night: str) -> List[Dict[str, Any]]:
    if runs < 2 or runs % 2:
        raise SystemExit(f"refused: {runs} runs (an even number >= 2, so both arms get equal time)")
    out = []
    t = float(SELFCHECK_MIN)
    for i in range(runs):
        out.append({"run": i + 1, "arm": ABBA[i % 4], "label": f"{night}r{i // 2 + 1}", "wall_min": wall_min, "start_offset_min": round(t, 1)})
        t += wall_min + GAP_MIN
    return out


def cmd_plan(a: argparse.Namespace) -> int:
    lab = lab_root_arg(a.lab_root)
    import frs_archive as fa
    import frs_run as fr

    if not fa.LABEL_RE.match(a.night) or len(a.night) > 8:
        raise SystemExit("refused: the night label is 1-8 lower-case letters or digits")
    if a.wall_min is None and a.hours is None:
        raise SystemExit("refused: give --hours or --wall-min")
    wall = float(a.wall_min) if a.wall_min is not None else float(math.floor((60.0 * a.hours - SELFCHECK_MIN - GAP_MIN * a.runs) / a.runs))
    if wall * 60.0 - 60.0 * (a.open_reserve_min + a.close_reserve_min) <= 0:
        raise SystemExit("refused: the run wall leaves no exploration after the reserves")
    layout = night_layout(a.runs, wall, a.night)
    total = SELFCHECK_MIN + a.runs * (wall + GAP_MIN)
    if a.hours is not None and total > 60.0 * a.hours:
        raise SystemExit(f"refused: the layout needs {total:.0f} min > {60.0 * a.hours:.0f} min")
    nd = lab / "nights" / a.night
    if nd.exists():
        print(f"refused: {nd} exists (never overwritten)")
        return 2
    code = fr.code_manifest()
    digest = fr.code_digest(code)
    g.LabGuard.install(lab)
    fs = g.LabFS(lab)
    py = Path(sys.executable).as_posix()
    labp = lab.as_posix()
    repo = REPO.as_posix()
    log = (nd / "night_log.txt").as_posix()
    res = f"--open-reserve-min {a.open_reserve_min:g} --close-reserve-min {a.close_reserve_min:g}"
    lines = ["#!/usr/bin/env bash",
             f"# Lab night {a.night}: generated {g.utc()} by rl/frs_lab.py plan (mode lab; exploratory, unregistered).",
             "# Runs the self-check, then each run in ABBA order; stops the night at the first non-zero exit (MEMORY_BUDGET exits 0).",
             "set -u", f'cd "{repo}" || exit 1', f'PY="{py}"', f'LAB="{labp}"', f'LOG="{log}"',
             'stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }',
             'step() { echo "$(stamp) start: $*" >> "$LOG"; "$@"; rc=$?; echo "$(stamp) exit $rc: $*" >> "$LOG"; return $rc; }',
             'echo "$(stamp) night ' + a.night + ' begins" >> "$LOG"',
             'step "$PY" -B rl/frs_lab.py selfcheck --lab-root "$LAB" || { echo "$(stamp) NIGHT STOPPED: self-check did not pass" >> "$LOG"; exit 1; }']
    for r in layout:
        lines.append(f'step "$PY" -B rl/frs_lab.py run --lab-root "$LAB" --arm {r["arm"]} --wall-min {wall:g} --label {r["label"]} {res} '
                     f'--expect-code {digest} || {{ echo "$(stamp) NIGHT STOPPED after run {r["run"]} ({r["arm"]} {r["label"]})" >> "$LOG"; exit 1; }}')
    lines.append('echo "$(stamp) NIGHT COMPLETE" >> "$LOG"')
    fs.mkdir(nd)
    fs.write_text(nd / "night.sh", "\n".join(lines) + "\n")
    plan = {"mode": "lab", "utc": g.utc(), "night": a.night, "runs": layout, "wall_min": wall, "open_reserve_min": a.open_reserve_min,
            "close_reserve_min": a.close_reserve_min, "explore_min": wall - a.open_reserve_min - a.close_reserve_min, "selfcheck_min": SELFCHECK_MIN,
            "gap_min": GAP_MIN, "total_min": total, "code_digest": digest, "code_files": len(code), "python": sys.executable, "lab_root": str(lab)}
    fs.write_json(nd / "plan.json", plan)
    print(f"night {a.night}: {a.runs} runs x {wall:g} min (explore {plan['explore_min']:g} min), ABBA, total {total:.0f} min "
          f"({int(total // 60)} h {int(total % 60):02d} min); code {digest[:16]}")
    for r in layout:
        print(f"  {r['run']}  {r['arm']:<8} {r['label']:<6} wall {wall:g} min  starts at +{int(r['start_offset_min'] // 60)}:{int(r['start_offset_min'] % 60):02d}")
    print(f"start it from Git Bash with:  bash \"{(nd / 'night.sh').as_posix()}\"")
    return 0


# -- smoke ---------------------------------------------------------------------------------------------------------------------------------------


def cmd_smoke(a: argparse.Namespace) -> int:
    lab = lab_root_arg(a.lab_root)
    date = a.date or dt.date.today().isoformat()
    out = lab / f"smoke_{date}"
    if out.exists():
        print(f"refused: {out} exists")
        return 2
    t0 = time.monotonic()
    me = str(Path(__file__).resolve())
    r1 = subprocess.run([sys.executable, "-B", me, "selfcheck", "--lab-root", str(lab), "--out", str(out / "selfcheck")], cwd=str(REPO))
    if r1.returncode != 0:
        print(f"smoke stopped: the self-check exited {r1.returncode}")
        return r1.returncode
    left = SMOKE_TOTAL_S - (time.monotonic() - t0) - 30.0
    if left < 330.0:
        print(f"smoke stopped: only {left:.0f} s left of the 10 minutes for the run")
        return 2
    wall_min = math.floor(left / 6.0) / 10.0
    r2 = subprocess.run([sys.executable, "-B", me, "run", "--lab-root", str(lab), "--arm", "CONT", "--label", "smoke", "--wall-min", f"{wall_min:g}",
                         "--run-dir", str(out / "run"), "--open-reserve-min", "2", "--close-reserve-min", "2"], cwd=str(REPO))
    print(f"smoke: self-check 0, run exit {r2.returncode}, total {time.monotonic() - t0:.0f} s (cap {SMOKE_TOTAL_S:.0f} s)")
    return r2.returncode


def cmd_report(run_dir: Path) -> int:
    p = Path(run_dir) / "report.md"
    if not p.is_file():
        print(f"no report at {p}")
        return 1
    print(p.read_text(encoding="utf-8"))
    return 0


# -- main ----------------------------------------------------------------------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    if not sys.flags.dont_write_bytecode:
        raise SystemExit("run with python -B")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("import", "selfcheck", "run", "plan", "smoke"):
        p = sub.add_parser(name)
        p.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
        if name == "selfcheck":
            p.add_argument("--out", default=None)
        if name == "run":
            p.add_argument("--arm", required=True)
            p.add_argument("--wall-min", type=float, required=True)
            p.add_argument("--label", required=True)
            p.add_argument("--run-dir", default=None)
            p.add_argument("--expect-code", default=None)
            p.add_argument("--workers", type=int, default=5)
        if name in ("run", "plan"):
            p.add_argument("--open-reserve-min", type=float, default=4.0)
            p.add_argument("--close-reserve-min", type=float, default=6.0)
        if name == "plan":
            p.add_argument("--night", required=True)
            p.add_argument("--runs", type=int, default=6)
            p.add_argument("--hours", type=float, default=None)
            p.add_argument("--wall-min", type=float, default=None)
        if name == "smoke":
            p.add_argument("--date", default=None)
    r = sub.add_parser("report")
    r.add_argument("--run-dir", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "report":
        return cmd_report(Path(a.run_dir))
    if a.cmd == "import":
        return cmd_import(lab_root_arg(a.lab_root))
    if a.cmd == "selfcheck":
        return cmd_selfcheck(lab_root_arg(a.lab_root), Path(a.out) if a.out else None)
    if a.cmd == "run":
        if not 1 <= a.workers <= 5:
            raise SystemExit("refused: 1 to 5 workers (one standby each: at most 10 BattleShip processes)")
        return cmd_run(a)
    if a.cmd == "plan":
        return cmd_plan(a)
    return cmd_smoke(a)


if __name__ == "__main__":
    sys.exit(main())
