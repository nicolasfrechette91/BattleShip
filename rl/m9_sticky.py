"""M9-g1: keyed sticky actions and the open-loop tape control (pure, standard library only).

Definition (decision 2; proposal 4.2). For every submitted-word tick t >= 1 of the policy phase, with the keyed uniform u_t below p
(p = 0.25), the word submitted at tick t is the word submitted at tick t - 1; otherwise it is the policy's sampled word. At tick 0 an
episode has no previous word, so nothing repeats. The first policy word after a prefix may therefore repeat the prefix's last word, which
is still the agent's own lineage word. The rule is the same in training, the reach evaluation, the tape control and the claim.

Draws are Python-side sha256 uniforms, `m9|g1|sticky|<episode label>|<tick>`, never the native RNG and never a stateful generator, so a
recorded mask is reproducible from the key alone (`mask_from_keys`) and a replay re-draws nothing: the submitted words are the record.

The tape control replays the trunk's words (T_clear) by tick index as a fixed open-loop tape under the identical keyed draws (the same
label as the policy episode it is paired with): at a draw below p the previous submitted word repeats, otherwise the tape's word for that
tick is submitted. After the tape's last word the neutral word 0 is submitted (a tape never improvises).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

import m9_contract as C

STICKY_CONTRACT = "m9_sticky_v1"
NEUTRAL_WORD = 0


def uniform(key: str) -> float:
    """First 8 bytes of sha256(key) / 2^64 (the draw scheme of rl/m8_rd_explore)."""
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") / 2.0 ** 64


def sticky_key(label: str, tick: int) -> str:
    return f"m9|{C.GATE.split('_')[1]}|sticky|{label}|{int(tick)}"


def train_label(episode: int) -> str:
    return f"train:{int(episode)}"


def eval_label(kind: str, tau: int, k: int) -> str:
    """The shared label of a policy episode and of its paired tape episode: kind is 'reach' (landing states) or 'tick0' or 'fine'."""
    return f"{kind}:{int(tau)}:{int(k)}"


def hit(label: str, tick: int, p: float = C.STICKY_P) -> bool:
    return uniform(sticky_key(label, tick)) < p


def submit(label: Optional[str], tick: int, sampled: int, prev: Optional[int], p: float = C.STICKY_P) -> Tuple[int, bool]:
    """(submitted word, sticky flag) at `tick`. `label` None = no perturbation (the unperturbed diagnostic). `prev` is the word
    submitted at tick - 1 (None at tick 0)."""
    if label is None or prev is None or tick < 1:
        return int(sampled), False
    if hit(label, tick, p):
        return int(prev), True
    return int(sampled), False


def mask_from_keys(label: str, first_tick: int, n: int, p: float = C.STICKY_P) -> bytes:
    """The sticky flags of ticks first_tick .. first_tick + n - 1 recomputed from the keys alone."""
    return bytes(1 if (t >= 1 and hit(label, t, p)) else 0 for t in range(first_tick, first_tick + n))


def check_record(label: Optional[str], first_tick: int, sampled: bytes, submitted: bytes, mask: bytes, prev_word: Optional[int],
                 p: float = C.STICKY_P) -> List[str]:
    """Problems of one recorded policy phase: the mask must equal the one the keys give, a flagged tick repeats the word before it, an
    unflagged tick submits the sampled word. `prev_word` is the last prefix word (None when the phase starts at tick 0)."""
    problems: List[str] = []
    n = len(submitted)
    if not (len(sampled) == n == len(mask)):
        return [f"lengths differ: sampled {len(sampled)} submitted {n} mask {len(mask)}"]
    if label is None:
        if any(mask):
            problems.append("an unperturbed episode carries sticky flags")
        if sampled != submitted:
            problems.append("an unperturbed episode submitted a word the policy did not sample")
        return problems
    want = mask_from_keys(label, first_tick, n, p)
    if want != mask:
        problems.append(f"sticky mask not reproducible from its keys (first difference at index {next(i for i in range(n) if want[i] != mask[i])})")
    prev = prev_word
    for i in range(n):
        if mask[i]:
            if prev is None or submitted[i] != prev:
                problems.append(f"sticky tick {first_tick + i} did not repeat the previous submitted word")
                break
        elif submitted[i] != sampled[i]:
            problems.append(f"tick {first_tick + i} submitted a word other than the sampled one without a sticky flag")
            break
        prev = submitted[i]
    return problems


class Tape:
    """The open-loop tape: words by tick index, neutral after the end."""

    def __init__(self, words: bytes):
        self.words = bytes(words)

    def word(self, tick: int) -> int:
        return int(self.words[tick]) if 0 <= tick < len(self.words) else NEUTRAL_WORD


def contract_description() -> Dict[str, Any]:
    return {"contract": STICKY_CONTRACT, "p": C.STICKY_P, "draw": "u = first 8 bytes of sha256(key) / 2^64", "key": "m9|g1|sticky|<label>|<tick>",
            "rule": "tick >= 1 and u < p: repeat the word submitted at tick - 1; else the sampled word", "tape": "words by tick index, "
            "neutral word 0 after the last", "labels": {"train": "train:<episode>", "paired": "<reach|tick0|fine>:<tau>:<k> (policy and tape share it)"}}
