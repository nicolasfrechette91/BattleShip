"""M7u: the learned dynamics ensemble (design: docs/rl_model_planning_m7u_proposal_2026-09-29.md, revision 2, section 4).

Opt-in; PyTorch, CPU. Main process only (spawn workers never import this module).

LEARNED (heads, teacher-forced one-step losses): the next native row's gameplay fields - status id (H1); ground/air,
facing, jumps used, fast fall (H2, masked to combinations recorded with the chosen status); floor line + contact bits
(H3, masked to combinations recorded with the chosen ground/air); hitlag, attack active, shield, motion flag 1 (H4);
the game's latched controller state: tap levels, Z level, button_tap / button_release masks (H5); continuous motion,
floor distance, carry, collision diamond, animation frame / speed (H6); target breaks and the fatal fall (H7).

DETERMINISTIC (never learned, never a gameplay rule): the Track 1 word window (exact submitted words), the bookkeeping
history (rl/m7u_state.advance_history, re-implemented batched here and tested equal), the clock (+1 per tick), the
verified clock track (platform translate / speed, moving target), the observation encodings (v3 / v4 scalings, class
table v2, Mario-relative geometry of the 8 nearest segments from position + the reset line table + the track, target
relative positions) and the vocabularies / masks built from the training split. There is no gravity, drift, collision
test, landing snap, input fold, stick-band logic or status-transition rule anywhere in this module.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import torch
from torch import nn
from torch.nn import functional as Fn

import m7q_status_table as st2
import m7u_state as us

MODEL_CONTRACT = "m7u_dynamics_ensemble_v1"
DENSE = 338                     # dense features (section 4.3 layout below); + 2 x 16 status embeddings = 370 trunk inputs
EMB_STATUS, EMB_H2, EMB_H3 = 16, 8, 8
HIDDEN = 256
H6_HIDDEN = 64
S_CAP, V3_CAP, V4_CAP = 160, 128, 64
N_H2 = 24                       # ga (2) x facing (2) x jumps used (3) x fast fall (2)
HITLAG_CLASS_CAP = 15
H6_FIELDS = ("dx", "dy", "vax", "vay", "vgx", "floor_dist", "carry_x", "carry_y", "coll_top", "coll_width",
             "anim_frame", "anim_speed")
H6_SCALE = (50.0, 50.0, 50.0, 50.0, 50.0, 2000.0, 50.0, 50.0, 2000.0, 2000.0, 60.0, 2.0)
H6_WEIGHT = (4.0, 4.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
LOSS_WEIGHTS = {"h1": 2.0, "h2": 1.0, "h3": 2.0, "h4": 1.0, "tapx": 1.0, "tapy": 1.0, "z": 1.0, "masks": 1.0,
                "h6": 1.0, "breaks": 1.0, "fall": 1.0}
TAP_RAW_OF_LEVEL = (1, 2, 3, 4, 254)
STATUS_LOOKUP = 1024            # raw status ids covered by the lookup tensors


class ModelError(RuntimeError):
    pass


# -- vocabularies (data-derived, frozen before training) ---------------------------------------------------------------


def h2_index(ga: int, facing: int, jumps_used: int, fastfall: int) -> int:
    return int(ga) * 12 + (1 if facing > 0 else 0) * 6 + min(max(int(jumps_used), 0), 2) * 2 + (1 if fastfall else 0)


def h2_decode(i: int) -> Tuple[int, int, int, int]:
    return i // 12, (1 if (i // 6) % 2 else -1), (i // 2) % 3, i % 2


def contact_bits(row: np.ndarray) -> int:
    F = us.F
    return (int(row[F["c_floor"]]) | int(row[F["c_ceil"]]) << 1 | int(row[F["c_lwall"]]) << 2
            | int(row[F["c_rwall"]]) << 3 | int(row[F["c_edge"]]) << 4)


def h4_key(row: np.ndarray) -> Tuple[int, int, int, int]:
    F = us.F
    return (min(int(row[F["hitlag"]]), HITLAG_CLASS_CAP), int(row[F["attack"]]), int(row[F["shield"]]), int(row[F["mflag1"]]))


@dataclass
class Vocab:
    status_ids: List[int]                        # vocab index k + 1 <-> status id; index 0 = unseen
    h2_mask: np.ndarray                          # (S, 24) bool: combinations recorded with each next status
    h3_combos: List[Tuple[int, int]]             # (floor line, contact bits)
    h3_mask: np.ndarray                          # (2, V3) bool: combinations recorded with each ground/air
    h4_combos: List[Tuple[int, int, int, int]]   # (hitlag, attack, shield, mflag1)

    @property
    def S(self) -> int:
        return len(self.status_ids) + 1

    @property
    def V3(self) -> int:
        return len(self.h3_combos)

    @property
    def V4(self) -> int:
        return len(self.h4_combos)

    def to_json(self) -> Dict[str, Any]:
        return {"status_ids": self.status_ids, "h2_mask": self.h2_mask.astype(int).tolist(),
                "h3_combos": [list(c) for c in self.h3_combos], "h3_mask": self.h3_mask.astype(int).tolist(),
                "h4_combos": [list(c) for c in self.h4_combos]}

    @staticmethod
    def from_json(d: Mapping[str, Any]) -> "Vocab":
        return Vocab(status_ids=[int(s) for s in d["status_ids"]], h2_mask=np.array(d["h2_mask"], dtype=bool),
                     h3_combos=[tuple(int(v) for v in c) for c in d["h3_combos"]],  # type: ignore[misc]
                     h3_mask=np.array(d["h3_mask"], dtype=bool),
                     h4_combos=[tuple(int(v) for v in c) for c in d["h4_combos"]])  # type: ignore[misc]

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True).encode("utf-8")).hexdigest()


def build_vocab(next_rows: np.ndarray) -> Vocab:
    """From the target rows of the training transitions (valid rows only). Raises when a cap is exceeded (the run is
    then invalid: nothing is merged or dropped silently)."""
    F = us.F
    rows = next_rows[next_rows[:, F["valid"]] == 1.0]
    status_ids = sorted({int(s) for s in rows[:, F["status"]]})
    if len(status_ids) + 1 > S_CAP:
        raise ModelError(f"{len(status_ids)} statuses exceed the cap {S_CAP - 1}")
    sidx = {s: k + 1 for k, s in enumerate(status_ids)}
    h2_mask = np.zeros((len(status_ids) + 1, N_H2), dtype=bool)
    h2_mask[0] = True
    h3 = sorted({(int(r[F["floor_line"]]), contact_bits(r)) for r in rows})
    if len(h3) > V3_CAP:
        raise ModelError(f"{len(h3)} floor / contact combinations exceed the cap {V3_CAP}")
    h3i = {c: k for k, c in enumerate(h3)}
    h3_mask = np.zeros((2, len(h3)), dtype=bool)
    h4 = sorted({h4_key(r) for r in rows})
    if len(h4) > V4_CAP:
        raise ModelError(f"{len(h4)} hitlag / flag combinations exceed the cap {V4_CAP}")
    for r in rows:
        h2_mask[sidx[int(r[F["status"]])], h2_index(r[F["ga"]], r[F["facing"]], r[F["jumps_used"]], r[F["fastfall"]])] = True
        h3_mask[int(r[F["ga"]]) & 1, h3i[(int(r[F["floor_line"]]), contact_bits(r))]] = True
    return Vocab(status_ids=status_ids, h2_mask=h2_mask, h3_combos=h3, h3_mask=h3_mask, h4_combos=h4)


# -- deterministic tensors: status lookups, class table, world, track -------------------------------------------------


@dataclass
class Context:
    """Every deterministic tensor the featurisation and the rollout need (built once)."""
    vocab: Vocab
    status_to_idx: torch.Tensor      # (STATUS_LOOKUP,) long: raw id -> vocab index (0 = unseen)
    idx_to_status: torch.Tensor      # (S,) float64: vocab index -> raw id (index 0 -> -1)
    status_class: torch.Tensor       # (STATUS_LOOKUP,) long: raw id -> class v2 index
    aerial: torch.Tensor             # (STATUS_LOOKUP,) bool
    h2_mask: torch.Tensor            # (S, 24) bool
    h3_mask: torch.Tensor            # (2, V3) bool
    h3_floor: torch.Tensor           # (V3,) float64
    h3_bits: torch.Tensor            # (V3, 5) float64
    h4_vals: torch.Tensor            # (V4, 4) float64
    seg: torch.Tensor                # (n, 4) float64
    seg_kind: torch.Tensor           # (n, 7) float32
    seg_moving: torch.Tensor         # (n,) bool
    static_targets: torch.Tensor     # (10, 2) float64 (NaN for the moving target)
    track: torch.Tensor              # (T, 6) float64
    track_covered: torch.Tensor      # (T,) bool


def make_context(vocab: Vocab, world: us.StaticWorld, track: us.ClockTrack, character: str = "mario") -> Context:
    table = st2.load_table()
    clf = st2.ActionClassifier(table, character)
    cls = torch.tensor([clf.index(i) for i in range(STATUS_LOOKUP)], dtype=torch.long)
    clf.unmapped_seen.clear()
    aer = torch.zeros(STATUS_LOOKUP, dtype=torch.bool)
    for i in st2.aerial_attack_ids(table):
        aer[int(i)] = True
    s2i = torch.zeros(STATUS_LOOKUP, dtype=torch.long)
    for k, s in enumerate(vocab.status_ids):
        if not 0 <= s < STATUS_LOOKUP:
            raise ModelError(f"status id {s} outside the lookup range")
        s2i[s] = k + 1
    return Context(
        vocab=vocab, status_to_idx=s2i,
        idx_to_status=torch.tensor([-1.0] + [float(s) for s in vocab.status_ids], dtype=torch.float64),
        status_class=cls, aerial=aer, h2_mask=torch.tensor(vocab.h2_mask), h3_mask=torch.tensor(vocab.h3_mask),
        h3_floor=torch.tensor([float(c[0]) for c in vocab.h3_combos], dtype=torch.float64),
        h3_bits=torch.tensor([[float((c[1] >> k) & 1) for k in range(5)] for c in vocab.h3_combos], dtype=torch.float64),
        h4_vals=torch.tensor([[float(v) for v in c] for c in vocab.h4_combos], dtype=torch.float64),
        seg=torch.tensor(world.seg, dtype=torch.float64), seg_kind=torch.tensor(world.kind, dtype=torch.float32),
        seg_moving=torch.tensor(world.group == us.PLATFORM_GROUP),
        static_targets=torch.tensor(world.static_targets, dtype=torch.float64),
        track=torch.tensor(track.table, dtype=torch.float64), track_covered=torch.tensor(track.covered))


def track_at(ctx: Context, ticks: torch.Tensor) -> torch.Tensor:
    t = ticks.long()
    if (t < 0).any() or (t >= len(ctx.track)).any() or not bool(ctx.track_covered[t].all()):
        raise ModelError("clock track does not cover a requested tick")
    return ctx.track[t]


# -- featurisation (torch, batched; the production path for training and imagination) ---------------------------------


# Lookup tables (constants): one-hot rows with row 0 = "none", tap levels of every u8 counter, tap values, popcount.
_ONEHOT_LUT = {n: torch.cat([torch.zeros(1, n), torch.eye(n)]) for n in (8, 9, 21, 23)}
_TAP_LEVEL_LUT = torch.tensor([us.tap_level_index(r) for r in range(256)], dtype=torch.long)
_TAP_VALUE_LUT = torch.tensor(us.TAP_LEVEL_VALUES, dtype=torch.float64)
_POPCOUNT_LUT = torch.tensor([bin(i).count("1") for i in range(1 << us.TARGET_COUNT)], dtype=torch.float64)


def _onehot(idx: torch.Tensor, n: int) -> torch.Tensor:
    """(N,) with -1 = none -> (N, n) float32 (a zero row for none)."""
    return _ONEHOT_LUT[n][idx.long() + 1]


def _tap_value(level: torch.Tensor) -> torch.Tensor:
    return _TAP_VALUE_LUT[level.long().clamp(0, 4)]


def _tap_level_t(raw: torch.Tensor) -> torch.Tensor:
    return _TAP_LEVEL_LUT[raw.long().clamp(0, 255)]


def featurise(ctx: Context, rows: torch.Tensor, hist: torch.Tensor, words: torch.Tensor
              ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """rows (N, N_FIELDS) float64, hist (N, N_HIST) float64, words (N, 2) long (the word submitted at this state) ->
    dense (N, 338) float32, current status vocab index (N,), previous status vocab index (N,)."""
    F, Hh = us.F, us.Hh
    L, V = us.LENGTH_SCALE, us.VELOCITY_SCALE
    N = rows.shape[0]
    col = lambda name: rows[:, F[name]]  # noqa: E731
    hc = lambda name: hist[:, Hh[name]]  # noqa: E731
    px, py = col("x"), col("y")
    tk = track_at(ctx, col("input_tick"))
    parts: List[torch.Tensor] = []
    # words (68): the word at this state, then the three previous words
    for s, b in ((words[:, 0], words[:, 1]), (hc("w1s"), hc("w1b")), (hc("w2s"), hc("w2b")), (hc("w3s"), hc("w3b"))):
        parts += [_onehot(s.long(), 9), _onehot(b.long(), 8)]
    # agent (35): v3 order without cliff_hold; status tics from bookkeeping; then the v4 appended fields without echoes
    status = col("status").long().clamp(0, STATUS_LOOKUP - 1)
    jm = col("jumps_max")
    jumps_left = torch.where(jm > 0, (jm - col("jumps_used")) / jm.clamp(min=1.0), torch.zeros_like(jm)).clamp(0.0, 1.0)
    z = col("z")
    agent = torch.stack([
        px / L, py / L, (px - hc("prev_x")) / V, (py - hc("prev_y")) / V,
        col("vax") / V, col("vay") / V, col("vgx") / V, col("carry_x") / V, col("carry_y") / V,
        col("facing"), (col("ga") == 0).double(), col("c_floor"), col("c_ceil"), col("c_lwall"), col("c_rwall"),
        col("floor_dist").clamp(-us.FLOOR_DIST_CAP, us.FLOOR_DIST_CAP) / L, jumps_left,
        col("status") / us.STATUS_ID_SCALE, hc("run_ticks").clamp(max=us.STATUS_TICS_CAP) / us.PROGRESS_SCALE,
        col("hitlag").clamp(max=us.HITLAG_CAP) / us.PROGRESS_SCALE, col("attack"), col("shield"), col("fastfall"),
        col("time_passed") / us.TIME_SCALE, col("targets_remaining") / 10.0, col("coll_top") / L, col("coll_width") / L,
        _tap_value(_tap_level_t(col("tap_x"))), _tap_value(_tap_level_t(col("tap_y"))),
        z.clamp(0, us.Z_WINDOW) / us.Z_WINDOW, (z > us.Z_WINDOW).double(),
        col("anim_frame").clamp(0.0, us.ANIM_FRAME_CAP) / us.PROGRESS_SCALE,
        col("anim_speed").clamp(0.0, us.ANIM_SPEED_CAP) / us.ANIM_SPEED_CAP,
        ((col("mflag1") != 0) & ctx.aerial[status]).double(), col("c_edge"),
    ], dim=1)
    parts.append(agent.float())
    # extras (42): motion flag 1, tap history, facing at run start, last grounded floor, tornado bit, latched masks
    tap_mask, rel_mask = col("tap_mask").long(), col("rel_mask").long()
    bits = torch.arange(7)
    extras = [col("mflag1")[:, None], _tap_value(hc("tapx1"))[:, None], _tap_value(hc("tapy1"))[:, None],
              _tap_value(hc("tapx2"))[:, None], _tap_value(hc("tapy2"))[:, None], hc("facing_start")[:, None],
              _onehot((hc("last_floor") + 1).long(), us.N_FLOOR_CLASSES).double(), hc("tornado")[:, None],
              ((tap_mask[:, None] >> bits) & 1).double(), ((rel_mask[:, None] >> bits) & 1).double()]
    parts.append(torch.cat(extras, dim=1).float())
    # class v2 (23)
    parts.append(_onehot(ctx.status_class[status], len(st2.CLASSES)))
    # segments (8 x 15): v3 arithmetic, moving group from the track, 8 nearest by closest-point distance (stable)
    seg = ctx.seg[None, :, :].expand(N, -1, -1)
    mv = ctx.seg_moving[None, :].expand(N, -1)
    tx = tk[:, 0:1].expand(-1, seg.shape[1])
    ty = tk[:, 1:2].expand(-1, seg.shape[1])
    ax = torch.where(mv, (seg[:, :, 0].float() + tx.float()).double(), seg[:, :, 0])
    ay = torch.where(mv, (seg[:, :, 1].float() + ty.float()).double(), seg[:, :, 1])
    bx = torch.where(mv, (seg[:, :, 2].float() + tx.float()).double(), seg[:, :, 2])
    by = torch.where(mv, (seg[:, :, 3].float() + ty.float()).double(), seg[:, :, 3])
    sx = torch.where(mv, tk[:, 2:3].expand_as(ax), torch.zeros_like(ax))
    sy = torch.where(mv, tk[:, 3:4].expand_as(ax), torch.zeros_like(ax))
    vx, vy = bx - ax, by - ay
    vv = vx * vx + vy * vy
    rax, ray = ax - px[:, None], ay - py[:, None]
    t = (-(rax * vx + ray * vy) / vv).clamp(0.0, 1.0)
    nx, ny = rax + t * vx, ray + t * vy
    geo = torch.stack([rax / L, ray / L, (bx - px[:, None]) / L, (by - py[:, None]) / L, nx / L, ny / L, sx / V, sy / V],
                      dim=2)
    kind = ctx.seg_kind[None, :, :].expand(N, -1, -1).clone()
    kind[:, :, 6] = mv.float()
    dist = torch.sqrt(nx * nx + ny * ny)
    order = torch.sort(dist, dim=1, stable=True).indices[:, :us.SEGMENTS_KEPT]
    g8 = torch.gather(geo, 1, order[:, :, None].expand(-1, -1, us.SEG_GEOM))
    k8 = torch.gather(kind, 1, order[:, :, None].expand(-1, -1, us.SEG_KIND))
    parts.append(torch.cat([g8.float(), k8], dim=2).reshape(N, -1))
    # targets (10 x 5): relative position, position change since the previous state, live
    live = col("live_mask").long()
    tpos = ctx.static_targets[None, :, :].expand(N, -1, -1).clone()
    tpos[:, us.MOVING_TARGET_ID, 0] = tk[:, 4]
    tpos[:, us.MOVING_TARGET_ID, 1] = tk[:, 5]
    is_live = ((live[:, None] >> torch.arange(us.TARGET_COUNT)) & 1).bool()
    tv = torch.zeros(N, us.TARGET_COUNT, 2, dtype=torch.float64)
    prev2 = torch.stack([hc("prev_t2x"), hc("prev_t2y")], dim=1)
    ok2 = ~torch.isnan(prev2[:, 0])
    tv[:, us.MOVING_TARGET_ID] = torch.where(ok2[:, None], (tpos[:, us.MOVING_TARGET_ID] - prev2) / V,
                                             torch.zeros_like(prev2))
    tgt = torch.cat([(tpos[:, :, 0:1] - px[:, None, None]) / L, (tpos[:, :, 1:2] - py[:, None, None]) / L, tv,
                     torch.ones(N, us.TARGET_COUNT, 1, dtype=torch.float64)], dim=2)
    tgt = torch.where(is_live[:, :, None], tgt, torch.zeros_like(tgt))
    parts.append(tgt.float().reshape(N, -1))
    dense = torch.cat(parts, dim=1)
    if dense.shape[1] != DENSE:
        raise ModelError(f"dense width {dense.shape[1]} != {DENSE}")
    cur = ctx.status_to_idx[status]
    prev = ctx.status_to_idx[hc("prev_status").long().clamp(0, STATUS_LOOKUP - 1)]
    return dense, cur, prev


def advance_history_t(hist: torch.Tensor, row_prev: torch.Tensor, words: torch.Tensor, row_next: torch.Tensor
                      ) -> torch.Tensor:
    """Batched rl/m7u_state.advance_history (identical rule)."""
    F, Hh = us.F, us.Hh
    n = hist.clone()
    n[:, Hh["w3s"]], n[:, Hh["w3b"]] = hist[:, Hh["w2s"]], hist[:, Hh["w2b"]]
    n[:, Hh["w2s"]], n[:, Hh["w2b"]] = hist[:, Hh["w1s"]], hist[:, Hh["w1b"]]
    n[:, Hh["w1s"]], n[:, Hh["w1b"]] = words[:, 0].double(), words[:, 1].double()
    n[:, Hh["tapx2"]], n[:, Hh["tapy2"]] = hist[:, Hh["tapx1"]], hist[:, Hh["tapy1"]]
    n[:, Hh["tapx1"]] = _tap_level_t(row_prev[:, F["tap_x"]]).double()
    n[:, Hh["tapy1"]] = _tap_level_t(row_prev[:, F["tap_y"]]).double()
    changed = row_next[:, F["status"]].long() != row_prev[:, F["status"]].long()
    n[:, Hh["prev_status"]] = torch.where(changed, row_prev[:, F["status"]], hist[:, Hh["prev_status"]])
    n[:, Hh["run_ticks"]] = torch.where(changed, torch.zeros_like(hist[:, 0]),
                                        (hist[:, Hh["run_ticks"]] + 1).clamp(max=us.STATUS_TICS_CAP))
    n[:, Hh["facing_start"]] = torch.where(changed, row_next[:, F["facing"]], hist[:, Hh["facing_start"]])
    grounded = row_next[:, F["ga"]].long() == 0
    ended = ((row_prev[:, F["status"]].long() == us.STATUS_SPECIAL_AIR_LW)
             & (row_next[:, F["status"]].long() != us.STATUS_SPECIAL_AIR_LW))
    n[:, Hh["last_floor"]] = torch.where(grounded, row_next[:, F["floor_line"]], hist[:, Hh["last_floor"]])
    n[:, Hh["tornado"]] = torch.where(grounded, torch.zeros_like(hist[:, 0]),
                                      torch.where(ended, torch.ones_like(hist[:, 0]), hist[:, Hh["tornado"]]))
    n[:, Hh["prev_x"]], n[:, Hh["prev_y"]] = row_prev[:, F["x"]], row_prev[:, F["y"]]
    n[:, Hh["prev_t2x"]], n[:, Hh["prev_t2y"]] = row_prev[:, F["t2_x"]], row_prev[:, F["t2_y"]]
    return n


# -- the ensemble ------------------------------------------------------------------------------------------------------


class EnsembleLinear(nn.Module):
    """E independent linear layers applied as one batched matmul: x (E, N, i) -> (E, N, o)."""

    def __init__(self, e: int, i: int, o: int, gen: torch.Generator):
        super().__init__()
        bound = 1.0 / math.sqrt(i)
        self.weight = nn.Parameter((torch.rand(e, i, o, generator=gen) * 2 - 1) * bound)
        self.bias = nn.Parameter((torch.rand(e, 1, o, generator=gen) * 2 - 1) * bound)
        self.shape = (i, o)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.baddbmm(self.bias, x, self.weight)


class EnsembleEmbedding(nn.Module):
    def __init__(self, e: int, n: int, d: int, gen: torch.Generator):
        super().__init__()
        self.weight = nn.Parameter(torch.randn(e, n, d, generator=gen) * 0.1)

    def forward(self, idx: torch.Tensor) -> torch.Tensor:          # idx (E, N) long -> (E, N, d)
        return torch.gather(self.weight, 1, idx[:, :, None].expand(-1, -1, self.weight.shape[2]))


class DynamicsEnsemble(nn.Module):
    def __init__(self, vocab: Vocab, members: int = 3, seed: int = 0):
        super().__init__()
        g = torch.Generator().manual_seed(int(seed))
        E, S, V3, V4 = members, vocab.S, vocab.V3, vocab.V4
        self.members = E
        self.dims = {"S": S, "V3": V3, "V4": V4}
        self.emb_s = EnsembleEmbedding(E, S, EMB_STATUS, g)
        self.emb_h2 = EnsembleEmbedding(E, N_H2, EMB_H2, g)
        self.emb_h3 = EnsembleEmbedding(E, V3, EMB_H3, g)
        self.l1 = EnsembleLinear(E, DENSE + 2 * EMB_STATUS, HIDDEN, g)
        self.l2 = EnsembleLinear(E, HIDDEN, HIDDEN, g)
        self.h1 = EnsembleLinear(E, HIDDEN, S, g)
        self.h2 = EnsembleLinear(E, HIDDEN + EMB_STATUS, N_H2, g)
        self.h3 = EnsembleLinear(E, HIDDEN + EMB_STATUS + EMB_H2, V3, g)
        self.h4 = EnsembleLinear(E, HIDDEN + EMB_STATUS, V4, g)
        self.h5 = EnsembleLinear(E, HIDDEN + EMB_STATUS, 5 + 5 + us.N_Z_LEVELS + 14, g)
        self.h6a = EnsembleLinear(E, HIDDEN + EMB_STATUS + EMB_H2 + EMB_H3, H6_HIDDEN, g)
        self.h6b = EnsembleLinear(E, H6_HIDDEN, len(H6_FIELDS), g)
        self.h7 = EnsembleLinear(E, HIDDEN, us.TARGET_COUNT + 1, g)

    def macs_per_transition(self) -> int:
        """Multiply-accumulates of the linear layers for one transition of one member (embedding gathers excluded)."""
        return sum(m.shape[0] * m.shape[1] for m in self.modules() if isinstance(m, EnsembleLinear))

    def trunk(self, dense: torch.Tensor, cur: torch.Tensor, prev: torch.Tensor) -> torch.Tensor:
        x = torch.cat([dense, self.emb_s(cur), self.emb_s(prev)], dim=2)
        return Fn.silu(self.l2(Fn.silu(self.l1(x))))

    def heads_given(self, h: torch.Tensor, s_next: torch.Tensor, h2_next: torch.Tensor, h3_next: torch.Tensor
                    ) -> Dict[str, torch.Tensor]:
        """Every head's raw output, the conditional heads conditioned on the given next values (teacher forcing in
        training, the decoded values in a rollout)."""
        es, e2, e3 = self.emb_s(s_next), self.emb_h2(h2_next), self.emb_h3(h3_next)
        hs = torch.cat([h, es], dim=2)
        return {"h1": self.h1(h), "h2": self.h2(hs), "h3": self.h3(torch.cat([h, es, e2], dim=2)), "h4": self.h4(hs),
                "h5": self.h5(hs), "h6": self.h6b(Fn.silu(self.h6a(torch.cat([h, es, e2, e3], dim=2)))),
                "h7": self.h7(h)}


# -- training ----------------------------------------------------------------------------------------------------------


@dataclass
class Episode:
    """One recorded episode: rows (T + 1), the T submitted Track 1 words, and whether it ended in a native fall."""
    episode_id: str
    rows: np.ndarray
    words: np.ndarray
    fell: bool


@dataclass
class TransitionSet:
    dense: torch.Tensor
    cur: torch.Tensor
    prev: torch.Tensor
    targets: Dict[str, torch.Tensor]
    episode_of: np.ndarray
    n_episodes: int


def transition_targets(ctx: Context, row_t: np.ndarray, row_n: np.ndarray, fall: np.ndarray) -> Dict[str, torch.Tensor]:
    F = us.F
    v = ctx.vocab
    s2i = {s: k + 1 for k, s in enumerate(v.status_ids)}
    h3i = {c: k for k, c in enumerate(v.h3_combos)}
    h4i = {c: k for k, c in enumerate(v.h4_combos)}
    n = len(row_n)
    s_next = np.array([s2i.get(int(s), 0) for s in row_n[:, F["status"]]], dtype=np.int64)
    h2 = np.array([h2_index(r[F["ga"]], r[F["facing"]], r[F["jumps_used"]], r[F["fastfall"]]) for r in row_n], np.int64)
    h3 = np.array([h3i[(int(r[F["floor_line"]]), contact_bits(r))] for r in row_n], dtype=np.int64)
    h4 = np.array([h4i[h4_key(r)] for r in row_n], dtype=np.int64)
    tapx = np.array([us.tap_level_index(v_) for v_ in row_n[:, F["tap_x"]]], dtype=np.int64)
    tapy = np.array([us.tap_level_index(v_) for v_ in row_n[:, F["tap_y"]]], dtype=np.int64)
    z = np.array([us.z_level_index(v_) for v_ in row_n[:, F["z"]]], dtype=np.int64)
    bits = np.arange(7)
    masks = np.concatenate([(row_n[:, F["tap_mask"]].astype(np.int64)[:, None] >> bits) & 1,
                            (row_n[:, F["rel_mask"]].astype(np.int64)[:, None] >> bits) & 1], axis=1).astype(np.float32)
    h6 = np.stack([(row_n[:, F["x"]] - row_t[:, F["x"]]), (row_n[:, F["y"]] - row_t[:, F["y"]]), row_n[:, F["vax"]],
                   row_n[:, F["vay"]], row_n[:, F["vgx"]],
                   np.clip(row_n[:, F["floor_dist"]], -us.FLOOR_DIST_CAP, us.FLOOR_DIST_CAP), row_n[:, F["carry_x"]],
                   row_n[:, F["carry_y"]], row_n[:, F["coll_top"]], row_n[:, F["coll_width"]],
                   np.clip(row_n[:, F["anim_frame"]], -60.0, us.ANIM_FRAME_CAP), row_n[:, F["anim_speed"]]], axis=1)
    h6 = h6 / np.array(H6_SCALE)
    live_t = row_t[:, F["live_mask"]].astype(np.int64)
    live_n = row_n[:, F["live_mask"]].astype(np.int64)
    tb = np.arange(us.TARGET_COUNT)
    was = (live_t[:, None] >> tb) & 1
    now = (live_n[:, None] >> tb) & 1
    return {"s": torch.tensor(s_next), "h2": torch.tensor(h2), "h3": torch.tensor(h3), "h4": torch.tensor(h4),
            "ga": torch.tensor(row_n[:, F["ga"]].astype(np.int64) & 1), "tapx": torch.tensor(tapx),
            "tapy": torch.tensor(tapy), "z": torch.tensor(z), "masks": torch.tensor(masks),
            "h6": torch.tensor(h6, dtype=torch.float32), "breaks": torch.tensor((was & (1 - now)).astype(np.float32)),
            "live": torch.tensor(was.astype(np.float32)), "fall": torch.tensor(fall.astype(np.float32))}


def episode_transitions(ep: Episode) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(t indices, row_t, row_next, words, fall label) of the usable transitions: both rows valid; the last transition
    of a fall episode carries fall = 1 (its target row is the terminal reply, kept when valid)."""
    F = us.F
    rows = ep.rows
    T = len(ep.words)
    idx, fall = [], []
    for k in range(T):
        if rows[k, F["valid"]] == 1.0 and rows[k + 1, F["valid"]] == 1.0:
            idx.append(k)
            fall.append(1.0 if (ep.fell and k == T - 1) else 0.0)
    idx_a = np.array(idx, dtype=np.int64)
    return idx_a, rows[idx_a], rows[idx_a + 1], ep.words[idx_a], np.array(fall)


def build_transitions(ctx: Context, episodes: Sequence[Episode], chunk: int = 8192) -> TransitionSet:
    dense, cur, prev, tgt_parts, epi = [], [], [], [], []
    for e, ep in enumerate(episodes):
        hist = us.history_sequence(ep.rows, [tuple(int(v) for v in w) for w in ep.words])
        idx, row_t, row_n, words, fall = episode_transitions(ep)
        if len(idx) == 0:
            continue
        for a in range(0, len(idx), chunk):
            sl = slice(a, a + chunk)
            d, c, p = featurise(ctx, torch.tensor(row_t[sl]), torch.tensor(hist[idx[sl]]),
                                torch.tensor(words[sl], dtype=torch.long))
            dense.append(d)
            cur.append(c)
            prev.append(p)
        tgt_parts.append(transition_targets(ctx, row_t, row_n, fall))
        epi.append(np.full(len(idx), e, dtype=np.int64))
    if not dense:
        raise ModelError("no usable transitions")
    targets = {k: torch.cat([t[k] for t in tgt_parts]) for k in tgt_parts[0]}
    return TransitionSet(dense=torch.cat(dense), cur=torch.cat(cur), prev=torch.cat(prev), targets=targets,
                         episode_of=np.concatenate(epi), n_episodes=len(episodes))


def masked_logits(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return logits.masked_fill(~mask, -1e9)


def losses(model: DynamicsEnsemble, ctx: Context, batch_idx: torch.Tensor, ts: TransitionSet) -> Dict[str, torch.Tensor]:
    """Teacher-forced one-step losses; batch_idx (E, B) long (each member's own transitions)."""
    t = {k: v[batch_idx] for k, v in ts.targets.items()}
    h = model.trunk(ts.dense[batch_idx], ts.cur[batch_idx], ts.prev[batch_idx])
    out = model.heads_given(h, t["s"], t["h2"], t["h3"])
    E, B = batch_idx.shape
    ce = lambda lg, y: Fn.cross_entropy(lg.reshape(E * B, -1), y.reshape(-1))  # noqa: E731
    h2m = masked_logits(out["h2"], ctx.h2_mask[t["s"]])
    h3m = masked_logits(out["h3"], ctx.h3_mask[t["ga"]])
    h5 = out["h5"]
    nz = us.N_Z_LEVELS
    L: Dict[str, torch.Tensor] = {
        "h1": ce(out["h1"], t["s"]), "h2": ce(h2m, t["h2"]), "h3": ce(h3m, t["h3"]), "h4": ce(out["h4"], t["h4"]),
        "tapx": ce(h5[:, :, 0:5], t["tapx"]), "tapy": ce(h5[:, :, 5:10], t["tapy"]), "z": ce(h5[:, :, 10:10 + nz], t["z"]),
        "masks": Fn.binary_cross_entropy_with_logits(h5[:, :, 10 + nz:], t["masks"]),
        "h6": (Fn.huber_loss(out["h6"], t["h6"], reduction="none", delta=1.0)
               * torch.tensor(H6_WEIGHT, dtype=torch.float32)).mean(),
        "breaks": (Fn.binary_cross_entropy_with_logits(out["h7"][:, :, :us.TARGET_COUNT], t["breaks"], reduction="none")
                   * t["live"]).sum() / t["live"].sum().clamp(min=1.0),
        "fall": Fn.binary_cross_entropy_with_logits(out["h7"][:, :, us.TARGET_COUNT], t["fall"]),
    }
    L["total"] = sum(LOSS_WEIGHTS[k] * v for k, v in L.items())
    return L


@dataclass
class TrainResult:
    steps: int
    wall_s: float
    log: List[Dict[str, Any]] = field(default_factory=list)
    stopped: Optional[str] = None


def bootstrap_indices(ts: TransitionSet, members: int, seed: int) -> List[np.ndarray]:
    """Episode-level bootstrap: member m resamples the episode list with replacement (its own generator)."""
    by_ep: Dict[int, np.ndarray] = {}
    for e in np.unique(ts.episode_of):
        by_ep[int(e)] = np.nonzero(ts.episode_of == e)[0]
    eps = sorted(by_ep)
    out = []
    for m in range(members):
        rng = np.random.default_rng(np.random.SeedSequence([int(seed), 7919, m]))
        pick = rng.choice(len(eps), size=len(eps), replace=True)
        out.append(np.concatenate([by_ep[eps[i]] for i in pick]))
    return out


def train(model: DynamicsEnsemble, ctx: Context, ts: TransitionSet, *, steps: int, batch: int = 1024, lr: float = 3e-4,
          seed: int = 0, heldout: Optional[TransitionSet] = None, log_every: int = 1000,
          should_stop: Optional[Callable[[], Optional[str]]] = None) -> TrainResult:
    """Adam, fixed step count, no early stopping. `should_stop()` returning a reason ends training at once (the caller
    records an incomplete run; nothing is extended)."""
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    boot = bootstrap_indices(ts, model.members, seed)
    gens = [torch.Generator().manual_seed(int(seed) * 1000 + 17 + m) for m in range(model.members)]
    res = TrainResult(steps=0, wall_s=0.0)
    t0 = time.perf_counter()
    for step in range(1, steps + 1):
        if should_stop is not None:
            why = should_stop()
            if why:
                res.stopped = why
                break
        idx = torch.stack([torch.as_tensor(boot[m])[torch.randint(len(boot[m]), (batch,), generator=gens[m])]
                           for m in range(model.members)])
        L = losses(model, ctx, idx, ts)
        opt.zero_grad(set_to_none=True)
        L["total"].backward()
        opt.step()
        res.steps = step
        if step % log_every == 0 or step == steps:
            row = {"step": step, "wall_s": round(time.perf_counter() - t0, 1),
                   **{k: round(float(v.detach()), 5) for k, v in L.items()}}
            if heldout is not None:
                with torch.no_grad():
                    n = min(4096, len(heldout.cur))
                    hi = torch.arange(n)[None, :].expand(model.members, -1)
                    row["heldout_total"] = round(float(losses(model, ctx, hi, heldout)["total"]), 5)
            res.log.append(row)
    res.wall_s = round(time.perf_counter() - t0, 1)
    return res


# -- imagination ---------------------------------------------------------------------------------------------------------


@dataclass
class Rollout:
    x: torch.Tensor            # (E, N, H) predicted positions after each planned word
    y: torch.Tensor
    air: torch.Tensor          # (E, N, H) bool
    fall_at: torch.Tensor      # (E, N) long: first index with a predicted fall, H if none
    rows: Optional[torch.Tensor] = None   # (E, N, H, N_FIELDS) when requested


def decode_step(model: DynamicsEnsemble, ctx: Context, h: torch.Tensor) -> Dict[str, torch.Tensor]:
    """Masked argmax decoding in the fixed order H1 -> H2 -> H3 -> H4 -> H5, then H6 / H7 conditioned on the choices."""
    E, N, _ = h.shape
    lg1 = model.h1(h).clone()
    lg1[:, :, 0] = -1e9                                    # 'unseen' is never imagined
    s = lg1.argmax(dim=2)
    es = model.emb_s(s)
    hs = torch.cat([h, es], dim=2)
    h2 = masked_logits(model.h2(hs), ctx.h2_mask[s]).argmax(dim=2)
    ga = torch.div(h2, 12, rounding_mode="floor")
    e2 = model.emb_h2(h2)
    h3 = masked_logits(model.h3(torch.cat([h, es, e2], dim=2)), ctx.h3_mask[ga]).argmax(dim=2)
    e3 = model.emb_h3(h3)
    h4 = model.h4(hs).argmax(dim=2)
    h5 = model.h5(hs)
    nz = us.N_Z_LEVELS
    h6 = model.h6b(Fn.silu(model.h6a(torch.cat([h, es, e2, e3], dim=2))))
    h7 = torch.sigmoid(model.h7(h))
    return {"s": s, "h2": h2, "h3": h3, "h4": h4, "tapx": h5[:, :, 0:5].argmax(2), "tapy": h5[:, :, 5:10].argmax(2),
            "z": h5[:, :, 10:10 + nz].argmax(2), "masks": (h5[:, :, 10 + nz:] > 0).long(), "h6": h6,
            "breaks": h7[:, :, :us.TARGET_COUNT] > 0.5, "fall": h7[:, :, us.TARGET_COUNT] > 0.5}


_H6_COLS = [us.F[name] for name in H6_FIELDS[2:]]
_CONTACT_COLS = [us.F[c] for c in ("c_floor", "c_ceil", "c_lwall", "c_rwall", "c_edge")]
_H4_COLS = [us.F[c] for c in ("hitlag", "attack", "shield", "mflag1")]
_TRACK_COLS = [us.F[c] for c in us.TRACK_COLUMNS]
_NAN_COLS = [us.F[c] for c in ("hold", "stick_x", "stick_y", "status_tics", "n_proj", "game_status")]


def compose_next(ctx: Context, rows: torch.Tensor, d: Mapping[str, torch.Tensor]) -> torch.Tensor:
    """The next imagined row from the current row (E*N, F) and the decoded predictions (flattened to E*N). Fields that
    are neither predicted nor used by the featurisation (button hold echo, stick echo, native status tics, projectile
    count, game status) become NaN, so any accidental use is visible."""
    F = us.F
    n = rows.clone()
    h6 = d["h6"].double() * torch.tensor(H6_SCALE, dtype=torch.float64)
    n[:, F["x"]] = rows[:, F["x"]] + h6[:, 0]
    n[:, F["y"]] = rows[:, F["y"]] + h6[:, 1]
    n[:, _H6_COLS] = h6[:, 2:]
    n[:, F["status"]] = ctx.idx_to_status[d["s"]]
    h2 = d["h2"]
    n[:, F["ga"]] = torch.div(h2, 12, rounding_mode="floor").double()
    n[:, F["facing"]] = torch.where(torch.div(h2, 6, rounding_mode="floor") % 2 == 1, 1.0, -1.0).double()
    n[:, F["jumps_used"]] = (torch.div(h2, 2, rounding_mode="floor") % 3).double()
    n[:, F["fastfall"]] = (h2 % 2).double()
    n[:, F["floor_line"]] = ctx.h3_floor[d["h3"]]
    n[:, _CONTACT_COLS] = ctx.h3_bits[d["h3"]]
    n[:, _H4_COLS] = ctx.h4_vals[d["h4"]]
    raw = torch.tensor(TAP_RAW_OF_LEVEL, dtype=torch.float64)
    n[:, F["tap_x"]] = raw[d["tapx"]]
    n[:, F["tap_y"]] = raw[d["tapy"]]
    n[:, F["z"]] = d["z"].double()
    m = d["masks"]
    w = 2 ** torch.arange(7)
    n[:, F["tap_mask"]] = (m[:, :7] * w).sum(1).double()
    n[:, F["rel_mask"]] = (m[:, 7:] * w).sum(1).double()
    live = rows[:, F["live_mask"]].long()
    brk = (d["breaks"].long() * (2 ** torch.arange(us.TARGET_COUNT))).sum(1)
    live = live & ~brk
    n[:, F["live_mask"]] = live.double()
    n[:, F["targets_remaining"]] = _POPCOUNT_LUT[live.clamp(0, (1 << us.TARGET_COUNT) - 1)]
    n[:, F["input_tick"]] = rows[:, F["input_tick"]] + 1
    n[:, F["time_passed"]] = rows[:, F["time_passed"]] + 1
    n[:, _TRACK_COLS] = track_at(ctx, n[:, F["input_tick"]])
    t2_live = ((live >> us.MOVING_TARGET_ID) & 1).bool()
    n[:, F["t2_x"]] = torch.where(t2_live, n[:, F["t2_x"]], torch.full_like(n[:, 0], float("nan")))
    n[:, F["t2_y"]] = torch.where(t2_live, n[:, F["t2_y"]], torch.full_like(n[:, 0], float("nan")))
    n[:, _NAN_COLS] = float("nan")
    n[:, F["valid"]] = 1.0
    return n


@torch.inference_mode()
def rollout(model: DynamicsEnsemble, ctx: Context, start_rows: torch.Tensor, start_hist: torch.Tensor,
            plans: torch.Tensor, *, keep_rows: bool = False) -> Rollout:
    """Imagine every member over every plan: start_rows (N, F), start_hist (N, Hh), plans (N, H, 2) long. Members roll
    independently (states are never averaged). A predicted fall freezes that member's rollout."""
    E = model.members
    N, H, _ = plans.shape
    rows = start_rows[None].expand(E, -1, -1).reshape(E * N, -1).clone()
    hist = start_hist[None].expand(E, -1, -1).reshape(E * N, -1).clone()
    xs, ys, airs = [], [], []
    fall_at = torch.full((E * N,), H, dtype=torch.long)
    dead = torch.zeros(E * N, dtype=torch.bool)
    kept = [] if keep_rows else None
    for tau in range(H):
        w = plans[:, tau, :][None].expand(E, -1, -1).reshape(E * N, 2)
        dense, cur, prev = featurise(ctx, rows, hist, w)
        h = model.trunk(dense.view(E, N, -1), cur.view(E, N), prev.view(E, N))
        d = decode_step(model, ctx, h)
        flat = {k: (v.reshape(E * N, *v.shape[2:])) for k, v in d.items()}
        nxt = compose_next(ctx, rows, flat)
        nxt = torch.where(dead[:, None], rows, nxt)
        new_hist = advance_history_t(hist, rows, w, nxt)
        hist = torch.where(dead[:, None], hist, new_hist)
        newly = flat["fall"] & ~dead
        fall_at = torch.where(newly, torch.full_like(fall_at, tau), fall_at)
        dead = dead | flat["fall"]
        rows = nxt
        xs.append(rows[:, us.F["x"]])
        ys.append(rows[:, us.F["y"]])
        airs.append(rows[:, us.F["ga"]] == 1)
        if kept is not None:
            kept.append(rows.clone())
    out = Rollout(x=torch.stack(xs, 1).view(E, N, H), y=torch.stack(ys, 1).view(E, N, H),
                  air=torch.stack(airs, 1).view(E, N, H), fall_at=fall_at.view(E, N))
    if kept is not None:
        out.rows = torch.stack(kept, 1).view(E, N, H, -1)
    return out


# -- persistence ---------------------------------------------------------------------------------------------------------


def save(model: DynamicsEnsemble, vocab: Vocab, path: Any, meta: Optional[Mapping[str, Any]] = None) -> str:
    buf = io.BytesIO()
    torch.save({"contract": MODEL_CONTRACT, "state_dict": model.state_dict(), "members": model.members,
                "vocab": vocab.to_json(), "meta": dict(meta or {})}, buf)
    data = buf.getvalue()
    with open(path, "wb") as fp:
        fp.write(data)
    return hashlib.sha256(data).hexdigest()


def load(path: Any) -> Tuple[DynamicsEnsemble, Vocab, Dict[str, Any]]:
    d = torch.load(path, map_location="cpu", weights_only=False)
    if d.get("contract") != MODEL_CONTRACT:
        raise ModelError(f"{path}: not a {MODEL_CONTRACT} checkpoint")
    vocab = Vocab.from_json(d["vocab"])
    m = DynamicsEnsemble(vocab, members=int(d["members"]))
    m.load_state_dict(d["state_dict"])
    return m, vocab, dict(d.get("meta") or {})


def parameter_digest(model: DynamicsEnsemble) -> str:
    h = hashlib.sha256()
    for k, v in sorted(model.state_dict().items()):
        h.update(k.encode("utf-8"))
        h.update(v.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()
