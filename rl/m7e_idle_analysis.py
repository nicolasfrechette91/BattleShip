#!/usr/bin/env python3
"""M7e Phase A: reproducible idle diagnosis of the M7d `btt_reward_v2` policies.

Read-only over the stored M7d evidence. This module never trains, never
mutates an action, never touches native RNG state and never writes inside
`runs/m7d/`. It answers one question: what does "idling" actually mean in the
M7d v2 policies, and is unchanged longer v2 training justified?

Evidence sources, all produced by M7d and left untouched:

  runs/m7d/_eval/<run>/<stage>/<mode>/evaluation.json   per-episode evaluation rows
  runs/m7d/<run>/metrics/episodes.jsonl                 per-episode training rows
  <artifact_dir>/actions.jsonl                          canonical native actions
  <artifact_dir>/metadata.json                          initial and final observation

Three evidence classes are kept apart everywhere in the output:

  measured    computed directly from a stored field
  inferred    derived from measured quantities under a stated assumption
  unknown     not answerable from what M7d stored

Commands
--------
    python rl/m7e_idle_analysis.py --test          self-tests of the metric definitions
    python rl/m7e_idle_analysis.py                 full diagnosis -> docs/rl_v2_idle_diagnosis_m7e.{md,json}
    python rl/m7e_idle_analysis.py --no-actions    skip the action-stream pass (fast)
    python rl/m7e_idle_analysis.py --replay-plan   print the Phase A4 replay selection only
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX_ROOT = REPO_ROOT / "runs" / "m7d"
EVAL_ROOT = MATRIX_ROOT / "_eval"
DOC_MD = REPO_ROOT / "docs" / "rl_v2_idle_diagnosis_m7e.md"
DOC_JSON = REPO_ROOT / "docs" / "rl_v2_idle_diagnosis_m7e.json"

SCHEMA = "m7e_idle_diagnosis_v1"
HORIZON = 3600           # frozen M7d episode horizon, native ticks
TARGETS_TOTAL = 10
SEEDS: Tuple[int, ...] = (0, 1, 2)
CONTRACTS: Tuple[str, ...] = ("v1", "v2")

# M7d's frozen idle definition, reused unchanged so the two reports compare.
M7D_IDLE_TAIL_TICKS = 1800

# New M7e thresholds. Every one of them is a reporting cut, never a decision
# rule: the tables below always carry the underlying continuous quantity too.
EARLY_TARGET_TICK = 600          # "early progress" = first target inside the first 600 ticks
LONG_RUN_TICKS = 60              # a "long repeated-action run" is >= 60 identical consecutive actions
SHORT_RUN_TICKS = 30
CENSUS_WINDOWS: Tuple[int, ...] = (600, 900, 1200, 1800, 2400, 3000, 3600)

# Track 1 decoding tables (frozen `btt_s9_b8_v1`; imported lazily in decode_action
# so the metric functions stay importable without gymnasium present).
STICK_NAMES: Tuple[str, ...] = (
    "neutral", "right", "up-right", "up", "up-left", "left", "down-left", "down", "down-right",
)
BUTTON_NAMES: Tuple[str, ...] = ("none", "A", "B", "C-up", "C-left", "L", "R", "Z")
STICK_TABLE: Tuple[Tuple[int, int], ...] = (
    (0, 0), (80, 0), (80, 80), (0, 80), (-80, 80), (-80, 0), (-80, -80), (0, -80), (80, -80),
)
BUTTON_WORDS: Tuple[int, ...] = (0x0000, 0x8000, 0x4000, 0x0008, 0x0002, 0x0020, 0x0010, 0x2000)
_STICK_INDEX: Dict[Tuple[int, int], int] = {xy: i for i, xy in enumerate(STICK_TABLE)}
_BUTTON_INDEX: Dict[int, int] = {w: i for i, w in enumerate(BUTTON_WORDS)}


# -- metric definitions -------------------------------------------------------------------------
#
# One episode e is a stored row with:
#   L(e)   length in native ticks (`length` on an evaluation row, `steps` on a training row)
#   T(e)   targets broken
#   B(e)   the ordered target-break ticks (b_1 < ... < b_T), field `target_break_ticks`
#   end(e) end reason in {clear, fall, horizon, lifecycle_failure}
#
# Every definition below is stated in those four quantities alone.


def tail_ticks(length: int, breaks: Sequence[int]) -> int:
    """tail(e) = L - (b_T + 1) when T >= 1, else L.

    Ticks elapsed after the last target break. With no break the whole episode
    is tail. This is M7d's definition, reused unchanged."""
    if breaks:
        return int(length) - (int(max(breaks)) + 1)
    return int(length)


def tail_fraction(length: int, breaks: Sequence[int]) -> Optional[float]:
    """tail_frac(e) = tail(e) / L(e), in [0, 1]. Undefined for L = 0.

    The fraction of the episode spent with no new target after the final one."""
    if length <= 0:
        return None
    return tail_ticks(length, breaks) / float(length)


def m7d_idle(end_reason: str, length: int, breaks: Sequence[int]) -> bool:
    """M7d's `idle` flag: end = horizon and tail(e) >= 1800.

    Kept bit-identical to `m7d_analysis.episode_metrics` so the M7e tables can
    be read against the M7d report without a translation step."""
    return end_reason == "horizon" and tail_ticks(length, breaks) >= M7D_IDLE_TAIL_TICKS


def target_gaps(breaks: Sequence[int]) -> List[int]:
    """gap_k(e) = b_{k+1} - b_k for k = 1..T-1. Empty when T <= 1."""
    b = sorted(int(x) for x in breaks)
    return [b[i + 1] - b[i] for i in range(len(b) - 1)]


def opening_gap(breaks: Sequence[int]) -> Optional[int]:
    """b_1, the first-target tick. None when T = 0."""
    return int(min(breaks)) if breaks else None


def targets_per_1000(length: int, targets: int) -> Optional[float]:
    """tpk(e) = 1000 * T(e) / L(e). Density of progress per tick actually played."""
    if length <= 0:
        return None
    return 1000.0 * int(targets) / float(length)


def targets_before(breaks: Sequence[int], window: int) -> int:
    """T_W(e) = |{b in B(e) : b < W}| -- targets broken strictly inside the first W ticks."""
    return sum(1 for b in breaks if int(b) < int(window))


def targets_in_window(breaks: Sequence[int], lo: int, hi: int) -> int:
    """|{b in B(e) : lo <= b < hi}| -- targets broken inside a half-open tick window."""
    return sum(1 for b in breaks if int(lo) <= int(b) < int(hi))


def zero_target_horizon(end_reason: str, targets: int) -> bool:
    """A horizon episode that never broke a target: the strongest single-episode idle signal."""
    return end_reason == "horizon" and int(targets) == 0


def early_then_stagnant(length: int, breaks: Sequence[int], *,
                        early: int = EARLY_TARGET_TICK, tail: int = M7D_IDLE_TAIL_TICKS) -> bool:
    """Early progress followed by a long no-progress tail: b_1 <= `early` and tail(e) >= `tail`.

    This separates "never got going" from "got going, then stopped", which the
    single M7d idle flag cannot distinguish."""
    if not breaks:
        return False
    return int(min(breaks)) <= int(early) and tail_ticks(length, breaks) >= int(tail)


def shannon_bits(counts: Iterable[int]) -> float:
    """H = -sum p log2 p over a count vector, in bits. H = 0 for a single symbol."""
    c = [int(x) for x in counts if int(x) > 0]
    n = sum(c)
    if n <= 0:
        return 0.0
    return float(-sum((x / n) * math.log2(x / n) for x in c))


def decode_action(buttons: int, stick_x: int, stick_y: int) -> Tuple[Optional[int], Optional[int]]:
    """Native (buttons, stick_x, stick_y) -> frozen Track 1 (stick index, button index).

    Returns (None, None) components for values outside the Track 1 subset; the
    M7d policies only ever emit Track 1 actions, so a None here is a data fault
    and is counted, never silently dropped."""
    return (_STICK_INDEX.get((int(stick_x), int(stick_y))), _BUTTON_INDEX.get(int(buttons)))


def run_lengths(symbols: Sequence[Any]) -> List[int]:
    """Lengths of the maximal runs of identical consecutive symbols."""
    if not symbols:
        return []
    out: List[int] = []
    n = 1
    for i in range(1, len(symbols)):
        if symbols[i] == symbols[i - 1]:
            n += 1
        else:
            out.append(n)
            n = 1
    out.append(n)
    return out


def switch_rate(symbols: Sequence[Any]) -> Optional[float]:
    """switch(e) = |{t in [1, L) : a_t != a_{t-1}}| / (L - 1). Undefined for L < 2.

    1.0 means the action changes every tick; 0.0 means one action held for the
    whole episode."""
    if len(symbols) < 2:
        return None
    changes = sum(1 for i in range(1, len(symbols)) if symbols[i] != symbols[i - 1])
    return changes / float(len(symbols) - 1)


def long_run_share(symbols: Sequence[Any], k: int = LONG_RUN_TICKS) -> Optional[float]:
    """Fraction of ticks that sit inside a maximal run of length >= k.

    This is the action-side definition of "repeated ineffective action pattern":
    it is high only when the stream literally holds one action for long stretches."""
    if not symbols:
        return None
    runs = run_lengths(symbols)
    return sum(r for r in runs if r >= k) / float(len(symbols))


@dataclass
class ActionStats:
    """Summary of one canonical native action stream, or of a slice of one."""

    ticks: int = 0
    joint: Counter = field(default_factory=Counter)
    stick: Counter = field(default_factory=Counter)
    button: Counter = field(default_factory=Counter)
    switch: Optional[float] = None
    max_run: int = 0
    long_run_share: Optional[float] = None
    short_run_share: Optional[float] = None
    distinct_joint: int = 0
    full_neutral_share: Optional[float] = None     # stick neutral AND no button
    stick_neutral_share: Optional[float] = None
    button_none_share: Optional[float] = None
    undecodable: int = 0

    def entropies(self) -> Dict[str, float]:
        return {"joint_bits": round(shannon_bits(self.joint.values()), 4),
                "stick_bits": round(shannon_bits(self.stick.values()), 4),
                "button_bits": round(shannon_bits(self.button.values()), 4)}

    def as_dict(self, *, distributions: bool = False) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "ticks": self.ticks,
            "entropy": self.entropies(),
            "switch_rate": _r(self.switch),
            "max_run": self.max_run,
            "long_run_share": _r(self.long_run_share),
            "short_run_share": _r(self.short_run_share),
            "distinct_joint_actions": self.distinct_joint,
            "full_neutral_share": _r(self.full_neutral_share),
            "stick_neutral_share": _r(self.stick_neutral_share),
            "button_none_share": _r(self.button_none_share),
            "undecodable_actions": self.undecodable,
        }
        if distributions:
            out["stick_distribution"] = {STICK_NAMES[i]: self.stick.get(i, 0) for i in range(9)}
            out["button_distribution"] = {BUTTON_NAMES[i]: self.button.get(i, 0) for i in range(8)}
            out["top_joint_actions"] = [
                {"stick": STICK_NAMES[s], "button": BUTTON_NAMES[b], "ticks": n}
                for (s, b), n in self.joint.most_common(8) if s is not None and b is not None
            ]
        return out


def analyse_actions(rows: Sequence[Mapping[str, Any]]) -> ActionStats:
    """Build an ActionStats over a list of `actions.jsonl` rows (already sliced by the caller)."""
    st = ActionStats(ticks=len(rows))
    symbols: List[Tuple[Optional[int], Optional[int]]] = []
    for r in rows:
        s, b = decode_action(r.get("buttons", 0), r.get("stick_x", 0), r.get("stick_y", 0))
        if s is None or b is None:
            st.undecodable += 1
        symbols.append((s, b))
        st.joint[(s, b)] += 1
        st.stick[s] += 1
        st.button[b] += 1
    st.switch = switch_rate(symbols)
    runs = run_lengths(symbols)
    st.max_run = max(runs) if runs else 0
    st.long_run_share = long_run_share(symbols, LONG_RUN_TICKS)
    st.short_run_share = long_run_share(symbols, SHORT_RUN_TICKS)
    st.distinct_joint = len(st.joint)
    if st.ticks:
        st.full_neutral_share = st.joint.get((0, 0), 0) / float(st.ticks)
        st.stick_neutral_share = st.stick.get(0, 0) / float(st.ticks)
        st.button_none_share = st.button.get(0, 0) / float(st.ticks)
    return st


def _r(x: Optional[float], nd: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), nd)


def _mean(xs: Sequence[float]) -> Optional[float]:
    return statistics.fmean(xs) if xs else None


def _median(xs: Sequence[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None


def _quantile(xs: Sequence[float], p: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(float(x) for x in xs)
    if len(s) == 1:
        return s[0]
    i = p * (len(s) - 1)
    lo = int(math.floor(i))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


# -- episode records ----------------------------------------------------------------------------


@dataclass
class Episode:
    """One stored episode, normalised across the evaluation and training schemas."""

    run: str
    seed: int
    contract: str
    stage: str                 # initial | curve_tXXXXXXXXX | final | training
    transitions: Optional[int]  # policy age in transitions; None for training rows
    mode: str                  # stochastic | deterministic | training
    episode_id: str
    length: int
    targets: int
    end_reason: str
    breaks: List[int]
    digest: Optional[str]
    artifact_dir: Optional[str]
    final_obs: Optional[Mapping[str, Any]] = None
    anomalies: int = 0

    # derived, all from the definitions above
    @property
    def tail(self) -> int:
        return tail_ticks(self.length, self.breaks)

    @property
    def tail_frac(self) -> Optional[float]:
        return tail_fraction(self.length, self.breaks)

    @property
    def idle(self) -> bool:
        return m7d_idle(self.end_reason, self.length, self.breaks)

    @property
    def first_target(self) -> Optional[int]:
        return opening_gap(self.breaks)

    @property
    def tpk(self) -> Optional[float]:
        return targets_per_1000(self.length, self.targets)

    @property
    def zero_horizon(self) -> bool:
        return zero_target_horizon(self.end_reason, self.targets)

    @property
    def early_stagnant(self) -> bool:
        return early_then_stagnant(self.length, self.breaks)

    def objective_key(self) -> Tuple[int, int, int]:
        """Frozen objective ranking: verified clear, then targets, then faster completion."""
        if self.end_reason == "clear":
            return (1, TARGETS_TOTAL, 0)
        return (0, self.targets, 0)


def _stage_of(rel_parts: Sequence[str]) -> str:
    return rel_parts[1] if len(rel_parts) > 2 else "random"


def _transitions_of(stage: str, total: int = 1_024_000) -> Optional[int]:
    if stage == "initial":
        return 0
    if stage == "final":
        return total
    if stage.startswith("curve_t"):
        return int(stage.split("curve_t", 1)[1])
    return None


def load_evaluation_episodes(root: Path = EVAL_ROOT) -> List[Episode]:
    """Every evaluation row of the six M7d models. The random baseline is loaded separately."""
    out: List[Episode] = []
    for ev in sorted(root.rglob("evaluation.json")):
        rel = ev.relative_to(root).as_posix().split("/")
        run = rel[0]
        if not run.startswith("m7d_s"):
            continue
        stage = _stage_of(rel)
        seed = int(run.split("_s", 1)[1][0])
        contract = run.rsplit("_", 1)[1]
        doc = json.loads(ev.read_text(encoding="utf-8"))
        for e in doc.get("episodes") or []:
            out.append(Episode(
                run=run, seed=seed, contract=contract, stage=stage,
                transitions=_transitions_of(stage), mode=str(e.get("mode") or doc.get("mode")),
                episode_id=str(e["episode_id"]), length=int(e["length"]), targets=int(e["targets_broken"]),
                end_reason=str(e["end_reason"]), breaks=[int(x) for x in (e.get("target_break_ticks") or [])],
                digest=e.get("native_action_digest"), artifact_dir=e.get("artifact_dir"),
                anomalies=int(e.get("anomaly_events") or 0)))
    return out


def load_random_baseline(root: Path = EVAL_ROOT) -> List[Episode]:
    """The M7d random-agent baseline, stored one level deeper than the model sets."""
    base = root / "random_baseline"
    p = next((q for q in (base / "random" / "evaluation.json", base / "evaluation.json") if q.exists()), None)
    if p is None:
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    return [Episode(run="random_baseline", seed=-1, contract="random", stage="random", transitions=None,
                    mode="random", episode_id=str(e["episode_id"]), length=int(e["length"]),
                    targets=int(e["targets_broken"]), end_reason=str(e["end_reason"]),
                    breaks=[int(x) for x in (e.get("target_break_ticks") or [])],
                    digest=e.get("native_action_digest"), artifact_dir=e.get("artifact_dir"))
            for e in doc.get("episodes") or []]


def load_training_episodes(root: Path = MATRIX_ROOT) -> List[Episode]:
    """Every training row, which additionally carries a terminal native observation."""
    out: List[Episode] = []
    for run_dir in sorted(root.glob("m7d_s*")):
        p = run_dir / "metrics" / "episodes.jsonl"
        if not p.exists():
            continue
        run = run_dir.name
        seed = int(run.split("_s", 1)[1][0])
        contract = run.rsplit("_", 1)[1]
        with open(p, encoding="utf-8") as fp:
            for line in fp:
                if not line.strip():
                    continue
                e = json.loads(line)
                out.append(Episode(
                    run=run, seed=seed, contract=contract, stage="training",
                    transitions=e.get("sb3_num_timesteps_at_end"), mode="training",
                    episode_id=str(e["episode_id"]), length=int(e["steps"]), targets=int(e["targets_broken"]),
                    end_reason=str(e["end_reason"]), breaks=[int(x) for x in (e.get("target_break_ticks") or [])],
                    digest=e.get("native_action_digest"), artifact_dir=e.get("artifact_dir"),
                    final_obs=e.get("terminal_native_observation"), anomalies=int(e.get("anomaly_events") or 0)))
    return out


def read_artifact_metadata(artifact_dir: str) -> Optional[Mapping[str, Any]]:
    p = REPO_ROOT / artifact_dir / "metadata.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_artifact_actions(artifact_dir: str) -> Optional[List[Dict[str, Any]]]:
    p = REPO_ROOT / artifact_dir / "actions.jsonl"
    if not p.exists():
        return None
    rows: List[Dict[str, Any]] = []
    try:
        with open(p, encoding="utf-8") as fp:
            for line in fp:
                if line.strip():
                    rows.append(json.loads(line))
    except (OSError, ValueError):
        return None
    return rows


# -- aggregation --------------------------------------------------------------------------------


def summarise(eps: Sequence[Episode]) -> Dict[str, Any]:
    """Objective and behavioural summary of an episode group. All fields measured."""
    if not eps:
        return {"episodes": 0}
    n = len(eps)
    targets = [e.targets for e in eps]
    lengths = [e.length for e in eps]
    tails = [e.tail for e in eps]
    tail_fracs = [e.tail_frac for e in eps if e.tail_frac is not None]
    firsts = [e.first_target for e in eps if e.first_target is not None]
    tpks = [e.tpk for e in eps if e.tpk is not None]
    gaps = [g for e in eps for g in target_gaps(e.breaks)]
    ends = Counter(e.end_reason for e in eps)
    hist = Counter(targets)
    return {
        "episodes": n,
        "clears": sum(1 for e in eps if e.end_reason == "clear"),
        "targets_mean": _r(_mean(targets)),
        "targets_median": _r(_median(targets)),
        "targets_max": max(targets),
        "targets_min": min(targets),
        "targets_histogram": {str(k): hist[k] for k in sorted(hist)},
        "end_reasons": dict(ends),
        "fall_rate": _r(ends.get("fall", 0) / n),
        "horizon_rate": _r(ends.get("horizon", 0) / n),
        "length_mean": _r(_mean(lengths), 1),
        "length_p10": _r(_quantile(lengths, 0.10), 1),
        "length_p90": _r(_quantile(lengths, 0.90), 1),
        "first_target_tick_median": _r(_median(firsts), 1),
        "first_target_tick_p90": _r(_quantile(firsts, 0.90), 1),
        "episodes_with_first_target": len(firsts),
        "last_target_tick_median": _r(_median([max(e.breaks) for e in eps if e.breaks]), 1),
        "gap_median": _r(_median(gaps), 1),
        "gap_p90": _r(_quantile(gaps, 0.90), 1),
        "gap_count": len(gaps),
        "tail_mean": _r(_mean(tails), 1),
        "tail_median": _r(_median(tails), 1),
        "tail_fraction_mean": _r(_mean(tail_fracs)),
        "targets_per_1000_ticks": _r(_mean(tpks)),
        "m7d_idle_rate": _r(sum(1 for e in eps if e.idle) / n),
        "zero_target_horizon_rate": _r(sum(1 for e in eps if e.zero_horizon) / n),
        "early_then_stagnant_rate": _r(sum(1 for e in eps if e.early_stagnant) / n),
        "distinct_action_digests": len({e.digest for e in eps if e.digest}),
        "anomaly_events": sum(e.anomalies for e in eps),
    }


def survival_matched(eps: Sequence[Episode], windows: Sequence[int] = CENSUS_WINDOWS) -> List[Dict[str, Any]]:
    """Targets broken inside the first W ticks, restricted to episodes that survived >= W ticks.

    This removes the M7d confound in which a v1 episode ending in a fall at
    tick 900 cannot accumulate an idle tail and cannot break a late target.
    `survivors` is the denominator; `survivor_rate` is itself the fall-rate
    evidence, reported beside the progress figure rather than mixed into it."""
    out: List[Dict[str, Any]] = []
    n = len(eps)
    for w in windows:
        surv = [e for e in eps if e.length >= w]
        tw = [targets_before(e.breaks, w) for e in surv]
        out.append({
            "window": w,
            "survivors": len(surv),
            "survivor_rate": _r(len(surv) / n) if n else None,
            "targets_in_window_mean": _r(_mean(tw)),
            "targets_in_window_median": _r(_median(tw)),
            "zero_in_window_rate": _r(sum(1 for x in tw if x == 0) / len(tw)) if tw else None,
        })
    return out


def phase_progress(eps: Sequence[Episode], edges: Sequence[int] = (0, 600, 1200, 1800, 2400, 3000, 3600),
                   ) -> List[Dict[str, Any]]:
    """Targets broken per phase of the episode, over the episodes that reached that phase.

    phase_k covers ticks [edges_k, edges_{k+1}); an episode contributes only if
    L(e) >= edges_{k+1}, so a phase rate is never diluted by episodes that had
    already ended. A collapsing sequence of phase rates is the direct signature
    of "progress stops partway through", independent of why the episode ends."""
    out: List[Dict[str, Any]] = []
    for lo, hi in zip(edges, edges[1:]):
        reached = [e for e in eps if e.length >= hi]
        vals = [targets_in_window(e.breaks, lo, hi) for e in reached]
        out.append({
            "phase": f"{lo}-{hi}",
            "episodes_reaching": len(reached),
            "targets_mean": _r(_mean(vals)),
            "zero_rate": _r(sum(1 for v in vals if v == 0) / len(vals)) if vals else None,
        })
    return out


def action_summary(eps: Sequence[Episode], *, limit: Optional[int] = None,
                   distributions: bool = True) -> Optional[Dict[str, Any]]:
    """Pooled action statistics over a group, plus the head/tail contrast.

    head = ticks [0, b_T]  (up to and including the last target break)
    tail = ticks (b_T, L)  (everything after it)

    The contrast is the discriminator the M7d idle flag lacks: a genuinely
    stuck or looping tail shows falling entropy and rising long-run share
    against its own head, while a tail that merely fails to score does not."""
    chosen = [e for e in eps if e.artifact_dir]
    if limit is not None:
        chosen = chosen[:limit]
    if not chosen:
        return None
    whole = ActionStats()
    head_ent: List[float] = []
    tail_ent: List[float] = []
    head_sw: List[float] = []
    tail_sw: List[float] = []
    head_lr: List[float] = []
    tail_lr: List[float] = []
    tail_neutral: List[float] = []
    distinct_per_ep: List[int] = []
    max_runs: List[int] = []
    used = 0
    for e in chosen:
        rows = read_artifact_actions(e.artifact_dir)
        if not rows:
            continue
        used += 1
        st = analyse_actions(rows)
        whole.ticks += st.ticks
        whole.joint.update(st.joint)
        whole.stick.update(st.stick)
        whole.button.update(st.button)
        whole.undecodable += st.undecodable
        distinct_per_ep.append(st.distinct_joint)
        max_runs.append(st.max_run)
        if e.breaks:
            cut = int(max(e.breaks)) + 1
            h, t = rows[:cut], rows[cut:]
            if len(h) >= 2 and len(t) >= 2:
                hs, ts = analyse_actions(h), analyse_actions(t)
                head_ent.append(hs.entropies()["joint_bits"])
                tail_ent.append(ts.entropies()["joint_bits"])
                if hs.switch is not None and ts.switch is not None:
                    head_sw.append(hs.switch)
                    tail_sw.append(ts.switch)
                if hs.long_run_share is not None and ts.long_run_share is not None:
                    head_lr.append(hs.long_run_share)
                    tail_lr.append(ts.long_run_share)
                if ts.full_neutral_share is not None:
                    tail_neutral.append(ts.full_neutral_share)
    if not used:
        return None
    whole.switch = None
    pooled = whole.as_dict(distributions=distributions)
    pooled.pop("switch_rate", None)
    pooled.pop("long_run_share", None)
    pooled.pop("short_run_share", None)
    pooled.pop("max_run", None)
    return {
        "episodes_analysed": used,
        "pooled": pooled,
        "per_episode": {
            "distinct_joint_actions_mean": _r(_mean(distinct_per_ep), 2),
            "max_run_mean": _r(_mean(max_runs), 1),
            "max_run_p90": _r(_quantile(max_runs, 0.90), 1),
        },
        "head_tail": {
            "pairs": len(head_ent),
            "head_entropy_bits_mean": _r(_mean(head_ent)),
            "tail_entropy_bits_mean": _r(_mean(tail_ent)),
            "entropy_delta_mean": _r((_mean(tail_ent) - _mean(head_ent)) if head_ent else None),
            "head_switch_rate_mean": _r(_mean(head_sw)),
            "tail_switch_rate_mean": _r(_mean(tail_sw)),
            "switch_delta_mean": _r((_mean(tail_sw) - _mean(head_sw)) if head_sw else None),
            "head_long_run_share_mean": _r(_mean(head_lr)),
            "tail_long_run_share_mean": _r(_mean(tail_lr)),
            "long_run_delta_mean": _r((_mean(tail_lr) - _mean(head_lr)) if head_lr else None),
            "tail_full_neutral_share_mean": _r(_mean(tail_neutral)),
        },
    }


def final_state_clusters(eps: Sequence[Episode], *, grid: float = 200.0,
                         limit: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Concentration of the FINAL position only, binned on a `grid`-unit lattice.

    This is a final-state fact and nothing more. It cannot establish that a
    policy stood still: an episode that orbits a region and one that stops dead
    in it produce the same final bin. Trajectory-level spatial claims are marked
    unknown throughout this report and are what the Phase A4 replay exists for."""
    pts: List[Tuple[float, float]] = []
    statuses: Counter = Counter()
    ground: Counter = Counter()
    chosen = eps if limit is None else eps[:limit]
    for e in chosen:
        obs = e.final_obs
        if obs is None and e.artifact_dir:
            md = read_artifact_metadata(e.artifact_dir)
            obs = (md or {}).get("final_observation")
        if not obs or obs.get("position_x") is None:
            continue
        pts.append((float(obs["position_x"]), float(obs["position_y"])))
        statuses[int(obs.get("fighter_status_id", -1))] += 1
        ground[int(obs.get("ground_air_state", -1))] += 1
    if not pts:
        return None
    bins = Counter((math.floor(x / grid), math.floor(y / grid)) for x, y in pts)
    top = bins.most_common(5)
    return {
        "episodes_with_final_position": len(pts),
        "grid": grid,
        "distinct_bins": len(bins),
        "modal_bin_share": _r(top[0][1] / len(pts)),
        "top_bins": [{"x_bin": int(b[0] * grid), "y_bin": int(b[1] * grid), "episodes": n} for b, n in top],
        "position_x_median": _r(_median([p[0] for p in pts]), 1),
        "position_x_p10": _r(_quantile([p[0] for p in pts], 0.10), 1),
        "position_x_p90": _r(_quantile([p[0] for p in pts], 0.90), 1),
        "position_y_median": _r(_median([p[1] for p in pts]), 1),
        "top_fighter_status_ids": dict(statuses.most_common(5)),
        "ground_air_state": dict(ground),
        "evidence_class": "measured (final state only); trajectory occupancy is unknown from stored data",
    }


# -- learning-curve classification --------------------------------------------------------------


def _theil_sen(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Median of pairwise slopes. Robust to the single-checkpoint outliers these curves contain."""
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(xs)) for j in range(i + 1, len(xs)) if xs[j] != xs[i]]
    return statistics.median(slopes) if slopes else None


def classify_curve(points: Sequence[Tuple[int, float]], *, noise: Optional[float] = None) -> Dict[str, Any]:
    """Classify a checkpoint curve as improving / plateaued / regressing / too_noisy.

    points   [(transitions, mean targets)], ordered
    noise    a scale for "indistinguishable from flat"; defaults to the
             checkpoint-to-checkpoint mean absolute change divided by 2.

    The rule, stated before it is applied:
      let s   = Theil-Sen slope over the curve, in targets per 1,000,000 transitions
      let d   = mean(last third) - mean(first third), in targets
      let eps = noise (targets per 1,000,000 transitions, on the same scale as s)
      improving   if s > +eps and d > 0
      regressing  if s < -eps and d < 0
      plateaued   if |s| <= eps
      too_noisy   otherwise (slope and endpoint difference disagree in sign)

    The classification is descriptive. It is never used as a decision rule on
    its own; the report pairs it with the fall, horizon and tail metrics."""
    if len(points) < 4:
        return {"class": "too_noisy", "reason": "fewer than 4 checkpoints"}
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    slope_per_m = _theil_sen(xs, ys)
    if slope_per_m is None:
        return {"class": "too_noisy", "reason": "degenerate x"}
    slope_per_m *= 1_000_000.0
    steps = [abs(ys[i] - ys[i - 1]) for i in range(1, len(ys))]
    span = xs[-1] - xs[0]
    eps = noise if noise is not None else (statistics.fmean(steps) / 2.0) / (span / 1_000_000.0)
    k = max(1, len(ys) // 3)
    delta = statistics.fmean(ys[-k:]) - statistics.fmean(ys[:k])
    if slope_per_m > eps and delta > 0:
        cls = "improving"
    elif slope_per_m < -eps and delta < 0:
        cls = "regressing"
    elif abs(slope_per_m) <= eps:
        cls = "plateaued"
    else:
        cls = "too_noisy"
    return {"class": cls, "theil_sen_targets_per_1e6": _r(slope_per_m, 3),
            "noise_scale_targets_per_1e6": _r(eps, 3), "third_delta_targets": _r(delta, 3),
            "first": _r(ys[0], 3), "last": _r(ys[-1], 3), "best": _r(max(ys), 3),
            "argmax_transitions": int(xs[ys.index(max(ys))]), "checkpoints": len(ys)}


# -- report -------------------------------------------------------------------------------------


def stage_order(stage: str) -> Tuple[int, int]:
    if stage == "initial":
        return (0, 0)
    if stage == "final":
        return (2, 0)
    if stage.startswith("curve_t"):
        return (1, int(stage.split("curve_t", 1)[1]))
    return (3, 0)


def build(*, with_actions: bool = True) -> Dict[str, Any]:
    ev = load_evaluation_episodes()
    tr = load_training_episodes()
    rnd = load_random_baseline()
    report: Dict[str, Any] = {
        "schema": SCHEMA,
        "milestone": "M7e Phase A",
        "purpose": "diagnose what 'idling' means in the M7d btt_reward_v2 policies",
        "read_only": True,
        "sources": {
            "evaluation_rows": len(ev), "training_rows": len(tr), "random_baseline_rows": len(rnd),
            "total_rows": len(ev) + len(tr) + len(rnd),
        },
        "definitions": definitions_block(),
        "runs": {},
        "comparisons": {},
    }

    by_run: Dict[str, List[Episode]] = {}
    for e in ev + tr:
        by_run.setdefault(e.run, []).append(e)

    for seed in SEEDS:
        for contract in CONTRACTS:
            run = f"m7d_s{seed}_{contract}"
            eps = by_run.get(run, [])
            stages: Dict[str, Any] = {}
            for stage in sorted({e.stage for e in eps if e.stage != "training"}, key=stage_order):
                entry: Dict[str, Any] = {"transitions": _transitions_of(stage)}
                for mode in ("stochastic", "deterministic"):
                    group = [e for e in eps if e.stage == stage and e.mode == mode]
                    if not group:
                        continue
                    block = summarise(group)
                    block["survival_matched"] = survival_matched(group)
                    block["phase_progress"] = phase_progress(group)
                    if mode == "deterministic":
                        block["identical_plays"] = block["distinct_action_digests"] == 1
                    if with_actions and stage in ("initial", "final"):
                        block["actions"] = action_summary(group, distributions=True)
                        block["final_state"] = final_state_clusters(group)
                        if mode == "deterministic":
                            block["deterministic_collapse"] = deterministic_collapse(block)
                    entry[mode] = block
                stages[stage] = entry
            train = [e for e in eps if e.stage == "training"]
            report["runs"][run] = {
                "seed": seed, "contract": f"btt_reward_{contract}",
                "stages": stages,
                "training": {**summarise(train), "final_state": final_state_clusters(train)} if train else None,
                "training_windows": training_windows(train),
                "learning_curve": learning_curve(stages),
                "optimization": optimization_telemetry(run),
            }

    report["comparisons"] = comparisons(report["runs"])
    report["random_baseline"] = summarise(rnd) if rnd else None
    report["replay_plan"] = replay_plan(ev)
    if REPLAY_JSON.exists():      # Phase A4 results, when the probe has been run
        report["replay"] = json.loads(REPLAY_JSON.read_text(encoding="utf-8"))
    report["findings"] = findings(report)
    return report


def training_windows(eps: Sequence[Episode], window: int = 102_400) -> List[Dict[str, Any]]:
    """Training episodes bucketed by the transition count at which they finished."""
    if not eps:
        return []
    buckets: Dict[int, List[Episode]] = {}
    for e in eps:
        t = e.transitions
        if t is None:
            continue
        b = (int(t) // window + 1) * window
        buckets.setdefault(b, []).append(e)
    out = []
    for b in sorted(buckets):
        g = buckets[b]
        tails = [x.tail for x in g]
        out.append({
            "transitions_upto": b, "episodes": len(g),
            "targets_mean": _r(_mean([x.targets for x in g])),
            "fall_rate": _r(sum(1 for x in g if x.end_reason == "fall") / len(g)),
            "horizon_rate": _r(sum(1 for x in g if x.end_reason == "horizon") / len(g)),
            "length_mean": _r(_mean([x.length for x in g]), 1),
            "tail_mean": _r(_mean(tails), 1),
            "m7d_idle_rate": _r(sum(1 for x in g if x.idle) / len(g)),
            "clears": sum(1 for x in g if x.end_reason == "clear"),
        })
    return out


MAX_CONDITIONAL_ENTROPY_NATS = math.log(9) + math.log(8)   # uniform over MultiDiscrete([9, 8]) = 4.2767


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def optimization_telemetry(run: str, root: Path = MATRIX_ROOT) -> Optional[Dict[str, Any]]:
    """Policy-entropy and value-fit trajectory from the stored rollout metrics.

    SB3 records `train/entropy_loss` = -H, where H is the mean per-state policy
    entropy in nats. With `ent_coef = 0.0` nothing holds H open, so H is a direct
    read on how far the policy has concentrated:

        H_max = ln 9 + ln 8 = 4.2767 nats   (uniform over the frozen Track 1 space)
        entropy_fraction = H / H_max
        concentration rate = d H / d(transitions), in nats per 1e6 transitions
        deceleration = (rate over the last third) / (rate over the whole run)

    A run whose deceleration is near or above 1 is still concentrating at full
    speed at the budget's end. This is measured optimization state, not a
    gameplay claim; it is reported beside the gameplay curves, never instead."""
    p = root / run / "training_summary.json"
    if not p.exists():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    rr = doc.get("rollouts") or []
    pts = [(int(r["num_timesteps"]), -float(r["train_metrics"]["train/entropy_loss"]),
            float(r["train_metrics"]["train/explained_variance"]),
            float(r["train_metrics"]["train/approx_kl"])) for r in rr if r.get("train_metrics")]
    if len(pts) < 6:
        return None
    xs = [p_[0] for p_ in pts]
    hs = [p_[1] for p_ in pts]
    ev = [p_[2] for p_ in pts]
    kl = [p_[3] for p_ in pts]
    k = max(2, len(xs) // 3)
    s_all = _ols_slope(xs, hs)
    s_last = _ols_slope(xs[-k:], hs[-k:])
    return {
        "ent_coef": doc.get("ppo", {}).get("ent_coef"),
        "rollouts": len(pts),
        "entropy_nats_start": _r(hs[0], 4),
        "entropy_nats_end": _r(hs[-1], 4),
        "entropy_max_nats": _r(MAX_CONDITIONAL_ENTROPY_NATS, 4),
        "entropy_fraction_start": _r(hs[0] / MAX_CONDITIONAL_ENTROPY_NATS),
        "entropy_fraction_end": _r(hs[-1] / MAX_CONDITIONAL_ENTROPY_NATS),
        "entropy_slope_per_1e6": _r((s_all or 0) * 1e6, 4),
        "entropy_slope_last_third_per_1e6": _r((s_last or 0) * 1e6, 4),
        "deceleration": _r((s_last / s_all) if (s_all and s_last) else None, 3),
        "still_concentrating": bool(s_last is not None and s_last < 0),
        "explained_variance_last": _r(ev[-1], 4),
        "explained_variance_mean_last_third": _r(_mean(ev[-k:]), 4),
        "approx_kl_mean_last_third": _r(_mean(kl[-k:]), 5),
        "evidence_class": "measured (stored SB3 rollout metrics)",
    }


def deterministic_collapse(block: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Is the argmax policy frozen on a single action?

    collapse_share = max_run / L for the one deterministic play. A value near 1
    means the greedy policy emits one action for essentially the whole episode,
    which is literal idling in a way the sampled policy is not. Reported with
    the joint entropy of the same stream so the two readings travel together."""
    if not block or not block.get("actions"):
        return None
    a = block["actions"]
    length = block.get("length_mean")
    max_run = a["per_episode"]["max_run_mean"]
    if not length or max_run is None:
        return None
    share = max_run / float(length)
    return {
        "max_run_ticks": max_run, "episode_length": length,
        "collapse_share": _r(share),
        "joint_entropy_bits": a["pooled"]["entropy"]["joint_bits"],
        "distinct_joint_actions": a["per_episode"]["distinct_joint_actions_mean"],
        "collapsed": bool(share >= 0.5),
        "criterion": "collapse_share = max_run / L >= 0.5 (one action held for at least half the episode)",
    }


def learning_curve(stages: Mapping[str, Any]) -> Dict[str, Any]:
    """Checkpoint curves and their classification, per mode."""
    out: Dict[str, Any] = {}
    for mode in ("stochastic", "deterministic"):
        pts: List[Tuple[int, float]] = []
        rows: List[Dict[str, Any]] = []
        for stage, entry in sorted(stages.items(), key=lambda kv: stage_order(kv[0])):
            block = entry.get(mode)
            if not block or block.get("targets_mean") is None:
                continue
            t = entry["transitions"]
            pts.append((int(t), float(block["targets_mean"])))
            rows.append({"transitions": t, "stage": stage, "targets_mean": block["targets_mean"],
                         "fall_rate": block["fall_rate"], "horizon_rate": block["horizon_rate"],
                         "m7d_idle_rate": block["m7d_idle_rate"], "tail_mean": block["tail_mean"],
                         "tail_fraction_mean": block["tail_fraction_mean"],
                         "targets_per_1000_ticks": block["targets_per_1000_ticks"],
                         "zero_target_horizon_rate": block["zero_target_horizon_rate"],
                         "episodes": block["episodes"]})
        if pts:
            out[mode] = {"points": rows, "classification": classify_curve(pts)}
    # Is the final checkpoint also the best one, on the objective ranking?
    st = out.get("stochastic")
    if st:
        ordered = st["points"]
        best = max(ordered, key=lambda r: (r["targets_mean"], -(r["transitions"] or 0)))
        out["best_checkpoint"] = {"transitions": best["transitions"], "stage": best["stage"],
                                  "targets_mean": best["targets_mean"]}
        out["final_is_best"] = ordered[-1]["transitions"] == best["transitions"]
        out["final_minus_best_targets"] = _r(ordered[-1]["targets_mean"] - best["targets_mean"])
        # first checkpoint beating the untrained policy by >= 0.25 targets
        base = ordered[0]["targets_mean"]
        first = next((r for r in ordered[1:] if r["targets_mean"] >= base + 0.25), None)
        out["first_useful_learning"] = None if first is None else {
            "transitions": first["transitions"], "targets_mean": first["targets_mean"],
            "untrained_targets_mean": base}
    return out


def comparisons(runs: Mapping[str, Any]) -> Dict[str, Any]:
    """Paired v1/v2 contrasts that the M7d report could not make: survival-matched progress."""
    out: Dict[str, Any] = {"final_stochastic": {}, "idle_vs_fall": {}}
    for seed in SEEDS:
        a = runs[f"m7d_s{seed}_v1"]["stages"].get("final", {}).get("stochastic")
        b = runs[f"m7d_s{seed}_v2"]["stages"].get("final", {}).get("stochastic")
        if not a or not b:
            continue
        sm = []
        for wa, wb in zip(a["survival_matched"], b["survival_matched"]):
            sm.append({
                "window": wa["window"],
                "v1_survivors": wa["survivors"], "v2_survivors": wb["survivors"],
                "v1_targets": wa["targets_in_window_mean"], "v2_targets": wb["targets_in_window_mean"],
                "delta": _r((wb["targets_in_window_mean"] - wa["targets_in_window_mean"])
                            if (wa["targets_in_window_mean"] is not None
                                and wb["targets_in_window_mean"] is not None) else None),
            })
        out["final_stochastic"][f"seed{seed}"] = {
            "survival_matched": sm,
            "targets_delta": _r(b["targets_mean"] - a["targets_mean"]),
            "fall_delta": _r(b["fall_rate"] - a["fall_rate"]),
            "idle_delta": _r(b["m7d_idle_rate"] - a["m7d_idle_rate"]),
            "tail_fraction_delta": _r(b["tail_fraction_mean"] - a["tail_fraction_mean"]),
        }
    # Does idling rise as falling drops, within v2's own curve?
    for seed in SEEDS:
        run = runs[f"m7d_s{seed}_v2"]
        pts = run["learning_curve"].get("stochastic", {}).get("points", [])
        if len(pts) >= 4:
            falls = [p["fall_rate"] for p in pts]
            idles = [p["m7d_idle_rate"] for p in pts]
            tails = [p["tail_fraction_mean"] for p in pts]
            out["idle_vs_fall"][f"seed{seed}"] = {
                "fall_first": falls[0], "fall_last": falls[-1],
                "idle_first": idles[0], "idle_last": idles[-1],
                "tail_fraction_first": tails[0], "tail_fraction_last": tails[-1],
                "correlation_fall_idle": _r(_pearson(falls, idles)),
            }
    return out


def _pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    xs = [float(x) for x in a]
    ys = [float(y) for y in b]
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def replay_plan(ev: Sequence[Episode]) -> Dict[str, Any]:
    """The Phase A4 selection: a small documented set, chosen by stated rules, not by hand."""
    sel: List[Dict[str, Any]] = []

    def pick(eps: Sequence[Episode], key, why: str, role: str) -> None:
        if not eps:
            return
        e = max(eps, key=key)
        sel.append({"role": role, "run": e.run, "episode_id": e.episode_id, "stage": e.stage, "mode": e.mode,
                    "targets": e.targets, "length": e.length, "end_reason": e.end_reason,
                    "tail": e.tail, "tail_fraction": _r(e.tail_frac), "breaks": e.breaks,
                    "artifact_dir": e.artifact_dir, "selection_rule": why})

    for seed in SEEDS:
        for contract in CONTRACTS:
            run = f"m7d_s{seed}_{contract}"
            fin = [e for e in ev if e.run == run and e.stage == "final" and e.mode == "stochastic"]
            det = [e for e in ev if e.run == run and e.stage == "final" and e.mode == "deterministic"]
            pick(fin, lambda e: (e.objective_key(), -e.length), "highest objective key, then shortest",
                 f"best_final_{contract}")
            if contract == "v2":
                pick([e for e in fin if e.idle], lambda e: (e.tail, e.targets),
                     "longest tail among idle episodes", f"worst_idle_{contract}")
                pick([e for e in fin if e.early_stagnant], lambda e: e.tail,
                     "early first target then longest tail", f"early_then_stagnant_{contract}")
            pick(det[:1], lambda e: 0, "the single deterministic play (100 identical)", f"deterministic_{contract}")
    return {"episodes": sel, "count": len(sel),
            "note": "observational replay only: fresh process, tick 0, canonical native actions, "
                    "consumed-tick alignment enforced by run_artifacts.resubmit_actions"}


# -- Phase A4: bounded observational replay -----------------------------------------------------

REPLAY_ROOT = REPO_ROOT / "runs" / "_m7e_replay"
REPLAY_JSON = REPO_ROOT / "docs" / "rl_v2_idle_diagnosis_m7e_replay.json"


def _trajectory_metrics(xs: Sequence[float], ys: Sequence[float], breaks: Sequence[int]) -> Dict[str, Any]:
    """Spatial facts of one replayed trajectory. These are the quantities the
    stored records could not supply.

      path_length      sum over t of |p_t - p_{t-1}|, total distance travelled
      displacement     |p_last - p_first|, net displacement
      x_range          max x - min x, horizontal extent explored
      tail_*           the same quantities restricted to ticks after the last break
      stationary_share fraction of ticks with |p_t - p_{t-1}| < 1.0 (below one unit per tick)
      revisit_share    fraction of tail ticks whose 100-unit cell was already
                       visited earlier in the tail; high means looping in place

    "Stuck in a location" means a small tail x_range with a large tail path
    length: the character keeps moving but stays in one region. "Standing
    still" means a high stationary_share. The two are different and are
    reported separately."""
    n = len(xs)
    if n < 2:
        return {"ticks": n}

    def seg(a: int, b: int) -> Dict[str, Any]:
        px, py = xs[a:b], ys[a:b]
        if len(px) < 2:
            return {"ticks": len(px)}
        steps = [math.dist((px[i - 1], py[i - 1]), (px[i], py[i])) for i in range(1, len(px))]
        cells: set = set()
        revisits = 0
        for x, y in zip(px, py):
            c = (math.floor(x / 100.0), math.floor(y / 100.0))
            if c in cells:
                revisits += 1
            cells.add(c)
        return {
            "ticks": len(px),
            "path_length": _r(sum(steps), 1),
            "displacement": _r(math.dist((px[0], py[0]), (px[-1], py[-1])), 1),
            "x_min": _r(min(px), 1), "x_max": _r(max(px), 1), "x_range": _r(max(px) - min(px), 1),
            "y_min": _r(min(py), 1), "y_max": _r(max(py), 1), "y_range": _r(max(py) - min(py), 1),
            "stationary_share": _r(sum(1 for s in steps if s < 1.0) / len(steps)),
            "distinct_cells_100": len(cells),
            "revisit_share": _r(revisits / len(px)),
            "mean_speed_per_tick": _r(sum(steps) / len(steps), 3),
        }

    out = {"whole": seg(0, n)}
    if breaks:
        cut = min(int(max(breaks)) + 1, n)
        out["head"] = seg(0, cut)
        out["tail"] = seg(cut, n)
    return out


def replay_probe(selection: Sequence[Mapping[str, Any]], *, out_root: Path = REPLAY_ROOT,
                 limit: Optional[int] = None) -> Dict[str, Any]:
    """Re-submit the canonical native actions of selected artifacts on fresh processes and
    record the position trajectory.

    Strictly observational: one fresh process per episode, always from tick 0,
    always the artifact's own canonical actions in order, never a mutated or
    synthesised action, no training, no RNG inspection. `resubmit_actions`
    raises `ReplayMismatch` if any consumed tick disagrees with the record, so
    tick alignment is enforced rather than assumed. Output goes to
    `runs/_m7e_replay/`; nothing under `runs/m7d/` is opened for writing."""
    import m7d_matrix as mm
    from m7_runtime import PortCandidates, install_kill_on_close_job, prepare_worker_runtime
    from battleship_process import BattleShipEpisode, LaunchConfig
    from run_artifacts import read_artifact, resubmit_actions

    install_kill_on_close_job()
    seen: set = set()
    picks: List[Mapping[str, Any]] = []
    for s in selection:
        if s["artifact_dir"] and s["artifact_dir"] not in seen:
            seen.add(s["artifact_dir"])
            picks.append(s)
    if limit is not None:
        picks = picks[:limit]

    out_root.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    exp_cache: Dict[str, Any] = {}
    for i, s in enumerate(picks):
        run = s["run"]
        if run not in exp_cache:
            exp_cache[run] = mm.load_run(mm.run_by_name(run))
        exp = exp_cache[run]
        work = out_root / f"probe_{i:02d}_{s['episode_id'][-8:]}"
        if work.exists():
            raise RuntimeError(f"{work} exists (never overwritten)")
        art = read_artifact(REPO_ROOT / s["artifact_dir"])
        runtime = work / "runtime"
        prepare_worker_runtime(runtime, exp.executable)
        port, _busy = PortCandidates(0).claim()
        cfg = LaunchConfig(executable=Path(exp.executable), working_dir=runtime, run_root=work / "episodes",
                           port=port, startup_timeout=20.0, ready_timeout=60.0, request_timeout=10.0,
                           exit_timeout=30.0, extra_env=dict(exp.extra_env))
        (work / "episodes").mkdir(parents=True, exist_ok=True)
        xs: List[float] = []
        ys: List[float] = []
        ground: Counter = Counter()
        status: Counter = Counter()
        breaks: List[int] = []
        prev_remaining = [TARGETS_TOTAL]

        def observe(_a: Any, r: Any) -> None:
            o = r.observation
            xs.append(float(o.position_x))
            ys.append(float(o.position_y))
            ground[int(o.ground_air_state)] += 1
            status[int(o.fighter_status_id)] += 1
            rem = int(o.targets_remaining)
            for _ in range(max(0, prev_remaining[0] - rem)):
                breaks.append(int(r.consumed_tick))
            prev_remaining[0] = rem

        rec: Dict[str, Any] = {"role": s["role"], "run": run, "episode_id": s["episode_id"],
                               "stage": s["stage"], "mode": s["mode"], "recorded_targets": s["targets"],
                               "recorded_length": s["length"], "recorded_end": s["end_reason"],
                               "recorded_breaks": s["breaks"], "artifact": s["artifact_dir"],
                               "actions": len(art.actions)}
        ep = BattleShipEpisode(cfg, index=9500 + i)
        with ep:
            fresh = ep.start()
            rec["fresh"] = {"state": fresh.state_name, "step_count": fresh.step_count}
            results = resubmit_actions(ep.client, art.actions, on_result=observe)
            last = results[-1]
            rec["submitted"] = len(results)
            rec["last_consumed_tick"] = int(last.consumed_tick)
            rec["final_state"] = last.state_name
            rec["replay_targets"] = TARGETS_TOTAL - int(last.observation.targets_remaining)
            rec["replay_breaks"] = breaks
        rec["checks"] = {
            "fresh_at_tick_zero": rec["fresh"]["state"] == "WaitingForAction" and rec["fresh"]["step_count"] == 0,
            "all_actions_submitted": rec["submitted"] == len(art.actions),
            "targets_match": rec["replay_targets"] == s["targets"],
            "break_ticks_match": breaks == list(s["breaks"]),
            "consumed_tick_aligned": rec["last_consumed_tick"] == rec["submitted"] - 1,
        }
        rec["ok"] = all(rec["checks"].values())
        rec["trajectory"] = _trajectory_metrics(xs, ys, breaks)
        rec["ground_air_state"] = dict(ground)
        rec["top_fighter_status_ids"] = dict(status.most_common(6))
        records.append(rec)
        print(f"  {run:11s} {s['role']:24s} targets={rec['replay_targets']} ok={rec['ok']}")
    return {"schema": SCHEMA + "_replay", "episodes": len(records), "records": records,
            "note": "observational replay only; fresh process per episode, tick 0, canonical native actions"}


def definitions_block() -> Dict[str, Any]:
    return {
        "notation": "L(e) episode length in native ticks; T(e) targets broken; "
                    "B(e) = (b_1 < ... < b_T) target-break ticks; end(e) end reason; H = 3600 horizon",
        "tail": "tail(e) = L - (b_T + 1) if T >= 1 else L",
        "tail_fraction": "tail_frac(e) = tail(e) / L(e)",
        "m7d_idle": f"idle(e) = [end(e) = horizon] and [tail(e) >= {M7D_IDLE_TAIL_TICKS}] (M7d definition, unchanged)",
        "first_target_tick": "b_1, undefined when T = 0",
        "gap": "gap_k(e) = b_{k+1} - b_k, k = 1..T-1",
        "targets_per_1000_ticks": "tpk(e) = 1000 T(e) / L(e)",
        "zero_target_horizon": "end(e) = horizon and T(e) = 0",
        "early_then_stagnant": f"T >= 1 and b_1 <= {EARLY_TARGET_TICK} and tail(e) >= {M7D_IDLE_TAIL_TICKS}",
        "targets_before_W": "T_W(e) = |{b in B(e) : b < W}|",
        "survival_matched": "for window W, the mean of T_W over the survivor set S_W = {e : L(e) >= W}; "
                            "the survivor rate |S_W|/n is reported beside it, never folded into it",
        "phase_progress": "targets broken in [lo, hi) over episodes with L(e) >= hi",
        "action_entropy": "H = -sum p log2 p in bits over the empirical action distribution; "
                          "max log2(72) = 6.1699 joint, log2(9) = 3.1699 stick, log2(8) = 3 button",
        "switch_rate": "switch(e) = |{t in [1,L) : a_t != a_{t-1}}| / (L - 1)",
        "long_run_share": f"fraction of ticks inside a maximal run of >= {LONG_RUN_TICKS} identical actions",
        "full_neutral_share": "fraction of ticks with stick index 0 and button index 0 (no input at all)",
        "head_tail_contrast": "head = ticks [0, b_T], tail = ticks (b_T, L); deltas are tail minus head",
        "final_state_cluster": "binning of the FINAL position only; trajectory occupancy is not stored",
        "learning_curve_class": "Theil-Sen slope s (targets per 1e6 transitions) against a noise scale eps; "
                                "improving if s > eps and last-third minus first-third > 0; regressing if the "
                                "mirror image; plateaued if |s| <= eps; too_noisy if slope and delta disagree",
        "entropy_fraction": f"H / H_max where H is SB3's mean per-state policy entropy in nats and "
                            f"H_max = ln 9 + ln 8 = {MAX_CONDITIONAL_ENTROPY_NATS:.4f} (uniform over Track 1)",
        "deceleration": "(entropy slope over the last third) / (entropy slope over the whole run); "
                        "~1 means the policy is still concentrating at full speed at the budget's end",
        "collapse_share": "max_run / L for a deterministic play; >= 0.5 is a collapsed argmax policy",
        "evidence_classes": {
            "measured": "computed directly from a stored field",
            "inferred": "derived from measured quantities under a stated assumption",
            "unknown": "not answerable from what M7d stored",
        },
    }


def findings(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Mechanical extraction of the facts the prose report interprets. No judgement here."""
    runs = report["runs"]
    out: Dict[str, Any] = {"per_seed_v2": {}, "unknowns": [
        "Position occupancy over an episode. Only the initial and final observations are stored, so "
        "'physically stuck in one place' cannot be separated from 'moving without scoring' from the "
        "records alone. Phase A4's bounded replay is the only way to settle it.",
        "Which target each break corresponds to. target_break_ticks records when, never which, so "
        "'always the same easy targets' is not measurable from stored data.",
        "Value-function or advantage estimates per state. Only rollout-level train metrics are stored.",
    ]}
    for seed in SEEDS:
        run = runs[f"m7d_s{seed}_v2"]
        lc = run["learning_curve"]
        fin = run["stages"]["final"]["stochastic"]
        ini = run["stages"]["initial"]["stochastic"]
        det = run["stages"]["final"].get("deterministic") or {}
        out["per_seed_v2"][f"seed{seed}"] = {
            "optimization": run.get("optimization"),
            "deterministic_collapse": det.get("deterministic_collapse"),
            "stochastic_class": lc["stochastic"]["classification"]["class"],
            "deterministic_class": lc.get("deterministic", {}).get("classification", {}).get("class"),
            "final_is_best": lc["final_is_best"],
            "best_checkpoint": lc["best_checkpoint"],
            "first_useful_learning": lc["first_useful_learning"],
            "final_targets_mean": fin["targets_mean"],
            "untrained_targets_mean": ini["targets_mean"],
            "final_fall_rate": fin["fall_rate"],
            "final_horizon_rate": fin["horizon_rate"],
            "final_idle_rate": fin["m7d_idle_rate"],
            "final_tail_fraction": fin["tail_fraction_mean"],
            "final_zero_target_horizon_rate": fin["zero_target_horizon_rate"],
            "final_early_then_stagnant_rate": fin["early_then_stagnant_rate"],
        }
    return out


# -- markdown -----------------------------------------------------------------------------------


def _fmt(x: Any, nd: int = 3) -> str:
    if x is None:
        return "-"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def render_markdown(rep: Mapping[str, Any]) -> str:
    d = rep["definitions"]
    L: List[str] = []
    a = L.append
    a("# RL M7e Phase A: what \"idling\" means in the `btt_reward_v2` policies")
    a("")
    a("Read-only diagnosis over the stored M7d evidence. No training, no broad")
    a("evaluation, no native or submodule change, nothing written inside")
    a("`runs/m7d/`. Generated by `rl/m7e_idle_analysis.py`.")
    a("")
    s = rep["sources"]
    a(f"Rows read: **{s['evaluation_rows']} evaluation**, **{s['training_rows']} training**, "
      f"**{s['random_baseline_rows']} random baseline** = **{s['total_rows']}**.")
    a("")

    a("## Metric definitions")
    a("")
    a("Every metric is defined here before it is used. For one episode `e`:")
    a("")
    a(f"- notation: {d['notation']}")
    for k in ("tail", "tail_fraction", "m7d_idle", "first_target_tick", "gap", "targets_per_1000_ticks",
              "zero_target_horizon", "early_then_stagnant", "targets_before_W", "survival_matched",
              "phase_progress", "action_entropy", "switch_rate", "long_run_share", "full_neutral_share",
              "head_tail_contrast", "final_state_cluster", "learning_curve_class"):
        a(f"- `{k}`: {d[k]}")
    a("")
    a("Evidence classes used throughout: **measured** (read from a stored field),")
    a("**inferred** (derived under a stated assumption), **unknown** (not stored).")
    a("")

    a("## Per-seed v2 summary (final checkpoint, stochastic)")
    a("")
    a("| seed | targets | falls | horizon | M7d idle | tail frac | zero-target horizon | early-then-stagnant | class | final = best |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        f = rep["findings"]["per_seed_v2"][f"seed{seed}"]
        a(f"| {seed} | {_fmt(f['final_targets_mean'],2)} | {_fmt(f['final_fall_rate'],2)} | "
          f"{_fmt(f['final_horizon_rate'],2)} | {_fmt(f['final_idle_rate'],2)} | "
          f"{_fmt(f['final_tail_fraction'],3)} | {_fmt(f['final_zero_target_horizon_rate'],2)} | "
          f"{_fmt(f['final_early_then_stagnant_rate'],2)} | {f['stochastic_class']} | "
          f"{_fmt(f['final_is_best'])} |")
    a("")

    a("## Learning curves (stochastic, mean targets per checkpoint)")
    a("")
    hdr = "| transitions | " + " | ".join(f"s{s}_{c}" for s in SEEDS for c in CONTRACTS) + " |"
    a(hdr)
    a("| --- | " + " | ".join("---" for _ in range(6)) + " |")
    stages_all = sorted({st for r in rep["runs"].values() for st in r["stages"]}, key=stage_order)
    for st in stages_all:
        cells = []
        for seed in SEEDS:
            for c in CONTRACTS:
                b = rep["runs"][f"m7d_s{seed}_{c}"]["stages"].get(st, {}).get("stochastic")
                cells.append(f"{_fmt(b['targets_mean'],2)} / {_fmt(b['fall_rate'],2)}" if b else "-")
        t = _transitions_of(st)
        a(f"| {st} ({t}) | " + " | ".join(cells) + " |")
    a("")
    a("Cell format: mean targets / fall rate.")
    a("")

    a("## Curve classification")
    a("")
    a("| run | mode | class | Theil-Sen (targets / 1e6) | noise scale | last third - first third | best ckpt | final = best |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        for c in CONTRACTS:
            r = rep["runs"][f"m7d_s{seed}_{c}"]
            lc = r["learning_curve"]
            for mode in ("stochastic", "deterministic"):
                if mode not in lc:
                    continue
                cl = lc[mode]["classification"]
                a(f"| m7d_s{seed}_{c} | {mode} | {cl['class']} | {_fmt(cl.get('theil_sen_targets_per_1e6'))} | "
                  f"{_fmt(cl.get('noise_scale_targets_per_1e6'))} | {_fmt(cl.get('third_delta_targets'))} | "
                  f"{lc['best_checkpoint']['transitions'] if mode=='stochastic' else '-'} | "
                  f"{_fmt(lc['final_is_best']) if mode=='stochastic' else '-'} |")
    a("")

    a("## Survival-matched progress (final stochastic)")
    a("")
    a("The M7d idle metric is confounded with survival: an episode that falls at")
    a("tick 900 can neither accumulate a tail nor break a late target. These")
    a("columns restrict both arms to the episodes that actually reached tick `W`,")
    a("so the progress figure is not a survival figure in disguise.")
    a("")
    for seed in SEEDS:
        cmp = rep["comparisons"]["final_stochastic"].get(f"seed{seed}")
        if not cmp:
            continue
        a(f"### Seed {seed}")
        a("")
        a("| window W | v1 survivors | v2 survivors | v1 targets < W | v2 targets < W | v2 - v1 |")
        a("| --- | --- | --- | --- | --- | --- |")
        for row in cmp["survival_matched"]:
            a(f"| {row['window']} | {row['v1_survivors']} | {row['v2_survivors']} | "
              f"{_fmt(row['v1_targets'],3)} | {_fmt(row['v2_targets'],3)} | {_fmt(row['delta'],3)} |")
        a("")

    a("## Phase progress (final stochastic, v2)")
    a("")
    a("Targets broken inside each tick band, over the episodes that reached it.")
    a("A collapsing sequence is the direct signature of progress stopping partway.")
    a("")
    a("| phase | " + " | ".join(f"s{s}_v2 (n)" for s in SEEDS) + " |")
    a("| --- | " + " | ".join("---" for _ in SEEDS) + " |")
    ref = rep["runs"][f"m7d_s{SEEDS[0]}_v2"]["stages"]["final"]["stochastic"]["phase_progress"]
    for i, ph in enumerate(ref):
        cells = []
        for seed in SEEDS:
            pp = rep["runs"][f"m7d_s{seed}_v2"]["stages"]["final"]["stochastic"]["phase_progress"][i]
            cells.append(f"{_fmt(pp['targets_mean'],3)} ({pp['episodes_reaching']})")
        a(f"| {ph['phase']} | " + " | ".join(cells) + " |")
    a("")

    a("## Action behaviour (final stochastic)")
    a("")
    a("| run | joint entropy (bits) | stick entropy | distinct actions/ep | max run (mean) | long-run share | full-neutral share |")
    a("| --- | --- | --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        for c in CONTRACTS:
            b = rep["runs"][f"m7d_s{seed}_{c}"]["stages"]["final"]["stochastic"].get("actions")
            if not b:
                continue
            p = b["pooled"]
            a(f"| m7d_s{seed}_{c} | {_fmt(p['entropy']['joint_bits'])} | {_fmt(p['entropy']['stick_bits'])} | "
              f"{_fmt(b['per_episode']['distinct_joint_actions_mean'],1)} | "
              f"{_fmt(b['per_episode']['max_run_mean'],1)} | {_fmt(p['long_run_share'] if 'long_run_share' in p else None)} | "
              f"{_fmt(p['full_neutral_share'])} |")
    a("")
    a("### Head versus tail (does the tail look different from the scoring part?)")
    a("")
    a("| run | head entropy | tail entropy | delta | head switch | tail switch | delta | tail long-run share |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        for c in CONTRACTS:
            b = rep["runs"][f"m7d_s{seed}_{c}"]["stages"]["final"]["stochastic"].get("actions")
            if not b:
                continue
            h = b["head_tail"]
            a(f"| m7d_s{seed}_{c} | {_fmt(h['head_entropy_bits_mean'])} | {_fmt(h['tail_entropy_bits_mean'])} | "
              f"{_fmt(h['entropy_delta_mean'])} | {_fmt(h['head_switch_rate_mean'])} | "
              f"{_fmt(h['tail_switch_rate_mean'])} | {_fmt(h['switch_delta_mean'])} | "
              f"{_fmt(h['tail_long_run_share_mean'])} |")
    a("")

    a("## Final-state clusters (measured: final position only)")
    a("")
    a("Binned on a 200-unit lattice. This is a final-state fact; it cannot show")
    a("where a policy spent the tail. Trajectory occupancy is **unknown** from")
    a("stored data.")
    a("")
    a("| run | episodes | distinct bins | modal bin share | x median | x p10-p90 |")
    a("| --- | --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        for c in CONTRACTS:
            fs = rep["runs"][f"m7d_s{seed}_{c}"]["stages"]["final"]["stochastic"].get("final_state")
            if not fs:
                continue
            a(f"| m7d_s{seed}_{c} | {fs['episodes_with_final_position']} | {fs['distinct_bins']} | "
              f"{_fmt(fs['modal_bin_share'],2)} | {_fmt(fs['position_x_median'],0)} | "
              f"{_fmt(fs['position_x_p10'],0)} to {_fmt(fs['position_x_p90'],0)} |")
    a("")

    a("## Optimization state at the budget's end (measured, SB3 rollout metrics)")
    a("")
    a("`ent_coef = 0.0` in every run, so nothing holds the policy entropy open:")
    a("what `H` does is what the optimizer chose to do.")
    a("")
    a("| run | H start (nats) | H end | fraction of max | slope / 1e6 | last-third slope | deceleration | still concentrating | explained variance |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        for c in CONTRACTS:
            o = rep["runs"][f"m7d_s{seed}_{c}"].get("optimization")
            if not o:
                continue
            a(f"| m7d_s{seed}_{c} | {_fmt(o['entropy_nats_start'])} | {_fmt(o['entropy_nats_end'])} | "
              f"{_fmt(o['entropy_fraction_end'],3)} | {_fmt(o['entropy_slope_per_1e6'])} | "
              f"{_fmt(o['entropy_slope_last_third_per_1e6'])} | {_fmt(o['deceleration'],2)} | "
              f"{_fmt(o['still_concentrating'])} | {_fmt(o['explained_variance_mean_last_third'],3)} |")
    a("")

    a("## Deterministic (argmax) collapse")
    a("")
    a("| run | max run (ticks) | length | collapse share | joint entropy (bits) | distinct actions | collapsed |")
    a("| --- | --- | --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        for c in CONTRACTS:
            dc = rep["runs"][f"m7d_s{seed}_{c}"]["stages"]["final"].get("deterministic", {}).get(
                "deterministic_collapse")
            if not dc:
                continue
            a(f"| m7d_s{seed}_{c} | {_fmt(dc['max_run_ticks'],0)} | {_fmt(dc['episode_length'],0)} | "
              f"{_fmt(dc['collapse_share'],3)} | {_fmt(dc['joint_entropy_bits'])} | "
              f"{_fmt(dc['distinct_joint_actions'],0)} | {_fmt(dc['collapsed'])} |")
    a("")

    a("## Idle against falling, inside v2's own curve")
    a("")
    a("| seed | fall first -> last | idle first -> last | tail frac first -> last | corr(fall, idle) |")
    a("| --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        iv = rep["comparisons"]["idle_vs_fall"].get(f"seed{seed}")
        if not iv:
            continue
        a(f"| {seed} | {_fmt(iv['fall_first'],2)} -> {_fmt(iv['fall_last'],2)} | "
          f"{_fmt(iv['idle_first'],2)} -> {_fmt(iv['idle_last'],2)} | "
          f"{_fmt(iv['tail_fraction_first'],3)} -> {_fmt(iv['tail_fraction_last'],3)} | "
          f"{_fmt(iv['correlation_fall_idle'])} |")
    a("")

    rp = rep.get("replay")
    if rp:
        a("## Phase A4: bounded observational replay")
        a("")
        a(f"{rp['episodes']} selected episodes were re-submitted to fresh processes from tick 0")
        a("using their own canonical native actions. Every one reproduced its stored")
        a("record exactly (targets, break ticks and consumed-tick alignment), so the")
        a("trajectories below describe the recorded episodes and not a new rollout.")
        a("")
        a("This is the only evidence in the report that speaks to *where* the")
        a("character was during the tail; the stored records hold the first and last")
        a("observation only.")
        a("")
        a("| role | run | tail ticks | tail path length | tail x range | distinct 100-cells | stationary share | speed/tick |")
        a("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in rp["records"]:
            t = (r.get("trajectory") or {}).get("tail")
            if not t or "path_length" not in t:
                continue
            a(f"| {r['role']} | {r['run']} | {t['ticks']} | {_fmt(t['path_length'],0)} | "
              f"{_fmt(t['x_range'],0)} | {t['distinct_cells_100']} | {_fmt(t['stationary_share'],2)} | "
              f"{_fmt(t['mean_speed_per_tick'],1)} |")
        a("")
        a("| role | run | targets | whole-episode x min | x max | x range | distinct 100-cells | path length |")
        a("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in rp["records"]:
            t = (r.get("trajectory") or {}).get("whole")
            if not t or "path_length" not in t:
                continue
            a(f"| {r['role']} | {r['run']} | {r['replay_targets']} | {_fmt(t['x_min'],0)} | "
              f"{_fmt(t['x_max'],0)} | {_fmt(t['x_range'],0)} | {t['distinct_cells_100']} | "
              f"{_fmt(t['path_length'],0)} |")
        a("")

    a("## Unknowns")
    a("")
    for u in rep["findings"]["unknowns"]:
        a(f"- {u}")
    a("")
    return "\n".join(L) + "\n"


# -- self-tests ---------------------------------------------------------------------------------


def _tests() -> int:
    fails: List[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"  PASS  {name}")
        else:
            fails.append(name)
            print(f"  FAIL  {name} {detail}")

    print("m7e metric definitions")
    # tail / idle, against the M7d definition
    check("tail with breaks", tail_ticks(3600, [37, 890, 1159]) == 3600 - 1160)
    check("tail without breaks", tail_ticks(3600, []) == 3600)
    check("tail last tick", tail_ticks(100, [99]) == 0)
    check("tail_fraction", abs(tail_fraction(3600, [1799]) - (3600 - 1800) / 3600) < 1e-12)
    check("tail_fraction zero length", tail_fraction(0, []) is None)
    check("idle true", m7d_idle("horizon", 3600, [1000]) is True)
    check("idle boundary exactly 1800", m7d_idle("horizon", 3600, [1799]) is True)
    check("idle boundary 1799", m7d_idle("horizon", 3600, [1800]) is False)
    check("idle needs horizon", m7d_idle("fall", 3600, []) is False)
    check("idle no breaks", m7d_idle("horizon", 2000, []) is True)

    # gaps / first target
    check("gaps", target_gaps([10, 30, 100]) == [20, 70])
    check("gaps single", target_gaps([10]) == [])
    check("gaps unordered input sorted", target_gaps([100, 10, 30]) == [20, 70])
    check("first target", opening_gap([100, 10, 30]) == 10)
    check("first target none", opening_gap([]) is None)

    # rates
    check("tpk", abs(targets_per_1000(2000, 4) - 2.0) < 1e-12)
    check("targets_before strict", targets_before([100, 200, 300], 200) == 1)
    check("targets_in_window half open", targets_in_window([100, 200, 300], 100, 300) == 2)
    check("zero target horizon", zero_target_horizon("horizon", 0) is True)
    check("zero target horizon needs horizon", zero_target_horizon("fall", 0) is False)
    check("early_then_stagnant", early_then_stagnant(3600, [100]) is True)
    check("early_then_stagnant late first", early_then_stagnant(3600, [700]) is False)
    check("early_then_stagnant short tail", early_then_stagnant(3600, [100, 3000]) is False)
    check("early_then_stagnant needs a break", early_then_stagnant(3600, []) is False)

    # entropy
    check("entropy single symbol", shannon_bits([10]) == 0.0)
    check("entropy uniform 8", abs(shannon_bits([1] * 8) - 3.0) < 1e-12)
    check("entropy uniform 72", abs(shannon_bits([1] * 72) - math.log2(72)) < 1e-12)
    check("entropy empty", shannon_bits([]) == 0.0)

    # runs / switching
    check("run_lengths", run_lengths([1, 1, 2, 2, 2, 3]) == [2, 3, 1])
    check("run_lengths empty", run_lengths([]) == [])
    check("switch all change", switch_rate([1, 2, 3, 4]) == 1.0)
    check("switch none", switch_rate([1, 1, 1, 1]) == 0.0)
    check("switch single", switch_rate([1]) is None)
    check("long_run_share", abs(long_run_share([1] * 60 + [2] * 10, 60) - 60 / 70) < 1e-12)
    check("long_run_share none", long_run_share([], 60) is None)

    # decoding, against the frozen Track 1 tables
    check("decode neutral none", decode_action(0, 0, 0) == (0, 0))
    check("decode right A", decode_action(0x8000, 80, 0) == (1, 1))
    check("decode down-left Z", decode_action(0x2000, -80, -80) == (6, 7))
    check("decode C-up", decode_action(0x0008, 0, 80) == (3, 3))
    check("decode C-left", decode_action(0x0002, 0, 0) == (0, 4))
    check("decode outside track1 stick", decode_action(0, 40, 0)[0] is None)
    check("decode outside track1 button", decode_action(0x1000, 0, 0)[1] is None)
    names_ok = len(STICK_NAMES) == 9 and len(BUTTON_NAMES) == 8 and len(STICK_TABLE) == 9 and len(BUTTON_WORDS) == 8
    check("track1 table sizes", names_ok)

    # analyse_actions on a synthetic stream
    rows = [{"buttons": 0, "stick_x": 0, "stick_y": 0}] * 50 + [{"buttons": 0x8000, "stick_x": 80, "stick_y": 0}] * 50
    st = analyse_actions(rows)
    check("stats ticks", st.ticks == 100)
    check("stats distinct", st.distinct_joint == 2)
    check("stats entropy 1 bit", abs(st.entropies()["joint_bits"] - 1.0) < 1e-12)
    check("stats switch one change", abs(st.switch - 1 / 99) < 1e-12)
    check("stats max run", st.max_run == 50)
    check("stats full neutral", abs(st.full_neutral_share - 0.5) < 1e-12)
    check("stats no undecodable", st.undecodable == 0)

    # curve classification
    up = [(i * 100_000, 3.0 + i * 0.1) for i in range(11)]
    down = [(i * 100_000, 4.0 - i * 0.1) for i in range(11)]
    flat = [(i * 100_000, 3.5) for i in range(11)]
    check("classify improving", classify_curve(up)["class"] == "improving")
    check("classify regressing", classify_curve(down)["class"] == "regressing")
    check("classify plateaued", classify_curve(flat)["class"] == "plateaued")
    check("classify too few", classify_curve(up[:3])["class"] == "too_noisy")
    check("classify argmax", classify_curve(up)["argmax_transitions"] == 1_000_000)

    # helpers
    check("quantile median", abs(_quantile([1, 2, 3], 0.5) - 2.0) < 1e-12)
    check("quantile p90", abs(_quantile([0, 10], 0.9) - 9.0) < 1e-12)
    check("pearson perfect", abs(_pearson([1, 2, 3], [2, 4, 6]) - 1.0) < 1e-12)
    check("pearson anti", abs(_pearson([1, 2, 3], [6, 4, 2]) + 1.0) < 1e-12)
    check("pearson degenerate", _pearson([1, 1, 1], [1, 2, 3]) is None)
    check("theil-sen", abs(_theil_sen([0, 1, 2], [0, 2, 4]) - 2.0) < 1e-12)

    # Episode wiring
    e = Episode(run="r", seed=0, contract="v2", stage="final", transitions=1, mode="stochastic",
                episode_id="x", length=3600, targets=3, end_reason="horizon", breaks=[37, 890, 1159],
                digest=None, artifact_dir=None)
    check("episode tail", e.tail == 2440)
    check("episode idle", e.idle is True)
    check("episode first", e.first_target == 37)
    check("episode early stagnant", e.early_stagnant is True)
    check("episode objective key", e.objective_key() == (0, 3, 0))
    check("episode clear key", Episode(run="r", seed=0, contract="v2", stage="final", transitions=1,
                                       mode="stochastic", episode_id="x", length=447, targets=10,
                                       end_reason="clear", breaks=[], digest=None,
                                       artifact_dir=None).objective_key() == (1, 10, 0))

    # survival matching on a hand-built set
    a1 = Episode(run="r", seed=0, contract="v1", stage="final", transitions=1, mode="stochastic",
                 episode_id="a", length=900, targets=3, end_reason="fall", breaks=[100, 200, 300],
                 digest=None, artifact_dir=None)
    a2 = Episode(run="r", seed=0, contract="v1", stage="final", transitions=1, mode="stochastic",
                 episode_id="b", length=3600, targets=4, end_reason="horizon", breaks=[100, 200, 300, 2000],
                 digest=None, artifact_dir=None)
    sm = {row["window"]: row for row in survival_matched([a1, a2], (600, 1800, 3600))}
    check("survival W=600 both survive", sm[600]["survivors"] == 2)
    check("survival W=600 targets", abs(sm[600]["targets_in_window_mean"] - 3.0) < 1e-12)
    check("survival W=1800 one survivor", sm[1800]["survivors"] == 1)
    check("survival W=3600 targets exclude boundary", abs(sm[3600]["targets_in_window_mean"] - 4.0) < 1e-12)
    pp = {row["phase"]: row for row in phase_progress([a1, a2], (0, 600, 1800, 3600))}
    check("phase 0-600 both", pp["0-600"]["episodes_reaching"] == 2)
    check("phase 1800-3600 one", pp["1800-3600"]["episodes_reaching"] == 1)
    check("phase 1800-3600 targets", abs(pp["1800-3600"]["targets_mean"] - 1.0) < 1e-12)

    # optimization telemetry helpers
    check("ols slope", abs(_ols_slope([0, 1, 2], [0, 3, 6]) - 3.0) < 1e-12)
    check("ols slope flat", _ols_slope([0, 1, 2], [5, 5, 5]) == 0.0)
    check("ols slope degenerate", _ols_slope([1, 1], [1, 2]) is None)
    check("max conditional entropy", abs(MAX_CONDITIONAL_ENTROPY_NATS - (math.log(9) + math.log(8))) < 1e-12)
    check("max conditional entropy value", abs(MAX_CONDITIONAL_ENTROPY_NATS - 4.2767) < 1e-3)

    # deterministic collapse
    col = deterministic_collapse({"length_mean": 3600.0, "actions": {
        "per_episode": {"max_run_mean": 3402.0, "distinct_joint_actions_mean": 16.0},
        "pooled": {"entropy": {"joint_bits": 0.4773}}}})
    check("collapse share", abs(col["collapse_share"] - 3402 / 3600) < 1e-4)
    check("collapse flagged", col["collapsed"] is True)
    not_col = deterministic_collapse({"length_mean": 3600.0, "actions": {
        "per_episode": {"max_run_mean": 354.0, "distinct_joint_actions_mean": 18.0},
        "pooled": {"entropy": {"joint_bits": 2.9888}}}})
    check("collapse not flagged", not_col["collapsed"] is False)
    check("collapse needs actions", deterministic_collapse({"length_mean": 3600.0}) is None)
    check("collapse needs a block", deterministic_collapse(None) is None)

    # the report must never write into runs/m7d
    check("outputs are under docs/", DOC_MD.parent.name == "docs" and DOC_JSON.parent.name == "docs")

    print()
    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("PASS all metric cases")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="M7e Phase A idle diagnosis (read-only)")
    ap.add_argument("--test", action="store_true", help="run the metric self-tests and exit")
    ap.add_argument("--no-actions", action="store_true", help="skip the action-stream pass")
    ap.add_argument("--replay-plan", action="store_true", help="print the Phase A4 replay selection and exit")
    ap.add_argument("--replay", action="store_true", help="run the bounded observational replay probe")
    ap.add_argument("--replay-limit", type=int, default=None, help="cap the number of replayed episodes")
    ap.add_argument("--replay-out", type=Path, default=REPLAY_JSON)
    ap.add_argument("--md", type=Path, default=DOC_MD)
    ap.add_argument("--json", dest="json_out", type=Path, default=DOC_JSON)
    args = ap.parse_args(argv)

    if args.test:
        return _tests()

    if args.replay_plan:
        plan = replay_plan(load_evaluation_episodes())
        print(json.dumps(plan, indent=2))
        return 0

    if args.replay:
        plan = replay_plan(load_evaluation_episodes())
        out = replay_probe(plan["episodes"], limit=args.replay_limit)
        args.replay_out.parent.mkdir(parents=True, exist_ok=True)
        args.replay_out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        bad = [r["episode_id"] for r in out["records"] if not r["ok"]]
        print(f"replayed {out['episodes']} episode(s); wrote {args.replay_out}")
        if bad:
            print(f"MISMATCH in {len(bad)}: {bad}")
            return 1
        print("all replays reproduced their record exactly")
        return 0

    rep = build(with_actions=not args.no_actions)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(rep, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    args.md.write_text(render_markdown(rep), encoding="utf-8")
    print(f"rows: {rep['sources']['total_rows']}")
    print(f"wrote {args.json_out}")
    print(f"wrote {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
