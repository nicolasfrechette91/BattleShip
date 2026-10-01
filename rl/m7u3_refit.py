"""M7u3: the refit pipeline (design: docs/rl_model_planning_m7u3_proposal_2026-10-01.md section 3.2, as amended by
docs/rl_model_planning_m7u3_decisions_2026-10-01.md). Opt-in; PyTorch, CPU, main process only.

The refit is the M7u1 training pipeline with ONE intended difference, the data:
- the same architecture (E = 3, trunk 370 -> 256 -> 256, heads H1-H7, vocabulary caps 160 / 128 / 64);
- the same loss, Adam 3e-4, batch 1,024 per member, S = 6,000 one-step teacher-forced steps, per-member batch
  generators seeded `seed * 1000 + 17 + m`, no early stopping and no checkpoint choice (the step-S parameters are the
  model), trained FROM SCRATCH (never warm-started);
- the same initialisation (`DynamicsEnsemble(vocab, members=3, seed=seed)`);
- the only change to the sampler is a STRATIFIED episode bootstrap (below). With an empty pool it reduces exactly to
  m7u1's `bootstrap_indices`, which is what makes "the refit pipeline without the new pool" reproduce the frozen model.

`train_loop` is `rl/m7u_model.train` with the bootstrap injected; nothing else differs (the identity retrain and a test
check that the two produce identical parameters). It is the ONLY training path of m7u3 and the only place an optimizer
is constructed; each construction is registered, so the gate can assert exactly one optimizer exists in a run.

Data manifest (checked by the gate): M7u1's 80 training episodes (collection.json order) first, then the training-pool
episodes. M7u1's 12 held-out episodes are used only to log a held-out loss every 1,000 steps (it decides nothing).

    python rl/m7u3_refit.py identity   # the identity retrain: refit pipeline, empty pool, seed 0 -> must equal 0e70af78...
    python rl/m7u3_refit.py retrain    # P_retrain: M7u1 data only, training seed 1 (offline diagnostic model; no native arm)

Both write only under logs/m7u3_prep/ (never runs/).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m7u_model as um  # noqa: E402
import m7u_state as us  # noqa: E402

CONTRACT = "m7u3_refit_v1"
MEMBERS = 3
STEPS = 6000
BATCH = 1024
LR = 3e-4
LOG_EVERY = 1000
TRAIN_SEED = 0                    # the refit's training seed (= m7u1's GATE_SEED)
RETRAIN_SEED = 1                  # P_retrain's training seed (offline diagnostic model)
N_M7U1_TRAIN = 80
BOOT_SALT = 7919                  # m7u1's SeedSequence salt (rl/m7u_model.bootstrap_indices)
REPO_ROOT = Path(__file__).resolve().parent.parent
PREP_DIR = REPO_ROOT / "logs" / "m7u3_prep"


class RefitError(RuntimeError):
    pass


# -- the stratified episode bootstrap ----------------------------------------------------------------------------------


def stratified_bootstrap_indices(ts: um.TransitionSet, n_base: int, members: int, seed: int) -> List[np.ndarray]:
    """Member m's transition indices. Episodes with index < n_base (M7u1's training episodes) are one stratum, the rest
    (the training pool) the other. Member m's generator (SeedSequence([seed, 7919, m])) first draws the base stratum
    with replacement exactly as m7u1's `bootstrap_indices` does, then the pool stratum. A plain bootstrap over the union
    would let the number of long M7u1 episodes per member vary (Binomial); stratifying fixes it. With an empty pool the
    result equals `um.bootstrap_indices(ts, members, seed)` element for element."""
    by_ep: Dict[int, np.ndarray] = {}
    for e in np.unique(ts.episode_of):
        by_ep[int(e)] = np.nonzero(ts.episode_of == e)[0]
    base = sorted(e for e in by_ep if e < n_base)
    pool = sorted(e for e in by_ep if e >= n_base)
    out = []
    for m in range(members):
        rng = np.random.default_rng(np.random.SeedSequence([int(seed), BOOT_SALT, m]))
        pick = [by_ep[base[i]] for i in rng.choice(len(base), size=len(base), replace=True)]
        if pool:
            pick += [by_ep[pool[i]] for i in rng.choice(len(pool), size=len(pool), replace=True)]
        out.append(np.concatenate(pick))
    return out


# -- the training loop (m7u1's, with the bootstrap injected) -----------------------------------------------------------

OPTIMIZERS: List[Dict[str, Any]] = []        # one record per optimizer constructed through train_loop (the gate asserts 1)


def train_loop(model: um.DynamicsEnsemble, ctx: um.Context, ts: um.TransitionSet, boot: Sequence[np.ndarray], *,
               steps: int, batch: int = BATCH, lr: float = LR, seed: int = TRAIN_SEED,
               heldout: Optional[um.TransitionSet] = None, log_every: int = LOG_EVERY,
               should_stop: Optional[Callable[[], Optional[str]]] = None) -> um.TrainResult:
    """`rl/m7u_model.train` line for line, except that the per-member index lists come from the caller."""
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    own = {id(p) for p in model.parameters()}
    OPTIMIZERS.append({"params": sum(len(g["params"]) for g in opt.param_groups),
                       "all_model_params": all(id(p) in own for g in opt.param_groups for p in g["params"])})
    gens = [torch.Generator().manual_seed(int(seed) * 1000 + 17 + m) for m in range(model.members)]
    res = um.TrainResult(steps=0, wall_s=0.0)
    t0 = time.perf_counter()
    for step in range(1, steps + 1):
        if should_stop is not None:
            why = should_stop()
            if why:
                res.stopped = why
                break
        idx = torch.stack([torch.as_tensor(boot[m])[torch.randint(len(boot[m]), (batch,), generator=gens[m])]
                           for m in range(model.members)])
        L = um.losses(model, ctx, idx, ts)
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
                    row["heldout_total"] = round(float(um.losses(model, ctx, hi, heldout)["total"]), 5)
            res.log.append(row)
    res.wall_s = round(time.perf_counter() - t0, 1)
    return res


# -- the refit ---------------------------------------------------------------------------------------------------------


@dataclass
class RefitResult:
    model: um.DynamicsEnsemble
    vocab: um.Vocab
    ctx: um.Context
    track: us.ClockTrack
    train: um.TrainResult
    transitions: int
    heldout_transitions: int
    n_base: int
    n_pool: int
    seed: int
    steps: int
    build_wall_s: float = 0.0
    boot_sizes: List[int] = field(default_factory=list)

    @property
    def parameter_digest(self) -> str:
        return um.parameter_digest(self.model)

    @property
    def vocab_dims(self) -> Dict[str, int]:
        return {"S": self.vocab.S, "V3": self.vocab.V3, "V4": self.vocab.V4}


def refit(base_eps: Sequence[um.Episode], pool_eps: Sequence[um.Episode], heldout_eps: Sequence[um.Episode] = (), *,
          seed: int = TRAIN_SEED, steps: int = STEPS, batch: int = BATCH, lr: float = LR, members: int = MEMBERS,
          log_every: int = LOG_EVERY, should_stop: Optional[Callable[[], Optional[str]]] = None,
          expected_track_sha256: Optional[str] = None) -> RefitResult:
    """From-scratch training on base_eps (+ pool_eps, possibly empty). The vocabulary, masks and clock track are
    derived from the training episodes alone and frozen before training; a vocabulary cap overrun raises (INVALID)."""
    t0 = time.perf_counter()
    episodes = list(base_eps) + list(pool_eps)
    if not base_eps:
        raise RefitError("no base episodes")
    track, problems = us.build_clock_track([e.rows for e in episodes])
    if problems:
        raise RefitError(f"clock track disagreement among the training episodes: {problems[:3]}")
    if expected_track_sha256 is not None and track.digest() != expected_track_sha256:
        raise RefitError("the clock track rebuilt from the training episodes differs from the pinned track")
    next_rows = np.concatenate([e.rows[1:] for e in episodes])
    vocab = um.build_vocab(next_rows)                                  # raises ModelError beyond a cap
    ctx = um.make_context(vocab, us.static_world_pinned(), track)
    ts = um.build_transitions(ctx, episodes)
    hold = um.build_transitions(ctx, list(heldout_eps)) if heldout_eps else None
    model = um.DynamicsEnsemble(vocab, members=members, seed=seed)
    boot = stratified_bootstrap_indices(ts, len(base_eps), members, seed)
    build_s = round(time.perf_counter() - t0, 1)
    tr = train_loop(model, ctx, ts, boot, steps=steps, batch=batch, lr=lr, seed=seed, heldout=hold, log_every=log_every,
                    should_stop=should_stop)
    return RefitResult(model=model, vocab=vocab, ctx=ctx, track=track, train=tr, transitions=len(ts.cur),
                       heldout_transitions=len(hold.cur) if hold is not None else 0, n_base=len(base_eps),
                       n_pool=len(pool_eps), seed=seed, steps=tr.steps, build_wall_s=build_s,
                       boot_sizes=[len(b) for b in boot])


# -- m7u1 sources as training episodes ---------------------------------------------------------------------------------


def m7u1_split(src: Any) -> Tuple[List[um.Episode], List[um.Episode]]:
    """(M7u1's 80 training episodes in collection.json order, its 12 held-out episodes). `src` is
    m7u2_gate.M7u1Sources: episodes are in collection.json order, train_ids = the training ids."""
    train_set = set(src.train_ids)
    train, held = [], []
    for eid, rows, words, fell in src.episodes:
        ep = um.Episode(episode_id=str(eid), rows=rows, words=words, fell=bool(fell))
        (train if str(eid) in train_set else held).append(ep)
    if len(train) != N_M7U1_TRAIN or [e.episode_id for e in train] != [str(i) for i in src.train_ids]:
        raise RefitError(f"m7u1 training split is {len(train)} episodes, expected {N_M7U1_TRAIN} in record order")
    return train, held


def parameter_diff(a: um.DynamicsEnsemble, b: um.DynamicsEnsemble) -> Dict[str, Any]:
    """Largest absolute and relative parameter difference between two models of the same architecture."""
    sa, sb = a.state_dict(), b.state_dict()
    if sa.keys() != sb.keys() or any(sa[k].shape != sb[k].shape for k in sa):
        return {"same_architecture": False}
    worst = max(sa, key=lambda k: float((sa[k] - sb[k]).abs().max()))
    mx = float(max((sa[k] - sb[k]).abs().max() for k in sa))
    n_diff = int(sum((sa[k] != sb[k]).sum() for k in sa))
    n_all = int(sum(v.numel() for v in sa.values()))
    return {"same_architecture": True, "max_abs_diff": mx, "worst_tensor": worst, "elements_differing": n_diff,
            "elements": n_all}


def compare_inputs(ts_saved_path: Path, episodes: Sequence[um.Episode], ctx: um.Context) -> Dict[str, Any]:
    """The rebuilt per-transition model inputs and targets against the arrays m7u1 saved (model_inputs_train.npz)."""
    ts = um.build_transitions(ctx, episodes)
    with np.load(ts_saved_path) as z:
        out = {"episode_ids_equal": [str(i) for i in z["episode_ids"]] == [e.episode_id for e in episodes],
               "transitions": int(len(z["tick"])), "rebuilt_transitions": int(len(ts.cur))}
        out["dense_equal"] = bool(np.array_equal(z["dense"], ts.dense.numpy()))
        out["cur_equal"] = bool(np.array_equal(z["cur"], ts.cur.numpy()))
        out["prev_equal"] = bool(np.array_equal(z["prev"], ts.prev.numpy()))
        out["targets_equal"] = all(bool(np.array_equal(z[f"target_{k}"], v.numpy())) for k, v in ts.targets.items())
        out["episode_of_equal"] = bool(np.array_equal(z["episode_of"], ts.episode_of))
    out["ok"] = all(v for k, v in out.items() if k.endswith("_equal")) and out["transitions"] == out["rebuilt_transitions"]
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


# -- preparation commands ----------------------------------------------------------------------------------------------


def _prep_common() -> Tuple[Any, List[um.Episode], List[um.Episode]]:
    import m7u2_gate as gg

    src = gg.load_m7u1_sources()
    train, held = m7u1_split(src)
    return src, train, held


def cmd_identity() -> int:
    """The refit pipeline with an empty pool, seed 0, on M7u1's recorded data: must reproduce the frozen parameters
    bit for bit. A mismatch is reported (max |delta|) and NOT worked around."""
    import m7u2_gate as gg

    torch.set_num_threads(max(1, os.cpu_count() or 6))               # as the m7u1 gate (run_gate)
    src, train, held = _prep_common()
    t0 = time.perf_counter()
    res = refit(train, [], held, seed=TRAIN_SEED, steps=STEPS, expected_track_sha256=gg.PIN["track_sha256"])
    inputs = compare_inputs(gg.M7U1 / "model_inputs_train.npz", train, res.ctx)
    frozen, _vocab, _meta = um.load(gg.MODEL_PATH)
    diff = parameter_diff(res.model, frozen)
    rec = {"contract": CONTRACT, "kind": "identity_retrain", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "torch": torch.__version__, "threads": torch.get_num_threads(), "seed": TRAIN_SEED, "steps": res.steps,
           "wall_s": round(time.perf_counter() - t0, 1), "train_wall_s": res.train.wall_s, "build_wall_s": res.build_wall_s,
           "transitions": res.transitions, "heldout_transitions": res.heldout_transitions, "vocab": res.vocab_dims,
           "vocab_equals_pin": res.vocab_dims == gg.PIN["vocab"], "track_sha256": res.track.digest(),
           "rebuilt_inputs_equal_m7u1_saved_inputs": inputs,
           "parameter_digest": res.parameter_digest, "frozen_parameter_digest": gg.PIN["parameter_digest"],
           "bit_exact": res.parameter_digest == gg.PIN["parameter_digest"], "parameter_diff": diff,
           "log": res.train.log, "optimizers": list(OPTIMIZERS)}
    PREP_DIR.mkdir(parents=True, exist_ok=True)
    out = PREP_DIR / "identity_retrain.json"
    out.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("bit_exact", "parameter_digest", "frozen_parameter_digest", "parameter_diff",
                                          "vocab_equals_pin", "train_wall_s")}, indent=1, default=str))
    return 0 if rec["bit_exact"] else 3


def cmd_retrain() -> int:
    """P_retrain: the same pipeline on M7u1's data only with training seed 1. Saved under logs/m7u3_prep/; its file
    sha256 and parameter digest are what the gate pins."""
    import m7u2_gate as gg

    torch.set_num_threads(max(1, os.cpu_count() or 6))
    src, train, held = _prep_common()
    t0 = time.perf_counter()
    res = refit(train, [], held, seed=RETRAIN_SEED, steps=STEPS, expected_track_sha256=gg.PIN["track_sha256"])
    PREP_DIR.mkdir(parents=True, exist_ok=True)
    path = PREP_DIR / "p_retrain.pt"
    file_sha = um.save(res.model, res.vocab, path, meta={"kind": "p_retrain", "seed": RETRAIN_SEED, "steps": res.steps,
                                                         "contract": CONTRACT})
    rec = {"contract": CONTRACT, "kind": "p_retrain", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "torch": torch.__version__, "threads": torch.get_num_threads(), "seed": RETRAIN_SEED, "steps": res.steps,
           "data": "m7u1 training episodes only (80), empty pool", "wall_s": round(time.perf_counter() - t0, 1),
           "train_wall_s": res.train.wall_s, "transitions": res.transitions, "vocab": res.vocab_dims,
           "track_sha256": res.track.digest(), "model_file": str(path.relative_to(REPO_ROOT)), "model_sha256": file_sha,
           "parameter_digest": res.parameter_digest,
           "differs_from_frozen": res.parameter_digest != gg.PIN["parameter_digest"], "log": res.train.log,
           "optimizers": list(OPTIMIZERS)}
    (PREP_DIR / "p_retrain.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("model_sha256", "parameter_digest", "vocab", "train_wall_s",
                                          "differs_from_frozen")}, indent=1))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["identity", "retrain"])
    a = ap.parse_args(argv)
    return cmd_identity() if a.cmd == "identity" else cmd_retrain()


if __name__ == "__main__":
    sys.exit(main())
