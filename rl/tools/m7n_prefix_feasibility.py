#!/usr/bin/env python3
"""M7n follow-up feasibility (no training): can the frozen v3 finals initiate wall-directed behaviour from the agent's
own early-sweep states?

Sources (user authorisation 2026-09-27: cross-run use SOLELY as explicit action-prefix restarts after a normal
non-consuming tick-0 reset; never supervised targets; no fixtures / TAS): the two final stochastic tick-0 evaluation
episodes of the M7n campaign that completed the seven right targets early (seed 1 `…907d762b`, sweep at consumed tick
1678; seed 2 `…e404fde0`, sweep at 1692). Both replay exactly (sweeps addendum).

Lives under rl/tools (outside the fingerprinted M7n set); writes below runs/m7n/feasibility/prefix and the two
write-once registrations in docs/. Reads the frozen campaign evidence only.

    python rl/tools/m7n_prefix_feasibility.py trace                 # exact source replays with every raw reply kept
    python rl/tools/m7n_prefix_feasibility.py states                # the candidate-state table at the planned cuts
    python rl/tools/m7n_prefix_feasibility.py register              # sources + plan (write-once) BEFORE any check
    python rl/tools/m7n_prefix_feasibility.py foothold [--workers 3]
    python rl/tools/m7n_prefix_feasibility.py summarize

Cut semantics = M7m's: a cut tau replays source rows 0..tau-1 (row i consumes tick i); the policy's first action is
for input tick tau; the horizon counts from the reset; prefix steps earn nothing and enter no rollout. The v3 policy
observation at the cut is built by feeding EVERY prefix reply to the same EntityObservationBuilder the worker uses,
so the policy sees exactly what it would have seen had it played the prefix (displacements, sticky projectile slots,
action-class history). Native gameplay is authoritative; one fresh process per episode; native RNG never inspected.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import multiprocessing
import os
import pickle
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parents[1]
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7g_fixture as fx  # noqa: E402
import m7h_curriculum as mc  # noqa: E402
import m7n_crossing as xc  # noqa: E402
import m7n_matrix as nm  # noqa: E402
import m7n_obs as mn  # noqa: E402

REPO_ROOT = RL_DIR.parent
OUT = REPO_ROOT / "runs" / "m7n" / "feasibility" / "prefix"
SWEEPS_REGISTRY = REPO_ROOT / "docs" / "rl_observation_v3_m7n_sweeps_addendum_replays.json"
SOURCES_DOC = REPO_ROOT / "docs" / "rl_observation_v3_m7n_prefix_sources.json"
PLAN_DOC = REPO_ROOT / "docs" / "rl_observation_v3_m7n_prefix_feasibility_plan.json"
HORIZON = 3600
LEFT_X = -2100.0
LEDGE_RIGHT_X = -1200.0        # the ledge's right end: x <= this at y >= wall top = over the ledge
WALL_TOP_Y = 3000.0
WALL_FACE_X = -1800.0
EPISODES_PER_CUT = 25
# the planned cuts (input tick of the policy's first action), chosen from the traces (see `states`); registered by
# `register` and never changed afterwards
PLANNED_CUTS: Dict[str, Tuple[int, ...]] = {
    "907d762b": (1679, 1880, 2160, 2440),
    "e404fde0": (1693, 1893, 2493, 2693, 2813),
}
FOOTHOLD_RULE = {
    "stages_after_the_cut": {
        "S1_approach": "a live step with x <= -1200 at any height (past the ledge's right end; the sources never did)",
        "S2_over_ledge": "a live step with y >= 3000 and x <= -1200 (above the wall top, over the ledge span); "
                         "policy_initiated iff the last grounded step before it has consumed tick >= cut, else inherited",
        "S3_over_wall_entry": "an over_wall entry (btt_reward_v3.classify_entry) at consumed tick >= cut; policy_initiated "
                              "iff the crossing evidence's grounded takeoff has consumed tick >= cut",
        "S4_qualified_crossing": "btt_qualified_crossing_v1 (m7n_crossing.analyse_trace): over_wall entry + over_ledge path "
                                 "+ grounded takeoff + landing on a decoded left floor in the same visit",
        "S5_left_target_break": "target 1, 6 or 8 broken at consumed tick >= cut",
        "also_recorded": ["fall tick", "horizon survival", "first grounded step after the cut", "min x / max y after the cut",
                          "reward v2 return of the policy phase (rebased at the cut)", "unqualified entries"],
    },
    "outcomes": {
        "FOOTHOLD (GO)": "at some cut, policy-initiated S2 in >= 3 of 25 continuations AND S1 in >= 5 of 25; OR >= 1 S4 "
                         "with a policy-initiated takeoff at any cut",
        "NO FOOTHOLD (STOP)": "pooled S1 <= 2 of 225 AND S2 (policy-initiated or inherited) = 0",
        "INCONCLUSIVE": "anything else (approaches without passage; passages only inherited from an airborne cut; ...)",
    },
    "never": ["a raw left entry or an off-stage fall counted as a crossing", "an inherited passage counted as initiation",
              "a threshold changed after seeing results"],
}


# -- io --------------------------------------------------------------------------------------------------------------


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, d: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, default=str) + "\n", encoding="utf-8")


def write_once(p: Path, d: Any) -> None:
    if p.is_file():
        raise SystemExit(f"refused: {ec.repo_relative(p)} exists (a registration is never rewritten)")
    write_json(p, d)


def sha256_file(p: Path) -> str:
    return xc.sha256_file(Path(p))


def log(msg: str) -> None:
    print(f"[m7n_prefix {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# -- sources -------------------------------------------------------------------------------------------------------


def sources() -> List[Dict[str, Any]]:
    reg = read_json(SWEEPS_REGISTRY)
    out = []
    for e in reg["episodes"]:
        short = e["episode_id"][-8:]
        if short not in PLANNED_CUTS:
            continue
        out.append({"short": short, "seed": int(e["seed"]), "run": e["run"], "episode_id": e["episode_id"],
                    "artifact_dir": e["artifact_dir"], "native_action_digest": e["native_action_digest"],
                    "breaks": [tuple(b) for b in e["breaks"]], "sweep_tick": int(e["sweep_tick"]), "flags": dict(e["flags"])})
    return out


def source_rows(src: Mapping[str, Any]) -> Tuple[List[Tuple[int, int, int, int]], bytes]:
    """The artifact's native rows and the same actions as Track 1 indices (exact inverse, round-trip checked)."""
    import m7f_trace as tr

    acts, _meta = tr.artifact_actions(REPO_ROOT / src["artifact_dir"])
    rows = [(int(b), int(x), int(y), int(t)) for b, x, y, t in acts]
    pairs = fx.native_to_track1_exact([(b, x, y) for b, x, y, _ in rows])
    idx = bytes(mc.encode_track1(s, bt) for s, bt in pairs)
    for a, (b, x, y, _) in zip(idx, rows):
        if mc.track1_triple(a) != (b, x, y):
            raise RuntimeError("Track 1 round trip failed")
    if mc.native_digest(rows) != src["native_action_digest"]:
        raise RuntimeError("artifact digest differs from the registered source digest")
    return rows, idx


def checkpoint_of(seed: int) -> Path:
    return nm.matrix()[seed].run_dir / "final"


# -- policy (v3 finals, frozen) ---------------------------------------------------------------------------------------

_POLICY: Dict[str, Tuple[Any, Any]] = {}


def load_policy(ckpt: Path) -> Tuple[Any, Any, Dict[str, Any]]:
    import torch

    import m7_evaluation as me
    from m7_trainer import M7PPO

    torch.set_num_threads(1)
    key = str(ckpt)
    if key not in _POLICY:
        model = M7PPO.load(str(ckpt / "model.zip"), device="cpu")
        me.check_model_identity(model, mn.OBS_CONTRACT)
        with open(ckpt / "vecnormalize.pkl", "rb") as fp:
            vn = pickle.load(fp)
        me.check_vecnormalize_identity(vn, mn.OBS_CONTRACT)
        vn.training = False
        vn.norm_reward = False
        _POLICY[key] = (model, vn)
    model, vn = _POLICY[key]
    meta = read_json(ckpt / "checkpoint.json")
    info = {"checkpoint": ec.repo_relative(ckpt), "run_id": meta.get("run_id"), "num_timesteps": meta.get("num_timesteps"),
            "files_sha256": {n: sha256_file(ckpt / n) for n in ("checkpoint.json", "model.zip", "vecnormalize.pkl")},
            "policy_parameter_digest": me.policy_parameter_digest(model), "obs_rms_digest": me.obs_rms_digest(vn)}
    return model, vn, info


# -- one harness episode ---------------------------------------------------------------------------------------------


class Builder:
    """The worker's v3 observation pipeline over raw replies (reset observe with lines, then one reply per step)."""

    def __init__(self, initial_reply: Mapping[str, Any]):
        import m7g_spatial as ms
        import m7n_entity as ne
        import m7n_status_table as st

        self.ms, self.ne = ms, ne
        sp = ms.spatial_of(initial_reply, expect_lines=True)
        en = ne.entity_of(initial_reply)
        self.classifier = st.ActionClassifier(st.load_table(), mn.DEFAULT_CHARACTER)
        self.builder = mn.EntityObservationBuilder(sp.lines or (), self.classifier)
        self.obs, self.stale = self.builder.build(initial_reply["observation"], sp, en)
        self.last_sp, self.last_en = sp, en

    def feed(self, reply: Mapping[str, Any]) -> None:
        sp = self.ms.spatial_of(reply, expect_lines=False)
        en = self.ne.entity_of(reply)
        self.obs, self.stale = self.builder.build(reply["observation"], sp, en)
        self.last_sp, self.last_en = sp, en

    def batched(self) -> Dict[str, Any]:
        import numpy as np

        return {k: np.asarray(v, dtype=np.float32)[None] for k, v in self.obs.items()}


def state_facts(reply: Mapping[str, Any], bld: Builder, cut: int) -> Dict[str, Any]:
    """The candidate-state table row for the observation the policy sees at input tick `cut` (after row cut-1)."""
    o = reply["observation"]
    sp, en = bld.last_sp, bld.last_en
    g2 = sp.group(2)
    weapons = self_weapons = [w for w in en.weapons if w.owned == 1]
    surface = fx.classify_ground(xc.geometry(), o)
    return {"cut": cut, "consumed_through": cut - 1, "remaining_horizon": HORIZON - cut,
            "x": round(float(o["position_x"]), 1), "y": round(float(o["position_y"]), 1),
            "air_velocity": [round(float(o["air_velocity_x"]), 2), round(float(o["air_velocity_y"]), 2)],
            "ground_velocity_x": round(float(o["ground_velocity_x"]), 2), "facing": int(o["facing_direction"]),
            "grounded": int(o["ground_air_state"]) == 0, "surface": surface, "jumps_used": int(o["jumps_used"]),
            "jumps_max": int(en.fighter.jumps_max), "status_id": int(o["fighter_status_id"]),
            "action_class": bld.classifier.name(int(o["fighter_status_id"])), "status_tics": int(en.fighter.status_total_tics),
            "attack_active": int(en.fighter.attack_active), "hitstun": int(en.fighter.hitstun), "shield": int(en.fighter.shield_active),
            "floor_line": int(sp.fighter.floor_line_id) if sp.fighter else None,
            "floor_dist": round(float(sp.fighter.floor_dist), 1) if sp.fighter else None,
            "carry": [round(float(c), 2) for c in sp.fighter.carry] if sp.fighter else None,
            "platform": {"y": round(float(g2.translate[1]), 1), "vy": round(float(g2.speed[1]), 3)} if g2 else None,
            "on_platform": bool(self_weapons is weapons) and bool(bld.ms.on_platform(sp, o)),
            "targets_remaining": int(o["targets_remaining"]), "targets_live_mask": int(sp.target_live_mask),
            "own_projectiles": [{"kind": w.kind, "lifetime": w.lifetime, "x": round(float(w.translate[0]), 1),
                                 "y": round(float(w.translate[1]), 1), "vx": round(float(w.velocity[0]), 2),
                                 "vy": round(float(w.velocity[1]), 2)} for w in weapons],
            "time_passed": int(o["time_passed"]), "v3_stale": bool(bld.stale)}


def launch(work: Path, rank: int, index: int, flags: Mapping[str, str]):
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, prepare_worker_runtime

    exe = nm.load_run(nm.matrix()[0]).executable
    work = Path(work).resolve()
    shutil.rmtree(work / "runtime", ignore_errors=True)
    prepare_worker_runtime(work / "runtime", exe)
    port, _busy = PortCandidates(rank).claim()
    (work / "episodes").mkdir(parents=True, exist_ok=True)
    cfg = LaunchConfig(executable=Path(exe), working_dir=work / "runtime", run_root=work / "episodes", port=port,
                       startup_timeout=30.0, ready_timeout=90.0, request_timeout=15.0, exit_timeout=30.0, extra_env=dict(flags))
    return BattleShipEpisode(cfg, index=index)


def cleanup(work: Path) -> None:
    from m7k_target2 import remove_runtime_with_retry

    remove_runtime_with_retry(Path(work) / "runtime")
    shutil.rmtree(Path(work) / "episodes", ignore_errors=True)


def compact_row(reply: Mapping[str, Any]) -> List[Any]:
    o = reply.get("observation") or {}
    return [reply.get("consumed_tick"), o.get("position_x"), o.get("position_y"), o.get("ground_air_state"),
            o.get("fighter_status_id"), o.get("air_velocity_x"), o.get("air_velocity_y"), o.get("jumps_used")]


def staging(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]], cut: int) -> Dict[str, Any]:
    """The S1-S5 stages after the cut, from the raw replies (native observations only)."""
    geo = xc.geometry()
    an = xc.analyse_trace(initial, steps, geo)
    ev = fx.crossing_evidence(geo, initial, steps)
    live = [(int(s["consumed_tick"]), s["observation"]) for s in steps if xc._live(s.get("observation") or {})]
    after = [(t, o) for t, o in live if t >= cut]
    grounded_ticks = [t for t, o in live if int(o["ground_air_state"]) == 0]
    first_grounded_after = next((t for t in grounded_ticks if t >= cut), None)
    s1 = [t for t, o in after if float(o["position_x"]) <= LEDGE_RIGHT_X]
    s2 = []
    for t, o in after:
        if float(o["position_y"]) >= WALL_TOP_Y and float(o["position_x"]) <= LEDGE_RIGHT_X:
            lg = max((g for g in grounded_ticks if g < t), default=None)
            s2.append({"tick": t, "x": float(o["position_x"]), "y": float(o["position_y"]), "last_grounded_tick": lg,
                       "policy_initiated": lg is not None and lg >= cut})
    entries = [e for e in an["entries"] if int(e["consumed_tick"]) >= cut]
    ap = ev.get("approach_surface")
    takeoff_tick = ap.get("consumed_tick") if ap else None
    s3 = [dict(e, policy_initiated=(takeoff_tick is not None and int(takeoff_tick) >= cut)) for e in entries
          if e["class"] == "over_wall"]
    s4 = bool(an["qualified_crossing"]) and any(e["qualified"] for e in entries)
    s5 = [(i, t) for i, t in an["left_target_breaks"] if t >= cut]
    xs = [float(o["position_x"]) for _, o in after]
    ys = [float(o["position_y"]) for _, o in after]
    fall_tick = next((int(s["consumed_tick"]) for s in steps if fx.is_fall(s)), None)
    return {"S1_approach": bool(s1), "S1_first_tick": s1[0] if s1 else None,
            "S2_over_ledge": bool(s2), "S2_policy_initiated": any(z["policy_initiated"] for z in s2), "S2_first": s2[0] if s2 else None,
            "S3_over_wall_entry": bool(s3), "S3_policy_initiated": any(z["policy_initiated"] for z in s3),
            "S3_entries": s3[:4], "S4_qualified_crossing": bool(s4) and any(z["policy_initiated"] for z in s3),
            "S4_qualified_any": bool(s4), "S5_left_target_breaks": s5,
            "entries_after_cut": [{k: e[k] for k in ("consumed_tick", "class", "y_c")} for e in entries][:6],
            "first_grounded_after_cut": first_grounded_after, "takeoff_tick": takeoff_tick,
            "min_x_after": min(xs) if xs else None, "max_y_after": max(ys) if ys else None,
            "fall_tick": fall_tick, "terminal": an["terminal"]["kind"], "steps_after_cut": len(after),
            "route": an["route"]["identity"]}


def run_episode(job: Mapping[str, Any]) -> Dict[str, Any]:
    import torch

    import m7f_targets as ft
    import m7f_trace as tr
    from battleship_client import StepState
    from btt_learning import live_targets
    from btt_parallel import is_native_failure
    from btt_rewards import REWARD_V2, reward_step
    from stable_baselines3.common.utils import set_random_seed

    work = OUT / "foothold" / "work" / f"{job['short']}_{job['cut']}_{job['k']:02d}"
    prefix_rows = [tuple(r) for r in job["prefix_rows"]]
    cut = int(job["cut"])
    model, vn, pinfo = load_policy(Path(REPO_ROOT / job["checkpoint"]))
    if pinfo["files_sha256"] != job["checkpoint_files_sha256"]:
        raise RuntimeError("checkpoint files differ from the registered ones")
    set_random_seed(int(job["episode_seed"]))
    replies: List[Dict[str, Any]] = []
    terms = {"target_term": 0.0, "step_term": 0.0, "clear_term": 0.0, "failure_term": 0.0}
    t0 = time.perf_counter()
    rows: List[Tuple[int, int, int, int]] = []
    mask = 0
    ep = launch(work, int(job["rank"]), int(job["index"]), job["flags"])
    end = None
    exit_code = None
    with ep:
        ep.start()
        client = ep.client
        tr._capture_requests(client, replies)
        client.request("status")
        initial = client.request("observe")
        o0 = initial["observation"]
        if int(o0["input_tick"]) != 0 or int(o0["targets_remaining"]) != 10:
            raise RuntimeError(f"reset observation {o0['input_tick']} / {o0['targets_remaining']}")
        bld = Builder(initial)
        steps: List[Dict[str, Any]] = []
        for i, (b, x, y, _t) in enumerate(prefix_rows):
            r = client.step(b, x, y)
            if r.consumed_tick != i or r.state != StepState.WAITING_FOR_ACTION:
                raise RuntimeError(f"prefix row {i}: consumed {r.consumed_tick} state {r.state_name}")
            rep = replies[-1]
            steps.append(rep)
            rows.append((b, x, y, int(r.consumed_tick)))
            bld.feed(rep)
            mask = ft.parse_targets(rep["targets"]).broken_mask
        prefix_digest = mc.native_digest(rows)
        if prefix_digest != job["prefix_digest"]:
            raise RuntimeError("prefix digest differs from the registered prefix")
        last = steps[-1]["observation"]
        got = mc.observation_dict(last)
        diffs = mc.observation_diffs(got, job["expected_observation"])
        if diffs or mask != int(job["expected_mask"]):
            raise RuntimeError(f"post-prefix state differs from the registration: {diffs} mask {mask:#x}")
        prefix_wall = time.perf_counter() - t0
        prev_targets = live_targets(last)
        t = cut
        while True:
            with torch.no_grad():
                act, _ = model.predict(vn.normalize_obs(bld.batched()), deterministic=False)
            a = mc.encode_track1(int(act[0][0]), int(act[0][1]))
            b, x, y = mc.track1_triple(a)
            r = client.step(b, x, y)
            if r.consumed_tick != t:
                raise RuntimeError(f"policy row {t}: consumed {r.consumed_tick}")
            rep = replies[-1]
            steps.append(rep)
            rows.append((b, x, y, int(r.consumed_tick)))
            bld.feed(rep)
            o = rep["observation"]
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
                    exit_code = done.exit_code
                break
            if t >= HORIZON:
                end = "horizon"
                break
    stg = staging(initial, steps, cut)
    rec = {"short": job["short"], "seed": job["seed"], "cut": cut, "k": job["k"], "episode_seed": job["episode_seed"],
           "end": end, "exit_code": exit_code, "rows": len(rows), "policy_steps": len(rows) - cut,
           "prefix_wall_s": round(prefix_wall, 2), "wall_s": round(time.perf_counter() - t0, 2),
           "native_action_digest": mc.native_digest(rows), "reward_v2_policy_phase": {k: round(v, 4) for k, v in terms.items()},
           "return_policy_phase": round(sum(terms.values()), 4), "staging": stg,
           "trajectory_fields": ["t", "x", "y", "ga", "status", "vx", "vy", "jumps"],
           "trajectory_after_cut": [compact_row(s) for s in steps[cut:]]}
    work.mkdir(parents=True, exist_ok=True)
    with gzip.open(work / "episode.json.gz", "wt", encoding="utf-8") as fp:
        json.dump(dict(rec, actions_hex=bytes(mc.encode_track1(*divmod_track1(b, x, y)) for b, x, y, _ in rows).hex()), fp)
    cleanup(work)
    return {k: v for k, v in rec.items() if k != "trajectory_after_cut"}


def divmod_track1(b: int, x: int, y: int) -> Tuple[int, int]:
    return fx.native_to_track1_exact([(b, x, y)])[0]


# -- commands --------------------------------------------------------------------------------------------------------


def trace_path(short: str) -> Path:
    return OUT / "traces" / f"{short}.json.gz"


def cmd_trace(_: argparse.Namespace) -> int:
    import m7f_trace as tr
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    for k, src in enumerate(sources()):
        p = trace_path(src["short"])
        if p.is_file():
            log(f"{src['short']}: trace exists")
            continue
        rows, idx = source_rows(src)
        exe = nm.load_run(nm.matrix()[0]).executable
        work = OUT / "traces" / "work" / src["short"]
        acts = [(b, x, y, t) for b, x, y, t in rows]
        trace = tr.run_stepping_trace(f"m7n_prefix_trace_{k}", exe, acts, work, extra_env=src["flags"], index=9960 + k)
        exact = trace["consumed_tick_mismatch"] is None and trace["unsent"] == 0 and trace["action_digest"] == src["native_action_digest"]
        bld = Builder(trace["initial"])
        per_step = []
        for s in trace["steps"]:
            bld.feed(s)
            per_step.append(dict(state_facts(s, bld, int(s["consumed_tick"]) + 1)))
        doc = {"source": src, "exact": exact, "track1_hex": idx.hex(), "rows": len(rows), "initial": trace["initial"],
               "steps": trace["steps"], "states": per_step}
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wt", encoding="utf-8") as fp:
            json.dump(doc, fp)
        cleanup(work)
        log(f"{src['short']}: exact {exact}, {len(rows)} rows -> {ec.repo_relative(p)}")
        if not exact:
            return 1
    return 0


def load_trace(short: str) -> Dict[str, Any]:
    with gzip.open(trace_path(short), "rt", encoding="utf-8") as fp:
        return json.load(fp)


def cmd_states(_: argparse.Namespace) -> int:
    table = []
    for src in sources():
        tr_ = load_trace(src["short"])
        for cut in PLANNED_CUTS[src["short"]]:
            st = tr_["states"][cut - 1]
            assert st["cut"] == cut
            table.append(dict(st, short=src["short"], seed=src["seed"], sweep_tick=src["sweep_tick"]))
            print(json.dumps({k: st[k] for k in ("cut", "remaining_horizon", "x", "y", "air_velocity", "ground_velocity_x",
                                                  "grounded", "surface", "on_platform", "platform", "jumps_used", "jumps_max",
                                                  "action_class", "status_id", "status_tics", "facing", "floor_dist",
                                                  "own_projectiles", "targets_remaining", "v3_stale")} | {"src": src["short"]}))
    write_json(OUT / "candidate_states.json", table)
    return 0


def cmd_register(_: argparse.Namespace) -> int:
    srcs = []
    plan_cuts = []
    for src in sources():
        rows, idx = source_rows(src)
        tr_ = load_trace(src["short"])
        if not tr_["exact"]:
            raise SystemExit("source trace not exact")
        srcs.append({**{k: src[k] for k in ("short", "seed", "run", "episode_id", "artifact_dir", "native_action_digest",
                                           "breaks", "sweep_tick", "flags")},
                     "rows": len(rows), "track1_actions_hex": idx.hex(), "track1_actions_sha256": hashlib.sha256(idx).hexdigest(),
                     "source_kind": "final stochastic tick-0 evaluation episode of the M7n campaign (policy-discovered)",
                     "artifact_sha256": {n: sha256_file(REPO_ROOT / src["artifact_dir"] / n) for n in ("actions.jsonl", "metadata.json")}})
        for cut in PLANNED_CUTS[src["short"]]:
            st = tr_["steps"][cut - 1]
            import m7f_targets as ft

            plan_cuts.append({"short": src["short"], "seed": src["seed"], "cut": cut, "remaining_horizon": HORIZON - cut,
                              "prefix_digest": mc.native_digest([tuple(r) for r in [(b, x, y, t) for b, x, y, t in rows[:cut]]]),
                              "expected_observation": mc.observation_dict(st["observation"]),
                              "expected_mask": ft.parse_targets(st["targets"]).broken_mask, "state": tr_["states"][cut - 1]})
    ck = {}
    for s in sorted({c["seed"] for c in plan_cuts}):
        _m, _v, info = load_policy(checkpoint_of(s))
        ck[str(s)] = info
    sources_doc = {"schema": "m7n_prefix_sources_v1", "utc": xc.utc_now(),
                   "authorization": {"by": "the user", "date": "2026-09-27",
                                     "scope": "cross-run use of these two policy-discovered trajectories solely as explicit "
                                              "action-prefix restarts after a normal tick-0 reset"},
                   "exclusions": ["no source actions as supervised targets", "no human crossing fixtures or TAS as training material",
                                  "no transfer of weights, optimizer or statistics through the source"],
                   "classification": "policy-discovered final tick-0 evaluation episodes, replay-verified (sweeps addendum); "
                                     "useful source trajectories, not a consolidated skill",
                   "executable_sha256": sha256_file(nm.load_run(nm.matrix()[0]).executable), "sources": srcs}
    plan = {"schema": "m7n_prefix_feasibility_plan_v1", "utc": xc.utc_now(), "registered_before_any_check": True,
            "harness": "rl/tools/m7n_prefix_feasibility.py foothold", "sources_doc": ec.repo_relative(SOURCES_DOC),
            "cut_semantics": "rows 0..cut-1 replayed after the non-consuming tick-0 reset; policy's first action at input tick cut; "
                             "horizon counted from the reset; prefix earns nothing; v3 observation built from every prefix reply",
            "checkpoints": ck, "sampling": "stochastic policy (deterministic=False), per-episode seed = sha256('m7n_prefix|<short>|<cut>|<k>')[:8]",
            "episodes_per_cut": EPISODES_PER_CUT, "cuts": plan_cuts, "total_episodes": EPISODES_PER_CUT * len(plan_cuts),
            "geometry": {"left_x": LEFT_X, "ledge_right_x": LEDGE_RIGHT_X, "wall_top_y": WALL_TOP_Y, "wall_face_x": WALL_FACE_X},
            "rule": FOOTHOLD_RULE, "stop_on": ["a failed launch gate", "an integrity or provenance mismatch", "a process leak"],
            "no_training": True, "no_new_tick0_evaluation": True}
    write_once(SOURCES_DOC, sources_doc)
    write_once(PLAN_DOC, plan)
    log(f"registered {len(srcs)} sources, {len(plan_cuts)} cuts x {EPISODES_PER_CUT} = {plan['total_episodes']} episodes")
    return 0


def episode_seed(short: str, cut: int, k: int) -> int:
    return int(hashlib.sha256(f"m7n_prefix|{short}|{cut}|{k}".encode("ascii")).hexdigest()[:8], 16)


_RANK = 0


def _init(counter: Any) -> None:
    global _RANK
    with counter.get_lock():
        counter.value += 1
        _RANK = int(counter.value)
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()


def _job(job: Dict[str, Any]) -> Dict[str, Any]:
    job = dict(job, rank=_RANK)
    return run_episode(job)


def cmd_foothold(args: argparse.Namespace) -> int:
    import m7h_guard as g
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, list_processes_named, wait_until_no_process

    install_kill_on_close_job()
    plan = read_json(PLAN_DOC)
    if sha256_file(SOURCES_DOC) != plan.get("sources_sha256", sha256_file(SOURCES_DOC)):
        raise SystemExit("sources document changed")
    if list_processes_named():
        raise SystemExit("BattleShip already running")
    gate = g.launch_gate()
    if not gate["ok"]:
        raise SystemExit(f"launch gate refused: {gate['problems']}")
    src_rows = {s["short"]: source_rows(s)[0] for s in sources()}
    results_path = OUT / "foothold" / "results.jsonl"
    done = set()
    if results_path.is_file():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["short"], r["cut"], r["k"]))
    jobs = []
    idx = 0
    for c in plan["cuts"]:
        for k in range(int(plan["episodes_per_cut"])):
            idx += 1
            if (c["short"], c["cut"], k) in done:
                continue
            jobs.append({"short": c["short"], "seed": c["seed"], "cut": c["cut"], "k": k, "index": 9000 + idx,
                         "episode_seed": episode_seed(c["short"], c["cut"], k), "prefix_rows": src_rows[c["short"]][:c["cut"]],
                         "prefix_digest": c["prefix_digest"], "expected_observation": c["expected_observation"],
                         "expected_mask": c["expected_mask"], "checkpoint": plan["checkpoints"][str(c["seed"])]["checkpoint"],
                         "checkpoint_files_sha256": plan["checkpoints"][str(c["seed"])]["files_sha256"],
                         "flags": next(s["flags"] for s in sources() if s["short"] == c["short"])})
    log(f"{len(jobs)} episode(s) to run ({len(done)} done)")
    ctx = multiprocessing.get_context("spawn")
    counter = ctx.Value("i", 0)
    failures = []
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=int(args.workers), mp_context=ctx, initializer=_init, initargs=(counter,)) as ex:
        futs = {ex.submit(_job, j): j for j in jobs}
        for n, fut in enumerate(as_completed(futs), 1):
            j = futs[fut]
            try:
                r = fut.result()
                with open(results_path, "a", encoding="utf-8") as fp:
                    fp.write(json.dumps(r) + "\n")
                s = r["staging"]
                log(f"{n}/{len(jobs)} {r['short']} cut {r['cut']} k{r['k']}: {r['end']} S1 {s['S1_approach']} S2 {s['S2_over_ledge']}"
                    f"{'(policy)' if s['S2_policy_initiated'] else ''} S3 {s['S3_over_wall_entry']} S4 {s['S4_qualified_any']} "
                    f"minx {s['min_x_after']:.0f} maxy {s['max_y_after']:.0f} ret {r['return_policy_phase']} {r['wall_s']:.0f}s")
            except Exception as exc:  # noqa: BLE001 - recorded, stops the run
                failures.append({"job": {k: j[k] for k in ("short", "cut", "k")}, "error": f"{type(exc).__name__}: {exc}"})
                log(f"FAILED {j['short']} cut {j['cut']} k{j['k']}: {type(exc).__name__}: {exc}")
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    write_json(OUT / "foothold" / "run_summary.json", {"utc": xc.utc_now(), "jobs": len(jobs), "failures": failures,
                                                       "leftover_pids": leftover, "wall_s": round(time.perf_counter() - t0, 1),
                                                       "launch_gate": gate})
    log(f"done in {(time.perf_counter() - t0) / 60:.1f} min; failures {len(failures)}; leftover {leftover}")
    return 0 if not failures and not leftover else 1


def cmd_summarize(_: argparse.Namespace) -> int:
    plan = read_json(PLAN_DOC)
    rs = [json.loads(l) for l in (OUT / "foothold" / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    n_plan = int(plan["episodes_per_cut"])
    per = []
    for c in plan["cuts"]:
        grp = [r for r in rs if r["short"] == c["short"] and r["cut"] == c["cut"]]
        st = [r["staging"] for r in grp]
        row = {"short": c["short"], "seed": c["seed"], "cut": c["cut"], "remaining": c["remaining_horizon"], "n": len(grp),
               "S1": sum(s["S1_approach"] for s in st), "S2": sum(s["S2_over_ledge"] for s in st),
               "S2_policy": sum(s["S2_policy_initiated"] for s in st), "S3": sum(s["S3_over_wall_entry"] for s in st),
               "S3_policy": sum(s["S3_policy_initiated"] for s in st), "S4_policy": sum(s["S4_qualified_crossing"] for s in st),
               "S4_any": sum(s["S4_qualified_any"] for s in st), "S5": sum(1 for s in st if s["S5_left_target_breaks"]),
               "falls": sum(1 for r in grp if r["end"] == "fall"), "horizon": sum(1 for r in grp if r["end"] == "horizon"),
               "clears": sum(1 for r in grp if r["end"] == "clear"),
               "min_x_after_min": min((s["min_x_after"] for s in st if s["min_x_after"] is not None), default=None),
               "max_y_after_max": max((s["max_y_after"] for s in st if s["max_y_after"] is not None), default=None),
               "mean_return": round(sum(r["return_policy_phase"] for r in grp) / len(grp), 3) if grp else None,
               "entries_after_cut": sum(len(s["entries_after_cut"]) for s in st)}
        per.append(row)
    pooled = {k: sum(r[k] for r in per) for k in ("n", "S1", "S2", "S2_policy", "S3", "S3_policy", "S4_policy", "S4_any", "S5", "falls", "horizon", "clears")}
    complete = all(r["n"] == n_plan for r in per)
    go = any(r["S2_policy"] >= 3 and r["S1"] >= 5 for r in per) or pooled["S4_policy"] >= 1
    stop = pooled["S1"] <= 2 and pooled["S2"] == 0
    outcome = "INCOMPLETE" if not complete else ("FOOTHOLD (GO)" if go else ("NO FOOTHOLD (STOP)" if stop else "INCONCLUSIVE"))
    doc = {"utc": xc.utc_now(), "plan_sha256": sha256_file(PLAN_DOC), "per_cut": per, "pooled": pooled, "outcome": outcome,
           "rule": plan["rule"]["outcomes"]}
    write_json(OUT / "foothold" / "summary.json", doc)
    print("| source | seed | cut | remaining | n | S1 approach | S2 over-ledge (policy) | S3 over-wall (policy) | S4 qualified | S5 left break | falls | horizon | min x | max y | mean v2 return |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in per:
        print(f"| {r['short']} | {r['seed']} | {r['cut']} | {r['remaining']} | {r['n']} | {r['S1']} | {r['S2']} ({r['S2_policy']}) | "
              f"{r['S3']} ({r['S3_policy']}) | {r['S4_any']} | {r['S5']} | {r['falls']} | {r['horizon']} | "
              f"{r['min_x_after_min']:.0f} | {r['max_y_after_max']:.0f} | {r['mean_return']} |")
    print("pooled", json.dumps(pooled), "outcome", outcome)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["trace", "states", "register", "foothold", "summarize"])
    ap.add_argument("--workers", default=3)
    args = ap.parse_args(argv)
    return {"trace": cmd_trace, "states": cmd_states, "register": cmd_register, "foothold": cmd_foothold,
            "summarize": cmd_summarize}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
