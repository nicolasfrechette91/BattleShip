#!/usr/bin/env python3
"""M7t synthetic prerequisite (docs/rl_learning_strategy_review_2026-09-29.md, revision 2, section 7).

Standalone. No BattleShip process, native code, M7 trainer, experiment contract, observation, reward or action module
is used or changed. The only project import is `rl/m7s_goal.py`'s unchanged `EpisodeData` / `sample_examples`, the
sampler revision 2 names for the S control's same-trajectory rows. Zero native ticks; optimizer steps on synthetic
data only.

    python rl/tools/m7t_synthetic_prereq.py selftest
    python rl/tools/m7t_synthetic_prereq.py world-check --out DIR
    python rl/tools/m7t_synthetic_prereq.py register --out DIR
    python rl/tools/m7t_synthetic_prereq.py run --out DIR [--smoke]

`register` writes DIR/registration.json: the pinned REG table below (world, data, model, training, evaluation,
diagnostics, gate rule, tests S1-S6, caps), its sha256, this file's sha256 and the UTC time; it never overwrites.
`run` refuses unless DIR/registration.json carries this file's REG digest; the code sha256 at registration and at run
are both recorded so any later code change (REG untouched) is visible. `--smoke` crash-tests every code path on
seed 99 with tiny sizes; it never reads or writes the registered seeds' outputs. DIR must be outside runs/.

Report: docs/rl_m7t_synthetic_prerequisite_2026-09-29.md.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "rl"))

import m7s_goal as mg  # noqa: E402  (unchanged M7s sampler, revision 2 section 4)

TOOL = "m7t_synthetic_prereq_v1"

# -- the registration: everything below is pinned before any training --------------------------------------------------

REG: Dict[str, Any] = {
    "id": "m7t_synth_prereq_v1",
    "design": "docs/rl_learning_strategy_review_2026-09-29.md revision 2, section 7",
    "world": {
        "size_xy": [192, 64],
        "cell_xy": [8, 4],
        "floors_id_y_x0_x1_oneway": [[0, 45, 32, 39, False], [1, 8, 40, 191, False], [2, 20, 48, 58, True],
                                     [3, 8, 2, 31, False], [4, 30, 10, 20, True], [19, 28, 104, 116, True]],
        "wall_x0_x1_top": [32, 39, 45],
        "start_xy": [170, 8],
        "jump_vy": 5, "double_jump_vy": 4, "gravity": 1, "vy_min_max": [-5, 5],
        "squat_ticks": 3, "attack_lock": 6, "landing_lag": 4,
        "speed": "ground vx = stick x (1 unit/tick); air vx += stick x, clamped to [-1, 1] (drift, also in locks)",
        "words": "72 = 9 sticks (Track 1 order, unit magnitude) x 8 buttons (none, A, B, C-up, C-left, L, R, Z); "
                 "A = attack (6-tick lock; in the air: drift continues, landing inside it adds a 4-tick lag); "
                 "C-up / C-left = jump (grounded: 3-tick squat then vy +5; airborne: double jump vy +4 if one "
                 "left); B, L, R, Z and stick-up are inert; stick-down while falling = fast fall (vy -5)",
        "edge_rule": "jump and attack fire only on a press edge: the word's button class (attack / jump) differs from "
                     "the previous word's",
        "death": "y < 0 (the pit left of the left floor); the death tick is invalid",
        "cells": "i = x // 8 (24), j = y // 4 (16), contact = floor id if grounded else air (M7s tuple form)",
    },
    "data": {"seeds": [0, 1, 2], "episodes": 120, "horizon": 3600, "phase_a": 20, "held_out": 12,
             "behaviour": "uniform over the 72 words; per-episode generator sha256('m7t_synth|behaviour|seed|ep')",
             "held_out_rule": "the 12 episodes with the smallest sha256('m7t_synth|split|seed|ep')"},
    "observation": {"size": 626,
                    "layout": "action_class 23 + agent 45 (v4 field order; clock at agent index 24) + projectiles 28 "
                              "(zero) + segment_geometry 32x8 (Mario-relative, 9 used) + segment_kind 32x7 (static) + "
                              "targets 10x5 (static distractor points)",
                    "standardisation": "training-split mean / max(std, 0.01), frozen"},
    "model": {"encoder": [626, 256, 256, 256], "goal_encoder": [10, 256, 256],
              "goal_features": "cell centre (2) + contact one-hot over (air, 0, 1, 2, 3, 4, 19, other)",
              "iqe": {"components": 16, "dim_per_component": 16, "reduction": "maxmean",
                      "raw_alpha_init": -1.0, "reference": "torchqmet iqe() + MaxMean, reimplemented"},
              "dynamics": {"hidden": [256, 256], "input": "z (256) + one-hot stick (9) + one-hot button (8)",
                           "residual": True, "zero_init_last": True},
              "init": "one parameter set per seed from torch seed sha256('m7t_synth|init|seed'), shared by T and S"},
    "training": {"steps": 20000, "optimizer": "Adam", "lr": 3.0e-4, "lambda_optimizer": "Adam",
                 "lambda_lr": 0.3, "lambda_init": 0.01, "epsilon": 0.25,
                 "phi": {"form": "softplus(offset - d, beta), mean", "offset": 4000.0, "beta": 0.00125},
                 "dynamics_weight": 75.0,
                 "rows": {"constraint_main": 512, "membership": 256, "spread_state_state": 384,
                          "spread_state_goal": 384, "spread_goal_state_sink": 256, "model": 512},
                 "batch_sharing": "one shared sample of 512 transitions per step (reference-code style): local rows "
                                  "(T) and model rows are those transitions; membership = next states 0..255; spread "
                                  "state-state = zx[:384] vs roll(zy, 1)[:384]; state-goal = zx[128:] vs random goal "
                                  "nodes; sink = random goal nodes vs zy[256:]",
                 "T_main_rows": "(s_t -> s_t+1, cost 1)",
                 "S_main_rows": "(s_t -> G, cost h) from m7s_goal.sample_examples (unchanged) on the training split",
                 "generators": "batch rows sha256('m7t_synth|batch|seed') identical for T and S; S rows "
                               "sha256('m7t_synth|s_rows|seed')",
                 "threads": 6},
    "evaluation": {"policy": "greedy argmin over the 72 words of d(T(z, a), w(G)); ties -> lowest index "
                             "(torch.argmin)",
                   "success": "first valid reach of the commanded cell (cell and contact) within the budget",
                   "rare_goals": {"band": [1, 2], "count": 20,
                                  "order": "sha256('m7t_synth|E|seed|cell')", "budget": 3600},
                   "replays": {"T": 10, "S": 4, "method": "re-simulate the recorded words from tick 0"}},
    "diagnostics": {"support_subset": "action_class 23 + agent 45 minus the clock (agent index 24) = 67 values "
                                      "(standardised)",
                    "support_reference": 50000, "calibration": "p99 over the held-out episodes (states / recorded "
                                                               "transitions)",
                    "OFF": "support NN distance > p99 for 10 consecutive ticks (flag time = first tick)",
                    "MODEL": "realised two-way error of the executed word > p99 on >= 3 of 10 consecutive ticks "
                             "(flag time = first exceeding tick of the first such window)",
                    "LOOP": "running min of d(z_t, w(G)) decreases by < 1 over 300 ticks, with no OFF run start "
                            "and no MODEL window start inside the window",
                    "FALSE_ARRIVAL": "d(z_t, w(G)) <= 30, cell not reached within the next 120 ticks, on-support and "
                                     "previous-tick model error <= p99",
                    "tie_order": ["OFF", "MODEL", "LOOP", "FALSE_ARRIVAL"],
                    "attribution": "OFF / MODEL -> execution-limited; LOOP / FALSE_ARRIVAL / none -> distance-limited"},
    "gate_rule": {"F1": {"max_local": 1.5, "min_frac": 0.90},
                  "F2": {"h_max": 64, "min_spearman": 0.30, "pairs": 20000},
                  "F3": {"max_median": 0.5, "rows": 20000},
                  "D0": {"min_distance": 3000.0, "min_frac": 0.99, "states": 2000},
                  "sighted": {"states": 4000, "min_frac": 0.10},
                  "return_min": 6, "twin_margin": 4, "null_slack": 1, "exec_healthy_min": 0.5,
                  "chance": "q_g = (v_g + 1) / (N + 2) over the 100 non-phase-A episodes; mu = sum q_g; K = most E "
                            "goals any single one of those episodes reached",
                  "outcomes": {"1": "Pass in >= 2 seeds", "2": "Null in >= 2 seeds", "3": "Return in >= 2 seeds",
                               "4": "otherwise"}},
    "tests": {
        "S1": {"scope": "every seed; goals = distinct valid cells of the training split except the start cell; "
                        "truth = BFS over the world from the start (dynamic state)",
               "min_spearman": 0.9, "under_ratio": 0.8, "max_under_frac": 0.05},
        "S2": {"stitch_only": "min over training episodes of the own-episode loop-free shortest path to G > budget; "
                              "L* = union data-graph shortest path from the start (dynamic-state identity); "
                              "budget = floor(1.25 L*) + 20",
               "success": "first valid reach within the budget", "max_goals_per_seed": 20,
               "order": "sha256('m7t_synth|S2|seed|cell')", "min_goals_pooled": 15, "T_min": 0.70, "S_max": 0.30,
               "gate_rule_outcome": 1},
        "S3": {"pairs": "recorded airborne states in one cell, jumps_left 1 (a) and 0 (b), no lock; G = the first goal "
                        "node (sha256 order) with truth d_a <= 30 and d_b >= 2 d_a (unreachable -> 3600)",
               "pairs_per_seed": 30, "min_pairs_pooled": 15, "ratio_min": 0.8, "frac_min": 0.90,
               "D0": "T passes D0 in every seed"},
        "S4": {"OFF": "start displaced to the first of [16,8] (F3), [15,30] (F4), [35,45] (F0) whose support "
                      "distance exceeds p99",
               "MODEL": "scores use T(z, pi(a)) with pi = (stick + 3) % 9, (button + 3) % 8",
               "LOOP": "the neutral word (0, 0) is forced from tick 30",
               "goals": "the seed's rare goals", "min_failed_pooled": 10, "correct_min": 0.80,
               "false_alarm_max": 0.10, "false_alarm": "OFF or MODEL flag before the reach, over successful healthy "
                                                       "T episodes (rare + S2)",
               "min_healthy_successes": 10},
        "S5": {"requirement": "the untrained initialisation (T = S = init) is null or not functional in every seed"},
        "S6": {"steps": 20000, "max_train_wall_s": 3600},
        "overall": "PASS iff S1-S6 all pass",
    },
    "caps": {"train_wall_s": 3600, "harness_wall_s": 28800},
}


def canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


REG_DIGEST = hashlib.sha256(canon(REG)).hexdigest()


def seed_int(*parts: Any) -> int:
    return int(hashlib.sha256(("m7t_synth|" + "|".join(str(p) for p in parts)).encode()).hexdigest()[:16], 16)


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def file_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# -- the world ----------------------------------------------------------------------------------------------------------

W = REG["world"]
WX, WY = W["size_xy"]
CELL_X, CELL_Y = W["cell_xy"]
NXC, NYC = WX // CELL_X, WY // CELL_Y
FLOORS = [tuple(f) for f in W["floors_id_y_x0_x1_oneway"]]
WALL_X0, WALL_X1, WALL_TOP = W["wall_x0_x1_top"]
START_X, START_Y = W["start_xy"]
JUMP_VY, DJ_VY, GRAV = W["jump_vy"], W["double_jump_vy"], W["gravity"]
VY_MIN, VY_MAX = W["vy_min_max"]
SQUAT, ATK_LOCK, LAND_LAG = W["squat_ticks"], W["attack_lock"], W["landing_lag"]
HORIZON = REG["data"]["horizon"]

STICK = np.array([(0, 0), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)], dtype=np.int64)
BCLASS = np.array([0, 1, 0, 2, 2, 0, 0, 0], dtype=np.int64)       # none, A, B, C-up, C-left, L, R, Z
BTN_Z = 7
AIR = mg.AIR
CONTACTS = mg.CONTACT_CLASSES                                      # (-1, 0, 1, 2, 3, 4, 19, -2)
CONTACT_INDEX = {c: k for k, c in enumerate(CONTACTS)}
DYN = ("x", "y", "vx", "vy", "g", "j", "sq", "lock", "pb")
DIMS = (WX, WY, 3, VY_MAX - VY_MIN + 1, 2, 3, SQUAT + 1, ATK_LOCK + 1, 3)
NSTATES = int(np.prod(DIMS))
# the 18 effective inputs (stick x, stick-down, button class) that span every word's dynamics
EFF = np.array([(sx, sy, bc) for sx in (-1, 0, 1) for sy in (-1, 0) for bc in (0, 1, 2)], dtype=np.int64)


def start_state(n: int = 1, x: int = START_X, y: int = START_Y) -> Dict[str, np.ndarray]:
    s = {k: np.zeros(n, np.int64) for k in DYN}
    s["x"][:] = x
    s["y"][:] = y
    s["g"][:] = 1
    s["j"][:] = 2
    return s


def floor_under(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    fid = np.full(len(x), -1, np.int64)
    for f, fy, x0, x1, _ in FLOORS:
        fid[(y == fy) & (x >= x0) & (x <= x1)] = f
    return fid


def step(s: Dict[str, np.ndarray], sx: np.ndarray, sy: np.ndarray, bc: np.ndarray):
    """One deterministic tick for arrays of states. Returns (next state, dead, events)."""
    x, y, vx, vy, g, j, sq, lock, pb = (s[k] for k in DYN)
    n = len(x)
    G = g == 1
    A = ~G
    eJ = (bc == 2) & (pb != 2)
    eA = (bc == 1) & (pb != 1)
    nvx, nvy, ng, nj, nsq, nlock = vx.copy(), vy.copy(), g.copy(), j.copy(), sq.copy(), lock.copy()
    atk = np.zeros(n, bool)
    # grounded
    sqa = G & (sq > 0)
    nsq[sqa] -= 1
    launch = sqa & (nsq == 0)
    lkg = G & ~sqa & (lock > 0)
    nlock[lkg] -= 1
    nvx[lkg] = 0
    fg = G & ~sqa & (lock == 0)
    sj = fg & eJ
    nsq[sj] = SQUAT
    sa = fg & eA
    nlock[sa] = ATK_LOCK
    nvx[sa] = 0
    atk |= sa
    mv = fg & ~eJ & ~eA
    nvx[mv] = sx[mv]
    # airborne
    lka = A & (lock > 0)
    nlock[lka] -= 1
    fa = A & (lock == 0)
    dj = fa & eJ & (j > 0)
    nvy[dj] = DJ_VY
    nj[dj] -= 1
    aa = fa & eA
    nlock[aa] = ATK_LOCK
    atk |= aa
    nvx[A] = np.clip(vx[A] + sx[A], -1, 1)
    # launch at the end of the squat
    nvy[launch] = JUMP_VY
    ng[launch] = 0
    nj[launch] = 1
    ff = A & (sy == -1) & (nvy < 0)
    nvy[ff] = VY_MIN
    # horizontal (no movement on squat ticks)
    hm = ~(sqa | sj)
    nx = np.clip(x + np.where(hm, nvx, 0), 0, WX - 1)
    blk = (y < WALL_TOP) & (nx >= WALL_X0) & (nx <= WALL_X1) & (nx != x)
    wl = blk & (nx < x)
    wr = blk & (nx > x)
    nx = np.where(blk, x, nx)
    # vertical
    air = ng == 0
    ny = y.copy()
    ny[air] = y[air] + nvy[air]
    ceil = air & (ny > WY - 1)
    ny[ceil] = WY - 1
    vyu = nvy.copy()
    nvy[ceil] = 0
    land_y = np.full(n, -1, np.int64)
    for f, fy, x0, x1, _ in FLOORS:
        c = air & (vyu <= 0) & (y >= fy) & (ny <= fy) & (nx >= x0) & (nx <= x1) & (fy > land_y)
        land_y[c] = fy
    landed = land_y >= 0
    ny[landed] = land_y[landed]
    ng[landed] = 1
    nvy[landed] = 0
    nj[landed] = 2
    lag = landed & (nlock > 0)
    nlock[lag] = LAND_LAG
    grav = air & ~landed
    nvy[grav] = np.maximum(nvy[grav] - GRAV, VY_MIN)
    # walking off an edge keeps one jump
    on = floor_under(nx, ny) >= 0
    wo = (ng == 1) & ~on
    ng[wo] = 0
    nvy[wo] = 0
    nj[wo] = np.minimum(nj[wo], 1)
    dead = ny < 0
    ns = {"x": nx, "y": ny, "vx": nvx, "vy": nvy, "g": ng, "j": nj, "sq": nsq, "lock": nlock, "pb": bc.copy()}
    ev = {"wl": wl, "wr": wr, "ceil": ceil, "landed": landed, "lag": lag, "atk": atk}
    return ns, dead, ev


def pack(s: Dict[str, np.ndarray]) -> np.ndarray:
    idx = np.zeros(len(s["x"]), np.int64)
    vals = (s["x"], s["y"], s["vx"] + 1, s["vy"] - VY_MIN, s["g"], s["j"], s["sq"], s["lock"], s["pb"])
    for v, d in zip(vals, DIMS):
        idx = idx * d + v
    return idx


def unpack(idx: np.ndarray) -> Dict[str, np.ndarray]:
    out = []
    r = idx.copy()
    for d in reversed(DIMS):
        out.append(r % d)
        r //= d
    x, y, vx1, vy0, g, j, sq, lock, pb = reversed(out)
    return {"x": x, "y": y, "vx": vx1 - 1, "vy": vy0 + VY_MIN, "g": g, "j": j, "sq": sq, "lock": lock, "pb": pb}


def cell_codes(s: Dict[str, np.ndarray]) -> np.ndarray:
    """Integer code of the goal cell (i, j, contact) of each state."""
    fid = np.where(s["g"] == 1, floor_under(s["x"], s["y"]), AIR)
    ci = np.full(len(fid), CONTACT_INDEX[mg.OTHER], np.int64)
    for c, k in CONTACT_INDEX.items():
        ci[fid == c] = k
    return ((s["x"] // CELL_X) * NYC + np.clip(s["y"], 0, WY - 1) // CELL_Y) * len(CONTACTS) + ci


def code_to_cell(code: int) -> Tuple[int, int, int]:
    ci = code % len(CONTACTS)
    ij = code // len(CONTACTS)
    return (int(ij // NYC), int(ij % NYC), int(CONTACTS[ci]))


def cell_to_code(c: Tuple[int, int, int]) -> int:
    return (c[0] * NYC + c[1]) * len(CONTACTS) + CONTACT_INDEX[c[2]]


_VISITED: Optional[np.ndarray] = None


def bfs(start: Dict[str, np.ndarray], max_depth: int = HORIZON, want: Optional[set] = None,
        world_mod: Optional[str] = None) -> Tuple[Dict[int, int], int]:
    """Shortest ticks from `start` (one state) to every cell code reachable within max_depth; stops early once every
    code in `want` is found. world_mod 'no_double_jump' disables the double jump (for the world check)."""
    global _VISITED
    if _VISITED is None:
        _VISITED = np.zeros(NSTATES, bool)
    vis = _VISITED
    marked: List[np.ndarray] = []
    fr = {k: v.copy() for k, v in start.items()}
    i0 = pack(fr)
    vis[i0] = True
    marked.append(i0)
    depth: Dict[int, int] = {int(cell_codes(fr)[0]): 0}
    n_states = 1
    try:
        for d in range(1, max_depth + 1):
            m = len(fr["x"])
            rep = {k: np.repeat(v, len(EFF)) for k, v in fr.items()}
            act = np.tile(EFF, (m, 1))
            if world_mod == "no_double_jump":
                rep["j"] = np.where(rep["g"] == 1, rep["j"], 0)
            ns, dead, _ = step(rep, act[:, 0], act[:, 1], act[:, 2])
            if world_mod == "no_double_jump":
                ns["j"] = np.where(ns["g"] == 1, ns["j"], 0)
            keep = ~dead
            ns = {k: v[keep] for k, v in ns.items()}
            idx = pack(ns)
            idx, first = np.unique(idx, return_index=True)
            new = ~vis[idx]
            idx, first = idx[new], first[new]
            if len(idx) == 0:
                break
            vis[idx] = True
            marked.append(idx)
            fr = {k: v[first] for k, v in ns.items()}
            n_states += len(idx)
            for c in np.unique(cell_codes(fr)):
                depth.setdefault(int(c), d)
            if want is not None and want.issubset(depth.keys()):
                break
    finally:
        for mk in marked:
            vis[mk] = False
    return depth, n_states


# -- episodes and observation records ------------------------------------------------------------------------------------

REC = ("x", "y", "vx", "vy", "g", "j", "sq", "lock", "pb", "floor", "lk", "stick", "button", "dx", "dy", "facing",
       "wl", "wr", "ceil", "status", "stics", "tapx", "tapy", "zage", "clock", "dead")


def status_of(r: Dict[str, np.ndarray]) -> np.ndarray:
    st = np.zeros(len(r["x"]), np.int64)
    g = r["g"] == 1
    st[g & (r["vx"] != 0)] = 1
    st[g & (r["sq"] > 0)] = 2
    st[g & (r["lock"] > 0) & (r["lk"] == 1)] = 6
    st[g & (r["lock"] > 0) & (r["lk"] == 3)] = 7
    a = ~g
    st[a & (r["j"] > 0)] = 3
    st[a & (r["j"] == 0)] = 4
    st[a & (r["lock"] > 0)] = 5
    return st


def initial_record(s: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    n = len(s["x"])
    r = {k: v.copy() for k, v in s.items()}
    z = lambda: np.zeros(n, np.int64)  # noqa: E731
    r.update(floor=np.where(s["g"] == 1, floor_under(s["x"], s["y"]), -1), lk=z(), stick=z(), button=z(), dx=z(),
             dy=z(), facing=np.ones(n, np.int64), wl=z(), wr=z(), ceil=z(), stics=z(), tapx=z(), tapy=z(),
             zage=np.full(n, 11, np.int64), clock=z(), dead=z())
    r["status"] = status_of(r)
    return r


def advance(r: Dict[str, np.ndarray], words: np.ndarray) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
    """Apply one word per row to records r (alive rows); returns the next records and the dead flags."""
    st, bt = words // 8, words % 8
    sx, sy = STICK[st, 0], STICK[st, 1]
    bc = BCLASS[bt]
    s = {k: r[k] for k in DYN}
    ns, dead, ev = step(s, sx, sy, bc)
    nr = dict(ns)
    lk = r["lk"].copy()
    lk[ev["atk"] & (ns["g"] == 1)] = 1
    lk[ev["atk"] & (ns["g"] == 0)] = 2
    lk[ev["lag"]] = 3
    lk[ns["lock"] == 0] = 0
    nr["lk"] = lk
    nr["floor"] = np.where(ns["g"] == 1, floor_under(ns["x"], ns["y"]), -1)
    nr["stick"], nr["button"] = st, bt
    nr["dx"], nr["dy"] = ns["x"] - r["x"], ns["y"] - r["y"]
    nr["facing"] = np.where(ns["vx"] != 0, np.sign(ns["vx"]), r["facing"])
    nr["wl"], nr["wr"], nr["ceil"] = ev["wl"].astype(np.int64), ev["wr"].astype(np.int64), ev["ceil"].astype(np.int64)
    nr["status"] = status_of(nr)
    nr["stics"] = np.where(nr["status"] == r["status"], np.minimum(r["stics"] + 1, 240), 0)
    psx, psy = STICK[r["stick"], 0], STICK[r["stick"], 1]
    nr["tapx"] = np.where(sx == 0, 0, np.where(sx != psx, 1, np.minimum(r["tapx"] + 1, 254)))
    nr["tapy"] = np.where(sy == 0, 0, np.where(sy != psy, 1, np.minimum(r["tapy"] + 1, 254)))
    nr["zage"] = np.where(bt == BTN_Z, 0, np.minimum(r["zage"] + 1, 65535))
    nr["clock"] = r["clock"] + 1
    nr["dead"] = dead.astype(np.int64)
    return nr, dead


SEGS = [(x0, fy, x1, fy, 0 if not ow else 4) for _, fy, x0, x1, ow in FLOORS] + \
       [(WALL_X0, 0, WALL_X0, WALL_TOP, 2), (WALL_X1, 0, WALL_X1, WALL_TOP, 3), (0, 0, 0, WY - 1, 6),
        (WX - 1, 0, WX - 1, WY - 1, 6)]
SEG_KIND = np.zeros((32, 7), np.float32)
for _k, _s in enumerate(SEGS):
    SEG_KIND[_k, _s[4]] = 1.0
    if _s[4] == 4:
        SEG_KIND[_k, 0] = 1.0
TARGET_PTS = np.array([(20, 50), (40, 12), (60, 45), (100, 30), (120, 12), (140, 40), (160, 25), (180, 50),
                       (30, 35), (170, 10)], np.float32)
TAP = np.array([0.0, 1.0, 0.75, 0.5] + [0.25] * 251, np.float32)
OBS_DIM = 626
STD_FLOOR = 0.01                                                   # REG observation.standardisation
SUPPORT_COLS = np.array(list(range(23)) + [23 + k for k in range(45) if k != 24], np.int64)   # 67 values


def build_obs(r: Dict[str, np.ndarray]) -> np.ndarray:
    n = len(r["x"])
    o = np.zeros((n, OBS_DIM), np.float32)
    o[np.arange(n), r["status"]] = 1.0
    a = o[:, 23:68]
    x = r["x"].astype(np.float32)
    y = r["y"].astype(np.float32)
    g = r["g"].astype(np.float32)
    a[:, 0] = x / (WX / 2.0) - 1.0
    a[:, 1] = y / (WY / 2.0) - 1.0
    a[:, 2] = r["dx"]
    a[:, 3] = r["dy"] / 5.0
    a[:, 4] = r["vx"] * (1 - g)
    a[:, 5] = r["vy"] / 5.0
    a[:, 6] = r["vx"] * g
    a[:, 9] = r["facing"]
    a[:, 10] = g
    a[:, 11] = g
    a[:, 12] = r["ceil"]
    a[:, 13] = r["wl"]
    a[:, 14] = r["wr"]
    below = np.full(n, -1.0, np.float32)
    for _, fy, x0, x1, _ in FLOORS:
        c = (r["x"] >= x0) & (r["x"] <= x1) & (r["y"] >= fy) & (fy > below)
        below[c] = fy
    a[:, 15] = np.where(below >= 0, (y - below) / 32.0, 2.0)
    a[:, 16] = r["j"] / 2.0
    a[:, 17] = r["status"] / 256.0
    a[:, 18] = np.minimum(r["stics"], 240) / 60.0
    a[:, 20] = ((r["lock"] > 0) & ((r["lk"] == 1) | (r["lk"] == 2))).astype(np.float32)
    a[:, 23] = ((r["g"] == 0) & (r["vy"] == VY_MIN)).astype(np.float32)
    a[:, 24] = r["clock"] / float(HORIZON)
    a[:, 25] = 1.0
    a[:, 28] = STICK[r["stick"], 0]
    a[:, 29] = STICK[r["stick"], 1]
    for col, b in zip(range(30, 37), (1, 2, 7, 5, 6, 3, 4)):          # A, B, Z, L, R, C-up, C-left
        a[:, col] = (r["button"] == b)
    a[:, 37] = TAP[np.minimum(r["tapx"], 254)]
    a[:, 38] = TAP[np.minimum(r["tapy"], 254)]
    a[:, 39] = np.minimum(r["zage"], 10) / 10.0
    a[:, 40] = (r["zage"] > 10)
    a[:, 41] = np.minimum(r["stics"], 240) / 60.0
    a[:, 42] = 0.5
    a[:, 43] = ((r["g"] == 0) & (r["lock"] > 0)).astype(np.float32)
    edge = np.zeros(n, bool)
    for _, fy, x0, x1, _ in FLOORS:
        edge |= (r["g"] == 1) & (r["y"] == fy) & ((r["x"] == x0) | (r["x"] == x1))
    a[:, 44] = edge
    seg = o[:, 96:352].reshape(n, 32, 8)
    for k, (x0, y0, x1, y1, _) in enumerate(SEGS):
        seg[:, k, 0] = (x0 - x) / WX
        seg[:, k, 1] = (y0 - y) / WY
        seg[:, k, 2] = (x1 - x) / WX
        seg[:, k, 3] = (y1 - y) / WY
        seg[:, k, 4] = (np.clip(x, min(x0, x1), max(x0, x1)) - x) / WX
        seg[:, k, 5] = (np.clip(y, min(y0, y1), max(y0, y1)) - y) / WY
    o[:, 352:576] = SEG_KIND.reshape(-1)
    t = o[:, 576:626].reshape(n, 10, 5)
    t[:, :, 0] = (TARGET_PTS[None, :, 0] - x[:, None]) / WX
    t[:, :, 1] = (TARGET_PTS[None, :, 1] - y[:, None]) / WY
    t[:, :, 2] = 1.0
    return o


def rec_take(recs: Dict[str, np.ndarray], rows: np.ndarray) -> Dict[str, np.ndarray]:
    return {k: v[rows] for k, v in recs.items()}


def collect(seed: int, n_episodes: int, horizon: int = HORIZON) -> Dict[str, Any]:
    """Uniform-random behaviour from the fixed start. Records every state row (tick 0 .. T, including a death row)
    and every word; cells per row (None = invalid death row)."""
    words = np.stack([np.random.default_rng(seed_int("behaviour", seed, e)).integers(72, size=horizon)
                      for e in range(n_episodes)])
    r = initial_record(start_state(n_episodes))
    rows: List[Dict[str, np.ndarray]] = [r]
    alive = np.ones(n_episodes, bool)
    length = np.full(n_episodes, horizon, np.int64)
    for t in range(horizon):
        nr, dead = advance(r, words[:, t])
        for k in REC:                                   # dead episodes are frozen (their later rows are dropped)
            nr[k] = np.where(alive, nr[k], r[k])
        newly = alive & dead
        length[newly] = t + 1
        rows.append(nr)
        alive &= ~dead
        r = nr
    st = {k: np.stack([rw[k] for rw in rows], axis=1) for k in REC}       # (E, horizon + 1)
    eps = []
    for e in range(n_episodes):
        T = int(length[e])
        rec = {k: st[k][e, :T + 1].copy() for k in REC}
        eps.append({"id": f"s{seed}_e{e:03d}", "T": T, "rec": rec, "words": words[e, :T].copy()})
    return {"seed": seed, "episodes": eps}


def episode_cells(ep: Dict[str, Any]) -> List[Optional[Tuple[int, int, int]]]:
    r = ep["rec"]
    codes = cell_codes({k: r[k] for k in DYN})
    return [None if r["dead"][k] else code_to_cell(int(codes[k])) for k in range(ep["T"] + 1)]


# -- memory ---------------------------------------------------------------------------------------------------------------


class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def memory_mb() -> Dict[str, float]:
    if platform.system() != "Windows":
        return {}
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    h = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    return {"working_set_mb": pmc.WorkingSetSize / 2 ** 20, "peak_working_set_mb": pmc.PeakWorkingSetSize / 2 ** 20,
            "private_mb": pmc.PagefileUsage / 2 ** 20, "peak_private_mb": pmc.PeakPagefileUsage / 2 ** 20}


# -- networks (torch imported lazily) -------------------------------------------------------------------------------------


def torch_mod():
    import torch
    torch.set_num_threads(REG["training"]["threads"])
    return torch


def make_nets(torch, mean: np.ndarray, std: np.ndarray):
    nn = torch.nn
    M = REG["model"]
    comps, dim = M["iqe"]["components"], M["iqe"]["dim_per_component"]

    def mlp(sizes):
        layers = []
        for i in range(len(sizes) - 1):
            layers.append(nn.Linear(sizes[i], sizes[i + 1]))
            if i < len(sizes) - 2:
                layers.append(nn.ReLU())
        return nn.Sequential(*layers)

    class Nets(nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
            self.register_buffer("std", torch.tensor(std, dtype=torch.float32))
            self.enc = mlp(M["encoder"])
            self.genc = mlp(M["goal_encoder"])
            self.dyn = mlp([256 + 17] + M["dynamics"]["hidden"] + [256])
            nn.init.zeros_(self.dyn[-1].weight)
            nn.init.zeros_(self.dyn[-1].bias)
            self.raw_alpha = nn.Parameter(torch.tensor(M["iqe"]["raw_alpha_init"]))

        def z(self, obs):
            return self.enc((obs - self.mean) / self.std)

        def w(self, gfeat):
            return self.genc(gfeat)

        def d(self, a, b):
            x = a.unflatten(-1, (comps, dim))
            y = b.unflatten(-1, (comps, dim))
            x, y = torch.broadcast_tensors(x, y)
            valid = x < y
            xy = torch.cat([x, y], dim=-1)
            sxy, ixy = xy.sort(dim=-1)
            neg_inc = torch.gather(valid, -1, ixy % dim) * torch.where(ixy < dim, -1, 1)
            neg_inp = torch.cumsum(neg_inc, dim=-1)
            neg_f = (neg_inp < 0) * (-1.0)
            neg_incf = torch.cat([neg_f.narrow(-1, 0, 1), torch.diff(neg_f, dim=-1)], dim=-1)
            comp = (sxy * neg_incf).sum(-1)
            alpha = torch.sigmoid(self.raw_alpha)
            return torch.lerp(comp.mean(-1), comp.max(-1).values, alpha)

        def T(self, z, words):
            st = torch.nn.functional.one_hot(words // 8, 9).float()
            bt = torch.nn.functional.one_hot(words % 8, 8).float()
            return z + self.dyn(torch.cat([z, st, bt], dim=-1))

    return Nets()


def goal_feats(codes: np.ndarray) -> np.ndarray:
    codes = np.asarray(codes, np.int64)
    ci = codes % len(CONTACTS)
    ij = codes // len(CONTACTS)
    f = np.zeros((len(codes), 10), np.float32)
    f[:, 0] = ((ij // NYC) * CELL_X + CELL_X / 2) / (WX / 2.0) - 1.0
    f[:, 1] = ((ij % NYC) * CELL_Y + CELL_Y / 2) / (WY / 2.0) - 1.0
    f[np.arange(len(codes)), 2 + ci] = 1.0
    return f


def iqe_brute(x: np.ndarray, y: np.ndarray, comps: int, dim: int) -> np.ndarray:
    """Union-of-intervals length per component, brute force (selftest)."""
    out = np.zeros(comps)
    for c in range(comps):
        iv = sorted((a, max(a, b)) for a, b in zip(x[c * dim:(c + 1) * dim], y[c * dim:(c + 1) * dim]) if b > a)
        tot, cur_s, cur_e = 0.0, None, None
        for s0, e0 in iv:
            if cur_e is None or s0 > cur_e:
                if cur_e is not None:
                    tot += cur_e - cur_s
                cur_s, cur_e = s0, e0
            else:
                cur_e = max(cur_e, e0)
        if cur_e is not None:
            tot += cur_e - cur_s
        out[c] = tot
    return out


# -- a seed's dataset ----------------------------------------------------------------------------------------------------


class SeedData:
    def __init__(self, seed: int, n_episodes: int, horizon: int, phase_a: int, held_out: int):
        self.seed = seed
        raw = collect(seed, n_episodes, horizon)
        self.eps = raw["episodes"]
        order = sorted(range(n_episodes), key=lambda e: hashlib.sha256(
            f"m7t_synth|split|{seed}|{e}".encode()).hexdigest())
        self.held = set(order[:held_out])
        self.train = [e for e in range(n_episodes) if e not in self.held]
        self.phase_a = list(range(phase_a))
        self.others = list(range(phase_a, n_episodes))
        self.cells = [episode_cells(ep) for ep in self.eps]
        # concatenated state rows of every episode
        offs, tot = [], 0
        for ep in self.eps:
            offs.append(tot)
            tot += ep["T"] + 1
        self.off = np.array(offs, np.int64)
        self.recs = {k: np.concatenate([ep["rec"][k] for ep in self.eps]) for k in REC}
        self.words = [ep["words"] for ep in self.eps]
        self.codes = np.concatenate([np.array([-1 if c is None else cell_to_code(c) for c in cl], np.int64)
                                     for cl in self.cells])

        def trans(ep_list):
            src, dst, wd = [], [], []
            for e in ep_list:
                T = self.eps[e]["T"]
                ok = np.array([not self.eps[e]["rec"]["dead"][k + 1] for k in range(T)], bool)
                ks = np.nonzero(ok)[0]
                src.append(self.off[e] + ks)
                dst.append(self.off[e] + ks + 1)
                wd.append(self.words[e][ks])
            return np.concatenate(src), np.concatenate(dst), np.concatenate(wd)

        self.tr_src, self.tr_dst, self.tr_word = trans(self.train)
        self.ho_src, self.ho_dst, self.ho_word = trans(sorted(self.held))
        train_rows = np.concatenate([self.off[e] + np.arange(self.eps[e]["T"] + 1) for e in self.train])
        self.train_rows = train_rows[self.codes[train_rows] >= 0]
        held_rows = np.concatenate([self.off[e] + np.arange(self.eps[e]["T"] + 1) for e in sorted(self.held)])
        self.held_rows = held_rows[self.codes[held_rows] >= 0]
        self.goal_nodes = np.unique(self.codes[self.train_rows])
        # standardisation (training split, frozen)
        s1 = np.zeros(OBS_DIM)
        s2 = np.zeros(OBS_DIM)
        for c0 in range(0, len(self.train_rows), 50000):
            ob = build_obs(rec_take(self.recs, self.train_rows[c0:c0 + 50000])).astype(np.float64)
            s1 += ob.sum(0)
            s2 += (ob ** 2).sum(0)
        m = s1 / len(self.train_rows)
        v = np.maximum(s2 / len(self.train_rows) - m ** 2, 0.0)
        self.mean = m.astype(np.float32)
        self.std = np.maximum(np.sqrt(v), STD_FLOOR).astype(np.float32)
        # M7s EpisodeData for the S rows (dummy obs; cells k = 1..T)
        self.m7s_eps = []
        self.m7s_index = {}
        for e in self.train:
            ep = self.eps[e]
            T = ep["T"]
            self.m7s_index[ep["id"]] = e
            self.m7s_eps.append(mg.EpisodeData(
                episode_id=ep["id"], origin="train", obs=np.zeros((T, 1), np.float32),
                pos=np.zeros((T, 2), np.float32),
                actions=np.stack([ep["words"] // 8, ep["words"] % 8], axis=1).astype(np.int64),
                cells=self.cells[e][1:]))

    def obs(self, rows: np.ndarray) -> np.ndarray:
        return build_obs(rec_take(self.recs, rows))

    def dyn_state(self, rows: np.ndarray) -> Dict[str, np.ndarray]:
        return {k: self.recs[k][rows] for k in DYN}


# -- training -------------------------------------------------------------------------------------------------------------


def train_arm(torch, arm: str, sd: SeedData, init_state: Dict[str, Any], steps: int, cap_s: float,
              log: List[Dict[str, Any]]) -> Tuple[Any, Dict[str, Any]]:
    tr = REG["training"]
    rows = tr["rows"]
    nets = make_nets(torch, sd.mean, sd.std)
    nets.load_state_dict(init_state)
    raw_lam = torch.nn.Parameter(torch.tensor(math.log(math.expm1(tr["lambda_init"])), dtype=torch.float32))
    opt = torch.optim.Adam(nets.parameters(), lr=tr["lr"])
    opt_l = torch.optim.Adam([raw_lam], lr=tr["lambda_lr"])
    rng_b = np.random.default_rng(seed_int("batch", sd.seed))
    rng_s = np.random.default_rng(seed_int("s_rows", sd.seed))
    eps2 = tr["epsilon"] ** 2
    off, beta = tr["phi"]["offset"], tr["phi"]["beta"]
    n_goal = rows["spread_state_goal"] + rows["spread_goal_state_sink"]
    nb = rows["constraint_main"]
    t0, c0 = time.perf_counter(), time.process_time()
    done = 0
    for it in range(steps):
        if time.perf_counter() - t0 > cap_s:
            break
        ti = rng_b.integers(len(sd.tr_src), size=nb)
        gi = rng_b.integers(len(sd.goal_nodes), size=n_goal)
        src, dst, wd = sd.tr_src[ti], sd.tr_dst[ti], sd.tr_word[ti]
        obs = torch.from_numpy(sd.obs(np.concatenate([src, dst])))
        zz = nets.z(obs)
        zx, zy = zz[:nb], zz[nb:]
        gw = nets.w(torch.from_numpy(goal_feats(sd.goal_nodes[gi])))
        nm = rows["membership"]
        wm = nets.w(torch.from_numpy(goal_feats(sd.codes[dst[:nm]])))
        d_mem = nets.d(zy[:nm], wm)
        if arm == "T":
            d_main = nets.d(zx, zy)
            c_main = torch.ones(nb)
        else:
            ex = mg.sample_examples(sd.m7s_eps, nb, rng_s)
            erow = np.array([sd.off[sd.m7s_index[e]] for e in ex["episode"]], np.int64) + ex["t"]
            zs = nets.z(torch.from_numpy(sd.obs(erow)))
            gcodes = np.array([cell_to_code(tuple(int(v) for v in c)) for c in ex["cell"]], np.int64)
            d_main = nets.d(zs, nets.w(torch.from_numpy(goal_feats(gcodes))))
            c_main = torch.from_numpy(ex["h"].astype(np.float32))
        dc = torch.cat([d_main, d_mem])
        cost = torch.cat([c_main, torch.zeros(nm)])
        sq_dev = (dc - cost).relu().square().mean()
        k1, k2, k3 = rows["spread_state_state"], rows["spread_state_goal"], rows["spread_goal_state_sink"]
        d_ss = nets.d(zx[:k1], torch.roll(zy, 1, dims=0)[:k1])
        d_sg = nets.d(zx[nb - k2:], gw[:k2])
        d_gs = nets.d(gw[k2:k2 + k3], zy[nb - k3:])
        dsp = torch.cat([d_ss, d_sg, d_gs])
        l_push = torch.nn.functional.softplus(off - dsp, beta=beta).mean()
        pred = nets.T(zx, torch.from_numpy(wd))
        d_m = torch.stack([nets.d(pred, zy), nets.d(zy, pred)], dim=-1)
        l_dyn = tr["dynamics_weight"] * d_m.square().mean()
        lam = torch.nn.functional.softplus(raw_lam)
        lam_rev = lam.detach() + (-lam + lam.detach())           # value lam, gradient -1 x (gradient reversal)
        l_con = lam_rev * (sq_dev - eps2)
        loss = l_push + l_con + l_dyn
        opt.zero_grad()
        opt_l.zero_grad()
        loss.backward()
        opt.step()
        opt_l.step()
        done = it + 1
        if it % 500 == 0 or it == steps - 1:
            log.append({"step": it, "wall_s": round(time.perf_counter() - t0, 1), "push": float(l_push),
                        "sq_dev": float(sq_dev), "lambda": float(lam), "dyn_sq": float(d_m.square().mean()),
                        "d_main": float(d_main.mean()), "d_spread": float(dsp.mean()),
                        "d_mem": float(d_mem.mean())})
    info = {"arm": arm, "steps_done": done, "steps_registered": steps, "wall_s": time.perf_counter() - t0,
            "cpu_s": time.process_time() - c0, "completed": done == steps, "final_lambda": float(
                torch.nn.functional.softplus(raw_lam)), "memory": memory_mb()}
    info["s_per_step"] = info["wall_s"] / max(done, 1)
    return nets, info


# -- evaluation -----------------------------------------------------------------------------------------------------------


def run_episodes(torch, nets, sd: SeedData, goal_codes: Sequence[int], budgets: Sequence[int],
                 ref_support, starts: Optional[Tuple[int, int]] = None, plant: Optional[str] = None,
                 max_ticks: int = HORIZON) -> List[Dict[str, Any]]:
    """Greedy batched episodes from tick 0 (or a displaced start). Records words, reach tick and per-tick
    diagnostics: support NN distance, d(z_t, w(G)), realised two-way error of the executed word, predicted next
    distance."""
    B = len(goal_codes)
    if B == 0:
        return []
    s0 = start_state(B) if starts is None else start_state(B, *starts)
    r = initial_record(s0)
    gw = nets.w(torch.from_numpy(goal_feats(np.asarray(goal_codes))))
    allw = torch.arange(72)
    perm = (allw // 8 + 3) % 9 * 8 + (allw % 8 + 3) % 8
    active = np.ones(B, bool)
    reach = np.full(B, -1, np.int64)
    end = ["budget"] * B
    words: List[List[int]] = [[] for _ in range(B)]
    sig = [[] for _ in range(B)]
    dg = [[] for _ in range(B)]
    err = [[] for _ in range(B)]
    pdn = [[] for _ in range(B)]
    prev_pred = None
    budgets = np.asarray(budgets)
    with torch.no_grad():
        for t in range(max_ticks + 1):
            ai = np.nonzero(active)[0]
            if len(ai) == 0:
                break
            ob = build_obs(rec_take(r, ai))
            z = nets.z(torch.from_numpy(ob))
            dgt = nets.d(z, gw[ai]).numpy()
            sup = ref_support(ob)
            if prev_pred is not None:
                pp = prev_pred[ai]
                e2 = torch.maximum(nets.d(pp, z), nets.d(z, pp)).numpy()
            for k, b in enumerate(ai):
                sig[b].append(float(sup[k]))
                dg[b].append(float(dgt[k]))
                if prev_pred is not None:
                    err[b].append(float(e2[k]))
            # the episode has already ended on this row? (reach / death recorded on the previous step)
            if t == max_ticks:
                break
            zr = z.repeat_interleave(72, dim=0)
            wds = allw.repeat(len(ai))
            fed = perm.repeat(len(ai)) if plant == "MODEL" else wds
            pred = nets.T(zr, fed)
            sc = nets.d(pred, gw[ai].repeat_interleave(72, dim=0)).view(len(ai), 72)
            choice = torch.argmin(sc, dim=1)
            if plant == "LOOP" and t >= 30:
                choice = torch.zeros_like(choice)
            chosen_pred = pred.view(len(ai), 72, -1)[torch.arange(len(ai)), choice]
            full_pred = torch.zeros((B, chosen_pred.shape[1]))
            full_pred[ai] = chosen_pred
            prev_pred = full_pred
            pd = sc[torch.arange(len(ai)), choice].numpy()
            ch = choice.numpy().astype(np.int64)
            nr, dead = advance(rec_take(r, ai), ch)
            codes = cell_codes({k: nr[k] for k in DYN})
            for k, b in enumerate(ai):
                words[b].append(int(ch[k]))
                pdn[b].append(float(pd[k]))
            for key in REC:
                r[key][ai] = nr[key]
            for k, b in enumerate(ai):
                tick = t + 1
                if dead[k]:
                    active[b] = False
                    end[b] = "dead"
                elif codes[k] == goal_codes[b]:
                    active[b] = False
                    reach[b] = tick
                    end[b] = "reached"
                elif tick >= budgets[b]:
                    active[b] = False
                    end[b] = "budget"
            if not active.any():
                # record the final rows' diagnostics for the last transition (needed for the last error)
                pass
    out = []
    for b in range(B):
        out.append({"goal": int(goal_codes[b]), "budget": int(budgets[b]), "reach": int(reach[b]),
                    "success": bool(reach[b] > 0), "end": end[b], "len": len(words[b]), "words": words[b],
                    "sigma": sig[b], "dg": dg[b], "err": err[b], "pred_next": pdn[b], "plant": plant})
    return out


def replay_reach(words: Sequence[int], goal: int, starts: Optional[Tuple[int, int]] = None) -> int:
    s0 = start_state(1) if starts is None else start_state(1, *starts)
    r = initial_record(s0)
    for t, w in enumerate(words):
        r, dead = advance(r, np.array([w], np.int64))
        if dead[0]:
            return -1
        if int(cell_codes({k: r[k] for k in DYN})[0]) == goal:
            return t + 1
    return -1


def flags(ep: Dict[str, Any], p99_sig: float, p99_err: float) -> Dict[str, Optional[int]]:
    D = REG["diagnostics"]
    sig = np.array(ep["sigma"])
    err = np.array(ep["err"])
    dg = np.array(ep["dg"])
    n = len(sig)
    f: Dict[str, Optional[int]] = {"OFF": None, "MODEL": None, "LOOP": None, "FALSE_ARRIVAL": None}
    off_start = np.zeros(n, bool)
    for t in range(0, max(n - 9, 0)):
        if (sig[t:t + 10] > p99_sig).all():
            off_start[t] = True
    if off_start.any():
        f["OFF"] = int(np.argmax(off_start))
    ne = len(err)
    mod_start = np.zeros(max(ne, 1), bool)
    for t in range(0, max(ne - 9, 0)):
        exc = err[t:t + 10] > p99_err
        if exc.sum() >= 3:
            mod_start[t] = True
            if f["MODEL"] is None:
                f["MODEL"] = int(t + np.argmax(exc))
    runmin = np.minimum.accumulate(dg) if n else dg
    for t in range(0, n - 300):
        if runmin[t + 300] > runmin[t] - 1.0 and not off_start[t:t + 300].any() and \
                not mod_start[t:min(t + 300, len(mod_start))].any():
            f["LOOP"] = t
            break
    reach = ep["reach"]
    for t in range(n):
        if dg[t] <= 30.0 and not (0 < reach <= t + 120) and sig[t] <= p99_sig and                 (t == 0 or t - 1 >= len(err) or err[t - 1] <= p99_err):
            f["FALSE_ARRIVAL"] = t
            break
    return f


def attribute(fl: Dict[str, Optional[int]]) -> Tuple[str, str]:
    order = REG["diagnostics"]["tie_order"]
    best, bt = "none", None
    for k in order:
        v = fl[k]
        if v is not None and (bt is None or v < bt):
            best, bt = k, v
    return best, ("execution" if best in ("OFF", "MODEL") else "distance")


# -- statistics helpers ---------------------------------------------------------------------------------------------------


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    def rank(v):
        o = np.argsort(v, kind="mergesort")
        rk = np.empty(len(v), np.float64)
        rk[o] = np.arange(len(v))
        vs = v[o]
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and vs[j + 1] == vs[i]:
                j += 1
            rk[o[i:j + 1]] = (i + j) / 2.0
            i = j + 1
        return rk
    if len(a) < 3:
        return float("nan")
    ra, rb = rank(np.asarray(a, float)), rank(np.asarray(b, float))
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def data_graph_depths(sd: SeedData, ep_list: Sequence[int]) -> Dict[int, int]:
    """BFS over recorded transitions (dynamic-state identity) from the start; min depth per cell code."""
    src, dst = [], []
    for e in ep_list:
        T = sd.eps[e]["T"]
        rows = sd.off[e] + np.arange(T + 1)
        pk = pack(sd.dyn_state(rows))
        alive = sd.recs["dead"][rows] == 0
        ok = alive[1:] & alive[:-1]
        src.append(pk[:-1][ok])
        dst.append(pk[1:][ok])
    src_a, dst_a = np.concatenate(src), np.concatenate(dst)
    ed = np.unique(np.stack([src_a, dst_a], 1), axis=0)
    order = np.argsort(ed[:, 0], kind="stable")
    ed = ed[order]
    s0 = int(pack(start_state(1))[0])
    dist = {s0: 0}
    fr = np.array([s0], np.int64)
    d = 0
    while len(fr):
        d += 1
        lo = np.searchsorted(ed[:, 0], fr, "left")
        hi = np.searchsorted(ed[:, 0], fr, "right")
        nxt = np.unique(np.concatenate([ed[a:b, 1] for a, b in zip(lo, hi)])) if len(fr) else np.zeros(0, np.int64)
        nxt = np.array([v for v in nxt if int(v) not in dist], np.int64)
        for v in nxt:
            dist[int(v)] = d
        fr = nxt
    nodes = np.array(list(dist.keys()), np.int64)
    depths = np.array(list(dist.values()), np.int64)
    codes = cell_codes(unpack(nodes))
    best: Dict[int, int] = {}
    for c, dd in zip(codes, depths):
        c = int(c)
        if c not in best or dd < best[c]:
            best[c] = int(dd)
    return best


# -- per-seed pipeline --------------------------------------------------------------------------------------------------


def seed_pipeline(torch, sd: SeedData, out: Path, steps: int, smoke: bool, t_start: float) -> Dict[str, Any]:
    ER = REG["evaluation"]
    GR = REG["gate_rule"]
    TS = REG["tests"]
    res: Dict[str, Any] = {"seed": sd.seed, "episodes": len(sd.eps), "train_episodes": len(sd.train),
                           "transitions_train": int(len(sd.tr_src)), "goal_nodes": int(len(sd.goal_nodes)),
                           "deaths": int(sum(ep["rec"]["dead"][-1] for ep in sd.eps))}
    # rare goals E from phase A (1-2 of 20)
    cnt: Dict[int, int] = {}
    for e in sd.phase_a:
        for c in {cell_to_code(c) for c in sd.cells[e][1:] if c is not None}:
            cnt[c] = cnt.get(c, 0) + 1
    lo, hi = ER["rare_goals"]["band"]
    cand = [c for c, v in cnt.items() if lo <= v <= hi]
    cand.sort(key=lambda c: hashlib.sha256(f"m7t_synth|E|{sd.seed}|{code_to_cell(c)}".encode()).hexdigest())
    E = cand[:ER["rare_goals"]["count"]]
    res["rare_candidates"] = len(cand)
    res["E"] = [list(code_to_cell(c)) for c in E]
    # chance references from the 100 non-phase-A episodes
    reached_by = []
    for e in sd.others:
        s = {cell_to_code(c) for c in sd.cells[e][1:] if c is not None}
        reached_by.append([c in s for c in E])
    rb = np.array(reached_by, bool) if E else np.zeros((len(sd.others), 0), bool)
    N = len(sd.others)
    q = (rb.sum(0) + 1) / (N + 2)
    res["mu"] = float(q.sum())
    res["K"] = int(rb.sum(1).max()) if E else 0
    res["q"] = [float(v) for v in q]
    # support reference and calibration
    rng = np.random.default_rng(seed_int("support", sd.seed))
    ref_rows = rng.choice(sd.train_rows, size=min(REG["diagnostics"]["support_reference"], len(sd.train_rows)),
                          replace=False)
    ref = torch.from_numpy(((sd.obs(ref_rows) - sd.mean) / sd.std)[:, SUPPORT_COLS])

    def ref_support(ob: np.ndarray) -> np.ndarray:
        q_ = torch.from_numpy(((ob - sd.mean) / sd.std)[:, SUPPORT_COLS])
        return torch.cdist(q_, ref).min(dim=1).values.numpy()

    ho = rng.choice(sd.held_rows, size=min(20000, len(sd.held_rows)), replace=False)
    sig_ho = np.concatenate([ref_support(sd.obs(ho[i:i + 200])) for i in range(0, len(ho), 200)])
    p99_sig = float(np.quantile(sig_ho, 0.99))
    res["p99_support"] = p99_sig
    # initialisation shared by T and S
    torch.manual_seed(seed_int("init", sd.seed) % (2 ** 31))
    init = make_nets(torch, sd.mean, sd.std)
    init_state = {k: v.clone() for k, v in init.state_dict().items()}
    torch.save(init_state, out / f"s{sd.seed}_init.pt")
    arms: Dict[str, Any] = {"init": init}
    res["train"] = {}
    for arm in ("T", "S"):
        log: List[Dict[str, Any]] = []
        cap = REG["caps"]["train_wall_s"]
        if time.perf_counter() - t_start > REG["caps"]["harness_wall_s"]:
            raise RuntimeError("harness wall cap reached")
        nets, info = train_arm(torch, arm, sd, init_state, steps, cap, log)
        torch.save(nets.state_dict(), out / f"s{sd.seed}_{arm}.pt")
        (out / f"s{sd.seed}_{arm}_trainlog.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
        info["log_last"] = log[-1] if log else None
        res["train"][arm] = info
        arms[arm] = nets
        print(f"[s{sd.seed}] {arm}: {info['steps_done']} steps, {info['wall_s']:.0f} s, "
              f"{info['s_per_step'] * 1000:.1f} ms/step, lambda {info['final_lambda']:.3g}", flush=True)
    # functional checks, sighted, calibration of model error per arm
    rng_f = np.random.default_rng(seed_int("functional", sd.seed))
    hsel = rng_f.choice(len(sd.ho_src), size=min(GR["F3"]["rows"], len(sd.ho_src)), replace=False)
    # held-out first-hit pairs with h <= 64
    pairs = []
    for e in sorted(sd.held):
        cl = sd.cells[e]
        T = sd.eps[e]["T"]
        nextv: Dict[int, int] = {}
        for k in range(T, -1, -1):
            if k + 1 <= T:
                c1 = cl[k + 1]
                if c1 is not None:
                    nextv[cell_to_code(c1)] = k + 1
            if cl[k] is None:
                continue
            for c, kk in nextv.items():
                if kk - k <= GR["F2"]["h_max"]:
                    pairs.append((sd.off[e] + k, c, kk - k))
    pairs_a = np.array(pairs, np.int64) if pairs else np.zeros((0, 3), np.int64)
    if len(pairs_a) > GR["F2"]["pairs"]:
        pairs_a = pairs_a[rng_f.choice(len(pairs_a), size=GR["F2"]["pairs"], replace=False)]
    d0_states = rng_f.choice(sd.held_rows, size=min(GR["D0"]["states"], len(sd.held_rows)), replace=False)
    sg_states = rng_f.choice(sd.held_rows, size=min(GR["sighted"]["states"], len(sd.held_rows)), replace=False)
    g1 = sd.goal_nodes[rng_f.integers(len(sd.goal_nodes), size=len(sg_states))]
    g2 = sd.goal_nodes[rng_f.integers(len(sd.goal_nodes), size=len(sg_states))]
    same = g2 == g1
    g2[same] = sd.goal_nodes[(np.searchsorted(sd.goal_nodes, g1[same]) + 1) % len(sd.goal_nodes)]
    res["functional"] = {}
    p99_err: Dict[str, float] = {}
    with torch.no_grad():
        for arm in ("T", "S", "init"):
            nets = arms[arm]
            zs = nets.z(torch.from_numpy(sd.obs(sd.ho_src[hsel])))
            zd = nets.z(torch.from_numpy(sd.obs(sd.ho_dst[hsel])))
            loc = nets.d(zs, zd).numpy()
            pr = nets.T(zs, torch.from_numpy(sd.ho_word[hsel]))
            e2 = torch.maximum(nets.d(pr, zd), nets.d(zd, pr)).numpy()
            p99_err[arm] = float(np.quantile(e2, 0.99))
            mem = nets.d(zd, nets.w(torch.from_numpy(goal_feats(sd.codes[sd.ho_dst[hsel]])))).numpy()
            if len(pairs_a):
                zp = nets.z(torch.from_numpy(sd.obs(pairs_a[:, 0])))
                dp = nets.d(zp, nets.w(torch.from_numpy(goal_feats(pairs_a[:, 1])))).numpy()
                rho = spearman(dp, pairs_a[:, 2])
            else:
                rho = float("nan")
            zg = nets.w(torch.from_numpy(goal_feats(sd.goal_nodes)))
            zx0 = nets.z(torch.from_numpy(sd.obs(d0_states)))
            dd0 = np.concatenate([nets.d(zg[i:i + 4, None, :], zx0[None, :, :]).numpy().ravel()
                                  for i in range(0, len(zg), 4)])
            zsg = nets.z(torch.from_numpy(sd.obs(sg_states)))
            ch = []
            for gset in (g1, g2):
                cc = []
                for i in range(0, len(zsg), 500):
                    zb = zsg[i:i + 500]
                    pred = nets.T(zb.repeat_interleave(72, 0), torch.arange(72).repeat(len(zb)))
                    wg = nets.w(torch.from_numpy(goal_feats(gset[i:i + 500]))).repeat_interleave(72, 0)
                    cc.append(torch.argmin(nets.d(pred, wg).view(len(zb), 72), dim=1).numpy())
                ch.append(np.concatenate(cc))
            sighted = float((ch[0] != ch[1]).mean())
            f1 = float((loc <= GR["F1"]["max_local"]).mean())
            f3 = float(np.median(e2))
            d0 = float((dd0 >= GR["D0"]["min_distance"]).mean())
            fu = {"F1_frac": f1, "F2_spearman": rho, "F3_median_err": f3, "D0_frac": d0, "sighted_frac": sighted,
                  "membership_frac_le_0.5": float((mem <= 0.5).mean()), "local_mean": float(loc.mean()),
                  "p99_err": p99_err[arm]}
            fu["F1"] = f1 >= GR["F1"]["min_frac"]
            fu["F2"] = bool(rho >= GR["F2"]["min_spearman"]) if rho == rho else False
            fu["F3"] = f3 <= GR["F3"]["max_median"]
            fu["D0"] = d0 >= GR["D0"]["min_frac"]
            fu["sighted"] = sighted >= GR["sighted"]["min_frac"]
            fu["functional"] = (fu["F1"] if arm in ("T", "init") else True) and fu["F2"] and fu["F3"] and fu["D0"]
            res["functional"][arm] = fu
    res["functional"]["F2_pairs"] = int(len(pairs_a))
    # S1: distance to every training goal node from the start vs world BFS truth
    truth, n_reach = bfs(start_state(1))
    res["world_reachable_states"] = n_reach
    dg_data = data_graph_depths(sd, sd.train)
    goals_s1 = [int(c) for c in sd.goal_nodes if int(c) in truth and truth[int(c)] > 0]
    res["S1"] = {"goals": len(goals_s1)}
    with torch.no_grad():
        for arm in ("T", "S", "init"):
            nets = arms[arm]
            z0 = nets.z(torch.from_numpy(build_obs(initial_record(start_state(1)))))
            dd = nets.d(z0, nets.w(torch.from_numpy(goal_feats(np.array(goals_s1))))).numpy()
            tv = np.array([truth[c] for c in goals_s1], float)
            dv = np.array([dg_data.get(c, np.nan) for c in goals_s1], float)
            res["S1"][arm] = {"spearman_truth": spearman(dd, tv), "under_frac": float((dd < REG["tests"]["S1"][
                "under_ratio"] * tv).mean()), "mae_truth": float(np.abs(dd - tv).mean()),
                "median_ratio_truth": float(np.median(dd / tv)),
                "spearman_datagraph": spearman(dd[~np.isnan(dv)], dv[~np.isnan(dv)]),
                "median_ratio_datagraph": float(np.nanmedian(dd / dv))}
    res["S1"]["truth_vs_datagraph_median_ratio"] = float(np.nanmedian(
        np.array([dg_data.get(c, np.nan) for c in goals_s1], float) / np.array([truth[c] for c in goals_s1], float)))
    # S2: stitch-only goals
    own_best: Dict[int, int] = {}
    for e in sd.train:
        dep = data_graph_depths(sd, [e])
        for c, v in dep.items():
            if c not in own_best or v < own_best[c]:
                own_best[c] = v
    stitch = []
    for c in sd.goal_nodes:
        c = int(c)
        if c not in dg_data or dg_data[c] == 0:
            continue
        budget = int(math.floor(1.25 * dg_data[c])) + 20
        if own_best.get(c, 10 ** 9) > budget:
            stitch.append((c, budget))
    stitch.sort(key=lambda cb: hashlib.sha256(f"m7t_synth|S2|{sd.seed}|{code_to_cell(cb[0])}".encode()).hexdigest())
    res["S2_candidates"] = len(stitch)
    stitch = stitch[:TS["S2"]["max_goals_per_seed"]]
    res["S2_goals"] = [{"cell": list(code_to_cell(c)), "budget": b, "L_star": dg_data[c],
                        "own_best": own_best.get(c), "truth": truth.get(c)} for c, b in stitch]
    # evaluations
    ev: Dict[str, List[Dict[str, Any]]] = {}
    for arm in ("T", "S", "init"):
        ev[f"{arm}_rare"] = run_episodes(torch, arms[arm], sd, E, [HORIZON] * len(E), ref_support)
    for arm in ("T", "S"):
        ev[f"{arm}_S2"] = run_episodes(torch, arms[arm], sd, [c for c, _ in stitch], [b for _, b in stitch],
                                       ref_support)
    # OFF plant start
    off_start = None
    for cx, cy in ((16, 8), (15, 30), (35, 45)):
        ob = build_obs(initial_record(start_state(1, cx, cy)))
        if ref_support(ob)[0] > p99_sig:
            off_start = (cx, cy)
            break
    res["off_start"] = off_start
    if off_start is not None:
        ev["T_OFF"] = run_episodes(torch, arms["T"], sd, E, [HORIZON] * len(E), ref_support, starts=off_start,
                                   plant="OFF")
    ev["T_MODEL"] = run_episodes(torch, arms["T"], sd, E, [HORIZON] * len(E), ref_support, plant="MODEL")
    ev["T_LOOP"] = run_episodes(torch, arms["T"], sd, E, [HORIZON] * len(E), ref_support, plant="LOOP")
    # flags and attribution
    for key, lst in ev.items():
        arm = key.split("_")[0]
        for epi in lst:
            fl = flags(epi, p99_sig, p99_err[arm])
            epi["flags"] = fl
            epi["attribution"], epi["limited"] = attribute(fl)
    # replays of successful returns
    rep = {"T": [], "S": []}
    for arm, cap_n in (("T", ER["replays"]["T"]), ("S", ER["replays"]["S"])):
        for epi in ev[f"{arm}_rare"]:
            if epi["success"] and len(rep[arm]) < cap_n:
                rt = replay_reach(epi["words"], epi["goal"])
                rep[arm].append({"goal": epi["goal"], "reach": epi["reach"], "replayed": rt,
                                 "exact": rt == epi["reach"]})
    res["replays"] = rep
    # gate rule per arm set
    res["rule"] = {"trained": seed_rule(res, ev["T_rare"], ev["S_rare"], res["functional"]["T"],
                                        res["functional"]["S"], rep),
                   "untrained": seed_rule(res, ev["init_rare"], ev["init_rare"], res["functional"]["init"],
                                          res["functional"]["init"], {"T": [], "S": []})}
    # S2 rates
    res["S2"] = {arm: {"n": len(ev[f"{arm}_S2"]), "success": int(sum(e["success"] for e in ev[f"{arm}_S2"]))}
                 for arm in ("T", "S")}
    # S3 planted pairs
    res["S3"] = s3_pairs(torch, arms["T"], sd)
    # S4 plants
    s4: Dict[str, Any] = {}
    for plant in ("OFF", "MODEL", "LOOP"):
        key = f"T_{plant}"
        lst = ev.get(key, [])
        failed = [e for e in lst if not e["success"]]
        s4[plant] = {"episodes": len(lst), "failed": len(failed),
                     "correct": int(sum(e["attribution"] == plant for e in failed)),
                     "attributions": {a: int(sum(e["attribution"] == a for e in failed))
                                      for a in ("OFF", "MODEL", "LOOP", "FALSE_ARRIVAL", "none")}}
    healthy = [e for e in ev["T_rare"] + ev["T_S2"] if e["success"]]
    fa = [e for e in healthy if any(e["flags"][k] is not None and e["flags"][k] < e["reach"]
                                    for k in ("OFF", "MODEL"))]
    s4["healthy_successes"] = len(healthy)
    s4["false_alarms"] = len(fa)
    res["S4"] = s4
    # compact episode records (no per-tick arrays) + full arrays to a side file
    res["episodes"] = {k: [{kk: vv for kk, vv in e.items() if kk not in ("sigma", "dg", "err", "pred_next",
                                                                         "words")} for e in lst]
                       for k, lst in ev.items()}
    import gzip
    with gzip.open(out / f"s{sd.seed}_episodes.json.gz", "wt", encoding="utf-8") as fp:
        json.dump(ev, fp)
    res["memory_after"] = memory_mb()
    return res


def seed_rule(res: Dict[str, Any], t_eps, s_eps, fT: Dict[str, Any], fS: Dict[str, Any], rep) -> Dict[str, Any]:
    GR = REG["gate_rule"]
    n_T = int(sum(e["success"] for e in t_eps))
    n_S = int(sum(e["success"] for e in s_eps))
    b = int(sum(te["success"] and not se["success"] for te, se in zip(t_eps, s_eps)))
    c = int(sum(se["success"] and not te["success"] for te, se in zip(t_eps, s_eps)))
    failed = [e for e in t_eps if not e["success"]]
    dist_lim = sum(e.get("limited") == "distance" for e in failed)
    exec_healthy = (dist_lim / len(failed) >= GR["exec_healthy_min"]) if failed else True
    replays_ok = all(r["exact"] for r in rep["T"]) and all(r["exact"] for r in rep["S"])
    ret = fT["functional"] and fT["sighted"] and n_T >= max(GR["return_min"], res["K"] + 1) and replays_ok
    pas = ret and fS["functional"] and (b - c) >= GR["twin_margin"]
    null = fT["functional"] and exec_healthy and n_T <= math.ceil(res["mu"]) + GR["null_slack"]
    if pas:
        cls = "pass"
    elif null:
        cls = "null"
    elif ret:
        cls = "return"
    elif not fT["functional"]:
        cls = "not_functional"
    else:
        cls = "inconclusive"
    return {"n_T": n_T, "n_S": n_S, "b": b, "c": c, "K": res["K"], "mu": res["mu"],
            "return_threshold": max(GR["return_min"], res["K"] + 1), "null_bound": math.ceil(res["mu"]) + GR[
                "null_slack"], "exec_healthy": exec_healthy, "failed": len(failed), "distance_limited": dist_lim,
            "replays_ok": replays_ok, "Return": ret, "Pass": pas, "Null": null, "class": cls}


def s3_pairs(torch, nets, sd: SeedData) -> Dict[str, Any]:
    TS = REG["tests"]["S3"]
    r = sd.recs
    rows = sd.train_rows
    air = rows[(r["g"][rows] == 0) & (r["lock"][rows] == 0)]
    codes = sd.codes[air]
    by: Dict[int, Dict[int, int]] = {}
    for row, c in zip(air, codes):
        jj = int(r["j"][row])
        if jj in (0, 1):
            by.setdefault(int(c), {}).setdefault(jj, int(row))
    cells = [c for c, v in by.items() if 0 in v and 1 in v]
    cells.sort(key=lambda c: hashlib.sha256(f"m7t_synth|S3|{sd.seed}|{code_to_cell(c)}".encode()).hexdigest())
    goal_set = set(int(c) for c in sd.goal_nodes)
    out = []
    for c in cells:
        if len(out) >= TS["pairs_per_seed"]:
            break
        ra, rb_ = by[c][1], by[c][0]
        sa = sd.dyn_state(np.array([ra]))
        sb = sd.dyn_state(np.array([rb_]))
        da, _ = bfs(sa, max_depth=30)
        cand = sorted((g for g, v in da.items() if 0 < v <= 30 and g in goal_set and g != c),
                      key=lambda g: hashlib.sha256(f"m7t_synth|S3g|{sd.seed}|{code_to_cell(g)}".encode()).hexdigest())
        if not cand:
            continue
        db, _ = bfs(sb, max_depth=HORIZON, want=set(cand))
        pick = None
        for g in cand:
            dbv = db.get(g, HORIZON)
            if dbv >= 2 * da[g]:
                pick = (g, da[g], dbv)
                break
        if pick is None:
            continue
        g, dav, dbv = pick
        with torch.no_grad():
            zb = nets.z(torch.from_numpy(sd.obs(np.array([rb_]))))
            za = nets.z(torch.from_numpy(sd.obs(np.array([ra]))))
            wg = nets.w(torch.from_numpy(goal_feats(np.array([g]))))
            d_b = float(nets.d(zb, wg)[0])
            d_a = float(nets.d(za, wg)[0])
        out.append({"cell": list(code_to_cell(c)), "goal": list(code_to_cell(g)), "truth_a": int(dav),
                    "truth_b": int(dbv), "d_a": d_a, "d_b": d_b, "ok": d_b >= TS["ratio_min"] * min(dbv, HORIZON)})
    return {"pairs": out, "n": len(out), "ok": int(sum(p["ok"] for p in out))}


# -- commands --------------------------------------------------------------------------------------------------------------


def out_dir(p: Path) -> Path:
    p = p.resolve()
    if str(p).lower().startswith(str((REPO / "runs").resolve()).lower()):
        raise SystemExit("--out must be outside runs/ (the D: coverage of runs/ stays exact)")
    p.mkdir(parents=True, exist_ok=True)
    return p


def cmd_selftest() -> int:
    torch = torch_mod()
    rng = np.random.default_rng(0)
    nets = make_nets(torch, np.zeros(OBS_DIM, np.float32), np.ones(OBS_DIM, np.float32))
    for _ in range(20):
        a = rng.normal(size=256).astype(np.float32) * 3
        b = rng.normal(size=256).astype(np.float32) * 3
        comp_b = iqe_brute(a, b, 16, 16)
        with torch.no_grad():
            alpha = float(torch.sigmoid(nets.raw_alpha))
            want = (1 - alpha) * comp_b.mean() + alpha * comp_b.max()
            got = float(nets.d(torch.from_numpy(a), torch.from_numpy(b)))
        assert abs(got - want) < 1e-3 * max(1.0, abs(want)), (got, want)
    with torch.no_grad():
        x = torch.randn(200, 256) * 3
        d_xy = nets.d(x[:, None], x[None, :])
        tri = d_xy[:, :, None] + d_xy[None, :, :]            # [i, k, j] = d(i, k) + d(k, j)
        viol = (d_xy[:, None, :] - tri).max()                # d(i, j) - (d(i, k) + d(k, j))
    assert float(viol) < 1e-3, float(viol)
    ob = build_obs(initial_record(start_state(3)))
    assert ob.shape == (3, OBS_DIM) and np.isfinite(ob).all()
    # simulation vs BFS: every recorded state of short random episodes is BFS-reachable no later than its tick
    raw = collect(1234, 3, 300)
    depth_state: Dict[int, int] = {}
    truth, _ = bfs(start_state(1), max_depth=300)
    for ep in raw["episodes"]:
        codes = cell_codes({k: ep["rec"][k] for k in DYN})
        for k in range(ep["T"] + 1):
            if ep["rec"]["dead"][k]:
                continue
            c = int(codes[k])
            assert c in truth and truth[c] <= k, (c, k, truth.get(c))
    print("selftest PASS: IQE equals the brute-force union + maxmean, triangle inequality holds, obs 626, "
          "simulator cells reachable by BFS no later than recorded")
    return 0


def cmd_world_check(out: Path) -> int:
    out = out_dir(out)
    t0 = time.perf_counter()
    full, n_full = bfs(start_state(1))
    nodj, n_nodj = bfs(start_state(1), world_mod="no_double_jump")
    wall_top = [c for c in full if code_to_cell(c)[2] == 0]
    left = [c for c in full if code_to_cell(c)[0] * CELL_X < WALL_X0]
    left_nodj = [c for c in nodj if code_to_cell(c)[0] * CELL_X < WALL_X0]
    wt_nodj = [c for c in nodj if code_to_cell(c)[2] == 0]
    rep = {"tool": TOOL, "reg_digest": REG_DIGEST, "utc": utc(),
           "reachable_states": n_full, "reachable_cells": len(full),
           "wall_top_reachable": bool(wall_top), "wall_top_min_ticks": min((full[c] for c in wall_top), default=None),
           "left_region_reachable": bool(left), "left_min_ticks": min((full[c] for c in left), default=None),
           "without_double_jump": {"reachable_states": n_nodj, "wall_top_reachable": bool(wt_nodj),
                                   "left_reachable": bool(left_nodj)},
           "bfs_wall_s": round(time.perf_counter() - t0, 1)}
    # behaviour-only sufficiency on the smoke seed 99 (never a registered seed)
    sd = collect(99, 40, HORIZON)
    cnt: Dict[int, int] = {}
    for ep in sd["episodes"][:20]:
        for c in {cell_to_code(c) for c in episode_cells(ep)[1:] if c is not None}:
            cnt[c] = cnt.get(c, 0) + 1
    allc = set()
    for ep in sd["episodes"]:
        allc |= {cell_to_code(c) for c in episode_cells(ep)[1:] if c is not None}
    rep["seed99_behaviour"] = {"cells_in_40_episodes": len(allc), "rare_1_2_of_first_20": int(sum(
        1 <= v <= 2 for v in cnt.values())), "wall_top_visited": any(code_to_cell(c)[2] == 0 for c in allc),
        "left_visited": any(code_to_cell(c)[0] * CELL_X < WALL_X0 for c in allc),
        "deaths": int(sum(ep["rec"]["dead"][-1] for ep in sd["episodes"]))}
    rep["spec_checks"] = {"wall_top_needs_double_jump": rep["wall_top_reachable"] and not wt_nodj,
                          "left_needs_double_jump": rep["left_region_reachable"] and not left_nodj}
    (out / "world_check.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0 if all(rep["spec_checks"].values()) else 1


def cmd_register(out: Path) -> int:
    out = out_dir(out)
    path = out / "registration.json"
    if path.exists():
        raise SystemExit(f"{path} exists; registration is write-once")
    rec = {"tool": TOOL, "utc": utc(), "reg_digest": REG_DIGEST, "code_sha256_at_registration": file_sha(),
           "reg": REG}
    path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(f"registered {REG_DIGEST} at {rec['utc']} -> {path}")
    return 0


def cmd_run(out: Path, smoke: bool) -> int:
    out = out_dir(out)
    if not smoke:
        reg = json.loads((out / "registration.json").read_text(encoding="utf-8"))
        if reg["reg_digest"] != REG_DIGEST or hashlib.sha256(canon(reg["reg"])).hexdigest() != REG_DIGEST:
            raise SystemExit("registration digest differs from this file's REG: refusing")
    torch = torch_mod()
    t0 = time.perf_counter()
    D = REG["data"]
    seeds = [99] if smoke else D["seeds"]
    n_ep, phase_a, held = (16, 8, 3) if smoke else (D["episodes"], D["phase_a"], D["held_out"])
    horizon = 600 if smoke else D["horizon"]
    steps = 60 if smoke else REG["training"]["steps"]
    results: Dict[str, Any] = {"tool": TOOL, "reg_digest": REG_DIGEST, "code_sha256_at_run": file_sha(),
                               "smoke": smoke, "started_utc": utc(), "torch": torch.__version__,
                               "threads": torch.get_num_threads(), "python": sys.version.split()[0],
                               "platform": platform.platform(), "seeds": {}}
    if not smoke:
        results["code_sha256_at_registration"] = json.loads(
            (out / "registration.json").read_text(encoding="utf-8"))["code_sha256_at_registration"]
    saved_horizon = globals()["HORIZON"]
    try:
        if smoke:
            globals()["HORIZON"] = horizon          # smoke only; restored below
        for s in seeds:
            ts = time.perf_counter()
            sd = SeedData(s, n_ep, horizon, phase_a, held)
            print(f"[s{s}] data {time.perf_counter() - ts:.0f} s, {len(sd.tr_src)} train transitions, "
                  f"{len(sd.goal_nodes)} goal nodes", flush=True)
            res = seed_pipeline(torch, sd, out, steps, smoke, t0)
            res["seed_wall_s"] = time.perf_counter() - ts
            results["seeds"][str(s)] = res
            (out / ("smoke_results.json" if smoke else "results_partial.json")).write_text(
                json.dumps(results, indent=1, default=float), encoding="utf-8")
    finally:
        globals()["HORIZON"] = saved_horizon
    results["wall_s"] = time.perf_counter() - t0
    results["finished_utc"] = utc()
    results["tests"] = evaluate_tests(results)
    results["memory_end"] = memory_mb()
    name = "smoke_results.json" if smoke else "results.json"
    (out / name).write_text(json.dumps(results, indent=1, default=float), encoding="utf-8")
    print(json.dumps(results["tests"], indent=1, default=float))
    return 0


def evaluate_tests(results: Dict[str, Any]) -> Dict[str, Any]:
    TS = REG["tests"]
    S = list(results["seeds"].values())
    t: Dict[str, Any] = {}
    s1 = [{"seed": r["seed"], "spearman": r["S1"]["T"]["spearman_truth"], "under_frac": r["S1"]["T"]["under_frac"]}
          for r in S]
    t["S1"] = {"per_seed": s1, "pass": all((x["spearman"] >= TS["S1"]["min_spearman"]) and
                                           (x["under_frac"] <= TS["S1"]["max_under_frac"]) for x in s1)}
    nT = sum(r["S2"]["T"]["success"] for r in S)
    nS = sum(r["S2"]["S"]["success"] for r in S)
    n = sum(r["S2"]["T"]["n"] for r in S)
    classes = [r["rule"]["trained"]["class"] for r in S]
    outcome = gate_outcome([r["rule"]["trained"] for r in S])
    t["S2"] = {"goals_pooled": n, "T_rate": nT / n if n else None, "S_rate": nS / n if n else None,
               "gate_rule_outcome": outcome, "seed_classes": classes,
               "pass": bool(n >= TS["S2"]["min_goals_pooled"] and nT / n >= TS["S2"]["T_min"] and
                            nS / n <= TS["S2"]["S_max"] and outcome == TS["S2"]["gate_rule_outcome"]) if n else False}
    npairs = sum(r["S3"]["n"] for r in S)
    ok = sum(r["S3"]["ok"] for r in S)
    d0 = all(r["functional"]["T"]["D0"] for r in S)
    t["S3"] = {"pairs_pooled": npairs, "ok": ok, "frac": ok / npairs if npairs else None, "D0_all_seeds": d0,
               "pass": bool(npairs >= TS["S3"]["min_pairs_pooled"] and ok / npairs >= TS["S3"]["frac_min"] and d0)
               if npairs else False}
    s4 = {}
    all_ok = True
    for plant in ("OFF", "MODEL", "LOOP"):
        fl = sum(r["S4"][plant]["failed"] for r in S)
        co = sum(r["S4"][plant]["correct"] for r in S)
        okp = fl >= TS["S4"]["min_failed_pooled"] and co / fl >= TS["S4"]["correct_min"] if fl else False
        s4[plant] = {"failed": fl, "correct": co, "frac": co / fl if fl else None, "pass": bool(okp)}
        all_ok &= bool(okp)
    hs = sum(r["S4"]["healthy_successes"] for r in S)
    fa = sum(r["S4"]["false_alarms"] for r in S)
    fa_ok = hs >= TS["S4"]["min_healthy_successes"] and fa / hs <= TS["S4"]["false_alarm_max"] if hs else False
    s4["healthy"] = {"successes": hs, "false_alarms": fa, "frac": fa / hs if hs else None, "pass": bool(fa_ok)}
    s4["pass"] = bool(all_ok and fa_ok)
    t["S4"] = s4
    un = [r["rule"]["untrained"]["class"] for r in S]
    t["S5"] = {"seed_classes": un, "pass": all(c in ("null", "not_functional") for c in un)}
    tr = [(r["seed"], a, r["train"][a]["completed"], r["train"][a]["wall_s"]) for r in S for a in ("T", "S")]
    t["S6"] = {"runs": [{"seed": s, "arm": a, "completed": c, "wall_s": w} for s, a, c, w in tr],
               "pass": all(c and w <= TS["S6"]["max_train_wall_s"] for _, _, c, w in tr)}
    t["overall_pass"] = all(t[k]["pass"] for k in ("S1", "S2", "S3", "S4", "S5", "S6"))
    return t


def gate_outcome(rules: Sequence[Dict[str, Any]]) -> int:
    if sum(r["Pass"] for r in rules) >= 2:
        return 1
    if sum(r["Null"] for r in rules) >= 2:
        return 2
    if sum(r["Return"] for r in rules) >= 2:
        return 3
    return 4


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    for name in ("world-check", "register", "run"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, required=True)
        if name == "run":
            p.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return cmd_selftest()
    if a.cmd == "world-check":
        return cmd_world_check(a.out)
    if a.cmd == "register":
        return cmd_register(a.out)
    return cmd_run(a.out, a.smoke)


if __name__ == "__main__":
    sys.exit(main())
