#!/usr/bin/env python3
"""M8-rd1 session driver (route discovery by archive exploration).

    python rl/m8_rd_session.py status
    python rl/m8_rd_session.py preflight [--skip-unit]   # no game: tests, pins, D: coverage, readiness, approval
    python rl/m8_rd_session.py approval-template         # prints the record a reviewer would write (never writes it)
    python rl/m8_rd_session.py run                       # refused unless the preflight passes, including the approval
    python rl/m8_rd_session.py verify-run                # read-only post-run verification
    python rl/m8_rd_session.py reverify [--execute]      # rebuilt-executable path (section 7.2); not used by M8-rd1

Design: docs/rl_m8_rd_proposal_2026-10-01.md (revision 2) as amended by docs/rl_m8_rd_amendment_2026-10-02.md; preparation
record docs/rl_m8_rd_implementation.md. SCOPE: return-based archive exploration (arm T) against a matched no-return control
(arm C) from the normal tick-0 reset, one session, one set of draws; never a policy result. Light top-level imports only
(spawned workers re-import this script).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_rule as mrule  # noqa: E402
import m8_rd_run as mrun  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL = REPO_ROOT / "rl"
RUNS = REPO_ROOT / "runs"
LOGS = REPO_ROOT / "logs"
M8_ROOT = RUNS / "m8_rd"
APPROVAL = REPO_ROOT / "docs" / "rl_m8_rd1_approval.json"
EXE_DIR = REPO_ROOT / "build-us" / "Release"
EXECUTABLE = EXE_DIR / "BattleShip.exe"
BACKUP_ROOT = Path(r"D:\BattleShip_runs_backup")
BACKUP_BASE = BACKUP_ROOT / "2026-09-28"
SNAPSHOT_ROOT = Path(r"D:\BattleShip_source_snapshots")
SESSION = "rd1"
GATE = "m8_rd1"
ARCHIVE_ID = "m8_rd_a1"
SCOPE = ("M8-rd1: return-based archive exploration (arm T) against a matched no-return control (arm C) from the normal "
         "tick-0 reset; one session, one set of keyed draws; not a policy result, not a learning result")
FLAGS_EXPLORE = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1"}
FLAGS_VERIFY = dict(FLAGS_EXPLORE, SSB64_RL_ENTITY="1", SSB64_RL_TARGET_DIAG="1", SSB64_RL_INPUT="1")
N_WORKERS = 5
RUNTIME_FILES = ("BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")
EXE_COPY_FILES = ("BattleShip.exe", "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt", "config.yml")
EXE_COPY_DIRS = (".tcc", "assets")
CONTROLLER_CVAR_NAMES = ("tapjumpdisabled", "autozcancel", "failedzcancelflash")
MEMORY_SAMPLE_S = 5.0
READINESS = {"min_available_mb": 4096, "min_commit_free_mb": 10240, "min_free_gib_c": 5.0, "min_free_gib_d": 5.0}

# the two shortest pinned Track 1 artifacts (3,361 + 2,560 words), replayed word for word in P1
P1_TRACES: Tuple[Dict[str, Any], ...] = (
    {"name": "m7d_s0v1_det_fall", "words": 3361,
     "artifact": "runs/m7d/_eval/m7d_s0_v1/final/deterministic/workers/w00/artifacts/episode_20260922T181810Z_41b8dbcd",
     "trace": "runs/m7q/_equiv/input_all/fx_m7d_s0v1_det_fall.json.gz"},
    {"name": "m7d_s0v1_fall6_double", "words": 2560,
     "artifact": "runs/m7d/_eval/m7d_s0_v1/final/stochastic/workers/w03/artifacts/episode_20260922T182432Z_e5c67c95",
     "trace": "runs/m7q/_equiv/input_all/fx_m7d_s0v1_fall6_double.json.gz"},
)

CODE_FILES = ("m8_rd_cells.py", "m8_rd_explore.py", "m8_rd_archive.py", "m8_rd_claims.py", "m8_rd_rule.py", "m8_rd_worker.py",
              "m8_rd_run.py", "m8_rd_finish.py", "m8_rd_session.py", "m8_rd_report.py", "m8_rd_snapshot.py", "m8_rd_stub.py", "m8_rd_fakegame.py",
              "m8_rd_tests.py",
              "battleship_client.py", "battleship_process.py", "m7_standby.py", "m7_runtime.py", "m7f_trace.py",
              "m7n_crossing.py", "m7g_fixture.py", "btt_reward_v3.py", "btt_rewards.py", "m7q_status_table.py",
              "m7n_status_table.py", "m7g_spatial.py", "m7h_curriculum.py", "m7u_gate.py", "m7u2_gate.py", "m7s_gate.py",
              "m7u3_gate.py", "tools/runs_backup.py", "data/m7n_action_classes_v2.json")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    return mw.sha256_file(Path(p))


def _norm(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str)


def caps() -> Dict[str, Any]:
    cfg = mrun.RunConfig(root=M8_ROOT)
    return {"arm_tick_cap": cfg.arm_tick_cap, "min_arm_ticks": cfg.min_arm_ticks, "p1_tick_cap": cfg.p1_tick_cap,
            "replay_tick_cap": cfg.replay_tick_cap, "wall_caps_s": dict(cfg.wall_caps_s), "global_cap_s": cfg.global_cap_s,
            "checkpoint_every_s": cfg.checkpoint_every_s, "memory_caps_mb": dict(cfg.memory_caps_mb),
            "memory_sample_s": MEMORY_SAMPLE_S, "max_battleship_processes": cfg.max_battleship_processes,
            "lifecycle_failure_limit": cfg.lifecycle_failure_limit, "verify_threads": cfg.verify_threads,
            "identity_k": cfg.identity_k, "job_timeout_s": mrun.JOB_TIMEOUT_S, "wall_cap_grace_s": mrun.WALL_CAP_GRACE_S}


# -- the pinned P1 traces ----------------------------------------------------------------------------------------------------


def _word_index() -> Dict[Tuple[int, int, int], int]:
    return {t: i for i, t in enumerate(mcell.TRIPLES)}


def read_pinned_words(artifact: Path) -> Tuple[bytes, List[int]]:
    """Track 1 words of a recorded artifact (canonical native triples from actions.jsonl) and its consumed ticks."""
    idx = _word_index()
    words, ticks = bytearray(), []
    for line in (Path(artifact) / "actions.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        words.append(idx[(int(r["buttons"]), int(r["stick_x"]), int(r["stick_y"]))])
        ticks.append(int(r["consumed_tick"]))
    return bytes(words), ticks


def p1_pins() -> Dict[str, Any]:
    import gzip

    out: Dict[str, Any] = {}
    for t in P1_TRACES:
        art, trc = REPO_ROOT / t["artifact"], REPO_ROOT / t["trace"]
        words, ticks = read_pinned_words(art)
        meta = json.loads((art / "metadata.json").read_text(encoding="utf-8"))
        tr = json.load(gzip.open(trc, "rt", encoding="utf-8"))
        out[t["name"]] = {"words": len(words), "artifact_actions_sha256": sha256_file(art / "actions.jsonl"),
                          "artifact_metadata_sha256": sha256_file(art / "metadata.json"), "trace_sha256": sha256_file(trc),
                          "native_action_digest": mcell.words_digest(words),
                          "recorded_digest": (meta.get("labels") or {}).get("native_action_digest"),
                          "trace_action_digest": tr.get("action_digest"), "consumed_ticks_ok": ticks == list(range(len(ticks))),
                          "trace_submitted": tr.get("submitted"), "trace_flags": tr.get("extra_env")}
    return out


def p1_inputs() -> List[Dict[str, Any]]:
    import gzip

    out = []
    for t in P1_TRACES:
        words, _ticks = read_pinned_words(REPO_ROOT / t["artifact"])
        tr = json.load(gzip.open(REPO_ROOT / t["trace"], "rt", encoding="utf-8"))
        steps = tr["steps"]
        if len(steps) != len(words):
            raise RuntimeError(f"{t['name']}: {len(steps)} pinned replies for {len(words)} words")
        out.append({"name": t["name"], "words": words,
                    "expected_digests": [mcell.record_digest(mcell.record_of(s)) for s in steps],
                    "expected_host_frames": [s["observation"]["host_frame"] for s in steps],
                    "native_action_digest": mcell.words_digest(words)})
    return out


# -- runtime pins -----------------------------------------------------------------------------------------------------------------


def controller_cvar_problems(cfg_path: Path) -> List[str]:
    """CVars that change controller rules must be absent or zero (the mechanics audit): the tap-jump switches and the
    auto-Z-cancel switches. Reads the JSON structurally; any leaf whose dotted path contains one of the names and whose value
    is truthy."""
    data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    bad: List[str] = []

    def walk(o: Any, path: str) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                p = f"{path}.{k}" if path else str(k)
                if any(n in p.lower() for n in CONTROLLER_CVAR_NAMES) and not isinstance(v, (dict, list)):
                    if v not in (0, 0.0, False, "0", "", None):
                        bad.append(f"{p} = {v!r}")
                walk(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk(data, "")
    return bad


def runtime_pins() -> Dict[str, Any]:
    return {n: sha256_file(EXE_DIR / n) for n in RUNTIME_FILES}


# -- identity, approval ----------------------------------------------------------------------------------------------------------------


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO_ROOT)
    return r.stdout


def d_records_digest(root: Path = BACKUP_ROOT, folders: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    out: Dict[str, str] = {}
    if Path(root).is_dir():
        for d in sorted(p for p in Path(root).iterdir() if p.is_dir()):
            if folders is not None and d.name not in folders:
                continue
            h = hashlib.sha256()
            for f in sorted(p for p in d.iterdir() if p.is_file()):
                h.update(f.name.encode("utf-8"))
                h.update(sha256_file(f).encode("ascii"))
            out[d.name] = h.hexdigest()
    return {"folders": sorted(out), "digest": hashlib.sha256(json.dumps(out, sort_keys=True).encode("utf-8")).hexdigest(),
            "per_folder": out}


def contract_digests() -> Dict[str, str]:
    import m7q_status_table as st

    return {"m8_rd_cell_v1": mcell.contract_digest(), "m8_rd_select_v1": march.select_contract_digest(),
            "m8_rd_explore_v1": mx.contract_digest(), "m8_rd_claims_v1": mclaims.contract_digest(),
            "track1_btt_s9_b8_v1": mcell.track1_digest(), "btt_action_class_table_v2": st.load_table()["sha256"]}


def identity() -> Dict[str, Any]:
    dr = d_records_digest()
    return {"gate": GATE, "scope": SCOPE, "milestone": "M8", "archive_id": ARCHIVE_ID, "session": SESSION,
            "rule": mrule.RULE_ID, "rule_sha256": mrule.rule_digest(), "contracts": contract_digests(),
            "key_strings": {"cell": "m8_rd_cell_v1", "select": "m8_rd|<archive_id>|select|<iteration>",
                            "explore": "m8_rd|<archive_id>|explore|<iteration>|<decision index>",
                            "control": "m8_rd1|control|<episode>|<decision index>"},
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None,
            "runtime_files": runtime_pins(), "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY},
            "p1": p1_pins(), "caps": caps(), "workers": N_WORKERS, "burst_words": mx.BURST_WORDS,
            "horizon": mcell.HORIZON, "readiness": READINESS,
            "amendment": {"record": "docs/rl_m8_rd_amendment_2026-10-02.md", "arm_cap_ticks": mclaims.ARM_TICK_CAP,
                          "min_arm_ticks": mclaims.MIN_ARM_TICKS, "treatment_wall_cap_s": 1560, "session_hard_cap_s": 3600},
            "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "proposal_sha256": sha256_file(REPO_ROOT / "docs" / "rl_m8_rd_proposal_2026-10-01.md"),
            "git_head": git("rev-parse", "HEAD").strip(),
            "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


IDENTITY_SKIP = ("code", "d_records", "git_head")


def approval_status(path: Path = APPROVAL, want: Optional[Mapping[str, Any]] = None) -> Tuple[bool, str]:
    path = Path(path)
    if not path.is_file():
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path
        return False, f"no approval record at {shown} (the session is not authorised)"
    rec = json.loads(path.read_text(encoding="utf-8"))
    if not str(rec.get("approval", "")).startswith("APPROVED"):
        return False, f"approval record says {rec.get('approval')!r}"
    want = dict(want) if want is not None else identity()
    diffs = [k for k in want if k not in IDENTITY_SKIP and _norm(rec.get(k)) != _norm(want[k])]
    diffs += [f"code:{f}" for f, h in want["code"].items() if (rec.get("code") or {}).get(f) != h]
    if rec.get("git_head") != want["git_head"]:
        diffs.append("git_head")
    pinned = rec.get("d_records") or {}
    if pinned.get("folders"):
        if d_records_digest(folders=pinned["folders"])["digest"] != pinned.get("digest"):
            diffs.append("d_records")
    else:
        diffs.append("d_records")
    if diffs:
        return False, f"approval record does not match the current identity: {diffs[:8]}"
    return True, "approved"


# -- readiness, preflight ---------------------------------------------------------------------------------------------------------


def memory_status() -> Optional[Dict[str, float]]:
    import m7u2_gate as gg

    return gg.memory_status()


def readiness(memory: Callable[[], Optional[Mapping[str, float]]] = memory_status,
              disk: Optional[Callable[[Path], float]] = None) -> Dict[str, Any]:
    disk = disk or (lambda p: shutil.disk_usage(p).free / 2 ** 30)
    problems: List[str] = []
    mem = memory()
    if mem is None:
        problems.append("memory status unavailable")
    else:
        if mem["available_mb"] < READINESS["min_available_mb"]:
            problems.append(f"available memory {mem['available_mb']:.0f} MB < {READINESS['min_available_mb']} MB")
        if mem["commit_free_mb"] < READINESS["min_commit_free_mb"]:
            problems.append(f"free commit {mem['commit_free_mb']:.0f} MB < {READINESS['min_commit_free_mb']} MB")
    free = {}
    for name, p, key in (("C", REPO_ROOT, "min_free_gib_c"), ("D", BACKUP_ROOT.anchor or BACKUP_ROOT, "min_free_gib_d")):
        try:
            free[name] = round(disk(Path(p)), 1)
        except OSError as exc:
            problems.append(f"free disk of {name}: unreadable ({exc})")
            continue
        if free[name] < READINESS[key]:
            problems.append(f"free disk on {name}: {free[name]} GiB < {READINESS[key]} GiB")
    return {"ok": not problems, "problems": problems, "memory": mem, "free_gib": free, "thresholds": dict(READINESS)}


def combined_coverage() -> Dict[str, Any]:
    import m7u_gate as g1

    return g1.combined_coverage()


def game_processes() -> List[int]:
    from m7_runtime import BATTLESHIP_IMAGE, list_processes_named

    return list(list_processes_named(BATTLESHIP_IMAGE) or [])


def tracked_changes() -> List[str]:
    """Tracked files that differ from HEAD (the proposal and every earlier M7 file are tracked: any entry here is a change)."""
    return [ln for ln in git("diff", "--name-only", "HEAD").split() if ln]


def untracked_not_new() -> List[str]:
    """`git status` entries other than untracked (`??`) files: staged, modified, deleted, renamed."""
    return [ln for ln in git("status", "--porcelain").splitlines() if ln.strip() and not ln.startswith("??")]


def snapshot_status(approval: Optional[Mapping[str, Any]], repo_root: Optional[Path] = None) -> Tuple[bool, str]:
    """When an approval exists it names the source snapshot; it must exist with a PASS record whose hash is the pinned one."""
    if approval is None:
        return True, "no approval yet"
    s = approval.get("source_snapshot") or {}
    dest = Path(str(s.get("dest", "")))
    sj = dest / "snapshot.json"
    if not sj.is_file():
        return False, f"source snapshot {dest} has no snapshot.json"
    if sha256_file(sj) != s.get("snapshot_json_sha256"):
        return False, "snapshot.json differs from the hash in the approval"
    rec = json.loads(sj.read_text(encoding="utf-8"))
    if rec.get("result") != "PASS":
        return False, "the source snapshot's record is not PASS"
    repo = Path(repo_root) if repo_root is not None else REPO_ROOT
    bad = [f["path"] for f in rec.get("files", []) if (repo / f["path"]).is_file()
           and sha256_file(repo / f["path"]) != f["sha256_source"]]
    if bad:
        return False, f"files changed since the source snapshot: {bad[:5]}"
    return True, "snapshot recorded, PASS and equal to the repository"


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": SCOPE}
    if M8_ROOT.exists():
        problems.append(f"{M8_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        for cmd, key in (([sys.executable, "-B", str(RL / "m8_rd_tests.py"), "unit"], "unit_suite"),
                         ([sys.executable, "-B", str(RL / "m8_rd_rule.py"), "self-test"], "rule_self_test")):
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
            rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
            if r.returncode != 0:
                problems.append(f"{key} failed")
    if not EXECUTABLE.is_file():
        problems.append(f"missing executable {EXECUTABLE}")
    ident = identity()
    rep["executable_sha256"] = ident["executable_sha256"]
    rep["git_head"] = ident["git_head"]
    changed = tracked_changes()
    if changed:
        problems.append(f"tracked files differ from HEAD: {changed[:6]}")
    odd = untracked_not_new()
    if odd:
        problems.append(f"git status shows entries other than new files: {odd[:6]}")
    rep["git_status_new_files"] = sum(1 for ln in git("status", "--porcelain").splitlines() if ln.startswith("??"))
    for n, p in ident["p1"].items():
        if not (p["native_action_digest"] == p["recorded_digest"] == p["trace_action_digest"] and p["consumed_ticks_ok"]
                and p["trace_submitted"] == p["words"] and p["trace_flags"] and
                p["trace_flags"].get("SSB64_RL_SPATIAL") == "1"):
            problems.append(f"pinned P1 trace {n} is not consistent: {p}")
    rep["p1"] = {n: {k: p[k] for k in ("words", "native_action_digest")} for n, p in ident["p1"].items()}
    cvars = controller_cvar_problems(EXE_DIR / "BattleShip.cfg.json")
    rep["controller_cvars"] = cvars or "absent or zero"
    if cvars:
        problems.append(f"controller-rule CVars set in BattleShip.cfg.json: {cvars}")
    try:
        import m7q_status_table as st

        st.load_table()
        rep["status_table"] = "digest verified"
    except Exception as exc:  # noqa: BLE001
        problems.append(f"status table: {type(exc).__name__}: {exc}")
    cov = combined_coverage()
    rep["backup"] = {k: cov.get(k) for k in ("ok", "reason", "source_files", "uncovered", "increments", "skipped")}
    if not cov.get("ok"):
        problems.append(f"backup prerequisite not met: {cov.get('reason')}")
    procs = game_processes()
    if procs:
        problems.append(f"BattleShip already running: {procs}")
    rd = readiness()
    rep["readiness"] = rd
    problems += [f"readiness: {p}" for p in rd["problems"]]
    ok, why = approval_status()
    rep["approval"] = why
    approval = json.loads(APPROVAL.read_text(encoding="utf-8")) if APPROVAL.is_file() else None
    sok, swhy = snapshot_status(approval)
    rep["source_snapshot"] = swhy
    if not sok:
        problems.append(f"source snapshot: {swhy}")
    if not ok:
        problems.append(why)
    rep["problems"] = problems
    rep["ok"] = not problems
    return rep


# -- S0: the frozen runtime and the preserved executable ------------------------------------------------------------------------


def preserve_runtime(archive_dir: Path, exe_dir: Path = EXE_DIR) -> Dict[str, Any]:
    """S0: copy the live BattleShip.cfg.json and imgui.ini once into <archive>/runtime/ (the frozen copies every worker
    installs), and keep a runnable copy of the pinned executable beside them. After this no M8 tool reads the user's live
    configuration for an archive run again. The CVars that change controller rules must be absent or zero."""
    rt = Path(archive_dir) / "runtime"
    if rt.exists():
        raise RuntimeError(f"{rt} exists (never overwritten)")
    rt.mkdir(parents=True)
    bad = controller_cvar_problems(Path(exe_dir) / "BattleShip.cfg.json")
    if bad:
        raise RuntimeError(f"controller-rule CVars set: {bad}")
    frozen: Dict[str, str] = {}
    for n in mw.FROZEN_FILES:
        src = Path(exe_dir) / n
        if not src.is_file():
            raise RuntimeError(f"{src} missing: nothing to freeze")
        dst = rt / n
        shutil.copyfile(src, dst)
        h, hs = sha256_file(dst), sha256_file(src)
        if h != hs:
            raise RuntimeError(f"{n}: the frozen copy differs from the source")
        frozen[n] = h
    exe_copy = rt / "exe"
    exe_copy.mkdir()
    copied: Dict[str, str] = {}
    for n in EXE_COPY_FILES:
        shutil.copyfile(Path(exe_dir) / n, exe_copy / n)
        copied[n] = sha256_file(exe_copy / n)
        if copied[n] != sha256_file(Path(exe_dir) / n):
            raise RuntimeError(f"{n}: the preserved copy differs from the source")
    for d in EXE_COPY_DIRS:
        if (Path(exe_dir) / d).is_dir():
            shutil.copytree(Path(exe_dir) / d, exe_copy / d)
    rec = {"frozen_sha256": frozen, "exe_copy_sha256": copied, "runtime_files": {n: sha256_file(Path(exe_dir) / n) for n in RUNTIME_FILES},
           "created_utc": utc(), "controller_cvars": "absent or zero"}
    mrun.write_json(rt / "frozen_runtime.json", rec)
    return rec


# -- the real environment ---------------------------------------------------------------------------------------------------------


def build_real_env(cfg: mrun.RunConfig, frozen: Mapping[str, str], pins: Mapping[str, Any], sampler: Any = None, *,
                   executable: Optional[Path] = None, flags_explore: Optional[Mapping[str, str]] = None,
                   flags_verify: Optional[Mapping[str, str]] = None) -> mrun.RunEnv:
    """The real environment. The executable and the flag sets are parameters for the tests that drive the real lifecycle code
    against a fake game; the session always uses the module defaults."""
    import m7_runtime

    exe = Path(executable) if executable is not None else EXECUTABLE
    fx = dict(flags_explore if flags_explore is not None else FLAGS_EXPLORE)
    fv = dict(flags_verify if flags_verify is not None else FLAGS_VERIFY)

    frozen_rt = mw.FrozenRuntime(cfg.archive_dir / "runtime", frozen)
    orig_prepare = m7_runtime.prepare_worker_runtime

    def frozen_prepare(runtime_dir, executable):
        manifest = orig_prepare(runtime_dir, executable)
        frozen_rt.install(Path(runtime_dir))          # the verification replays use the frozen configuration too
        manifest["frozen_config"] = True
        return manifest

    m7_runtime.prepare_worker_runtime = frozen_prepare

    def worker_spec(rank: int, c: mrun.RunConfig) -> Dict[str, Any]:
        return {"rank": rank, "root": str(c.session_dir / "workers" / f"w{rank:02d}"), "executable": str(exe),
                "flags": dict(fx), "frozen_dir": str(c.archive_dir / "runtime"), "frozen_sha256": dict(frozen),
                "exe_sha256": pins.get("executable_sha256"), "runtime_sha256": dict(pins.get("runtime_files") or {}),
                "port_base": 30000, "port_size": 250, "failure_dir": str(c.session_dir / "failures")}

    def replay(cand: Mapping[str, Any], counted: int, label: str, slot: int) -> Dict[str, Any]:
        import m7f_trace as tr

        words = bytes(cand["words"][:counted])
        actions = [(*mcell.TRIPLES[w], i) for i, w in enumerate(words)]
        work = cfg.session_dir / "vw" / f"s{slot}_{label}"
        trace = tr.run_stepping_trace(label, exe, actions, work, extra_env=dict(fv), index=9000 + int(cand["cid"]),
                                      rank=8 + int(slot))
        mw.remove_tree_retry(work / "runtime", runtime=True)
        mw.remove_tree_retry(work / "episodes")
        return trace

    def analyse(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        import m7n_crossing as xc

        return xc.analyse_trace(initial, steps)

    tree_snapshot = None
    private_mb = None
    try:
        import m7u_gate as g1

        private_mb = g1.private_mb
    except Exception:  # noqa: BLE001
        pass
    if sampler is not None:
        tree_snapshot = lambda: getattr(sampler, "last", None)      # noqa: E731 - the sampler thread's latest tree sample
    return mrun.RunEnv(worker_spec=worker_spec, replay=replay, analyse=analyse, p1_inputs=p1_inputs, pins=dict(pins),
                       tree_snapshot=tree_snapshot, private_mb=private_mb, sampler=sampler)


def make_sampler(path: Path, caps_mb: Mapping[str, float]) -> Any:
    """The M7u3 whole-process-tree sampler (reused unchanged; imported lazily because that module imports torch), with the
    latest sample kept for the engine's process-count check."""
    import m7u3_gate as g3

    class Sampler(g3.TreeSampler):
        last: Optional[Dict[str, Any]] = None

        def sample(self):
            snap = super().sample()
            if snap is not None:
                self.last = dict(snap, seq=self.samples)       # the sample's sequence number: the engine needs DISTINCT samples
            return snap

    return Sampler(path, interval=MEMORY_SAMPLE_S, caps=caps_mb)


# -- commands --------------------------------------------------------------------------------------------------------------------------


def cmd_run(overrides: Optional[Mapping[str, Any]] = None) -> int:
    """`overrides` (RunConfig fields) exists for the tests of this command only; the session passes none."""
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process

    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(pf, indent=1, default=str))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    install_kill_on_close_job()
    mw.ProvenanceGuard.install()
    cfg = mrun.RunConfig(root=M8_ROOT, session_id=SESSION, archive_id=ARCHIVE_ID, n_workers=N_WORKERS, **dict(overrides or {}))
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    M8_ROOT.mkdir(parents=True)
    cfg.session_dir.mkdir(parents=True)
    frozen_rec = preserve_runtime(cfg.archive_dir, EXE_DIR)
    pins = {"executable_sha256": approval["executable_sha256"], "runtime_files": frozen_rec["runtime_files"],
            "frozen_sha256": frozen_rec["frozen_sha256"], "contracts": approval["contracts"], "flags": approval["flags"],
            "archive_id": ARCHIVE_ID, "approval_sha256": sha256_file(APPROVAL), "git_head": approval["git_head"],
            "rule_sha256": approval["rule_sha256"], "p1": approval["p1"]}
    shutil.copyfile(APPROVAL, cfg.session_dir / "approval_copy.json")
    mrun.write_json(cfg.session_dir / "open.json", {"utc": utc(), "pins": pins, "preflight": {k: pf.get(k) for k in (
        "executable_sha256", "git_head", "readiness", "backup", "approval", "source_snapshot", "unit_suite")},
        "caps": caps(), "identity": {k: v for k, v in identity().items() if k != "code"}})
    sampler = make_sampler(cfg.session_dir / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    env = build_real_env(cfg, frozen_rec["frozen_sha256"], pins, sampler)
    import m8_rd_finish as fin

    try:
        sess = mrun.Session(cfg, env)
        out = fin.run_all(sess)
    finally:
        rep = sampler.stop()
        mrun.write_json(cfg.session_dir / "memory_summary.json", rep)
    left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
    mrun.write_json(cfg.session_dir / "leftover_processes.json", {"battleship_pids_after_the_run": left, "utc": utc()})
    print(json.dumps(out["rule"], indent=1, default=str)[:4000])
    if left:
        print(f"WARNING: BattleShip processes still alive after the run: {left}")
    return 0


def cmd_verify_run() -> int:
    import m8_rd_report as rpt

    rep = rpt.verify_run(M8_ROOT, SESSION)
    print(json.dumps(rep, indent=1, default=str))
    return 0 if rep["ok"] else 1


def cmd_reverify(execute: bool) -> int:
    import m8_rd_report as rpt

    rep = rpt.reverify_projection(M8_ROOT)
    print(json.dumps(rep, indent=1, default=str))
    if execute:
        print("refused: the rebuilt-executable re-verification is its own separately authorised session")
        return 2
    return 0


def cmd_status() -> int:
    st = M8_ROOT / "sessions" / SESSION / "state.json"
    out = {"m8_root_exists": M8_ROOT.exists(), "approval_present": APPROVAL.is_file(),
           "state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None}
    print(json.dumps(out, indent=1, default=str))
    return 0


def cmd_template() -> int:
    ident = identity()
    rec = dict(ident, approval="PENDING (a reviewer replaces this with APPROVED ... and fills the authorisation and the source "
                               "snapshot entries; this command never writes the record)",
               revision=1, authorisation={"source": "<the user's message>", "text": ["<what is authorised, once>"]},
               source_snapshot={"dest": "D:\\BattleShip_source_snapshots\\<date>_m8_rd1", "snapshot_json_sha256": "<sha256>",
                                "result": "PASS", "files": "<n>", "git_head": ident["git_head"],
                                "independent_verification": "<tool verify and an independent PowerShell re-hash>"},
               backup_coverage_before_approval="<combined coverage record>")
    print(json.dumps(rec, indent=1, default=str))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("verify-run")
    sub.add_parser("approval-template")
    sub.add_parser("run")
    p = sub.add_parser("preflight")
    p.add_argument("--skip-unit", action="store_true")
    r = sub.add_parser("reverify")
    r.add_argument("--execute", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "preflight":
        rep = preflight(run_unit=not a.skip_unit)
        print(json.dumps(rep, indent=1, default=str))
        return 0 if rep["ok"] else 1
    if a.cmd == "approval-template":
        return cmd_template()
    if a.cmd == "verify-run":
        return cmd_verify_run()
    if a.cmd == "reverify":
        return cmd_reverify(a.execute)
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
