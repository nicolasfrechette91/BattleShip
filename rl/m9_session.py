#!/usr/bin/env python3
"""M9-g1 session driver: one bounded gate of the backward-algorithm robustification of the agent's own two verified rd4 clears.

    python rl/m9_session.py status
    python rl/m9_session.py preflight [--skip-unit]    # no game: tests, pins, the four M8 trees, D: coverage, readiness, approval
    python rl/m9_session.py approval-template          # prints the record a reviewer would write (never writes it)
    python rl/m9_session.py run                        # refused unless the preflight passes, including the approval
    python rl/m9_session.py verify-run                 # read-only post-run verification of the recorded gate
    python rl/m9_session.py report                     # the reported readings of the recorded gate

Design: docs/rl_m9_policy_proposal_2026-10-03.md as decided in docs/rl_m9_g1_decisions_2026-10-04.md; implementation record
docs/rl_m9_g1_implementation.md. SCOPE: see rl/m9_contract.SCOPE. The four M8 trees (runs/m8_rd, runs/m8_rd_rd2, runs/m8_rd_rd3, runs/m8_rd_rd4)
are only read and must stay byte-identical to their D: increments; the gate writes only runs/m9_g1/. Light top-level imports only (spawned workers
re-import this script).
"""
from __future__ import annotations

import argparse
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

import m8_rd_resume as rs  # noqa: E402
import m8_rd_session as ses1  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m8_rd3_resume as r3  # noqa: E402
import m8_rd4_resume as r4  # noqa: E402
import m9_artifacts as A  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_rule as R  # noqa: E402

REPO_ROOT = ses1.REPO_ROOT
RL = ses1.RL
RUNS = ses1.RUNS
LOGS = ses1.LOGS
RUN_ROOT = RUNS / "m9_g1"
APPROVAL = REPO_ROOT / "docs" / "rl_m9_g1_approval.json"
EXE_DIR = ses1.EXE_DIR
EXECUTABLE = ses1.EXECUTABLE
BACKUP_ROOT = ses1.BACKUP_ROOT
SNAPSHOT_ROOT = ses1.SNAPSHOT_ROOT
RD1_ROOT, RD2_ROOT, RD3_ROOT, RD4_ROOT = RUNS / "m8_rd", RUNS / "m8_rd_rd2", RUNS / "m8_rd_rd3", RUNS / "m8_rd_rd4"
RD4_INCREMENT_NAME = "2026-10-03_incr_m8_rd4"
RD4_FACTS = {"files": 93, "bytes": 165_147_441, "increment_manifest_sha256": "7ff2b29dfad2bcaa26e2567786acc3c84c55a6414501545b0f1c1815480068a8"}
M8_TREES: Tuple[Tuple[str, Path, Path, Mapping[str, Any]], ...] = (
    ("rd1", RD1_ROOT, BACKUP_ROOT / rs.RD1_INCREMENT_NAME, {"files": rs.RD1_FACTS["files"], "bytes": rs.RD1_FACTS["bytes"], "increment_manifest_sha256": rs.RD1_INCREMENT_MANIFEST_SHA256}),
    ("rd2", RD2_ROOT, BACKUP_ROOT / r3.RD2_INCREMENT_NAME, {k: r3.RD2_FACTS[k] for k in ("files", "bytes", "increment_manifest_sha256")}),
    ("rd3", RD3_ROOT, BACKUP_ROOT / r4.RD3_INCREMENT_NAME, {k: r4.RD3_FACTS[k] for k in ("files", "bytes", "increment_manifest_sha256")}),
    ("rd4", RD4_ROOT, BACKUP_ROOT / RD4_INCREMENT_NAME, RD4_FACTS),
)
FROZEN_DIR = RD1_ROOT / "archive" / "runtime"
GATE = C.GATE

CODE_FILES = ("m9_contract.py", "m9_artifacts.py", "m9_sticky.py", "m9_curriculum.py", "m9_rule.py", "m9_obs.py", "m9_lineages.py", "m9_verify.py", "m9_worker.py", "m9_pool.py",
              "m9_vec.py", "m9_train.py", "m9_eval.py", "m9_run.py", "m9_claim.py", "m9_report.py", "m9_session.py", "m9_snapshot.py", "m9_stub.py", "m9_testenv.py",
              "m9_tests.py",
              "m8_rd_cells.py", "m8_rd_claims.py", "m8_rd_worker.py", "m8_rd2_worker.py", "m8_rd_resume.py", "m8_rd_session.py", "m8_rd3_resume.py", "m8_rd4_resume.py", "m8_rd_explore.py",
              "m8_rd_archive.py", "m8_rd_stub.py", "battleship_client.py", "battleship_process.py", "m7_standby.py", "m7_runtime.py", "m7f_trace.py", "m7n_crossing.py", "m7n_obs.py",
              "m7n_entity.py", "m7n_policy.py", "m7n_status_table.py", "m7g_spatial.py", "btt_rewards.py", "btt_learning.py", "m7u_gate.py", "m7u3_gate.py", "m7u2_gate.py",
              "m7s_gate.py", "m7h_curriculum.py", "run_artifacts.py", "tools/runs_backup.py", "data/m7n_action_classes_v1.json")
DOC_FILES = ("docs/rl_m9_policy_proposal_2026-10-03.md", "docs/rl_m9_g1_decisions_2026-10-04.md", "docs/rl_m9_g1_implementation.md")


def utc() -> str:
    return A.utc()


def sha256_file(p: Path) -> str:
    return mw.sha256_file(Path(p))


# -- the sampler (every row carries the task block and created_utc) -----------------------------------------------------------------------


def make_sampler(path: Path, caps_mb: Mapping[str, float]) -> Any:
    """The M7u3 whole-process-tree sampler (reused; imported lazily because that module imports torch) with every row written through the M9 writer."""
    import m7u3_gate as g3

    class M9Sampler(g3.TreeSampler):
        last: Optional[Dict[str, Any]] = None

        def sample(self):                                                   # noqa: D401
            snap = self.snapshot()
            if snap is None:
                return None
            self.samples += 1
            for k in ("main_private_mb", "tree_private_mb", "tree_working_set_mb", "processes"):
                self.peak[k] = max(self.peak[k], snap[k])
            self.peak["system_available_min_mb"] = min(self.peak["system_available_min_mb"], snap["system_available_mb"])
            self.peak["system_commit_free_min_mb"] = min(self.peak["system_commit_free_min_mb"], snap["system_commit_free_mb"])
            why = g3.memory_breach(snap, self.caps)
            if why and self.breach is None:
                self.breach = why
            self.last = dict(snap, seq=self.samples)
            A.append_jsonl(self.path, A.stamp(dict(snap, t_s=round(self.now() - self._t0, 1), breach=why)))
            return snap

    return M9Sampler(Path(path), interval=ses1.MEMORY_SAMPLE_S, caps=caps_mb)


# -- identity and approval ------------------------------------------------------------------------------------------------------------


def m8_trees_state() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, root, inc, expect in M8_TREES:
        imm = rs.rd1_immutability(root, inc)
        probs = list(imm.get("problems", []))
        for ek, ik in (("files", "files"), ("bytes", "bytes"), ("increment_manifest_sha256", "manifest_sha256")):
            if imm.get(ik) != expect[ek]:
                probs.append(f"the increment's {ik} {imm.get(ik)!r} differs from the registered {expect[ek]!r}")
        out[name] = {"ok": bool(imm.get("ok")) and not probs, "files": imm.get("files"), "bytes": imm.get("bytes"), "manifest_sha256": imm.get("manifest_sha256"),
                     "increment": inc.name, "problems": probs}
    out["ok"] = all(v["ok"] for k, v in out.items() if k != "ok")
    return out


def earlier_trees_immutability() -> Dict[str, Any]:
    s = m8_trees_state()
    return {"ok": s["ok"], "problems": [f"{k}: {p}" for k, v in s.items() if k != "ok" for p in v["problems"]],
            **{k: {kk: v[kk] for kk in ("ok", "files", "manifest_sha256", "bytes")} for k, v in s.items() if k != "ok"}}


def frozen_pins() -> Dict[str, str]:
    return {n: sha256_file(FROZEN_DIR / n) for n in mw.FROZEN_FILES}


def archive_pins() -> Mapping[str, Any]:
    meta = json.loads((RD1_ROOT / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    return meta["pins"]


def identity_now() -> Dict[str, Any]:
    return {"executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None, "runtime_files": ses1.runtime_pins(), "frozen_sha256": frozen_pins()}


def lineage_facts() -> Dict[str, Any]:
    import m9_lineages as L

    out: Dict[str, Any] = {}
    for name, ln in L.load_registered(REPO_ROOT).items():
        out[name] = ln.registration()
    out["pin_tick0"] = L.load_pin_tick0(REPO_ROOT)
    return out


def identity() -> Dict[str, Any]:
    import m9_curriculum as CU
    import m9_run as RUN
    import m9_sticky as S

    dr = ses1.d_records_digest()
    pins = archive_pins()
    return {"gate": GATE, "scope": C.SCOPE, "milestone": C.MILESTONE, "task": dict(C.TASK), "rule": R.RULE_ID, "rule_sha256": R.rule_digest(), "contract_sha256": C.contract_digest(),
            "contracts": {"m9_contract": C.contract_digest(), "m9_curriculum": CU.contract_digest(), "m9_rule": R.rule_digest(), "m9_artifacts": A.contract_description()["contract"],
                          "m9_sticky": S.contract_description()["contract"]},
            "key_strings": dict(C.KEYS), "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None, "runtime_files": ses1.runtime_pins(),
            "frozen_sha256": frozen_pins(), "archive_pins": {"executable_sha256": pins.get("executable_sha256"), "frozen_sha256": pins.get("frozen_sha256"),
                                                            "runtime_files": pins.get("runtime_files")},
            "flags": {"train": C.FLAGS_TRAIN, "eval": C.FLAGS_EVAL, "verify": C.FLAGS_VERIFY}, "lineages": lineage_facts(), "m8_trees": {k: {kk: v[kk] for kk in ("files", "bytes", "manifest_sha256", "increment")}
                                                                                                                                             for k, v in m8_trees_state().items() if k != "ok"},
            "caps": {"wall_caps_s": dict(C.WALL_CAPS_S), "tick_caps": dict(C.TICK_CAPS), "transition_cap": C.TRANSITION_CAP, "global_cap_s": C.GLOBAL_CAP_S,
                     "memory_caps_mb": dict(C.MEMORY_CAPS_MB), "max_battleship_processes": C.MAX_BATTLESHIP_PROCESSES},
            "budget": RUN.budget_projection(), "ppo": dict(C.PPO), "split_rule": {"default": list(C.SPLIT_DEFAULT), "alternative": list(C.SPLIT_ALTERNATIVE), "ratio": C.SPLIT_SWITCH_RATIO},
            "readiness": ses1.READINESS, "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "docs_sha256": {f: sha256_file(REPO_ROOT / f) for f in DOC_FILES if (REPO_ROOT / f).is_file()}, "git_head": ses1.git("rev-parse", "HEAD").strip(),
            "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


def approval_status(path: Optional[Path] = None, want: Optional[Mapping[str, Any]] = None) -> Tuple[bool, str]:
    return ses1.approval_status(Path(APPROVAL if path is None else path), want if want is not None else identity())


# -- preflight ------------------------------------------------------------------------------------------------------------------------


def _run_unit_suites() -> Tuple[Dict[str, Any], List[str]]:
    problems: List[str] = []
    rep: Dict[str, Any] = {}
    r = subprocess.run([sys.executable, "-B", str(RL / "m9_tests.py"), "unit"], capture_output=True, text=True, cwd=REPO_ROOT)
    rep["unit_suite_m9"] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
    if r.returncode != 0:
        problems.append("unit_suite_m9 failed")
    r = subprocess.run([sys.executable, "-B", str(RL / "m9_rule.py"), "self-test"], capture_output=True, text=True, cwd=REPO_ROOT)
    rep["rule_self_test_m9"] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
    if r.returncode != 0:
        problems.append("rule_self_test_m9 failed")
    return rep, problems


def pins_problems() -> List[str]:
    """The executable, the runtime files and the frozen configuration equal the archive's pins (rd1's, as rd2-rd4)."""
    p = archive_pins()
    now = identity_now()
    out: List[str] = []
    if now["executable_sha256"] != p.get("executable_sha256"):
        out.append("the executable differs from the archive's pin")
    if now["runtime_files"] != p.get("runtime_files"):
        out.append("a runtime file differs from the archive's pin")
    if now["frozen_sha256"] != p.get("frozen_sha256"):
        out.append("the frozen runtime configuration differs from the archive's pin")
    return out


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": C.SCOPE}
    if not sys.flags.dont_write_bytecode:
        problems.append("python was not started with -B (a compiled module written under rl/ would be a write-guard violation)")
    if RUN_ROOT.exists():
        problems.append(f"{RUN_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        r, p = _run_unit_suites()
        rep.update(r)
        problems += p
    if not EXECUTABLE.is_file():
        problems.append(f"missing executable {EXECUTABLE}")
    ident = identity()
    rep["executable_sha256"] = ident["executable_sha256"]
    rep["git_head"] = ident["git_head"]
    changed = ses1.tracked_changes()
    if changed:
        problems.append(f"tracked files differ from HEAD: {changed[:6]}")
    odd = ses1.untracked_not_new()
    if odd:
        problems.append(f"git status shows entries other than new files: {odd[:6]}")
    rep["git_status_new_files"] = sum(1 for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??"))
    pp = pins_problems()
    rep["pins"] = pp or "executable, runtime files and frozen configuration equal the archive's pins"
    problems += pp
    trees = ident["m8_trees"]
    rep["m8_trees"] = trees
    cvars = ses1.controller_cvar_problems(EXE_DIR / "BattleShip.cfg.json")
    rep["controller_cvars"] = cvars or "absent or zero"
    if cvars:
        problems.append(f"controller-rule CVars set in BattleShip.cfg.json: {cvars}")
    try:
        import m7n_status_table as st

        st.load_table()
        rep["status_table"] = "digest verified"
    except Exception as exc:                                         # noqa: BLE001
        problems.append(f"status table: {type(exc).__name__}: {exc}")
    s = m8_trees_state()
    if not s["ok"]:
        problems += [f"M8 tree {k}: {p}" for k, v in s.items() if k != "ok" for p in v["problems"]]
    try:
        import m9_lineages as L

        lins = L.load_registered(REPO_ROOT)
        rep["lineages"] = {n: {"words": ln.length, "native_action_digest": ln.native_action_digest[:16]} for n, ln in lins.items()}
    except Exception as exc:                                         # noqa: BLE001
        problems.append(f"lineages: {type(exc).__name__}: {exc}")
    cov = ses1.combined_coverage()
    rep["backup"] = {k: cov.get(k) for k in ("ok", "reason", "source_files", "uncovered", "increments", "skipped")}
    if not cov.get("ok"):
        problems.append(f"backup prerequisite not met: {cov.get('reason')}")
    procs = ses1.game_processes()
    if procs:
        problems.append(f"BattleShip already running: {procs}")
    rd = ses1.readiness()
    rep["readiness"] = rd
    problems += [f"readiness: {p}" for p in rd["problems"]]
    ok, why = approval_status(APPROVAL, ident)
    rep["approval"] = why
    approval = json.loads(APPROVAL.read_text(encoding="utf-8")) if APPROVAL.is_file() else None
    if approval is not None:
        try:
            A.check(approval, "the approval record")             # the approval is itself an M9 artifact: it carries the task block and created_utc
        except A.ArtifactError as exc:
            problems.append(f"approval record metadata: {exc}")
    sok, swhy = ses1.snapshot_status(approval)
    rep["source_snapshot"] = swhy
    if not sok:
        problems.append(f"source snapshot: {swhy}")
    if not ok:
        problems.append(why)
    rep["problems"] = problems
    rep["ok"] = not problems
    return rep


# -- the real environment -----------------------------------------------------------------------------------------------------------


def write_guard_roots() -> List[Path]:
    """Every tree a worker or the session must never write: each other directory under runs/, the sources and the documents."""
    roots = [p for p in RUNS.iterdir() if p.is_dir() and p.name != "m9_g1"]
    roots += [RL, REPO_ROOT / "docs"]
    return roots


def build_real_env(cfg: Any, sampler: Any = None, *, executable: Optional[Path] = None, run_root: Optional[Path] = None, frozen_dir: Optional[Path] = None,
                   pins: Optional[Mapping[str, Any]] = None, lineage_root: Optional[Path] = None, protect: Optional[Sequence[Path]] = None,
                   lineages_override: Optional[Mapping[str, Any]] = None, route_traces_override: Optional[Mapping[str, Any]] = None,
                   pin_override: Optional[Mapping[str, Any]] = None, flags_override: Optional[Mapping[str, str]] = None,
                   obs_pipeline_override: Optional[str] = None) -> Any:
    """The real RunEnv. The executable, run root, frozen directory, pins, lineages and flags are parameters for the tests that drive the real lifecycle code against a fake game."""
    import m7_runtime
    import m7f_trace as tr
    import m7n_crossing as xc
    import m8_rd2_worker as w2
    import m9_lineages as L
    import m9_obs
    import m9_pool as P
    import m9_run as RUN
    import m9_train as T
    import m8_rd_cells as mcell

    exe = Path(executable) if executable is not None else EXECUTABLE
    root = Path(run_root) if run_root is not None else RUN_ROOT
    fdir = Path(frozen_dir) if frozen_dir is not None else FROZEN_DIR
    ap = dict(pins if pins is not None else archive_pins())
    repo = Path(lineage_root) if lineage_root is not None else REPO_ROOT
    frozen = dict(ap["frozen_sha256"])
    lineages = dict(lineages_override) if lineages_override is not None else L.load_registered(repo)
    route_traces = dict(route_traces_override) if route_traces_override is not None else {n: L.load_route_trace(repo, ln) for n, ln in lineages.items()}
    pin_tick0 = dict(pin_override) if pin_override is not None else L.load_pin_tick0(repo)
    protected = [str(p) for p in (protect if protect is not None else write_guard_roots())]
    counter = {"n": 0}
    now = time.monotonic

    frozen_rt = mw.FrozenRuntime(fdir, frozen)
    orig_prepare = m7_runtime.prepare_worker_runtime

    def frozen_prepare(runtime_dir: Any, executable_: Any) -> Any:
        manifest = orig_prepare(runtime_dir, executable_)
        frozen_rt.install(Path(runtime_dir))                      # every replay (P1, P2, verification) uses the frozen configuration too
        manifest["frozen_config"] = True
        return manifest

    m7_runtime.prepare_worker_runtime = frozen_prepare

    def worker_spec(tag: str, flags: Mapping[str, str]) -> Callable[[int], Dict[str, Any]]:
        def spec(rank: int) -> Dict[str, Any]:
            return {"rank": rank, "root": str(root / "session" / "workers" / tag / f"w{rank:02d}"), "executable": str(exe), "flags": dict(flags_override or flags), "frozen_dir": str(fdir),
                    "frozen_sha256": frozen, "exe_sha256": ap.get("executable_sha256"), "runtime_sha256": dict(ap.get("runtime_files") or {}), "port_base": 30000,
                    "port_size": 250, "failure_dir": str(root / "session" / "failures"), "lineage_dir": str(root / "lineages"), "lineages": list(lineages),
                    "pin_tick0": pin_tick0, "protected_roots": protected, **({"obs_pipeline": obs_pipeline_override} if obs_pipeline_override else {})}
        return spec

    def make_pool(tag: str, flags: Mapping[str, str]) -> Any:
        pool = P.SlotPool(cfg.n_slots, worker_spec(tag, flags), now=now, name=f"m9-{tag}")
        pool.wait_ready()
        return pool

    def replay(words: bytes, label: str, slot: int) -> Dict[str, Any]:
        counter["n"] += 1
        actions = [(*mcell.TRIPLES[w], i) for i, w in enumerate(words)]
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
        work = root / "session" / "vw" / f"s{slot}_{safe}"
        trace = tr.run_stepping_trace(label, exe, actions, work, extra_env=dict(flags_override or C.FLAGS_VERIFY), index=9000 + counter["n"], rank=12 + int(slot) % 8)
        mw.remove_tree_retry(work / "runtime", runtime=True)
        mw.remove_tree_retry(work / "episodes")
        return trace

    def analyse(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        return xc.analyse_trace(initial, steps)

    def promoted_trace(ln: Any, route_trace: Mapping[str, Any]) -> Dict[str, Any]:
        """P1's replay through a promoted standby: the unchanged M8 worker (RealBackend, its `trace` job: every reply's record digest must equal the rd4
        verifying replay's)."""
        import multiprocessing

        from multiprocessing.connection import wait as mp_wait

        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe(duplex=True)
        abort = ctx.Event()
        spec = {"rank": 10, "root": str(root / "session" / "workers" / f"promoted_{ln.name}"), "executable": str(exe), "flags": dict(flags_override or C.FLAGS_VERIFY), "frozen_dir": str(fdir),
                "frozen_sha256": frozen, "exe_sha256": ap.get("executable_sha256"), "runtime_sha256": dict(ap.get("runtime_files") or {}), "port_base": 30000, "port_size": 250,
                "failure_dir": str(root / "session" / "failures"), "protected_roots": protected}
        p = ctx.Process(target=w2.worker_main2, args=(child, spec, abort), name=f"m9-promoted-{ln.name}", daemon=True)
        p.start()
        child.close()
        try:
            t0 = now()
            while not parent.poll(0.1):
                if now() - t0 > 180 or not p.is_alive():
                    raise RuntimeError("the promoted-standby worker did not become ready")
            kind, payload = parent.recv()
            if kind != "ready":
                raise RuntimeError(f"promoted-standby worker failed to start: {payload}")
            digests = [mcell.record_digest(mcell.record_of(s)) for s in route_trace["steps"]]
            parent.send(("job", {"kind": "trace", "name": f"promoted-{ln.name}", "words": bytes(ln.words), "expected_digests": digests, "pin": pin_tick0}))
            t0 = now()
            while not parent.poll(0.2):
                if now() - t0 > 240 or not p.is_alive():
                    raise RuntimeError("the promoted-standby replay did not finish")
            kind, res = parent.recv()
            if not res.get("ok"):
                if res.get("kind") == "mismatch":
                    import m9_vec as V

                    raise V.IntegrityStop("the promoted-standby replay differs from the rd4 verifying replay", res)
                raise RuntimeError(f"the promoted-standby replay could not run (a lifecycle failure, not a mismatch): {res}")
            return res
        finally:
            try:
                parent.send(("stop",))
            except (OSError, BrokenPipeError):
                pass
            p.join(60)
            if p.is_alive():
                p.terminate()
                p.join(10)

    def make_model(vec: Any, n: int) -> Any:
        return T.make_ppo(vec, n)

    def load_model(path: Path) -> Any:
        import m7n_policy as pol
        from stable_baselines3 import PPO

        pol.assert_v3_checkpoint(Path(path))
        m = PPO.load(str(path), device="cpu")
        m.policy.set_training_mode(False)
        return m

    def leftover() -> List[int]:
        from m7_runtime import BATTLESHIP_IMAGE, wait_until_no_process

        return list(wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0))

    private_mb = None
    try:
        import m7u_gate as g1

        private_mb = g1.private_mb
    except Exception:                                                # noqa: BLE001
        pass
    return RUN.RunEnv(make_pool=make_pool, replay=replay, analyse=analyse, promoted_trace=promoted_trace, lineages=lineages, route_traces=route_traces, pin_tick0=pin_tick0,
                      make_model=make_model, load_model=load_model, now=now, pipeline_cls=(getattr(__import__(obs_pipeline_override.split(":")[0]), obs_pipeline_override.split(":")[1]) if obs_pipeline_override else m9_obs.V3Pipeline), sampler=sampler, private_mb=private_mb,
                      earlier_trees=earlier_trees_immutability, identity_now=identity_now,
                      pins={"executable_sha256": ap.get("executable_sha256"), "runtime_files": dict(ap.get("runtime_files") or {}), "frozen_sha256": frozen},
                      provenance_violations=lambda: list(mw.ProvenanceGuard.violations), leftover_processes=leftover)


# -- commands ------------------------------------------------------------------------------------------------------------------------


def cmd_run(overrides: Optional[Mapping[str, Any]] = None) -> int:
    """`overrides` (RunConfig fields) exists for the tests of this command only; the session passes none."""
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process

    import m8_rd2_worker as w2
    import m9_run as RUN

    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(A.stamp(pf), indent=1, default=str))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"          # every child interpreter of the session (spawned workers inherit the -B flag as well)
    install_kill_on_close_job()
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install(write_guard_roots())
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    cfg = RUN.RunConfig(root=RUN_ROOT, **dict(overrides or {}))
    RUN_ROOT.mkdir(parents=True)
    cfg.session_dir.mkdir(parents=True)
    shutil.copyfile(APPROVAL, cfg.session_dir / "approval_copy.json")
    A.write_json(cfg.session_dir / "open.json", A.stamp({"utc": utc(), "scope": C.SCOPE, "approval_sha256": sha256_file(APPROVAL), "pins": identity_now(),
                                                         "preflight": {k: pf.get(k) for k in ("executable_sha256", "git_head", "readiness", "backup", "approval", "source_snapshot",
                                                                                              "unit_suite_m9", "rule_self_test_m9", "m8_trees", "pins")},
                                                         "caps": identity()["caps"], "budget": RUN.budget_projection()}))
    sampler = make_sampler(cfg.session_dir / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    out: Dict[str, Any] = {}
    try:
        env = build_real_env(cfg, sampler)
        sess = RUN.Session(cfg, env)
        out = sess.run()
    finally:
        rep = sampler.stop()
        A.write_json(cfg.session_dir / "memory_summary.json", A.stamp(rep))
    left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
    A.write_json(cfg.session_dir / "leftover_processes.json", A.stamp({"battleship_pids_after_the_run": left}))
    print(json.dumps({k: out.get(k) for k in ("outcome", "R", "reasons", "crossing_learned", "route_mastered_ticks")}, indent=1, default=str)[:3000])
    if left:
        print(f"WARNING: BattleShip processes still alive after the run: {left}")
    return 0


def cmd_verify_run() -> int:
    import m9_report as RPT

    rep = RPT.verify_run(RUN_ROOT)
    print(json.dumps(A.stamp(rep), indent=1, default=str))                   # stamped, so a saved copy under runs/m9_g1/derived/ carries the task block and created_utc
    return 0 if rep["ok"] else 1


def cmd_report() -> int:
    import m9_report as RPT

    print(json.dumps(A.stamp(RPT.full_report(RUN_ROOT)), indent=1, default=str))
    return 0


def cmd_status() -> int:
    st = RUN_ROOT / "session" / "state.json"
    print(json.dumps({"run_root_exists": RUN_ROOT.exists(), "approval_present": APPROVAL.is_file(), "state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None},
                     indent=1, default=str))
    return 0


def cmd_template() -> int:
    ident = identity()
    rec = dict(ident, approval="PENDING (a reviewer replaces this with APPROVED ... and fills the authorisation and the source snapshot entries; this command never writes the record)",
               revision=1, authorisation={"source": "<the user's message>", "text": ["<what is authorised, once>"]},
               source_snapshot={"dest": "D:\\BattleShip_source_snapshots\\<date>_m9_g1", "snapshot_json_sha256": "<sha256>", "result": "PASS", "files": "<n>",
                                "git_head": ident["git_head"], "independent_verification": "<tool verify and an independent PowerShell re-hash>"},
               backup_coverage_before_approval="<combined coverage record>", task=dict(C.TASK), created_utc=utc())
    print(json.dumps(rec, indent=1, default=str))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("status", "verify-run", "approval-template", "run", "report"):
        sub.add_parser(n)
    p = sub.add_parser("preflight")
    p.add_argument("--skip-unit", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "preflight":
        rep = preflight(run_unit=not a.skip_unit)
        print(json.dumps(A.stamp(rep), indent=1, default=str))
        return 0 if rep["ok"] else 1
    if a.cmd == "approval-template":
        return cmd_template()
    if a.cmd == "verify-run":
        return cmd_verify_run()
    if a.cmd == "report":
        return cmd_report()
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
