"""M8-rd: the exploration policy `m8_rd_explore_v1` and the keyed Python-side draws (pure, stdlib only).

At each decision, one of the 72 Track 1 words is drawn uniformly and a hold length k uniformly from {1, 2, 4, 8, 16}; the
word's canonical native triple is submitted for k consecutive native ticks, clipped at the end of the run it belongs to.
The explorer reads no observation. A "word" in this module and in every archive is ONE native tick's controller word
(a Track 1 index 0..71, one byte); a burst of 120 words is 120 native ticks.

All draws are Python-side sha256-keyed uniforms (never the native RNG, never a stateful generator), so a resumed archive
needs no generator state:

    selection    m8_rd|<archive_id>|select|<iteration>                    two uniforms (level, cell)
    exploration  m8_rd|<archive_id>|explore|<iteration>|<decision index>  a word and a hold length
    control      m8_rd1|control|<episode>|<decision index>                the same draw scheme, arm C
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable, Iterator, Tuple

EXPLORE_CONTRACT = "m8_rd_explore_v1"
HOLD_CHOICES: Tuple[int, ...] = (1, 2, 4, 8, 16)
WORDS = 72
BURST_WORDS = 120
HORIZON = 3600


def contract_digest() -> str:
    d = {"contract": EXPLORE_CONTRACT, "words": WORDS, "hold_choices": list(HOLD_CHOICES), "burst_words": BURST_WORDS,
         "horizon": HORIZON, "word_draw": "floor(u1 * 72), u1 = first 8 bytes of sha256(key) / 2^64",
         "hold_draw": "HOLD_CHOICES[floor(u2 * 5)], u2 = bytes 8..16 of sha256(key) / 2^64",
         "clip": "the last hold is clipped at the end of the burst (120 words), the native end, a native failure or the "
                 "3,600-tick horizon",
         "keys": {"explore": "m8_rd|<archive_id>|explore|<iteration>|<decision index>",
                  "control": "m8_rd1|control|<episode>|<decision index>"}}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def digest(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


def uniforms(key: str) -> Tuple[float, float]:
    d = digest(key)
    return int.from_bytes(d[0:8], "big") / 2.0 ** 64, int.from_bytes(d[8:16], "big") / 2.0 ** 64


def select_key(archive_id: str, iteration: int) -> str:
    return f"m8_rd|{archive_id}|select|{int(iteration)}"


def explore_key(archive_id: str, iteration: int, index: int) -> str:
    return f"m8_rd|{archive_id}|explore|{int(iteration)}|{int(index)}"


def control_key(episode: int, index: int) -> str:
    return f"m8_rd1|control|{int(episode)}|{int(index)}"


def decision(key: str) -> Tuple[int, int]:
    """(word, hold length) of one decision."""
    u1, u2 = uniforms(key)
    return min(WORDS - 1, int(u1 * WORDS)), HOLD_CHOICES[min(len(HOLD_CHOICES) - 1, int(u2 * len(HOLD_CHOICES)))]


def words(key_of: Callable[[int], str], max_words: int) -> Iterator[int]:
    """The per-tick word stream of one run: decisions 0, 1, ... with each hold clipped so that at most `max_words` words
    are produced. Lazy: a caller that stops early (a fall, a clear) simply stops consuming."""
    produced = 0
    index = 0
    while produced < max_words:
        word, hold = decision(key_of(index))
        index += 1
        for _ in range(min(hold, max_words - produced)):
            produced += 1
            yield word
