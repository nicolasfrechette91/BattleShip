#!/usr/bin/env python3
"""M7m: registration and the no-training feasibility gate (F1-F5) of the anchored backward sweep curriculum.

Design: docs/rl_sweep_consolidation_m7m_design.md. The plan executed here is m7m_anchor.registered_plan(), written to
docs/rl_sweep_consolidation_m7m_feasibility_plan.json by `register` BEFORE any check runs (write-once: a registration
file is never rewritten with different content).

Nothing here trains: policies are frozen Phase K reward-v2 finals (runs/m7g_k/m7g_s{0,1,2}_v1/final) evaluated with
frozen VecNormalize statistics, exactly as the evaluator does. The anchor supplies start states only (explicit native
action-prefix replay after the ordinary non-consuming tick-0 reset); the user's crossing fixtures and TAS are never read.

One harness episode = one fresh BattleShip process: tick-0 `observe` (input_tick 0, nothing consumed) -> the prefix
(anchor rows 0..tau-1, each must consume tick i and stay WaitingForAction) -> the post-prefix observation and target
mask must equal the registered F1 table -> frozen-policy actions from input tick tau. Rewards are btt_reward_v2 via
the project's reward_step, rebased on the post-prefix observation (prefix breaks earn nothing).

    python rl/m7m_feasibility.py register | f1 | f2 | f3 | validate | f4 | f5 | verify | summarize | status

Outputs: runs/m7m/feasibility/ (git-ignored). Registered files: docs/rl_sweep_consolidation_m7m_{anchor,
feasibility_plan,anchor_observations}.json. Stops (a failed launch gate, available commit < 3 GiB, an integrity or
provenance mismatch, a leftover game process) end the command with a non-zero exit and keep every episode written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7h_curriculum as mc  # noqa: E402
import m7m_anchor as ma  # noqa: E402

REPO = ma.REPO_ROOT
OUT = REPO / "runs" / "m7m" / "feasibility"
EXE = REPO / "build-us" / "Release" / "BattleShip.exe"
EXPECTED_EXE_SHA = "1e7c62a05a9397fb4ef1d404d85a793cd01c4dbdc187068e3a63890cb5cbeb97"
ENV = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_TARGET_DIAG": "1"}
OBS = "btt_policy_obs_v1"
PLAN_FILE = REPO / "docs" / "rl_sweep_consolidation_m7m_feasibility_plan.json"
PLAN_SCHEMA = "m7m_feasibility_plan_v1"
SOURCE_RUN_DIR = REPO / "runs" / "m7l" / "campaign" / ma.ANCHOR_SOURCE_RUN
SOURCE_ARTIFACT = SOURCE_RUN_DIR / "workers" / "w00" / "artifacts" / ma.ANCHOR_EPISODE_ID
SOURCE_REPLAY = REPO / "runs" / "m7l" / "campaign" / "_replays" / "training_sweep_s1" / "summary.json"
WARM_STARTS = {j: REPO / "runs" / "m7g_k" / f"m7g_s{j}_v1" / "final" for j in ma.F4_SEEDS}
PHASE_K_EVAL = {j: REPO / "runs" / "m7g_k" / "_eval" / f"m7g_s{j}_v1" / "final" for j in ma.F4_SEEDS}
M7L_CONTROL_CHECK = REPO / "runs" / "m7l" / "campaign" / "_control" / "control_check.json"
STOP_COMMIT_GIB = 3.0
WARN_COMMIT_GIB = 4.0
GATE_READINGS, GATE_RETRY_S = 5, 60.0
POOL_RANKS = {0: 1, 1: 2, 2: 3}                 # seed -> port block rank (one game process per harness process)
VERIFY_MAX = 150

EXIT_OK, EXIT_FAILED, EXIT_STOPPED = 0, 1, 3


class IntegrityError(RuntimeError):
    """An exactness, provenance or registration violation: the checks stop."""


class ResourceStop(RuntimeError):
    """The in-run memory policy or the launch gate stopped the checks."""


def log(msg: str) -> None:
    print(f"[m7m {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(p: Path, doc: Any) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(doc, indent=1, default=str) + "\n").encode("utf-8")
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return hashlib.sha256(data).hexdigest()


def write_once(p: Path, doc: Any) -> str:
    """A registration file: written once; an existing file must be byte-identical (never silently altered)."""
    data = (json.dumps(doc, indent=1, sort_keys=False) + "\n").encode("utf-8")
    if p.exists():
        if p.read_bytes() != data:
            raise IntegrityError(f"{p.relative_to(REPO)} exists with different content; registration is write-once")
        return hashlib.sha256(data).hexdigest()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def append_jsonl(p: Path, rec: Mapping[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as fp:
        fp.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.is_file():
        return []
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]


def head_revision() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()


# -- resource gates ------------------------------------------------------------------------------------------------


def launch_gate(tag: str) -> Dict[str, Any]:
    """The registered launch gate (commit >= 10 GiB AND physical >= 4 GiB, disk, CPU, no game, free ports); a failed
    reading is re-measured 60 s later, at most 5 readings."""
    import m7h_guard as g

    readings = []
    for i in range(GATE_READINGS):
        r = g.launch_gate()
        m = r.get("measurement") or {}
        readings.append({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ok": r["ok"], "problems": r["problems"],
                         "avail_commit_gib": m.get("avail_commit_gib"), "avail_phys_gib": m.get("avail_phys_gib"),
                         "cpu_mean_pct": m.get("cpu_mean_pct")})
        if r["ok"]:
            log(f"{tag}: launch gate ok (commit {m.get('avail_commit_gib')} GiB, physical {m.get('avail_phys_gib')} GiB)")
            return {"ok": True, "tag": tag, "readings": readings}
        log(f"{tag}: launch gate reading {i + 1} failed {r['problems']}")
        if i < GATE_READINGS - 1:
            time.sleep(GATE_RETRY_S)
    return {"ok": False, "tag": tag, "readings": readings}


def memory_check(tag: str) -> Dict[str, Any]:
    from m7d_run import memory_status

    ms = memory_status()
    c = ms.get("avail_commit_gib")
    if c is None or float(c) < STOP_COMMIT_GIB:
        raise ResourceStop(f"{tag}: available commit {c} GiB < {STOP_COMMIT_GIB} GiB (in-run stop)")
    if float(c) < WARN_COMMIT_GIB:
        log(f"{tag}: warning, available commit {c} GiB < {WARN_COMMIT_GIB} GiB")
    return ms


def leftover_processes() -> List[int]:
    from m7_runtime import list_processes_named

    return list(list_processes_named() or [])


def check_executable() -> None:
    if sha256_file(EXE) != EXPECTED_EXE_SHA:
        raise IntegrityError("the executable differs from the registered build")


# -- policy ----------------------------------------------------------------------------------------------------------


def load_policy(seed: int) -> Tuple[Any, Any, Dict[str, Any]]:
    import torch

    import m7_evaluation as me
    from m7_trainer import M7PPO

    torch.set_num_threads(1)
    ck = WARM_STARTS[seed]
    meta = me.read_checkpoint_set(ck)
    model = M7PPO.load(str(ck / "model.zip"), device="cpu")
    me.check_model_identity(model, OBS)
    with open(ck / "vecnormalize.pkl", "rb") as fp:
        vn = pickle.load(fp)
    me.check_vecnormalize_identity(vn, OBS)
    vn.training = False
    vn.norm_reward = False
    info = {"checkpoint": ck.relative_to(REPO).as_posix(), "num_timesteps": meta.get("num_timesteps"),
            "files_sha256": {n: sha256_file(ck / n) for n in ("checkpoint.json", "model.zip", "vecnormalize.pkl")},
            "policy_parameter_digest": me.policy_parameter_digest(model), "obs_rms_digest": me.obs_rms_digest(vn),
            "obs_rms_count": float(vn.obs_rms.count)}
    return model, vn, info


def check_policy_identity(seed: int, info: Mapping[str, Any]) -> None:
    reg = registered_warm_start(seed)
    for k in ("files_sha256", "policy_parameter_digest", "obs_rms_digest", "num_timesteps"):
        if info.get(k) != reg.get(k):
            raise IntegrityError(f"warm start s{seed}: {k} differs from the registration")


def registered_warm_start(seed: int) -> Dict[str, Any]:
    plan = read_json(PLAN_FILE)
    return next(w for w in plan["warm_starts"] if int(w["seed"]) == int(seed))


# -- one harness episode ---------------------------------------------------------------------------------------------


def run_episode(*, work: Path, rank: int, index: int, prefix: bytes, expected: Optional[Mapping[str, Any]],
                policy: Optional[Tuple[Any, Any]], deterministic: bool, seed: Optional[int], stop_rule: str,
                capture_obs_rows: int = 0) -> Dict[str, Any]:
    """stop_rule: 'natural' (native clear / failure / horizon), 'f4' (also success, or the step that consumed the
    deadline tick 2699), 'replay' (policy None: the prefix is the whole trajectory; ends after the last row)."""
    import numpy as np  # noqa: F401 - policy input
    import torch

    import m7f_targets as ft
    import m7f_trace as tr
    from battleship_client import StepState
    from battleship_process import BattleShipEpisode, LaunchConfig
    from btt_learning import live_targets, policy_observation
    from btt_parallel import is_native_failure
    from btt_rewards import REWARD_V2, reward_step
    from m7_runtime import PortCandidates, prepare_worker_runtime, remove_worker_runtime
    from stable_baselines3.common.utils import set_random_seed

    work = Path(work).resolve()
    shutil.rmtree(work, ignore_errors=True)
    runtime = work / "runtime"
    prepare_worker_runtime(runtime, EXE)
    port, _busy = PortCandidates(rank).claim()
    (work / "episodes").mkdir(parents=True, exist_ok=True)
    cfg = LaunchConfig(executable=EXE, working_dir=runtime, run_root=work / "episodes", port=port,
                       startup_timeout=30.0, ready_timeout=90.0, request_timeout=15.0, exit_timeout=30.0,
                       extra_env=dict(ENV))
    if seed is not None:
        set_random_seed(seed)
    tau = len(prefix)
    rows: List[Tuple[int, int, int, int]] = []
    track1: List[int] = []
    replies: List[Dict[str, Any]] = []
    obs_rows: List[Dict[str, Any]] = []
    masks: List[int] = []
    first: Dict[int, int] = {}
    terms = {"target_term": 0.0, "step_term": 0.0, "clear_term": 0.0, "failure_term": 0.0}
    rec: Dict[str, Any] = {"tau": tau, "deterministic": deterministic, "seed": seed, "stop_rule": stop_rule}
    t0 = time.perf_counter()
    mask = 0
    first_left: Optional[int] = None

    def note(t: int, reply: Mapping[str, Any]) -> None:
        nonlocal mask, first_left
        if reply.get("targets") is None:
            raise IntegrityError(f"tick {t}: step reply without a target table (diagnostic flag missing)")
        m = ft.parse_targets(reply["targets"]).broken_mask
        if m & mask != mask:
            raise IntegrityError(f"tick {t}: a broken target became unbroken")
        for i in ft.mask_ids(m & ~mask):
            first[int(i)] = int(t)
        mask = m
        masks.append(m)
        o = reply["observation"]
        if first_left is None and int(o["fighter_valid"]) == 1 and int(o["btt_active"]) == 1 \
                and float(o["position_x"]) < mc.LEFT_BOUNDARY_X:
            first_left = int(t)

    ep = BattleShipEpisode(cfg, index=index)
    end = None
    with ep:
        ep.start()
        client = ep.client
        tr._capture_requests(client, replies)
        client.request("status")
        initial = client.request("observe")
        o0 = initial["observation"]
        if int(o0["input_tick"]) != 0 or int(o0["targets_remaining"]) != ma.TARGETS_TOTAL:
            raise IntegrityError(f"reset observation input_tick {o0['input_tick']}, targets {o0['targets_remaining']}")
        last = o0
        state = None
        for i, a in enumerate(prefix):                         # the explicit prefix phase
            b, x, y = mc.track1_triple(a)
            r = client.step(b, x, y)
            if r.consumed_tick != i or (r.state != StepState.WAITING_FOR_ACTION and not (stop_rule == "replay"
                                                                                           and i == tau - 1)):
                raise IntegrityError(f"prefix row {i}: consumed {r.consumed_tick}, state {r.state_name}")
            rows.append((b, x, y, int(r.consumed_tick)))
            track1.append(int(a))
            note(i, replies[-1])
            last = replies[-1]["observation"]
            state = r.state
            if i < capture_obs_rows:
                obs_rows.append(mc.observation_dict(last))
        rec["prefix_wall_s"] = round(time.perf_counter() - t0, 3)
        if expected is not None:
            diffs = mc.observation_diffs(mc.observation_dict(last), expected)
            if diffs or mask != int(expected["broken_mask"]):
                raise IntegrityError(f"cut {tau}: post-prefix state differs from the table: {diffs} mask {mask:#x}")
            rec["o_tau_equal_table"] = True
            rec["o_tau_host_frame_equal"] = last.get("host_frame") == expected.get("host_frame")
        rec["o_tau"] = {k: last[k] for k in ("position_x", "position_y", "ground_air_state", "fighter_status_id",
                                               "jumps_used", "targets_remaining", "air_velocity_x", "air_velocity_y")}
        prev_targets = live_targets(last)
        t = tau
        if policy is None:
            end = "replay_end" if state == StepState.WAITING_FOR_ACTION else f"replay_state_{state}"
        else:
            model, vn = policy
            obs_vec = policy_observation(last)
            while True:                                         # normal policy actions
                with torch.no_grad():
                    act, _ = model.predict(vn.normalize_obs(obs_vec[None, :]), deterministic=deterministic)
                a = mc.encode_track1(int(act[0][0]), int(act[0][1]))
                b, x, y = mc.track1_triple(a)
                r = client.step(b, x, y)
                if r.consumed_tick != t:
                    raise IntegrityError(f"policy row {t}: consumed {r.consumed_tick}")
                rows.append((b, x, y, int(r.consumed_tick)))
                track1.append(int(a))
                note(t, replies[-1])
                o = replies[-1]["observation"]
                ended = r.state == StepState.EPISODE_ENDED
                failure = is_native_failure(r.observation, r.state)
                clear = ended and int(o["btt_active"]) == 1 and int(o["targets_remaining"]) == 0
                cur = live_targets(o)
                rt = reward_step(prev_targets, cur, clear=clear, native_failure=failure, contract=REWARD_V2)
                prev_targets = cur
                for k in terms:
                    terms[k] += getattr(rt, k)
                t += 1
                if ended or failure:
                    end = "clear" if clear else ("fall" if failure else "ended_not_clear")
                    if ended:
                        done = ep.finish(r)
                        rec["exit_code"] = done.exit_code
                    break
                if t >= ma.HORIZON:
                    end = "horizon"
                    break
                if stop_rule == "f4":
                    if all(i in first for i in ma.RIGHT_IDS):
                        end = "success_stop"
                        break
                    if t > ma.DEADLINE_CONSUMED_TICK:
                        end = "deadline"
                        break
                obs_vec = policy_observation(o)
    remove_worker_runtime(runtime)
    shutil.rmtree(work / "episodes", ignore_errors=True)
    rec.update(end=end, rows=len(rows), policy_steps=len(rows) - tau, wall_s=round(time.perf_counter() - t0, 3),
               digest=mc.native_digest(rows), actions_hex=bytes(track1).hex(),
               reward={k: round(v, 6) for k, v in terms.items()}, ret=round(sum(terms.values()), 6),
               first_break_ticks={str(k): v for k, v in sorted(first.items())}, first_left_tick=first_left,
               final_mask=mask)
    rec["outcome"] = ma.sweep_outcome(tau=tau, first_break_ticks=first,
                                      end_reason={"success_stop": None, "deadline": None, "clear": "clear"}.get(end, end),
                                      policy_steps=len(rows) - tau)
    if capture_obs_rows:
        rec["_obs_rows"] = obs_rows
        rec["_masks"] = masks[:capture_obs_rows]
        rec["_final_observation"] = mc.observation_dict(last if policy is None else replies[-1]["observation"])
    return rec


# -- register ----------------------------------------------------------------------------------------------------------


def artifact_rows() -> Tuple[List[Tuple[int, int, int, int]], List[int]]:
    """The source artifact's native rows and their Track 1 indices (each triple must be exactly one Track 1 action)."""
    from btt_learning import TRACK1_BUTTON_TABLE, TRACK1_STICK_TABLE

    lookup: Dict[Tuple[int, int, int], int] = {}
    for s, (x, y) in enumerate(TRACK1_STICK_TABLE):
        for bi, b in enumerate(TRACK1_BUTTON_TABLE):
            key = (int(b), int(x), int(y))
            if key in lookup:
                raise IntegrityError(f"Track 1 table maps {key} twice")
            lookup[key] = mc.encode_track1(s, bi)
    rows, idx = [], []
    for n, line in enumerate(open(SOURCE_ARTIFACT / "actions.jsonl", encoding="utf-8")):
        r = json.loads(line)
        triple = (int(r["buttons"]), int(r["stick_x"]), int(r["stick_y"]))
        if int(r["sequence_index"]) != n or int(r["consumed_tick"]) != n:
            raise IntegrityError(f"artifact row {n}: sequence {r['sequence_index']} consumed {r['consumed_tick']}")
        if triple not in lookup:
            raise IntegrityError(f"artifact row {n}: native {triple} is not a Track 1 action")
        rows.append((*triple, n))
        idx.append(lookup[triple])
    return rows, idx


def source_training_row() -> Dict[str, Any]:
    for line in open(SOURCE_RUN_DIR / "metrics" / "episodes.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("episode_id") == ma.ANCHOR_EPISODE_ID:
            return r
    raise IntegrityError("the source episode is not in the M7l training rows")


def reward_v3_t2_sha(labels: Mapping[str, Any]) -> str:
    """The canonical sha256 of the source's reward contract (the M7l registration), checked against the artifact."""
    from btt_rewards import REWARD_V3_T2
    from m7l_matrix import REWARD_V3_T2_SHA256, canonical_sha256

    exp = labels.get("experiment") or {}
    if exp.get("reward_contract") != ma.ANCHOR_SOURCE_REWARD or exp.get("reward_canonical") is not True             or canonical_sha256(REWARD_V3_T2.to_json()) != REWARD_V3_T2_SHA256:
        raise IntegrityError("the source artifact's reward contract is not the registered btt_reward_v3_t2")
    return REWARD_V3_T2_SHA256


def anchor_record() -> Dict[str, Any]:
    rows, idx = artifact_rows()
    row = source_training_row()
    meta = read_json(SOURCE_ARTIFACT / "metadata.json")
    rep = read_json(SOURCE_REPLAY)
    breaks = {int(i): int(t) for i, t in rep["breaks"]}
    actions = bytes(idx)
    if not (rep["exact"]["digest_equal"] and rep["exact"]["consumed_tick_mismatch"] is None and rep["exact"]["unsent"] == 0):
        raise IntegrityError("the M7l replay of the source is not exact")
    for name, d in (("artifact rows", mc.native_digest(rows)), ("Track 1 re-encoding", mc.prefix_digest(actions)),
                    ("training row", row["native_action_digest"]), ("M7l replay", rep["item"]["reference_digest"])):
        if d != ma.ANCHOR_NATIVE_DIGEST:
            raise IntegrityError(f"{name} digest {d[:16]} != pinned {ma.ANCHOR_NATIVE_DIGEST[:16]}")
    if breaks != ma.ANCHOR_RIGHT_BREAKS or sorted(breaks.values()) != sorted(row["target_break_ticks"]):
        raise IntegrityError(f"source breaks {breaks} / {row['target_break_ticks']} != registered {ma.ANCHOR_RIGHT_BREAKS}")
    lab = meta["labels"]
    return {
        "schema": ma.ANCHOR_SCHEMA, "anchor_id": ma.ANCHOR_ID,
        "purpose": "M7m anchored backward consolidation (docs/rl_sweep_consolidation_m7m_design.md)",
        "permitted_use": ("start states ONLY: an explicit native action-prefix replay of rows 0..tau-1 (1 <= tau <= "
                          f"{ma.MAX_CUT}) after a normal non-consuming tick-0 reset"),
        "authorization": {"by": "the user", "date": "2026-09-25",
                          "scope": "cross-run use of this trajectory solely to supply start states through explicit "
                                   "native action-prefix replay after a normal tick-0 reset"},
        "exclusions": ["never supervised training targets (no behaviour cloning, no imitation or action loss)",
                       "never a transfer of the source run's policy weights, optimizer or normalisation statistics",
                       "the user's crossing fixtures and TAS are never training material or inputs of any kind"],
        "classification": "replay-verified M7l training event, not a learned result",
        "source": {"run_id": ma.ANCHOR_SOURCE_RUN, "episode_id": ma.ANCHOR_EPISODE_ID,
                   "reward_contract": row["reward_contract"],
                   "reward_contract_note": "discovered by a policy trained under btt_reward_v3_t2 (M7l arm T, seed 1); "
                                           "M7m trains and evaluates under btt_reward_v2 only",
                   "reward_canonical_sha256": reward_v3_t2_sha(lab),
                   "rank": row["rank"], "worker_episode": row["worker_episode"],
                   "sb3_num_timesteps_at_start": lab.get("sb3_num_timesteps_at_start"),
                   "sb3_num_timesteps_at_end": row.get("sb3_num_timesteps_at_end"),
                   "checkpoint_label_at_start": lab.get("checkpoint_label"),
                   "start": "tick 0 (M7l has no curriculum)", "startup_mode": row.get("startup_mode"),
                   "artifact_dir": SOURCE_ARTIFACT.relative_to(REPO).as_posix(),
                   "artifact_actions_sha256": sha256_file(SOURCE_ARTIFACT / "actions.jsonl"),
                   "artifact_metadata_sha256": sha256_file(SOURCE_ARTIFACT / "metadata.json"),
                   "training_row": {k: row.get(k) for k in ("end_reason", "steps", "return", "targets_broken",
                                                            "target_break_ticks", "native_action_digest", "cleared")},
                   "m7l_replay": {"summary": SOURCE_REPLAY.relative_to(REPO).as_posix(),
                                  "summary_sha256": sha256_file(SOURCE_REPLAY), "exact": rep["exact"]}},
        "trajectory": {"rows": len(actions), "native_action_digest": ma.ANCHOR_NATIVE_DIGEST,
                       "track1_actions_sha256": hashlib.sha256(actions).hexdigest(),
                       "track1_actions_hex": actions.hex(), "end": "horizon (3,600 rows; no clear, no fall)",
                       "right_breaks": {str(k): v for k, v in sorted(ma.ANCHOR_RIGHT_BREAKS.items(), key=lambda kv: kv[1])},
                       "targets_broken": 7, "left_entry": False},
        "use": {"min_cut": ma.MIN_CUT, "max_cut": ma.MAX_CUT,
                "cut_semantics": ma.registered_plan()["cut_semantics"]},
        "executable_sha256": EXPECTED_EXE_SHA,
    }


def warm_start_record(seed: int) -> Dict[str, Any]:
    _model, _vn, info = load_policy(seed)
    ev = {}
    for mode in ("deterministic", "stochastic"):
        d = read_json(PHASE_K_EVAL[seed] / mode / "evaluation.json")
        eps = d["episodes"]
        ev[mode] = {"episodes": len(eps), "distinct_digests": len({e["native_action_digest"] for e in eps}),
                    "falls": sum(1 for e in eps if e.get("end_reason") == "fall"),
                    "mean_length": round(sum(int(e["length"]) for e in eps) / len(eps), 1)}
        if mode == "deterministic":
            ev[mode]["digests"] = sorted({e["native_action_digest"] for e in eps})
            ev[mode]["raw_returns"] = sorted({round(float(e["raw_return"]), 6) for e in eps})
    cc = read_json(M7L_CONTROL_CHECK) if M7L_CONTROL_CHECK.is_file() else {}
    return {"seed": seed, "arm_use": "warm start of both paired arms (E and K) of seed pair " + str(seed),
            "run": f"m7g_s{seed}_v1 (Phase K control, btt_policy_obs_v1, btt_reward_v2, fresh model at t=0)",
            **info, "phase_k_final_evaluation": ev,
            "m7l_control_check": {"file": M7L_CONTROL_CHECK.relative_to(REPO).as_posix(),
                                  "ok": cc.get("ok"), "sha256": sha256_file(M7L_CONTROL_CHECK) if cc else None}}


def cmd_register(args: argparse.Namespace) -> int:  # noqa: ARG001
    check_executable()
    anchor = anchor_record()
    ma.anchor_from_record(anchor)                       # the module's own integrity checks
    a_sha = write_once(ma.ANCHOR_FILE, anchor)
    plan = {"schema": PLAN_SCHEMA, "design": "docs/rl_sweep_consolidation_m7m_design.md",
            "registered_before_any_check": True, "head": head_revision(),
            "anchor_file": {"path": ma.ANCHOR_FILE.relative_to(REPO).as_posix(), "sha256": a_sha},
            "executable_sha256": EXPECTED_EXE_SHA, "native_flags": dict(ENV),
            "harness": "rl/m7m_feasibility.py (plan = m7m_anchor.registered_plan())",
            "warm_starts": [warm_start_record(j) for j in ma.F4_SEEDS],
            "plan": ma.registered_plan()}
    p_sha = write_once(PLAN_FILE, plan)
    log(f"registered anchor {a_sha[:16]} plan {p_sha[:16]}")
    print(json.dumps({"anchor_sha256": a_sha, "plan_sha256": p_sha}))
    return EXIT_OK


def registered_plan_checked() -> Dict[str, Any]:
    plan = read_json(PLAN_FILE)
    if plan["plan"] != json.loads(json.dumps(ma.registered_plan())):
        raise IntegrityError("the code's plan differs from the registered plan")
    if sha256_file(ma.ANCHOR_FILE) != plan["anchor_file"]["sha256"]:
        raise IntegrityError("the anchor file differs from the registration")
    return plan


# -- F1: exact source replays -> the observation table ---------------------------------------------------------------


def cmd_f1(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    registered_plan_checked()
    check_executable()
    anchor = ma.load_anchor()
    gate = launch_gate("F1")
    if not gate["ok"]:
        write_json(OUT / "f1_gate_refused.json", gate)
        return EXIT_STOPPED
    reps, tables = [], []
    for r in range(ma.F1_REPLAYS):
        memory_check(f"F1 replay {r}")
        rec = run_episode(work=OUT / "work" / "f1", rank=1, index=9500 + r, prefix=anchor.actions, expected=None,
                          policy=None, deterministic=True, seed=None, stop_rule="replay", capture_obs_rows=ma.MAX_CUT)
        obs, masks, final = rec.pop("_obs_rows"), rec.pop("_masks"), rec.pop("_final_observation")
        meta = read_json(SOURCE_ARTIFACT / "metadata.json")
        breaks = {int(k): v for k, v in rec["first_break_ticks"].items()}
        final_diffs = mc.observation_diffs(final, meta["final_observation"])
        ok = (rec["digest"] == ma.ANCHOR_NATIVE_DIGEST and rec["rows"] == ma.ANCHOR_ROWS and rec["end"] == "replay_end"
              and breaks == ma.ANCHOR_RIGHT_BREAKS and rec["first_left_tick"] is None and not final_diffs)
        reps.append({"replay": r, "ok": ok, "digest": rec["digest"], "rows": rec["rows"], "end": rec["end"],
                     "breaks": rec["first_break_ticks"], "first_left_tick": rec["first_left_tick"],
                     "final_observation_diffs": final_diffs,
                     "final_host_frame_equal": final.get("host_frame") == meta["final_observation"].get("host_frame"),
                     "wall_s": rec["wall_s"]})
        tables.append((obs, masks))
        log(f"F1 replay {r}: {'exact' if ok else 'MISMATCH'} digest {rec['digest'][:16]} breaks {rec['first_break_ticks']}")
    same = all(len(t[0]) == ma.MAX_CUT and t[1] == tables[0][1] and
               all(not mc.observation_diffs(a, b) for a, b in zip(t[0], tables[0][0])) for t in tables)
    host_same = all(all(a.get("host_frame") == b.get("host_frame") for a, b in zip(t[0], tables[0][0])) for t in tables)
    ok = all(x["ok"] for x in reps) and same
    doc: Dict[str, Any] = {"check": "F1", "ok": ok, "replays": reps, "tables_identical_except_host_frame": same,
                           "tables_host_frame_identical": host_same, "leftover_processes": leftover_processes()}
    if ok:
        table = ma.observation_table_doc(tables[0][0], tables[0][1],
                                         [{"replay": x["replay"], "digest": x["digest"]} for x in reps])
        t_sha = write_once(ma.OBS_TABLE_FILE, table)
        ma.load_observation_table(t_sha)                 # the module's own checks (masks = registered breaks)
        doc["observation_table"] = {"path": ma.OBS_TABLE_FILE.relative_to(REPO).as_posix(), "sha256": t_sha,
                                    "bytes": ma.OBS_TABLE_FILE.stat().st_size}
    ok = ok and not doc["leftover_processes"]
    doc["ok"] = ok
    write_json(OUT / "f1.json", doc)
    log(f"F1 {'PASS' if ok else 'FAIL'}")
    return EXIT_OK if ok else EXIT_FAILED


def table_sha() -> str:
    f1 = read_json(OUT / "f1.json")
    if not f1.get("ok"):
        raise IntegrityError("F1 did not pass")
    return f1["observation_table"]["sha256"]


# -- F2: the Track 1 encoding --------------------------------------------------------------------------------------


def cmd_f2(args: argparse.Namespace) -> int:  # noqa: ARG001
    registered_plan_checked()
    anchor = ma.load_anchor()
    rows, idx = artifact_rows()
    reenc = [(*mc.track1_triple(a), i) for i, a in enumerate(idx)]
    row = source_training_row()
    checks = {
        "artifact_rows_are_track1": len(idx) == ma.ANCHOR_ROWS,
        "artifact_consumed_ticks_0_to_3599": [r[3] for r in rows] == list(range(ma.ANCHOR_ROWS)),
        "artifact_digest_equals_training_row": mc.native_digest(rows) == row["native_action_digest"],
        "reencoded_triples_equal_artifact": reenc == rows,
        "reencoded_digest_equals_pinned": mc.native_digest(reenc) == ma.ANCHOR_NATIVE_DIGEST,
        "registered_bytes_equal_artifact_indices": bytes(idx) == anchor.actions,
        "artifact_files_equal_registration": (
            sha256_file(SOURCE_ARTIFACT / "actions.jsonl") == anchor.record["source"]["artifact_actions_sha256"]
            and sha256_file(SOURCE_ARTIFACT / "metadata.json") == anchor.record["source"]["artifact_metadata_sha256"]),
    }
    ok = all(checks.values())
    write_json(OUT / "f2.json", {"check": "F2", "ok": ok, "checks": checks, "rows": len(rows)})
    log(f"F2 {'PASS' if ok else 'FAIL'} {checks}")
    return EXIT_OK if ok else EXIT_FAILED


# -- F3: cut mechanics through the M7m training worker (in-process) ----------------------------------------------------


def window_of(tau: int) -> int:
    for k, (_p, lo, hi) in enumerate(ma.WINDOWS):
        if lo <= tau <= hi:
            return k
    raise ma.AnchorError(f"cut {tau} is in no window")


def cmd_f3(args: argparse.Namespace) -> int:  # noqa: ARG001
    import numpy as np

    from btt_learning import POLICY_FIELDS
    from btt_parallel import RunCoordinator, WorkerSpec, initial_coordination_state
    from btt_rewards import REWARD_V2
    from m7_runtime import install_kill_on_close_job, prepare_worker_runtime, remove_worker_runtime
    from m7d_run import validate_episode_row
    from m7h_vec import policy_observation_from_dict
    from m7m_worker import AnchorWorkerFactory, prefix_spec

    install_kill_on_close_job()
    registered_plan_checked()
    check_executable()
    sha = table_sha()
    anchor = ma.load_anchor()
    table = ma.load_observation_table(sha)
    settings = ma.registered_table(tick0_probability=ma.TICK0_PROBABILITY_E, observation_table_sha256=sha)
    gate = launch_gate("F3")
    if not gate["ok"]:
        write_json(OUT / "f3_gate_refused.json", gate)
        return EXIT_STOPPED
    root = OUT / "f3"
    shutil.rmtree(root, ignore_errors=True)
    coord = root / "coord"
    run_id = "m7m_f3"
    RunCoordinator.create(coord, initial_coordination_state(run_id, "test", 0))
    wdir = root / "w00"
    prepare_worker_runtime(wdir / "runtime", EXE)
    spec = WorkerSpec(rank=4, run_id=run_id, role="test", worker_dir=str(wdir), coordination_dir=str(coord),
                      executable=str(EXE), horizon=ma.HORIZON, base_seed=0, extra_env=tuple(ENV.items()),
                      reward_contract=REWARD_V2, experiment=None, standby_preboot=False, standby_count=0,
                      preserve_all=True)
    env = AnchorWorkerFactory(spec, settings)()
    cuts = list(ma.F3_LANDMARK_CUTS) + ma.f3_random_cuts()
    results: List[Dict[str, Any]] = []
    full: List[Dict[str, Any]] = []
    sink = OUT / "f3_cuts.jsonl"
    sink.unlink(missing_ok=True)
    try:
        for tau in cuts:
            memory_check(f"F3 cut {tau}")
            env.reset()
            s = prefix_spec(anchor, table, tau=tau, window_index=window_of(tau), run_id=run_id)
            reply = env.run_prefix_phase(s)
            st = reply["start"]
            want = policy_observation_from_dict(table[tau - 1])
            rec = env.recording.recorder
            lab = rec.labels.get(mc.START_LABEL) or {}
            r = {"tau": tau, "kind": st["kind"], "delivered_equals_table": bool(np.array_equal(reply["observation"], want)),
                 "prefix_length": st.get("prefix_length"), "mask": st.get("prefix_broken_mask"),
                 "mask_registered": ma.broken_mask_at(tau), "standing_right": st.get("standing_right"),
                 "reward_reference": st.get("reward_reference_targets_remaining"),
                 "host_frame_equal": st.get("prefix_host_frame_equal"),
                 "label_rows": mc.prefix_rows(rec.labels, rec.action_count), "label_contract": lab.get("contract")}
            before = int(table[tau - 1]["targets_remaining"])
            # the first policy step: neutral (stick 0, no button), except at a full cut, where it is anchor row tau
            first = mc.decode_track1(anchor.actions[tau]) if tau in ma.F3_FULL_CUTS else (0, 0)
            obs, rew, term, trunc, info = env.step(np.array(first, dtype=np.int64))
            after = int(round(float(obs[POLICY_FIELDS.index("targets_remaining")])))
            r["first_step_reward"] = float(rew)
            r["first_step_reward_ok"] = term or abs(float(rew) - (-0.001 + (before - after))) < 1e-9
            r["rows_after_one_step"] = mc.prefix_rows(rec.labels, rec.action_count)
            r["ok"] = (r["kind"] == mc.START_PREFIX and r["delivered_equals_table"] and r["prefix_length"] == tau
                       and r["mask"] == r["mask_registered"] and r["reward_reference"] == ma.TARGETS_TOTAL - bin(r["mask"]).count("1")
                       and tuple(r["standing_right"]) == ma.standing_right(tau) and r["label_rows"] == (tau, mc.START_PREFIX)
                       and r["label_contract"] == ma.CONTRACT_ID and r["first_step_reward_ok"]
                       and r["rows_after_one_step"] == (tau, mc.START_PREFIX) and rec.action_count == tau + 1)
            if tau in ma.F3_FULL_CUTS:                      # the anchor's own remaining rows through step()
                total_r = float(rew)
                steps = 1
                summary = None
                for a in anchor.actions[tau + 1:]:
                    stick, button = mc.decode_track1(a)
                    obs, rew, term, trunc, info = env.step(np.array([stick, button], dtype=np.int64))
                    total_r += float(rew)
                    steps += 1
                    if term or trunc:
                        summary = info.get("m7_episode")
                        break
                policy_breaks = sum(1 for b in ma.ANCHOR_RIGHT_BREAKS.values() if b >= tau)
                want_ret = policy_breaks - 0.001 * (ma.HORIZON - tau)
                probs = validate_episode_row(summary or {}, REWARD_V2, ma.HORIZON) if summary else ["no summary"]
                out = (summary or {}).get("m7m") or {}
                f = {"tau": tau, "policy_steps": steps, "want_policy_steps": ma.HORIZON - tau,
                     "return": round(total_r, 6), "want_return": round(want_ret, 6),
                     "summary_return": (summary or {}).get("return"), "end_reason": (summary or {}).get("end_reason"),
                     "digest_equals_anchor": (summary or {}).get("native_action_digest") == ma.ANCHOR_NATIVE_DIGEST,
                     "validator_problems": probs, "outcome_success": out.get("success"),
                     "outcome_policy_right_breaks": out.get("policy_right_breaks"),
                     "m7h_block": {k: ((summary or {}).get("m7h") or {}).get(k) for k in ("prefix_length", "policy_steps",
                                                                                        "rows", "rows_equal_prefix_plus_policy")}}
                f["ok"] = (steps == ma.HORIZON - tau and abs(total_r - want_ret) < 1e-6
                           and abs(float((summary or {}).get("return", 1e9)) - want_ret) < 1e-6
                           and f["end_reason"] == "horizon" and f["digest_equals_anchor"] and not probs
                           and out.get("success") is True and f["m7h_block"]["rows_equal_prefix_plus_policy"] is True)
                full.append(f)
                log(f"F3 full cut {tau}: {'ok' if f['ok'] else 'FAIL'} steps {steps} return {f['return']} "
                    f"(want {f['want_return']}) problems {probs}")
            results.append(r)
            append_jsonl(sink, r)
            if not r["ok"]:
                log(f"F3 cut {tau}: FAIL {r}")
                break
    finally:
        env.close()
        remove_worker_runtime(wdir / "runtime")
    left = leftover_processes()
    ok = (len(results) == len(cuts) and all(r["ok"] for r in results) and len(full) == len(ma.F3_FULL_CUTS)
          and all(f["ok"] for f in full) and not left)
    doc = {"check": "F3", "ok": ok, "cuts": len(cuts), "exact": sum(1 for r in results if r["ok"]),
           "host_frame_equal": sum(1 for r in results if r["host_frame_equal"]), "full_cuts": full,
           "observation_table_sha256": sha, "leftover_processes": left}
    write_json(OUT / "f3.json", doc)
    log(f"F3 {'PASS' if ok else 'FAIL'}: {doc['exact']}/{len(cuts)} cuts exact, full {[f['ok'] for f in full]}")
    return EXIT_OK if ok else EXIT_FAILED


# -- pooled jobs (validate / F4 / F5) --------------------------------------------------------------------------------


def _init_child() -> None:
    import torch

    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass


def validate_job(seed: int) -> Dict[str, Any]:
    model, vn, info = load_policy(seed)
    check_policy_identity(seed, info)
    ws = registered_warm_start(seed)
    det = ws["phase_k_final_evaluation"]["deterministic"]
    memory_check(f"validate s{seed}")
    rec = run_episode(work=OUT / "work" / f"validate_s{seed}", rank=POOL_RANKS[seed], index=9600 + seed, prefix=b"",
                      expected=None, policy=(model, vn), deterministic=True, seed=12345, stop_rule="natural")
    ok = det["distinct_digests"] == 1 and rec["digest"] in det["digests"] and rec["ret"] in det["raw_returns"]
    return {"seed": seed, "ok": ok, "digest": rec["digest"], "phase_k_digests": det["digests"], "return": rec["ret"],
            "phase_k_returns": det["raw_returns"], "end": rec["end"], "outcome": rec["outcome"],
            "policy_parameter_digest": info["policy_parameter_digest"]}


def f4_job(seed: int) -> Dict[str, Any]:
    anchor = ma.load_anchor()
    table = ma.load_observation_table(table_sha())
    model, vn, info = load_policy(seed)
    check_policy_identity(seed, info)
    sink = OUT / f"f4_s{seed}.jsonl"
    done = {(int(r["tau"]), int(r["k"])): r for r in read_jsonl(sink)}
    results: List[Tuple[int, int]] = []
    windows: List[Dict[str, Any]] = []
    while True:
        w = ma.f4_next_window(results)
        if w is None:
            break
        succ, n = 0, 0
        per_cut = {}
        for tau in ma.f4_window_cuts(w):
            per_cut[tau] = 0
            for k in range(ma.F4_EPISODES_PER_CUT):
                rec = done.get((tau, k))
                if rec is None:
                    memory_check(f"F4 s{seed} tau {tau} k {k}")
                    es = ma.episode_seed("f4", seed, tau, k)
                    rec = run_episode(work=OUT / "work" / f"f4_s{seed}", rank=POOL_RANKS[seed],
                                      index=10000 + seed * 1000 + (tau % 1000), prefix=anchor.prefix(tau),
                                      expected=table[tau - 1], policy=(model, vn), deterministic=False, seed=es,
                                      stop_rule="f4")
                    rec.update(check="F4", seed=seed, window_index=w, k=k, episode_seed=es,
                               policy_parameter_digest=info["policy_parameter_digest"])
                    append_jsonl(sink, rec)
                n += 1
                s = bool(rec["outcome"]["success"])
                succ += int(s)
                per_cut[tau] += int(s)
        results.append((succ, n))
        windows.append({"window_index": w, "window": list(ma.WINDOWS[w][1:]), "successes": succ, "n": n,
                        "class": ma.f4_classify_window(succ, n), "per_cut": per_cut})
        log(f"F4 s{seed} W{w} {list(ma.WINDOWS[w][1:])}: {succ}/{n} ({windows[-1]['class']})")
    return {"seed": seed, "windows": windows, **ma.f4_seed_status(results)}


def f5_job(seed: int) -> Dict[str, Any]:
    anchor = ma.load_anchor()
    table = ma.load_observation_table(table_sha())
    model, vn, info = load_policy(seed)
    check_policy_identity(seed, info)
    sink = OUT / f"f5_s{seed}.jsonl"
    done = {(int(r["tau"]), int(r["k"])) for r in read_jsonl(sink)}
    for tau in ma.F5_CUTS:
        for k in range(ma.F5_EPISODES_PER_CUT):
            if (tau, k) in done:
                continue
            memory_check(f"F5 s{seed} tau {tau} k {k}")
            es = ma.episode_seed("f5", seed, tau, k)
            rec = run_episode(work=OUT / "work" / f"f5_s{seed}", rank=POOL_RANKS[seed],
                              index=20000 + seed * 1000 + (tau % 1000), prefix=anchor.prefix(tau), expected=table[tau - 1],
                              policy=(model, vn), deterministic=False, seed=es, stop_rule="natural")
            rec.update(check="F5", seed=seed, k=k, episode_seed=es, policy_parameter_digest=info["policy_parameter_digest"])
            append_jsonl(sink, rec)
        log(f"F5 s{seed} cut {tau} done")
    return {"seed": seed, "episodes": len(read_jsonl(sink))}


def run_pool(tag: str, fn: Any) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    import multiprocessing

    import m7m_feasibility as fz          # a module-level reference the spawned children can import

    gate = launch_gate(tag)
    if not gate["ok"]:
        write_json(OUT / f"{tag.lower()}_gate_refused.json", gate)
        return False, [], ["launch gate refused"]
    out, errors = [], []
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=len(ma.F4_SEEDS), mp_context=ctx, initializer=_init_child) as ex:
        futs = {ex.submit(getattr(fz, fn.__name__), j): j for j in ma.F4_SEEDS}
        for fut in as_completed(futs):
            try:
                out.append(fut.result())
            except Exception as exc:  # noqa: BLE001 - recorded; the command fails
                errors.append(f"seed {futs[fut]}: {type(exc).__name__}: {exc}")
                log(f"{tag}: seed {futs[fut]} stopped: {type(exc).__name__}: {exc}")
    left = leftover_processes()
    if left:
        errors.append(f"leftover BattleShip processes {left}")
    return not errors, sorted(out, key=lambda r: r["seed"]), errors


def cmd_validate(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    registered_plan_checked()
    check_executable()
    ok, res, errors = run_pool("VALIDATE", validate_job)
    ok = ok and len(res) == len(ma.F4_SEEDS) and all(r["ok"] for r in res)
    write_json(OUT / "validate.json", {"check": "harness_validation", "ok": ok, "results": res, "errors": errors})
    log(f"harness validation {'PASS' if ok else 'FAIL'} {[(r['seed'], r['ok']) for r in res]} {errors}")
    return EXIT_OK if ok else (EXIT_STOPPED if errors else EXIT_FAILED)


def cmd_f4(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    registered_plan_checked()
    check_executable()
    if not read_json(OUT / "validate.json").get("ok"):
        raise IntegrityError("the harness validation did not pass")
    ok, res, errors = run_pool("F4", f4_job)
    passing = sum(1 for r in res if r["passes"])
    f4_pass = ok and len(res) == len(ma.F4_SEEDS) and passing >= ma.F4_SEEDS_REQUIRED
    write_json(OUT / "f4.json", {"check": "F4", "ok": f4_pass, "complete": ok, "seeds_passing": passing,
                                 "results": res, "errors": errors})
    log(f"F4 {'PASS' if f4_pass else 'FAIL'}: {passing} of {len(res)} seeds pass {errors}")
    return EXIT_OK if f4_pass else (EXIT_STOPPED if errors else EXIT_FAILED)


def f5_summary() -> Dict[str, Any]:
    recs = []
    for j in ma.F4_SEEDS:
        recs += read_jsonl(OUT / f"f5_s{j}.jsonl")

    def groups(rs: Sequence[Mapping[str, Any]]) -> Dict[str, List[float]]:
        return {"t2": [r["ret"] for r in rs if r["outcome"]["t2_policy"]],
                "no_t2": [r["ret"] for r in rs if not r["outcome"]["t2_policy"]]}

    def falls(rs: Sequence[Mapping[str, Any]], t2: bool) -> Dict[str, Any]:
        g = [r for r in rs if r["outcome"]["t2_policy"] == t2]
        return {"n": len(g), "falls": sum(1 for r in g if r["end"] == "fall")}

    per_seed = {}
    for j in ma.F4_SEEDS:
        rs = [r for r in recs if int(r["seed"]) == j]
        per_seed[str(j)] = {"episodes": len(rs), **ma.f5_diagnostic(groups(rs), min_group=ma.F5_MIN_GROUP_SEED),
                            "falls_t2": falls(rs, True), "falls_no_t2": falls(rs, False),
                            "success": sum(1 for r in rs if r["outcome"]["success"])}
    per_cut = {str(t): {"n": sum(1 for r in recs if r["tau"] == t),
                        "t2": sum(1 for r in recs if r["tau"] == t and r["outcome"]["t2_policy"]),
                        "falls": sum(1 for r in recs if r["tau"] == t and r["end"] == "fall"),
                        "success": sum(1 for r in recs if r["tau"] == t and r["outcome"]["success"])}
               for t in ma.F5_CUTS}
    return {"episodes": len(recs), "pooled": ma.f5_diagnostic(groups(recs), min_group=ma.F5_MIN_GROUP_POOLED),
            "falls_t2": falls(recs, True), "falls_no_t2": falls(recs, False), "per_seed": per_seed, "per_cut": per_cut,
            "t2_ticks": sorted(r["outcome"]["t2_tick"] for r in recs if r["outcome"]["t2_policy"])}


def cmd_f5(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    registered_plan_checked()
    check_executable()
    ok, res, errors = run_pool("F5", f5_job)
    complete = ok and sum(r["episodes"] for r in res) == len(ma.F4_SEEDS) * len(ma.F5_CUTS) * ma.F5_EPISODES_PER_CUT
    doc = {"check": "F5", "role": "diagnostic (never gates)", "complete": complete, "errors": errors, **f5_summary()}
    write_json(OUT / "f5.json", doc)
    log(f"F5 {'complete' if complete else 'INCOMPLETE'}: pooled {doc['pooled']['classification']} "
        f"(t2 n={doc['pooled']['t2']['n']}, no_t2 n={doc['pooled']['no_t2']['n']}) {errors}")
    return EXIT_OK if complete else EXIT_STOPPED


# -- verification replays ----------------------------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:  # noqa: ARG001
    """Exact canonical replay from tick 0 (fresh process, m7f_trace) of the registered sample: every F5 episode with a
    policy target-2 break, every F4 success of each seed's last evaluated window, then the first episode of every
    (check, seed, cut) cell; at most 150 in that order. Digest, consumed ticks and the first-break table must match."""
    import m7f_targets as ft
    import m7f_trace as tr
    from m7_runtime import install_kill_on_close_job, remove_worker_runtime

    install_kill_on_close_job()
    registered_plan_checked()
    f4 = read_json(OUT / "f4.json")
    last_w = {int(r["seed"]): int(r["window_index"]) for r in f4["results"]}
    recs = []
    for j in ma.F4_SEEDS:
        recs += read_jsonl(OUT / f"f4_s{j}.jsonl") + read_jsonl(OUT / f"f5_s{j}.jsonl")
    pick = [r for r in recs if r["check"] == "F5" and r["outcome"]["t2_policy"]]
    pick += [r for r in recs if r["check"] == "F4" and r["outcome"]["success"] and r["window_index"] == last_w[int(r["seed"])]]
    firsts: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
    for r in recs:
        firsts.setdefault((r["check"], int(r["seed"]), int(r["tau"])), r)
    chosen, seen = [], set()
    for r in pick + list(firsts.values()):
        key = (r["check"], int(r["seed"]), int(r["tau"]), int(r["k"]))
        if key not in seen:
            seen.add(key)
            chosen.append(r)
    chosen = chosen[:VERIFY_MAX]
    gate = launch_gate("VERIFY")
    if not gate["ok"]:
        write_json(OUT / "verify_gate_refused.json", gate)
        return EXIT_STOPPED
    results = []
    for n, r in enumerate(chosen):
        memory_check(f"verify {n}")
        acts = bytes.fromhex(r["actions_hex"])
        rows = [(*mc.track1_triple(a), i) for i, a in enumerate(acts)]
        t = tr.run_stepping_trace(f"m7m_verify_{n}", EXE, rows, OUT / "work" / "verify", extra_env=dict(ENV),
                                  index=9300 + (n % 100), rank=1)
        first: Dict[int, int] = {}
        mask = 0
        for s in t["steps"]:
            m = ft.parse_targets(s["targets"]).broken_mask
            for i in ft.mask_ids(m & ~mask):
                first[int(i)] = int(s["consumed_tick"])
            mask = m
        ok = (t["consumed_tick_mismatch"] is None and t["unsent"] == 0 and t["action_digest"] == r["digest"]
              and {str(k): v for k, v in sorted(first.items())} == r["first_break_ticks"])
        remove_worker_runtime(OUT / "work" / "verify" / "runtime")
        shutil.rmtree(OUT / "work" / "verify" / "episodes", ignore_errors=True)
        results.append({"check": r["check"], "seed": r["seed"], "tau": r["tau"], "k": r["k"], "ok": ok,
                        "success": r["outcome"]["success"], "t2_policy": r["outcome"]["t2_policy"],
                        "digest": r["digest"][:16]})
    left = leftover_processes()
    doc = {"check": "verification_replays", "requested": len(chosen), "exact": sum(x["ok"] for x in results),
           "leftover_processes": left, "episodes": results}
    doc["ok"] = doc["requested"] == doc["exact"] and not left
    write_json(OUT / "verify.json", doc)
    log(f"verification {doc['exact']}/{doc['requested']} exact")
    return EXIT_OK if doc["ok"] else EXIT_FAILED


# -- summary ------------------------------------------------------------------------------------------------------------


def cmd_summarize(args: argparse.Namespace) -> int:  # noqa: ARG001
    plan = registered_plan_checked()
    res = {}
    for name in ("f1", "f2", "f3", "validate", "f4", "f5", "verify"):
        p = OUT / f"{name}.json"
        res[name] = read_json(p) if p.is_file() else None
    gating = {k: bool(res[k] and res[k].get("ok")) for k in ("f1", "f2", "f3", "validate", "f4", "verify")}
    go = all(gating.values())
    f4 = res["f4"] or {}
    doc = {"schema": "m7m_feasibility_result_v1", "plan_sha256": sha256_file(PLAN_FILE),
           "anchor_sha256": plan["anchor_file"]["sha256"],
           "observation_table_sha256": (res["f1"] or {}).get("observation_table", {}).get("sha256"),
           "gating": gating, "decision": "GO" if go else "NO-GO",
           "f4": [{k: r.get(k) for k in ("seed", "status", "window_index", "passes", "windows")} for r in f4.get("results", [])],
           "f5_diagnostic": {k: (res["f5"] or {}).get(k) for k in ("pooled", "falls_t2", "falls_no_t2", "per_seed",
                                                                   "per_cut", "t2_ticks", "complete")},
           "episodes": {"F4": sum(len(read_jsonl(OUT / f"f4_s{j}.jsonl")) for j in ma.F4_SEEDS),
                        "F5": sum(len(read_jsonl(OUT / f"f5_s{j}.jsonl")) for j in ma.F4_SEEDS)},
           "files": {p.name: sha256_file(p) for p in sorted(OUT.glob("*.json*")) if p.name != "summary.json"}}
    write_json(OUT / "summary.json", doc)
    print(json.dumps({k: doc[k] for k in ("gating", "decision", "episodes")}, indent=1))
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    for name in ("f1", "f2", "f3", "validate", "f4", "f5", "verify", "summary"):
        p = OUT / f"{name}.json"
        print(name, "-" if not p.is_file() else read_json(p).get("ok", read_json(p).get("decision")))
    for j in ma.F4_SEEDS:
        print(f"f4_s{j}", len(read_jsonl(OUT / f"f4_s{j}.jsonl")), f"f5_s{j}", len(read_jsonl(OUT / f"f5_s{j}.jsonl")))
    return EXIT_OK


COMMANDS = {"register": cmd_register, "f1": cmd_f1, "f2": cmd_f2, "f3": cmd_f3, "validate": cmd_validate,
            "f4": cmd_f4, "f5": cmd_f5, "verify": cmd_verify, "summarize": cmd_summarize, "status": cmd_status}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=sorted(COMMANDS))
    args = ap.parse_args(argv)
    os.chdir(REPO)
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        return COMMANDS[args.command](args)
    except (IntegrityError, ma.AnchorError) as exc:
        log(f"{args.command}: INTEGRITY STOP: {exc}")
        write_json(OUT / f"{args.command}_integrity_stop.json", {"error": str(exc), "type": type(exc).__name__})
        return EXIT_FAILED
    except ResourceStop as exc:
        log(f"{args.command}: RESOURCE STOP: {exc}")
        write_json(OUT / f"{args.command}_resource_stop.json", {"error": str(exc)})
        return EXIT_STOPPED


if __name__ == "__main__":
    sys.exit(main())
