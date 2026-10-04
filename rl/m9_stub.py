"""M9-g1 synthetic native stand-in (tests only). THE WORLD IS SYNTHETIC: nothing it produces says anything about Mario. It exercises code paths.

`ChainWorld` speaks the reply format of SSB64_RL_SPATIAL=1 (observation, spatial, step bookkeeping) for two synthetic lineages of the real
lengths (2,326 and 2,315 words, sharing 2,298): grounded segments at the real landing ticks, ten targets broken at fixed ticks while alive, a
clear at tick 2,326 (T_clear branch) or 2,315 (T_t branch; decided by the word submitted at tick 2,298), and CRITICAL ticks (about every 30th
word change) at which the lineage's word must be submitted within a grace of 4 ticks or the character falls. An open-loop tape stuck by one
sticky draw misses its critical word and falls; a closed-loop policy that reads the pending-word feature re-submits it. That is the property
the sticky/tape tests need, built from nothing but the words.

    StubBackend   worker backend (`spec["backend"] = "m9_stub:StubBackend"`): acquire() returns a parked tick-0 process
    TraceBackend  serves the RECORDED replies of a real rd4 route trace (tests: the real reply format through the real worker core and the real
                  v3 builder); a word that leaves the recorded route ends the episode as a native failure
    StubObs       the observation pipeline of the stub world (v3-shaped arrays, a few non-zero features)
    StubModel     a deterministic stand-in for the SB3 model with a competence boundary that moves back as it collects transitions from there
    stub_replay / stub_analyse  the verification replay and its analyser
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_sticky as S  # noqa: E402

STUB_CONTRACT = "m9_stub_v1"
LANDING_STARTS = (0, 58, 174, 269, 375, 508, 682, 753, 841, 1061, 1192, 1248, 1369, 1473, 1694, 1966, 2128)    # the real trunk's grounded segments
GROUND_TICKS = 40
BREAK_TICKS = (43, 120, 399, 609, 880, 982, 1339, 1838, 2066)                                                      # the real trunk's break ticks
BREAK_IDS = (0, 4, 9, 5, 3, 7, 2, 6, 8)
LAST_ID = 1
LEN_A, LEN_B, BRANCH_TICK = 2326, 2315, 2298
GRACE = 4
SKILL_STATUS = "idle_ground"
_WORD = {t: i for i, t in enumerate(mcell.TRIPLES)}


def make_words(seed: str = "m9stub") -> Tuple[bytes, bytes]:
    """The two lineages' words: keyed explorer-style holds; T_t = T_clear's first 2,298 words and a different 17-word tail."""
    a = bytes(mx.words(lambda i: f"{seed}|A|{i}", LEN_A))
    tail = bytes(mx.words(lambda i: f"{seed}|B|{i}", LEN_B - BRANCH_TICK))
    if tail[0] == a[BRANCH_TICK]:
        tail = bytes([(tail[0] + 1) % 72]) + tail[1:]
    return a, a[:BRANCH_TICK] + tail


def critical_ticks(words: bytes, spacing: int = 30) -> List[int]:
    """Ticks where the word changes and the next GRACE words all differ from it (so a stuck tape cannot hit it by accident)."""
    out: List[int] = []
    last = -spacing
    for t in range(60, BRANCH_TICK - GRACE - 1):
        if t - last >= (spacing if t < 2100 else 8) and words[t] != words[t - 1] and all(words[t + k] != words[t] for k in range(1, GRACE + 1)):
            out.append(t)
            last = t
    return out


_LINES = [{"id": i, "type": 0, "group": 1, "flags": 0, "vertex_total": 2, "vertices": [[float(i), 0.0], [float(i) + 1, 0.0]]} for i in range(20)]
_GROUPS = [{"id": g, "present": 1, "speed": [0.0, 0.0], "status": 0, "translate": [0.0, 0.0], "translated": 0} for g in range(3)]


def _status_ids() -> Dict[str, int]:
    clf = mcell.Classifier()
    by: Dict[str, int] = {}
    for sid, cls in sorted(clf._by_id.items()):
        by.setdefault(cls, sid)
    return by


_STATUS = _status_ids()


class ChainWorld:
    def __init__(self, seed: str = "m9stub", *, no_clear: bool = False):
        self.no_clear = bool(no_clear)                    # tests: the stage can never be cleared, so an episode runs to the horizon
        self.a, self.b = make_words(seed)
        self.crit = {t: self.a[t] for t in critical_ticks(self.a)}
        self.ground = set()
        for s in LANDING_STARTS:
            self.ground.update(range(s, s + GROUND_TICKS))
        self.positions = [[float(100 * i), 0.0] for i in range(10)]

    def initial(self) -> List[Any]:
        # t, mask, alive, branch, pending_word, pending_until, ended, fell, prev_word
        return [0, (1 << 10) - 1, True, None, -1, -1, False, False, -1]

    def route_word(self, t: int) -> int:
        return int(self.a[t]) if t < len(self.a) else 0

    def advance(self, s: List[Any], word: int) -> None:
        t, mask, alive, branch, pword, puntil, ended, fell, _prev = s
        tick = t                                    # the consumed tick of this word
        if tick == BRANCH_TICK:
            branch = "B" if word == self.b[BRANCH_TICK] else "A"
        if tick in self.crit:
            if word != self.crit[tick]:
                pword, puntil = self.crit[tick], tick + GRACE
        elif pword >= 0 and word == pword:
            pword, puntil = -1, -1
        if tick in self.crit and word == self.crit[tick]:
            pword, puntil = -1, -1
        if pword >= 0 and tick >= puntil:
            fell, alive = True, False
        t += 1
        clear_tick = 10 ** 9 if self.no_clear else (LEN_B if branch == "B" else LEN_A)
        for k, bt in enumerate(BREAK_TICKS):
            if t == bt and alive:
                mask &= ~(1 << BREAK_IDS[k])
        if alive and t == clear_tick:
            mask &= ~(1 << LAST_ID)
            if mask == 0:
                ended = True
        s[:] = [t, mask, alive, branch, pword, puntil, ended, fell, word]

    def reply(self, s: Sequence[Any], host_off: int, *, observe: bool = False) -> Dict[str, Any]:
        t, mask, alive, branch, pword, puntil, ended, fell, _prev = s
        grounded = (t in self.ground) and not fell
        gs = 5 if (fell or ended) else 1
        status = "dead" if fell else (SKILL_STATUS if grounded else "airborne")
        obs = {"observation_schema": 1, "host_frame": host_off + t, "input_tick": t, "time_passed": max(0, t - 1), "game_status": gs, "btt_active": 1,
               "targets_remaining": mcell.popcount(mask), "fighter_valid": 1, "position_x": float(t), "position_y": 0.0 if grounded else 100.0,
               "air_velocity_x": 0.0, "air_velocity_y": 0.0, "ground_velocity_x": 0.0, "facing_direction": 1, "ground_air_state": 0 if grounded else 1,
               "fighter_status_id": _STATUS[status], "jumps_used": 0}
        sp = {"contract": "btt_spatial_v1", "spatial_schema": 1, "input_tick": t, "scene_active": 1, "live": 1, "update_tic": t + 62, "anomaly_flags": 0,
              "map_bounds": [9600, -9600, 9600, -9600], "camera_bounds": [5000, -5000, 5000, -5000], "groups": _GROUPS,
              "fighter": {"valid": 1, "floor_line_id": 4, "ceil_line_id": 0, "lwall_line_id": 0, "rwall_line_id": 0, "mask_curr": 0, "floor_dist": 0.0,
                          "carry": [0.0, 0.0], "coll": [320.0, 190.0, 0.0, 150.0]},
              "target_live_mask": mask, "target_positions": self.positions}
        if observe:
            sp = dict(sp, lines=_LINES)
        state = mcell.STATE_ENDED if ended else mcell.STATE_WAITING
        r = {"ok": True, "op": "observe" if observe else "step", "protocol": 1, "state": state, "state_name": "EpisodeEnded" if ended else "WaitingForAction",
             "step_count": t, "observation": obs, "spatial": sp,
             "stub": {"route_word": self.route_word(t), "pending": int(pword), "t": t}}
        if observe:
            r["can_step"] = True
        else:
            r["consumed_tick"] = t - 1
            r["step_schema"] = 1
        return r


# -- processes and backends ----------------------------------------------------------------------------------------------------------------


class StubProc:
    def __init__(self, backend: "StubBackend", n: int):
        self.backend, self.world, self.n = backend, backend.world, n
        self.state = self.world.initial()
        self.host_off = 40 + (hashlib.sha256(f"{os.getpid()}|{n}".encode()).digest()[0] % 60)
        self.mode = "cold"
        self.startup = {"mode": "cold", "wait_s": 0.0}
        self.pid = os.getpid() * 1000 + n
        self.inject = backend.inject
        self.closed = False
        self.failed = False
        self.steps = 0

    def observe(self) -> Dict[str, Any]:
        return self.world.reply(self.state, self.host_off, observe=True)

    def step(self, b: int, x: int, y: int) -> Dict[str, Any]:
        if self.n in (self.inject.get("lifecycle_jobs") or []) and self.steps == int(self.inject.get("lifecycle_tick", 3)):
            raise mw.LifecycleFailure("premature_exit", "injected process death")
        self.world.advance(self.state, _WORD[(b, x, y)])
        self.steps += 1
        r = self.world.reply(self.state, self.host_off)
        mj = self.inject.get("mismatch_job")
        if mj is not None and (self.n in mj if isinstance(mj, (list, tuple)) else self.n >= int(mj)) and self.steps == int(self.inject.get("mismatch_tick", 20)):
            r = dict(r, observation=dict(r["observation"], position_x=r["observation"]["position_x"] + 1.0))
        if self.inject.get("bad_consumed_job") == self.n and self.steps == 5:
            r = dict(r, consumed_tick=r["consumed_tick"] + 1)
        return r

    def finish(self, reply: Mapping[str, Any]) -> Dict[str, Any]:
        t = reply["observation"]["input_tick"]
        return {"exit_code": 0, "result": {"result_schema": 1, "outcome": "clear", "targets_broken": 10, "completion_time_passed": t - 1, "completion_input_tick": t,
                                           "time_passed_final": t - 1, "input_cursor_final": t, "host_frames": t + 60}}

    def close(self) -> str:
        self.closed = True
        return "terminated"


class StubBackend:
    def __init__(self, spec: Mapping[str, Any]):
        self.spec = dict(spec)
        self.rank = int(spec["rank"])
        self.inject = dict(spec.get("inject") or {})
        self.world = ChainWorld(spec.get("seed", "m9stub"), no_clear=bool(self.inject.get("no_clear")))
        self.n = 0

    def acquire(self, wait_timeout: float = 0.0) -> StubProc:
        self.n += 1
        if self.inject.get("hang_job") == self.n:
            time.sleep(600.0)
        if self.inject.get("acquire_fail_jobs") and self.n in self.inject["acquire_fail_jobs"]:
            raise mw.LifecycleFailure("startup_failure", "injected launch failure")
        if self.inject.get("provenance_job") == self.n:
            mw.ProvenanceGuard.violations.append("injected/" + "rl/" + "fix" + "tures/x")
        return StubProc(self, self.n)

    def info(self) -> Dict[str, Any]:
        return {"pid": os.getpid(), "rank": self.rank, "backend": "stub"}

    def report(self) -> Dict[str, Any]:
        return {"acquired": self.n}

    def close(self) -> Dict[str, Any]:
        return {"closed": True}


class TraceProc:
    """A process that serves the recorded replies of one real trace: the lineage's own words reproduce the recording; any other word is a native failure."""

    def __init__(self, backend: "TraceBackend", n: int):
        self.backend, self.n = backend, n
        self.trace = backend.trace
        self.i = 0
        self.dead = False
        self.mode, self.startup, self.pid = "cold", {"mode": "cold", "wait_s": 0.0}, 7000 + n
        self.failed = False
        self.closed = False
        self.words = backend.words

    def observe(self) -> Dict[str, Any]:
        return self.trace["initial"]

    def step(self, b: int, x: int, y: int) -> Dict[str, Any]:
        i = self.i
        if self.dead or i >= len(self.trace["steps"]):
            raise mw.LifecycleFailure("trace_exhausted", "the recorded trace has no further reply")
        word = _WORD[(b, x, y)]
        if word != self.words[i]:
            self.dead = True
            last = self.trace["steps"][i]
            o = dict(last["observation"], game_status=5, targets_remaining=max(1, last["observation"]["targets_remaining"]))
            rep = dict(last, observation=o, state=mcell.STATE_WAITING, state_name="WaitingForAction")
            self.i += 1
            return rep
        self.i += 1
        return self.trace["steps"][i]

    def finish(self, reply: Mapping[str, Any]) -> Dict[str, Any]:
        return {"exit_code": 0, "result": dict(self.trace["result"])}

    def close(self) -> str:
        self.closed = True
        return "terminated"


class TraceBackend:
    def __init__(self, spec: Mapping[str, Any]):
        self.spec = dict(spec)
        self.rank = int(spec["rank"])
        self.trace = spec["trace"]
        self.words = bytes(spec["words"])
        self.n = 0

    def acquire(self, wait_timeout: float = 0.0) -> TraceProc:
        self.n += 1
        return TraceProc(self, self.n)

    def info(self) -> Dict[str, Any]:
        return {"backend": "trace", "rank": self.rank}

    def report(self) -> Dict[str, Any]:
        return {"acquired": self.n}

    def close(self) -> Dict[str, Any]:
        return {"closed": True}


# -- observation pipeline and model stand-ins -------------------------------------------------------------------------------------------


SHAPES = {"action_class": (20,), "agent": (28,), "projectiles": (4, 7), "segment_geometry": (32, 8), "segment_kind": (32, 7), "targets": (10, 5)}
KEY_ORDER = ("action_class", "agent", "projectiles", "segment_geometry", "segment_kind", "targets")


class StubObs:
    """v3-shaped arrays; agent[24] = tick / 3600, agent[25] = the route word at this tick / 72, agent[26] = (pending word + 1) / 73."""

    def __init__(self, initial_reply: Mapping[str, Any]):
        self.obs: Dict[str, np.ndarray] = {}
        self.stale = False
        self.feed(initial_reply)

    def feed(self, reply: Mapping[str, Any]) -> None:
        st = reply["stub"]
        o = {k: np.zeros(sh, dtype=np.float32) for k, sh in SHAPES.items()}
        o["agent"][24] = st["t"] / 3600.0
        o["agent"][25] = st["route_word"] / 72.0
        o["agent"][26] = (st["pending"] + 1) / 73.0
        o["agent"][27] = reply["observation"]["targets_remaining"] / 10.0
        self.obs = o

    def digest(self) -> str:
        h = hashlib.sha256()
        for k in KEY_ORDER:
            a = np.ascontiguousarray(self.obs[k])
            h.update(f"{k}|{a.dtype.str}|{a.shape}|".encode("ascii"))
            h.update(a.tobytes())
        return h.hexdigest()

    def arrays(self) -> Dict[str, np.ndarray]:
        return dict(self.obs)


class SpatialObs:
    """The observation pipeline for the m8 fake game (replies carry no entity block and no `stub` key): v3-shaped arrays from the observation fields."""

    def __init__(self, initial_reply: Mapping[str, Any]):
        self.obs: Dict[str, np.ndarray] = {}
        self.stale = False
        self.feed(initial_reply)

    def feed(self, reply: Mapping[str, Any]) -> None:
        o = reply["observation"]
        a = {k: np.zeros(sh, dtype=np.float32) for k, sh in SHAPES.items()}
        a["agent"][0] = float(o["position_x"]) / 2000.0
        a["agent"][1] = float(o["position_y"]) / 2000.0
        a["agent"][24] = float(o["input_tick"]) / 3600.0
        a["agent"][27] = float(o["targets_remaining"]) / 10.0
        self.obs = a

    digest = StubObs.digest
    arrays = StubObs.arrays


class StubLogger:
    def record(self, *a: Any, **k: Any) -> None:
        pass

    def dump(self, *a: Any, **k: Any) -> None:
        pass


class StubModel:
    """A deterministic stand-in for the SB3 model. Competence: the policy emits the route word (or the pending word) at every tick t >= B and a keyed
    pseudo-random word below B. B moves back by one 20-tick bin each time the model has collected `need` transitions in the bin just below B (the way a
    policy trained from starts there learns it). `learn` mirrors the SB3 loop: rollouts of n_steps over the vec env, callbacks, one update per rollout."""

    def __init__(self, env: Any, *, n_steps: int, b0: int = C.TAU0, need: int = 120, seed: int = 0, bin_ticks: int = 20):
        self.env, self.n_steps, self.B, self.need, self.seed, self.bin = env, int(n_steps), int(b0), int(need), int(seed), int(bin_ticks)
        self.num_timesteps = 0
        self.logger = StubLogger()
        self.calls = 0
        self.exposure: Dict[int, int] = {}
        self.updates = 0
        self.history: List[Tuple[int, int]] = []
        self.ent_coef = C.PPO["ent_coef"]

    def get_env(self) -> Any:
        return self.env

    def _word(self, env_index: int, t: int, route_word: int, pending: int, call: int) -> int:
        if t >= self.B:
            return pending if pending >= 0 else route_word
        return int(S.uniform(f"m9stub|{self.seed}|{call}|{env_index}") * 72) % 72

    def predict(self, obs: Mapping[str, np.ndarray], deterministic: bool = False) -> Tuple[np.ndarray, None]:
        n = obs["agent"].shape[0]
        out = np.zeros((n, 2), dtype=np.int64)
        for i in range(n):
            a = obs["agent"][i]
            t = int(round(float(a[24]) * 3600.0))
            word = self._word(i, t, int(round(float(a[25]) * 72.0)), int(round(float(a[26]) * 73.0)) - 1, self.calls)
            out[i] = (word // 8, word % 8)
        self.calls += 1
        return out, None

    def learn(self, total_timesteps: int, callback: Any = None, **_k: Any) -> "StubModel":
        env = self.env
        callback.init_callback(self)
        callback.on_training_start({}, {})
        obs = env.reset()
        done_all = False
        try:
            while self.num_timesteps < total_timesteps and not done_all:
                callback.on_rollout_start()
                for _ in range(self.n_steps):
                    actions, _ = self.predict(obs, deterministic=False)
                    ts = obs["agent"][:, 24].copy()
                    obs, _r, _d, _i = env.step(actions)
                    self.num_timesteps += env.num_envs
                    for t in ts:
                        b = int(round(float(t) * 3600.0)) // self.bin
                        self.exposure[b] = self.exposure.get(b, 0) + 1
                    if callback.on_step() is False:
                        done_all = True
                        break
                if done_all:
                    break
                callback.on_rollout_end()
                self.update()
        finally:
            callback.on_training_end()
        return self

    def update(self) -> None:
        self.updates += 1
        below = self.B // self.bin - 1
        if below >= 0 and self.exposure.get(below, 0) >= self.need:
            self.B = below * self.bin
            self.history.append((self.num_timesteps, self.B))

    def save(self, path: Any) -> None:
        import zipfile

        info = zipfile.ZipInfo("stub_model.json", date_time=(2026, 1, 1, 0, 0, 0))        # a fixed timestamp: the file is a pure function of the model
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(info, json.dumps({"B": self.B, "updates": self.updates, "num_timesteps": self.num_timesteps, "seed": self.seed}))


# -- verification stand-ins ---------------------------------------------------------------------------------------------------------------


def stub_replay_factory(seed: str = "m9stub"):
    world = ChainWorld(seed)

    def replay(words: bytes, label: str, slot: int) -> Dict[str, Any]:
        s = world.initial()
        initial = world.reply(s, 77, observe=True)
        steps: List[Dict[str, Any]] = []
        rows = []
        final = "WaitingForAction"
        result = None
        for w in words:
            world.advance(s, w)
            r = world.reply(s, 77)
            steps.append(r)
            b, x, y = mcell.TRIPLES[w]
            rows.append((b, x, y, r["consumed_tick"]))
            if r["state"] == mcell.STATE_ENDED:
                final = "EpisodeEnded"
                t = r["observation"]["input_tick"]
                result = {"result_schema": 1, "outcome": "clear", "targets_broken": 10, "completion_time_passed": t - 1, "completion_input_tick": t,
                          "time_passed_final": t - 1, "input_cursor_final": t, "host_frames": t + 60}
                break
            if r["observation"]["game_status"] == 5:
                final = "NativeFailure"
                break
        return {"label": label, "initial": initial, "steps": steps, "submitted": len(steps), "unsent": len(words) - len(steps), "consumed_tick_mismatch": None,
                "final_state": final, "exit_code": 0 if result else None, "result": result, "action_digest": mcell.native_digest(rows)}

    return replay


def stub_analyse(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    prev = int(initial["spatial"]["target_live_mask"])
    breaks: List[Tuple[int, int]] = []
    for r in steps:
        m = int(r["spatial"]["target_live_mask"])
        if m != prev:
            for i in range(10):
                if (prev & ~m) >> i & 1:
                    breaks.append((i, int(r["consumed_tick"])))
            prev = m
    return {"breaks": breaks}
