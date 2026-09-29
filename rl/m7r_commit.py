"""M7r: action contract `btt_commit_s9_b8_m2_d6_v1` (committed options over Track 1 words; opt-in).

Design: docs/rl_temporal_control_design_2026-09-28.md (revision 3, section 3). Track 1 `btt_s9_b8_v1`, every
observation contract, reward v2 and the M4 artifacts are unchanged; this module only decides WHICH Track 1 word is
submitted on each native tick.

    policy action   MultiDiscrete([9, 8, 2, 6]) = (Track 1 stick, Track 1 button, mode, max length)
    mode            tap: the button on the option's first tick, none afterwards; hold: the button on every tick
    max length d    DURATIONS = (1, 2, 4, 8, 16, 32) native ticks

Per tick i = 1..tau the executor submits ONE Track 1 action (stick, button_i) to the wrapper below it (the existing
Track1PolicyWrapper path: one native request, one consumed tick). The option ends after tick i when i = d; or, for
i >= 2, when tick i's native reply shows an input-effect boundary (BOUNDARY_EVENTS, `boundaries`); or when the episode
ends; or, in training only, when the environment's rollout tick quota is used up. Ending an option never submits
anything: the next decision's first tick follows immediately (no gap, no hidden tick, no inserted release). R stays a
Track 1 button; the game folds it to R+A+Z. With d = 1 both modes emit exactly the Track 1 word of (stick, button).

Replay truth stays the per-tick canonical native words recorded by EpisodeRecordingWrapper BELOW this layer. Option
metadata and the per-tick boundary signatures go to a sidecar (`SIDECAR_FILE` in the episode's artifact directory);
`check_expansion` re-derives every per-tick word and every option length from the sidecar and must match the
canonical actions exactly. NumPy / Gymnasium only (no PyTorch): spawn workers import this module.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from btt_learning import (TRACK1_BUTTON_NAMES, TRACK1_BUTTON_STATES, TRACK1_BUTTON_TABLE, TRACK1_CONTRACT,
                          TRACK1_STICK_NAMES, TRACK1_STICK_STATES, TRACK1_STICK_TABLE)

CONTRACT = "btt_commit_s9_b8_m2_d6_v1"
SCHEMA_VERSION = 1
MODES: Tuple[str, ...] = ("tap", "hold")
MODE_TAP, MODE_HOLD = 0, 1
DURATIONS: Tuple[int, ...] = (1, 2, 4, 8, 16, 32)
ACTION_NVEC: Tuple[int, ...] = (TRACK1_STICK_STATES, TRACK1_BUTTON_STATES, len(MODES), len(DURATIONS))
# Input-effect boundaries, in the order used to label an option end when several fire on the same tick.
BOUNDARY_EVENTS: Tuple[str, ...] = ("class_change", "ground_air_change", "apex", "hitlag_end", "target_break")
END_MAX_LENGTH = "max_length"
END_EPISODE = "episode_end"
END_ROLLOUT = "rollout_boundary"            # training only: the environment's rollout tick quota
END_REASONS: Tuple[str, ...] = BOUNDARY_EVENTS + (END_MAX_LENGTH, END_EPISODE, END_ROLLOUT)
SIDECAR_FILE = "decisions.json.gz"
NETWORK_ID = "btt_policy_net_v4_commit_multiinput_mlp64"   # the v4 network body with a 9 + 8 + 2 + 6 action head
SIDECAR_SCHEMA = "btt_commit_sidecar_v1"
TRACK1_NONE_BUTTON = 0


def make_action_space() -> spaces.MultiDiscrete:
    return spaces.MultiDiscrete(list(ACTION_NVEC))


@dataclass(frozen=True)
class Option:
    stick: int
    button: int
    mode: int
    d_index: int

    @property
    def d(self) -> int:
        return DURATIONS[self.d_index]

    def to_json(self) -> Dict[str, Any]:
        return {"stick": self.stick, "button": self.button, "mode": MODES[self.mode], "d": self.d}


def _index(v: Any, limit: int, what: str) -> int:
    if isinstance(v, (bool, np.bool_)):
        raise ValueError(f"{what} must be an integer, got a boolean")
    if isinstance(v, (int, np.integer)):
        i = int(v)
    else:
        raise ValueError(f"{what} must be an integer, got {type(v).__name__}")
    if not 0 <= i < limit:
        raise ValueError(f"{what} {i} outside 0..{limit - 1}")
    return i


def decode(action: Any) -> Option:
    """A policy action (4 integers) -> Option; ValueError for anything else."""
    a = np.asarray(action)
    if a.shape != (4,) or not np.issubdtype(a.dtype, np.integer):
        raise ValueError(f"{CONTRACT} action must be 4 integers, got shape {a.shape} dtype {a.dtype}")
    return Option(_index(a[0], ACTION_NVEC[0], "stick"), _index(a[1], ACTION_NVEC[1], "button"),
                  _index(a[2], ACTION_NVEC[2], "mode"), _index(a[3], ACTION_NVEC[3], "length"))


def tick_word(option: Option, i: int) -> Tuple[int, int]:
    """The Track 1 (stick, button) submitted on tick i (1-based) of the option."""
    if i < 1:
        raise ValueError("ticks are 1-based")
    button = option.button if (i == 1 or option.mode == MODE_HOLD) else TRACK1_NONE_BUTTON
    return option.stick, button


def native_word(track1: Tuple[int, int]) -> Tuple[int, int, int]:
    """Track 1 (stick, button) -> the canonical native (buttons, stick_x, stick_y) the M4 artifact records."""
    sx, sy = TRACK1_STICK_TABLE[track1[0]]
    return int(TRACK1_BUTTON_TABLE[track1[1]]), int(sx), int(sy)


# -- native boundary signatures ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    """The native facts after one tick that the boundaries read (all from the raw reply)."""
    live: int          # btt_active, fighter_valid and a valid input object
    klass: int         # btt_action_class_table_v2 index of fighter_status_id (-1 when not live)
    status: int
    airborne: int      # ground_air_state (1 = airborne)
    vy_pos: int        # air_velocity_y > 0
    hitlag: int        # entity.fighter.hitlag_tics > 0
    targets: int       # targets_remaining

    def to_row(self) -> List[int]:
        return [self.live, self.klass, self.status, self.airborne, self.vy_pos, self.hitlag, self.targets]

    @classmethod
    def from_row(cls, row: Sequence[int]) -> "Signature":
        return cls(*[int(v) for v in row])


def signature_of(reply: Mapping[str, Any], classifier: Any) -> Signature:
    """Signature of a raw observe / step reply (the M7q v4 stack's reply: observation + entity + input)."""
    o = reply.get("observation") or {}
    en = ((reply.get("entity") or {}).get("fighter") or {})
    inp = reply.get("input") or {}
    live = int(bool(o.get("btt_active")) and bool(o.get("fighter_valid")) and bool(inp.get("valid"))
               and bool(en.get("valid", 1)))
    status = int(o.get("fighter_status_id", -1))
    klass = int(classifier.index(status)) if live else -1
    return Signature(live=live, klass=klass, status=status, airborne=int(int(o.get("ground_air_state", 0)) == 1),
                     vy_pos=int(float(o.get("air_velocity_y", 0.0)) > 0.0),
                     hitlag=int(int(en.get("hitlag_tics", 0)) > 0), targets=int(o.get("targets_remaining", 0)))


def boundaries(prev: Signature, cur: Signature) -> List[str]:
    """Every input-effect boundary between two consecutive replies, in BOUNDARY_EVENTS order. None across a reply
    that is not live (the episode then ends by its own rule)."""
    if not (prev.live and cur.live):
        return []
    out = []
    if prev.klass != cur.klass:
        out.append("class_change")
    if prev.airborne != cur.airborne:
        out.append("ground_air_change")
    if prev.airborne and cur.airborne and prev.vy_pos and not cur.vy_pos:
        out.append("apex")
    if prev.hitlag and not cur.hitlag:
        out.append("hitlag_end")
    if cur.targets < prev.targets:
        out.append("target_break")
    return out


# -- the executor ------------------------------------------------------------------------------------------


class CommitError(RuntimeError):
    """The executor's own invariants failed (a wrapper-stack or accounting defect, never a gameplay event)."""


class CommitExecutorWrapper(gym.Wrapper):
    """Above the v4 observation wrapper: one policy decision in, tau >= 1 native ticks through the wrappers below.

    Returns the observation after the option's last tick, the UNDISCOUNTED sum of its per-tick rewards (episode
    returns stay the btt_reward_v2 returns), the last tick's terminated / truncated, and that tick's info plus
    info["commit"] = {tau, reason, events, tick_rewards, option, first_tick, idle}. The semi-Markov learner discounts
    the per-tick rewards itself (rl/m7r_ppo.py)."""

    def __init__(self, env: Any, *, obs_wrapper: Any, classifier: Any, tracker: Any = None):
        super().__init__(env)
        self.action_space = make_action_space()
        self.obs_wrapper = obs_wrapper
        self.classifier = classifier
        self.tracker = tracker
        self.quota: Optional[int] = None         # remaining native ticks of this training rollout (None = no quota)
        self.last_obs: Any = None
        self._prev: Optional[Signature] = None
        self._episode: Optional[Dict[str, Any]] = None
        self.totals = {"decisions": 0, "ticks": 0, "episodes": 0, "sidecars_written": 0}
        self.last_commit_info: Optional[Dict[str, Any]] = None   # read by the worker wrapper (its slim info drops keys)

    # -- rollout quota (SubprocVecEnv env_method) --------------------------------------------------------

    def commit_begin_rollout(self, ticks: int) -> bool:
        if int(ticks) < 1:
            raise CommitError("the rollout tick quota must be >= 1")
        self.quota = int(ticks)
        return True

    def commit_end_rollout(self) -> int:
        left, self.quota = self.quota, None
        return int(left or 0)

    @property
    def quota_exhausted(self) -> bool:
        return self.quota is not None and self.quota <= 0

    # -- episode bookkeeping ---------------------------------------------------------------------------------

    def _reply(self) -> Mapping[str, Any]:
        reply = getattr(self.obs_wrapper, "_last_reply", None)
        if not isinstance(reply, Mapping):
            raise CommitError("the observation wrapper exposes no raw reply for this tick")
        return reply

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        obs, info = self.env.reset(seed=seed, options=options)
        self._prev = signature_of(self._reply(), self.classifier)
        self._episode = {"decisions": [], "signatures": [self._prev.to_row()], "ticks": 0}
        self.last_obs = obs
        return obs, info

    def step(self, action: Any):
        if self._episode is None or self._prev is None:
            raise CommitError("step before reset")
        if self.quota_exhausted:
            raise CommitError("step with an exhausted rollout quota (the worker wrapper answers idle steps)")
        opt = decode(action)
        first_tick = self._episode["ticks"]
        tick_rewards: List[float] = []
        reason, events, obs = None, [], self.last_obs
        terminated = truncated = False
        info: Dict[str, Any] = {}
        i = 0
        while reason is None:
            i += 1
            obs, reward, terminated, truncated, info = self.env.step(np.array(tick_word(opt, i), dtype=np.int64))
            if info.get("truncation_reason") == "episode_failure" and info.get("consumed_tick") is None:
                # Track1PolicyWrapper's lifecycle-failure path: no tick was consumed; the episode ends here.
                i -= 1
                reason = END_EPISODE
                info = dict(info, commit_unconsumed_failure=True)
                break
            tick_rewards.append(float(reward))
            self._episode["ticks"] += 1
            self.totals["ticks"] += 1
            cur = signature_of(self._reply(), self.classifier)
            self._episode["signatures"].append(cur.to_row())
            fired = boundaries(self._prev, cur)
            self._prev = cur
            if self.quota is not None:
                self.quota -= 1
            if terminated or truncated:
                reason = END_EPISODE
            elif i >= 2 and fired:
                reason, events = fired[0], fired
            elif i >= opt.d:
                reason = END_MAX_LENGTH
            elif self.quota is not None and self.quota <= 0:
                reason = END_ROLLOUT
        tau = i
        record = {"j": len(self._episode["decisions"]), "first_tick": first_tick, "tau": tau, **opt.to_json(),
                  "mode_index": opt.mode, "reason": reason, "events": list(events)}
        self._episode["decisions"].append(record)
        self.totals["decisions"] += 1
        self.last_obs = obs
        info = dict(info)
        info["commit"] = {"contract": CONTRACT, "tau": tau, "reason": reason, "events": list(events),
                          "tick_rewards": tick_rewards, "option": opt.to_json(), "first_tick": first_tick, "idle": False}
        self.last_commit_info = info["commit"]
        if terminated or truncated:
            self._finish_episode()
        return obs, float(sum(tick_rewards)), terminated, truncated, info

    def _finish_episode(self) -> None:
        ep, self._episode = self._episode, None
        self.totals["episodes"] += 1
        if ep is None or self.tracker is None:
            return

        def build(summary: Mapping[str, Any]) -> Dict[str, Any]:
            extra: Dict[str, Any] = {"commit": {"contract": CONTRACT, "decisions": len(ep["decisions"]),
                                                "ticks": ep["ticks"], "sidecar": None}}
            if summary.get("preserved"):
                directory = Path(self.tracker.artifact_root) / str(summary["episode_id"])
                write_sidecar(directory, episode_id=str(summary["episode_id"]),
                              native_action_digest=summary.get("native_action_digest"), ticks=ep["ticks"],
                              decisions=ep["decisions"], signatures=ep["signatures"])
                extra["commit"]["sidecar"] = SIDECAR_FILE
                self.totals["sidecars_written"] += 1
            return extra

        self.tracker.extend_pending_summary(build)


# -- sidecar and the expansion check -------------------------------------------------------------------------


def write_sidecar(directory: Path, *, episode_id: str, native_action_digest: Optional[str], ticks: int,
                  decisions: Sequence[Mapping[str, Any]], signatures: Sequence[Sequence[int]]) -> Path:
    doc = {"schema": SIDECAR_SCHEMA, "contract": CONTRACT, "contract_sha256": contract_digest(),
           "episode_id": episode_id, "native_action_digest": native_action_digest, "ticks": int(ticks),
           "signature_fields": ["live", "klass", "status", "airborne", "vy_pos", "hitlag", "targets"],
           "signatures_note": "row 0 = the tick-0 observe reply; row t + 1 = the reply after consumed tick t",
           "decisions": list(decisions), "signatures": [list(r) for r in signatures]}
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SIDECAR_FILE
    with gzip.open(path, "wt", encoding="utf-8") as fp:
        json.dump(doc, fp, separators=(",", ":"))
    return path


def read_sidecar(path: Path) -> Dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        return json.load(fp)


def check_expansion(sidecar: Mapping[str, Any], canonical: Sequence[Tuple[int, int, int, int]], *,
                    allow_rollout_cut: bool) -> List[str]:
    """Re-derive every per-tick word and option length from the sidecar. `canonical` = the episode's recorded
    (consumed_tick, buttons, stick_x, stick_y) rows. Returns the problems (empty = exact)."""
    problems: List[str] = []
    decisions = list(sidecar.get("decisions") or [])
    sigs = [Signature.from_row(r) for r in (sidecar.get("signatures") or [])]
    if len(sigs) != int(sidecar.get("ticks", -1)) + 1:
        problems.append(f"{len(sigs)} signatures for {sidecar.get('ticks')} ticks (expected ticks + 1)")
    if len(canonical) != int(sidecar.get("ticks", -1)):
        problems.append(f"{len(canonical)} canonical actions for {sidecar.get('ticks')} sidecar ticks")
    t = 0
    for k, d in enumerate(decisions):
        if int(d.get("j", -1)) != k or int(d.get("first_tick", -1)) != t:
            problems.append(f"decision {k}: index / first tick {d.get('j')} / {d.get('first_tick')} != {k} / {t}")
        try:
            opt = Option(int(d["stick"]), int(d["button"]), int(d["mode_index"]), DURATIONS.index(int(d["d"])))
        except (KeyError, ValueError) as exc:
            problems.append(f"decision {k}: bad option {exc}")
            break
        tau, reason = int(d["tau"]), d.get("reason")
        unconsumed_end = tau == 0 and reason == END_EPISODE and k == len(decisions) - 1   # lifecycle failure: no tick
        if not (1 <= tau <= opt.d or unconsumed_end):
            problems.append(f"decision {k}: tau {tau} outside 1..{opt.d}")
        if unconsumed_end:
            continue
        for i in range(1, tau + 1):
            if t + i - 1 >= len(canonical):
                problems.append(f"decision {k}: runs past the recorded actions")
                break
            row = canonical[t + i - 1]
            want = native_word(tick_word(opt, i))
            if int(row[0]) != t + i - 1 or tuple(int(v) for v in row[1:]) != want:
                problems.append(f"tick {t + i - 1}: recorded {tuple(row)} != expanded {(t + i - 1, *want)}")
            # no boundary may fire on ticks 2..tau-1 (the option would have ended there)
            if 2 <= i < tau and len(sigs) > t + i and boundaries(sigs[t + i - 1], sigs[t + i]):
                problems.append(f"decision {k}: boundary {boundaries(sigs[t + i - 1], sigs[t + i])} at its tick {i} "
                                f"but the option ran to {tau}")
        if len(sigs) > t + tau:
            fired = boundaries(sigs[t + tau - 1], sigs[t + tau]) if tau >= 2 else []
            last = k == len(decisions) - 1
            if reason in BOUNDARY_EVENTS:
                if not fired or fired[0] != reason:
                    problems.append(f"decision {k}: reason {reason} but the signatures give {fired}")
            elif reason == END_MAX_LENGTH:
                if tau != opt.d or fired:
                    problems.append(f"decision {k}: max_length with tau {tau} / d {opt.d} / boundaries {fired}")
            elif reason == END_EPISODE:
                if not last:
                    problems.append(f"decision {k}: episode_end before the last decision")
            elif reason == END_ROLLOUT:
                if not allow_rollout_cut:
                    problems.append(f"decision {k}: rollout_boundary in a record without rollout cuts (evaluation)")
                elif fired or tau == opt.d:
                    problems.append(f"decision {k}: rollout_boundary although a boundary / max length also ended it")
            else:
                problems.append(f"decision {k}: unknown reason {reason!r}")
        t += tau
    if t != len(canonical):
        problems.append(f"decisions cover {t} ticks, the canonical record has {len(canonical)}")
    return problems


def canonical_rows(actions_jsonl: Path) -> List[Tuple[int, int, int, int]]:
    """(consumed_tick, buttons, stick_x, stick_y) of an M4 actions.jsonl."""
    rows = []
    with open(actions_jsonl, encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            r = json.loads(line)
            rows.append((int(r["consumed_tick"]), int(r["buttons"]), int(r["stick_x"]), int(r["stick_y"])))
    return rows


# -- contract identity -----------------------------------------------------------------------------------------


def contract_description() -> Dict[str, Any]:
    return {
        "contract": CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "space": {"type": "gymnasium.spaces.MultiDiscrete", "nvec": list(ACTION_NVEC)},
        "components": {
            "stick": {"table": TRACK1_CONTRACT, "names": list(TRACK1_STICK_NAMES),
                      "native": [list(v) for v in TRACK1_STICK_TABLE]},
            "button": {"table": TRACK1_CONTRACT, "names": list(TRACK1_BUTTON_NAMES),
                       "native": [int(b) for b in TRACK1_BUTTON_TABLE],
                       "note": "R stays a Track 1 button; the game folds it to R+A+Z; no combined action exists"},
            "mode": {"values": list(MODES), "tap": "button on tick 1 only, none on ticks 2..tau",
                     "hold": "button on every tick 1..tau"},
            "max_length": {"values": list(DURATIONS), "unit": "native ticks"},
        },
        "per_tick_word": "stick on every tick; button per mode; exactly one Track 1 action per consumed tick",
        "termination": {"max_length": "tick i = d", "boundaries": list(BOUNDARY_EVENTS),
                        "boundary_ticks": "i >= 2 (a change on tick 1 is the option's own intended effect)",
                        "boundary_source": "raw native reply: table-v2 class of fighter_status_id, ground_air_state, "
                                           "air_velocity_y (> 0 then <= 0 while airborne), entity hitlag_tics "
                                           "(> 0 then 0), targets_remaining (decreased); none across a non-live reply",
                        "episode_end": "terminated or truncated", "rollout_boundary": "training only: the "
                        "environment's rollout tick quota is used up"},
        "no_hidden_input": "ending an option submits nothing; the next decision's first tick follows immediately",
        "duration_one": "d = 1 emits exactly the Track 1 word of (stick, button) in both modes",
        "replay_truth": "the per-tick canonical native words recorded below this layer (M4 actions.jsonl)",
        "sidecar": {"file": SIDECAR_FILE, "schema": SIDECAR_SCHEMA},
        "reward": "the undiscounted sum of the per-tick rewards; the learner discounts per tick",
    }


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True).encode("utf-8")).hexdigest()
