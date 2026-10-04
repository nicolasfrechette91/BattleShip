"""M9-g1 test environment (tests only): the synthetic RunEnv of rl/m9_run built on rl/m9_stub, with an in-process lock-step pool and a virtual clock.

THE WORLD IS SYNTHETIC: nothing it produces says anything about Mario. A run is a pure function of its configuration (no thread or process
scheduling enters the data), so two builds of the same session agree byte for byte on every record but wall-clock fields.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_lineages as L  # noqa: E402
import m9_pool as P  # noqa: E402
import m9_run as RUN  # noqa: E402
import m9_stub as ST  # noqa: E402
import m9_worker as W  # noqa: E402


def stub_lineages(world: ST.ChainWorld) -> Dict[str, L.Lineage]:
    out: Dict[str, L.Lineage] = {}
    for name, words, clocks in (("T_clear", world.a, (2325, 2326)), ("T_t", world.b, (2314, 2315))):
        out[name] = L.Lineage(name=name, words=words, native_action_digest=mcell.words_digest(words), words_sha256=hashlib.sha256(words).hexdigest(),
                              completion_time_passed=clocks[0], completion_input_tick=clocks[1], route_dir=f"stub/{name}", iteration=0, file_sha256={})
    return out


class StubEnvBuilder:
    def __init__(self, root: Path, *, rate: float = 1200.0, seed: str = "m9stub", inject: Optional[Mapping[str, Any]] = None, model_need: int = 120,
                 n_slots: int = C.N_SLOTS):
        self.root = Path(root)
        self.seed = seed
        self.world = ST.ChainWorld(seed)
        self.clock = P.VirtualClock(rate=rate)
        self.inject = dict(inject or {})
        self.model_need = model_need
        self.n_slots = n_slots
        self.replay = ST.stub_replay_factory(seed)
        self.pools: List[Any] = []
        init = self.replay(self.world.a, "x", 0)["initial"]
        self.pin = {"obs": list(mcell.obs_tuple(init["observation"])), "digest": mcell.record_digest(mcell.tick0_record(init)).hex(),
                    "chain": mcell.chain_start(mcell.tick0_record(init)).hex()}
        self.lineages = stub_lineages(self.world)
        self.route_traces = {n: self.replay(ln.words, n, 0) for n, ln in self.lineages.items()}

    def spec(self, rank: int, flags: Mapping[str, str]) -> Dict[str, Any]:
        return {"rank": rank, "lineage_dir": str(self.root / "lineages"), "lineages": list(self.lineages), "pin_tick0": self.pin, "failure_dir": str(self.root / "failures"),
                "backend": "m9_stub:StubBackend", "obs_pipeline": "m9_stub:StubObs", "seed": self.seed, "inject": self.inject, "flags": dict(flags)}

    def make_pool(self, tag: str, flags: Mapping[str, str]) -> P.LocalPool:
        cores = [W.WorkerCore(self.spec(r, flags), ST.StubBackend(self.spec(r, flags))) for r in range(self.n_slots)]
        pool = P.LocalPool(cores, self.clock)
        self.pools.append(pool)
        return pool

    def promoted_trace(self, ln: L.Lineage, route_trace: Mapping[str, Any]) -> Dict[str, Any]:
        tr = self.replay(ln.words, f"promoted-{ln.name}", 0)
        return {"native_action_digest": tr["action_digest"], "result_json": tr["result"], "startup": {"mode": "standby_promoted"}}

    def make_model(self, vec: Any, n: int) -> ST.StubModel:
        return ST.StubModel(vec, n_steps=C.ROLLOUT_SIZE // n, need=self.model_need)

    def load_model(self, path: Path) -> ST.StubModel:
        import zipfile

        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read("stub_model.json"))
        m = ST.StubModel(None, n_steps=1, b0=int(meta["B"]), seed=int(meta["seed"]))
        m.num_timesteps = int(meta["num_timesteps"])
        return m

    def env(self, **over: Any) -> RUN.RunEnv:
        kw: Dict[str, Any] = dict(make_pool=self.make_pool, replay=self.replay, analyse=ST.stub_analyse, promoted_trace=self.promoted_trace, lineages=self.lineages,
                                  route_traces=self.route_traces, pin_tick0=self.pin, make_model=self.make_model, load_model=self.load_model, now=self.clock.now,
                                  pipeline_cls=ST.StubObs, earlier_trees=lambda: {"ok": True, "problems": []}, log=lambda s: None, landings=C.LANDINGS)
        kw.update(over)
        return RUN.RunEnv(**kw)
