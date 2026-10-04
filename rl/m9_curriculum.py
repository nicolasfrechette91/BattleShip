"""M9-g1: the backward curriculum (pure, standard library only): the frontier pointer, the strips, the start distribution, the blocks and
the stale accounting (proposal 5.1).

The frontier pointer tau* starts at 2,300 and moves back in strips of 20 ticks; it never moves forward. Every start draw is a keyed
sha256 uniform (`m9|g1|start|<episode>|region|tau|lineage`): a start is a pure function of (episode number, the pointer in force when it
was drawn), and both are recorded. Start distribution:

    50 %  the strip              [tau*, tau* + 20)
    30 %  the near window        [tau* + 20, tau* + 60)
    20 %  rehearsal              [tau* + 60, the last valid start]

Valid starts are 0 .. (longest lineage - 2): a start needs a lineage with at least tau + 2 words (a start never lies on a terminal tick).
A region that is empty after that clipping is drawn as the preceding non-empty one (rehearsal -> near -> strip); the strip is never
empty. Up to the shared prefix (2,298 words) both lineages hold the same words, so the start is labelled `shared` and uses T_clear's
words; above it the lineage is drawn uniformly among those that are long enough.

Pointer rule (the M7m fix). Only strip starts drawn under the CURRENT pointer count, in completion order, in blocks of 10. A block with
at least 3 clears (rho = 0.3) moves the pointer back by 20 and starts a fresh block; otherwise a new block starts at the same pointer. An
outcome of a strip start drawn under an EARLIER pointer is stale: it is logged and still used for PPO (the caller does that), but it never
enters a block. A start outside the strip never enters a block. So a step back is earned only by clearing from the newly exposed ticks.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m9_contract as C
import m9_sticky as S

CURRICULUM_CONTRACT = "m9_curriculum_v1"
SHARED = "shared"


def start_key(episode: int, what: str) -> str:
    return f"m9|g1|start|{int(episode)}|{what}"


@dataclass(frozen=True)
class Start:
    episode: int
    region: str                 # strip | near | rehearsal
    tau: int                    # prefix words 0..tau-1 are replayed; the policy's first word consumes tick tau
    lineage: str                # the lineage whose words are replayed
    shared: bool                # tau <= the shared prefix: any lineage would give the same words
    pointer: int                # the frontier pointer in force when the start was drawn

    def to_json(self) -> Dict[str, Any]:
        return {"episode": self.episode, "region": self.region, "tau": self.tau, "lineage": self.lineage, "shared": self.shared,
                "pointer": self.pointer}


class Curriculum:
    def __init__(self, lengths: Mapping[str, int], *, order: Sequence[str] = ("T_clear", "T_t"), tau0: int = C.TAU0,
                 shared_prefix: int = C.SHARED_PREFIX, strip: int = C.STRIP, near: int = C.NEAR_WINDOW,
                 weights: Sequence[Tuple[str, int]] = C.REGION_WEIGHTS, block_size: int = C.BLOCK_SIZE, block_pass: int = C.BLOCK_PASS):
        self.lengths = {n: int(lengths[n]) for n in order}
        self.order = tuple(order)
        self.shared_prefix = int(shared_prefix)
        self.strip, self.near = int(strip), int(near)
        self.weights = tuple((r, int(w)) for r, w in weights)
        if sum(w for _r, w in self.weights) != 100:
            raise ValueError("region weights must sum to 100")
        self.block_size, self.block_pass = int(block_size), int(block_pass)
        self.max_start = max(self.lengths.values()) - C.MIN_WORDS_AFTER_START
        if not 0 <= int(tau0) <= self.max_start:
            raise ValueError(f"tau0 {tau0} outside the valid starts 0..{self.max_start}")
        self.pointer = int(tau0)
        self.block: List[bool] = []
        self.block_index = 0
        self.moves: List[Dict[str, Any]] = []
        self.blocks: List[Dict[str, Any]] = []
        self.counted = 0
        self.stale = 0
        self.stale_clears = 0
        self.outside = 0
        self.draws = 0

    # -- the start distribution -------------------------------------------------------------------------------------------------

    def ranges(self, pointer: Optional[int] = None) -> Dict[str, Optional[Tuple[int, int]]]:
        """Inclusive integer ranges of the three regions at `pointer`, clipped to the valid starts; None when empty."""
        p = self.pointer if pointer is None else int(pointer)
        raw = {"strip": (p, p + self.strip - 1), "near": (p + self.strip, p + self.strip + self.near - 1),
               "rehearsal": (p + self.strip + self.near, self.max_start)}
        out: Dict[str, Optional[Tuple[int, int]]] = {}
        for r, (lo, hi) in raw.items():
            hi = min(hi, self.max_start)
            out[r] = (lo, hi) if lo <= hi else None
        return out

    def _region(self, episode: int, rng: Mapping[str, Optional[Tuple[int, int]]]) -> str:
        u = S.uniform(start_key(episode, "region")) * 100.0
        acc = 0.0
        pick = self.weights[-1][0]
        for r, w in self.weights:
            acc += w
            if u < acc:
                pick = r
                break
        order = [r for r, _w in self.weights]
        i = order.index(pick)
        while rng[order[i]] is None and i > 0:      # an empty region is drawn as the preceding non-empty one
            i -= 1
        return order[i]

    def lineage_for(self, episode: int, tau: int) -> Tuple[str, bool]:
        if tau <= self.shared_prefix:
            return self.order[0], True
        valid = [n for n in self.order if self.lengths[n] >= tau + C.MIN_WORDS_AFTER_START]
        if not valid:
            raise ValueError(f"no lineage holds a start at {tau}")
        u = S.uniform(start_key(episode, "lineage"))
        return valid[min(len(valid) - 1, int(u * len(valid)))], False

    def draw(self, episode: int) -> Start:
        rng = self.ranges()
        region = self._region(episode, rng)
        lo, hi = rng[region]                                                    # type: ignore[misc]
        u = S.uniform(start_key(episode, "tau"))
        tau = lo + min(hi - lo, int(u * (hi - lo + 1)))
        lineage, shared = self.lineage_for(episode, tau)
        self.draws += 1
        return Start(int(episode), region, int(tau), lineage, shared, self.pointer)

    # -- the pointer ------------------------------------------------------------------------------------------------------------

    def record(self, start: Start, cleared: bool) -> Optional[Dict[str, Any]]:
        """One finished episode (a native end or the horizon; never a lifecycle failure). Returns the block record when this outcome
        completed a block, else None."""
        if start.region != "strip":
            self.outside += 1
            return None
        if start.pointer != self.pointer:
            self.stale += 1
            self.stale_clears += int(bool(cleared))
            return None
        self.counted += 1
        self.block.append(bool(cleared))
        if len(self.block) < self.block_size:
            return None
        clears = sum(self.block)
        moved = clears >= self.block_pass and self.pointer > 0
        rec = {"block": self.block_index, "pointer": self.pointer, "clears": clears, "size": len(self.block), "moved": moved,
               "new_pointer": max(0, self.pointer - self.strip) if moved else self.pointer, "at_floor": self.pointer == 0}
        self.blocks.append(rec)
        self.block_index += 1
        self.block = []
        if moved:
            self.moves.append({"from": self.pointer, "to": rec["new_pointer"], "block": rec["block"], "clears": clears})
            self.pointer = rec["new_pointer"]
        return rec

    def state(self) -> Dict[str, Any]:
        return {"pointer": self.pointer, "moves": len(self.moves), "blocks": len(self.blocks), "counted_strip_outcomes": self.counted,
                "stale_strip_outcomes": self.stale, "stale_clears": self.stale_clears, "non_strip_outcomes": self.outside,
                "open_block": list(map(int, self.block)), "draws": self.draws}


def contract_description() -> Dict[str, Any]:
    return {"contract": CURRICULUM_CONTRACT, "tau0": C.TAU0, "strip": C.STRIP, "near_window": C.NEAR_WINDOW,
            "weights": [list(x) for x in C.REGION_WEIGHTS], "block": [C.BLOCK_SIZE, C.BLOCK_PASS], "shared_prefix": C.SHARED_PREFIX,
            "valid_starts": "0 .. longest lineage - 2", "empty_region": "drawn as the preceding non-empty region",
            "keys": "m9|g1|start|<episode>|region|tau|lineage", "pointer_rule": "only strip starts drawn under the current pointer count"}


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
