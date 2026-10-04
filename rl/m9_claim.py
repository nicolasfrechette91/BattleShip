"""M9: the final-claim evaluator (defined here, NOT run by gate g1).

The claim (decision 3, proposal 4.1) is evaluated on the frozen final policy from the ordinary tick-0 reset with NO prefix and NO idle words: this module
has no prefix code path. It cannot stage a start (it imports no staging, arena, pool, curriculum or lineage module: a static test asserts that), it accepts
only a process that sits at the non-consuming tick-0 reset (`input_tick` 0, `step_count` 0), the first policy word consumes tick 0, and every record it
produces states `prefix_rows: 0`. Part A: at least 50 of 100 stochastic episodes clear, unperturbed. Part B: at least 50 of 100 clear under sticky actions
(p = 0.25, the same keyed rule) and at least 25 more than the open-loop tape on the same 100 draw keys (the tape is run by the caller from the same label).
Every counted clear must reproduce exactly from tick 0 (the verification of rl/m9_verify), which the caller runs.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

import m8_rd_cells as mcell
import m9_contract as C
import m9_rule as R
import m9_sticky as S

CLAIM_EVALUATOR = "m9_claim_v1"


class ClaimError(RuntimeError):
    pass


def claim_label(kind: str, k: int) -> str:
    return S.eval_label(f"claim_{kind}", 0, k)


def run_claim_episode(proc: Any, predict: Callable[[Mapping[str, Any]], int], label: Optional[str], *, pin: Mapping[str, Any], pipeline_cls: Any,
                      horizon: int = C.HORIZON) -> Dict[str, Any]:
    """One episode from a process parked at the ordinary tick-0 reset. `predict(obs) -> a Track 1 word`; `label` None = unperturbed, else the sticky label."""
    reply0 = proc.observe()
    o0 = reply0["observation"]
    if reply0.get("step_count") != 0 or int(o0["input_tick"]) != 0 or reply0.get("state") != mcell.STATE_WAITING:
        raise ClaimError("the claim evaluator accepts only the non-consuming tick-0 reset (input_tick 0, step_count 0)")
    if mcell.record_digest(mcell.tick0_record(reply0)).hex() != pin["digest"]:
        raise ClaimError("the tick-0 record differs from the pin")
    pipe = pipeline_cls(reply0)
    words = bytearray()
    prev: Optional[int] = None
    ended = fell = False
    reply = reply0
    for tick in range(horizon):
        sampled = int(predict(pipe.arrays()))
        word, _sticky = S.submit(label, tick, sampled, prev)
        b, x, y = mcell.TRIPLES[word]
        reply = proc.step(b, x, y)
        if reply["consumed_tick"] != tick or reply["observation"]["input_tick"] != tick + 1:
            raise ClaimError(f"tick contract violated at {tick}")
        words.append(word)
        prev = word
        pipe.feed(reply)
        ended = reply["state"] == mcell.STATE_ENDED
        fell = mcell.is_native_failure(reply["observation"], reply["state"])
        if ended or fell:
            break
    clear = bool(ended and int(reply["observation"]["targets_remaining"]) == 0)
    return {"prefix_rows": 0, "first_policy_tick": 0, "idle_words": 0, "label": label, "words_hex": bytes(words).hex(), "ticks": len(words), "clear": clear,
            "end": "clear" if clear else ("fall" if fell else ("ended" if ended else "horizon")), "native_action_digest": mcell.words_digest(bytes(words))}


def claim_status(unperturbed_clears: int, sticky_clears: int, tape_clears: int, episodes: int = 100) -> Dict[str, Any]:
    return R.claim_status(unperturbed_clears, sticky_clears, tape_clears, episodes)
