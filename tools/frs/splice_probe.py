"""Splice probe (lab, unregistered): does the agent's own archive already hold a faster clear, made by joining an earlier
arrival at a cell of the best verified route with that route's own continuation from the same cell?

Generic rule (no cell id, position, target id or tick literal anywhere): for every cell the route passes through (its first
reach on the route, read from the route's own burst chain in the archive), if the cell's archive representative arrived
earlier than the route did (gain >= 1 tick), the candidate is the representative's stored words up to its arrival followed
by the route's words from the route's own arrival at that cell to the end. Only the agent's own trajectories are read.

  python -B tools/frs/splice_probe.py plan [--out DIR]    zero native ticks: candidates, plan and the run command
  python -B tools/frs/splice_probe.py run  [--out DIR]    native replays (only under the owner's authorisation)

Every replay is a fresh BattleShip process from tick 0 with the verify flags (rl/m9_contract.FLAGS_VERIFY) and the M8
archive's frozen runtime configuration (as sd2's verification replays), stepped by rl/m7f_trace.run_stepping_trace
unchanged. The probe stops submitting words after a native failure (a fall: the steps after it hang natively). The unspliced
route is replayed first as the control and must reproduce its registered clear. Every clear is replayed a second time in
another fresh process; it counts only if both replays clear with identical chain digests and clocks. Writes only under the
output directory (default C:/BattleShip_lab/splice_probe_<date>); refuses the checkout, any runs/ folder and the D:
evidence folders. Standard library plus the repository's rl/ modules; run with python -B.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import gzip
import hashlib
import json
import os
import shutil
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict, deque
from collections.abc import Sequence as SequenceABC
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "rl"))

import m8_rd_cells as mcell  # noqa: E402
import m9_contract as mc  # noqa: E402

ARCHIVE = REPO / "runs" / "m8_rd_sd2" / "archive"
ROUTE = REPO / "runs" / "m8_rd_sd2" / "routes" / "T_clear_best"
FROZEN = REPO / "runs" / "m8_rd" / "archive" / "runtime"
EXECUTABLE = REPO / "build-us" / "Release" / "BattleShip.exe"
LAB_ROOT = Path("C:/BattleShip_lab")
FORBIDDEN = (REPO, Path("D:/BattleShip_runs_backup"), Path("D:/BattleShip_source_snapshots"), Path("D:/BattleShip_exe_archive"))
ARCHIVE_FILES = ("cells.jsonl", "bursts.bin", "bursts.idx.jsonl")
NO_CLOCK = tuple(i for i, k in enumerate(mcell.OBS_FIELDS) if k in ("host_frame", "input_tick", "time_passed"))
I = mcell.OBS_INDEX
SIMILAR_V = 10.0          # the F5 "similar" motion test of the proposal and the review: each velocity within this, same facing,
                          # jumps used and status


# -- paths and small helpers ---------------------------------------------------------------------------------------------------------


def check_out(out: Path) -> Path:
    out = Path(os.path.abspath(out))
    norm = os.path.normcase(str(out))
    for f in FORBIDDEN:
        fn = os.path.normcase(os.path.abspath(f))
        if norm == fn or norm.startswith(fn.rstrip("\\/") + os.sep):
            raise SystemExit(f"refused: output directory {out} is inside {f}")
    if any(p.lower() == "runs" for p in out.parts):
        raise SystemExit(f"refused: output directory {out} is under a runs/ folder")
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")


def chain_list(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> List[bytes]:
    """chain[k] = the m8_rd chain digest after input tick k (k = 0: the tick-0 observe record)."""
    ch = [mcell.chain_start(mcell.tick0_record(initial))]
    for s in steps:
        ch.append(mcell.chain_next(ch[-1], mcell.record_digest(mcell.record_of(s))))
    return ch


def breaks_of(trace: Mapping[str, Any]) -> List[Tuple[int, int]]:
    """[(input tick, target id)] in tick order, from the read-only target diagnostic (m7n_crossing.analyse_trace)."""
    import m7n_crossing as xc

    an = xc.analyse_trace(trace["initial"], trace["steps"])
    return sorted((int(t) + 1, int(i)) for i, t in an["breaks"])


# -- the candidate rule (zero native ticks) --------------------------------------------------------------------------------------------


def load_archive(arch: Path) -> Dict[str, Any]:
    man = {ln.split()[1]: ln.split()[0] for ln in (arch / "manifest.sha256").read_text(encoding="utf-8").splitlines() if ln.strip()}
    for n in ARCHIVE_FILES:
        if sha256_file(arch / n) != man.get(n):
            raise SystemExit(f"refused: {arch / n} does not match the archive manifest")
    cells = []
    with open(arch / "cells.jsonl", encoding="utf-8") as f:
        for ln in f:
            c = json.loads(ln)
            cells.append({k: c[k] for k in ("id", "key", "level", "L", "burst", "offset", "end", "ch", "doomed", "first_iter")})
    raw = (arch / "bursts.bin").read_bytes()
    bursts = []
    with open(arch / "bursts.idx.jsonl", encoding="utf-8") as f:
        for ln in f:
            b = json.loads(ln)
            bursts.append({"id": b["id"], "start_rep": tuple(b["start_rep"]), "start_L": b["start_L"], "n": b["n"],
                           "words": raw[b["bin_off"]:b["bin_off"] + b["n"]], "reaches": b["reaches"],
                           "iteration": b["iteration"], "session": b["session"]})
    assert all(c["id"] == i for i, c in enumerate(cells)) and all(b["id"] == i for i, b in enumerate(bursts))
    return {"cells": cells, "bursts": bursts, "manifest": {n: man[n] for n in ARCHIVE_FILES}}


def rep_words(bursts: Sequence[Mapping[str, Any]], b: int, o: int) -> bytes:
    segs = []
    while b != -1:
        segs.append(bursts[b]["words"][:o])
        b, o = bursts[b]["start_rep"]
    return b"".join(reversed(segs))


def load_route(route: Path) -> Dict[str, Any]:
    meta = json.loads((route / "metadata.json").read_text(encoding="utf-8"))
    idx = {t: w for w, t in enumerate(mcell.TRIPLES)}
    words = bytearray()
    with open(route / "actions.jsonl", encoding="utf-8") as f:
        for i, ln in enumerate(f):
            a = json.loads(ln)
            assert a["consumed_tick"] == i == a["sequence_index"]
            words.append(idx[(a["buttons"], a["stick_x"], a["stick_y"])])
    words = bytes(words)
    assert len(words) == meta["words"] and mcell.words_digest(words) == meta["native_action_digest"]
    with gzip.open(route / "trace.json.gz", "rt", encoding="utf-8") as f:
        trace = json.load(f)
    assert trace["action_digest"] == meta["native_action_digest"] and len(trace["steps"]) == len(words)
    assert trace["extra_env"] == mc.FLAGS_VERIFY, "the route trace was not made with the verify flags"
    return {"meta": meta, "words": words, "trace": trace, "chain": chain_list(trace["initial"], trace["steps"]),
            "breaks": breaks_of(trace)}


def route_chain_bursts(bursts: Sequence[Mapping[str, Any]], meta: Mapping[str, Any], words: bytes) -> List[Tuple[int, int]]:
    """The route's burst chain [(burst, words used)] from tick 0: the burst of the route's iteration whose representative
    prefix plus its words reproduce the route's words."""
    hits = [b for b in bursts if b["iteration"] == meta["iteration"] and b["session"] == meta["session"]
            and (rep_words(bursts, *b["start_rep"]) + b["words"])[:len(words)] == words]
    assert len(hits) == 1, f"{len(hits)} bursts reproduce the route"
    b, o = hits[0]["id"], len(words) - hits[0]["start_L"]
    assert 0 < o <= hits[0]["n"]
    chain = []
    while b != -1:
        chain.append((b, o))
        b, o = bursts[b]["start_rep"]
    return list(reversed(chain))


def build_plan(arch: Path = ARCHIVE, route_dir: Path = ROUTE) -> Dict[str, Any]:
    A = load_archive(arch)
    R = load_route(route_dir)
    cells, bursts, words = A["cells"], A["bursts"], R["words"]
    chain = route_chain_bursts(bursts, R["meta"], words)
    first: Dict[int, int] = {}                    # cell id -> the route's first reach (input tick)
    L = 0
    for b, o in chain:
        assert bursts[b]["start_L"] == L
        for r in bursts[b]["reaches"]:
            j, cid = int(r[0]), int(r[1])
            if j <= L + o and cid not in first:
                first[cid] = j
        L += o
    assert L == len(words)
    steps = R["trace"]["steps"]
    rb = R["breaks"]
    same_ch = [0, 0]                              # gain-0 route cells: the stored chain digest equals the replayed route's
    cands = []
    for cid, jr in sorted(first.items(), key=lambda kv: kv[1]):
        c = cells[cid]
        g = jr - c["L"]
        if g == 0:
            same_ch[1] += 1
            same_ch[0] += int(R["chain"][jr].hex() == c["ch"])
        if g < 1:
            continue
        pre = rep_words(bursts, c["burst"], c["offset"])
        assert len(pre) == c["L"]
        ob, e = steps[jr - 1]["observation"], c["end"]
        assert ob["input_tick"] == jr
        dv = {k: round(abs(ob[k] - e[I[k]]), 3) for k in ("air_velocity_x", "air_velocity_y", "ground_velocity_x")}
        same = {k: ob[k] == e[I[k]] for k in ("facing_direction", "ground_air_state", "fighter_status_id", "jumps_used")}
        similar = all(v < SIMILAR_V for v in dv.values()) and same["facing_direction"] and same["jumps_used"] \
            and same["fighter_status_id"]
        sw = pre + words[jr:]
        cands.append({"cid": cid, "level": c["level"], "key": c["key"], "route_tick": jr, "rep_L": c["L"], "gain": g,
                      "words": len(sw), "rep_session": bursts[c["burst"]]["session"] if c["burst"] >= 0 else None,
                      "rep_first_iter": c["first_iter"], "rep_doomed": c["doomed"], "similar": bool(similar),
                      "dpos": round(max(abs(ob["position_x"] - e[I["position_x"]]), abs(ob["position_y"] - e[I["position_y"]])), 1),
                      "dv": dv, "same": same, "route_breaks_after": sum(1 for t, _ in rb if t > jr),
                      "rep_end": e, "rep_ch": c["ch"], "words_digest": mcell.words_digest(sw), "words_hex": sw.hex()})
    cands.sort(key=lambda r: (-r["route_tick"], r["cid"]))          # run order: the latest splice points first
    for n, r in enumerate(cands):
        r["n"] = n
    per = defaultdict(lambda: {"route_cells": 0, "candidates": 0, "gain_ge_30": 0, "similar": 0, "gains": []})
    for cid, jr in first.items():
        per[cells[cid]["level"]]["route_cells"] += 1
    for r in cands:
        p = per[r["level"]]
        p["candidates"] += 1
        p["gain_ge_30"] += int(r["gain"] >= 30)
        p["similar"] += int(r["similar"])
        p["gains"].append(r["gain"])
    levels = {str(lv): {"route_cells": p["route_cells"], "candidates": p["candidates"], "gain_ge_30": p["gain_ge_30"],
                        "similar": p["similar"], "max_gain": max(p["gains"], default=None),
                        "median_gain": statistics.median(p["gains"]) if p["gains"] else None}
              for lv, p in sorted(per.items())}
    tr = R["trace"]
    screen = sum(r["words"] for r in cands)
    plan = {"utc": utc(), "rule": "splice_rule_v1: route first reach j_r per cell; representative L < j_r; words = rep[:L] + route[j_r:]",
            "archive": str(arch), "archive_manifest": A["manifest"], "route": str(route_dir),
            "route_words": len(words), "route_digest": R["meta"]["native_action_digest"],
            "route_clocks": {k: tr["result"][k] for k in ("completion_input_tick", "completion_time_passed")},
            "route_final_chain": R["chain"][-1].hex(), "route_breaks": rb, "route_chain_bursts": len(chain),
            "route_cells": len(first), "candidates": len(cands), "gain_ge_30": sum(1 for r in cands if r["gain"] >= 30),
            "similar": sum(1 for r in cands if r["similar"]), "per_level": levels,
            "gain0_stored_chain_equal": {"equal": same_ch[0], "of": same_ch[1]},
            "flags": mc.FLAGS_VERIFY, "budget": {"control_ticks": len(words), "screen_ticks_max": screen,
                                                  "processes_min": 1 + len(cands),
                                                  "route_trace_startup_s": tr.get("startup_s"),
                                                  "route_trace_stepping_s": tr.get("stepping_s")},
            "candidate_set_digest": hashlib.sha256("".join(r["words_digest"] for r in cands).encode()).hexdigest()}
    return {"plan": plan, "candidates": cands, "route": R}


def cmd_plan(out: Path) -> int:
    P = build_plan()
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "plan.json", P["plan"])
    with open(out / "candidates.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in P["candidates"]:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    p = P["plan"]
    print(json.dumps({k: p[k] for k in ("route_words", "route_clocks", "route_chain_bursts", "route_cells", "candidates",
                                        "gain_ge_30", "similar", "gain0_stored_chain_equal", "budget",
                                        "candidate_set_digest")}, separators=(",", ":")))
    for lv, s in p["per_level"].items():
        print("level", lv, json.dumps(s, separators=(",", ":")))
    print(f"wrote {out / 'plan.json'} and {out / 'candidates.jsonl'}")
    return 0


# -- native replays --------------------------------------------------------------------------------------------------------------------


class StopAfterFailure(SequenceABC):
    """The action list handed to m7f_trace.run_stepping_trace; iteration ends after a step reply that is a native failure
    (btt_native_failure_v1: a fall). Indexing and len() are the plain list's."""

    def __init__(self, actions: List[Tuple[int, int, int, int]]):
        self.actions = actions
        self.last: Optional[Mapping[str, Any]] = None

    def __len__(self) -> int:
        return len(self.actions)

    def __getitem__(self, i):
        return self.actions[i]

    def __iter__(self):
        for a in self.actions:
            r = self.last
            if r is not None and mcell.is_native_failure(r["observation"], r["state"]):
                return
            yield a

    def on_ready(self, episode: Any) -> None:
        client = episode.client
        original = client.request

        def request(op: str, **payload: Any) -> Dict[str, Any]:
            reply = original(op, **payload)
            if op == "step":
                self.last = reply
            return reply

        client.request = request


def install_frozen(out: Path) -> Dict[str, Any]:
    """Pin checks, then the frozen configuration copied into the lab folder and installed into every private runtime (as
    the M8 sessions' build_real_env)."""
    import m7_runtime

    fz = json.loads((FROZEN / "frozen_runtime.json").read_text(encoding="utf-8"))
    problems = []
    if sha256_file(EXECUTABLE) != fz["exe_copy_sha256"]["BattleShip.exe"]:
        problems.append("executable differs from the archive's pinned copy")
    for n, h in fz["runtime_files"].items():
        if sha256_file(EXECUTABLE.parent / n) != h:
            problems.append(f"runtime file {n} differs")
    dst = out / "frozen"
    dst.mkdir(parents=True, exist_ok=True)
    for n, h in fz["frozen_sha256"].items():
        shutil.copyfile(FROZEN / n, dst / n)
        if sha256_file(dst / n) != h:
            problems.append(f"frozen {n} differs")
    if problems:
        return {"ok": False, "problems": problems}
    orig = m7_runtime.prepare_worker_runtime

    def prepare(runtime_dir, executable):
        manifest = orig(runtime_dir, executable)
        for n, h in fz["frozen_sha256"].items():
            shutil.copyfile(dst / n, Path(runtime_dir) / n)
            if sha256_file(Path(runtime_dir) / n) != h:
                raise RuntimeError(f"frozen {n} install mismatch")
        manifest["frozen_config"] = True
        return manifest

    m7_runtime.prepare_worker_runtime = prepare
    return {"ok": True, "executable_sha256": fz["exe_copy_sha256"]["BattleShip.exe"], "frozen_sha256": fz["frozen_sha256"],
            "runtime_files": fz["runtime_files"]}


def remove_retry(path: Path, runtime: bool) -> bool:
    from m7_runtime import remove_worker_runtime

    for _ in range(24):
        try:
            if not path.exists():
                return True
            remove_worker_runtime(path) if runtime else shutil.rmtree(path)
            return True
        except OSError:
            time.sleep(0.25)
    return not path.exists()


def replay(label: str, words: bytes, slot: int, index: int, run_dir: Path) -> Dict[str, Any]:
    import m7f_trace as tr

    acts = StopAfterFailure([(*mcell.TRIPLES[w], i) for i, w in enumerate(words)])
    work = run_dir / "work" / label
    errors = []
    trace = None
    for attempt in range(2):                     # one fresh-process retry after an exception (the replay is deterministic)
        w = work if attempt == 0 else work.with_name(label + "_retry")
        try:
            acts.last = None
            trace = tr.run_stepping_trace(label, EXECUTABLE, acts, w, extra_env=dict(mc.FLAGS_VERIFY), index=index,
                                          rank=slot, on_ready=acts.on_ready)
        except Exception as exc:  # noqa: BLE001 - recorded, never hidden
            errors.append(f"{type(exc).__name__}: {exc}"[:400])
        finally:
            remove_retry(w / "runtime", True)
            remove_retry(w / "episodes", False)
        if trace is not None:
            break
    if trace is not None:
        tdir = run_dir / "traces"
        tdir.mkdir(parents=True, exist_ok=True)
        with gzip.open(tdir / f"{label}.json.gz", "wt", encoding="utf-8") as f:
            json.dump(trace, f, separators=(",", ":"))
    return {"trace": trace, "errors": errors}


def evaluate(trace: Optional[Mapping[str, Any]], words: bytes, cand: Optional[Mapping[str, Any]],
             route: Mapping[str, Any]) -> Dict[str, Any]:
    import m8_rd_claims as mclaims

    if trace is None:
        return {"outcome": "error", "ticks": 0}
    steps = trace["steps"]
    n = len(steps)
    ticks_ok = all(int(s["consumed_tick"]) == i and int(s["observation"]["input_tick"]) == i + 1 for i, s in enumerate(steps))
    ch = chain_list(trace["initial"], steps)
    br = breaks_of(trace)
    facts = mclaims.clear_facts(trace, len(br))
    last = steps[-1] if steps else None
    fell = last is not None and mcell.is_native_failure(last["observation"], last["state"])
    outcome = ("clear" if facts["all"] else "fall" if fell else
               "words_exhausted" if n == len(words) else "ended_other")
    row = {"outcome": outcome, "ticks": n, "ticks_ok": ticks_ok and trace.get("consumed_tick_mismatch") is None,
           "action_digest_ok": trace["action_digest"] == mcell.words_digest(words[:n]),
           "completion_input_tick": facts["completion_input_tick"], "completion_time_passed": facts["completion_time_passed"],
           "final_chain": ch[-1].hex(), "targets": len(br), "breaks": br, "fall_tick": n if fell else None,
           "startup_s": trace.get("startup_s"), "stepping_s": trace.get("stepping_s")}
    if cand is None:
        return row
    L, g, jr = cand["rep_L"], cand["gain"], cand["route_tick"]
    rt = route["trace"]
    at = lambda t, k: t["initial"] if k == 0 else t["steps"][k - 1]       # noqa: E731 - the reply after input tick k
    row["prefix_end_equal"] = n >= L and not mcell.obs_diffs(mcell.obs_tuple(at(trace, L)["observation"]), cand["rep_end"])
    row["prefix_chain_equal"] = n >= L and ch[L].hex() == cand["rep_ch"]
    exact_div = bin_div = None
    for k in range(L, n + 1):                     # splice input tick k <-> route input tick k + g
        a, b = at(trace, k), at(rt, k + g)
        oa, ob = mcell.obs_tuple(a["observation"]), mcell.obs_tuple(b["observation"])
        if exact_div is None and mcell.obs_diffs(oa, ob, ignore=NO_CLOCK):
            exact_div = k
        ka = (int(oa[I["position_x"]] // mcell.CELL_SIZE), int(oa[I["position_y"]] // mcell.CELL_SIZE), oa[I["ground_air_state"]],
              a["spatial"]["target_live_mask"])
        kb = (int(ob[I["position_x"]] // mcell.CELL_SIZE), int(ob[I["position_y"]] // mcell.CELL_SIZE), ob[I["ground_air_state"]],
              b["spatial"]["target_live_mask"])
        if bin_div is None and k > L and ka != kb:
            bin_div = k
        if exact_div is not None and bin_div is not None:
            break
    after_route = [(t, i) for t, i in route["breaks"] if t > jr]
    after_splice = {i: t for t, i in br if t > L}
    missed = next(((i, t) for t, i in after_route if i not in after_splice), None)
    row.update({"exact_div_tick": exact_div, "bin_div_tick": bin_div,
                "bin_div_route_tick": bin_div + g if bin_div is not None else None,
                "route_breaks_after": len(after_route), "kept": sum(1 for _, i in after_route if i in after_splice),
                "kept_on_time": sum(1 for t, i in after_route if after_splice.get(i) == t - g),
                "first_missed": {"target": missed[0], "route_tick": missed[1]} if missed else None,
                "fall_route_tick": row["fall_tick"] + g if row["fall_tick"] is not None else None})
    return row


def cmd_run(out: Path, workers: int, max_ticks: int, max_wall_s: float) -> int:
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, list_processes_named, wait_until_no_process
    import m8_rd_session as ses

    t0 = time.monotonic()
    run_dir = out / "run"
    if run_dir.exists():
        raise SystemExit(f"refused: {run_dir} exists (no overwrite)")
    P = build_plan()
    saved = out / "plan.json"
    if saved.exists() and json.loads(saved.read_text(encoding="utf-8"))["candidate_set_digest"] != P["plan"]["candidate_set_digest"]:
        raise SystemExit("refused: the candidate set differs from the saved plan")
    pids = list_processes_named(BATTLESHIP_IMAGE)
    ready = ses.readiness()
    pre = {"utc": utc(), "battleship_pids": pids, "readiness": ready, "workers": workers, "max_ticks": max_ticks,
           "max_wall_s": max_wall_s, "candidate_set_digest": P["plan"]["candidate_set_digest"]}
    if pids is None or pids or not ready["ok"]:            # refused: recorded beside run/, which is not created
        write_json(out / f"preflight_refused_{pre['utc'].replace('-', '').replace(':', '')}.json", pre)
        print(json.dumps({"refused": True, "battleship_pids": pids, "readiness_problems": ready["problems"]}))
        return 2
    run_dir.mkdir(parents=True)
    pre["pins"] = install_frozen(out)
    write_json(run_dir / "preflight.json", pre)
    if not pre["pins"]["ok"]:
        print(json.dumps({"refused": True, "pins": pre["pins"]}))
        return 2
    install_kill_on_close_job()
    route, cands = P["route"], P["candidates"]
    res_f = open(run_dir / "results.jsonl", "w", encoding="utf-8", newline="\n")
    lock = threading.Lock()
    used = 0

    def emit(row: Dict[str, Any]) -> None:
        with lock:
            res_f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
            res_f.flush()

    # the control: the unspliced route, alone, must reproduce its registered clear exactly
    rw = route["words"]
    rc = replay("control_r1", rw, 0, 0, run_dir)
    ctl = evaluate(rc["trace"], rw, None, route)
    used += ctl["ticks"]
    reg = route["trace"]["result"]
    ctl["exact"] = (ctl["outcome"] == "clear" and ctl["final_chain"] == route["chain"][-1].hex() and ctl["action_digest_ok"]
                    and ctl["completion_input_tick"] == reg["completion_input_tick"]
                    and ctl["completion_time_passed"] == reg["completion_time_passed"] and ctl["breaks"] == route["breaks"])
    emit({"label": "control_r1", "kind": "control", "errors": rc["errors"], **ctl})
    print(json.dumps({"control": {k: ctl[k] for k in ("outcome", "exact", "completion_input_tick", "completion_time_passed", "ticks")}}))
    if not ctl["exact"]:
        res_f.close()
        print("stopped: the control replay does not reproduce the registered clear")
        return 3

    pending = deque(("r1", c) for c in cands)
    first_rows: Dict[int, Dict[str, Any]] = {}
    second_rows: Dict[int, Dict[str, Any]] = {}
    skipped: List[Dict[str, Any]] = []
    free = list(range(workers))
    reserved = 0
    running: Dict[cf.Future, Tuple[str, Mapping[str, Any], int, int]] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        while pending or running:
            while pending and free:
                kind, c = pending[0]
                nw = c["words"]
                if used + reserved + nw > max_ticks or time.monotonic() - t0 > max_wall_s - 60:
                    pending.popleft()
                    skipped.append({"n": c["n"], "cid": c["cid"], "replay": kind, "reason": "budget"})
                    continue
                pending.popleft()
                slot = free.pop()
                reserved += nw
                label = f"c{c['n']:03d}_cid{c['cid']}_{kind}"
                fut = pool.submit(replay, label, bytes.fromhex(c["words_hex"]), slot, 1 + c["n"] + (1000 if kind == "r2" else 0),
                                  run_dir)
                running[fut] = (kind, c, slot, nw)
            if not running:
                break
            done, _ = cf.wait(list(running), return_when=cf.FIRST_COMPLETED)
            for fut in done:
                kind, c, slot, nw = running.pop(fut)
                free.append(slot)
                reserved -= nw
                rep = fut.result()
                try:
                    ev = evaluate(rep["trace"], bytes.fromhex(c["words_hex"]), c, route)
                except Exception as exc:  # noqa: BLE001 - recorded, never hidden
                    ev = {"outcome": "eval_error", "ticks": len((rep["trace"] or {}).get("steps") or []),
                          "eval_error": f"{type(exc).__name__}: {exc}"[:400]}
                used += ev["ticks"]
                row = {"label": f"c{c['n']:03d}_cid{c['cid']}_{kind}", "kind": kind, "n": c["n"], "cid": c["cid"],
                       "level": c["level"], "route_tick": c["route_tick"], "gain": c["gain"], "errors": rep["errors"], **ev}
                emit(row)
                if kind == "r1":
                    first_rows[c["n"]] = row
                    if ev["outcome"] == "clear":
                        pending.appendleft(("r2", c))
                else:
                    second_rows[c["n"]] = row
                print(f"{row['label']} {ev['outcome']} t={ev['ticks']} targets={ev.get('targets')} "
                      f"clock={ev.get('completion_input_tick')} used={used} wall={time.monotonic() - t0:.0f}s", flush=True)
    res_f.close()
    left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
    verified = []
    for n, r1 in sorted(first_rows.items()):
        r2 = second_rows.get(n)
        if r1["outcome"] == "clear":
            same = r2 is not None and all(r1[k] == r2[k] for k in ("outcome", "final_chain", "completion_input_tick",
                                                                      "completion_time_passed", "breaks", "action_digest_ok"))
            verified.append({"n": n, "cid": r1["cid"], "gain": r1["gain"], "clock": r1["completion_input_tick"],
                             "time_passed": r1["completion_time_passed"], "chain_r1": r1["final_chain"],
                             "chain_r2": r2["final_chain"] if r2 else None, "identical": same,
                             "faster_than_route": r1["completion_input_tick"] < route["trace"]["result"]["completion_input_tick"]})
    summary = {"utc": utc(), "wall_s": round(time.monotonic() - t0, 1), "ticks_used": used,
               "processes": 1 + len(first_rows) + len(second_rows), "candidates": len(cands), "replayed": len(first_rows),
               "skipped": skipped, "outcomes": dict(Counter(r["outcome"] for r in first_rows.values())),
               "errors": sum(1 for r in list(first_rows.values()) + list(second_rows.values()) if r["errors"]),
               "clears": verified, "leftover_battleship_pids": left}
    write_json(run_dir / "summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("wall_s", "ticks_used", "processes", "replayed", "outcomes", "errors",
                                              "leftover_battleship_pids")}))
    print("clears", json.dumps(verified))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("plan", "run"))
    ap.add_argument("--out", type=Path, default=LAB_ROOT / f"splice_probe_{dt.date.today().isoformat()}")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--max-ticks", type=int, default=1_000_000)
    ap.add_argument("--max-wall-s", type=float, default=3600.0)
    a = ap.parse_args(argv)
    out = check_out(a.out)
    if a.workers < 1 or a.workers > 5:
        raise SystemExit("refused: at most 5 game processes at once")
    if a.command == "plan":
        return cmd_plan(out)
    return cmd_run(out, a.workers, a.max_ticks, a.max_wall_s)


if __name__ == "__main__":
    sys.exit(main())
