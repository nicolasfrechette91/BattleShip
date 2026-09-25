"""M7g Phase K campaign tests: evaluation metrics, matrix, orchestration, resource gate and the decision rule.

Nothing here trains a model: no learn(), no optimizer step. Orchestration is tested with dry runs, a redirected
temporary matrix root, synthetic records (untrained checkpoint sets built with the trainer's own helpers, synthetic
evaluation rows) and existing artifacts. The M7g-a crossing fixtures are read ONLY by game_metrics_fixtures, as
validation evidence for the metrics recorder (their known left entries and target IDs); they are never a training
input, a start state or a route hint, and nothing outside this test reads them.

Two manifests (test isolation, 2026-09-24). The Phase K campaign ran and was committed, so the frozen manifest
(docs/rl_obs_v2_phase_k_manifest_m7g.json == runs/m7g_k/_matrix/manifest.json, HEAD afa42fc) no longer describes any
later checkout. It is checked as ARCHIVED evidence: byte-identical to the recorded sha256, internally consistent, and
refused for a relaunch on this tree (its drift is exactly HEAD and, when the code changed, the code fingerprint; the
executable, submodules and every profile still match). The orchestration logic is exercised in temporary roots against
a manifest built for the tree under test by km.build_manifest() (the `manifest` command's own function), written below
the suite root; every provenance and drift check runs in full against it. That current-tree manifest must equal the
frozen one in every contract field (runs, fingerprints, untrained digests, proofs, census, rule, limits), so the tree
under test still registers the Phase K experiment exactly.

Unit cases (no game):
    unit_recorder              m7g_eval_metrics self-test (incremental derivation == m7f check_trace on 9 variants,
                               record checks incl. the 446/447 clocks); the left boundary equals the M7g-a derived one
    unit_recorder_wiring       evaluator opt-in (flags, factories, rows), tracker hook, training never records metrics
    unit_manifest              archived: frozen manifest byte-identical and consistent, drift only HEAD / code;
                               current-tree manifest ok, no drift, equal to the frozen one in every contract field;
                               six comparison profiles pinned; proofs; census; untrained v1 digests == M7d's
    unit_drift_detection       executable / HEAD / submodule / code / profile changes are all reported as drift; the
                               frozen manifest is refused on this tree for exactly the archived reasons
    unit_resource_gate         commit AND physical gated separately (boundaries inclusive, missing reading fails),
                               disk / CPU / processes / ports / env; one real reading, nothing launched
    unit_dry_runs              real (archived) root: every launch path refused (manifest drift; verified runs skipped;
                               existing pilot never overwritten; extension locked by the recorded gate), nothing
                               created or changed; temporary root with the current-tree manifest: plan, refusals
                               (out of order, extension without a decision), nothing created
    unit_partial_and_resume    temporary root: a partial run stops `train`; --restart-partial moves it aside intact and
                               relaunches from scratch; --resume continues the own lineage (deviation recorded); a
                               foreign-seed checkpoint is refused
    unit_pilot_gating          temporary root, stand-in launcher: v2 alone refused without a passed v1 control; an
                               inexact control reproduction stops the pilot before any evaluation and before v2
    unit_checkpoint_provenance synthetic checkpoint sets pass; wrong run id / point / seed / executable / arm and a
                               historical M7e set are refused
    unit_analysis              decision-rule self-test (every gate and branch) + an end-to-end synthetic evaluation tree
                               through load / report / analyze (decision recorded once; gate 6 unlocks --extension)
    unit_census                planned versus executed episodes on a synthetic tree
    unit_historical_verify     the (Dict-aware) M7d run verification still verifies runs/m7e/m7e_s0_v2 (read-only)
    unit_isolation             new modules never reference the fixtures; only the evaluator imports the recorder
Game cases (no training; fresh BattleShip processes, at most 10):
    game_metrics_fixtures      both fixtures through the v1 and v2 worker stacks with the recorder (validation evidence
                               only): left entry and target IDs / ticks equal the fixtures' stored evidence and the M7f /
                               M7g-a derivations on the raw trace; cold == standby-promoted
    game_metrics_tas_clear     the 7.43 TAS below Track 1 with the recorder: clear, 446 / 447 kept separate, ten
                               targets, target 2, left entry at consumed tick 359
    game_clear_verification    that TAS artifact re-validated natively (446 / 447); a collapsed clock is refused
    game_eval_end_to_end       temporary root: untrained checkpoint sets of both arms through the driver's evaluation
                               path (provenance, metrics, verification) with reduced counts; random baseline

Usage: python rl/m7g_k_campaign_tests.py [unit|game|<case> ...] [--root runs/_tests/m7g_k_campaign_<utc>]
(the default root is outside the archived Phase K tree runs/m7g_k, which the suite never writes)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import numpy as np  # noqa: E402

import experiment_config as ec  # noqa: E402
import m7g_k_matrix as km  # noqa: E402
import m7g_k_run as kr  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
TAS = REPO_ROOT / "tas_input_2" / "mario_743.btti"
FIXTURES = {"lower": REPO_ROOT / "rl" / "fixtures" / "m7g" / "lower_precision_2ad7b1da89d8.json",
            "upper": REPO_ROOT / "rl" / "fixtures" / "m7g" / "upper_moving_platform_8b9ecf2b967f.json"}
M6 = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}
DIAG = {"SSB64_RL_TARGET_DIAG": "1"}
SPATIAL = {"SSB64_RL_SPATIAL": "1"}
# The six comparison profiles as prepared in the readiness task (source, semantic, compatibility): must not change.
PINNED_SIX = {
    "m7g_s0_v1": ("d9f763f701deadf3432256736d0d904be192d74a965cff7af5bbb0dab143faa9", "d8d993eaacf7ee72d3f8c98787bafa8a2a4f583e42746827b2862c5f5941fd8b", "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "m7g_s0_v2": ("082b46b3a77012e65f7baa7c646edf53d2ae2421adfe7e86a6ee65556e5d18ff", "7ebf069407cc1e491eca5ff9ebafdbc63397b0db16252f26a10d5d6a284457d5", "7b9cfd189bda17f7de2b5e54ef1e2821246438bf24a8374a7e9646ec57acf4f0"),
    "m7g_s1_v1": ("ab7dbbb4b68180f0935e42999a1fb442b05994e17aff9c783b1ada6251947699", "dd87c6c044691af15d3d9a5f8237f0ffca86bad7046f96a7b0318341de62ffc7", "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "m7g_s1_v2": ("efbcef81e1c22a82be032a5aefed29107aa817233364dbea1b761cb7c1a93679", "c9bdb6369f08ed640c4497a95dbf4db7d17f0714209f95c01193804cfe17d087", "7b9cfd189bda17f7de2b5e54ef1e2821246438bf24a8374a7e9646ec57acf4f0"),
    "m7g_s2_v1": ("6b8b6285c1703571031a4d1c8111d71daa762f9b2585e08314b08726d5a8367f", "684dc27abebbc9f4de00f984c3f90607049a6c289fbfe44249273d2579c57bb8", "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "m7g_s2_v2": ("c8a31441d73b2d3b0b0e4f6ed03129842f649234300e7ae9979cb9853e2bdd2f", "b9286221247fa7ecd688b39808c3294dc3007ab661b9ed8cf79941fbd7f9dc2c", "7b9cfd189bda17f7de2b5e54ef1e2821246438bf24a8374a7e9646ec57acf4f0"),
}
M7D_INITIAL_V1 = {0: "68155f41065d243f", 1: "1dd753aeda5f", 2: "9fa632c6ffeb"}   # M7d manifest digests (prefixes)
# The archived campaign's frozen manifest (docs copy == runs/m7g_k/_matrix/manifest.json), as recorded by Phase K.
FROZEN_MANIFEST_SHA256 = "9a58f03b6f6f2f0fc8db8824c65e27a5f4470bddf4b113dbd890425ee4ac6e4e"
FROZEN_HEAD = "afa42fcd01b4b6657f57a78948ae212f59d96955"
# The only drift the frozen manifest may show on a later checkout: the commit and (when rl/ changed) the code.
ARCHIVED_DRIFT_PREFIXES = ("parent HEAD ", "the Python code or a Phase K profile changed since the manifest")
IDENTITY_KEYS = ("created_utc", "revisions", "code")     # manifest fields that describe the tree, not the experiment


class CaseFailure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise CaseFailure(msg)


class Suite:
    def __init__(self, root: Path):
        self.root = root

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _no_battleship() -> bool:
    from m7_runtime import list_processes_named

    return not list_processes_named()


_CURRENT_MANIFEST: Dict[str, Any] = {}


def current_tree_manifest() -> Dict[str, Any]:
    """The manifest of the tree under test: km.build_manifest() on the real root (read-only there), built once per
    process, never written over a frozen manifest. Temporary roots are seeded with it (see _Root)."""
    if not _CURRENT_MANIFEST:
        km.configure_root(None)
        _CURRENT_MANIFEST.update(km.build_manifest())
    return copy.deepcopy(_CURRENT_MANIFEST)


def contract_view(man: Mapping[str, Any]) -> Dict[str, Any]:
    """A manifest without the fields that identify the checkout (commit, dirty flag, code fingerprint, build time) and
    without the directory plan's list of directories that happen to exist."""
    m = {k: copy.deepcopy(v) for k, v in man.items() if k not in IDENTITY_KEYS}
    if isinstance(m.get("directory_plan"), dict):
        m["directory_plan"].pop("existing", None)
    return m


def archived_drift_problems(drift: Sequence[str], frozen: Mapping[str, Any]) -> List[str]:
    """What is wrong with the frozen manifest's drift on this checkout: anything beyond HEAD / code, or a HEAD that
    does not descend from the Phase K launch commit."""
    import subprocess

    p = [d for d in drift if not d.startswith(ARCHIVED_DRIFT_PREFIXES)]
    head = (frozen.get("revisions") or {}).get("head")
    if head != FROZEN_HEAD:
        p.append(f"frozen manifest HEAD {head} != recorded {FROZEN_HEAD}")
    if any(d.startswith("parent HEAD ") for d in drift):
        rc = subprocess.run(["git", "merge-base", "--is-ancestor", FROZEN_HEAD, "HEAD"], cwd=str(REPO_ROOT),
                            capture_output=True).returncode
        if rc != 0:
            p.append(f"HEAD does not descend from the Phase K launch commit {FROZEN_HEAD[:12]}")
    return p


class _Root:
    """Redirect the Phase K tree to a temporary root for one case (always restored). The root's frozen-manifest slot
    (<root>/_matrix/manifest.json) is seeded with the current-tree manifest, so the orchestration runs every drift and
    provenance check against a manifest that describes the tree under test."""

    def __init__(self, root: Path, *, seed_manifest: bool = True):
        self.root = root
        self.seed_manifest = seed_manifest

    def __enter__(self) -> Path:
        man = current_tree_manifest() if self.seed_manifest else None
        km.configure_root(self.root)
        if man is not None and not kr.frozen_manifest_path().exists():
            km.write_json(kr.frozen_manifest_path(), man)
        return self.root

    def __exit__(self, *exc: Any) -> None:
        km.configure_root(None)
        kr.LAUNCHER = kr.EVALUATE_FN = kr.REPLAY_FN = None


def _args(*argv: str) -> argparse.Namespace:
    return kr.build_parser().parse_args(list(argv))


def _synthetic_checkpoint(spec: km.RunSpec, *, t: int = 0, run_id: Optional[str] = None,
                          profile_spec: Optional[km.RunSpec] = None) -> Path:
    """An untrained checkpoint set with the metadata M7Run writes (trainer helpers; manifest executable; current
    revisions), at spec.run_dir/checkpoints/ckpt_<t>. profile_spec builds it from another run's profile."""
    import gymnasium as gym
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv

    import m7_trainer as tr
    import m7g_obs as mo
    from btt_learning import make_policy_observation_space, make_track1_action_space
    from btt_parallel import RunCoordinator, initial_coordination_state
    from m7_runtime import repository_revisions

    src = profile_spec or spec
    exp = km.load_run(src)
    cfg = tr.config_from_experiment(exp)
    space = mo.make_observation_space() if cfg.observation_v2 else make_policy_observation_space()

    class _Spaces(gym.Env):
        def __init__(self) -> None:
            self.observation_space = space
            self.action_space = make_track1_action_space()

        def _z(self) -> Any:
            if isinstance(space, gym.spaces.Dict):
                return {k: np.zeros(s.shape, np.float32) for k, s in space.spaces.items()}
            return np.zeros(space.shape, np.float32)

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return self._z(), {}

        def step(self, a):
            return self._z(), 0.0, False, False, {}

    torch.set_num_threads(1)
    vecnorm = tr.make_vecnormalize(cfg, DummyVecEnv([_Spaces for _ in range(cfg.n_envs)]))
    model = tr.make_model(cfg, vecnorm)
    tr.annotate_model(cfg, model)
    model.num_timesteps = int(t)
    rid = run_id or spec.name
    manifest = kr.load_manifest(freeze=False)       # the (temporary) root's manifest
    run_meta = {"run_id": rid, "purpose": "test", "lineage": [], "contracts": tr.run_contracts(cfg),
                "horizon": cfg.horizon, "n_envs": cfg.n_envs, "ppo": tr.resolved_ppo_params(model, cfg.policy),
                "seeds": {"base_seed": cfg.base_seed}, "executable": {"path": str(cfg.executable),
                                                                     "sha256": manifest["executable"]["sha256"]},
                "revisions": repository_revisions(), "m6_flags": dict(cfg.extra_env), "versions": tr.versions(),
                "torch_threads": {"requested": 1}, "lifecycle": cfg.lifecycle_json(),
                "experiment": dict(exp.summary(), compatibility_view=exp.compatibility_view()),
                "policy_network": tr.policy_network_identity(cfg, model)}
    d = spec.run_dir / "checkpoints" / f"ckpt_{t:09d}"
    d.parent.mkdir(parents=True, exist_ok=True)
    coord = RunCoordinator.create(spec.run_dir / f"coordination_{t}", initial_coordination_state(rid, "training", 10))
    tr.save_checkpoint_set(d, model, vecnorm, run_meta=run_meta, coordinator=coord, label=d.name, rollouts=0)
    vecnorm.close()
    return d


# -- unit ----------------------------------------------------------------------------------------------------------------


def unit_recorder(s: Suite) -> Dict[str, Any]:
    import m7g_eval_metrics as em
    import m7g_fixture as mf   # the stage-geometry decoder of M7g-a (collision data, not a fixture file)

    check(em.self_test() == 0, "m7g_eval_metrics self-test failed")
    left = mf.derive_regions(mf.decode_stage_geometry())["left_boundary_x"]
    check(em.LEFT_BOUNDARY_X == left == -2100.0, f"left boundary {em.LEFT_BOUNDARY_X} vs derived {left}")
    check(em.LEFT_TARGET_IDS == mf.LEFT_TARGET_IDS and em.MOVING_TARGET_ID == 2, "target ID constants")
    return {"left_boundary_x": left}


def unit_recorder_wiring(s: Suite) -> Dict[str, Any]:
    import m7_evaluation as ev
    import m7g_eval_metrics as em
    import m7g_obs as mo
    from btt_parallel import M7EpisodeTracker, WorkerFactory

    base = ev.EvaluationSettings(executable=str(EXE), n_workers=2, extra_env=tuple(M6.items()))
    check(base.eval_metrics is False and base.effective_extra_env() == tuple(M6.items()), "default must be unchanged")
    on = kr.phase_k_settings(km.load_run(km.run_by_name("m7g_s0_v2")))
    check(on.eval_metrics and dict(on.effective_extra_env()) == {**M6, **SPATIAL, **DIAG} and on.observation is None,
          f"phase K settings {on.effective_extra_env()}")
    d = s.dir("unit_recorder_wiring")
    facs, _ = ev._prepare_workers(d / "v1", 2, "evaluation", "t", ev.EvaluationSettings(
        executable=str(EXE), n_workers=2, extra_env=tuple(M6.items()), eval_metrics=True), preserve_all=True)
    check(all(isinstance(f, em.EvalMetricsWorkerFactory) and isinstance(f.inner, WorkerFactory)
              and dict(f.spec.extra_env) == {**M6, **DIAG} for f in facs), "v1 factories")
    facs2, _ = ev._prepare_workers(d / "v2", 1, "evaluation", "t", ev.EvaluationSettings(
        executable=str(EXE), n_workers=1, extra_env=tuple({**M6, **SPATIAL}.items()), eval_metrics=True,
        observation=mo.OBS_CONTRACT), preserve_all=True)
    check(isinstance(facs2[0].inner, mo.M7gWorkerFactory) and dict(facs2[0].spec.extra_env) == {**M6, **SPATIAL, **DIAG},
          "v2 factory")
    plain, _ = ev._prepare_workers(d / "plain", 1, "evaluation", "t", base, preserve_all=True)
    check(type(plain[0]) is WorkerFactory, "metrics off must build the unchanged factory")
    try:
        em.EvalMetricsWorkerFactory(plain[0])()
        raise CaseFailure("a spec without the diagnostic flag was accepted")
    except ValueError:
        pass
    check("eval_metrics" not in ev._row({"rank": 0}) and ev._row({"eval_metrics": {"x": 1}})["eval_metrics"] == {"x": 1},
          "_row adds the record only when present")
    tracker = M7EpisodeTracker.__new__(M7EpisodeTracker)
    tracker._pending_summary = None
    check(tracker.extend_pending_summary(lambda s_: {"a": 1}) is False, "no pending summary -> no-op")
    tracker._pending_summary = {"steps": 3}
    check(tracker.extend_pending_summary(lambda s_: {"eval_metrics": {"steps_seen": s_["steps"]}})
          and tracker._pending_summary == {"steps": 3, "eval_metrics": {"steps_seen": 3}}, "merge")
    # Training never records evaluation metrics: no profile sets the diagnostic flag, the trainer never enables it.
    # M7j/M7k: the one exception is a route-reward profile (btt_reward_v3, btt_reward_v3_t2), whose reward (not the
    # recorder) reads the diagnostic; the recorder is still never built in training (the trainer checks are unchanged).
    from btt_rewards import is_route_contract

    profiles = sorted((REPO_ROOT / "rl" / "configs").rglob("*.toml"))
    flagged = [p.name for p in profiles if "SSB64_RL_TARGET_DIAG" in dict(ec.load_experiment(p).extra_env)
               and not is_route_contract(ec.load_experiment(p).reward)]
    trainer_src = (RL_DIR / "m7_trainer.py").read_text(encoding="utf-8")
    check(not flagged and "eval_metrics" not in trainer_src and "TARGET_DIAG" not in trainer_src,
          f"training could record metrics: {flagged}")
    return {"profiles_checked": len(profiles)}


def _manifest_contract_checks(man: Mapping[str, Any], which: str) -> None:
    """The registered Phase K contract, as the original case checked it (applied to both manifests)."""
    check(man["ok"] and not man["problems"], f"{which} manifest problems {man['problems']}")
    runs = man["runs"]
    check(len(runs) == 12 and sum(r["extension"] for r in runs.values()) == 4
          and sum(r["pilot"] for r in runs.values()) == 2, f"{which}: run census")
    for seed, prefix in M7D_INITIAL_V1.items():
        check(runs[f"m7g_s{seed}_v1"]["expected_initial_policy_digest"].startswith(prefix), f"{which}: seed {seed} digest")
    check(len({runs[f"m7g_s{k}_v2"]["expected_initial_policy_digest"] for k in range(5)}) == 5, f"{which}: v2 seeds")
    check(all(p["proof"]["proof_ok"] for p in man["proofs"].values()) and len(man["proofs"]) == 3 + 5 + 4 + 2,
          f"{which}: proofs {[k for k, p in man['proofs'].items() if not p['proof']['proof_ok']]}")
    ep = man["evaluation_protocol"]
    check((ep["census"]["total_episodes"], ep["census_with_extension"]["total_episodes"]) == (6010, 9950),
          f"{which}: census totals")
    check(man["decision_rule"]["extension"]["seeds"] == [3, 4] and man["decision_rule"]["maximum"]["transitions"]
          == 30_720_000 and man["decision_rule"]["maximum"]["runs"] == 10, f"{which}: extension and maximum")
    plan = ep["plan"]["m7g_s0_v2"]
    check(len(plan) == 11 and all(p["eval_metrics"] and p["extra_env"] == {**M6, **SPATIAL, **DIAG} for p in plan)
          and all(p["extra_env"] == {**M6, **DIAG} for p in ep["plan"]["m7g_s0_v1"]), f"{which}: evaluation plan flags")


def unit_manifest(s: Suite) -> Dict[str, Any]:
    # 1. The archived campaign's frozen manifest: unchanged bytes, consistent, refused on this checkout for the
    #    archived reasons only (the executable, the submodules and every profile still match it).
    raw = km.MANIFEST_DOC.read_bytes()
    check(hashlib.sha256(raw).hexdigest() == FROZEN_MANIFEST_SHA256, "the frozen Phase K manifest changed")
    frozen_run_copy = km.DEFAULT_MATRIX_ROOT / "_matrix" / "manifest.json"
    if frozen_run_copy.is_file():
        check(frozen_run_copy.read_bytes() == raw, "runs/m7g_k/_matrix/manifest.json differs from the docs manifest")
    frozen = json.loads(raw)
    _manifest_contract_checks(frozen, "frozen")
    drift = kr.manifest_drift(frozen)
    bad = archived_drift_problems(drift, frozen)
    check(not bad, f"the frozen manifest drifts beyond HEAD / code: {bad}")
    for name, pinned in PINNED_SIX.items():
        e = ec.load_experiment(km.run_by_name(name).config_path)
        check((e.source.sha256, e.semantic_fingerprint, e.compatibility_fingerprint) == pinned, f"{name} changed")
    # 2. The tree under test: its own manifest is ok, current, and registers exactly the frozen contract.
    cur = current_tree_manifest()
    _manifest_contract_checks(cur, "current-tree")
    check(not kr.manifest_drift(cur), f"current-tree manifest drift {kr.manifest_drift(cur)}")
    a, b = contract_view(frozen), contract_view(cur)
    differ = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    check(not differ, f"the tree under test registers a different Phase K contract in {differ}")
    return {"frozen_sha256": FROZEN_MANIFEST_SHA256[:16], "frozen_drift": [d[:90] for d in drift],
            "current": {"head": cur["revisions"]["head"], "code_sha256": cur["code"]["sha256"][:16],
                        "code_files": cur["code"]["files"]},
            "contract_fields_compared": len(a), "runs": len(cur["runs"]), "proofs": len(cur["proofs"]),
            "census": [6010, 9950]}


def unit_drift_detection(s: Suite) -> Dict[str, Any]:
    frozen = km.read_json(km.MANIFEST_DOC)
    cur = kr.current_identity()
    archived = kr.manifest_drift(frozen, cur)
    check(archived and not archived_drift_problems(archived, frozen),
          f"the frozen manifest must be refused on this checkout for the archived reasons only: {archived}")
    # the archived filter is not a bypass: any other drift of the frozen manifest, or a changed contract field, is caught
    for name, mut in {"executable": lambda c: c.__setitem__("executable_sha256", "0" * 64),
                      "submodule": lambda c: c["revisions"]["submodules"].__setitem__("decomp", "e" * 40),
                      "profile": lambda c: c["profiles"].__setitem__("m7g_s1_v1", ("x", "y", "z"))}.items():
        c2 = copy.deepcopy(cur)
        mut(c2)
        check(archived_drift_problems(kr.manifest_drift(frozen, c2), frozen), f"archived filter missed {name} drift")
    man = current_tree_manifest()
    tampered = copy.deepcopy(man)
    tampered["runs"]["m7g_s0_v1"]["expected_initial_policy_digest"] = "0" * 64
    check(contract_view(tampered) != contract_view(frozen), "a changed untrained digest was not a contract difference")
    check(not kr.manifest_drift(man, cur), "baseline drift")
    found: Dict[str, List[str]] = {}
    for name, mut in {"executable": lambda m, c: c.__setitem__("executable_sha256", "0" * 64),
                      "head": lambda m, c: c["revisions"].__setitem__("head", "f" * 40),
                      "submodule": lambda m, c: c["revisions"]["submodules"].__setitem__("decomp", "e" * 40),
                      "code": lambda m, c: c.__setitem__("code_sha256", "1" * 64),
                      "profile": lambda m, c: c["profiles"].__setitem__("m7g_s1_v2", ("x", "y", "z")),
                      "manifest_not_ok": lambda m, c: m.__setitem__("ok", False)}.items():
        m2, c2 = copy.deepcopy(man), copy.deepcopy(cur)
        mut(m2, c2)
        found[name] = kr.manifest_drift(m2, c2)
        check(len(found[name]) == 1, f"{name}: drift {found[name]}")
    return {"mutations": {k: v[0][:80] for k, v in found.items()}, "frozen_manifest_refused_for": [d[:80] for d in archived]}


def unit_resource_gate(s: Suite) -> Dict[str, Any]:
    ok = {"avail_commit_gib": 6.0, "avail_phys_gib": 2.5, "disk_free_gib": 10.0, "cpu_mean_pct": 40.0,
          "battleship_pids": [], "listeners": [], "ssb64_environment_variables": []}
    g = kr.evaluate_resources(ok)
    check(g["ok"] and g["commit_gate"]["ok"] and g["physical_gate"]["ok"] and g["both_memory_gates_required"],
          f"inclusive boundaries {g['problems']}")
    cases = {"commit_low": ({"avail_commit_gib": 5.99}, ("commit",)),
             "physical_low": ({"avail_phys_gib": 2.49}, ("physical",)),
             "both_low": ({"avail_commit_gib": 3.0, "avail_phys_gib": 1.0}, ("commit", "physical")),
             "commit_missing": ({"avail_commit_gib": None}, ("commit",)),
             "physical_missing": ({"avail_phys_gib": None}, ("physical",)),
             "plenty_commit_low_physical": ({"avail_commit_gib": 40.0, "avail_phys_gib": 2.0}, ("physical",)),
             "plenty_physical_low_commit": ({"avail_commit_gib": 4.0, "avail_phys_gib": 30.0}, ("commit",))}
    for name, (over, failing) in cases.items():
        g = kr.evaluate_resources(dict(ok, **over))
        got = tuple(k for k in ("commit", "physical") if not g[f"{k}_gate"]["ok"])
        check(got == failing and not g["ok"], f"{name}: failing {got}")
    for over in ({"disk_free_gib": 9.9}, {"cpu_mean_pct": 40.1}, {"battleship_pids": [1]}, {"listeners": [{"port": 30000}]},
                 {"ssb64_environment_variables": ["SSB64_X"]}):
        check(not kr.evaluate_resources(dict(ok, **over))["ok"], f"{over} accepted")
    before = _no_battleship()
    real = kr.resource_gate(cpu_samples=2, cpu_interval=0.5)
    check(before and _no_battleship() and set(real) >= {"commit_gate", "physical_gate", "ok"}
          and real["commit_gate"]["measure"].startswith("commit limit"), "real reading")
    return {"real": {"commit_available_gib": real["commit_gate"]["available_gib"],
                     "physical_available_gib": real["physical_gate"]["available_gib"],
                     "cpu_mean_pct": real["measurement"]["cpu_mean_pct"], "ok": real["ok"], "problems": real["problems"]}}


def _dry(*argv: str) -> Tuple[int, str]:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kr.main(list(argv))
    return rc, buf.getvalue()


def _report(text: str) -> Dict[str, Any]:
    return json.loads(text[: text.rindex("}") + 1])


def _archived_tree_state(root: Path) -> Dict[str, Any]:
    """Top-level listing plus the bytes of the archived campaign's bookkeeping (state, manifest, analysis)."""
    files = sorted((root / "_matrix").glob("*.json")) if (root / "_matrix").is_dir() else []
    return {"listing": sorted(p.name for p in root.iterdir()) if root.is_dir() else [],
            "matrix_json": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}


def unit_dry_runs(s: Suite) -> Dict[str, Any]:
    out: Dict[str, Any] = {"archived_root": {}, "temporary_root": {}}
    # 1. The real (archived) Phase K root: every launch path is refused, nothing is created or changed.
    km.configure_root(None)
    root = km.DEFAULT_MATRIX_ROOT
    before = _archived_tree_state(root)
    frozen = kr.load_manifest(freeze=False)
    want_drift = kr.manifest_drift(frozen)
    check(want_drift and not archived_drift_problems(want_drift, frozen), f"archived drift {want_drift}")
    state = kr.load_state()
    archived = all(((state.get("runs") or {}).get(sp.name) or {}).get("status") == "verified" for sp in km.matrix())
    rc, text = _dry("train", "--dry-run", "--skip-resource-gate")
    rep = _report(text)
    check(rc == kr.EXIT_FAILED and rep["manifest_drift"] == want_drift and rep["blocking_problems"] == want_drift,
          f"archived train dry run: exit {rc}, blocking {rep['blocking_problems']}")
    if archived:
        check(all(p["status"] == "verified" and p["action"] == "skip" for p in rep["plan"]),
              f"a verified Phase K run would be retrained: {rep['plan']}")
    else:
        check(rep["plan"][0] == {"run": "m7g_s0_v1", "status": "absent", "action": "train from scratch"}, "plan")
    out["archived_root"]["train"] = {"exit": rc, "blocking": [b[:70] for b in rep["blocking_problems"]],
                                     "plan": sorted({p["action"] for p in rep["plan"]})}
    rc, _t = _dry("preflight", "--skip-resource-gate")
    check(rc == kr.EXIT_FAILED, f"archived preflight: exit {rc}")
    out["archived_root"]["preflight"] = rc
    rc, text = _dry("evaluate", "--dry-run")
    check(rc == kr.EXIT_FAILED and "BLOCKED" in text, f"archived evaluate dry run: exit {rc}")
    out["archived_root"]["evaluate"] = rc
    pilot_ran = any(sp.run_dir.exists() for sp in km.pilot_specs())
    rc, text = _dry("pilot", "--dry-run", "--skip-resource-gate")
    check(rc == kr.EXIT_FAILED and (not pilot_ran or "never overwritten" in text), f"archived pilot dry run: exit {rc}")
    out["archived_root"]["pilot"] = {"exit": rc, "existing_pilot_refused": pilot_ran}
    n3 = (state.get("decisions") or {}).get("n3") or {}
    rc, _t = _dry("train", "--dry-run", "--extension", "--skip-resource-gate")
    check(rc == kr.EXIT_USAGE and not n3.get("extension_required"), f"archived extension: exit {rc} ({n3})")
    out["archived_root"]["extension"] = {"exit": rc, "recorded_gate": n3.get("gate")}
    after = _archived_tree_state(root)
    check(before == after, f"a dry run changed the archived tree: {before} -> {after}")
    out["archived_root"]["unchanged_files"] = len(after["matrix_json"])
    # 2. A temporary root with the current-tree manifest: the launch logic itself.
    d = s.dir("unit_dry_runs")
    with _Root(d / "root") as troot:
        seeded = sorted(p.relative_to(troot).as_posix() for p in troot.rglob("*"))
        for name, argv, want in (("train", ("train", "--dry-run", "--skip-resource-gate"), kr.EXIT_OK),
                                 ("preflight", ("preflight", "--skip-resource-gate"), kr.EXIT_OK),
                                 ("out_of_order", ("train", "--dry-run", "--skip-resource-gate", "--only", "m7g_s1_v2"),
                                  kr.EXIT_FAILED),
                                 ("extension_refused", ("train", "--dry-run", "--extension", "--skip-resource-gate"),
                                  kr.EXIT_USAGE),
                                 ("pilot", ("pilot", "--dry-run", "--skip-resource-gate"), kr.EXIT_OK),
                                 ("evaluate", ("evaluate", "--dry-run"), kr.EXIT_OK)):
            rc, text = _dry(*argv)
            out["temporary_root"][name] = rc
            if name == "out_of_order":
                rc_ok = rc == kr.EXIT_OK and "out of order" in text     # the plan names the refusal; nothing launched
                check(rc_ok or rc == want, f"{name}: exit {rc}")
                check("out of order" in text, "out-of-order refusal not in the plan")
            else:
                check(rc == want, f"{name}: exit {rc} (want {want}): {text[-400:]}")
            if name == "train":
                plan = _report(text)["plan"]
                check(plan[0] == {"run": "m7g_s0_v1", "status": "absent", "action": "train from scratch"}
                      and all(p["action"].startswith("wait") for p in plan[1:]), f"plan {plan}")
        after_t = sorted(p.relative_to(troot).as_posix() for p in troot.rglob("*"))
        check(seeded == after_t, f"a dry run created something: {set(after_t) - set(seeded)}")
    return out


def unit_partial_and_resume(s: Suite) -> Dict[str, Any]:
    calls: List[Dict[str, Any]] = []

    def fake(**kw: Any) -> Dict[str, Any]:
        calls.append(kw)
        return {"exit_code": 1, "stop_reason": "test launcher (nothing trained)", "monitor": {}}

    d = s.dir("unit_partial_and_resume")
    with _Root(d / "root"):
        kr.LAUNCHER = fake
        spec = km.run_by_name("m7g_s0_v1")
        spec.run_dir.mkdir(parents=True)
        (spec.run_dir / "run.json").write_text("{}", encoding="utf-8")
        h0 = _tree_hash(spec.run_dir)
        rc = kr.cmd_train(_args("train", "--skip-resource-gate"))
        check(rc == kr.EXIT_USAGE and not calls and spec.run_dir.is_dir(), f"partial run not stopped: {rc} {calls}")
        rc = kr.cmd_train(_args("train", "--skip-resource-gate", "--restart-partial", "m7g_s0_v1"))
        moved = sorted(km.partial_root().iterdir())
        check(rc == kr.EXIT_FAILED and len(calls) == 1 and calls[0]["resume_from"] is None
              and Path(calls[0]["run_dir"]) == spec.run_dir and len(moved) == 1 and _tree_hash(moved[0]) == h0
              and not spec.run_dir.exists(), f"restart: {rc} {calls} {moved}")
        state = kr.load_state()
        check(state["runs"]["m7g_s0_v1"]["status"] == "failed"
              and any(e["kind"] == "partial_run_moved_aside" for e in state["events"]), "restart recorded")
        # a partial run with a checkpoint set of its own lineage -> --resume continues it as m7g_s0_v1_r1
        ckpt = _synthetic_checkpoint(spec, t=102_400)
        rc = kr.cmd_train(_args("train", "--skip-resource-gate", "--resume", "m7g_s0_v1"))
        state = kr.load_state()
        dev = state["runs"]["m7g_s0_v1"]["deviations"]
        check(rc == kr.EXIT_FAILED and len(calls) == 2 and Path(calls[1]["resume_from"]) == ckpt
              and calls[1]["run_id"] == "m7g_s0_v1_r1" and Path(calls[1]["run_dir"]).name == "m7g_s0_v1_r1"
              and dev and dev[-1]["kind"] == "lineage_resumed", f"resume: {rc} {calls[-1]} {dev}")
        # a checkpoint of another seed's profile placed in this run's directory is refused by the resume guard
        shutil.rmtree(spec.run_dir / "checkpoints")
        _synthetic_checkpoint(spec, t=204_800, profile_spec=km.run_by_name("m7g_s1_v1"))
        rc = kr.main(["train", "--skip-resource-gate", "--resume", "m7g_s0_v1"])
        check(rc == kr.EXIT_FAILED and len(calls) == 2, "a foreign-seed checkpoint was resumed")
        # the extension stays refused without a recorded n = 3 decision
        check(kr.cmd_train(_args("train", "--extension", "--skip-resource-gate")) == kr.EXIT_USAGE, "extension")
    return {"launcher_calls": len(calls), "partial_kept": moved[0].name}


def unit_pilot_gating(s: Suite) -> Dict[str, Any]:
    """Temporary root, stand-in launcher: v2 alone is refused without a passed v1 control; a v1 control whose
    reproduction is not exact stops the pilot before any evaluation and before v2 (nothing is trained)."""
    import contextlib
    import io

    calls: List[str] = []
    evaluated: List[Any] = []

    def fake(**kw: Any) -> Dict[str, Any]:
        calls.append(Path(kw["run_dir"]).name)
        Path(kw["run_dir"]).mkdir(parents=True)
        return {"exit_code": 0, "stop_reason": None, "monitor": {"max_battleship_processes": 10}}

    saved = (kr.verify_run, kr.control_reproduction)
    d = s.dir("unit_pilot_gating")
    out: Dict[str, Any] = {}
    try:
        with _Root(d / "root"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = kr.main(["pilot", "--dry-run", "--arm", "v2", "--skip-resource-gate"])
            check(rc == kr.EXIT_FAILED and "v2 refused" in buf.getvalue(), f"v2 alone not refused: {rc}")
            check(not km.pilot_root().exists(), "a pilot dry run created something")
            kr.LAUNCHER = fake
            kr.EVALUATE_FN = lambda *a, **k: evaluated.append(a) or {}
            kr.verify_run = lambda *a, **k: {"ok": True, "problems": []}
            kr.control_reproduction = lambda *a, **k: {"ok": False, "problems": ["synthetic digest mismatch"]}
            rc = kr.main(["pilot", "--skip-resource-gate"])
            state = kr.load_state()
            check(rc == kr.EXIT_FAILED and calls == ["m7g_pilot_s0_v1"] and not evaluated,
                  f"a failed control did not stop the pilot: {rc} {calls} {len(evaluated)}")
            check(state["pilot"]["control_reproduction"]["ok"] is False
                  and not state["pilot"]["m7g_pilot_s0_v1"].get("passed")
                  and (km.pilot_root() / "pilot_record.json").is_file() and not state.get("evaluations"),
                  "control failure record")
            rc = kr.main(["pilot", "--skip-resource-gate", "--arm", "v2"])
            check(rc == kr.EXIT_FAILED and calls == ["m7g_pilot_s0_v1"], f"v2 launched after a failed control: {calls}")
            out = {"launched": calls, "v2_refusal": kr.pilot_v2_gate(state["pilot"])}
    finally:
        kr.verify_run, kr.control_reproduction = saved
    return out


def unit_checkpoint_provenance(s: Suite) -> Dict[str, Any]:
    d = s.dir("unit_checkpoint_provenance")
    out: Dict[str, Any] = {}
    with _Root(d / "root"):
        man = kr.load_manifest(freeze=False)        # the current-tree manifest seeded into the temporary root
        state = kr.load_state()
        for arm in ("v1", "v2"):
            spec = km.run_by_name(f"m7g_s0_{arm}")
            exp = km.load_run(spec)
            ck = _synthetic_checkpoint(spec, t=0)
            check(kr.checkpoint_provenance(ck, spec, exp, 0, man, state) == [], f"{arm}: clean set refused")
            wrong = {"point": kr.checkpoint_provenance(ck, spec, exp, 307_200, man, state),
                     "arm": kr.checkpoint_provenance(ck, km.run_by_name(f"m7g_s0_{'v2' if arm == 'v1' else 'v1'}"),
                                                     km.load_run(km.run_by_name(f"m7g_s0_{'v2' if arm == 'v1' else 'v1'}")),
                                                     0, man, state)}
            ck2 = _synthetic_checkpoint(km.run_by_name(f"m7g_s1_{arm}"), t=0)
            wrong["seed"] = kr.checkpoint_provenance(ck2, spec, exp, 0, man, state)
            meta = km.read_json(ck / "checkpoint.json")
            for field, val in (("run_id", "someone_else"), ("executable", {"sha256": "0" * 64})):
                m2 = dict(meta, **{field: val})
                (ck / "checkpoint.json").write_text(json.dumps(m2), encoding="utf-8")
                wrong[field] = kr.checkpoint_provenance(ck, spec, exp, 0, man, state)
            (ck / "checkpoint.json").write_text(json.dumps(meta), encoding="utf-8")
            for k, v in wrong.items():
                check(bool(v), f"{arm}: wrong {k} accepted")
            out[arm] = {k: v[0][:90] for k, v in wrong.items()}
        hist = REPO_ROOT / "runs" / "m7e" / "m7e_s0_v2" / "final"
        if (hist / "checkpoint.json").is_file():
            spec = km.run_by_name("m7g_s0_v1")
            p = kr.checkpoint_provenance(hist, spec, km.load_run(spec), km.TOTAL_TRANSITIONS, man, state)
            check(any("run_id" in x for x in p) and any("executable" in x for x in p), f"historical: {p}")
            out["historical_m7e"] = p
    return out


def _rows(n: int, targets: int, *, mode: str, cross: bool = False) -> List[Dict[str, Any]]:
    ids = list(range(targets))
    return [{"episode_id": f"{mode}{i}", "cleared": False, "native_action_digest": f"{mode}{targets}{i}",
             "targets_broken": targets, "end_reason": "horizon", "artifact_dir": None,
             "eval_metrics": {"ok": True, "first_left_entry": {"consumed_tick": 900} if cross and i == 0 else None,
                              "broken_ids": ids, "seven_or_more_targets": targets >= 7,
                              "moving_target_broken": 2 in ids}} for i in range(n)]


def _synthetic_tree(targets: Dict[Tuple[int, str], int]) -> Dict[str, Any]:
    state = kr.load_state()
    for spec in km.matrix():
        t = targets[(spec.seed, spec.arm)]
        for mode in ("stochastic", "deterministic"):
            p = spec.eval_dir / "final" / mode / "evaluation.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            km.write_json(p, {"episodes": _rows(100, t, mode=mode)})
        state["runs"][spec.name] = {"status": "verified", "max_battleship_processes": 10}
    state["pilot"] = {"control_reproduction": {"ok": True}}
    kr.save_state(state)
    return state


def unit_analysis(s: Suite) -> Dict[str, Any]:
    import m7g_k_analysis as ka

    check(ka.self_test() == 0, "decision-rule self-test failed")
    d = s.dir("unit_analysis")
    out: Dict[str, Any] = {}
    with _Root(d / "better"):
        state = _synthetic_tree({(s_, a): (3 if a == "v1" else 4) for s_ in (0, 1, 2) for a in ("v1", "v2")})
        rep = ka.build_report(state, include_extension=False)
        check(rep["decision"]["gate"] == 5 and rep["decision"]["branch"] == "a_targets_v2", f"{rep['decision']}")
        check(kr.cmd_analyze(_args("analyze")) == kr.EXIT_OK and kr.cmd_analyze(_args("analyze")) == kr.EXIT_USAGE,
              "a decision is recorded once and never re-decided")
        out["better"] = kr.load_state()["decisions"]["n3"]
    with _Root(d / "disagree"):
        _synthetic_tree({(0, "v1"): 4, (0, "v2"): 5, (1, "v1"): 4, (1, "v2"): 3, (2, "v1"): 4, (2, "v2"): 4})
        check(kr.cmd_analyze(_args("analyze")) == kr.EXIT_OK, "analyze")
        dec = kr.load_state()["decisions"]["n3"]
        check(dec["gate"] == 6 and dec["extension_required"], f"{dec}")
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = kr.cmd_train(_args("train", "--dry-run", "--extension", "--skip-resource-gate"))
        text = buf.getvalue()
        plan = json.loads(text[: text.rindex("}") + 1])["plan"]
        check(rc == kr.EXIT_OK and [p["run"] for p in plan] == ["m7g_s3_v1", "m7g_s3_v2", "m7g_s4_v2", "m7g_s4_v1"],
              f"extension plan {plan}")
        out["disagree"] = dec
    with _Root(d / "integrity"):
        state = _synthetic_tree({(s_, a): 4 for s_ in (0, 1, 2) for a in ("v1", "v2")})
        spec = km.run_by_name("m7g_s1_v2")
        p = spec.eval_dir / "final" / "stochastic" / "evaluation.json"
        rows = km.read_json(p)["episodes"]
        rows[0].update(cleared=True, completion_time_passed=446, completion_input_tick=447, targets_broken=10)
        km.write_json(p, {"episodes": rows})
        rep = ka.build_report(state, include_extension=False)
        check(rep["decision"]["gate"] == 0 and any("re-validation" in x for x in rep["decision"]["problems"]),
              f"an unverified clear must be gate 0: {rep['decision']}")
        km.write_json(p, {"episodes": rows[:99]})
        rep = ka.build_report(state, include_extension=False)
        check(rep["decision"]["gate"] == 0, "a missing episode must be gate 0")
        out["integrity"] = rep["decision"]["problems"][:2]
    return out


def unit_census(s: Suite) -> Dict[str, Any]:
    d = s.dir("unit_census")
    with _Root(d / "root"):
        spec = km.run_by_name("m7g_s0_v1")
        f = spec.eval_dir / "final" / "evaluation_summary.json"
        f.parent.mkdir(parents=True)
        km.write_json(f, {"modes": {m: {"episodes": [{}] * 100} for m in ("deterministic", "stochastic")}})
        c = kr.census(include_extension=False)
        check(not c["complete"] and c["plan"]["total_episodes"] == 6010 and c["executed_episodes"] == 200
              and len(c["missing"]) == 6 * 11 - 1 + 1, f"census {c['executed_episodes']} {len(c['missing'])}")
        ce = kr.census(include_extension=True)
        check(ce["plan"]["total_episodes"] == 9950 and len(ce["missing"]) == 10 * 11 - 1 + 1, "extension census")
    return {"planned": 6010, "planned_with_extension": 9950}


def unit_historical_verify(s: Suite) -> Dict[str, Any]:
    import m7d_run as dr
    import m7e_matrix as em

    run = REPO_ROOT / "runs" / "m7e" / "m7e_s0_v2"
    if not (run / "training_summary.json").is_file():
        return {"skipped": "runs/m7e not present"}
    spec = em.run_by_name("m7e_s0_v2")
    man = em.read_json(em.MANIFEST_DOC)["runs"]["m7e_s0_v2"]
    ver = dr.verify_training_run(run, em.load_run(spec), expected_initial=(
        man["expected_initial_policy_digest"], man["expected_initial_obs_rms_digest"]))
    check(ver["ok"], f"M7e seed 0 no longer verifies: {ver['problems'][:3]}")
    vn = dr.inspect_vecnormalize(run / "final" / "vecnormalize.pkl")
    check("norm_obs_keys" not in vn and vn["obs_rms_finite"], "v1 statistics report changed shape")
    return {"verified": True, "checkpoint_sets": len(ver["checks"]["checkpoint_sets"])}


def unit_isolation(s: Suite) -> Dict[str, Any]:
    pattern = re.compile(r"m7g_(fixture|capture|crossing)|FIXTURE_DIR|fixtures['\"\s,/\\()]*m7g|lower_precision|"
                         r"upper_moving_platform|crossing_fixture", re.IGNORECASE)
    mods = ["m7g_eval_metrics.py", "m7g_k_matrix.py", "m7g_k_run.py", "m7g_k_analysis.py", "m7_evaluation.py",
            "m7_trainer.py", "experiment_config.py", "btt_parallel.py", "m7d_run.py"]
    offenders = [m for m in mods if pattern.search((RL_DIR / m).read_text(encoding="utf-8"))]
    check(not offenders, f"modules reference the crossing fixtures: {offenders}")
    confs = sorted((RL_DIR / "configs" / "m7g").rglob("*.toml"))
    check(len(confs) == 12 and not [c.name for c in confs if pattern.search(c.read_text(encoding="utf-8"))],
          "profiles reference the fixtures")
    learn = [m for m in mods[:4] + [Path(__file__).name] if re.search(r"\.learn\(", (RL_DIR / m).read_text(encoding="utf-8"))]
    check(not learn, f"PPO learn() in {learn}")
    imp = re.compile(r"^\s*(from\s+m7g_eval_metrics\s+import|import\s+m7g_eval_metrics)", re.MULTILINE)
    importers = sorted(p.name for p in RL_DIR.glob("*.py") if imp.search(p.read_text(encoding="utf-8"))
                       and not p.name.startswith("m7g_"))
    check(importers == ["m7_evaluation.py"], f"the recorder is imported outside the evaluator: {importers}")
    return {"modules": len(mods), "profiles": len(confs)}


# -- game ------------------------------------------------------------------------------------------------------------------


def _fixture_actions(path: Path) -> Tuple[List[np.ndarray], Dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))    # validation evidence only
    return [np.array(a, dtype=np.int64) for a in doc["sequence"]["track1"]], doc["evidence"]


def _worker(root: Path, arm: str, horizon: int, *, standby: bool) -> Any:
    import m7g_eval_metrics as em
    import m7g_obs as mo
    from btt_parallel import RunCoordinator, WorkerFactory, WorkerSpec, initial_coordination_state
    from m7_runtime import prepare_worker_runtime

    coord = root / "coordination"
    RunCoordinator.create(coord, initial_coordination_state("m7g_k_metrics", "test", None))
    wd = root / "w00"
    prepare_worker_runtime(wd / "runtime", EXE)
    flags = {**M6, **DIAG, **(SPATIAL if arm == "v2" else {})}
    spec = WorkerSpec(rank=0, run_id="m7g_k_metrics", role="test", worker_dir=str(wd.resolve()),
                      coordination_dir=str(coord.resolve()), executable=str(EXE), horizon=horizon,
                      extra_env=tuple(flags.items()), standby_preboot=standby, standby_count=1 if standby else 0,
                      preserve_all=True)
    env = em.EvalMetricsWorkerFactory(mo.M7gWorkerFactory(spec) if arm == "v2" else WorkerFactory(spec))()
    env.env.keep_trace = True
    return env


def _play(env: Any, actions: Sequence[Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    env.reset()
    info: Dict[str, Any] = {}
    for a in actions:
        _o, _r, term, trunc, info = env.step(a)
        if term or trunc:
            break
    summary = info.get("m7_episode") or {}
    check(summary.get("eval_metrics") is not None, f"no eval_metrics in the episode summary ({list(summary)})")
    rec = env.env
    return summary, dict(rec.initial_reply), list(rec.trace)


def game_metrics_fixtures(s: Suite) -> Dict[str, Any]:
    import m7f_targets as mt
    import m7g_fixture as mf

    geo = mf.decode_stage_geometry()
    d = s.dir("game_metrics_fixtures")
    out: Dict[str, Any] = {}
    for which, path in FIXTURES.items():
        actions, evidence = _fixture_actions(path)
        horizon = 3600 if which == "lower" else len(actions)
        for arm in ("v1", "v2"):
            standby = which == "lower" and arm == "v2"
            env = _worker(d / f"{which}_{arm}", arm, horizon, standby=standby)
            try:
                episodes = [_play(env, actions) for _ in range(2 if standby else 1)]
            finally:
                env.close()
            summary, initial, trace = episodes[0]
            m = summary["eval_metrics"]
            ref = mt.check_trace(initial, trace)
            ev = mf.crossing_evidence(geo, initial, trace)
            breaks = [(b["target_id"], b["consumed_tick"], b["input_tick"]) for b in m["target_breaks"]]
            want = [(b["target_id"], b["consumed_tick"], b["input_tick"]) for b in evidence["targets"]["breaks"]]
            check(m["ok"] and m["target_diag"]["ok"], f"{which}/{arm}: record not ok {m['consistency']} "
                                                      f"{m['target_diag']['problems']}")
            check(m["first_left_entry"] == evidence["first_left_entry"] == ev["first_left_entry"],
                  f"{which}/{arm}: left entry {m['first_left_entry']} vs fixture {evidence['first_left_entry']}")
            check(breaks == want == [(e["target_id"], e["consumed_tick"], e["input_tick"]) for e in ref.events],
                  f"{which}/{arm}: breaks {breaks} vs fixture {want}")
            check(m["left_targets_broken"] == evidence["targets"]["left_targets_broken"]
                  and m["broken_ids"] == evidence["targets"]["broken_ids"], f"{which}/{arm}: ids")
            check(m["first_break_tick"] == {str(t): c for t, c, _ in want} and m["seven_or_more_targets"] is False
                  and m["moving_target_broken"] is False and m["cleared_native"] is False, f"{which}/{arm}: flags")
            check(m["steps_recorded"] == len(trace) == evidence["terminal"]["submitted"]
                  and m["last_consumed_tick"] == evidence["terminal"]["last_consumed_tick"], f"{which}/{arm}: length")
            want_end = ("fall", "native_failure") if which == "lower" else ("horizon", None)
            check((m["end_reason"], m["termination_reason"]) == want_end, f"{which}/{arm}: end {m['end_reason']}")
            if standby:
                s2 = episodes[1][0]
                check(s2["startup_mode"] == "standby_promoted" and episodes[0][0]["startup_mode"] == "cold_start"
                      and s2["eval_metrics"] == m, f"{which}/{arm}: cold vs promoted metrics differ")
            out[f"{which}_{arm}"] = {"left_entry_tick": m["first_left_entry"]["consumed_tick"], "breaks": breaks,
                                     "end": m["end_reason"], "episodes": len(episodes)}
    check(_no_battleship(), "leftover BattleShip")
    return out


def _tas_stack(root: Path) -> Tuple[Any, Any, Any]:
    """M7 base env + reward + recorder + tracker (the worker stack below Track 1) with the metrics recorder."""
    import m7g_eval_metrics as em
    from battleship_process import LaunchConfig
    from btt_parallel import (M7BattleShipBTTEnv, M7EpisodeTracker, M7RewardWrapper, RunCoordinator,
                              initial_coordination_state)
    from btt_rewards import REWARD_V1
    from m7_runtime import PortCandidates, prepare_worker_runtime
    from run_artifacts import EpisodeRecordingWrapper, PositionDeltaDetector

    prepare_worker_runtime(root / "runtime", EXE)
    launch = LaunchConfig(executable=EXE, working_dir=root / "runtime", run_root=root / "episodes",
                          extra_env={**M6, **DIAG})
    base = M7BattleShipBTTEnv(launch, max_episode_steps=3600, rank=0, ports=PortCandidates(0))
    tracker = M7EpisodeTracker(run_id="m7g_k_tas", role="test", rank=0,
                               coordinator=RunCoordinator.create(root / "coord", initial_coordination_state(
                                   "m7g_k_tas", "test", None)),
                               artifact_root=root / "artifacts", ledger_path=root / "ledger.jsonl", env=base,
                               reward=REWARD_V1, preserve_all=True)
    rewarded = M7RewardWrapper(base, REWARD_V1, tracker)
    rec = EpisodeRecordingWrapper(rewarded, root / "artifacts", detectors=[PositionDeltaDetector(300.0)],
                                  labels=tracker.labels_for_new_episode, on_episode_end=tracker.on_episode_end,
                                  targets_total=10)
    return base, tracker, em.EvalMetricsWrapper(rec, base=base, tracker=tracker, keep_trace=True)


def game_metrics_tas_clear(s: Suite) -> Dict[str, Any]:
    import m7f_targets as mt
    import m7g_fixture as mf
    from battleship_env import native_to_action
    from btti_replay import read_btti_rows

    d = s.dir("game_metrics_tas_clear")
    rows = read_btti_rows(str(TAS))
    base, tracker, env = _tas_stack(d)
    try:
        env.reset()
        n = 0
        term = trunc = False
        for r in rows:
            _o, _rw, term, trunc, _info = env.step(native_to_action(r.buttons, r.stick_x, r.stick_y))
            n += 1
            if term or trunc:
                break
        summary = tracker.pop_summary()
    finally:
        env.close()
    m = summary["eval_metrics"]
    check(term and n == 447 and len(rows) - n == 21, f"TAS: {n} actions, term {term}")
    check(m["ok"] and m["cleared_native"] and (m["completion_time_passed"], m["completion_input_tick"]) == (446, 447)
          and m["last_consumed_tick"] == 446 and m["consistency"]["completion_input_tick_is_last_consumed_plus_1"]
          and m["consistency"]["completion_clocks_equal_final_break"], f"clear clocks {m}")
    check(m["targets_broken"] == 10 and sorted(m["broken_ids"]) == list(range(10)) and m["seven_or_more_targets"]
          and m["moving_target_broken"] and m["clear_verified"] is None, "targets")
    ev = mf.crossing_evidence(mf.decode_stage_geometry(), env.initial_reply, env.trace)
    ref = mt.check_trace(env.initial_reply, env.trace)
    check(m["first_left_entry"]["consumed_tick"] == 359 and m["first_left_entry"] == ev["first_left_entry"],
          f"TAS left entry {m['first_left_entry']}")
    check([(b["target_id"], b["consumed_tick"]) for b in m["target_breaks"]]
          == [(e["target_id"], e["consumed_tick"]) for e in ref.events], "breaks vs check_trace")
    check(_no_battleship(), "leftover BattleShip")
    art = REPO_ROOT / summary["artifact_dir"] if not Path(summary["artifact_dir"]).is_absolute() else Path(summary["artifact_dir"])
    (s.root / "tas_clear_episode.json").write_text(json.dumps({"summary": summary, "artifact": str(art)}, default=str),
                                                    encoding="utf-8")
    return {"actions": n, "clocks": [446, 447], "left_entry_tick": 359, "moving_target_break_tick":
            m["moving_target_break_tick"], "artifact": ec.repo_relative(art)}


def game_clear_verification(s: Suite) -> Dict[str, Any]:
    src = s.root / "tas_clear_episode.json"
    if not src.is_file():
        game_metrics_tas_clear(s)
    rec = json.loads(src.read_text(encoding="utf-8"))
    summary, art = rec["summary"], Path(rec["artifact"])
    d = s.dir("game_clear_verification")
    out: Dict[str, Any] = {}
    for name, collapsed in (("genuine", False), ("collapsed_clock", True)):
        a = d / name / "artifact"
        shutil.copytree(art, a)
        row = {"episode_id": summary["episode_id"], "cleared": True, "native_action_digest": summary["native_action_digest"],
               "completion_time_passed": 446, "completion_input_tick": 446 if collapsed else 447,
               "targets_broken": 10, "artifact_dir": str(a)}
        if collapsed:
            md = json.loads((a / "metadata.json").read_text(encoding="utf-8"))
            md["labels"]["completion_input_tick"] = 446
            (a / "metadata.json").write_text(json.dumps(md), encoding="utf-8")
        label = d / name / "final"
        (label / "stochastic").mkdir(parents=True)
        km.write_json(label / "stochastic" / "evaluation.json", {"episodes": [row, dict(row, episode_id="dup")]})
        doc = kr.verify_clears_in(label, d / name / "clears", executable=EXE, extra_env=M6)
        out[name] = {"candidates": doc["candidates"], "verified": doc["verified"],
                     "recorded": doc["clears"][0]["recorded_clocks"], "replayed": doc["clears"][0]["replayed_clocks"]}
        check(doc["candidates"] == 1, f"{name}: duplicates must be verified once")
        if collapsed:
            check(doc["verified"] == 0 and doc["clears"][0]["replayed_clocks"] == [446, 447], f"{name}: {out[name]}")
        else:
            check(doc["verified"] == 1 and doc["clears"][0]["replayed_clocks"] == [446, 447]
                  and (d / name / "clears" / "clear_verification.json").is_file(), f"{name}: {out[name]}")
    check(_no_battleship(), "leftover BattleShip")
    return out


def game_eval_end_to_end(s: Suite) -> Dict[str, Any]:
    import torch

    from m7_runtime import install_kill_on_close_job

    torch.set_num_threads(1)
    install_kill_on_close_job()
    d = s.dir("game_eval_end_to_end")
    out: Dict[str, Any] = {}
    with _Root(d / "root"):
        man = kr.load_manifest(freeze=False)        # the current-tree manifest seeded into the temporary root
        state = kr.load_state()
        for arm in ("v1", "v2"):
            spec = km.run_by_name(f"m7g_s0_{arm}")
            exp = km.load_run(spec)
            _synthetic_checkpoint(spec, t=0)
            plan = dict(km.evaluation_plan(spec, exp)[0], deterministic_episodes=1, stochastic_episodes=3)
            r = kr.evaluate_run_label(state, spec, exp, plan, man)
            check(r["ran"] and not r["provenance_problems"] and r["verification"]["ok"],
                  f"{arm}: {r['provenance_problems']} {(r.get('verification') or {}).get('problems')}")
            summ = km.read_json(spec.eval_dir / "initial" / "evaluation_summary.json")
            rows = [e for m in summ["modes"].values() for e in m["episodes"]]
            check(len(rows) == 4 and all((e.get("eval_metrics") or {}).get("ok") for e in rows)
                  and summ["extra_env"] == {**M6, **DIAG, **(SPATIAL if arm == "v2" else {})}, f"{arm}: rows / flags")
            again = kr.evaluate_run_label(state, spec, exp, plan, man)          # atomic: a complete label is reused
            check(again["ran"] and again["verification"]["ok"], "re-run of a complete label")
            out[arm] = {"episodes": len(rows), "targets": [e["targets_broken"] for e in rows],
                        "left_entries": sum(1 for e in rows if e["eval_metrics"]["first_left_entry"])}
        rb = kr.evaluate_random_baseline(state, episodes=3)
        check(state["evaluations"]["random_baseline"]["verification"]["ok"]
              and len(rb["modes"]["random"]["episodes"]) == 3, "random baseline metrics")
        out["random"] = [e["targets_broken"] for e in rb["modes"]["random"]["episodes"]]
    check(_no_battleship(), "leftover BattleShip")
    return out


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_recorder": unit_recorder, "unit_recorder_wiring": unit_recorder_wiring, "unit_manifest": unit_manifest,
    "unit_drift_detection": unit_drift_detection, "unit_resource_gate": unit_resource_gate,
    "unit_dry_runs": unit_dry_runs, "unit_partial_and_resume": unit_partial_and_resume,
    "unit_pilot_gating": unit_pilot_gating, "unit_checkpoint_provenance": unit_checkpoint_provenance, "unit_analysis": unit_analysis,
    "unit_census": unit_census, "unit_historical_verify": unit_historical_verify, "unit_isolation": unit_isolation,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "game_metrics_fixtures": game_metrics_fixtures, "game_metrics_tas_clear": game_metrics_tas_clear,
    "game_clear_verification": game_clear_verification, "game_eval_end_to_end": game_eval_end_to_end,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    names: List[str] = []
    for c in args.cases or list(ALL_CASES):
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        ap.error(f"unknown cases {unknown}")
    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / "_tests" / f"m7g_k_campaign_{utc}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    leaked = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
    if leaked:
        raise SystemExit(f"SSB64_* variables in the environment would leak into every child: {leaked}")
    if any(n in GAME_CASES for n in names):
        from m7_runtime import install_kill_on_close_job

        if not _no_battleship():
            raise SystemExit("BattleShip already running; the game cases need a quiet machine")
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
                             "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-3000:]}
        finally:
            km.configure_root(None)
            kr.LAUNCHER = kr.EVALUATE_FN = kr.REPLAY_FN = None
        print(f"{results[name]['status']}  {name}  ({results[name]['seconds']} s)"
              + (f"  {results[name].get('error')}" if results[name]["status"] != "PASS" else ""), flush=True)
    ok = all(r["status"] == "PASS" for r in results.values())
    with open(root / "m7g_k_campaign_tests_results.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump({"schema": "battleship_m7g_k_campaign_tests_v1", "utc": utc, "results": results, "ok": ok}, fp,
                  indent=1, default=str)
        fp.write("\n")
    print(f"m7g_k_campaign_tests: {sum(r['status'] == 'PASS' for r in results.values())}/{len(results)} PASS -> {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
