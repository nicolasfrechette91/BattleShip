"""M7h campaign readiness tests: no training, no learn(), no optimizer step. Launch paths use a stand-in launcher,
evaluations synthetic records, checkpoints untrained sets built with the trainer's own helpers; the only game case
(game_provisional_label) launches one BattleShip process for a short recorded prefix phase.

Unit cases (no game):
    unit_prefix_rows_rule          the one boundary rule (mc.prefix_rows) on every label kind and every inconsistency
    unit_manifest_profiles         manifest ok and current; F = Phase K v1 + exactly the registered curriculum keys; C =
                                   Phase K v1; fresh untrained F models == the control's; census; limits; directories
    unit_rule_registered           the rule JSON holds the proposal's thresholds; decide() self-test; manifest pins it
    unit_historical_control        arm C identity and rule inputs == the registered R3 values; every reuse condition
                                   (missing / failed / stale / other-executable record, changed control files) refused
    unit_resource_gates            launch: commit >= 10 AND physical >= 4 GiB, separately, inclusive, missing fails, the
                                   observed 3.2-3.5 GiB physical dip refused at launch; in run: commit only (a physical
                                   dip never changes the level; it is counted and reported); one real reading
    unit_dry_runs                  every launch / analysis path dry: control check required, stale / failed refused,
                                   gate refusal, order, extension, resume, retrain, evaluate, census, status; nothing
                                   created; the frozen manifest is never rebuilt
    unit_launch_stop_restart       stand-in launcher: F0 -> F1 -> F2 in the root, the gate before every launch, manifest
                                   frozen at the first launch; a stopped run is kept in _partial and restarted from
                                   scratch; a crashed run needs --restart-partial (moved aside intact); gate refusal
    unit_checkpoint_identity       untrained F sets: clean provenance at t = 0 and t > 0 (with the archive); wrong run,
                                   point, seed, executable, missing archive, interrupted set, C set with extra files
                                   refused; ckpt_000000000 digests == the manifest's fresh-model digests
    unit_curriculum_verification   the E4 run (copy): all views agree; tampered label L, row L, selection-log L, removed
                                   label, foreign archive source, broken count all detected
    unit_eval_tick0                tick-0 evaluation check on real evaluation artifacts (copy) and tampered copies
    unit_eval_tick0_excess         amendment 1: real ordinary and excess labels accepted (3 Phase K + the M7h curve
                                   label); forged / missing excess records, removed / unrecorded / aborted / misplaced
                                   excess artifacts and tick-0 violations on excess artifacts refused
    unit_amendment                 the post-training drift gate honours only a registered amendment of the
                                   verification files; code / profile / executable / HEAD / submodule / rule drift and
                                   a changed amendment refused; train and control-check stay strict
    unit_analysis_end_to_end       synthetic F evaluation trees + the real historical control: not ready -> refused,
                                   nothing recorded; gate 5a; gate 3 unlocks exactly C3, F3, F4, C4; gate 0 on a
                                   tick-0 violation; a decision is recorded once
    unit_left_entries              left-region trajectories kept by the parent; the section-4 replay selection (first
                                   genuine entry + up to 5), its pass / fail facts and g (stubbed replays: no real
                                   crossing exists outside the fixtures, which M7h never reads)
    unit_isolation                 no fixture / TAS / capture reference in any M7h module or profile; archived trees
                                   (runs/m7g_k bookkeeping, runs/m7h/_gate) unchanged by the whole suite
Game case:
    game_provisional_label         a real worker: an archived prefix with a corrupted end observation is refused, the
                                   written artifact carries archive_prefix_in_progress and L = rows; an exact prefix
                                   then policy steps -> archive_prefix, rows [0, L) prefix

    python rl/m7h_campaign_tests.py [unit|game|<case> ...] [--root runs/m7h/_readiness/campaign_tests_<utc>]
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import numpy as np  # noqa: E402

import m7h_analysis as ma  # noqa: E402
import m7h_campaign as cm  # noqa: E402
import m7h_curriculum as mc  # noqa: E402
import m7h_guard as g  # noqa: E402
import m7h_matrix as hm  # noqa: E402
import m7h_verify as mv  # noqa: E402

REPO_ROOT = RL_DIR.parent
GATE = REPO_ROOT / "runs" / "m7h" / "_gate"
E4 = GATE / "e4" / "m7h_e4_on_s0"
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
M7D_INITIAL = {0: "68155f41065d243f", 1: "1dd753aeda5f", 2: "9fa632c6ffeb"}
# evaluation / worker copies: rows and artifacts only (worker runtime folders hold junctions into build-us)
NO_RUNTIME = shutil.ignore_patterns("runtime", "runtime_gens", "episodes")


class Failure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Failure(msg)


class Suite:
    def __init__(self, root: Path):
        self.root = root

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d


_MANIFEST: Dict[str, Any] = {}


def manifest() -> Dict[str, Any]:
    """The manifest of the tree under test (hm.build_manifest on the default root; read only there), once."""
    if not _MANIFEST:
        hm.configure_root(None)
        _MANIFEST.update(hm.build_manifest())
    return copy.deepcopy(_MANIFEST)


class Root:
    """The campaign tree redirected to a temporary root (always restored, stand-ins cleared)."""

    def __init__(self, root: Path, *, frozen: bool = True, control: Optional[bool] = True):
        self.root, self.frozen, self.control = root, frozen, control
        self.saved: Dict[str, Any] = {}

    def __enter__(self) -> Path:
        man = manifest()
        hm.configure_root(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.frozen:
            hm.write_json(cm.frozen_manifest_path(), man)
        if self.control is not None:
            write_control_record(man, ok=self.control)
        self.saved = {"verify_run": cm.verify_run, "doc": hm.MANIFEST_DOC}
        return self.root

    def __exit__(self, *exc: Any) -> None:
        hm.configure_root(None)
        cm.LAUNCHER = cm.EVALUATE_FN = cm.CONTROL_CHECK_FN = cm.GATE_FN = cm.REPLAY_FN = None
        cm.verify_run = self.saved["verify_run"]
        hm.MANIFEST_DOC = self.saved["doc"]


def write_control_record(man: Mapping[str, Any], *, ok: bool = True, code: Optional[str] = None) -> None:
    hm.write_json(cm.control_record_path(), {
        "schema": "m7h_control_check_v1", "utc": cm.utc_now(), "code_sha256": code or man["code"]["sha256"],
        "executable_sha256": man["executable"]["sha256"], "revisions": man["revisions"], "ok": ok,
        "problems": [] if ok else ["synthetic failure"], "out": "synthetic"})


def run_cli(*argv: str) -> Tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cm.main(list(argv))
    return rc, buf.getvalue()


def report_of(text: str) -> Dict[str, Any]:
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def tree(root: Path, *, skip: Tuple[str, ...] = ()) -> Dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and p.relative_to(root).as_posix() not in skip}


def reading(**over: Any) -> Dict[str, Any]:
    base = {"avail_commit_gib": 16.0, "avail_phys_gib": 5.3, "disk_free_gib": 200.0, "cpu_mean_pct": 5.0,
            "battleship_pids": [], "listeners": [], "ssb64_environment_variables": []}
    base.update(over)
    return base


# -- unit ---------------------------------------------------------------------------------------------------------------


def unit_prefix_rows_rule(s: Suite) -> Dict[str, Any]:
    L = mc.START_LABEL
    ok_cases = [({}, 7, (0, mc.START_TICK0)),
                ({L: {"kind": mc.START_PREFIX, "prefix_length": 5}}, 9, (5, mc.START_PREFIX)),
                ({L: {"kind": mc.START_PREFIX, "prefix_length": 9}}, 9, (9, mc.START_PREFIX)),     # aborted at L
                ({L: {"kind": mc.START_PREFIX_IN_PROGRESS, "prefix_length_planned": 40}}, 12,
                 (12, mc.START_PREFIX_IN_PROGRESS)),
                ({L: {"kind": mc.START_PREFIX_FAILED, "prefix_length_planned": 40, "rows_before_failure": 12}}, 12,
                 (12, mc.START_PREFIX_FAILED))]
    for labels, rows, want in ok_cases:
        check(mc.prefix_rows(labels, rows) == want, f"{labels} {rows} -> {mc.prefix_rows(labels, rows)}")
    bad = [({L: {"kind": mc.START_PREFIX, "prefix_length": 10}}, 9, "L > rows"),
           ({L: {"kind": mc.START_PREFIX, "prefix_length": 0}}, 9, "L = 0 with a label"),
           ({L: {"kind": mc.START_PREFIX, "prefix_length": 3001}}, 4000, "L > 3000"),
           ({L: {"kind": mc.START_PREFIX_IN_PROGRESS, "prefix_length_planned": 5}}, 6, "rows > planned"),
           ({L: {"kind": mc.START_PREFIX_FAILED, "prefix_length_planned": 40, "rows_before_failure": 11}}, 12,
            "rows != rows before failure"),
           ({L: {"kind": "tick0"}}, 3, "unknown kind")]
    refused = []
    for labels, rows, why in bad:
        try:
            mc.prefix_rows(labels, rows)
            raise Failure(f"accepted: {why}")
        except mc.CurriculumError:
            refused.append(why)
    # the worker marks the phase before the first prefix row and the rule lives in one place
    src = (RL_DIR / "m7h_worker.py").read_text(encoding="utf-8")
    i_label, i_loop = src.index("mc.START_PREFIX_IN_PROGRESS"), src.index("for i, a in enumerate(prefix):")
    check(src.index("self._require_fresh()") < i_label < i_loop, "the provisional label is not written before the loop")
    readers = [p.name for p in RL_DIR.glob("m7h_*.py") if "prefix_length" in p.read_text(encoding="utf-8")
               and "labels" in p.read_text(encoding="utf-8") and p.name not in ("m7h_curriculum.py", "m7h_worker.py",
                                                                                "m7h_verify.py", "m7h_run.py",
                                                                                "m7h_campaign.py", "m7h_tests.py",
                                                                                "m7h_campaign_tests.py")]
    check(not readers, f"other modules derive the boundary from labels themselves: {readers}")
    return {"accepted": len(ok_cases), "refused": refused}


def unit_manifest_profiles(s: Suite) -> Dict[str, Any]:
    man = manifest()
    check(man["ok"] and not man["problems"], f"manifest problems {man['problems']}")
    check(not hm.manifest_drift(man), f"drift {hm.manifest_drift(man)}")
    runs = man["runs"]
    check(sorted(runs) == sorted(f"m7h_{a}_s{k}" for a in "fc" for k in range(5)), f"runs {sorted(runs)}")
    for name, r in runs.items():
        check(all(r["checks"].values()), f"{name}: {[k for k, v in r['checks'].items() if not v]}")
        check(r["phase_k_proof"]["ok"], f"{name}: {r['phase_k_proof']}")
        if name.startswith("m7h_f"):
            check(r["curriculum"] == mc.REGISTERED and r["phase_k_proof"]["compatibility_differences"] ==
                  sorted(f"curriculum.{k}" for k in mc.REGISTERED), f"{name}: curriculum keys")
        else:
            check(r["curriculum"] is None and r["phase_k_proof"]["same_semantic_fingerprint"], f"{name}: C identity")
    for k in range(5):
        f, c = runs[f"m7h_f_s{k}"], runs[f"m7h_c_s{k}"]
        check(f["expected_initial_policy_digest"] == c["expected_initial_policy_digest"], f"seed {k}: fresh F != C")
    for k, prefix in M7D_INITIAL.items():
        check(runs[f"m7h_f_s{k}"]["expected_initial_policy_digest"].startswith(prefix), f"seed {k}: not the M7d digest")
    ep = man["evaluation_protocol"]
    check((ep["census"]["episodes"], ep["census_with_extension"]["episodes"],
           ep["census_control_retrained"]["episodes"]) == (2955, 6895, 5910), "census")
    plan = ep["plan"]["m7h_f_s0"]
    check(len(plan) == 11 and all(p["starts"] == "tick0_only" and p["eval_metrics"] and p["extra_env"] ==
                                  {**hm.M6_FLAGS, **hm.EVAL_METRICS_FLAG} for p in plan), "evaluation plan")
    check([p["label"] for p in plan][0] == "initial" and plan[-1]["label"] == "final"
          and (plan[0]["deterministic_episodes"], plan[0]["stochastic_episodes"], plan[1]["deterministic_episodes"],
               plan[1]["stochastic_episodes"]) == (100, 100, 5, 60), "episodes per label")
    check(man["order"] == {"historical_control": ["m7h_f_s0", "m7h_f_s1", "m7h_f_s2"],
                           "control_retrained": ["m7h_c_s0", "m7h_f_s0", "m7h_f_s1", "m7h_c_s1", "m7h_c_s2", "m7h_f_s2"],
                           "extension": ["m7h_c_s3", "m7h_f_s3", "m7h_f_s4", "m7h_c_s4"]}, f"order {man['order']}")
    check(man["limits"]["runs_planned"] == 3 and man["limits"]["transitions_planned"] == 9_216_000
          and man["limits"]["runs_max"] == 10, "limits")
    rs = man["registered_settings"]
    check((rs["launch_gate"]["available_commit_gib_min"], rs["launch_gate"]["available_physical_gib_min"]) == (10.0, 4.0)
          and (rs["in_run_memory_policy"]["warn_gib"], rs["in_run_memory_policy"]["stop_gib"],
               rs["in_run_memory_policy"]["emergency_gib"]) == (4.0, 3.0, 1.0)
          and rs["curriculum"]["tick0_probability"] == 0.5 and rs["curriculum"]["max_prefix_ticks"] == 3000
          and rs["curriculum"]["pre_fall_exclusion_ticks"] == 60 and rs["atomic_checkpoint_sets"] is True,
          "registered settings")
    d = man["directory_plan"]
    check(d["ok"] and d["root"].replace("\\", "/") == "runs/m7h/campaign", f"directory plan {d['problems']}")
    code = man["code"]["per_file"]
    check("docs/rl_frontier_curriculum_m7h_decision_rule.json" in code and "rl/configs/m7h/m7h_f_s0.toml" in code
          and "rl/configs/m7h/gate/m7h_r1_s0.toml" in code and "rl/m7h_worker.py" in code, "code fingerprint coverage")
    return {"runs": len(runs), "code_sha256": man["code"]["sha256"][:16], "code_files": man["code"]["files"],
            "fresh_digests": {k: runs[f"m7h_f_s{k}"]["expected_initial_policy_digest"][:16] for k in range(3)}}


def unit_rule_registered(s: Suite) -> Dict[str, Any]:
    rule = ma.load_rule()
    check(ma.self_test(rule) == 0, "decision-rule self-test failed")
    n3 = {x["gate"]: x for x in rule["n3"]["gates"]}
    n5 = {x["gate"]: x for x in rule["n5"]["gates"]}
    check((n3[1]["clears_min"], n3[2]["crossings_min"], n3[4]["discovery_min"]) == (2, 2, 2), "n3 counts")
    check((n3[5]["targets_dbar_min"], n3[5]["targets_dbar_worse"], n3[5]["falls_phi_diff_max"]) == ("1/2", "-1/2", "1/10"),
          "n3 target thresholds")
    check(n3[3].get("extension_required") is True and rule["extension"]["order"] ==
          ["m7h_c_s3", "m7h_f_s3", "m7h_f_s4", "m7h_c_s4"], "extension")
    check((n5[1]["adopt_min"], n5[1]["delta_min"], n5[2]["adopt_min"], n5[2]["delta_min"], n5[3]["discovery_min"]) ==
          (3, "1/20", 3, "1/20", 3), "n5 thresholds")
    check(rule["known_control_values_n3"]["T_C"] == {"0": "472/100", "1": "475/100", "2": "427/100"}
          and rule["known_control_values_n3"]["Phi_C"] == "2/300", "known control values")
    check(manifest()["decision_rule"]["sha256"] == rule["_sha256"], "the manifest does not pin this rule")
    return {"rule_sha256": rule["_sha256"][:16]}


def unit_historical_control(s: Suite) -> Dict[str, Any]:
    man = manifest()
    out = {}
    for k in (0, 1, 2):
        h = hm.historical_identity(k)
        check(h["ok"], f"seed {k}: {h['problems']}")
        want = man["historical_control"]["seeds"][str(k)]
        check(all(h[x] == want[x] for x in ("final_checkpoint_json_sha256", "final_digests", "final_evaluation_sha256",
                                              "rule_inputs")), f"seed {k}: identity changed")
        out[k] = h["rule_inputs"]["T"]
    d = s.dir("unit_historical_control")
    with Root(d / "root", control=None):
        state = cm.load_state()
        p = cm.control_check_problems(man, state)
        check(len(p) == 1 and "has not run" in p[0], f"missing record: {p}")
        write_control_record(man, ok=False)
        check(any("FAILED" in x for x in cm.control_check_problems(man, state)), "failed record accepted")
        write_control_record(man, ok=True, code="0" * 64)
        check(any("re-run control-check" in x for x in cm.control_check_problems(man, state)), "stale record accepted")
        write_control_record(man, ok=True)
        m2 = copy.deepcopy(man)
        m2["executable"]["sha256"] = "1" * 64
        check(any("another executable" in x for x in cm.control_check_problems(m2, state)), "other executable accepted")
        m3 = copy.deepcopy(man)
        m3["historical_control"]["seeds"]["1"]["final_digests"] = ["x", "y"]
        check(any("seed 1 changed" in x for x in cm.control_check_problems(m3, state)), "changed control accepted")
        check(cm.control_check_problems(man, state) == [], "a valid record refused")
        check(cm.control_check_problems(man, {"control": {"mode": "retrained"}}) == [], "retrained branch")
    # the control-check command (stand-in R1-R3): a gate refusal records nothing; a pass binds to the manifest code;
    # a failed reproduction plus an explicit --retrain-control switches to the registered C0, F0, F1, C1, C2, F2 order
    with Root(d / "cmd", control=None):
        def refused(out: Path, seeds: Any) -> Dict[str, Any]:
            raise RuntimeError("launch gate refused: synthetic")

        cm.CONTROL_CHECK_FN = refused
        rc, _t = run_cli("control-check")
        check(rc == cm.EXIT_FAILED and not cm.control_record_path().exists(), "a gate refusal was recorded as a result")
        cm.CONTROL_CHECK_FN = lambda out, seeds: {"ok": True, "problems": [], "results": {}, "exit_codes": {}}
        rc, _t = run_cli("control-check")
        rec = hm.read_json(cm.control_record_path())
        check(rc == cm.EXIT_OK and rec["ok"] and rec["code_sha256"] == man["code"]["sha256"]
              and cm.control_check_problems(man, cm.load_state()) == [], "a passed control check")
        rc, _t = run_cli("train", "--retrain-control", "--dry-run", "--skip-resource-gate")
        check(rc == cm.EXIT_USAGE, "retrain accepted after a PASSED check")
        cm.CONTROL_CHECK_FN = lambda out, seeds: {"ok": False, "problems": ["r1_s0: digests differ (synthetic)"],
                                                  "results": {}, "exit_codes": {}}
        rc, _t = run_cli("control-check")
        check(rc == cm.EXIT_FAILED and not hm.read_json(cm.control_record_path())["ok"], "a failed check")
        rc, text = run_cli("train", "--dry-run", "--skip-resource-gate")
        check(rc == cm.EXIT_FAILED and "FAILED" in text, "the historical control reused after a failed check")
        calls: List[Dict[str, Any]] = []
        cm.LAUNCHER = _fake_ok(calls)
        cm.verify_run = lambda spec, exp, manifest: {"ok": True, "problems": []}
        rc, _t = run_cli("train", "--retrain-control", "--skip-resource-gate")
        st = cm.load_state()
        check(rc == cm.EXIT_OK and [c["run"] for c in calls] == ["m7h_c_s0", "m7h_f_s0", "m7h_f_s1", "m7h_c_s1",
                                                                 "m7h_c_s2", "m7h_f_s2"]
              and st["control"]["mode"] == "retrained" and all(c["curriculum"] is None for c in calls if "_c_" in c["run"]),
              f"retrain order {[c['run'] for c in calls]}")
    return {"T": out, "retrain_order": [c["run"] for c in calls]}


def unit_resource_gates(s: Suite) -> Dict[str, Any]:
    ev = g.evaluate_launch
    check(ev(reading())["ok"], "a good reading refused")
    check(ev(reading(avail_commit_gib=10.0, avail_phys_gib=4.0))["ok"], "the boundaries are inclusive")
    cases = {"commit_below": ({"avail_commit_gib": 9.99}, (False, True)),
             "physical_below": ({"avail_phys_gib": 3.99}, (True, False)),
             "observed_dip_3.2": ({"avail_commit_gib": 16.9, "avail_phys_gib": 3.2}, (True, False)),
             "observed_dip_3.5": ({"avail_commit_gib": 10.4, "avail_phys_gib": 3.5}, (True, False)),
             "both_low": ({"avail_commit_gib": 5.0, "avail_phys_gib": 2.0}, (False, False)),
             "commit_missing": ({"avail_commit_gib": None}, (False, True)),
             "physical_missing": ({"avail_phys_gib": None}, (True, False))}
    for name, (over, want) in cases.items():
        r = ev(reading(**over))
        check((r["commit_ok"], r["physical_ok"]) == want and not r["ok"], f"{name}: {r['problems']}")
    for over in ({"disk_free_gib": 9.9}, {"cpu_mean_pct": 40.1}, {"battleship_pids": [1]}, {"listeners": [{"port": 30000}]},
                 {"ssb64_environment_variables": ["SSB64_X"]}):
        check(not ev(reading(**over))["ok"], f"{over} accepted")
    # in run: the level reads available commit only; a physical dip never stops, it is counted and reported
    pol = g.REGISTERED_POLICY
    check(g.level_of(10.4, pol) == "ok" and g.level_of(4.0, pol) == "ok" and g.level_of(3.99, pol) == "warn"
          and g.level_of(2.99, pol) == "stop" and g.level_of(0.99, pol) == "emergency" and g.level_of(None, pol) == "stop",
          "in-run levels")
    import m7d_run as dr

    samples = iter([{"avail_commit_gib": 10.4, "avail_phys_gib": 3.2, "commit_used_gib": 20.0},
                    {"avail_commit_gib": 10.5, "avail_phys_gib": 3.5, "commit_used_gib": 20.1},
                    {"avail_commit_gib": 11.0, "avail_phys_gib": 4.2, "commit_used_gib": 19.0}] + [None] * 1000)
    saved = dr.memory_status
    last = {"v": {"avail_commit_gib": 11.0, "avail_phys_gib": 4.2, "commit_used_gib": 19.0}}

    def fake() -> Dict[str, Any]:
        v = next(samples)
        last["v"] = v or last["v"]
        return dict(last["v"])

    d = s.dir("unit_resource_gates")
    dr.memory_status = fake
    try:
        probe = g.MemoryProbe(g.MemoryPolicy(probe_interval_s=0.01), d, d / "probe.jsonl")
        probe.start()
        time.sleep(0.2)
        rep = probe.stop()
    finally:
        dr.memory_status = saved
    check(rep["samples"] >= 3 and rep["min_avail_phys_gib"] == 3.2 and rep["samples_physical_below_launch_gate"] == 2
          and not rep["crossings"], f"probe {rep}")
    real = g.launch_gate()
    check(set(real) >= {"commit_ok", "physical_ok", "ok", "measurement"}, "real reading")
    m = real["measurement"]
    return {"real": {"avail_commit_gib": m.get("avail_commit_gib"), "avail_phys_gib": m.get("avail_phys_gib"),
                     "disk_free_gib": m.get("disk_free_gib"), "cpu_mean_pct": m.get("cpu_mean_pct"), "ok": real["ok"],
                     "problems": real["problems"]},
            "probe_physical_dip": {"min_avail_phys_gib": rep["min_avail_phys_gib"],
                                   "samples_below_4": rep["samples_physical_below_launch_gate"], "crossings": rep["crossings"]}}


def unit_dry_runs(s: Suite) -> Dict[str, Any]:
    d = s.dir("unit_dry_runs")
    out: Dict[str, Any] = {}
    man = manifest()
    with Root(d / "root", control=None) as r:
        before = tree(r)
        rc, text = run_cli("train", "--dry-run", "--skip-resource-gate")
        rep = report_of(text)
        check(rc == cm.EXIT_FAILED and len(rep["blocking_problems"]) == 1 and "has not run" in rep["blocking_problems"][0],
              f"no control check: {rc} {rep['blocking_problems']}")
        out["no_control_check"] = rc
        write_control_record(man, ok=True)
        skip = ("_control/" + cm.CONTROL_RECORD,)            # rewritten by this test itself
        before = tree(r, skip=skip)
        rc, text = run_cli("train", "--dry-run", "--skip-resource-gate")
        rep = report_of(text)
        check(rc == cm.EXIT_OK and rep["plan"][0] == {"run": "m7h_f_s0", "status": "absent", "action": "train from scratch"}
              and [p["run"] for p in rep["plan"]] == ["m7h_f_s0", "m7h_f_s1", "m7h_f_s2"]
              and all(p["action"].startswith("wait") for p in rep["plan"][1:]), f"plan {rep['plan']} {rep['blocking_problems']}")
        out["train"] = rc
        rc, _t = run_cli("preflight", "--skip-resource-gate")
        check(rc == cm.EXIT_OK, f"preflight {rc}")
        write_control_record(man, ok=True, code="0" * 64)
        rc, text = run_cli("train", "--dry-run", "--skip-resource-gate")
        check(rc == cm.EXIT_FAILED and "re-run control-check" in text, "stale control check accepted")
        write_control_record(man, ok=False)
        rc, text = run_cli("train", "--dry-run", "--skip-resource-gate")
        check(rc == cm.EXIT_FAILED and "FAILED" in text, "failed control check accepted")
        write_control_record(man, ok=True)
        cm.GATE_FN = lambda: g.evaluate_launch(reading(avail_commit_gib=16.9, avail_phys_gib=3.3))
        rc, text = run_cli("train", "--dry-run")
        rep = report_of(text)
        check(rc == cm.EXIT_FAILED and rep["blocking_problems"] == ["available physical 3.3 GiB < 4.0 GiB"],
              f"physical launch gate: {rep['blocking_problems']}")
        out["gate_physical_3.3"] = rep["blocking_problems"]
        cm.GATE_FN = lambda: g.evaluate_launch(reading(avail_commit_gib=10.0, avail_phys_gib=4.0))
        rc, _t = run_cli("train", "--dry-run")
        check(rc == cm.EXIT_OK, "the gate boundaries refused")
        cm.GATE_FN = None
        rc, text = run_cli("train", "--dry-run", "--skip-resource-gate", "--only", "m7h_f_s1")
        check("out of order" in text, "out-of-order refusal not in the plan")
        for argv, want, name in ((("train", "--dry-run", "--extension", "--skip-resource-gate"), cm.EXIT_USAGE, "extension"),
                                 (("train", "--dry-run", "--resume", "m7h_f_s0", "--skip-resource-gate"), cm.EXIT_USAGE,
                                  "resume"),
                                 (("train", "--dry-run", "--retrain-control", "--skip-resource-gate"), cm.EXIT_USAGE,
                                  "retrain_without_failed_check"),
                                 (("control-check", "--dry-run"), cm.EXIT_OK, "control_check_dry"),
                                 (("evaluate", "--dry-run"), cm.EXIT_OK, "evaluate_dry"),
                                 (("census",), cm.EXIT_FAILED, "census_empty"),
                                 (("analyze",), cm.EXIT_FAILED, "analyze_not_ready"),
                                 (("status",), cm.EXIT_OK, "status"),
                                 (("manifest",), cm.EXIT_USAGE, "manifest_frozen")):
            rc, text = run_cli(*argv)
            check(rc == want, f"{name}: exit {rc} (want {want}) {text[-300:]}")
            out[name] = rc
        check(tree(r, skip=skip) == before, f"a dry run created or changed something: {set(tree(r, skip=skip)) ^ set(before)}")
    return out


def _fake_ok(calls: List[Any]) -> Callable[..., Dict[str, Any]]:
    def launch(*, spec: hm.RunSpec, exp: Any, manifest: Any) -> Dict[str, Any]:
        calls.append({"run": spec.name, "run_dir": spec.run_dir, "config": spec.config_path, "curriculum": exp.curriculum,
                      "exp_run_dir": exp.run_dir})
        spec.run_dir.mkdir(parents=True)
        hm.write_json(spec.run_dir / "training_summary.json", {"status": "completed"})
        return {"exit_code": 0, "stop_kind": None, "monitor": {"max_battleship_processes": 10},
                "probe": {"min_avail_commit_gib": 10.2, "min_avail_phys_gib": 3.4, "samples_physical_below_launch_gate": 7}}
    return launch


def unit_launch_stop_restart(s: Suite) -> Dict[str, Any]:
    d = s.dir("unit_launch_stop_restart")
    man = manifest()
    out: Dict[str, Any] = {}
    # 1. a full sequence: order, isolation, the gate before every launch, the manifest frozen at the first launch
    with Root(d / "seq", frozen=False) as r:
        doc = d / "doc_manifest.json"
        hm.write_json(doc, man)
        hm.MANIFEST_DOC = doc
        calls: List[Dict[str, Any]] = []
        gates: List[int] = []
        cm.GATE_FN = lambda: (gates.append(1), g.evaluate_launch(reading()))[1]
        cm.LAUNCHER = _fake_ok(calls)
        cm.verify_run = lambda spec, exp, manifest: {"ok": True, "problems": []}
        rc, _t = run_cli("train")
        check(rc == cm.EXIT_OK and [c["run"] for c in calls] == ["m7h_f_s0", "m7h_f_s1", "m7h_f_s2"], f"sequence {rc} {calls}")
        check(all(hm.within(c["run_dir"], r) and c["exp_run_dir"] == c["run_dir"] and c["curriculum"] == mc.REGISTERED
                  and c["config"] == hm.CONFIG_DIR / f"{c['run']}.toml" for c in calls), "output isolation / profiles")
        check(len(gates) == 3, f"launch gate calls {len(gates)} (1 preflight + 1 before each later launch)")
        check(cm.frozen_manifest_path().read_bytes() == doc.read_bytes(), "the manifest was not frozen at the first launch")
        st = cm.load_state()
        check(all(st["runs"][n]["status"] == "verified" for n in ("m7h_f_s0", "m7h_f_s1", "m7h_f_s2"))
              and st["runs"]["m7h_f_s0"]["attempts"][0]["probe"]["samples_physical_below_launch_gate"] == 7, "state")
        out["sequence"] = [c["run"] for c in calls]
    # 2. a stop: kept in _partial by the guard, restarted from scratch by the next invocation (never resumed)
    with Root(d / "stop") as r:
        calls = []
        state_box: Dict[str, Any] = {}

        def stop_once(*, spec: hm.RunSpec, exp: Any, manifest: Any) -> Dict[str, Any]:
            calls.append(spec.name)
            spec.run_dir.mkdir(parents=True)
            (spec.run_dir / "checkpoints").mkdir()
            (spec.run_dir / "checkpoints" / "marker.txt").write_text("periodic set stand-in", encoding="utf-8")
            dest = hm.partial_root() / f"{spec.name}__synthetic"
            dest.parent.mkdir(parents=True, exist_ok=True)
            spec.run_dir.rename(dest)
            state_box["partial"] = dest
            return {"exit_code": 130, "stop_kind": "cooperative_stop", "moved_to": str(dest)}

        cm.LAUNCHER = stop_once
        cm.verify_run = lambda spec, exp, manifest: {"ok": True, "problems": []}
        rc, _t = run_cli("train", "--skip-resource-gate")
        h = tree(state_box["partial"])
        check(rc == cm.EXIT_INTERRUPTED and cm.load_state()["runs"]["m7h_f_s0"]["status"] == "stopped", f"stop {rc}")
        calls2: List[Dict[str, Any]] = []
        cm.LAUNCHER = _fake_ok(calls2)
        rc, text = run_cli("train", "--dry-run", "--skip-resource-gate")
        check(report_of(text)["plan"][0]["action"] == "train from scratch", "a stopped run is not restarted from scratch")
        rc, _t = run_cli("train", "--skip-resource-gate")
        check(rc == cm.EXIT_OK and [c["run"] for c in calls2] == ["m7h_f_s0", "m7h_f_s1", "m7h_f_s2"]
              and tree(state_box["partial"]) == h, "restart after a stop")
        out["stop"] = {"first": calls, "restart": [c["run"] for c in calls2], "partial_kept": state_box["partial"].name}
    # 3. a crash leaves a partial directory: STOP, then --restart-partial moves it aside intact and relaunches
    with Root(d / "crash") as r:
        seen: List[str] = []

        def crash(*, spec: hm.RunSpec, exp: Any, manifest: Any) -> Dict[str, Any]:
            seen.append(spec.name)
            spec.run_dir.mkdir(parents=True)
            (spec.run_dir / "run.json").write_text("{}", encoding="utf-8")
            return {"exit_code": 1, "stop_kind": None}

        cm.LAUNCHER = crash
        rc, _t = run_cli("train", "--skip-resource-gate")
        spec = hm.run_by_name("m7h_f_s0")
        h = tree(spec.run_dir)
        check(rc == cm.EXIT_FAILED and spec.run_dir.is_dir(), f"crash {rc}")
        rc, text = run_cli("train", "--skip-resource-gate")
        check(rc == cm.EXIT_USAGE and "partial run directory" in text, f"a partial run was not stopped: {rc}")
        calls3: List[Dict[str, Any]] = []
        cm.LAUNCHER = _fake_ok(calls3)
        cm.verify_run = lambda spec, exp, manifest: {"ok": True, "problems": []}
        rc, _t = run_cli("train", "--skip-resource-gate", "--restart-partial", "m7h_f_s0")
        moved = sorted(hm.partial_root().iterdir())
        check(rc == cm.EXIT_OK and len(moved) == 1 and tree(moved[0]) == h and calls3[0]["run"] == "m7h_f_s0",
              f"restart-partial {rc} {moved}")
        out["crash"] = {"moved": moved[0].name}
    # 4. the launch gate before a later run refuses: the invocation stops before that launch
    with Root(d / "gate") as r:
        calls4: List[Dict[str, Any]] = []
        answers = iter([reading(), reading(avail_phys_gib=3.4)])
        cm.GATE_FN = lambda: g.evaluate_launch(next(answers))
        cm.LAUNCHER = _fake_ok(calls4)
        cm.verify_run = lambda spec, exp, manifest: {"ok": True, "problems": []}
        rc, _t = run_cli("train")
        st = cm.load_state()
        check(rc == cm.EXIT_FAILED and [c["run"] for c in calls4] == ["m7h_f_s0"]
              and any(e["kind"] == "launch_gate_refused" for e in st["events"]), f"gate refusal {rc} {calls4}")
        out["gate_refusal"] = [c["run"] for c in calls4]
    return out


def _synthetic_set(spec: hm.RunSpec, t: int, man: Mapping[str, Any], *, run_id: Optional[str] = None,
                   profile: Optional[hm.RunSpec] = None, archive: bool = True, interruption: Optional[Dict] = None) -> Path:
    import gymnasium as gym
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv

    import m7_trainer as tr
    from btt_learning import make_policy_observation_space, make_track1_action_space
    from btt_parallel import RunCoordinator, initial_coordination_state

    exp = hm.load_run(profile or spec)
    cfg = tr.config_from_experiment(exp)

    class _Spaces(gym.Env):
        def __init__(self) -> None:
            self.observation_space = make_policy_observation_space()
            self.action_space = make_track1_action_space()

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return np.zeros(15, np.float32), {}

        def step(self, a):
            return np.zeros(15, np.float32), 0.0, False, False, {}

    torch.set_num_threads(1)
    vecnorm = tr.make_vecnormalize(cfg, DummyVecEnv([_Spaces for _ in range(cfg.n_envs)]))
    model = tr.make_model(cfg, vecnorm)
    tr.annotate_model(cfg, model)
    model.num_timesteps = int(t)
    run_meta = {"run_id": run_id or spec.name, "purpose": "test", "lineage": [], "contracts": tr.run_contracts(cfg),
                "horizon": cfg.horizon, "n_envs": cfg.n_envs, "ppo": tr.resolved_ppo_params(model, cfg.policy),
                "seeds": {"base_seed": cfg.base_seed}, "executable": {"path": str(cfg.executable),
                                                                     "sha256": man["executable"]["sha256"]},
                "revisions": {"head": man["revisions"]["head"],
                              "submodules": [{"path": k, "commit": v} for k, v in man["revisions"]["submodules"].items()]},
                "m6_flags": dict(cfg.extra_env), "versions": tr.versions(), "torch_threads": {"requested": 1},
                "lifecycle": cfg.lifecycle_json(), "experiment": dict(exp.summary(), compatibility_view=exp.compatibility_view())}

    def extra(directory: Path) -> Dict[str, str]:
        a = mc.Archive(run_id or spec.name)
        files = {"curriculum_archive.json": json.dumps(a.to_json()).encode(), "curriculum_prefixes.bin": a.prefixes_blob()}
        for name, data in files.items():
            (directory / name).write_bytes(data)
        return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}

    label = f"ckpt_{t:09d}" if interruption is None else "interrupted"
    dst = spec.run_dir / "checkpoints" / label if interruption is None else spec.run_dir / "interrupted"
    coord = RunCoordinator.create(spec.run_dir / f"coord_{label}_{run_id or ''}", initial_coordination_state(
        run_id or spec.name, "training", 10))
    tr.save_checkpoint_set(dst, model, vecnorm, run_meta=run_meta, coordinator=coord, label=label, rollouts=0,
                           extra_writer=extra if archive else None, interruption=interruption)
    vecnorm.close()
    return dst


def unit_checkpoint_identity(s: Suite) -> Dict[str, Any]:
    import m7d_run as dr

    d = s.dir("unit_checkpoint_identity")
    man = manifest()
    out: Dict[str, Any] = {}
    with Root(d / "root"):
        f0, c3 = hm.run_by_name("m7h_f_s0"), hm.run_by_name("m7h_c_s3")
        e_f0, e_c3 = hm.load_run(f0), hm.load_run(c3)
        ck0 = _synthetic_set(f0, 0, man, archive=False)       # the trainer's ckpt_000000000 has no archive
        check(cm.checkpoint_provenance(ck0, f0, e_f0, 0, man) == [], f"t=0 {cm.checkpoint_provenance(ck0, f0, e_f0, 0, man)}")
        want = (man["runs"]["m7h_f_s0"]["expected_initial_policy_digest"], man["runs"]["m7h_f_s0"]["expected_initial_obs_rms_digest"])
        check(tuple(dr.checkpoint_digests(ck0)) == tuple(want), "an untrained F set differs from the fresh-model digests")
        ck = _synthetic_set(f0, 307_200, man)
        check(cm.checkpoint_provenance(ck, f0, e_f0, 307_200, man) == [], "t>0 with archive refused")
        wrong = {"point": cm.checkpoint_provenance(ck, f0, e_f0, 614_400, man),
                 "arm_C_profile": cm.checkpoint_provenance(ck, hm.run_by_name("m7h_c_s0"), hm.load_run(hm.run_by_name("m7h_c_s0")),
                                                           307_200, man)}
        ck_s1 = _synthetic_set(f0, 409_600, man, profile=hm.run_by_name("m7h_f_s1"), run_id="m7h_f_s0")
        wrong["seed"] = cm.checkpoint_provenance(ck_s1, f0, e_f0, 409_600, man)
        ck_na = _synthetic_set(f0, 512_000, man, archive=False)
        wrong["missing_archive"] = cm.checkpoint_provenance(ck_na, f0, e_f0, 512_000, man)
        ck_other = _synthetic_set(f0, 716_800, man, run_id="m7h_e4_on_s0")
        wrong["other_run"] = cm.checkpoint_provenance(ck_other, f0, e_f0, 716_800, man)
        ck_int = _synthetic_set(f0, 819_200, man, interruption={"completed_update_checkpoint": False, "kind": "stopped"})
        wrong["interrupted"] = cm.checkpoint_provenance(ck_int, f0, e_f0, 819_200, man)
        m2 = copy.deepcopy(man)
        m2["executable"]["sha256"] = "0" * 64
        wrong["executable"] = cm.checkpoint_provenance(ck, f0, e_f0, 307_200, m2)
        ck_c = _synthetic_set(c3, 102_400, man)                # a C set carrying curriculum files
        wrong["C_with_archive"] = cm.checkpoint_provenance(ck_c, c3, e_c3, 102_400, man)
        ck_c_ok = _synthetic_set(c3, 204_800, man, archive=False)
        check(cm.checkpoint_provenance(ck_c_ok, c3, e_c3, 204_800, man) == [], "a clean C set refused")
        for k, v in wrong.items():
            check(bool(v), f"accepted: {k}")
        out = {k: v[0][:80] for k, v in wrong.items()}
    return out


def unit_curriculum_verification(s: Suite) -> Dict[str, Any]:
    if not (E4 / "training_summary.json").is_file():
        return {"skipped": "runs/m7h/_gate/e4 not present"}
    d = s.dir("unit_curriculum_verification")
    base = mv.verify_curriculum_run(E4, run_id="m7h_e4_on_s0")
    check(base["ok"], f"E4 no longer verifies: {base['problems'][:3]}")
    found: Dict[str, List[str]] = {}

    def variant(name: str, mutate: Callable[[Path], None], expect: str) -> None:
        run = d / name / "m7h_e4_on_s0"
        shutil.copytree(E4, run)
        mutate(run)
        v = mv.verify_curriculum_run(run, run_id="m7h_e4_on_s0")
        found[name] = v["problems"][:3]
        shutil.rmtree(d / name)                              # test scratch only (a copy of the E4 run)
        check(not v["ok"] and any(expect in p for p in v["problems"]), f"{name}: not detected ({v['problems'][:4]})")

    def prefix_artifact(run: Path) -> Tuple[Path, Dict[str, Any]]:
        return next((a, m) for a, m in mv.artifacts_of(run)
                    if ((m.get("labels") or {}).get(mc.START_LABEL) or {}).get("kind") == mc.START_PREFIX)

    def label_L(run: Path) -> None:
        a, m = prefix_artifact(run)
        m["labels"][mc.START_LABEL]["prefix_length"] += 1
        (a / "metadata.json").write_text(json.dumps(m), encoding="utf-8")

    def drop_label(run: Path) -> None:
        a, m = prefix_artifact(run)
        m["labels"].pop(mc.START_LABEL)
        (a / "metadata.json").write_text(json.dumps(m), encoding="utf-8")

    def rows_edit(run: Path, fn: Callable[[Dict[str, Any]], None]) -> None:
        f = run / "metrics" / "episodes.jsonl"
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        fn(next(r for r in rows if (r.get("m7h") or {}).get("start_kind") == mc.START_PREFIX))
        f.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def log_L(run: Path) -> None:
        f = run / "curriculum" / "selection.jsonl"
        evs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        ev = next(e for k, e in enumerate(evs) if e["event"] == "delivered" and e["kind"] == mc.START_PREFIX
                  and any(x["event"] == "ingest" and x["env"] == e["env"] for x in evs[k + 1:]))
        ev["prefix_length"] += 5
        f.write_text("".join(json.dumps(e) + "\n" for e in evs), encoding="utf-8")

    def foreign_source(run: Path) -> None:
        f = run / "final" / "curriculum_archive.json"
        a = json.loads(f.read_text(encoding="utf-8"))
        a["entries"][0]["source"]["run_id"] = "another_run"
        f.write_text(json.dumps(a), encoding="utf-8")        # the set's hash check then fails too

    variant("label_L", label_L, "artifact_boundary_problems")
    variant("dropped_label", drop_label, "artifact_L_ne_row_L")
    variant("row_L", lambda run: rows_edit(run, lambda r: r["m7h"].__setitem__("prefix_length", r["m7h"]["prefix_length"] - 1)),
            "log_L_ne_row_L")
    variant("row_start_kind", lambda run: rows_edit(run, lambda r: r["m7h"].__setitem__("start_kind", mc.START_TICK0)),
            "kind_ne_row_kind")
    variant("log_L", log_L, "log_L_ne_row_L")
    variant("foreign_archive_source", foreign_source, "archive")
    return {"e4": base["counts"], "detected": found}


def unit_eval_tick0(s: Suite) -> Dict[str, Any]:
    src = GATE / "e2" / "e4_final_eval"
    if not (src / "evaluation_summary.json").is_file():
        return {"skipped": "runs/m7h/_gate/e2 not present"}
    d = s.dir("unit_eval_tick0")
    ok = mv.verify_eval_tick0(src)
    check(ok["ok"] and ok["artifacts"] == 10, f"E2 evaluation: {ok}")
    out = {"real": {k: ok[k] for k in ("artifacts", "rows")}}
    for name, fn, want in (("start_label", lambda a, m: m["labels"].__setitem__(mc.START_LABEL, {"kind": mc.START_PREFIX}),
                            "with_start_label"),
                           ("initial_tick", lambda a, m: m["initial_observation"].__setitem__("input_tick", 7),
                            "initial_not_tick0")):
        dst = d / name
        shutil.copytree(src, dst, ignore=NO_RUNTIME)
        a = next(iter(sorted((dst / "stochastic" / "workers").glob("w*/artifacts/*"))))
        m = json.loads((a / "metadata.json").read_text(encoding="utf-8"))
        fn(a, m)
        (a / "metadata.json").write_text(json.dumps(m), encoding="utf-8")
        v = mv.verify_eval_tick0(dst)
        check(not v["ok"] and any(want in p for p in v["problems"]), f"{name}: {v['problems']}")
    dst = d / "row_key"
    shutil.copytree(src, dst, ignore=NO_RUNTIME)
    f = dst / "deterministic" / "evaluation.json"
    doc = json.loads(f.read_text(encoding="utf-8"))
    doc["episodes"][0]["m7h"] = {"start_kind": mc.START_PREFIX}
    f.write_text(json.dumps(doc), encoding="utf-8")
    check(not mv.verify_eval_tick0(dst)["ok"], "an m7h key in an evaluation row accepted")
    return out


# Real labels with one legitimate excess episode each (the evaluator counted it as excess_episodes_not_counted and
# preserve_all kept its artifact): three Phase K labels and the M7h F s0 curve label that stopped the first evaluate.
REAL_EXCESS_LABELS = ("runs/m7g_k/_eval/m7g_s0_v2/curve_t000921600", "runs/m7g_k/_eval/m7g_s0_v2/curve_t002150400",
                      "runs/m7g_k/_eval/m7g_s1_v1/curve_t000614400", "runs/m7h/campaign/_eval/m7h_f_s0/curve_t000307200")
REAL_ORDINARY_LABELS = ("runs/m7h/campaign/_eval/m7h_f_s0/initial", "runs/m7g_k/_eval/m7g_s0_v1/final",
                        "runs/m7g_k/_eval/m7g_s1_v1/final", "runs/m7g_k/_eval/m7g_s2_v1/final",
                        "runs/m7h/_gate/e2/e4_final_eval")


def unit_eval_tick0_excess(s: Suite) -> Dict[str, Any]:
    """Amendment 1: artifacts = counted rows + the recorded excess episodes, each identified; forged / missing records
    and every non-excess extra artifact refused; the tick-0 checks apply to excess artifacts too."""
    out: Dict[str, Any] = {"real": {}}
    for rel in REAL_ORDINARY_LABELS + REAL_EXCESS_LABELS:
        p = REPO_ROOT / rel
        check((p / "stochastic" / "evaluation.json").is_file(), f"{rel} missing")
        v = mv.verify_eval_tick0(p)
        want = 1 if rel in REAL_EXCESS_LABELS else 0
        check(v["ok"] and v["excess_recorded"] == v["excess_artifacts"] == len(v["excess_episode_ids"]) == want
              and v["artifacts"] == v["rows"] + want, f"{rel}: {v['problems'][:3]} excess {v['excess_recorded']}")
        out["real"][rel] = {k: v[k] for k in ("artifacts", "rows", "excess_recorded")}
    src = REPO_ROOT / REAL_EXCESS_LABELS[-1]
    base = mv.verify_eval_tick0(src)
    ex_id = base["excess_episode_ids"][0]
    d = s.dir("unit_eval_tick0_excess")

    def locate(root: Path) -> Tuple[Path, Dict[str, Any]]:
        a = next(root.glob(f"stochastic/workers/w*/artifacts/{ex_id}"))
        return a, json.loads((a / "metadata.json").read_text(encoding="utf-8"))

    def save_meta(a: Path, m: Mapping[str, Any]) -> None:
        (a / "metadata.json").write_text(json.dumps(m), encoding="utf-8")

    def edit_eval(root: Path, fn: Callable[[Dict[str, Any]], None]) -> None:
        f = root / "stochastic" / "evaluation.json"
        doc = json.loads(f.read_text(encoding="utf-8"))
        fn(doc)
        f.write_text(json.dumps(doc), encoding="utf-8")

    def edit_ledger(ledger: Path, fn: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]) -> None:
        recs = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
        ledger.write_text("".join(json.dumps(r) + "\n" for r in fn(recs)), encoding="utf-8")

    def meta_edit(**labels: Any) -> Callable[[Path], None]:
        def fn(root: Path) -> None:
            a, m = locate(root)
            m["labels"].update(labels)
            save_meta(a, m)
        return fn

    def remove_excess(root: Path) -> None:
        shutil.rmtree(locate(root)[0])

    def forged_duplicate(root: Path) -> None:
        # the real excess artifact replaced by a copy of a counted episode under a new id (count still 1)
        a, m = locate(root)
        shutil.rmtree(a)
        doc = json.loads((root / "stochastic" / "evaluation.json").read_text(encoding="utf-8"))
        row = doc["episodes"][0]
        srcd = root / "/".join(Path(row["artifact_dir"]).parts[-5:])
        dst = srcd.parent / (row["episode_id"] + "_forged")
        shutil.copytree(srcd, dst)
        fm = json.loads((dst / "metadata.json").read_text(encoding="utf-8"))
        fm["episode_id"] = dst.name
        save_meta(dst, fm)

    def drop_ledger(root: Path) -> None:
        a, _m = locate(root)
        edit_ledger(a.parent.parent / "dispositions.jsonl", lambda rs: [r for r in rs if r.get("episode_id") != ex_id])

    def aborted(root: Path) -> None:
        a, m = locate(root)
        m["status"] = "aborted"
        m["labels"].update(episode_status="aborted", end_reason="aborted")
        save_meta(a, m)

    def next_episode(root: Path) -> None:
        a, m = locate(root)
        m["labels"]["worker_episode"] += 1
        save_meta(a, m)
        edit_ledger(a.parent.parent / "dispositions.jsonl", lambda rs: [dict(r, worker_episode=r["worker_episode"] + 1)
                                                                        if r.get("episode_id") == ex_id else r for r in rs])

    def lower_rank(root: Path) -> None:
        # the excess moved to rank 1 (its next episode, ledger moved too): rank 2 was counted on the final step
        a, m = locate(root)
        doc = json.loads((root / "stochastic" / "evaluation.json").read_text(encoding="utf-8"))
        nxt = 1 + max(e["worker_episode"] for e in doc["episodes"] if e["rank"] == 1)
        dst = root / "stochastic" / "workers" / "w01" / "artifacts" / ex_id
        shutil.move(str(a), str(dst))
        m["labels"].update(rank=1, worker_episode=nxt)
        save_meta(dst, m)
        rec: Dict[str, Any] = {}
        edit_ledger(a.parent.parent / "dispositions.jsonl",
                    lambda rs: [r for r in rs if r.get("episode_id") != ex_id or rec.update(r)])
        rec.update(rank=1, worker_episode=nxt, artifact_dir=str(dst.relative_to(REPO_ROOT)).replace("\\", "/"))
        edit_ledger(root / "stochastic" / "workers" / "w01" / "dispositions.jsonl", lambda rs: rs + [rec])

    def start_label(root: Path) -> None:
        a, m = locate(root)
        m["labels"][mc.START_LABEL] = {"kind": mc.START_PREFIX, "prefix_length": 5}
        save_meta(a, m)

    def initial_tick(root: Path) -> None:
        a, m = locate(root)
        m["initial_observation"]["input_tick"] = 7
        save_meta(a, m)

    def rows_edited(root: Path) -> None:
        a, _m = locate(root)
        f = a / "actions.jsonl"
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        rows[100]["buttons"] = int(rows[100]["buttons"]) ^ 1
        f.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def swap_rows(root: Path) -> None:
        def fn(doc: Dict[str, Any]) -> None:
            e = doc["episodes"]
            e[0]["artifact_dir"], e[1]["artifact_dir"] = e[1]["artifact_dir"], e[0]["artifact_dir"]
        edit_eval(root, fn)

    variants = (
        ("record_zero", lambda r: edit_eval(r, lambda doc: doc.__setitem__("excess_episodes_not_counted", 0)),
         "recorded 0 excess"),
        ("record_missing", lambda r: edit_eval(r, lambda doc: doc.pop("excess_episodes_not_counted")),
         "no valid excess record"),
        ("record_not_int", lambda r: edit_eval(r, lambda doc: doc.__setitem__("excess_episodes_not_counted", "1")),
         "no valid excess record"),
        ("record_forged_2", lambda r: edit_eval(r, lambda doc: doc.__setitem__("excess_episodes_not_counted", 2)),
         "recorded 2 excess"),
        ("excess_artifact_removed", remove_excess, "0 preserved artifacts beyond"),
        ("forged_duplicate_artifact", forged_duplicate, "not recorded as preserved"),
        ("not_in_ledger", drop_ledger, "not recorded as preserved in its worker ledger"),
        ("aborted_in_flight", aborted, "not a finished episode"),
        ("not_next_worker_episode", next_episode, "is not rank 4's next"),
        ("not_final_step", meta_edit(native_steps_at_end=0), "did not end on the final vector step"),
        ("other_run_id", meta_edit(run_id="eval:other"), "role / run id"),
        ("lower_rank_than_counted", lower_rank, "not after every counted episode"),
        ("excess_start_label", start_label, "with_start_label"),
        ("excess_initial_tick", initial_tick, "initial_not_tick0"),
        ("excess_rows_edited", rows_edited, "digest_mismatch"),
        ("counted_rows_swapped", swap_rows, "disagree"),
    )
    found: Dict[str, str] = {}
    for name, fn, want in variants:
        dst = d / name
        shutil.copytree(src, dst, ignore=NO_RUNTIME)
        check(mv.verify_eval_tick0(dst)["ok"], f"{name}: the unmodified copy is refused")
        fn(dst)
        v = mv.verify_eval_tick0(dst)
        hit = next((p for p in v["problems"] if want in p), None)
        check(not v["ok"] and hit is not None, f"{name}: accepted or wrong reason {v['problems'][:4]}")
        found[name] = hit[:120]
        shutil.rmtree(dst)
    out["refused"] = found
    return out


def unit_amendment(s: Suite) -> Dict[str, Any]:
    """The post-training drift gate honours a registered amendment of AMENDABLE_FILES only: any other code, profile,
    executable, HEAD, submodule or decision-rule drift, a changed control record, wrong hashes or manifest, and a
    changed amendment after its first use are refused; train and control-check stay strict."""
    d = s.dir("unit_amendment")
    saved_doc = cm.AMENDMENT_DOC
    out: Dict[str, Any] = {}
    now = hm.code_fingerprint()
    vf = "rl/m7h_verify.py"
    with Root(d / "root") as _r:
        fz = cm.frozen_manifest_path()
        clean = hm.read_json(fz)
        amp = d / "amendment.json"

        def setup(man_fn: Callable[[Dict[str, Any]], None] = lambda m: None,
                  am_fn: Callable[[Dict[str, Any]], None] = lambda a: None) -> Tuple[List[str], Any]:
            man = copy.deepcopy(clean)
            man["code"]["per_file"][vf] = "0" * 64                 # the "original" verifier
            man["code"]["sha256"] = "1" * 64
            man_fn(man)
            hm.write_json(fz, man)
            am = {"schema": cm.AMENDMENT_SCHEMA, "amendment": 1, "date": "test",
                  "manifest_sha256": hashlib.sha256(fz.read_bytes()).hexdigest(), "original_code_sha256": "1" * 64,
                  "amended_code_sha256": now["sha256"], "files": {vf: {"before": "0" * 64, "after": now["per_file"][vf]}},
                  "control_record": {"sha256": hashlib.sha256(cm.control_record_path().read_bytes()).hexdigest()}}
            am_fn(am)
            amp.write_text(json.dumps(am), encoding="utf-8")
            return cm.evaluation_drift(hm.read_json(fz))

        try:
            cm.AMENDMENT_DOC = d / "absent.json"
            p, am = setup()
            check(p and am is None and any("no amendment" in x for x in p), f"no amendment: {p}")
            cm.AMENDMENT_DOC = amp
            p, am = setup()
            check(not p and am and am["files"] == [vf], f"valid amendment refused: {p}")
            out["honoured"] = am["files"]
            rc, text = run_cli("evaluate", "--dry-run")
            check(rc == cm.EXIT_OK and "amendment 1" in text, f"evaluate --dry-run with the amendment: {rc}")
            check(not cm.frozen_amendment_path().exists(), "a dry run froze the amendment")
            rc, text = run_cli("train", "--dry-run", "--skip-resource-gate")
            check(rc == cm.EXIT_FAILED and "code fingerprint" in text, f"train accepted amended code: {rc}")
            rc, text = run_cli("control-check", "--dry-run")
            check(rc == cm.EXIT_FAILED and "code fingerprint" in text, f"control-check accepted amended code: {rc}")
            refused: Dict[str, str] = {}
            cases = (
                ("undeclared_training_file", lambda m: m["code"]["per_file"].__setitem__("rl/m7_trainer.py", "2" * 64),
                 lambda a: None, "changed files"),
                ("declared_training_file", lambda m: m["code"]["per_file"].__setitem__("rl/m7_trainer.py", "2" * 64),
                 lambda a: a["files"].__setitem__("rl/m7_trainer.py",
                                                  {"before": "2" * 64, "after": now["per_file"]["rl/m7_trainer.py"]}),
                 "may not be amended"),
                ("profile_file", lambda m: m["code"]["per_file"].__setitem__("rl/configs/m7h/m7h_f_s0.toml", "3" * 64),
                 lambda a: a["files"].__setitem__("rl/configs/m7h/m7h_f_s0.toml", {
                     "before": "3" * 64, "after": now["per_file"]["rl/configs/m7h/m7h_f_s0.toml"]}), "may not be amended"),
                ("wrong_after_hash", lambda m: None, lambda a: a["files"][vf].__setitem__("after", "4" * 64), "hashes"),
                ("wrong_manifest", lambda m: None, lambda a: a.__setitem__("manifest_sha256", "5" * 64),
                 "another manifest"),
                ("wrong_original_code", lambda m: None, lambda a: a.__setitem__("original_code_sha256", "6" * 64),
                 "original code fingerprint"),
                ("wrong_amended_code", lambda m: None, lambda a: a.__setitem__("amended_code_sha256", "7" * 64),
                 "amended code fingerprint"),
                ("other_control_record", lambda m: None, lambda a: a["control_record"].__setitem__("sha256", "8" * 64),
                 "control record"),
                ("executable", lambda m: m["executable"].__setitem__("sha256", "9" * 64), lambda a: None,
                 "executable sha256 differs"),
                ("head", lambda m: m["revisions"].__setitem__("head", "a" * 40), lambda a: None, "parent HEAD"),
                ("submodule", lambda m: m["revisions"]["submodules"].__setitem__("decomp", "b" * 40), lambda a: None,
                 "submodule revisions"),
                ("profile_fingerprint", lambda m: m["runs"]["m7h_f_s0"].__setitem__("semantic_fingerprint", "c" * 64),
                 lambda a: None, "m7h_f_s0: profile"),
                ("decision_rule", lambda m: m["decision_rule"].__setitem__("sha256", "d" * 64), lambda a: None,
                 "decision rule differs"),
                ("schema", lambda m: None, lambda a: a.__setitem__("schema", "other"), "schema"),
            )
            for name, mf, af, want in cases:
                p, am = setup(mf, af)
                hit = next((x for x in p if want in x), None)
                check(p and am is None and hit is not None, f"{name}: {p}")
                refused[name] = hit[:120]
            out["refused"] = refused
            # the first real use freezes the record; a later change is refused
            p, _am = setup()
            st = cm.load_state()
            p, am = cm.evaluation_drift(hm.read_json(fz), state=st)
            check(not p and cm.frozen_amendment_path().is_file() and cm.frozen_amendment_path().read_bytes() ==
                  amp.read_bytes() and any(e["kind"] == "amendment_frozen" for e in cm.load_state()["events"]),
                  f"first use did not freeze the amendment: {p}")
            doc = json.loads(amp.read_text(encoding="utf-8"))
            doc["date"] = "changed"
            amp.write_text(json.dumps(doc), encoding="utf-8")
            p, am = cm.evaluation_drift(hm.read_json(fz))
            check(p and am is None and any("frozen at its first use" in x for x in p), f"changed amendment accepted {p}")
            out["frozen_then_changed"] = "refused"
            # no drift at all: nothing to amend, nothing read
            hm.write_json(fz, clean)
            cm.AMENDMENT_DOC = d / "absent.json"
            check(cm.evaluation_drift(clean) == ([], None), "a clean tree needs an amendment")
        finally:
            cm.AMENDMENT_DOC = saved_doc
    return out


def _eval_rows(n: int, targets: List[int], *, left: int = 0, falls: int = 0, mode: str = "s") -> List[Dict[str, Any]]:
    rows = []
    for i in range(n):
        rows.append({"episode_id": f"{mode}{i}", "rank": i % 5, "worker_episode": i // 5, "cleared": False,
                     "native_action_digest": f"{mode}{i:03d}", "targets_broken": targets[i],
                     "end_reason": "fall" if i < falls else "horizon",
                     "eval_metrics": {"ok": True, "first_left_entry": {"consumed_tick": 900} if i < left else None}})
    return rows


def _synthetic_campaign(state: Dict[str, Any], targets: Mapping[int, List[int]], *, left: Mapping[int, int] = {}) -> None:
    for spec in hm.matrix():
        exp = hm.load_run(spec)
        for plan in hm.evaluation_plan(spec, exp):
            lab = spec.eval_dir / plan["label"]
            nd, ns = int(plan["deterministic_episodes"]), int(plan["stochastic_episodes"])
            sto = _eval_rows(ns, targets[spec.seed] if plan["label"] == "final" else [3] * ns,
                             left=left.get(spec.seed, 0) if plan["label"] == "final" else 0, mode="s")
            det = _eval_rows(nd, [3] * nd, mode="d")
            hm.write_json(lab / "stochastic" / "evaluation.json", {"episodes": sto})
            hm.write_json(lab / "deterministic" / "evaluation.json", {"episodes": det})
            hm.write_json(lab / "evaluation_summary.json", {"modes": {"stochastic": {"episodes": sto},
                                                                      "deterministic": {"episodes": det}}})
            state["evaluations"][f"{spec.name}:{plan['label']}"] = {"ok": True, "tick0_ok": True}
        state["runs"][spec.name] = {"status": "verified"}
        state["entries"][spec.name] = {"g": 0, "verified": 0, "replayed": 0, "genuine_episodes_recorded": 0}
    cm.save_state(state)


def unit_analysis_end_to_end(s: Suite) -> Dict[str, Any]:
    d = s.dir("unit_analysis_end_to_end")
    up = {0: [5] * 78 + [6] * 22, 1: [5] * 75 + [6] * 25, 2: [4] * 23 + [5] * 77}     # T_F = 522, 525, 477 / 100
    out: Dict[str, Any] = {}
    with Root(d / "better"):
        state = cm.load_state()
        rc, text = run_cli("analyze")
        check(rc == cm.EXIT_FAILED and "not ready" in text and not cm.load_state().get("decisions"), "premature decision")
        _synthetic_campaign(state, up)
        rc, text = run_cli("analyze")
        dec = cm.load_state()["decisions"]["n3"]
        check(rc == cm.EXIT_OK and (dec["gate"], dec["branch"]) == (5, "targets_a"), f"{rc} {dec} {text[-400:]}")
        rc, _t = run_cli("analyze")
        check(rc == cm.EXIT_USAGE, "a decision was re-decided")
        rep = hm.read_json(hm.state_dir() / "analysis_n3.json")
        q = rep["decision"]["quantities"]
        check(q["D"] == {"0": "1/2", "1": "1/2", "2": "1/2"} and q["Phi_C"] == "1/150" and q["K_C"] == 0,
              f"quantities {q}")
        out["better"] = dec
    with Root(d / "extension"):
        state = cm.load_state()
        _synthetic_campaign(state, up, left={1: 1})
        rc, _t = run_cli("analyze")
        dec = cm.load_state()["decisions"]["n3"]
        check(rc == cm.EXIT_OK and dec["gate"] == 3 and dec["extension_required"], f"{dec}")
        rc, text = run_cli("train", "--dry-run", "--extension", "--skip-resource-gate")
        plan = report_of(text)["plan"]
        check(rc == cm.EXIT_OK and [p["run"] for p in plan] == ["m7h_c_s3", "m7h_f_s3", "m7h_f_s4", "m7h_c_s4"]
              and plan[0]["action"] == "train from scratch", f"extension plan {rc} {plan}")
        rc, text = run_cli("analyze")
        check(rc == cm.EXIT_FAILED and "not ready" in text and "n5" not in cm.load_state()["decisions"],
              "an n = 5 decision before the extension runs")
        out["extension"] = [p["run"] for p in plan]
    with Root(d / "integrity"):
        state = cm.load_state()
        _synthetic_campaign(state, up)
        state = cm.load_state()
        state["evaluations"]["m7h_f_s1:curve_t001228800"]["tick0_ok"] = False
        cm.save_state(state)
        rc, _t = run_cli("analyze")
        dec = cm.load_state()["decisions"]["n3"]
        check(rc == cm.EXIT_OK and dec["gate"] == 0, f"a tick-0 violation must be gate 0: {dec}")
        out["integrity"] = dec["gate"]
    return out


def unit_left_entries(s: Suite) -> Dict[str, Any]:
    """Section 4 plumbing without a real crossing (none exists outside the fixtures, which M7h never reads): the parent
    keeps every left-region trajectory; verify_left_entries replays the first genuine entry and up to 5 more (stubbed
    replay facts here) and sets g; the driver records g for the rule."""
    from m7h_vec import CurriculumVecEnv

    d = s.dir("unit_left_entries")
    run = d / "run"
    (run / "curriculum").mkdir(parents=True)
    vec = object.__new__(CurriculumVecEnv)                 # only the persistence method and its fields
    vec.left_episodes, vec.vec_steps, vec.stats = run / "curriculum" / "left_episodes.jsonl", 0, {"left_episodes_kept": 0}
    reports = []
    for k in range(9):
        L = 0 if k % 3 == 0 else 300 + k
        acts = bytes((k + i) % mc.TRACK1_ACTIONS for i in range(1000))
        cls = mc.CLASS_REENTRY if k == 1 else mc.CLASS_GENUINE
        rep = {"run_id": "m7h_f_s0", "episode_id": f"ep{k}", "rank": k % 5, "worker_episode": k, "class": cls,
               "start": {"kind": mc.START_PREFIX if L else mc.START_TICK0, "prefix_length": L, "prefix_digest":
                         mc.prefix_digest(acts[:L]) if L else None}, "lineage_left_exposed": cls == mc.CLASS_REENTRY,
               "rows": len(acts), "full_digest": mc.prefix_digest(acts), "end_reason": "horizon",
               "last_consumed_tick": 999, "left": {"any_left": True, "prefix_left_steps": 0,
                                                   "first_policy_left_step": L + 50}, "actions": acts}
        vec.vec_steps = 10 * k
        vec._keep_left_episode(rep)
        reports.append(rep)
    kept = mv.jsonl(run / "curriculum" / "left_episodes.jsonl")
    check(len(kept) == 9 and vec.stats["left_episodes_kept"] == 9
          and all(bytes.fromhex(r["actions_hex"]) == reports[i]["actions"] and r["prefix_length"] ==
                  reports[i]["start"]["prefix_length"] and r["full_digest"] == reports[i]["full_digest"]
                  for i, r in enumerate(kept)), "left-episode persistence")
    seen: List[Tuple[int, str]] = []
    saved = mv.replay_boundary

    def stub(actions: Any, *, L: int, work: Path, index: int, expected_digest: str, **_: Any) -> Dict[str, Any]:
        k = index - 9700
        seen.append((L, expected_digest))
        check(mv._digest({"buttons": b, "stick_x": x, "stick_y": y, "consumed_tick": t} for b, x, y, t in actions)
              == expected_digest, "the replayed actions are not the kept trajectory")
        facts = {"prefix_left_steps": 1 if k == 1 else 0,                       # replayed #1 fails (prefix left step)
                 "first_policy_left_step": L + 50 if k != 2 else L + 51}         # replayed #2 fails (other first step)
        return {"ok": True, "problems": [], "rows": len(actions), "L": L, **facts}

    mv.replay_boundary = stub
    try:
        res = mv.verify_left_entries(run, out_dir=d / "entries", executable=EXE, extra_env={})
        stub_fail = lambda *a, **k: dict(stub(*a, **k), first_policy_left_step=None)   # noqa: E731
        mv.replay_boundary = stub_fail
        none = mv.verify_left_entries(run, out_dir=d / "entries_none", executable=EXE, extra_env={})
    finally:
        mv.replay_boundary = saved
    genuine = [r for r in reports if r["class"] == mc.CLASS_GENUINE]
    check(res["genuine_episodes_recorded"] == 8 and res["replayed"] == 6 and res["verified"] == 4 and res["g"] == 1
          and [e["episode_id"] for e in res["entries"]] == [r["episode_id"] for r in genuine[:6]], f"entries {res}")
    check(none["verified"] == 0 and none["g"] == 0, "g without a verified entry")
    return {"kept": len(kept), "replayed": res["replayed"], "verified": res["verified"], "g": res["g"]}


def unit_isolation(s: Suite) -> Dict[str, Any]:
    mods = sorted(p for p in RL_DIR.glob("m7h_*.py") if not p.name.endswith("_tests.py"))
    pat = re.compile(r"rl/fixtures|fixtures/m7g|m7g/capture|tas_input|mario_743|crossing_fixture|lower_precision|"
                     r"upper_moving_platform|runs/m7f", re.IGNORECASE)
    hits = {p.name: pat.findall(p.read_text(encoding="utf-8").replace("\\", "/")) for p in mods}
    hits = {k: v for k, v in hits.items() if v and k != "m7h_matrix.py"}
    check(not hits, f"M7h modules reference fixture / TAS / capture paths: {hits}")
    mtxt = (RL_DIR / "m7h_matrix.py").read_text(encoding="utf-8")
    check(pat.findall(mtxt.replace(mtxt[mtxt.index("FORBIDDEN_INPUTS = ("):mtxt.index("def _forbidden_in")], "")) == [],
          "m7h_matrix references a forbidden path outside its guard list")
    profs = sorted(hm.CONFIG_DIR.rglob("*.toml"))
    bad = [p.name for p in profs if pat.search(p.read_text(encoding="utf-8").replace("\\", "/"))]
    check(not bad, f"profiles reference forbidden inputs: {bad}")
    learn = [p.name for p in mods if re.search(r"\.learn\(", p.read_text(encoding="utf-8"))]
    check(not learn, f"PPO learn() in {learn}")
    ev = (RL_DIR / "m7_evaluation.py").read_text(encoding="utf-8")
    check("m7h" not in ev and "CurriculumVecEnv" not in ev, "the evaluator references the curriculum")
    return {"modules": [p.name for p in mods], "profiles": len(profs)}


# -- game ---------------------------------------------------------------------------------------------------------------


def game_provisional_label(s: Suite) -> Dict[str, Any]:
    import experiment_config as ec
    from btt_parallel import RunCoordinator, WorkerSpec, initial_coordination_state
    from m7_runtime import install_kill_on_close_job, list_processes_named, prepare_worker_runtime, remove_worker_runtime
    from m7h_worker import CurriculumWorkerFactory
    from run_artifacts import PreservationReason

    install_kill_on_close_job()
    check(not list_processes_named(), "BattleShip already running")
    arch = mc.Archive.from_json(hm.read_json(E4 / "final" / "curriculum_archive.json"),
                                (E4 / "final" / "curriculum_prefixes.bin").read_bytes())
    entry = min((e for e in arch.eligible() if e.length >= 60), key=lambda e: e.length)
    exp = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7h" / "gate" / "m7h_e4_on_s0.toml")
    root = s.dir("game_provisional_label")
    coord = root / "coord"
    RunCoordinator.create(coord, initial_coordination_state("m7h_e4_on_s0", "test", 0))
    wdir = root / "w00"
    prepare_worker_runtime(wdir / "runtime", EXE)
    spec = WorkerSpec(rank=0, run_id="m7h_e4_on_s0", role="test", worker_dir=str(wdir), coordination_dir=str(coord),
                      executable=str(EXE), horizon=3600, base_seed=0, extra_env=tuple(exp.extra_env),
                      reward_contract=exp.reward, experiment=exp.summary(), standby_preboot=False, standby_count=0,
                      preserve_all=True)
    env = CurriculumWorkerFactory(spec, exp.curriculum)()
    out: Dict[str, Any] = {"L": entry.length}
    try:
        env.reset()
        bad = mc.prefix_spec(entry, "m7h_e4_on_s0")
        bad["end_observation"] = dict(bad["end_observation"], position_x=bad["end_observation"]["position_x"] + 1.0)
        try:
            env.run_prefix_phase(bad)
            raise Failure("a corrupted end observation was accepted")
        except mc.CurriculumError:
            pass
        rec = env.recording.recorder
        lab = rec.labels.get(mc.START_LABEL) or {}
        check(lab.get("kind") == mc.START_PREFIX_IN_PROGRESS and rec.action_count == entry.length
              and mc.prefix_rows(rec.labels, rec.action_count) == (entry.length, mc.START_PREFIX_IN_PROGRESS),
              f"provisional label {lab.get('kind')} rows {rec.action_count}")
        env.recording.preserve(PreservationReason.MANUAL, "m7h readiness test: refused prefix phase")
        env.reset()                                        # the refused episode is written as aborted
        a, meta = next((a, m) for a, m in mv.artifacts_of(root) if m.get("status") == "aborted")
        b = mv.boundary_record(a, meta)
        check(b["kind"] == mc.START_PREFIX_IN_PROGRESS and b["L"] == b["rows"] == entry.length and not b["problems"],
              f"written artifact {b}")
        out["refused_artifact"] = {k: b[k] for k in ("kind", "L", "rows", "status")}
        reply = env.run_prefix_phase(mc.prefix_spec(entry, "m7h_e4_on_s0"))
        check(reply["start"]["kind"] == mc.START_PREFIX, "an exact prefix was not delivered")
        for _ in range(25):
            env.step(np.array([0, 0], dtype=np.int64))
        rec = env.recording.recorder
        check(mc.prefix_rows(rec.labels, rec.action_count) == (entry.length, mc.START_PREFIX)
              and rec.action_count == entry.length + 25, f"after policy steps {rec.action_count}")
        env.recording.preserve(PreservationReason.MANUAL, "m7h readiness test: prefix + policy rows")
    finally:
        env.close()
        remove_worker_runtime(wdir / "runtime")
    arts = [mv.boundary_record(a, m) for a, m in mv.artifacts_of(root)]
    last = next(x for x in arts if x["kind"] == mc.START_PREFIX)
    check(last["L"] == entry.length and last["rows"] == entry.length + 25 and not last["problems"], f"{last}")
    check(not list_processes_named(), "leftover BattleShip")
    out["prefix_then_policy"] = {k: last[k] for k in ("kind", "L", "rows", "status")}
    return out


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_prefix_rows_rule": unit_prefix_rows_rule, "unit_manifest_profiles": unit_manifest_profiles,
    "unit_rule_registered": unit_rule_registered, "unit_historical_control": unit_historical_control,
    "unit_resource_gates": unit_resource_gates, "unit_dry_runs": unit_dry_runs,
    "unit_launch_stop_restart": unit_launch_stop_restart, "unit_checkpoint_identity": unit_checkpoint_identity,
    "unit_curriculum_verification": unit_curriculum_verification, "unit_eval_tick0": unit_eval_tick0,
    "unit_eval_tick0_excess": unit_eval_tick0_excess, "unit_amendment": unit_amendment,
    "unit_analysis_end_to_end": unit_analysis_end_to_end, "unit_left_entries": unit_left_entries,
    "unit_isolation": unit_isolation,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {"game_provisional_label": game_provisional_label}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def archived_state() -> Dict[str, Any]:
    """The archived trees the suite must never touch."""
    pk = REPO_ROOT / "runs" / "m7g_k"
    return {"m7g_k_listing": sorted(p.name for p in pk.iterdir()) if pk.is_dir() else [],
            "m7g_k_matrix": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((pk / "_matrix").glob("*.json"))}
            if (pk / "_matrix").is_dir() else {},
            "gate_listing": sorted(p.name for p in GATE.iterdir()) if GATE.is_dir() else [],
            "gate_results": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((GATE / "results").glob("*.json"))}
            if (GATE / "results").is_dir() else {},
            "campaign_root_exists": hm.DEFAULT_ROOT.exists(),
            "docs_manifest": hashlib.sha256(hm.MANIFEST_DOC.read_bytes()).hexdigest() if hm.MANIFEST_DOC.is_file() else None}


def main(argv: Optional[List[str]] = None) -> int:
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
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / "m7h" / "_readiness" / f"campaign_tests_{utc}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    leaked = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
    if leaked:
        raise SystemExit(f"SSB64_* variables in the environment would leak into every child: {leaked}")
    before = archived_state()
    suite = Suite(root)
    results: Dict[str, Any] = {}
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            results[name] = {"status": "PASS", "seconds": round(time.perf_counter() - t0, 1), "details": details}
        except Exception as exc:  # noqa: BLE001
            results[name] = {"status": "FAIL", "seconds": round(time.perf_counter() - t0, 1),
                             "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-3000:]}
        finally:
            hm.configure_root(None)
        print(f"{results[name]['status']}  {name}  ({results[name]['seconds']} s)"
              + (f"  {results[name].get('error')}" if results[name]["status"] != "PASS" else ""), flush=True)
    after = archived_state()
    untouched = before == after
    print(f"{'PASS' if untouched else 'FAIL'}  archived trees unchanged (runs/m7g_k bookkeeping, runs/m7h/_gate, "
          f"no runs/m7h/campaign, docs manifest)", flush=True)
    ok = untouched and all(r["status"] == "PASS" for r in results.values())
    with open(root / "m7h_campaign_tests_results.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump({"schema": "battleship_m7h_campaign_tests_v1", "utc": utc, "results": results,
                   "archived_trees_unchanged": untouched, "ok": ok}, fp, indent=1, default=str)
        fp.write("\n")
    print(f"m7h_campaign_tests: {sum(r['status'] == 'PASS' for r in results.values())}/{len(results)} PASS "
          f"(+ archive check {'PASS' if untouched else 'FAIL'}) -> {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
