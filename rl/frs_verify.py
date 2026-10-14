"""Fast-route lab (frs): exact replay from tick 0 in a fresh process with the verify flags, and the verdicts built on it.

    replay      rl/m7f_trace.run_stepping_trace (unchanged) in a fresh BattleShip process, flags m8_rd_session.FLAGS_VERIFY (review S8), the lab's
                pinned executable copy whose directory holds the frozen BattleShip.cfg.json / imgui.ini (so the private runtime gets them without
                any patching); submission stops after a native-failure reply (the steps after a fall hang natively)
    evaluate    the four clear facts (rl/m8_rd_claims.clear_facts), every consumed tick, the native action digest of the words, both completion
                clocks, the m8_rd chain digest over every record, the break table (rl/m7n_crossing.analyse_trace)
    verdict     VERIFIED only if replay 1 clears and equals the claim (words digest, clocks, in-run chain) AND replay 2, in another fresh process,
                is identical to replay 1 (chain, clocks, breaks, digest); a replay that runs but disagrees is NONDETERMINISTIC (the run is
                LAB_INVALID); a replay that cannot run twice is ERROR (reported, never a clear)
    tick-0 pin  a fresh explore-flag process's tick-0 record equals the archive's pinned one
    reference   the imported best verified clear replays exactly (clocks, digest, final chain, breaks of its stored trace)

Nothing here reads native RNG. Design: logs/frs_prep/phase1_plan.md sections 5 and 8.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
from collections.abc import Sequence as SequenceABC
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_session as ses  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

FLAGS_EXPLORE: Dict[str, str] = dict(ses.FLAGS_EXPLORE)
FLAGS_VERIFY: Dict[str, str] = dict(ses.FLAGS_VERIFY)
VERIFIED, NOT_VERIFIED, NONDETERMINISTIC, ERROR = "VERIFIED", "NOT_VERIFIED", "NONDETERMINISTIC", "ERROR"
SAME_KEYS = ("outcome", "final_chain", "completion_input_tick", "completion_time_passed", "breaks", "action_digest", "ticks")
ReplayFn = Callable[[bytes, str, int], Optional[Dict[str, Any]]]
Analyse = Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], Mapping[str, Any]]


# -- replay ------------------------------------------------------------------------------------------------------------------------------------


class StopAfterFailure(SequenceABC):
    """The action list handed to run_stepping_trace: iteration ends after a step reply that is a native failure (a fall)."""

    def __init__(self, actions: List[Tuple[int, int, int, int]]):
        self.actions = actions
        self.last: Optional[Mapping[str, Any]] = None

    def __len__(self) -> int:
        return len(self.actions)

    def __getitem__(self, i: Any) -> Any:
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


def frozen_exe_problems(exe_dir: Path, frozen: Mapping[str, Any]) -> List[str]:
    """The lab executable directory must hold exactly the pinned files: the executable copy, its runtime files and the frozen config."""
    out = []
    for n, h in dict(frozen["exe_copy_sha256"]).items():
        p = Path(exe_dir) / n
        if not p.is_file() or mw.sha256_file(p) != h:
            out.append(f"{n} differs from frozen_runtime.json")
    for n, h in dict(frozen["frozen_sha256"]).items():
        p = Path(exe_dir) / n
        if not p.is_file() or mw.sha256_file(p) != h:
            out.append(f"frozen {n} differs from frozen_runtime.json")
    return out


def make_real_replay(executable: Path, work_root: Path, flags: Mapping[str, str], frozen: Mapping[str, Any]) -> ReplayFn:
    """A fresh-process replay with `flags`; the pinned files beside the executable are re-hashed before every replay (pin drift = error)."""
    import m7f_trace as tr

    exe = Path(executable)

    def replay(words: bytes, label: str, slot: int) -> Optional[Dict[str, Any]]:
        bad = frozen_exe_problems(exe.parent, frozen)
        if bad:
            raise mw.MismatchError("pin_drift", {"problems": bad})
        acts = StopAfterFailure([(*mcell.TRIPLES[w], i) for i, w in enumerate(bytes(words))])
        work = Path(work_root) / f"s{int(slot)}_{label}"
        try:
            return tr.run_stepping_trace(label, exe, acts, work, extra_env=dict(flags), index=9000 + int(slot), rank=8 + int(slot),
                                         on_ready=acts.on_ready)
        finally:
            mw.remove_tree_retry(work / "runtime", runtime=True)
            mw.remove_tree_retry(work / "episodes")
            try:
                work.rmdir()
            except OSError:
                pass

    return replay


def real_analyse(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    import m7n_crossing as xc

    return xc.analyse_trace(initial, steps)


def replay_with_retry(replay: ReplayFn, words: bytes, label: str, slot: int) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """One fresh-process retry after an exception (the replay is deterministic; a retry only covers a process that failed to run)."""
    errors: List[str] = []
    for attempt in range(2):
        try:
            tr = replay(words, label if attempt == 0 else label + "_retry", slot)
            if tr is not None:
                return tr, errors
        except mw.MismatchError as exc:
            errors.append(f"MismatchError {exc.kind}: {json.dumps(exc.detail, default=str)[:300]}")
            return None, errors
        except Exception as exc:  # noqa: BLE001 - recorded, never hidden
            errors.append(f"{type(exc).__name__}: {exc}"[:400])
    return None, errors


# -- evaluation --------------------------------------------------------------------------------------------------------------------------------


def chain_of(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> bytes:
    ch = mcell.chain_start(mcell.tick0_record(initial))
    for s in steps:
        ch = mcell.chain_next(ch, mcell.record_digest(mcell.record_of(s)))
    return ch


def breaks_of(trace: Mapping[str, Any], analyse: Analyse) -> List[List[int]]:
    """[[input tick, target id]] in tick order, from the read-only target diagnostic."""
    an = analyse(trace["initial"], trace["steps"])
    return [list(x) for x in sorted((int(t) + 1, int(i)) for i, t in an["breaks"])]


def evaluate(trace: Optional[Mapping[str, Any]], words: bytes, analyse: Analyse) -> Dict[str, Any]:
    if trace is None:
        return {"outcome": "error", "ticks": 0}
    steps = trace.get("steps") or []
    n = len(steps)
    ticks_ok = all(int(s["consumed_tick"]) == i and int(s["observation"]["input_tick"]) == i + 1 for i, s in enumerate(steps)) \
        and trace.get("consumed_tick_mismatch") is None
    br = breaks_of(trace, analyse)
    facts = mclaims.clear_facts(trace, len(br))
    last = steps[-1] if steps else None
    fell = last is not None and mcell.is_native_failure(last["observation"], last["state"])
    outcome = "clear" if facts["all"] else "fall" if fell else "words_exhausted" if n == len(words) else "ended_other"
    return {"outcome": outcome, "ticks": n, "ticks_ok": bool(ticks_ok), "action_digest": trace.get("action_digest"),
            "action_digest_ok": trace.get("action_digest") == mcell.words_digest(bytes(words[:n])), "facts_all": bool(facts["all"]),
            "completion_input_tick": facts["completion_input_tick"], "completion_time_passed": facts["completion_time_passed"],
            "final_chain": chain_of(trace["initial"], steps).hex(), "breaks": br, "targets": len(br),
            "startup_s": trace.get("startup_s"), "stepping_s": trace.get("stepping_s")}


def verdict(r1: Optional[Mapping[str, Any]], r2: Optional[Mapping[str, Any]], claim: Mapping[str, Any]) -> Dict[str, Any]:
    """claim: words_digest (required), completion_input_tick / completion_time_passed / chain (hex) when the in-run job recorded them."""
    reasons: List[str] = []
    if r1 is None or r1.get("outcome") == "error" or r2 is None or r2.get("outcome") == "error":
        return {"verdict": ERROR, "reasons": ["a replay could not run"]}
    if r1["outcome"] != "clear" or not r1["facts_all"]:
        reasons.append(f"replay 1 does not clear ({r1['outcome']})")
    if not r1["ticks_ok"]:
        reasons.append("replay 1: a consumed tick differs")
    if r1["action_digest"] != claim["words_digest"] or not r1["action_digest_ok"]:
        reasons.append("replay 1: the native action digest differs from the claimed words")
    for k in ("completion_input_tick", "completion_time_passed"):
        if claim.get(k) is not None and r1.get(k) != claim[k]:
            reasons.append(f"replay 1: {k} {r1.get(k)} differs from the claim {claim[k]}")
    if claim.get("chain") is not None and r1["final_chain"] != claim["chain"]:
        reasons.append("replay 1: the final chain digest differs from the in-run chain")
    diff = [k for k in SAME_KEYS if r1.get(k) != r2.get(k)]
    if diff:
        reasons.append(f"replay 2 differs from replay 1 in {diff}")
    if not reasons:
        return {"verdict": VERIFIED, "reasons": [], "completion_input_tick": r1["completion_input_tick"],
                "completion_time_passed": r1["completion_time_passed"], "final_chain": r1["final_chain"]}
    return {"verdict": NONDETERMINISTIC, "reasons": reasons}


# -- the tick-0 pin and the reference clear ----------------------------------------------------------------------------------------------------------


def tick0_check(trace: Optional[Mapping[str, Any]], pin: Mapping[str, Any]) -> Dict[str, Any]:
    """A zero-word trace's observe reply against the pinned tick-0 record (every field but host_frame, record digest, chain start)."""
    if trace is None:
        return {"ok": False, "why": "the process did not run"}
    init = trace["initial"]
    rec = mcell.tick0_record(init)
    obs = mcell.obs_tuple(init["observation"])
    diffs = mcell.obs_diffs(obs, tuple(pin["obs"]))
    digest = mcell.record_digest(rec).hex()
    chain = mcell.chain_start(rec).hex()
    ok = not diffs and digest == pin["digest"] and chain == pin["chain"] and rec["l"] == pin.get("lines", rec["l"])
    return {"ok": bool(ok), "field_diffs": {k: list(v) for k, v in diffs.items()}, "digest_equal": digest == pin["digest"],
            "chain_equal": chain == pin["chain"], "startup_s": trace.get("startup_s")}


def load_reference(ref_dir: Path, analyse: Analyse) -> Dict[str, Any]:
    """The imported best verified clear: its words (canonical Track 1 triples), and what an exact replay must reproduce, from its stored trace."""
    meta = json.loads((Path(ref_dir) / "metadata.json").read_text(encoding="utf-8"))
    idx = {t: w for w, t in enumerate(mcell.TRIPLES)}
    words = bytearray()
    with open(Path(ref_dir) / "actions.jsonl", encoding="utf-8") as f:
        for i, ln in enumerate(f):
            a = json.loads(ln)
            if int(a["consumed_tick"]) != i:
                raise ValueError(f"reference actions: consumed_tick {a['consumed_tick']} at row {i}")
            words.append(idx[(int(a["buttons"]), int(a["stick_x"]), int(a["stick_y"]))])
    with gzip.open(Path(ref_dir) / "trace.json.gz", "rt", encoding="utf-8") as f:
        trace = json.load(f)
    words_b = bytes(words)
    problems = []
    if len(words_b) != int(meta["words"]) or mcell.words_digest(words_b) != meta["native_action_digest"]:
        problems.append("the reference words do not reproduce their recorded digest")
    if trace.get("action_digest") != meta["native_action_digest"] or len(trace["steps"]) != len(words_b):
        problems.append("the stored reference trace does not match its words")
    if dict(trace.get("extra_env") or {}) != FLAGS_VERIFY:
        problems.append("the stored reference trace was not made with the verify flags")
    exp = evaluate(trace, words_b, analyse)
    if exp["outcome"] != "clear":
        problems.append(f"the stored reference trace does not clear ({exp['outcome']})")
    return {"meta": meta, "words": words_b, "expected": exp, "problems": problems}


def reference_check(row: Mapping[str, Any], ref: Mapping[str, Any]) -> Dict[str, Any]:
    exp = ref["expected"]
    diff = [k for k in ("outcome", "completion_input_tick", "completion_time_passed", "action_digest", "final_chain", "breaks", "ticks")
            if row.get(k) != exp.get(k)]
    return {"ok": not diff and row.get("ticks_ok") is True, "differs": diff,
            "completion_input_tick": row.get("completion_input_tick"), "completion_time_passed": row.get("completion_time_passed")}


def save_trace(path: Path, trace: Optional[Mapping[str, Any]]) -> None:
    if trace is None:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(trace, f, separators=(",", ":"), default=str)


def verify_twice(replay: ReplayFn, analyse: Analyse, words: bytes, claim: Mapping[str, Any], label: str, slot: int,
                 trace_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Replay 1 and replay 2, each in its own fresh process, then the verdict."""
    t0 = time.perf_counter()
    tr1, e1 = replay_with_retry(replay, words, f"{label}_r1", slot)
    r1 = evaluate(tr1, words, analyse)
    tr2, e2 = replay_with_retry(replay, words, f"{label}_r2", slot)
    r2 = evaluate(tr2, words, analyse)
    if trace_dir is not None:
        save_trace(Path(trace_dir) / f"{label}_r1.json.gz", tr1)
        save_trace(Path(trace_dir) / f"{label}_r2.json.gz", tr2)
    v = verdict(r1, r2, claim)
    return {"label": label, "verdict": v["verdict"], "reasons": v["reasons"], "r1": r1, "r2": r2, "errors": e1 + e2,
            "completion_input_tick": r1.get("completion_input_tick"), "completion_time_passed": r1.get("completion_time_passed"),
            "words": len(words), "wall_s": round(time.perf_counter() - t0, 2)}
