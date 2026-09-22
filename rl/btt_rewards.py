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
identify itself as v1 or v2. No other shaping term exists.

The per-step arithmetic delegates the target / step / clear terms to the
unchanged M5 reward_v1() (rl/btt_learning.py is not modified); only the
failure term is added here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from btt_learning import RewardBreakdown, RewardV1Config, reward_v1

REWARD_V1_ID = "btt_reward_v1"
REWARD_V2_ID = "btt_reward_v2"
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


REWARD_V1 = RewardContract(REWARD_V1_ID, 1.0, -0.001, 10.0, 0.0)
REWARD_V2 = RewardContract(REWARD_V2_ID, 1.0, -0.001, 10.0, -5.0)
CANONICAL_REWARD_CONTRACTS: Dict[str, RewardContract] = {REWARD_V1_ID: REWARD_V1, REWARD_V2_ID: REWARD_V2}
DEFAULT_REWARD_CONTRACT = REWARD_V1


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
    return make_reward_contract(rid, values)


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
    if clear and native_failure:
        raise RewardContractError("a step cannot be both a native clear and a native failure")
    base = reward_v1(previous_targets, current_targets, clear, contract.v1_config())
    failure_term = float(contract.failure_penalty) if native_failure else 0.0
    return RewardTerms(base.total + failure_term, base.newly_broken, base.target_term, base.step_term, base.clear_term,
                       failure_term)


def expected_return(targets_broken: int, steps: int, *, cleared: bool, native_failure: bool = False,
                    contract: RewardContract = REWARD_V1) -> float:
    """Closed form of an episode return under a contract (for checks; wrappers accumulate per step)."""
    if cleared and native_failure:
        raise RewardContractError("an episode cannot be both cleared and a native failure")
    return (targets_broken * contract.target_broken + steps * contract.per_step
            + (contract.clear_bonus if cleared else 0.0) + (contract.failure_penalty if native_failure else 0.0))
