"""M9-g1 checkpoint evaluation: the jobs, the runner, the session engine, the aggregation and the pre-registered readings.

Plan (fixed before any native tick): docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md. Diagnostic only: frozen, pinned M9-g1 checkpoints are evaluated
read-only at three start states of the trunk; nothing learns, no optimizer exists (rl/m9_eval_policy), the registered M9-g1 outcome (NULL) is not changed.

Phases (one session; environment-injected like rl/m9_run, so the same engine runs on the real game and on the g1 synthetic stub world):

    open    the T_clear tables (words, per-tick chain digests, per-tick v3 digests) placed under <root>/lineages by an injected `prepare_tables`
            (real run: copied read-only from runs/m9_g1/lineages and checked against their registered sha256)
    p1      one fresh-process replay of T_clear from tick 0 (verification flags): exact, chain equal to the rd4 verifying replay's and to the table,
            v3 table equal, tick-0 record equal to the pin; any difference is INVALID
    eval    675 episodes (plan section 4) on a 10-slot pool; staging checks every prefix tick against the tables (rl/m9_worker, unchanged)
    verify  every clear replayed exactly from tick 0 (rl/m9_verify, unchanged)
    close   the M8 and M9-g1 trees against their D: increments, pins, write guard, metadata audit, leftover processes; aggregation and readings

Every JSON record goes through the M9 writer (task block and created_utc). The sticky rule is rl/m9_sticky's; action draws are keyed (rl/m9_eval_policy).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import shutil
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import m8_rd_cells as mcell
import m9_artifacts as A
import m9_contract as C
import m9_curriculum as CU
import m9_eval as E
import m9_lineages as L
import m9_run as RUN
import m9_sticky as S
import m9_train as T
import m9_vec as V
import m9_verify as VF

EVAL_ID = "m9_g1_ckeval_v1"
SCOPE = ("M9-g1 checkpoint evaluation: frozen, pinned M9-g1 checkpoints evaluated read-only at three start states of the trunk (stochastic sticky, "
         "stochastic unperturbed, deterministic unperturbed, paired open-loop tape); diagnostic only; no training; not a gate and not a change to the "
         "registered M9-g1 outcome (NULL)")
PLAN_DOC = "docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md"
RUN_NAME = "m9_g1_eval"
LINEAGE = C.TAPE_LINEAGE                                   # T_clear: every start point lies inside the shared prefix
SOURCE_RUN = "runs/m9_g1"

CHECKPOINTS: Tuple[Dict[str, Any], ...] = (
    {"name": "ckpt_000000000", "num_timesteps": 0, "path": "runs/m9_g1/training/checkpoints/ckpt_000000000/model.zip",
     "sha256": "16dc29c9cac05322d3562dbc3bc865e157b6ede49969c8b0c209aa91e61d5c77"},
    {"name": "ckpt_000409600", "num_timesteps": 409600, "path": "runs/m9_g1/training/checkpoints/ckpt_000409600/model.zip",
     "sha256": "bb6ce1ad101abad60078a34893f93ca855752169ea771b7ca93040a86ffacc45"},
    {"name": "ckpt_000614400", "num_timesteps": 614400, "path": "runs/m9_g1/training/checkpoints/ckpt_000614400/model.zip",
     "sha256": "049807de6e7f9cc719bfba3367a933f2baa0d1d8dd910f4b4087c8dcbfc86568"},
    {"name": "ckpt_001228800", "num_timesteps": 1228800, "path": "runs/m9_g1/training/checkpoints/ckpt_001228800/model.zip",
     "sha256": "21c7ba3635a84d9d6ec4da27ad0ed471d4feaec58892c0a7b8d852cb6ce8c22e"},
    {"name": "final", "num_timesteps": 1396160, "path": "runs/m9_g1/training/checkpoints/final/model.zip",
     "sha256": "c56cb8dc386f1cd8a3a3a5928e87f073d346ebf2805721caad14a5db3a4fc9e2"},
)
START_POINTS: Tuple[int, ...] = (2128, 2250, 2010)        # priority order (plan section 3)
N_STICKY = 20
N_UNPERTURBED = 20
N_DET = 1
N_TAPE = 20
PHASES: Tuple[str, ...] = ("p1", "eval", "verify", "close")
WALL_CAPS_S: Dict[str, float] = {"p1": 120.0, "eval": 1740.0, "verify": 420.0, "close": 120.0}
TICK_CAPS: Dict[str, int] = {"p1": 5_000, "eval": 2_500_000, "verify": 600_000, "close": 0}
TOTAL_TICK_CAP = 3_105_000
GLOBAL_CAP_S = 2700.0                                     # 45 minutes of session wall time
GRACE_S = 20.0
POOL_SPAWN_S = 15.0
N_SLOTS = 10
VERIFY_THREADS = 8
VERIFY_LAUNCH_MARGIN_S = 120.0
MAX_BATTLESHIP_PROCESSES = 10
MEMORY_CAPS_MB: Dict[str, float] = dict(C.MEMORY_CAPS_MB)
DECLINE_MIN_DIFF = 5
DECLINE_ALPHA = 0.05
H1_CONTRA_FINAL_DIFF = 3
H1_CONTRA_UNTRAINED_DIFF = 5
H3_LOW = 3
H3_HIGH = 6
STICKY_EFFECT = 5
H2_STOCHASTIC_MIN = 5
KEYS: Dict[str, str] = {"sticky": "m9|g1|sticky|ckeval:<tau>:<k>|<tick>", "action": "m9|g1eval|act|<mode>|<tau>|<k>|<tick>|<stick|button>"}


def sticky_label(tau: int, k: int) -> str:
    return f"ckeval:{int(tau)}:{int(k)}"


def short(name: str) -> str:
    return "final" if name == "final" else "c" + name.split("_")[-1][-7:]


def description() -> Dict[str, Any]:
    return {"evaluation": EVAL_ID, "scope": SCOPE, "plan": PLAN_DOC, "lineage": LINEAGE, "checkpoints": [dict(c) for c in CHECKPOINTS], "start_points": list(START_POINTS),
            "counts": {"sticky": N_STICKY, "unperturbed": N_UNPERTURBED, "deterministic": N_DET, "tape": N_TAPE}, "sticky_p": C.STICKY_P, "keys": dict(KEYS),
            "phases": list(PHASES), "wall_caps_s": dict(WALL_CAPS_S), "tick_caps": dict(TICK_CAPS), "total_tick_cap": TOTAL_TICK_CAP, "global_cap_s": GLOBAL_CAP_S,
            "n_slots": N_SLOTS, "verify_threads": VERIFY_THREADS, "verify_launch_margin_s": VERIFY_LAUNCH_MARGIN_S, "max_battleship_processes": MAX_BATTLESHIP_PROCESSES,
            "memory_caps_mb": dict(MEMORY_CAPS_MB),
            "readings": {"decline_min_diff": DECLINE_MIN_DIFF, "decline_alpha": DECLINE_ALPHA, "h1_contra_final_diff": H1_CONTRA_FINAL_DIFF,
                         "h1_contra_untrained_diff": H1_CONTRA_UNTRAINED_DIFF, "h3_low": H3_LOW, "h3_high": H3_HIGH, "sticky_effect": STICKY_EFFECT,
                         "h2_stochastic_min": H2_STOCHASTIC_MIN},
            "flags": {"eval": C.FLAGS_EVAL, "verify": C.FLAGS_VERIFY}, "horizon": C.HORIZON}


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def budget_projection(wall_caps: Mapping[str, float] = WALL_CAPS_S, global_cap: float = GLOBAL_CAP_S) -> Dict[str, Any]:
    pess = sum(wall_caps.values()) + 2 * POOL_SPAWN_S + GRACE_S * len(wall_caps)
    return {"phase_caps_s": dict(wall_caps), "pessimistic_total_s": pess, "global_cap_s": global_cap, "fits": pess <= global_cap, "slack_s": global_cap - pess,
            "expected_eval_s": "about 1,050 s at g1's measured evaluation rate (2,037 ticks/s) for about 2.1 M ticks"}


# -- configuration and jobs ------------------------------------------------------------------------------------------------------------


@dataclass
class EvalConfig:
    root: Path
    checkpoints: Sequence[Mapping[str, Any]] = CHECKPOINTS
    checkpoint_root: Path = Path(".")                      # checkpoint paths are relative to it (the repository)
    start_points: Sequence[int] = START_POINTS
    n_sticky: int = N_STICKY
    n_unperturbed: int = N_UNPERTURBED
    n_det: int = N_DET
    n_tape: int = N_TAPE
    wall_caps_s: Mapping[str, float] = field(default_factory=lambda: dict(WALL_CAPS_S))
    tick_caps: Mapping[str, int] = field(default_factory=lambda: dict(TICK_CAPS))
    total_tick_cap: int = TOTAL_TICK_CAP
    global_cap_s: float = GLOBAL_CAP_S
    memory_caps_mb: Mapping[str, float] = field(default_factory=lambda: dict(MEMORY_CAPS_MB))
    max_battleship_processes: int = MAX_BATTLESHIP_PROCESSES
    n_slots: int = N_SLOTS
    verify_threads: int = VERIFY_THREADS
    write_artifacts: bool = True

    @property
    def session_dir(self) -> Path:
        return self.root / "session"


def _start(i: int, tau: int) -> CU.Start:
    return CU.Start(int(i), "ckeval", int(tau), LINEAGE, int(tau) <= C.SHARED_PREFIX, -1)


def build_jobs(cfg: EvalConfig) -> List[V.StartJob]:
    """The plan's jobs in priority order: (1) sticky cells and the tape, point by point, interleaved by k across checkpoints; (2) unperturbed;
    (3) deterministic. Labels and keys never name the checkpoint (paired episodes)."""
    names = [str(c["name"]) for c in cfg.checkpoints]
    jobs: List[V.StartJob] = []

    def add(**kw: Any) -> None:
        jobs.append(V.StartJob(len(jobs), _start(len(jobs), kw.pop("tau_")), **kw))

    for tau in cfg.start_points:
        for k in range(max(cfg.n_sticky, cfg.n_tape)):
            if k < cfg.n_tape:
                add(tau_=tau, label=sticky_label(tau, k), driver="tape", kind="tape", tier=0, job_id=f"tape-{tau}-{k:02d}",
                    extra={"model": None, "mode": "sticky", "landing": tau, "k": k})
            if k < cfg.n_sticky:
                for n in names:
                    add(tau_=tau, label=sticky_label(tau, k), driver="policy", kind="sticky", tier=0, job_id=f"sticky-{short(n)}-{tau}-{k:02d}",
                        extra={"model": n, "mode": "sticky", "landing": tau, "k": k})
    for tau in cfg.start_points:
        for k in range(cfg.n_unperturbed):
            for n in names:
                add(tau_=tau, label=None, driver="policy", kind="unperturbed", tier=1, job_id=f"unperturbed-{short(n)}-{tau}-{k:02d}",
                    extra={"model": n, "mode": "unperturbed", "landing": tau, "k": k})
    for tau in cfg.start_points:
        for k in range(cfg.n_det):
            for n in names:
                add(tau_=tau, label=None, driver="policy", deterministic=True, kind="det", tier=2, job_id=f"det-{short(n)}-{tau}-{k:02d}",
                    extra={"model": n, "mode": None, "landing": tau, "k": k})
    return jobs


# -- recording and running -------------------------------------------------------------------------------------------------------------


class Recorder:
    """Every episode keeps its compact canonical record and a full M4-form artifact; every clear is kept for the verification."""

    def __init__(self, run_dir: Path, *, now: Callable[[], float] = time.monotonic, write_artifacts: bool = True):
        self.dir = Path(run_dir)
        self.now = now
        self.t0 = now()
        self.write_artifacts = write_artifacts
        self.records: List[Dict[str, Any]] = []
        self.clears: List[Dict[str, Any]] = []
        self.start_stats: Dict[str, Dict[str, float]] = {}

    def on_episode(self, ctx: V.EpisodeCtx, rec: Dict[str, Any]) -> None:
        j = ctx.job
        rec = dict(rec, phase="ckeval", evaluation=EVAL_ID, eval_kind=j.kind, model=j.extra.get("model"), mode=j.extra.get("mode"), landing=j.extra.get("landing"),
                   k=j.extra.get("k"), start_value=self.start_stats.get(j.job_id, {}).get("v"), start_entropy=self.start_stats.get(j.job_id, {}).get("h"),
                   t_wall_s=round(self.now() - self.t0, 2))
        self.records.append(rec)
        A.append_jsonl(self.dir / "episodes.jsonl", A.stamp(rec))
        if rec["clear"]:
            self.clears.append({"id": rec["episode"], "words": ctx.words(), "online": ctx.online(ctx.final), "tau": ctx.tau, "kind": j.kind, "tier": j.tier,
                                "model": j.extra.get("model")})
        if self.write_artifacts:
            rows = [(*mcell.TRIPLES[w], i) for i, w in enumerate(ctx.words())]
            A.write_episode_artifact(self.dir.parent / "artifacts", rec["episode"], rows,
                                     {"evaluation": EVAL_ID, "scope": SCOPE, "lineage": ctx.lineage, "tau": ctx.tau, "kind": j.kind, "model": j.extra.get("model"),
                                      "mode": j.extra.get("mode"), "k": j.extra.get("k"), "label": rec["label"], "driver": j.driver, "deterministic": j.deterministic,
                                      "sticky_mask_hex": rec["sticky_mask_hex"], "sampled_hex": rec["sampled_hex"], "native_action_digest": rec["native_action_digest"],
                                      "chain_final": rec["chain_final"], "prefix_sha256": rec["prefix_sha256"], "prefix_words": ctx.tau},
                                     status="clear" if rec["clear"] else rec["end_reason"],
                                     terminal={"end_reason": rec["end_reason"], "ticks": rec["ticks"], "targets_broken": rec["t"], "completion": rec.get("result") or {}},
                                     labels={"phase": "ckeval", "evaluation": EVAL_ID, "m9_kind": j.kind, "model": j.extra.get("model")}, preservation_reason="manual")


class CkRunner(E.EvalRunner):
    """g1's free-running evaluation runner with the decision replaced: the tape by tick index, a pinned policy by keyed sampling or argmax."""

    def __init__(self, arena: V.Arena, tables: Mapping[str, Any], recorder: Recorder, policies: Mapping[str, Any], *, flatten: Callable[[Mapping[str, Any]], Any],
                 now: Callable[[], float] = time.monotonic):
        super().__init__(arena, tables, recorder, models={}, now=now)  # type: ignore[arg-type]
        self.policies = dict(policies)
        self.flatten = flatten

    def _decide(self, ctxs: Sequence[V.EpisodeCtx]) -> List[int]:
        out: List[int] = []
        for c in ctxs:
            j = c.job
            if j.driver == "tape":
                out.append(self.tape.word(c.tick))
                continue
            if j.driver != "policy":
                raise RuntimeError(f"unexpected driver {j.driver!r}")
            pol = self.policies[str(j.extra["model"])]
            flat = self.flatten(c.obs)
            if not c.sub:                                           # the handover observation: the policy's value and entropy there (descriptive)
                self.rec.start_stats[j.job_id] = {"v": round(pol.value(flat), 4), "h": round(pol.entropy(flat), 4)}   # type: ignore[attr-defined]
            if j.deterministic:
                out.append(pol.argmax_word(flat))
            else:
                out.append(pol.sample_word(flat, str(j.extra["mode"]), int(c.tau), int(j.extra["k"]), int(c.tick)))
        return out


# -- aggregation and readings ------------------------------------------------------------------------------------------------------------


def sign_test_p(b: int, d: int) -> float:
    """One-sided exact sign test: P(Bin(b + d, 1/2) >= b)."""
    n = b + d
    if n == 0:
        return 1.0
    return sum(math.comb(n, i) for i in range(b, n + 1)) / 2.0 ** n


def aggregate(records: Sequence[Mapping[str, Any]], verified: Mapping[str, bool], cfg: EvalConfig) -> Dict[str, Any]:
    """cells[kind][model][tau] = {n, planned, clears (claimed), verified, unverified, falls, horizon, policy_ticks_mean, by_k}; tape[tau] likewise."""
    names = [str(c["name"]) for c in cfg.checkpoints]
    planned = {"sticky": cfg.n_sticky, "unperturbed": cfg.n_unperturbed, "det": cfg.n_det, "tape": cfg.n_tape}
    cells: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = {k: {n: {} for n in names} for k in ("sticky", "unperturbed", "det")}
    tape: Dict[int, Dict[str, Any]] = {}

    def blank(kind: str) -> Dict[str, Any]:
        return {"n": 0, "planned": planned[kind], "clears": 0, "verified": 0, "unverified": 0, "falls": 0, "horizon": 0, "policy_ticks_sum": 0, "by_k": {},
                "start_value": None, "start_entropy": None}

    for r in records:
        kind = r["eval_kind"]
        tau = int(r["landing"])
        if kind == "tape":
            x = tape.setdefault(tau, blank("tape"))
        else:
            x = cells[kind][str(r["model"])].setdefault(tau, blank(kind))
        clear = bool(r["clear"])
        ok = clear and bool(verified.get(r["episode"], False))
        x["n"] += 1
        x["clears"] += int(clear)
        x["verified"] += int(ok)
        x["unverified"] += int(clear and not ok)
        x["falls"] += int(r["end_reason"] == "fall")
        x["horizon"] += int(r["end_reason"] == "horizon")
        x["policy_ticks_sum"] += int(r["policy_ticks"])
        x["by_k"][int(r["k"])] = "V" if ok else ("u" if clear else r["end_reason"][0])
        if r.get("start_value") is not None:
            x["start_value"], x["start_entropy"] = r["start_value"], r["start_entropy"]
    for d in list(cells.values()) + [{"tape": tape}]:
        for per in d.values():
            for x in per.values():
                x["complete"] = x["n"] == x["planned"]
                x["policy_ticks_mean"] = round(x["policy_ticks_sum"] / x["n"], 1) if x["n"] else None
                del x["policy_ticks_sum"]
    return {"cells": cells, "tape": tape, "checkpoints": names, "start_points": list(cfg.start_points)}


def _c(agg: Mapping[str, Any], name: str, tau: int, kind: str = "sticky") -> Optional[Mapping[str, Any]]:
    return agg["cells"][kind].get(name, {}).get(tau)


def paired_decline(agg: Mapping[str, Any], a: str, b: str, tau: int) -> Dict[str, Any]:
    """Decline of checkpoint a against b at tau (sticky cells): c(a) - c(b) >= 5 and the one-sided exact sign test on the k-paired episodes <= 0.05.
    Counts are verified clears; a pair is used only when both episodes exist; `decidable` is False when an unverified clear could change the reading."""
    xa, xb = _c(agg, a, tau), _c(agg, b, tau)
    if not xa or not xb:
        return {"a": a, "b": b, "tau": tau, "available": False, "decline": None, "decidable": False}
    ka, kb = xa["by_k"], xb["by_k"]
    common = sorted(set(ka) & set(kb))
    bb = sum(1 for k in common if ka[k] == "V" and kb[k] != "V")
    dd = sum(1 for k in common if kb[k] == "V" and ka[k] != "V")
    diff = xa["verified"] - xb["verified"]
    p = sign_test_p(bb, dd)
    decline = diff >= DECLINE_MIN_DIFF and p <= DECLINE_ALPHA
    unv = xa["unverified"] + xb["unverified"]
    complete = xa["complete"] and xb["complete"]
    return {"a": a, "b": b, "tau": tau, "available": True, "c_a": xa["verified"], "c_b": xb["verified"], "diff": diff, "b_only_a": bb, "b_only_b": dd,
            "p_one_sided": round(p, 5), "decline": decline, "complete": complete, "unverified": unv, "decidable": complete and unv == 0}


ROLES = ("untrained", "peak", "stall", "last_move", "final")


def roles(cfg: EvalConfig) -> Dict[str, str]:
    """The plan's roles in checkpoint order: untrained, peak (end of the fast phase), stall, last move, final."""
    names = [str(c["name"]) for c in cfg.checkpoints]
    if len(names) != len(ROLES):
        raise ValueError(f"{len(names)} checkpoints for the {len(ROLES)} roles")
    return dict(zip(ROLES, names))


def readings(agg: Mapping[str, Any], names: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """The plan's pre-registered readings (section 6). `names` maps the roles (untrained, peak, stall, last_move, final) to checkpoint names."""
    nm = dict(names or {"untrained": "ckpt_000000000", "peak": "ckpt_000409600", "stall": "ckpt_000614400", "last_move": "ckpt_001228800", "final": "final"})
    out: Dict[str, Any] = {"roles": nm}
    late = [t for t in (2128, 2250) if t in agg["start_points"]]
    # H1
    declines = [paired_decline(agg, nm[e], nm["final"], t) for t in late for e in ("peak", "stall")]
    interference = [paired_decline(agg, nm["untrained"], nm["final"], t) for t in late]
    trained = [nm[r] for r in ("peak", "stall", "last_move", "final")]
    contra_rows = []
    for t in late:
        f = _c(agg, nm["final"], t)
        u = _c(agg, nm["untrained"], t)
        row = {"tau": t, "available": bool(f and u)}
        if f and u:
            vals = {n: (_c(agg, n, t) or {}).get("verified") for n in trained}
            row.update({"verified": vals, "untrained": u["verified"],
                        "max_over_final": max((v - f["verified"]) for v in vals.values() if v is not None),
                        "max_over_untrained": max((v - u["verified"]) for v in vals.values() if v is not None),
                        "complete": all((_c(agg, n, t) or {}).get("complete") for n in trained + [nm["untrained"]]),
                        "unverified": sum((_c(agg, n, t) or {}).get("unverified", 0) for n in trained + [nm["untrained"]])})
        contra_rows.append(row)
    if any(d["decline"] and d["decidable"] for d in declines):
        h1 = "supported_decay"
    elif late and all(r["available"] and r["complete"] and r["unverified"] == 0 and r["max_over_final"] < H1_CONTRA_FINAL_DIFF
                      and r["max_over_untrained"] < H1_CONTRA_UNTRAINED_DIFF for r in contra_rows):
        h1 = "contradicted_never_learned"
    elif any(d["decline"] and not d["decidable"] for d in declines):
        h1 = "undecided_incomplete"
    else:
        h1 = "undecided"
    decayed = sorted({d["tau"] for d in declines if d["decline"] and d["decidable"]})
    out["H1"] = {"reading": h1, "decayed_points": decayed,
                 "interference": any(d["decline"] and d["decidable"] for d in interference if d["tau"] in decayed) if h1 == "supported_decay" else None,
                 "declines": declines, "untrained_vs_final": interference, "contradiction_rows": contra_rows}
    # H3 (move 16 at 2,010; move 9 at 2,128)
    h3: Dict[str, Any] = {}
    if 2010 in agg["start_points"]:
        a, b = _c(agg, nm["last_move"], 2010), _c(agg, nm["stall"], 2010)
        if a and b and a["complete"] and b["complete"]:
            lo_a, hi_a = a["verified"], a["verified"] + a["unverified"]
            lo_b, hi_b = b["verified"], b["verified"] + b["unverified"]
            if hi_a <= H3_LOW and hi_b <= H3_LOW:
                r16 = "supported"
            elif lo_a >= H3_HIGH or lo_b >= H3_HIGH:
                r16 = "contradicted"
            else:
                r16 = "undecided_incomplete" if (a["unverified"] + b["unverified"]) else "undecided"
            h3["move16"] = {"reading": r16, "last_move": a["verified"], "stall": b["verified"], "unverified": a["unverified"] + b["unverified"]}
        else:
            h3["move16"] = {"reading": "incomplete"}
    if 2128 in agg["start_points"]:
        p = _c(agg, nm["peak"], 2128)
        if p and p["complete"]:
            lo, hi = p["verified"], p["verified"] + p["unverified"]
            h3["move9"] = {"reading": "competence_real" if lo >= H3_HIGH else ("not_backed" if hi <= H3_LOW else ("undecided_incomplete" if p["unverified"] else "undecided")),
                           "peak": p["verified"],
                           "unverified": p["unverified"]}
        else:
            h3["move9"] = {"reading": "incomplete"}
    out["H3"] = h3
    # H2 premise and stickiness (reported); lower bound = verified clears, upper bound = verified + unverified (a reading an unverified clear could change is
    # reported as undecided_incomplete)
    def lo_hi(x: Optional[Mapping[str, Any]]) -> Tuple[int, int]:
        return (0, 0) if not x else (int(x["verified"]), int(x["verified"]) + int(x["unverified"]))

    det_clear_where_stoch_fails: List[Dict[str, Any]] = []
    det_fail_where_stoch_clears: List[Dict[str, Any]] = []
    det_clear_where_sticky_ge5: List[Dict[str, Any]] = []
    det_maybe: List[Dict[str, Any]] = []
    sticky_effects: List[Dict[str, Any]] = []
    sticky_maybe: List[Dict[str, Any]] = []
    for n in agg["checkpoints"]:
        for t in agg["start_points"]:
            sx, dx, ux = _c(agg, n, t, "sticky"), _c(agg, n, t, "det"), _c(agg, n, t, "unperturbed")
            (s_lo, s_hi), (d_lo, d_hi), (u_lo, u_hi) = lo_hi(sx), lo_hi(dx), lo_hi(ux)
            if sx and dx and dx["n"]:
                if d_lo > 0 and s_hi <= 1:
                    det_clear_where_stoch_fails.append({"model": n, "tau": t})
                if d_lo > 0 and s_lo >= H2_STOCHASTIC_MIN:
                    det_clear_where_sticky_ge5.append({"model": n, "tau": t})
                elif d_hi > 0 and s_hi >= H2_STOCHASTIC_MIN:
                    det_maybe.append({"model": n, "tau": t})
                if d_hi == 0 and s_lo >= H2_STOCHASTIC_MIN:
                    det_fail_where_stoch_clears.append({"model": n, "tau": t, "sticky": s_lo})
            if sx and ux and sx["complete"] and ux["complete"]:
                if u_lo - s_hi >= STICKY_EFFECT:
                    sticky_effects.append({"model": n, "tau": t, "unperturbed": u_lo, "sticky": s_lo})
                elif u_hi - s_lo >= STICKY_EFFECT:
                    sticky_maybe.append({"model": n, "tau": t, "unperturbed": [u_lo, u_hi], "sticky": [s_lo, s_hi]})
    det_any = [(n, t) for n in agg["checkpoints"] for t in agg["start_points"] if (_c(agg, n, t, "det") or {}).get("verified")]
    if det_clear_where_sticky_ge5:
        premise = "contradicted"
    elif det_maybe:
        premise = "undecided_incomplete"
    elif det_fail_where_stoch_clears:
        premise = "holds"
    else:
        premise = "vacuous (no cell with >= %d sticky clears)" % H2_STOCHASTIC_MIN
    out["H2"] = {"premise_argmax_does_not_clear": premise, "deterministic_clears": [{"model": n, "tau": t} for n, t in det_any],
                 "det_clears_where_sticky_ge5": det_clear_where_sticky_ge5, "det_fails_where_sticky_ge5": det_fail_where_stoch_clears,
                 "det_clears_where_sticky_le1": det_clear_where_stoch_fails, "undecided_cells": det_maybe,
                 "note": "the NULL's action-mode question is decided by the g1 records (no mismatch)"}
    out["stickiness"] = sticky_effects
    out["stickiness_undecided"] = sticky_maybe
    out["tape_margin"] = {str(t): {n: ((_c(agg, n, t) or {}).get("verified", 0) - agg["tape"].get(t, {}).get("verified", 0)) for n in agg["checkpoints"]}
                          for t in agg["start_points"]}
    return out


# -- the session ---------------------------------------------------------------------------------------------------------------------------


class EvalSession:
    def __init__(self, cfg: EvalConfig, env: RUN.RunEnv, *, prepare_tables: Callable[[Path], Dict[str, Any]], load_policies: Callable[[], Mapping[str, Any]],
                 flatten: Callable[[Mapping[str, Any]], Any], earlier_trees: Optional[Callable[[], Mapping[str, Any]]] = None):
        self.cfg, self.env = cfg, env
        self.log = env.log
        self.clock = RUN.Clock(env, cfg)                   # type: ignore[arg-type]
        self.dir = cfg.session_dir
        self.root = cfg.root
        self.prepare_tables, self.load_policies, self.flatten = prepare_tables, load_policies, flatten
        self.earlier_trees = earlier_trees
        self.invalid: List[str] = []
        self.phases: Dict[str, bool] = {}
        self.notes: Dict[str, Any] = {}
        self.tables: Dict[str, L.Tables] = {}
        self.policies: Dict[str, Any] = {}
        self.records: List[Dict[str, Any]] = []
        self.clears: List[Dict[str, Any]] = []
        self.verified: Dict[str, bool] = {}
        self.stop: Optional[Dict[str, Any]] = None
        self.ticks: Dict[str, int] = {}

    def put(self, name: str, obj: Mapping[str, Any]) -> None:
        A.write_json(self.dir / f"{name}.json", A.stamp(dict(obj, scope=SCOPE, evaluation=EVAL_ID)))

    def save_state(self, **extra: Any) -> None:
        try:
            A.write_json(self.dir / "state.json", A.stamp(dict({"utc": A.utc(), "phase": self.clock.phase, "phases": dict(self.phases), "clock": self.clock.to_json(),
                                                                "invalid": list(self.invalid), "scope": SCOPE, "ticks": dict(self.ticks)}, **extra)))
        except (OSError, A.ArtifactError):
            pass

    @contextlib.contextmanager
    def pool(self, tag: str, flags: Mapping[str, str]) -> Iterator[Any]:
        pool = self.env.make_pool(tag, flags)
        try:
            yield pool
        finally:
            try:
                pool.stop()
            except Exception:                                          # noqa: BLE001
                pass

    def _total_ticks_check(self, extra: int = 0) -> None:
        if sum(self.ticks.values()) + extra > self.cfg.total_tick_cap:
            raise V.CapStop(f"the session's native-tick cap {self.cfg.total_tick_cap} would be exceeded", valid=False)

    def run(self) -> Dict[str, Any]:
        self.dir.mkdir(parents=True, exist_ok=True)
        steps: List[Tuple[str, Callable[[], bool]]] = [("p1", self.p1), ("eval", self.evaluate), ("verify", self.verify)]
        try:
            self.policies = dict(self.load_policies())
            self.notes["policies"] = {n: getattr(p, "sha256", None) for n, p in self.policies.items()}
            for name, fn in steps:
                self.clock.begin(name)
                self.log(f"phase {name} begins (session clock {self.clock.elapsed():.0f} s)")
                self.save_state()
                ok = fn()
                self.clock.end()
                self.phases[name] = bool(ok)
                self.save_state()
                if not ok and name == "p1":
                    self.stop = {"phase": name, "reason": "P1 did not pass", "valid": False}
                    break
        except V.IntegrityStop as exc:
            self.invalid.append(f"{exc.why}: {json.dumps(exc.detail, default=str)[:400]}")
            self.stop = {"phase": self.clock.phase, "reason": f"INTEGRITY: {exc.why}", "valid": False}
        except V.CapStop as exc:
            self.stop = {"phase": self.clock.phase, "reason": exc.reason, "valid": exc.valid}
            self.log(f"stop in phase {self.clock.phase}: {exc.reason}")
        except Exception as exc:                                       # noqa: BLE001 - a software error: recorded, INCOMPLETE, never silent
            self.stop = {"phase": self.clock.phase, "reason": f"software error: {type(exc).__name__}: {exc}", "valid": False, "trace": traceback.format_exc()[-3000:]}
            self.log(f"software error in phase {self.clock.phase}: {exc}")
        finally:
            self.clock.end()
        return self.finish()

    # -- open + P1 --

    def p1(self) -> bool:
        cfg, env = self.cfg, self.env
        prep = dict(self.prepare_tables(self.root / "lineages"))
        self.put("tables", prep)
        if not prep.get("ok"):
            raise V.IntegrityStop("the copied lineage tables differ from their registration", prep)
        self.tables = L.load_all_tables(self.root / "lineages", list(prep["lineages"]))
        ln = env.lineages[LINEAGE]
        tb = self.tables[LINEAGE]
        if tb.words != bytes(ln.words):
            raise V.IntegrityStop("the table's words differ from the registered lineage", {"lineage": LINEAGE})
        self._total_ticks_check(len(ln.words))
        if len(ln.words) > cfg.tick_caps["p1"]:
            raise V.CapStop(f"P1 needs {len(ln.words)} ticks, cap {cfg.tick_caps['p1']}", valid=False)
        tr = env.replay(bytes(ln.words), f"p1-{LINEAGE}", 0)
        self.ticks["p1"] = len(tr.get("steps") or [])
        self.clock.check()
        problems: List[str] = []
        ev = VF.evaluate_trace(tr, bytes(ln.words), env.analyse, expect_clear=True)
        problems += list(ev["problems"])
        if (ev["completion_time_passed"], ev["completion_input_tick"]) != (ln.completion_time_passed, ln.completion_input_tick):
            problems.append("completion clocks differ from the registered ones")
        chain = VF.trace_chain(tr["initial"], tr["steps"])
        ref = VF.trace_chain(env.route_traces[LINEAGE]["initial"], env.route_traces[LINEAGE]["steps"])
        if chain != ref:
            problems.append("the per-tick chain differs from the rd4 verifying replay's")
        if chain != tb.chain:
            problems.append("the per-tick chain differs from the copied table")
        _ch, v3 = L.build_tables(tr["initial"], tr["steps"], env.pipeline_cls)
        if v3 != tb.v3:
            first = next((i for i, (a, b) in enumerate(zip(v3, tb.v3)) if a != b), min(len(v3), len(tb.v3)))
            problems.append(f"the v3 table differs from the copied table (first difference at tick {first})")
        if mcell.record_digest(mcell.tick0_record(tr["initial"])).hex() != env.pin_tick0["digest"]:
            problems.append("the tick-0 record differs from the archive pin")
        ok = not problems
        self.put("p1", {"ok": ok, "problems": problems, "ticks": self.ticks["p1"], "tick_cap": cfg.tick_caps["p1"], "native_action_digest": ev.get("native_action_digest"),
                        "completion_time_passed": ev["completion_time_passed"], "completion_input_tick": ev["completion_input_tick"], "chain_final": chain[-1].hex(),
                        "tables": prep})
        if not ok:
            raise V.IntegrityStop("P1: the T_clear replay is not exact or its tables differ", {"problems": problems[:5]})
        return ok

    # -- evaluation --

    def evaluate(self) -> bool:
        cfg, env = self.cfg, self.env
        jobs = build_jobs(cfg)
        self.notes["planned"] = len(jobs)
        cap = min(int(cfg.tick_caps["eval"]), cfg.total_tick_cap - sum(self.ticks.values()))
        budget = V.TickBudget(cap)
        rec = Recorder(self.root / "eval", now=env.now, write_artifacts=cfg.write_artifacts)
        with self.pool("eval", C.FLAGS_EVAL) as pool:
            arena = V.Arena(pool, self.tables, T.ListSource(jobs), budget, now=env.now, guard=self.clock.check, log=env.log)
            runner = CkRunner(arena, self.tables, rec, self.policies, flatten=self.flatten, now=env.now)
            try:
                res = runner.run()
            finally:                                              # what was recorded survives an integrity or software stop
                self.records, self.clears = rec.records, rec.clears
                self.ticks["eval"] = int(budget.consumed)
            arena.close_unfinished()
        complete = len(rec.records) == len(jobs)
        self.notes["eval"] = {"planned": len(jobs), "completed": len(rec.records), "stop": res["stop"]}
        self.put("eval_run", {"run": res, "planned": len(jobs), "completed": len(rec.records), "complete": complete, "tick_cap": cap,
                              "decisions": {n: getattr(p, "decisions", None) for n, p in self.policies.items()}})
        if res["stop"] is not None and not res["stop"]["valid"]:
            raise V.CapStop(f"evaluation stopped early: {res['stop']['reason']}", valid=False)
        return True

    # -- verification --

    def verify(self) -> bool:
        cfg, env = self.cfg, self.env
        tier = {"sticky": 0, "tape": 0, "unperturbed": 1, "det": 2}
        jobs = [VF.VerifyJob(c["id"], c["words"], c["online"], tau=c["tau"], tier=tier.get(c["kind"], 3), group="eval", meta={"kind": c["kind"], "model": c.get("model")})
                for c in self.clears]
        out_dir = self.root / "verification"

        def on_result(job: VF.VerifyJob, res: Mapping[str, Any]) -> None:
            self.verified[job.id] = bool(res["exact"])
            A.append_jsonl(out_dir / "replays.jsonl", A.stamp({k: v for k, v in res.items() if k != "breaks"} | {"breaks_n": len(res["breaks"]), "kind": job.meta.get("kind"),
                                                                                                                 "model": job.meta.get("model")}))

        cap = min(int(cfg.tick_caps["verify"]), cfg.total_tick_cap - sum(self.ticks.values()))
        # launches stop VERIFY_LAUNCH_MARGIN_S before the phase's wall cap, so the replays in flight finish inside it (the clock's cap is a stop)
        rep = VF.run_plan(jobs, env.replay, env.analyse, tick_cap=cap, wall_cap_s=max(1.0, float(cfg.wall_caps_s["verify"]) - VERIFY_LAUNCH_MARGIN_S),
                          threads=cfg.verify_threads, now=env.now, on_result=on_result, check=self.clock.check)
        self.ticks["verify"] = int(rep["ticks"])
        self.notes["verification"] = {k: v for k, v in rep.items() if k != "results"}
        self.put("verification", {k: v for k, v in rep.items() if k != "results"} | {"planned": len(jobs), "tick_cap": cap})
        if rep["inexact"]:
            self.invalid.append(f"an exact replay of a counted clear failed: {rep['inexact'][:5]}")
        if rep["errors"]:
            self.notes["verification_errors"] = rep["errors"][:5]
        return not rep["inexact"]

    # -- close and outcome --

    def finish(self) -> Dict[str, Any]:
        env = self.env
        close: Dict[str, Any] = {"phase": "close"}
        self.clock.phase = None
        t_close = env.now()
        try:
            if self.earlier_trees is not None:
                et = dict(self.earlier_trees())
                close["earlier_trees"] = et
                if not et.get("ok"):
                    self.invalid.append(f"an earlier tree no longer equals its D: increment: {et.get('problems')}")
            if env.identity_now is not None:
                idn = dict(env.identity_now())
                close["identity"] = idn
                diffs = {k: (idn.get(k), v) for k, v in dict(env.pins).items() if k in idn and idn.get(k) != v}
                if diffs:
                    self.invalid.append(f"pin drift at the close: {sorted(diffs)}")
            v = list(env.provenance_violations())
            close["provenance_violations"] = v
            if v:
                self.invalid.append(f"provenance or write-guard violations: {v[:3]}")
            aud = A.audit_tree(self.root, skip_dirs=("workers", "vw"))
            close["metadata_audit"] = {"files": aud["files"], "jsonl_lines": aud["jsonl_lines"], "failures": aud["failures"][:10], "ok": aud["ok"]}
            if not aud["ok"]:
                self.invalid.append(f"artifacts without the task block or created_utc: {aud['failures'][:3]}")
            if env.leftover_processes is not None:
                close["leftover_battleship_processes"] = env.leftover_processes()
        except Exception as exc:                                       # noqa: BLE001
            close["error"] = f"{type(exc).__name__}: {exc}"
            self.invalid.append(f"a close check failed to run: {close['error']}")
        agg = aggregate(self.records, self.verified, self.cfg)
        rd = readings(agg, roles(self.cfg))
        incomplete_cells = [f"{k}/{n}/{t}" for k, per in agg["cells"].items() for n, d in per.items() for t, x in d.items() if not x["complete"]]
        incomplete_cells += [f"tape/{t}" for t, x in agg["tape"].items() if not x["complete"]]
        missing_tape = [f"tape/{t}" for t in agg["start_points"] if t not in agg["tape"] and self.cfg.n_tape > 0]
        ver = self.notes.get("verification") or {}
        unverified_clears = list(ver.get("skipped_unverified") or []) + [e.get("id") for e in (ver.get("errors") or [])]
        missing_cells = [f"{k}/{n}/{t}" for k, per in agg["cells"].items() for n in agg["checkpoints"] for t in agg["start_points"]
                         if t not in per.get(n, {}) and (k != "det" or self.cfg.n_det > 0)] + missing_tape
        if self.invalid:
            status = "INVALID"
        elif self.stop is not None and not self.stop.get("valid"):
            status = "INCOMPLETE"
        elif not self.phases.get("p1") or not self.phases.get("eval") or not self.phases.get("verify"):
            status = "INCOMPLETE"
        elif incomplete_cells or missing_cells or unverified_clears:
            status = "PARTIAL"
        else:
            status = "COMPLETE"
        out = {"status": status, "stop": self.stop, "invalid": list(self.invalid), "phases": dict(self.phases), "ticks": dict(self.ticks), "total_ticks": sum(self.ticks.values()),
               "total_tick_cap": self.cfg.total_tick_cap, "clock": self.clock.to_json(), "incomplete_cells": incomplete_cells, "missing_cells": missing_cells,
               "unverified_clears": unverified_clears,
               "verification": self.notes.get("verification"), "aggregate": agg, "readings": rd, "notes": {k: v for k, v in self.notes.items() if k != "verification"}}
        close["wall_s"] = round(env.now() - t_close, 2)
        close["session_elapsed_s_at_close_end"] = round(self.clock.elapsed(), 1)
        self.put("close", close)
        self.put("outcome", out)
        self.save_state(done=True, status=status)
        return out


# -- the table source of the real run ----------------------------------------------------------------------------------------------------


def copy_registered_tables(source_dir: Path, dest_dir: Path, names: Sequence[str] = (LINEAGE,)) -> Dict[str, Any]:
    """Copy words.bin / chain.bin / v3.bin of each lineage from the g1 run (read only) and check each copy's sha256 against the registration's
    table_sha256 and against the source bytes. Nothing is written under the source."""
    out: Dict[str, Any] = {"lineages": list(names), "source": str(source_dir), "files": {}, "problems": []}
    for n in names:
        reg = json.loads((Path(source_dir) / n / "registration.json").read_text(encoding="utf-8"))
        want = dict(reg.get("table_sha256") or {})
        d = Path(dest_dir) / n
        d.mkdir(parents=True, exist_ok=False)
        for f in L.TABLE_FILES:
            src = Path(source_dir) / n / f
            b = src.read_bytes()
            h_src = hashlib.sha256(b).hexdigest()
            (d / f).write_bytes(b)
            h_dst = hashlib.sha256((d / f).read_bytes()).hexdigest()
            out["files"][f"{n}/{f}"] = {"sha256": h_dst, "registered": want.get(f)}
            if not (h_src == h_dst == want.get(f)):
                out["problems"].append(f"{n}/{f}: source {h_src[:16]} copy {h_dst[:16]} registered {str(want.get(f))[:16]}")
        out["registration_sha256"] = {n: hashlib.sha256((Path(source_dir) / n / "registration.json").read_bytes()).hexdigest()}
    out["ok"] = not out["problems"]
    return out


def contract_description() -> Dict[str, Any]:
    return {"evaluation": EVAL_ID, "digest": contract_digest(), "plan": PLAN_DOC, "scope": SCOPE}
