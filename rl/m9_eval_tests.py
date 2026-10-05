#!/usr/bin/env python3
"""M9-g1 checkpoint evaluation tests (deterministic; no game process is started).

    python -B rl/m9_eval_tests.py unit      # the gating suite
    python -B rl/m9_eval_tests.py list

DETERMINISM. Pure tests use keyed sha256 draws and fixed data. Session-level tests run the real evaluation engine (rl/m9_eval_ckpt.EvalSession) through
the g1 in-process lock-step pool and virtual clock against the g1 synthetic world (rl/m9_testenv / rl/m9_stub); synthetic checkpoints are built from
fixed tensors. Tests of the real checkpoints and records read runs/m9_g1 and runs/m8_rd_rd4 only (zero native ticks). No test reads a wall clock, sleeps
or uses a random generator (a source scan enforces it). THE SYNTHETIC WORLD IS NOT MARIO.
"""
from __future__ import annotations

import ast
import contextlib
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
sys.dont_write_bytecode = True

import numpy as np  # noqa: E402

import m8_rd_cells as mcell  # noqa: E402
import m9_artifacts as A  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_eval_ckpt as K  # noqa: E402
import m9_eval_policy as POL  # noqa: E402
import m9_lineages as L  # noqa: E402
import m9_sticky as S  # noqa: E402
import m9_stub as ST  # noqa: E402
import m9_testenv as TE  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RL = REPO / "rl"
TESTS: List[Tuple[str, Callable[[], None]]] = []
ROLE_NAMES = ("ck_a", "ck_b", "ck_c", "ck_d", "ck_e")
FORBIDDEN_PATH_PREFIXES = ("tas_" + "input_2/", "rl/" + "fixtures/")       # split so that this tuple is not itself a forbidden literal


def test(fn: Callable[[], None]) -> Callable[[], None]:
    TESTS.append((fn.__name__, fn))
    return fn


def eq(label: str, got: Any, want: Any) -> None:
    if got != want:
        raise AssertionError(f"{label}: got {str(got)[:300]!r}, want {str(want)[:300]!r}")


def ok(label: str, cond: Any) -> None:
    if not cond:
        raise AssertionError(label)


def raises(label: str, exc: Any, fn: Callable[[], Any]) -> Any:
    try:
        fn()
    except exc as e:                                    # noqa: PERF203
        return e
    raise AssertionError(f"{label}: expected {exc}")


@contextlib.contextmanager
def tmpdir(prefix: str = "m9e_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def strip_volatile(o: Any) -> Any:
    drop = {"created_utc", "utc", "t_wall_s", "wall_s", "native_s", "build_s", "boot_s", "wait_s", "waits", "dispatch_to_ready_s", "clock", "elapsed_s", "phase_wall_s",
            "pid", "close", "mode_proc"}
    if isinstance(o, dict):
        return {k: strip_volatile(v) for k, v in o.items() if k not in drop}
    if isinstance(o, list):
        return [strip_volatile(v) for v in o]
    return o


# -- synthetic checkpoints and sessions -----------------------------------------------------------------------------------------------------


def fixed_state(stick_bias: Optional[int] = None, button_bias: Optional[int] = None, value_bias: float = 0.0, scale: float = 0.0, seed: str = "w") -> Dict[str, Any]:
    """A v3-network state dict from fixed numbers: optional keyed weights (sha256-expanded, deterministic), a bias favouring one stick and one button."""
    import torch

    shapes = {"mlp_extractor.policy_net.0.weight": (64, 606), "mlp_extractor.policy_net.0.bias": (64,), "mlp_extractor.policy_net.2.weight": (64, 64),
              "mlp_extractor.policy_net.2.bias": (64,), "mlp_extractor.value_net.0.weight": (64, 606), "mlp_extractor.value_net.0.bias": (64,),
              "mlp_extractor.value_net.2.weight": (64, 64), "mlp_extractor.value_net.2.bias": (64,), "action_net.weight": (17, 64), "action_net.bias": (17,),
              "value_net.weight": (1, 64), "value_net.bias": (1,)}
    sd: Dict[str, Any] = {}
    for k, sh in shapes.items():
        n = int(np.prod(sh))
        if scale:
            raw = b"".join(hashlib.sha256(f"{seed}|{k}|{i}".encode()).digest() for i in range((n * 2 + 31) // 32))[:n * 2]
            a = (np.frombuffer(raw, dtype=np.uint16).astype(np.float32) / 65535.0 - 0.5) * scale
        else:
            a = np.zeros(n, dtype=np.float32)
        sd[k] = torch.from_numpy(a.reshape(sh).copy())
    b = sd["action_net.bias"]
    if stick_bias is not None:
        b[stick_bias] = 3.0
    if button_bias is not None:
        b[9 + button_bias] = 3.0
    sd["value_net.bias"][0] = float(value_bias)
    return sd


def write_ckpt(path: Path, sd: Mapping[str, Any]) -> str:
    import torch

    buf = io.BytesIO()
    torch.save(dict(sd), buf)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("policy.pth", buf.getvalue())
        z.writestr("data", json.dumps({"note": "synthetic test checkpoint"}))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_entries(ck: Path, bad_pin: bool = False) -> List[Dict[str, Any]]:
    out = []
    for i, n in enumerate(ROLE_NAMES):
        sha = write_ckpt(ck / n / "model.zip", fixed_state(stick_bias=i % 9, button_bias=(i * 3) % 8, value_bias=float(i), scale=0.2 * i, seed=n))
        out.append({"name": n, "num_timesteps": i * 1000, "path": f"{n}/model.zip", "sha256": ("0" * 64 if bad_pin and i == 4 else sha)})
    return out


def stub_prepare(b: TE.StubEnvBuilder, tamper: bool = False) -> Callable[[Path], Dict[str, Any]]:
    def prep(dest: Path) -> Dict[str, Any]:
        files = {}
        for n, ln in b.lineages.items():
            tr = b.route_traces[n]
            chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
            files[n] = L.save_tables(dest, n, ln.words, chain, v3)
        if tamper:
            p = dest / K.LINEAGE / "v3.bin"
            blob = bytearray(p.read_bytes())
            blob[32 * 5] ^= 0xFF
            p.write_bytes(bytes(blob))
        return {"ok": True, "lineages": list(b.lineages), "files": files}
    return prep


def synthetic_session(root: Path, *, tamper: bool = False, bad_pin: bool = False, eval_cap: Optional[int] = None, counts: Tuple[int, int, int, int] = (2, 1, 1, 2),
                      verify_cap: Optional[int] = None) -> Tuple[K.EvalSession, Dict[str, Any], K.EvalConfig]:
    import m7n_obs as mn

    b = TE.StubEnvBuilder(root / "run")
    entries = synthetic_entries(root / "ck", bad_pin=bad_pin)
    caps = dict(K.TICK_CAPS)
    if eval_cap is not None:
        caps["eval"] = int(eval_cap)
    if verify_cap is not None:
        caps["verify"] = int(verify_cap)
    cfg = K.EvalConfig(root=root / "run", checkpoints=entries, checkpoint_root=root / "ck", n_sticky=counts[0], n_unperturbed=counts[1], n_det=counts[2], n_tape=counts[3],
                       tick_caps=caps, verify_threads=2)
    sess = K.EvalSession(cfg, b.env(), prepare_tables=stub_prepare(b, tamper), load_policies=lambda: POL.load_policies(entries, root / "ck"), flatten=mn.flatten,
                         earlier_trees=lambda: {"ok": True, "problems": []})
    return sess, sess.run(), cfg


# =====================================================================================================================================
# contract and plan
# =====================================================================================================================================


@test
def contract_values_equal_the_plan() -> None:
    eq("checkpoints", [c["name"] for c in K.CHECKPOINTS], ["ckpt_000000000", "ckpt_000409600", "ckpt_000614400", "ckpt_001228800", "final"])
    reg = json.loads((REPO / "runs/m9_g1/training/checkpoints.json").read_text(encoding="utf-8"))
    pins = {c["checkpoint"]: c["model_zip_sha256"] for c in reg["checkpoints"]}
    pins["final"] = reg["final"]["model_zip_sha256"]
    for c in K.CHECKPOINTS:
        eq(f"pin {c['name']} equals g1's checkpoints.json", c["sha256"], pins[c["name"]])
        eq(f"path {c['name']}", c["path"], f"runs/m9_g1/training/checkpoints/{c['name']}/model.zip")
    eq("start points (priority order)", K.START_POINTS, (2128, 2250, 2010))
    eq("counts", (K.N_STICKY, K.N_UNPERTURBED, K.N_DET, K.N_TAPE), (20, 20, 1, 20))
    eq("phase caps", K.WALL_CAPS_S, {"p1": 120.0, "eval": 1740.0, "verify": 420.0, "close": 120.0})
    eq("tick caps", K.TICK_CAPS, {"p1": 5000, "eval": 2500000, "verify": 600000, "close": 0})
    eq("total tick cap is the sum", K.TOTAL_TICK_CAP, sum(K.TICK_CAPS.values()))
    eq("session cap 45 min", K.GLOBAL_CAP_S, 2700.0)
    eq("process caps", (K.N_SLOTS, K.VERIFY_THREADS, K.MAX_BATTLESHIP_PROCESSES), (10, 8, 10))
    eq("memory caps as g1", K.MEMORY_CAPS_MB, dict(C.MEMORY_CAPS_MB))
    eq("roles", K.roles(K.EvalConfig(root=Path("x"))), {"untrained": "ckpt_000000000", "peak": "ckpt_000409600", "stall": "ckpt_000614400", "last_move": "ckpt_001228800",
                                                        "final": "final"})
    ok("every start point is inside the shared prefix", all(t <= C.SHARED_PREFIX for t in K.START_POINTS))


@test
def budget_fits_45_minutes_and_the_eval_tick_cap_covers_the_worst_case() -> None:
    bp = K.budget_projection()
    eq("pessimistic", bp["pessimistic_total_s"], 120 + 1740 + 420 + 120 + 30 + 80)
    ok("fits", bp["fits"] and bp["slack_s"] >= 150)
    n_eps = len(K.START_POINTS) * (len(K.CHECKPOINTS) * (K.N_STICKY + K.N_UNPERTURBED + K.N_DET) + K.N_TAPE)
    eq("episodes", n_eps, 675)
    ok("worst case (every episode to the 3,600-tick horizon) fits the eval tick cap", n_eps * C.HORIZON <= K.TICK_CAPS["eval"])
    ok("verification tick cap holds 250 replays of a 2,400-word clear", 250 * 2400 <= K.TICK_CAPS["verify"])


@test
def jobs_counts_pairing_and_priority() -> None:
    cfg = K.EvalConfig(root=Path("x"))
    jobs = K.build_jobs(cfg)
    eq("675 jobs", len(jobs), 675)
    eq("unique ids", len({j.job_id for j in jobs}), 675)
    by = {}
    for j in jobs:
        by.setdefault((j.kind, j.extra["model"], j.start.tau), []).append(j)
    for c in K.CHECKPOINTS:
        for t in K.START_POINTS:
            eq("sticky cell", len(by[("sticky", c["name"], t)]), 20)
            eq("unperturbed cell", len(by[("unperturbed", c["name"], t)]), 20)
            eq("det cell", len(by[("det", c["name"], t)]), 1)
    for t in K.START_POINTS:
        eq("tape", len(by[("tape", None, t)]), 20)
        for k in range(20):
            labels = {j.label for j in jobs if j.start.tau == t and j.extra["k"] == k and j.kind in ("sticky", "tape")}
            eq("one sticky label per (tau, k), shared by every checkpoint and the tape", labels, {K.sticky_label(t, k)})
    ok("unperturbed and det carry no sticky label", all(j.label is None for j in jobs if j.kind in ("unperturbed", "det")))
    ok("det is deterministic, the rest is not", all(j.deterministic == (j.kind == "det") for j in jobs))
    ok("every start is T_clear and shared", all(j.start.lineage == "T_clear" and j.start.shared for j in jobs))
    tiers = [j.tier for j in jobs]
    eq("tiers in order", tiers, sorted(tiers))
    first = jobs[:120]
    ok("the first 120 jobs are the 2,128 sticky cells and tape", all(j.start.tau == 2128 and j.kind in ("sticky", "tape") for j in first))
    eq("k interleaved across checkpoints", [j.extra["k"] for j in jobs[:6]], [0] * 6)
    eq("episode numbers are the list index", [j.episode for j in jobs[:5]], [0, 1, 2, 3, 4])


@test
def keys_never_name_the_checkpoint() -> None:
    eq("action key", POL.action_key("sticky", 2128, 7, 2130, "stick"), "m9|g1eval|act|sticky|2128|7|2130|stick")
    raises("unknown mode", ValueError, lambda: POL.action_key("det", 1, 1, 1, "stick"))
    raises("unknown dim", ValueError, lambda: POL.action_key("sticky", 1, 1, 1, "x"))
    eq("sticky key", S.sticky_key(K.sticky_label(2010, 3), 2011), "m9|g1|sticky|ckeval:2010:3|2011")
    ok("labels distinct from g1's", not K.sticky_label(2128, 0).startswith(("reach:", "train:", "fine:", "tick0:")))


@test
def inverse_cdf_exact_cases_and_refusals() -> None:
    p = [0.1, 0.2, 0.3, 0.4]
    eq("u=0", POL.inverse_cdf(p, 0.0), 0)
    eq("u just below 0.1", POL.inverse_cdf(p, 0.0999999), 0)
    eq("u=0.1", POL.inverse_cdf(p, 0.1), 1)
    eq("u=0.3", POL.inverse_cdf(p, 0.3000001), 2)
    eq("u near 1", POL.inverse_cdf(p, 0.9999999), 3)
    eq("zero mass skipped", POL.inverse_cdf([0.0, 1.0, 0.0], 0.5), 1)
    eq("u above a rounded sum", POL.inverse_cdf([0.5, 0.5, 0.0], 1.0), 1)
    eq("unnormalised", POL.inverse_cdf([1.0, 1.0], 0.6), 1)
    raises("negative", ValueError, lambda: POL.inverse_cdf([-0.1, 1.1], 0.5))
    raises("nan", ValueError, lambda: POL.inverse_cdf([float("nan"), 1.0], 0.5))
    raises("zero sum", ValueError, lambda: POL.inverse_cdf([0.0, 0.0], 0.5))


@test
def keyed_sampling_reproduces_the_distribution() -> None:
    p = np.array([0.05, 0.15, 0.30, 0.50])
    n = 20000
    counts = np.zeros(4)
    for i in range(n):
        counts[POL.inverse_cdf(p, S.uniform(POL.action_key("sticky", 2128, i % 20, i, "stick")))] += 1
    freq = counts / n
    ok(f"frequencies {freq} within 0.012 of {p}", np.all(np.abs(freq - p) < 0.012))
    a = [POL.inverse_cdf(p, S.uniform(POL.action_key("unperturbed", 2010, 3, t, "button"))) for t in range(50)]
    b = [POL.inverse_cdf(p, S.uniform(POL.action_key("unperturbed", 2010, 3, t, "button"))) for t in range(50)]
    eq("reproducible from the keys", a, b)


@test
def optimizer_guard_refuses_any_optimizer() -> None:
    import torch

    POL.install_optimizer_guard()
    POL.install_optimizer_guard()
    ok("installed", POL.guard_installed())
    prm = [torch.nn.Parameter(torch.zeros(2))]
    raises("SGD", POL.OptimizerForbidden, lambda: torch.optim.SGD(prm, lr=0.1))
    raises("Adam", POL.OptimizerForbidden, lambda: torch.optim.Adam(prm))


@test
def pinned_policy_on_a_synthetic_checkpoint() -> None:
    with tmpdir() as d:
        sd = fixed_state(stick_bias=4, button_bias=2, value_bias=1.5)
        sha = write_ckpt(d / "m.zip", sd)
        before = (d / "m.zip").read_bytes()
        pol = POL.PinnedPolicy("t", d / "m.zip", sha)
        eq("bytes untouched", (d / "m.zip").read_bytes(), before)
        ok("no parameter requires a gradient", not any(p.requires_grad for p in pol.net.parameters()))
        x = np.zeros(606, dtype=np.float32)
        eq("argmax = biased stick and button", pol.argmax_word(x), 4 * 8 + 2)
        eq("value = bias", round(pol.value(x), 6), 1.5)
        ps, pb = pol.probabilities(x)
        ok("probabilities sum to 1", abs(ps.sum() - 1) < 1e-6 and abs(pb.sum() - 1) < 1e-6)
        eq("stick probability peak", int(np.argmax(ps)), 4)
        w1 = [pol.sample_word(x, "sticky", 2128, 1, t) for t in range(2128, 2178)]
        w2 = [pol.sample_word(x, "sticky", 2128, 1, t) for t in range(2128, 2178)]
        eq("sampling reproducible", w1, w2)
        ok("samples are words", all(0 <= w < 72 for w in w1))
        raises("wrong pin", POL.PinError, lambda: POL.PinnedPolicy("t", d / "m.zip", "0" * 64))
        bad = dict(sd)
        bad.pop("value_net.bias")
        sha2 = write_ckpt(d / "bad.zip", bad)
        raises("wrong keys", POL.PinError, lambda: POL.PinnedPolicy("t", d / "bad.zip", sha2))
        eq("pin problems none", POL.pin_problems([{"name": "t", "path": "m.zip", "sha256": sha}], d), [])
        eq("pin problems missing", len(POL.pin_problems([{"name": "t", "path": "nope.zip", "sha256": sha}], d)), 1)


@test
def two_checkpoints_share_draws_common_random_numbers() -> None:
    with tmpdir() as d:
        s1 = write_ckpt(d / "a.zip", fixed_state(stick_bias=1))
        s2 = write_ckpt(d / "b.zip", fixed_state(stick_bias=1))
        pa, pb = POL.PinnedPolicy("a", d / "a.zip", s1), POL.PinnedPolicy("b", d / "b.zip", s2)
        x = np.full(606, 0.1, dtype=np.float32)
        eq("identical policies sample identical words under the same keys", [pa.sample_word(x, "sticky", 2250, k, 2250) for k in range(20)],
           [pb.sample_word(x, "sticky", 2250, k, 2250) for k in range(20)])


# =====================================================================================================================================
# the real checkpoints and records (read only, zero native ticks)
# =====================================================================================================================================


@test
def real_checkpoint_pins_hold() -> None:
    eq("pins", POL.pin_problems(K.CHECKPOINTS, REPO), [])


@test
def real_final_policy_reproduces_the_recorded_deterministic_first_words() -> None:
    import m7n_obs as mn
    import m9_obs

    tr = json.load(gzip.open(REPO / "runs/m8_rd_rd4/routes/T_clear/trace.json.gz", "rt", encoding="utf-8"))
    v3tab = (REPO / "runs/m9_g1/lineages/T_clear/v3.bin").read_bytes()
    want = {2128, 1966, 1694, 1473, 1369, 1248, 0}
    pipe = m9_obs.V3Pipeline(tr["initial"])
    obs = {0: mn.flatten(pipe.arrays())}
    eq("tick 0 v3 digest", bytes.fromhex(pipe.digest()), v3tab[:32])
    for i, st in enumerate(tr["steps"]):
        pipe.feed(st)
        t = i + 1
        if t in want:
            obs[t] = mn.flatten(pipe.arrays())
            eq(f"v3 digest at {t}", bytes.fromhex(pipe.digest()), v3tab[32 * t:32 * t + 32])
        if t >= max(want):
            break
    e = K.CHECKPOINTS[-1]
    pol = POL.PinnedPolicy(e["name"], REPO / e["path"], e["sha256"])
    rec = [json.loads(ln) for ln in open(REPO / "runs/m9_g1/eval/episodes.jsonl", encoding="utf-8")]
    n = 0
    for r in rec:
        if r["eval_kind"] in ("reach_det", "tick0_det"):
            t = r["landing"] if r["eval_kind"] == "reach_det" else 0
            eq(f"first deterministic word at {t}", pol.argmax_word(obs[t]), int(r["sampled_hex"][:2], 16))
            n += 1
    eq("seven deterministic episodes checked", n, 7)


@test
def real_table_registration_matches_the_g1_run() -> None:
    reg = json.loads((REPO / "runs/m9_g1/lineages/T_clear/registration.json").read_text(encoding="utf-8"))
    for f in L.TABLE_FILES:
        eq(f"{f} sha256", hashlib.sha256((REPO / "runs/m9_g1/lineages/T_clear" / f).read_bytes()).hexdigest(), reg["table_sha256"][f])


# =====================================================================================================================================
# aggregation and readings
# =====================================================================================================================================


def _rec(kind: str, model: Optional[str], tau: int, k: int, end: str) -> Dict[str, Any]:
    return {"episode": f"{kind}-{model}-{tau}-{k:02d}", "eval_kind": kind, "model": model, "landing": tau, "k": k, "clear": end == "clear", "end_reason": end,
            "policy_ticks": 100}


def _agg(spec: Mapping[Tuple[str, int], Sequence[int]], tape: Mapping[int, int] = {}, unverified: Sequence[Tuple[str, int, int]] = (),
         points: Sequence[int] = (2128, 2250, 2010), unperturbed: Mapping[Tuple[str, int], int] = {}, det: Mapping[Tuple[str, int], bool] = {},
         names: Sequence[str] = ROLE_NAMES, n: int = 20, det_unverified: Sequence[Tuple[str, int]] = (),
         unperturbed_unverified: Mapping[Tuple[str, int], int] = {}) -> Tuple[Dict[str, Any], K.EvalConfig]:
    cfg = K.EvalConfig(root=Path("x"), checkpoints=[{"name": m, "path": "", "sha256": ""} for m in names], start_points=points)
    recs, ver = [], {}
    for m in names:
        for t in points:
            clears = set(spec.get((m, t), ()))
            for k in range(n):
                r = _rec("sticky", m, t, k, "clear" if k in clears else "fall")
                recs.append(r)
                ver[r["episode"]] = r["clear"] and (m, t, k) not in unverified
            uc = unperturbed.get((m, t), 0)
            for k in range(n):
                r = _rec("unperturbed", m, t, k, "clear" if k < uc else "horizon")
                recs.append(r)
                ver[r["episode"]] = r["clear"] and k >= unperturbed_unverified.get((m, t), 0)
            r = _rec("det", m, t, 0, "clear" if det.get((m, t)) else "horizon")
            recs.append(r)
            ver[r["episode"]] = r["clear"] and (m, t) not in det_unverified
    for t in points:
        for k in range(n):
            r = _rec("tape", None, t, k, "clear" if k < tape.get(t, 0) else "fall")
            recs.append(r)
            ver[r["episode"]] = r["clear"]
    return K.aggregate(recs, ver, cfg), cfg


@test
def sign_test_values() -> None:
    eq("5-0", round(K.sign_test_p(5, 0), 5), round(1 / 32, 5))
    eq("6-1", round(K.sign_test_p(6, 1), 5), round(8 / 128, 5))
    eq("0-0", K.sign_test_p(0, 0), 1.0)
    eq("7-1", round(K.sign_test_p(7, 1), 5), round(9 / 256, 5))


@test
def aggregate_counts_only_verified_clears() -> None:
    a, cfg = _agg({("ck_e", 2128): [0, 1, 2]}, unverified=[("ck_e", 2128, 2)])
    x = a["cells"]["sticky"]["ck_e"][2128]
    eq("claimed / verified / unverified", (x["clears"], x["verified"], x["unverified"]), (3, 2, 1))
    eq("complete", x["complete"], True)
    eq("by_k", (x["by_k"][0], x["by_k"][2], x["by_k"][5]), ("V", "u", "f"))


@test
def readings_h1_supported_decay_and_interference() -> None:
    a, cfg = _agg({("ck_b", 2128): range(8), ("ck_a", 2128): range(6), ("ck_e", 2128): []})
    rd = K.readings(a, K.roles(cfg))
    eq("H1", rd["H1"]["reading"], "supported_decay")
    eq("interference", rd["H1"]["interference"], True)
    d = [x for x in rd["H1"]["declines"] if x["a"] == "ck_b" and x["tau"] == 2128][0]
    eq("decline row", (d["c_a"], d["c_b"], d["b_only_a"], d["b_only_b"], d["decline"]), (8, 0, 8, 0, True))


@test
def readings_h1_needs_the_paired_test_not_only_the_difference() -> None:
    # 9 vs 4 clears but the pairs overlap badly: b = 6, d = 1 -> p = 0.0625 > 0.05: no decline
    a, cfg = _agg({("ck_b", 2128): list(range(9)), ("ck_e", 2128): [0, 1, 2, 19]})
    rd = K.readings(a, K.roles(cfg))
    d = [x for x in rd["H1"]["declines"] if x["a"] == "ck_b" and x["tau"] == 2128][0]
    eq("diff", d["diff"], 5)
    eq("pairs", (d["b_only_a"], d["b_only_b"]), (6, 1))
    eq("no decline", d["decline"], False)
    eq("H1 undecided", rd["H1"]["reading"], "undecided")


@test
def readings_h1_contradicted_and_incomplete() -> None:
    a, cfg = _agg({("ck_a", 2128): [0, 1], ("ck_b", 2128): [0, 1, 2], ("ck_e", 2128): [0], ("ck_a", 2250): [0, 1, 2, 3], ("ck_c", 2250): [0, 1, 2, 3, 4, 5],
                   ("ck_e", 2250): [1, 2, 3, 4]})
    eq("H1 contradicted", K.readings(a, K.roles(cfg))["H1"]["reading"], "contradicted_never_learned")
    a, cfg = _agg({("ck_b", 2128): range(8)}, unverified=[("ck_b", 2128, 0)])
    rd = K.readings(a, K.roles(cfg))
    eq("an unverified clear makes it undecided", rd["H1"]["reading"], "undecided_incomplete")


@test
def readings_h3_and_h2_and_stickiness() -> None:
    a, cfg = _agg({("ck_d", 2010): [0, 1], ("ck_c", 2010): [0], ("ck_b", 2128): range(7), ("ck_e", 2250): range(6)},
                  unperturbed={("ck_e", 2250): 12}, det={("ck_e", 2128): False})
    rd = K.readings(a, K.roles(cfg))
    eq("move 16 supported", rd["H3"]["move16"]["reading"], "supported")
    eq("move 9 competence real", rd["H3"]["move9"]["reading"], "competence_real")
    eq("H2 premise holds (det fails where sticky >= 5)", rd["H2"]["premise_argmax_does_not_clear"], "holds")
    eq("stickiness", rd["stickiness"], [{"model": "ck_e", "tau": 2250, "unperturbed": 12, "sticky": 6}])
    eq("tape margin", rd["tape_margin"]["2250"]["ck_e"], 6)
    a, cfg = _agg({("ck_d", 2010): range(6), ("ck_e", 2250): range(6)}, det={("ck_e", 2250): True})
    rd = K.readings(a, K.roles(cfg))
    eq("move 16 contradicted", rd["H3"]["move16"]["reading"], "contradicted")
    eq("H2 premise contradicted", rd["H2"]["premise_argmax_does_not_clear"], "contradicted")
    a, cfg = _agg({})
    eq("H2 vacuous", K.readings(a, K.roles(cfg))["H2"]["premise_argmax_does_not_clear"].startswith("vacuous"), True)


@test
def readings_treat_unverified_clears_as_undecided() -> None:
    a, cfg = _agg({("ck_e", 2250): range(6)}, det={("ck_e", 2250): True}, det_unverified=[("ck_e", 2250)])
    rd = K.readings(a, K.roles(cfg))
    eq("H2 with an unverified deterministic clear", rd["H2"]["premise_argmax_does_not_clear"], "undecided_incomplete")
    a, cfg = _agg({("ck_e", 2250): range(6)}, unperturbed={("ck_e", 2250): 12}, unperturbed_unverified={("ck_e", 2250): 3})
    rd = K.readings(a, K.roles(cfg))
    eq("no definite stickiness effect (9 verified vs 6)", rd["stickiness"], [])
    eq("but an undecided one", len(rd["stickiness_undecided"]), 1)
    a, cfg = _agg({("ck_d", 2010): [0, 1, 2, 3]}, unverified=[("ck_d", 2010, 3)])
    eq("move 16 with an unverified clear", K.readings(a, K.roles(cfg))["H3"]["move16"]["reading"], "undecided_incomplete")


@test
def interference_is_read_only_at_the_decayed_point() -> None:
    # decay at 2,128 only; the untrained policy beats the final at 2,250 but not at 2,128: no interference
    a, cfg = _agg({("ck_b", 2128): range(8), ("ck_a", 2250): range(8)})
    rd = K.readings(a, K.roles(cfg))
    eq("H1", rd["H1"]["reading"], "supported_decay")
    eq("decayed points", rd["H1"]["decayed_points"], [2128])
    eq("interference", rd["H1"]["interference"], False)


# =====================================================================================================================================
# tables, guards
# =====================================================================================================================================


@test
def copy_registered_tables_checks_every_digest() -> None:
    with tmpdir() as d:
        src = d / "src" / "T_clear"
        src.mkdir(parents=True)
        blobs = {"words.bin": bytes(range(10)), "chain.bin": b"c" * 352, "v3.bin": b"v" * 352}
        for f, b in blobs.items():
            (src / f).write_bytes(b)
        reg = {"table_sha256": {f: hashlib.sha256(b).hexdigest() for f, b in blobs.items()}}
        (src / "registration.json").write_text(json.dumps(reg), encoding="utf-8")
        before = {f: (src / f).read_bytes() for f in blobs}
        r = K.copy_registered_tables(d / "src", d / "dst")
        eq("ok", r["ok"], True)
        eq("copied bytes", (d / "dst" / "T_clear" / "v3.bin").read_bytes(), blobs["v3.bin"])
        eq("source untouched", {f: (src / f).read_bytes() for f in blobs}, before)
        raises("an existing destination is refused", FileExistsError, lambda: K.copy_registered_tables(d / "src", d / "dst"))
        reg["table_sha256"]["v3.bin"] = "0" * 64
        (src / "registration.json").write_text(json.dumps(reg), encoding="utf-8")
        r = K.copy_registered_tables(d / "src", d / "dst2")
        eq("a registration mismatch is a problem", (r["ok"], len(r["problems"])), (False, 1))


@test
def write_guard_covers_the_g1_and_m8_trees() -> None:
    import m9_eval_session as ES

    roots = {p.resolve() for p in ES.write_guard_roots()}
    for name in ("m9_g1", "m8_rd", "m8_rd_rd2", "m8_rd_rd3", "m8_rd_rd4"):
        ok(f"runs/{name} protected", (REPO / "runs" / name).resolve() in roots)
    ok("rl and docs protected", (REPO / "rl").resolve() in roots and (REPO / "docs").resolve() in roots)
    ok("the evaluation's own tree is not protected", (REPO / "runs" / K.RUN_NAME).resolve() not in roots)
    eq("the five protected trees", [t[0] for t in ES.TREES], ["rd1", "rd2", "rd3", "rd4", "m9_g1"])


@test
def source_guards() -> None:
    files = {f: (RL / f).read_text(encoding="utf-8") for f in ("m9_eval_policy.py", "m9_eval_ckpt.py", "m9_eval_session.py", "m9_eval_snapshot.py")}
    tests_src = (RL / "m9_eval_tests.py").read_text(encoding="utf-8")
    for f, src in files.items():
        for bad in ("tas_input", ".btti", "fixtures/m7g", "m7g_capture", "replay/recordings"):
            ok(f"{f}: no reference to {bad}", bad not in src)
        for bad in ("import random", "np.random", "torch.manual_seed", "import secrets", "import uuid", "os.urandom", "rng_seed", "native_rng"):
            ok(f"{f}: no {bad}", bad not in src)
        for bad in (".learn(", "PPO(", "PPO.load", ".backward(", "optimizer.step", "zero_grad", "torch.optim.Adam(", "torch.optim.SGD("):
            ok(f"{f}: no training vocabulary {bad}", bad not in src)
    tree = ast.parse(tests_src)
    for node in ast.walk(tree):                                   # the suite itself: no random generator of any kind, no fixture or TAS path
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            ok(f"the suite imports no random generator ({mods})", not any(m.split(".")[0] in ("random", "secrets", "uuid") for m in mods))
        if isinstance(node, ast.Attribute) and node.attr in ("random", "urandom", "manual_seed") and isinstance(node.value, ast.Name) and node.value.id in ("np", "os", "torch"):
            raise AssertionError(f"the suite uses {node.value.id}.{node.attr}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(FORBIDDEN_PATH_PREFIXES):
            raise AssertionError(f"the suite references {node.value}")
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and any(isinstance(d, ast.Name) and d.id == "test" for d in fn.decorator_list):
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "time" and node.attr in ("time", "sleep", "monotonic", "perf_counter"):
                    raise AssertionError(f"{fn.name}: reads a wall clock or sleeps (time.{node.attr})")


# =====================================================================================================================================
# the engine on the synthetic world
# =====================================================================================================================================


@test
def synthetic_session_runs_every_phase_and_verifies_every_clear() -> None:
    import m9_eval_session as ES

    with tmpdir() as d:
        sess, out, cfg = synthetic_session(d)
        eq("status", out["status"], "COMPLETE")
        eq("phases", out["phases"], {"p1": True, "eval": True, "verify": True})
        eq("no invalid", out["invalid"], [])
        n = len(K.build_jobs(cfg))
        eq("planned", n, 3 * (5 * (2 + 1 + 1) + 2))
        eps = A.read_jsonl(cfg.root / "eval" / "episodes.jsonl")
        eq("every job recorded once", sorted(r["episode"] for r in eps), sorted(j.job_id for j in K.build_jobs(cfg)))
        clears = [r for r in eps if r["clear"]]
        ok("the synthetic world produced clears (the verification path ran)", len(clears) > 0)
        reps = A.read_jsonl(cfg.root / "verification" / "replays.jsonl")
        eq("every clear replayed", sorted(x["id"] for x in reps), sorted(r["episode"] for r in clears))
        ok("every replay exact", all(x["exact"] for x in reps))
        ok("start value recorded for policy episodes", all(r["start_value"] is not None for r in eps if r["driver"] == "policy"))
        aud = A.audit_tree(cfg.root, skip_dirs=("workers", "vw"))
        ok(f"metadata audit {aud['failures'][:2]}", aud["ok"])
        vr = ES.verify_run(cfg.root, cfg, check_pins=False)
        ok(f"verify-run re-derives the run: {vr['problems'][:3]}", vr["ok"])
        eq("verify-run counts", (vr["episodes"], vr["planned"], vr["missing_jobs"]), (n, n, 0))
        eq("ticks recorded", set(out["ticks"]), {"p1", "eval", "verify"})
        ok("within the total tick cap", out["total_ticks"] <= cfg.total_tick_cap)


@test
def synthetic_session_is_a_pure_function_of_its_configuration() -> None:
    with tmpdir() as d1, tmpdir() as d2:
        _s1, o1, c1 = synthetic_session(d1)
        _s2, o2, c2 = synthetic_session(d2)
        r1 = [strip_volatile(r) for r in A.read_jsonl(c1.root / "eval" / "episodes.jsonl")]
        r2 = [strip_volatile(r) for r in A.read_jsonl(c2.root / "eval" / "episodes.jsonl")]
        eq("episode records", sorted(r1, key=lambda r: r["episode"]), sorted(r2, key=lambda r: r["episode"]))
        eq("readings", strip_volatile(o1["readings"]), strip_volatile(o2["readings"]))
        eq("aggregate", strip_volatile(o1["aggregate"]), strip_volatile(o2["aggregate"]))


@test
def synthetic_session_is_invalid_on_a_tampered_table() -> None:
    with tmpdir() as d:
        _s, out, cfg = synthetic_session(d, tamper=True)
        eq("status", out["status"], "INVALID")
        ok("stopped in P1", out["stop"]["phase"] == "p1")
        ok("nothing evaluated", not (cfg.root / "eval" / "episodes.jsonl").exists())


@test
def synthetic_session_refuses_a_wrong_checkpoint_pin_before_any_tick() -> None:
    with tmpdir() as d:
        _s, out, cfg = synthetic_session(d, bad_pin=True)
        eq("status", out["status"], "INCOMPLETE")
        ok("the pin mismatch is the reason", "differs from the pin" in out["stop"]["reason"])
        eq("no native tick", out["total_ticks"], 0)


@test
def synthetic_session_is_partial_at_a_small_eval_tick_cap() -> None:
    with tmpdir() as d:
        _s, out, cfg = synthetic_session(d, eval_cap=60_000)
        eq("status", out["status"], "PARTIAL")
        ok("cells left incomplete are named", out["incomplete_cells"] or out["missing_cells"])
        ok("the stop was the valid tick cap", out["stop"] is None)
        ok("evaluation ticks within the cap", out["ticks"]["eval"] <= 60_000)


@test
def synthetic_session_is_partial_when_clears_go_unverified() -> None:
    import m9_eval_session as ES

    with tmpdir() as d:
        _s, out, cfg = synthetic_session(d, verify_cap=1)
        eps = A.read_jsonl(cfg.root / "eval" / "episodes.jsonl")
        n_clear = sum(1 for r in eps if r["clear"])
        ok("the synthetic run has clears", n_clear > 0)
        eq("status", out["status"], "PARTIAL")
        eq("every clear recorded as unverified", sorted(out["unverified_clears"]), sorted(r["episode"] for r in eps if r["clear"]))
        ok("no clear counted", all(x["verified"] == 0 for per in out["aggregate"]["cells"]["sticky"].values() for x in per.values()))
        vr = ES.verify_run(cfg.root, cfg, check_pins=False)
        ok(f"verify-run consistent with the recorded unverified clears: {vr['problems'][:3]}", vr["ok"])


# =====================================================================================================================================


def run_unit(only: Optional[Sequence[str]] = None) -> int:
    passed, failed = 0, []
    t_all = time.time()
    for name, fn in TESTS:
        if only and not any(name.startswith(o) for o in only):
            continue
        t0 = time.time()
        try:
            fn()
            passed += 1
            print(f"PASS {name} ({time.time() - t0:.1f}s)", flush=True)
        except Exception as exc:                                    # noqa: BLE001
            failed.append(name)
            print(f"FAIL {name} ({time.time() - t0:.1f}s): {type(exc).__name__}: {str(exc)[:600]}", flush=True)
            traceback.print_exc(limit=6)
    total = passed + len(failed)
    print(f"m9 eval unit suite: {passed}/{total} passed" + (f" (failed: {', '.join(failed)})" if failed else "") + f" in {time.time() - t_all:.0f}s")
    return 0 if not failed else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "unit"
    if cmd == "unit":
        return run_unit(args[1:] or None)
    if cmd == "list":
        for n, _f in TESTS:
            print(n)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
