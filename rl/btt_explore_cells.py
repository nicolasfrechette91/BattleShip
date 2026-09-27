"""btt_explore_cells_v1: a count-based novelty credit over spatial cells (M7o), added to an UNCHANGED reward contract.

Pure arithmetic (no game, no gym, no SB3). The opt-in worker wrapper is rl/m7o_explore_env.py; a profile enables it
with the [exploration] table (rl/experiment_config.py). Everything below is derived from native geometry, contacts and
character state: nothing names a stage coordinate, a target, a route or a platform cycle.

Contract (docs/rl_exploration_credit_m7o_contract.json is generated from `contract_description()`):

  grid        square cells of side s = max(map width, map height) / grid_divisor, where the map bounds are the
              read-only spatial diagnostic's `map_bounds` ([top, bottom, right, left]) of the tick-0 observe reply;
              cell = (floor(x / s), floor(y / s)) in world units with the world origin as grid origin; no bounds
              clipping (a live fighter outside the map is simply in an outer cell; it is falling and its credit is
              pending, see below);
  eligible    a live post-update observation (fighter_valid 1, btt_active 1) whose action class (the v3 action-class
              table, derived from the decomp status enums) is not damage / dead / appear_entry / other / unmapped;
              an ineligible step marks nothing, banks nothing and keeps pending credit pending;
  first visit the first eligible step of the episode in a cell; the tick-0 reset observation marks its cell as
              visited without credit (there is no step and no reward at the reset);
  amount      beta * w(n) with n = the number of EARLIER episodes of this worker slot in which the cell was visited
              (harmonic: w(n) = 1 / (1 + n)); computed when the cell is first visited;
  grounded    ground_air_state 0 on an eligible step: the amount is banked on that step (subject to the cap);
  airborne    otherwise the amount is PENDING; every pending amount is banked, in visit order, on the next eligible
              grounded step of the episode (a landing on any floor, static or moving); pending amounts are VOIDED
              when the episode ends by native failure, at the horizon, or by any end before such a landing;
  cap         banked credit per episode <= cap; a credit that would exceed it is reduced to the remainder, the rest
              is dropped (recorded as capped); pending amounts keep their computed value until banking;
  banking is permanent: a fall after a landing does not undo what that landing banked (no claw-back rule exists);
  counts      at the end of every episode, n increases by one for EVERY cell the episode visited, whether its credit
              was banked, voided or capped (a cell reached only by fatal flights still becomes less novel);
  learner     the banked amount of a step is added to the contract reward of THAT step (grounded credit on the
              visiting step, airborne credit on the landing step), so it enters the PPO rollout there and earlier
              flight actions are credited through the discounted return; nothing is attributed retroactively;
  tables      one table per worker SLOT (the persistent logical environment of one rank inside its subprocess);
              it survives game-process restarts and standby promotions (which never touch the Python worker), is
              written after every episode to <worker_dir>/explore_table.json and reloaded when a worker of the same
              run is constructed again (resume); a fresh run starts empty; nothing is ever imported across runs;
  episode     the visited set and the pending list are cleared at every reset; they are never checkpointed (a
              checkpoint is written between rollouts, episodes in flight continue in their worker);
  logging     per step: banked, pending_added, voided, capped; per episode: the record below; the contract reward
              (btt_reward_v2) keeps its own terms, rows and closed form unchanged.

Not observed by the policy: the visited set and the tables are training-time state of the reward, not of the
observation contract (documented limitation, docs/rl_exploration_credit_proposal_m7o.md section 3).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CONTRACT_ID = "btt_explore_cells_v1"
TABLE_SCHEMA = "btt_explore_table_v1"
RECORD_SCHEMA = "btt_explore_episode_v1"
GRID_DIVISOR = 24
BETA = 0.05
CAP = 1.0
DECAY = "harmonic"
INELIGIBLE_CLASSES: Tuple[str, ...] = ("damage", "dead", "appear_entry", "other", "unmapped")
REQUIRED_EXTRA_ENV: Tuple[Tuple[str, str], ...] = (("SSB64_RL_SPATIAL", "1"),)   # the map bounds' source
SETTINGS_KEYS: Tuple[str, ...] = ("contract", "beta", "cap", "grid_divisor", "decay")
EVENT_CAP = 64                     # banked events kept verbatim per episode record (totals are exact regardless)
Cell = Tuple[int, int]


class ExploreContractError(ValueError):
    """A settings table or a reply violates this contract."""


@dataclass(frozen=True)
class ExploreContract:
    contract: str = CONTRACT_ID
    beta: float = BETA
    cap: float = CAP
    grid_divisor: int = GRID_DIVISOR
    decay: str = DECAY

    def to_json(self) -> Dict[str, Any]:
        return {"contract": self.contract, "beta": self.beta, "cap": self.cap, "grid_divisor": self.grid_divisor,
                "decay": self.decay}

    def weight(self, n: int) -> float:
        if self.decay != "harmonic":
            raise ExploreContractError(f"decay {self.decay!r} is not registered")
        return 1.0 / (1.0 + int(n))


def check_settings(settings: Mapping[str, Any]) -> ExploreContract:
    """The [exploration] table (short keys) -> the frozen contract; every value must be the registered one."""
    keys = tuple(sorted(settings))
    if keys != tuple(sorted(SETTINGS_KEYS)):
        raise ExploreContractError(f"exploration settings keys {keys} != {tuple(sorted(SETTINGS_KEYS))}")
    c = ExploreContract(contract=str(settings["contract"]), beta=float(settings["beta"]), cap=float(settings["cap"]),
                        grid_divisor=int(settings["grid_divisor"]), decay=str(settings["decay"]))
    if c != ExploreContract():
        raise ExploreContractError(f"exploration settings {c.to_json()} are not the registered {ExploreContract().to_json()}")
    return c


def cell_size(map_bounds: Sequence[int], contract: ExploreContract = ExploreContract()) -> float:
    """s = max(width, height) / grid_divisor from the spatial diagnostic's [top, bottom, right, left]."""
    if len(map_bounds) != 4:
        raise ExploreContractError(f"map_bounds {map_bounds!r}: expected [top, bottom, right, left]")
    top, bottom, right, left = (float(v) for v in map_bounds)
    width, height = right - left, top - bottom
    if width <= 0 or height <= 0:
        raise ExploreContractError(f"map_bounds {map_bounds!r}: non-positive extent")
    return max(width, height) / float(contract.grid_divisor)


def cell_of(x: float, y: float, size: float) -> Cell:
    return (math.floor(float(x) / size), math.floor(float(y) / size))


def is_live(observation: Mapping[str, Any]) -> bool:
    return int(observation.get("fighter_valid", 0)) == 1 and int(observation.get("btt_active", 0)) == 1


# -- the per-slot table ----------------------------------------------------------------------------------------------


class ExploreTable:
    """Visit counts of one worker slot: cell -> number of earlier episodes that visited it."""

    def __init__(self, contract: ExploreContract = ExploreContract(), *, rank: Optional[int] = None):
        self.contract = contract
        self.rank = rank
        self.counts: Dict[Cell, int] = {}
        self.episodes = 0

    def count(self, cell: Cell) -> int:
        return self.counts.get(cell, 0)

    def note_episode(self, visited: Iterable[Cell]) -> None:
        for c in set(visited):
            self.counts[c] = self.counts.get(c, 0) + 1
        self.episodes += 1

    def to_json(self) -> Dict[str, Any]:
        rows = sorted([cx, cy, n] for (cx, cy), n in self.counts.items())
        body = {"schema": TABLE_SCHEMA, "contract": self.contract.to_json(), "rank": self.rank, "episodes": self.episodes,
                "cells": len(rows), "counts": rows}
        body["sha256"] = hashlib.sha256(json.dumps({k: v for k, v in body.items()}, sort_keys=True, separators=(",", ":"))
                                        .encode("utf-8")).hexdigest()
        return body

    @staticmethod
    def from_json(doc: Mapping[str, Any], contract: ExploreContract = ExploreContract()) -> "ExploreTable":
        if doc.get("schema") != TABLE_SCHEMA:
            raise ExploreContractError(f"table schema {doc.get('schema')!r}")
        if dict(doc.get("contract") or {}) != contract.to_json():
            raise ExploreContractError("table written under another exploration contract")
        t = ExploreTable(contract, rank=doc.get("rank"))
        t.counts = {(int(cx), int(cy)): int(n) for cx, cy, n in doc.get("counts") or []}
        t.episodes = int(doc.get("episodes") or 0)
        return t

    def save(self, path: Path) -> str:
        """Atomic write (tmp + replace); returns the table's sha256."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = self.to_json()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return doc["sha256"]

    @staticmethod
    def load(path: Path, contract: ExploreContract = ExploreContract()) -> "ExploreTable":
        return ExploreTable.from_json(json.loads(Path(path).read_text(encoding="utf-8")), contract)


# -- one episode --------------------------------------------------------------------------------------------------------


@dataclass
class ExploreStep:
    banked: float = 0.0            # added to this step's learner reward
    banked_ground: float = 0.0
    banked_air: float = 0.0
    pending_added: float = 0.0
    voided: float = 0.0
    capped: float = 0.0
    new_cell: bool = False
    eligible: bool = False
    landing: bool = False

    def to_json(self) -> Dict[str, Any]:
        return {"banked": self.banked, "banked_ground": self.banked_ground, "banked_air": self.banked_air,
                "pending_added": self.pending_added, "voided": self.voided, "capped": self.capped,
                "new_cell": self.new_cell, "eligible": self.eligible, "landing": self.landing}


@dataclass
class ExploreEpisode:
    contract: ExploreContract
    table: ExploreTable
    size: float
    visited: set = field(default_factory=set)
    pending: List[Tuple[int, Cell, float]] = field(default_factory=list)
    banked_total: float = 0.0
    banked_ground: float = 0.0
    banked_air: float = 0.0
    voided_total: float = 0.0
    capped_total: float = 0.0
    steps: int = 0
    eligible_steps: int = 0
    landings: int = 0
    events: List[Dict[str, Any]] = field(default_factory=list)
    ended: Optional[str] = None
    cells_credited: int = 0

    @staticmethod
    def start(reset_observation: Mapping[str, Any], map_bounds: Sequence[int], table: ExploreTable,
              contract: ExploreContract = ExploreContract()) -> "ExploreEpisode":
        ep = ExploreEpisode(contract=contract, table=table, size=cell_size(map_bounds, contract))
        if is_live(reset_observation):
            ep.visited.add(cell_of(reset_observation["position_x"], reset_observation["position_y"], ep.size))
        return ep

    def _bank(self, tick: Any, cell: Cell, amount: float, kind: str) -> Tuple[float, float]:
        room = max(0.0, self.contract.cap - self.banked_total)
        paid = min(amount, room)
        dropped = amount - paid
        if paid > 0:
            self.banked_total += paid
            if kind == "ground":
                self.banked_ground += paid
            else:
                self.banked_air += paid
            self.cells_credited += 1
            if len(self.events) < EVENT_CAP:
                self.events.append({"tick": tick, "cell": list(cell), "amount": round(paid, 6), "kind": kind})
        if dropped > 0:
            self.capped_total += dropped
        return paid, dropped

    def step(self, observation: Mapping[str, Any], class_name: str, *, consumed_tick: Any, native_failure: bool,
             episode_end: bool) -> ExploreStep:
        """One post-update step. `native_failure`: btt_native_failure_v1 on this step. `episode_end`: this is the
        episode's last step (clear, failure, horizon or any truncation)."""
        if self.ended is not None:
            raise ExploreContractError("step after the episode's end")
        self.steps += 1
        out = ExploreStep()
        if native_failure:
            out.voided = self._void()
            self.ended = "native_failure"
            self.table.note_episode(self.visited)
            return out
        live = is_live(observation)
        eligible = live and class_name not in INELIGIBLE_CLASSES
        out.eligible = eligible
        if eligible:
            self.eligible_steps += 1
            grounded = int(observation.get("ground_air_state", -1)) == 0
            if grounded and self.pending:
                out.landing = True
                self.landings += 1
                for (t, c, a) in self.pending:
                    paid, _dropped = self._bank(t, c, a, "air")
                    out.banked += paid
                    out.banked_air += paid
                    out.capped += _dropped
                self.pending = []
            cell = cell_of(observation["position_x"], observation["position_y"], self.size)
            if cell not in self.visited:
                self.visited.add(cell)
                out.new_cell = True
                amount = float(self.contract.beta) * self.contract.weight(self.table.count(cell))
                if grounded:
                    paid, dropped = self._bank(consumed_tick, cell, amount, "ground")
                    out.banked += paid
                    out.banked_ground += paid
                    out.capped += dropped
                else:
                    self.pending.append((consumed_tick, cell, amount))
                    out.pending_added += amount
        if episode_end:
            out.voided += self._void()
            self.ended = "end"
            self.table.note_episode(self.visited)
        return out

    def _void(self) -> float:
        v = sum(a for _, _, a in self.pending)
        self.voided_total += v
        self.pending = []
        return v

    def record(self) -> Dict[str, Any]:
        return {"schema": RECORD_SCHEMA, "contract": self.contract.contract, "cell_size": self.size,
                "bonus": self.banked_total, "banked_ground": self.banked_ground,       # exact floats: ground + air == bonus
                "banked_air": self.banked_air, "voided": self.voided_total,
                "capped": self.capped_total, "cap_hit": self.banked_total >= self.contract.cap - 1e-12,
                "cells_visited": len(self.visited), "cells_credited": self.cells_credited, "landings": self.landings,
                "steps": self.steps, "eligible_steps": self.eligible_steps, "ended": self.ended,
                "table_episodes_before": self.table.episodes - (1 if self.ended else 0), "events": list(self.events)}


# -- contract description ---------------------------------------------------------------------------------------------


def contract_description() -> Dict[str, Any]:
    c = ExploreContract()
    return {
        "contract": CONTRACT_ID, "settings": c.to_json(), "required_extra_env": dict(REQUIRED_EXTRA_ENV),
        "grid": {"origin": "world (0, 0)", "cell": "(floor(x / s), floor(y / s))",
                 "size_rule": "s = max(width, height) / grid_divisor from the spatial diagnostic map_bounds [top, bottom, right, left] "
                              "of the tick-0 observe reply", "out_of_bounds": "no clipping; outer cells are ordinary cells"},
        "eligible": {"live": "fighter_valid 1 and btt_active 1",
                     "class_not_in": list(INELIGIBLE_CLASSES),
                     "ineligible_step": "marks nothing, banks nothing, keeps pending credit pending"},
        "first_visit": "first eligible step of the episode in the cell; the tick-0 reset observation marks its cell visited without credit",
        "amount": "beta * w(n), n = earlier episodes of this worker slot that visited the cell; w(n) = 1 / (1 + n); computed at the visit",
        "grounded": "ground_air_state 0: banked on the visiting step",
        "airborne": "pending; banked in visit order on the next eligible grounded step (a landing on any floor); voided at native "
                    "failure, at the horizon and at any episode end before such a landing",
        "cap": "banked credit per episode <= cap; the excess of a credit is dropped (recorded as capped); pending amounts keep "
               "their computed value until banking",
        "permanence": "banked credit is never undone; a fall after a landing keeps the landing's credit (no claw-back rule)",
        "counts": "at every episode end n += 1 for every visited cell, whether banked, voided or capped",
        "learner": "the banked amount joins the contract reward of the same step (grounded: the visiting step; airborne: the landing "
                   "step); no retroactive attribution",
        "tables": "one per worker slot (rank); persists across game-process restarts and standby promotions; written after every "
                  "episode to <worker_dir>/explore_table.json and reloaded on resume of the same run; empty in a fresh run; never "
                  "imported across runs",
        "episode_state": "visited set and pending list cleared at reset; never checkpointed",
        "logging": {"step": ["banked", "banked_ground", "banked_air", "pending_added", "voided", "capped", "new_cell", "eligible", "landing"],
                    "episode": ["bonus", "banked_ground", "banked_air", "voided", "capped", "cap_hit", "cells_visited", "cells_credited",
                                "landings", "steps", "eligible_steps", "ended", "table_episodes_before", "events(<= 64)"]},
        "not_observed": "the policy observation contract is unchanged; the visited set and tables are reward state only",
    }


# -- self-test ---------------------------------------------------------------------------------------------------------


def _obs(x: float, y: float, ga: int, *, live: bool = True) -> Dict[str, Any]:
    return {"fighter_valid": 1 if live else 0, "btt_active": 1 if live else 0, "position_x": x, "position_y": y,
            "ground_air_state": ga}


def self_test() -> int:
    fails: List[str] = []

    def expect(cond: bool, name: str, detail: Any = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {name}{'' if cond else ' ' + str(detail)}")
        if not cond:
            fails.append(name)

    c = ExploreContract()
    expect(cell_size([9600, -9600, 9600, -9600]) == 800.0, "cell size = extent / 24")
    expect(cell_size([4800, -4800, 9600, -9600]) == 800.0, "cell size uses the larger extent")
    expect(cell_of(-0.5, 799.9, 800.0) == (-1, 0) and cell_of(0.0, 0.0, 800.0) == (0, 0), "floor cells, world origin")
    try:
        check_settings({"contract": CONTRACT_ID, "beta": 0.1, "cap": 1.0, "grid_divisor": 24, "decay": "harmonic"})
        fails.append("unregistered beta accepted")
    except ExploreContractError:
        print("[PASS] an unregistered setting is refused")
    t = ExploreTable(c, rank=0)
    mb = [9600, -9600, 9600, -9600]
    # episode 1: reset cell marked, grounded new cell banked at once, airborne cells pending, banked at landing
    ep = ExploreEpisode.start(_obs(0, -2550, 0), mb, t, c)
    expect(len(ep.visited) == 1 and ep.banked_total == 0.0, "reset marks its cell without credit")
    s1 = ep.step(_obs(0, -2550, 0), "idle_ground", consumed_tick=0, native_failure=False, episode_end=False)
    expect(s1.banked == 0.0 and not s1.new_cell, "same cell as the reset: nothing")
    s2 = ep.step(_obs(900, -2550, 0), "dash_run", consumed_tick=1, native_failure=False, episode_end=False)
    expect(abs(s2.banked - 0.05) < 1e-12 and s2.banked_ground == s2.banked and s2.new_cell, "grounded new cell banks beta")
    s3 = ep.step(_obs(900, 100, 1), "airborne", consumed_tick=2, native_failure=False, episode_end=False)
    s4 = ep.step(_obs(900, 900, 1), "special_hi", consumed_tick=3, native_failure=False, episode_end=False)
    expect(s3.banked == 0.0 and abs(s3.pending_added - 0.05) < 1e-12 and abs(s4.pending_added - 0.05) < 1e-12, "airborne cells pending")
    s5 = ep.step(_obs(900, 100, 1), "damage", consumed_tick=4, native_failure=False, episode_end=False)
    expect(not s5.eligible and s5.banked == 0.0 and len(ep.pending) == 2, "damage step: nothing, pending kept")
    s6 = ep.step(_obs(1700, -2550, 0), "landing", consumed_tick=5, native_failure=False, episode_end=False)
    expect(s6.landing and abs(s6.banked_air - 0.10) < 1e-12 and abs(s6.banked_ground - 0.05) < 1e-12 and abs(s6.banked - 0.15) < 1e-12,
           "landing banks the pending flight plus its own new grounded cell", s6)
    s7 = ep.step(_obs(1700, 100, 1), "airborne", consumed_tick=6, native_failure=False, episode_end=False)
    s8 = ep.step(_obs(1700, 100, 1), "airborne", consumed_tick=7, native_failure=True, episode_end=True)
    expect(abs(s8.voided - 0.05) < 1e-12 and ep.ended == "native_failure" and abs(ep.banked_total - 0.20) < 1e-12,
           "native failure voids the pending flight, keeps what was banked", (s8, ep.banked_total))
    expect(t.episodes == 1 and t.count((1, -4)) == 1 and t.count((2, 0)) == 1 and t.count((2, -4)) == 1,
           "counts increment for every visited cell, banked or voided", t.counts)
    # episode 2 on the same slot: decayed amounts; horizon voids pending; cap applies to banked only
    ep2 = ExploreEpisode.start(_obs(0, -2550, 0), mb, t, c)
    s = ep2.step(_obs(900, -2550, 0), "dash_run", consumed_tick=0, native_failure=False, episode_end=False)
    expect(abs(s.banked - 0.025) < 1e-12, "second visit of a cell on this slot pays beta / 2")
    big = ExploreContract()
    ep3 = ExploreEpisode.start(_obs(0, -2550, 0), mb, ExploreTable(big), big)
    total = 0.0
    for i in range(1, 30):
        total += ep3.step(_obs(900 * i, -2550, 0), "dash_run", consumed_tick=i, native_failure=False, episode_end=False).banked
    expect(abs(total - 1.0) < 1e-9 and ep3.capped_total > 0 and ep3.record()["cap_hit"], "cap 1.0 on banked credit, excess recorded")
    ep4 = ExploreEpisode.start(_obs(0, -2550, 0), mb, ExploreTable(c), c)
    ep4.step(_obs(0, 100, 1), "airborne", consumed_tick=0, native_failure=False, episode_end=False)
    s = ep4.step(_obs(0, 900, 1), "airborne", consumed_tick=1, native_failure=False, episode_end=True)
    expect(abs(s.voided - 0.10) < 1e-12 and ep4.banked_total == 0.0, "horizon without a landing voids all pending")
    # persistence round trip
    doc = t.to_json()
    t2 = ExploreTable.from_json(doc, c)
    expect(t2.counts == t.counts and t2.episodes == t.episodes and t2.to_json()["sha256"] == doc["sha256"], "table round trip")
    rec = ep.record()
    expect(rec["schema"] == RECORD_SCHEMA and abs(rec["bonus"] - 0.20) < 1e-12 and rec["cells_visited"] == 6 and rec["landings"] == 1,
           "episode record", rec)
    print(f"self-test: {'PASS' if not fails else 'FAIL ' + str(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["self-test"]:
        raise SystemExit(self_test())
    if sys.argv[1:] == ["contract"]:
        print(json.dumps(contract_description(), indent=1))
        raise SystemExit(0)
    print(__doc__)
    raise SystemExit(2)
