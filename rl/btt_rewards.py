#!/usr/bin/env python3
"""M7b: versioned reward contracts for BattleShip Mario Break the Targets.

Two canonical contracts exist. Their numeric values are frozen and enforced:

    btt_reward_v1  (M5, unchanged)         btt_reward_v2  (M7b)
        +1.0   per newly broken target         +1.0   per newly broken target
        -0.001 per consumed native tick        -0.001 per consumed native tick
        +10.0  once, on the native clear       +10.0  once, on the native clear
        no native-failure penalty              -5.0   once, on termination_reason == "native_failure"

The v2 failure penalty is applied exactly once, on the terminal step whose
termination reason is the M7 native failure (btt_native_failure_v1: the
first post-update observation with game_status 5, targets left and no
native EpisodeEnded). It is never applied to a successful clear, a horizon
truncation, a manual interruption, a startup failure, a transport or
protocol failure, a worker exception, process cleanup or an administrative
cancellation: none of those steps carries termination_reason
"native_failure" (lifecycle failures reach the learner as a truncation with
reward 0.0 from Track1PolicyWrapper, and interruptions never produce a step).

Regression facts (proved by rl/m7b_config_tests.py and rl/m7b_smoke.py):
the 447-step TAS clear returns 19.553 under v1 and v2; the known 432-step
no-target fall returns -0.432 under v1 and -5.432 under v2; a horizon
truncation receives no terminal term under either contract. At the
3600-tick horizon the accumulated step cost is at most -3.6, so under v2 an
early fall can never outscore surviving to the horizon with the same
number of targets.

A custom contract (arbitrary finite values) is allowed only under a
noncanonical identity derived from its own values
(btt_reward_custom_<12 hex of the reward fingerprint>); it can never
identify itself as v1, v2 or v3. No other shaping term exists in v1 / v2.

The per-step arithmetic delegates the target / step / clear terms to the
unchanged M5 reward_v1() (rl/btt_learning.py is not modified); only the
failure term is added here.

M7j adds a third canonical contract, btt_reward_v3 (opt-in; every existing
profile keeps v1 or v2 and v1 / v2 values, identities and JSON are
unchanged). v3 = the v2 terms plus three route terms that need the native
target identity (SSB64_RL_TARGET_DIAG=1) and the native position:

    +3.0 + 2.0 * (3600 - n) / 3600   once, when the seven right-side targets
                                     {0, 2, 3, 4, 5, 7, 9} are all broken;
                                     n = consumed_tick + 1 of that step
    +2.0                             once, on the first left-floor landing
                                     after a qualified over-wall entry
    -1.0 instead of -5.0             native-failure penalty after that landing

Its constants live in RouteRewardContract (below, fingerprinted through
to_json()["route"]); its per-step arithmetic lives in rl/btt_reward_v3.py.
reward_step() / expected_return() refuse a route contract: they cannot see
target identity or position.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from btt_learning import RewardBreakdown, RewardV1Config, reward_v1

REWARD_V1_ID = "btt_reward_v1"
REWARD_V2_ID = "btt_reward_v2"
REWARD_V3_ID = "btt_reward_v3"
REWARD_CUSTOM_PREFIX = "btt_reward_custom_"
REWARD_CUSTOM_REQUEST = "custom"   # the value written in [contracts].reward of a TOML profile
REWARD_VALUE_FIELDS = ("target_broken", "per_step", "clear_bonus", "failure_penalty")
NATIVE_FAILURE_REASON = "native_failure"


class RewardContractError(ValueError):
    """A reward contract record is inconsistent (wrong values for a canonical id, unknown id, bad types)."""


@dataclass(frozen=True)
class RewardContract:
    """Identity plus the four constants. Plain data: picklable for spawn workers."""

    contract: str
    target_broken: float
    per_step: float
    clear_bonus: float
    failure_penalty: float

    @property
    def canonical(self) -> bool:
        return self.contract in CANONICAL_REWARD_CONTRACTS

    def values(self) -> Dict[str, float]:
        return {k: float(getattr(self, k)) for k in REWARD_VALUE_FIELDS}

    def to_json(self) -> Dict[str, Any]:
        return {"contract": self.contract, **self.values()}

    def v1_config(self) -> RewardV1Config:
        """The three M5 constants (the M5 function computes the target, step and clear terms)."""
        return RewardV1Config(target_broken=self.target_broken, per_step=self.per_step, clear_bonus=self.clear_bonus)


ROUTE_RULE_V3 = "btt_route_rule_v3"          # the event rules implemented by rl/btt_reward_v3.py
ROUTE_FIELDS = ("rule", "right_target_ids", "right_sweep_bonus", "right_sweep_timing_max", "horizon_ticks",
                "crossing_landing_bonus", "post_landing_failure_penalty", "left_boundary_x", "wall_top_y",
                "under_stage_y", "entry_y_tolerance", "landing_floor_y", "landing_floor_x_min", "landing_floor_x_max",
                "landing_tolerance")


@dataclass(frozen=True)
class RouteRewardContract(RewardContract):
    """M7j btt_reward_v3: the four v2 constants plus the frozen route constants.

    Geometry = native collision data of Mario's Break the Targets (decomp/src/relocData/124_GRBonus1MarioFile2.c; the
    pinned line table m7g_spatial.EXPECTED_LINES, which rl/m7j_tests.py compares with every value): the main solid's left face
    (line 17, x = -2100, y -2850..3000), the ledge top (line 0, y = 3000), the main solid's underside (line 6,
    y = -2850) and the only left-side floor (line 3, y = -1950, x -3900..-2700). Right targets = the M7f native IDs
    right of the wall. The event rules themselves are rl/btt_reward_v3.py (identity `rule`)."""

    rule: str = ROUTE_RULE_V3
    right_target_ids: Tuple[int, ...] = (0, 2, 3, 4, 5, 7, 9)
    right_sweep_bonus: float = 3.0
    right_sweep_timing_max: float = 2.0
    horizon_ticks: int = 3600
    crossing_landing_bonus: float = 2.0
    post_landing_failure_penalty: float = -1.0
    left_boundary_x: float = -2100.0
    wall_top_y: float = 3000.0
    under_stage_y: float = -2850.0
    entry_y_tolerance: float = 1.0
    landing_floor_y: float = -1950.0
    landing_floor_x_min: float = -3900.0
    landing_floor_x_max: float = -2700.0
    landing_tolerance: float = 1.0

    def route_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k in ROUTE_FIELDS:
            v = getattr(self, k)
            out[k] = list(v) if isinstance(v, tuple) else (v if isinstance(v, str) else
                                                           (int(v) if k == "horizon_ticks" else float(v)))
        return out

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "route": self.route_json()}


REWARD_V1 = RewardContract(REWARD_V1_ID, 1.0, -0.001, 10.0, 0.0)
REWARD_V2 = RewardContract(REWARD_V2_ID, 1.0, -0.001, 10.0, -5.0)
REWARD_V3 = RouteRewardContract(REWARD_V3_ID, 1.0, -0.001, 10.0, -5.0)


# M7k: btt_reward_v3_t2 = btt_reward_v3 unchanged plus a one-time, time-sensitive credit on the moving target (native
# ID 2): moving_target_timing_max * (3600 - n) / 3600 on the step whose reply first shows it broken, n = consumed_tick
# + 1 (the v3 timing convention). Arithmetic: rl/btt_reward_t2.py. btt_reward_v3's constants, JSON and code path are
# unchanged; the new constants are fingerprinted inside this contract's route block ("moving_target").
REWARD_V3_T2_ID = "btt_reward_v3_t2"
MOVING_TARGET_RULE_V1 = "btt_moving_target_timing_v1"


@dataclass(frozen=True)
class MovingTargetRouteRewardContract(RouteRewardContract):
    moving_target_id: int = 2
    moving_target_timing_max: float = 2.0
    moving_target_rule: str = MOVING_TARGET_RULE_V1

    def route_json(self) -> Dict[str, Any]:
        out = super().route_json()
        out["moving_target"] = {"rule": self.moving_target_rule, "target_id": int(self.moving_target_id),
                                "timing_max": float(self.moving_target_timing_max)}
        return out


REWARD_V3_T2 = MovingTargetRouteRewardContract(REWARD_V3_T2_ID, 1.0, -0.001, 10.0, -5.0)
CANONICAL_REWARD_CONTRACTS: Dict[str, RewardContract] = {REWARD_V1_ID: REWARD_V1, REWARD_V2_ID: REWARD_V2,
                                                         REWARD_V3_ID: REWARD_V3, REWARD_V3_T2_ID: REWARD_V3_T2}
DEFAULT_REWARD_CONTRACT = REWARD_V1
# The native flags a contract needs in every process of its workers (v3 reads the M7f target-identity diagnostic).
REWARD_EXTRA_ENV: Dict[str, Tuple[Tuple[str, str], ...]] = {REWARD_V3_ID: (("SSB64_RL_TARGET_DIAG", "1"),),
                                                            REWARD_V3_T2_ID: (("SSB64_RL_TARGET_DIAG", "1"),)}


def is_route_contract(contract: RewardContract) -> bool:
    return isinstance(contract, RouteRewardContract)


def reward_extra_env(contract: RewardContract) -> Tuple[Tuple[str, str], ...]:
    """Native flags the contract requires (none for v1 / v2 / custom)."""
    return REWARD_EXTRA_ENV.get(contract.contract, ())


def reward_values_fingerprint(values: Mapping[str, float]) -> str:
    """sha256 of the canonical JSON of the four constants (the reward part of the semantic fingerprint)."""
    canon = {k: float(values[k]) for k in REWARD_VALUE_FIELDS}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def custom_reward_id(values: Mapping[str, float]) -> str:
    return REWARD_CUSTOM_PREFIX + reward_values_fingerprint(values)[:12]


def _finite(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RewardContractError(f"reward.{name}: expected a number, got {value!r}")
    v = float(value)
    if not math.isfinite(v):
        raise RewardContractError(f"reward.{name}: value must be finite, got {value!r}")
    return v


def make_reward_contract(requested: str, values: Mapping[str, Any]) -> RewardContract:
    """Build a contract from a requested id and four values, enforcing canonical values.

    `requested` is a canonical id (values must match exactly), "custom" (id
    derived from the values) or an already-derived custom id (values must
    reproduce it)."""
    vals = {k: _finite(k, values[k]) for k in REWARD_VALUE_FIELDS if k in values}
    missing = [k for k in REWARD_VALUE_FIELDS if k not in vals]
    if missing:
        raise RewardContractError(f"reward: missing value(s) {missing}")
    if requested in CANONICAL_REWARD_CONTRACTS:
        canonical = CANONICAL_REWARD_CONTRACTS[requested]
        diffs = {k: {"expected": canonical.values()[k], "got": vals[k]} for k in REWARD_VALUE_FIELDS
                 if canonical.values()[k] != vals[k]}
        if diffs:
            raise RewardContractError(f"reward: {requested} is a canonical contract with frozen values; "
                                      f"mismatched {json.dumps(diffs, sort_keys=True)} (use contracts.reward = "
                                      f"\"{REWARD_CUSTOM_REQUEST}\" for a custom experiment)")
        return canonical
    derived = custom_reward_id(vals)
    if requested == REWARD_CUSTOM_REQUEST:
        return RewardContract(derived, **vals)
    if requested.startswith(REWARD_CUSTOM_PREFIX):
        if requested != derived:
            raise RewardContractError(f"reward: custom id {requested!r} does not match its values (expected {derived!r})")
        return RewardContract(derived, **vals)
    raise RewardContractError(f"reward: unknown contract id {requested!r} (known: {sorted(CANONICAL_REWARD_CONTRACTS)}, "
                              f"or {REWARD_CUSTOM_REQUEST!r})")


def reward_contract_from_json(record: Optional[Mapping[str, Any]], *, contract_id: Optional[str] = None) -> RewardContract:
    """Rebuild a contract from a stored `reward_constants` record.

    Legacy M7a records (checkpoint.json / artifacts written before M7b)
    carry {contract: btt_reward_v1, target_broken, per_step, clear_bonus}
    and no failure_penalty: they are v1 with a 0.0 penalty by definition and
    are never reinterpreted as v2. A record whose id is v2 must carry the v2
    values."""
    if record is None:
        if contract_id == REWARD_V1_ID or contract_id is None:
            return REWARD_V1
        raise RewardContractError(f"reward: no reward_constants record for contract {contract_id!r}")
    rid = str(record.get("contract") or contract_id or REWARD_V1_ID)
    if contract_id is not None and rid != contract_id:
        raise RewardContractError(f"reward: contract id {contract_id!r} disagrees with reward_constants.contract {rid!r}")
    values = {k: record[k] for k in REWARD_VALUE_FIELDS if k in record}
    if "failure_penalty" not in values:
        if rid != REWARD_V1_ID:
            raise RewardContractError(f"reward: record for {rid!r} lacks failure_penalty; only legacy v1 records may omit it")
        values["failure_penalty"] = 0.0
    contract = make_reward_contract(rid, values)
    # M7j: a route contract's record must carry its frozen route block exactly; no other record may carry one.
    if is_route_contract(contract):
        if record.get("route") != contract.route_json():
            raise RewardContractError(f"reward: record for {rid!r} does not carry the frozen route constants "
                                      f"(got {record.get('route')!r})")
    elif "route" in record:
        raise RewardContractError(f"reward: record for {rid!r} carries route constants; only btt_reward_v3 has them")
    return contract


# -- per-step arithmetic -------------------------------------------------------------------------------


@dataclass(frozen=True)
class RewardTerms:
    """One step's reward under a contract: the M5 breakdown plus the failure term."""

    total: float
    newly_broken: int
    target_term: float
    step_term: float
    clear_term: float
    failure_term: float

    def to_json(self) -> Dict[str, Any]:
        return {"total": self.total, "newly_broken": self.newly_broken, "target_term": self.target_term,
                "step_term": self.step_term, "clear_term": self.clear_term, "failure_term": self.failure_term}

    def m5_breakdown(self) -> RewardBreakdown:
        """The M5-shaped view (without the failure term); used for M5-compatible trackers and info keys."""
        return RewardBreakdown(self.total, self.newly_broken, self.target_term, self.step_term, self.clear_term)


def reward_step(previous_targets: Optional[int], current_targets: Optional[int], *, clear: bool,
                native_failure: bool, contract: RewardContract = REWARD_V1) -> RewardTerms:
    """The reward of one native step under `contract`.

    clear: the step returned the native EpisodeEnded result (clear bonus and
    the targets_remaining == 0 check, exactly as M5). native_failure: the step
    is the M7 native-failure termination. Both true is a contract violation."""
    if is_route_contract(contract):
        raise RewardContractError(f"{contract.contract} needs target identity and position: use btt_reward_v3")
    if clear and native_failure:
        raise RewardContractError("a step cannot be both a native clear and a native failure")
    base = reward_v1(previous_targets, current_targets, clear, contract.v1_config())
    failure_term = float(contract.failure_penalty) if native_failure else 0.0
    return RewardTerms(base.total + failure_term, base.newly_broken, base.target_term, base.step_term, base.clear_term,
                       failure_term)


def expected_return(targets_broken: int, steps: int, *, cleared: bool, native_failure: bool = False,
                    contract: RewardContract = REWARD_V1) -> float:
    """Closed form of an episode return under a contract (for checks; wrappers accumulate per step)."""
    if is_route_contract(contract):
        raise RewardContractError(f"{contract.contract}: use btt_reward_v3.expected_return_v3")
    if cleared and native_failure:
        raise RewardContractError("an episode cannot be both cleared and a native failure")
    return (targets_broken * contract.target_broken + steps * contract.per_step
            + (contract.clear_bonus if cleared else 0.0) + (contract.failure_penalty if native_failure else 0.0))
