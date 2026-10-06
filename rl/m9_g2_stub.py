"""M9-g2 synthetic stand-ins (tests only). THE WORLD IS SYNTHETIC: nothing here says anything about Mario. It exercises code paths.

Built on rl/m9_stub (the ChainWorld, its backend, StubObs) and rl/m9_testenv (the in-process lock-step pool and the virtual clock), unchanged:

* `G2StubModel`: the g1 StubModel (competence boundary B moving back as transitions are collected below it) with (a) a saved state that round-trips
  exactly (B, updates, num_timesteps, the exposure counts, the seed, the move history), (b) a resume path (`load` + `learn(reset_num_timesteps=False)`),
  (c) an injectable Pitfall-type forgetting: once B is at or below `forget_when_b_below`, the policy no longer completes from a COLD start at the landing
  `forget_landing` (it emits keyed random words for the whole episode), while its own traversals through that landing still succeed. That is what makes a
  re-check fail while the strip test passes (BLOCKED_BY_RECHECK, HELD, STALLED across a resumed session).
* `G2StubPolicy`: the frozen stand-in the probe runner samples (`stats` / `argmax_word` / `sample_word(flat, key)`): the snapshot's B and the forgetting rule;
  the random part keyed by the action key; the cold-start rule identifies an episode by its action-key prefix (the part of the key before the tick) and its
  first tick seen.
* `G2StubEnvBuilder`: rl/m9_testenv.StubEnvBuilder with the g2 model factory, the stub snapshot writer, the resume loader and the probe policy factory.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m9_contract as C
import m9_g2_contract as G
import m9_sticky as S
import m9_stub as ST
import m9_testenv as TE

STUB2_CONTRACT = "m9_g2_stub_v1"
AGENT0 = 20                                            # flat index of agent[0] (action_class has 20 values)
I_TICK, I_ROUTE, I_PENDING, I_TARGETS = AGENT0 + 24, AGENT0 + 25, AGENT0 + 26, AGENT0 + 27


def flat_fields(flat: Any) -> Tuple[int, int, int]:
    a = np.asarray(flat, dtype=np.float64).reshape(-1)
    return int(round(a[I_TICK] * 3600.0)), int(round(a[I_ROUTE] * 72.0)), int(round(a[I_PENDING] * 73.0)) - 1


class G2StubModel(ST.StubModel):
    """The g1 stub learner with a state that round-trips exactly, a resume path and the injectable cold-start forgetting."""

    def __init__(self, env: Any, *, n_steps: int, b0: int = C.TAU0, need: int = 120, seed: int = 0, bin_ticks: int = 20, forget_landing: Optional[int] = None,
                 forget_when_b_below: Optional[int] = None):
        super().__init__(env, n_steps=n_steps, b0=b0, need=need, seed=seed, bin_ticks=bin_ticks)
        self.forget_landing = forget_landing
        self.forget_when_b_below = forget_when_b_below
        self._n_updates = 0
        self.last_tick: Dict[int, int] = {}
        self.start_tick: Dict[int, int] = {}

    # -- competence --

    def forgetting(self) -> bool:
        return self.forget_landing is not None and self.forget_when_b_below is not None and self.B <= int(self.forget_when_b_below)

    def _word(self, env_index: int, t: int, route_word: int, pending: int, call: int) -> int:
        if self.forgetting() and self.start_tick.get(env_index) == self.forget_landing:
            return int(S.uniform(f"m9g2stub|forget|{self.seed}|{call}|{env_index}") * 72) % 72
        return super()._word(env_index, t, route_word, pending, call)

    def predict(self, obs: Mapping[str, np.ndarray], deterministic: bool = False) -> Tuple[np.ndarray, None]:
        n = obs["agent"].shape[0]
        for i in range(n):
            t = int(round(float(obs["agent"][i][24]) * 3600.0))
            if i not in self.last_tick or t <= self.last_tick[i]:
                self.start_tick[i] = t                   # a new episode in this env slot: its handover tick
            self.last_tick[i] = t
        return super().predict(obs, deterministic)

    def update(self) -> None:
        super().update()
        self._n_updates += 1

    # -- state --

    def state_dict(self) -> Dict[str, Any]:
        return {"B": int(self.B), "updates": int(self.updates), "n_updates": int(self._n_updates), "num_timesteps": int(self.num_timesteps), "seed": int(self.seed),
                "need": int(self.need), "bin": int(self.bin), "exposure": {str(k): int(v) for k, v in sorted(self.exposure.items())}, "history": [list(h) for h in self.history],
                "forget_landing": self.forget_landing, "forget_when_b_below": self.forget_when_b_below, "calls": int(self.calls)}

    def save(self, path: Any) -> None:
        info = zipfile.ZipInfo("stub_model.json", date_time=(2026, 1, 1, 0, 0, 0))
        opt = zipfile.ZipInfo("policy.optimizer.pth", date_time=(2026, 1, 1, 0, 0, 0))      # a stand-in member so the member digests exist
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(info, json.dumps(self.state_dict(), sort_keys=True))
            z.writestr(opt, json.dumps({"adam_steps": {"0": self._n_updates * 10}}, sort_keys=True))
            z.writestr(zipfile.ZipInfo("policy.pth", date_time=(2026, 1, 1, 0, 0, 0)), json.dumps({"B": int(self.B)}))

    @classmethod
    def load(cls, path: Any, env: Any = None, n_steps: int = 1) -> "G2StubModel":
        with zipfile.ZipFile(path) as z:
            st = json.loads(z.read("stub_model.json"))
        m = cls(env, n_steps=n_steps, b0=int(st["B"]), need=int(st["need"]), seed=int(st["seed"]), bin_ticks=int(st["bin"]), forget_landing=st.get("forget_landing"),
                forget_when_b_below=st.get("forget_when_b_below"))
        m.updates, m._n_updates, m.num_timesteps, m.calls = int(st["updates"]), int(st["n_updates"]), int(st["num_timesteps"]), int(st["calls"])
        m.exposure = {int(k): int(v) for k, v in st["exposure"].items()}
        m.history = [tuple(h) for h in st["history"]]
        return m

    def learn(self, total_timesteps: int, callback: Any = None, reset_num_timesteps: bool = True, **_k: Any) -> "G2StubModel":
        if reset_num_timesteps:
            self.num_timesteps = 0
        else:
            total_timesteps += self.num_timesteps
        return super().learn(total_timesteps, callback=callback)


class G2StubPolicy:
    """The frozen stand-in of a G2StubModel snapshot for the probe runner and the close audit."""

    def __init__(self, state: Mapping[str, Any], sha256: str):
        self.B = int(state["B"])
        self.seed = int(state["seed"])
        self.forget_landing = state.get("forget_landing")
        self.forget_when_b_below = state.get("forget_when_b_below")
        self.sha256 = sha256
        self.decisions = 0
        self.start_tick: Dict[str, int] = {}

    def forgetting(self) -> bool:
        return self.forget_landing is not None and self.forget_when_b_below is not None and self.B <= int(self.forget_when_b_below)

    def _episode_of(self, key: str) -> str:
        return key.rsplit("|", 1)[0]

    def stats(self, flat: Any) -> Dict[str, float]:
        t, _r, _p = flat_fields(flat)
        v = 10.0 if t >= self.B else -3.0
        h = 0.5 if t >= self.B else 4.27
        return {"v": v, "h": h, "top_word_p": 0.9 if t >= self.B else 0.014}

    def _rule(self, t: int, route_word: int, pending: int, cold_forgotten: bool, rnd_key: str) -> int:
        if t >= self.B and not cold_forgotten:
            return pending if pending >= 0 else route_word
        return int(S.uniform(rnd_key) * 72) % 72

    def argmax_word(self, flat: Any) -> int:
        t, r, p = flat_fields(flat)
        self.decisions += 1
        return self._rule(t, r, p, False, f"m9g2stub|det|{self.seed}|{t}")

    def sample_word(self, flat: Any, key: str) -> int:
        t, r, p = flat_fields(flat)
        ep = self._episode_of(key)
        if ep not in self.start_tick:
            self.start_tick[ep] = t
        cold = self.forgetting() and self.start_tick[ep] == self.forget_landing
        self.decisions += 1
        return self._rule(t, r, p, cold, key)


# -- the environment builder -----------------------------------------------------------------------------------------------------------------


class G2StubEnvBuilder(TE.StubEnvBuilder):
    def __init__(self, root: Path, *, model_need: int = 120, forget_landing: Optional[int] = None, forget_when_b_below: Optional[int] = None, **kw: Any):
        super().__init__(root, model_need=model_need, **kw)
        self.forget_landing, self.forget_when_b_below = forget_landing, forget_when_b_below
        self.models: List[G2StubModel] = []

    def make_model(self, vec: Any, n: int) -> G2StubModel:
        m = G2StubModel(vec, n_steps=C.ROLLOUT_SIZE // n, need=self.model_need, forget_landing=self.forget_landing, forget_when_b_below=self.forget_when_b_below)
        self.models.append(m)
        return m

    def resume_model(self, path: Path, vec: Any, n: int, session: int) -> G2StubModel:
        m = G2StubModel.load(path, vec, n_steps=C.ROLLOUT_SIZE // n)
        m.resumed_seed = G.SESSION_SEED_BASE + int(session)      # type: ignore[attr-defined]
        self.models.append(m)
        return m

    def load_model(self, path: Path) -> G2StubModel:
        return G2StubModel.load(path, None, n_steps=1)

    @staticmethod
    def snapshot_of(model: G2StubModel):
        def snapshot(path: Path) -> Dict[str, Any]:
            raw = json.dumps(model.state_dict(), sort_keys=True).encode("utf-8")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(raw)
            return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        return snapshot

    @staticmethod
    def make_policy(path: Path, sha256: str) -> G2StubPolicy:
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise RuntimeError("stub snapshot digest mismatch")
        return G2StubPolicy(json.loads(raw), sha256)

    @staticmethod
    def policy_from_model_zip(path: Path) -> G2StubPolicy:
        with zipfile.ZipFile(path) as z:
            st = json.loads(z.read("stub_model.json"))
        return G2StubPolicy(st, hashlib.sha256(Path(path).read_bytes()).hexdigest())

    @staticmethod
    def flatten(obs: Mapping[str, Any]) -> np.ndarray:
        return np.concatenate([np.asarray(obs[k], dtype=np.float32).reshape(-1) for k in ST.KEY_ORDER])


def contract_description() -> Dict[str, Any]:
    return {"contract": STUB2_CONTRACT, "world": "rl/m9_stub.ChainWorld (synthetic; not Mario)", "learner": "competence boundary B moving back; cold-start forgetting injectable"}
