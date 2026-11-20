#!/usr/bin/env python3
"""Claim verification (lab, after a run's close): two fresh-process replays of a closed lab run's NOT_REPLAYED clear claims.

A lab night (Option D, the crossing searches) replays a claimed clear at its close only when it is faster than the best verified clear at
the decision. Every other claim is kept in run/claims_not_replayed.jsonl with its whole tick-0 word sequence and nothing else: no trace,
no verification row. This tool verifies such claims afterwards, one at a time, by the night's own rule (owner, 2026-11-20).

    source      a closed lab run folder <lab>/<run>/ (run/summary.json written at the close) and its run/claims_not_replayed.jsonl (kind
                claim, verdict NOT_REPLAYED: words_hex, words_digest, the claimed clocks, chain_claimed, dispatch n, cell cid, k). Read
                only. Every row must parse: its words decode in the Track 1 alphabet (rl/m8_rd_cells.TRIPLES), their count is `words`,
                their native action digest is `words_digest`; one bad row refuses the run.
    replays     rl/frs_verify.verify_twice: replay 1 and replay 2, each in its own fresh BattleShip process from tick 0, with the source
                run's verify flags (run/config.json flags_verify, which must equal rl/frs_verify.FLAGS_VERIFY) and the lab's frozen
                executable (<lab>/import/exe, the import the source ran with; every pinned file is re-hashed before every replay).
    verdict     rl/frs_verify.verdict, the night's rule: VERIFIED only when replay 1 clears at the claimed completion input tick and
                time_passed, under the tick contract, with the claimed action digest and the in-run final chain, and replay 2 equals
                replay 1 (outcome, chain, clocks, breaks, digest, ticks). NONDETERMINISTIC (any mismatch) is an INTEGRITY FINDING, and
                so is a VERIFIED verdict whose own checks disagree; ERROR means a replay could not run. Each row also states every check
                on its own (`checks`: clear, clocks, chain and digest of each replay against the claim, replay 2 against replay 1).
    output      a NEW lab folder (--out), never the source: <out>/run/verifications.jsonl (one crossing-search row per claim,
                tools/frs/crossing_search.clear_row, plus phase post_close, tool, session, source, checks, integrity_finding),
                <out>/run/traces/clear_n<n>_c<cid>_k<k>_r{1,2}.json.gz (every reply of each replay) and <out>/sessions.jsonl (an open
                and a close row per invocation: the selection, the pins, the flags, git, the code digests, readiness, the verdicts). The
                replay browser lists the VERIFIED rows as LAB (unregistered) clears (replay/replay_lab.py). Several invocations may add
                to one --out, from the same source only; a claim with a row in --out is never replayed again.

Refusals (exit 2, before anything is written or launched; the checks are repeated under the lock): lab.lock exists in the lab root
(whatever it holds, stale or not: stricter than the lab's take-over of a stale lock); a BattleShip process is running (or the process
list cannot be read); the lab executable is not 30a3913b or a pinned file of <lab>/import/exe differs from import/frozen_runtime.json;
the source is not a closed lab run with a claims file, ran with another import, or its verify flags differ; a claims row does not
parse; --out is the source, inside it, contains it, is under the lab's import folder, or exists holding anything but this tool's files
or rows of another source; an asked claim is not in the source or already has a row in --out. While it runs the tool holds lab.lock
(one lab workload at a time) and the lab guard (rl/frs_guard: writes only inside the lab root).

    python -B tools/frs/verify_claim.py --source DIR --out DIR (--claim N:CID:K [--claim ...] | --all) [--dry-run] [--max-wall-min M]

--dry-run: zero native ticks, nothing written, no lock taken: what a run would replay and every refusal it would meet. --all: every
claim of the source without a row in --out, fastest claimed clear first. Exit 0 when every replayed claim is VERIFIED (or nothing was
left to replay), 3 on an integrity finding, 4 when a replay could not run or the wall cap stopped the session, 2 on a refusal.
Nothing here reads, logs, controls or compares native RNG state. Imported by no lab run (no code digest covers it). Zero-tick tests:
tools/frs/verify_claim_tests.py. Run with python -B.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "rl"))
sys.path.insert(0, str(HERE))

import crossing_search as cs  # noqa: E402  the crossing-search verification row (clear_row)
import frs_guard as g  # noqa: E402
import frs_verify as fv  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402

TOOL_CONTRACT = "frs_claim_verify_v1"
PHASE = "post_close"
EXPECT_EXE = "30a3913b"                 # owner: the frozen lab executable
CLAIMS = "claims_not_replayed.jsonl"
VERIFICATIONS = "verifications.jsonl"
SESSIONS = "sessions.jsonl"
LOCK_NAME = "lab.lock"
NOT_REPLAYED = "NOT_REPLAYED"           # the claims file's verdict (tools/frs/crossing_search_run2.record_not_replayed)
OUT_TOP = {"run": True, SESSIONS: False}                         # name -> is a folder
OUT_RUN = {VERIFICATIONS: False, "traces": True, "vw": True}
TRACE_RE = re.compile(r"^clear_n\d+_c\d+_k\d+_r[12]\.json\.gz$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SPEC_RE = re.compile(r"^(\d+):(\d+):(\d+)$")
MAX_WALL_MIN = 240.0
EXIT = {"COMPLETED": 0, "NOTHING_TO_DO": 0, "REFUSED": 2, "INTEGRITY_FINDING": 3, "INCOMPLETE": 4, "PARTIAL": 4}
INT_FIELDS = ("n", "cid", "k", "level", "start_tick", "lead", "claimed_completion_input_tick", "claimed_completion_time_passed", "words",
              "reference_completion_input_tick")

Key = Tuple[int, int, int]


class Refused(Exception):
    """A refusal: nothing was written or launched."""


# -- the claims ----------------------------------------------------------------------------------------------------------------------------


def parse_spec(spec: str) -> Key:
    """N:CID:K (dispatch, cell, iteration) -> (n, cid, k)."""
    m = SPEC_RE.match(str(spec).strip())
    if not m:
        raise Refused(f"--claim {spec!r} is not N:CID:K (three non-negative integers)")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def label_of(key: Key) -> str:
    return f"clear_n{key[0]}_c{key[1]}_k{key[2]}"


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def parse_claim_row(v: Any, line: int) -> Dict[str, Any]:
    """One claims_not_replayed.jsonl row -> a claim with its decoded words; ValueError with the reason when it does not parse."""
    if not isinstance(v, dict):
        raise ValueError("not an object")
    if v.get("kind") != "claim" or v.get("verdict") != NOT_REPLAYED:
        raise ValueError(f"kind {v.get('kind')!r} / verdict {v.get('verdict')!r} (expected claim / NOT_REPLAYED)")
    bad = [f for f in INT_FIELDS if not _is_int(v.get(f))]
    if bad:
        raise ValueError(f"missing or non-integer {bad}")
    if min(v["n"], v["cid"], v["k"]) < 0 or v["claimed_completion_input_tick"] < 1 or v["words"] < 1:
        raise ValueError("n / cid / k negative, or a claimed tick or word count below 1")
    if not isinstance(v.get("words_hex"), str):
        raise ValueError("no words_hex")
    try:
        words = bytes.fromhex(v["words_hex"])
    except ValueError as exc:
        raise ValueError(f"words_hex is not hexadecimal: {exc}") from None
    out_of = sorted({w for w in words if w >= len(mcell.TRIPLES)})
    if out_of:
        raise ValueError(f"words {out_of[:4]} outside the {len(mcell.TRIPLES)}-word Track 1 alphabet ({mcell.TRACK1_CONTRACT})")
    if len(words) != v["words"]:
        raise ValueError(f"{len(words)} decoded words, the row says {v['words']}")
    for f in ("words_digest", "chain_claimed"):
        if not isinstance(v.get(f), str) or not HEX64.match(v[f]):
            raise ValueError(f"{f} is not a sha256 hex digest")
    digest = mcell.words_digest(words)
    if digest != v["words_digest"]:
        raise ValueError(f"decoded words digest {digest[:16]} != words_digest {v['words_digest'][:16]}")
    c = {f: v[f] for f in INT_FIELDS}
    c.update({"key": (v["n"], v["cid"], v["k"]), "words_bytes": words, "words_digest": v["words_digest"], "chain_claimed": v["chain_claimed"],
              "line": line, "claim_utc": v.get("utc"), "best_at_decision": v.get("best_at_decision"), "why": v.get("why")})
    return c


def read_claims(path: Path) -> List[Dict[str, Any]]:
    """Every row of the claims file, parsed; Refused when any row does not parse or a (n, cid, k) repeats."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise Refused(f"{path}: {exc}") from None
    out: List[Dict[str, Any]] = []
    bad: List[str] = []
    seen: Dict[Key, int] = {}
    for line, s in enumerate(text.splitlines(), 1):
        if not s.strip():
            continue
        try:
            c = parse_claim_row(json.loads(s), line)
        except ValueError as exc:
            bad.append(f"line {line}: {exc}")
            continue
        if c["key"] in seen:
            bad.append(f"line {line}: claim {c['key']} repeats line {seen[c['key']]}")
            continue
        seen[c["key"]] = line
        out.append(c)
    if bad:
        raise Refused(f"{path}: {len(bad)} rows do not parse: {bad[:4]}")
    if not out:
        raise Refused(f"{path} holds no claim")
    return out


def select(claims: Sequence[Mapping[str, Any]], specs: Sequence[Key], all_claims: bool, done: Mapping[Key, str]) -> Tuple[List[Dict[str, Any]], List[Key]]:
    """(the claims to replay in order, the claims skipped because --out already has their row). --all: fastest claimed clear first."""
    by_key = {c["key"]: dict(c) for c in claims}
    if all_claims:
        order = sorted(by_key.values(), key=lambda c: (c["claimed_completion_input_tick"], c["n"], c["cid"], c["k"]))
        return [c for c in order if c["key"] not in done], [c["key"] for c in order if c["key"] in done]
    if len(set(specs)) != len(specs):
        raise Refused(f"a claim is asked twice: {list(specs)}")
    out = []
    for key in specs:
        if key not in by_key:
            raise Refused(f"claim {key} (n:cid:k) is not in the source's claims")
        if key in done:
            raise Refused(f"claim {key} already has a row in --out (verdict {done[key]}): a claim is never replayed again")
        out.append(by_key[key])
    return out, []


# -- the source, the output folder, the lock, the executable, the processes ----------------------------------------------------------------


def _forms_overlap(a: Path, b: Path) -> bool:
    return any(g.under(x, y) or g.under(y, x) for x in g.forms(a) for y in g.forms(b))


def source_flags(source: Path) -> Dict[str, str]:
    cfg = json.loads((Path(source) / "run" / "config.json").read_text(encoding="utf-8"))
    flags = cfg.get("flags_verify")
    return {str(k): str(v) for k, v in flags.items()} if isinstance(flags, dict) else {}


def source_problems(source: Path, lab: Path) -> List[str]:
    """The source is a closed lab run (run/summary.json) with a claims file that ran with this lab's import and the verify flags."""
    run = Path(source) / "run"
    probs = []
    if not (run / CLAIMS).is_file():
        probs.append(f"{run / CLAIMS} does not exist")
    if not (run / "summary.json").is_file():
        probs.append(f"{run / 'summary.json'} does not exist: the source run is not closed")
    try:
        cfg = json.loads((run / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return probs + [f"{run / 'config.json'} cannot be read: {exc}"]
    imp = cfg.get("import")
    if not isinstance(imp, str) or g.norm(Path(imp)) != g.norm(Path(lab) / "import"):
        probs.append(f"the source ran with import {imp!r}, not {Path(lab) / 'import'}")
    flags = cfg.get("flags_verify")
    if not isinstance(flags, dict) or {str(k): str(v) for k, v in flags.items()} != dict(fv.FLAGS_VERIFY):
        probs.append(f"the source's flags_verify {flags} differ from rl/frs_verify.FLAGS_VERIFY {fv.FLAGS_VERIFY}")
    return probs


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line, s in enumerate(f, 1):
            if s.strip():
                try:
                    rows.append(json.loads(s))
                except ValueError:
                    raise Refused(f"{path} line {line} does not parse") from None
    return rows


def out_problems(out: Path, lab: Path, source: Path) -> List[str]:
    """--out is inside the lab root, never under its import folder, never overlapping the source; an existing --out holds only this
    tool's files (sessions.jsonl, run/verifications.jsonl, run/traces/clear_*_r1|r2.json.gz, an empty run/vw) for this same source."""
    out, probs = Path(out), []
    try:
        g.validate_run_dir(out, lab)
    except g.LabRootError as exc:
        probs.append(str(exc))
    if _forms_overlap(out, Path(lab) / "import"):
        probs.append(f"{out} overlaps the lab's import folder")
    if _forms_overlap(out, source):
        probs.append(f"{out} and the source {source} overlap (the source is read only)")
    if probs or not out.exists():
        return probs
    if not out.is_dir():
        return [f"{out} exists and is not a folder"]
    for p in sorted(out.iterdir()):
        if p.name not in OUT_TOP or p.is_dir() != OUT_TOP[p.name]:
            probs.append(f"{p}: not a file of this tool")
    run = out / "run"
    if run.is_dir():
        for p in sorted(run.iterdir()):
            if p.name not in OUT_RUN or p.is_dir() != OUT_RUN[p.name]:
                probs.append(f"{p}: not a file of this tool")
        if (run / "traces").is_dir():
            probs += [f"{p}: not a trace of this tool" for p in sorted((run / "traces").iterdir()) if not (p.is_file() and TRACE_RE.match(p.name))]
        if (run / "vw").is_dir() and any((run / "vw").iterdir()):
            probs.append(f"{run / 'vw'} is not empty (replay work left by an interrupted session: look before deleting it)")
    sess = out / SESSIONS
    if (run / VERIFICATIONS).is_file() and not sess.is_file():
        probs.append(f"{run / VERIFICATIONS} exists without {SESSIONS}: not this tool's folder")
    src = g.norm(source)
    try:
        if sess.is_file():
            other = sorted({str(r.get("source")) for r in read_jsonl(sess) if g.norm(r.get("source")) != src})
            if other:
                probs.append(f"{sess} holds sessions of another source {other[:2]}")
        if (run / VERIFICATIONS).is_file():
            foreign = [r for r in read_jsonl(run / VERIFICATIONS) if r.get("phase") != PHASE or g.norm((r.get("source") or {}).get("run")) != src]
            if foreign:
                probs.append(f"{run / VERIFICATIONS} holds {len(foreign)} rows that are not this tool's for this source")
    except Refused as exc:
        probs.append(str(exc))
    return probs


def done_claims(out: Path) -> Dict[Key, str]:
    """{(n, cid, k): verdict} of the rows already in --out."""
    p = Path(out) / "run" / VERIFICATIONS
    return {(int(r["n"]), int(r["cid"]), int(r["k"])): str(r.get("verdict")) for r in read_jsonl(p)} if p.is_file() else {}


def lock_problems(lab: Path) -> List[str]:
    lock = Path(lab) / LOCK_NAME
    if not lock.exists():
        return []
    try:
        held = lock.read_text(encoding="utf-8").strip()[:300]
    except OSError as exc:
        held = f"unreadable: {exc}"
    return [f"{lock} exists ({held}): another lab workload holds it, or a stale lock waits for the owner"]


def exe_facts(lab: Path, expect: str = EXPECT_EXE) -> Tuple[Dict[str, Any], List[str]]:
    """The frozen executable pins: the recorded executable hash starts with `expect`, and every pinned file of <lab>/import/exe matches
    import/frozen_runtime.json (rl/frs_verify.frozen_exe_problems, the check every replay repeats)."""
    imp = Path(lab) / "import"
    try:
        frozen = json.loads((imp / "frozen_runtime.json").read_text(encoding="utf-8"))
        recorded = str(frozen["exe_copy_sha256"]["BattleShip.exe"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {}, [f"{imp / 'frozen_runtime.json'} cannot be read: {type(exc).__name__}: {exc}"]
    probs = [] if recorded.startswith(expect) else [f"the frozen executable is {recorded[:8]}, not {expect}"]
    try:
        probs += fv.frozen_exe_problems(imp / "exe", frozen)
    except (OSError, KeyError, TypeError) as exc:
        probs.append(f"the pinned files cannot be checked: {type(exc).__name__}: {exc}")
    return {"exe_sha256": recorded, "frozen": frozen, "exe": str(imp / "exe" / "BattleShip.exe")}, probs


def process_problems(pids: Optional[Sequence[int]]) -> List[str]:
    if pids is None:
        return ["the BattleShip process list cannot be read"]
    return [f"BattleShip processes are running: {sorted(pids)}"] if pids else []


# -- one claim ----------------------------------------------------------------------------------------------------------------------------


def claim_of(c: Mapping[str, Any]) -> Dict[str, Any]:
    """The claim frs_verify.verdict checks: the words digest, both claimed clocks and the in-run final chain."""
    return {"words_digest": c["words_digest"], "completion_input_tick": c["claimed_completion_input_tick"],
            "completion_time_passed": c["claimed_completion_time_passed"], "chain": c["chain_claimed"]}


def checks_of(c: Mapping[str, Any], out: Mapping[str, Any]) -> Dict[str, bool]:
    """Every check on its own: each replay against the claim, and replay 2 against replay 1."""
    claim = claim_of(c)
    res: Dict[str, bool] = {}
    for i in (1, 2):
        r = out.get(f"r{i}") or {}
        res[f"clear_r{i}"] = r.get("outcome") == "clear" and bool(r.get("facts_all"))
        res[f"tick_r{i}"] = r.get("completion_input_tick") == claim["completion_input_tick"]
        res[f"time_passed_r{i}"] = r.get("completion_time_passed") == claim["completion_time_passed"]
        res[f"chain_r{i}"] = r.get("final_chain") == claim["chain"]
        res[f"digest_r{i}"] = r.get("action_digest") == claim["words_digest"] and bool(r.get("action_digest_ok"))
        res[f"ticks_ok_r{i}"] = bool(r.get("ticks_ok"))
    r1, r2 = out.get("r1") or {}, out.get("r2") or {}
    res["r2_equals_r1"] = bool(r1) and all(r1.get(k) == r2.get(k) for k in fv.SAME_KEYS)
    return res


def integrity_finding(verdict: str, checks: Mapping[str, bool]) -> Optional[str]:
    """None, or why the row is an integrity finding: a mismatch (NONDETERMINISTIC), or a verdict its own checks disagree with."""
    if verdict == fv.NONDETERMINISTIC:
        return "a replay disagrees with the claim or with the other replay"
    if verdict == fv.VERIFIED and not all(checks.values()):
        return f"VERIFIED although checks fail: {[k for k, ok in checks.items() if not ok]}"
    return None


def verification_row(c: Mapping[str, Any], out: Mapping[str, Any], source: Path, session: str, utc: str) -> Dict[str, Any]:
    """The crossing-search row (crossing_search.clear_row) plus where the claim came from and every check."""
    cand = {"n": c["n"], "cid": c["cid"], "k": c["k"], "level": c["level"], "start_tick": c["start_tick"], "lead": c["lead"],
            "words": c["words_bytes"], "claim": claim_of(c)}
    row = cs.clear_row(cand, out, int(c["reference_completion_input_tick"]))
    checks = checks_of(c, out)
    why = integrity_finding(str(out["verdict"]), checks) if out["verdict"] != fv.ERROR else None
    row.update({"utc": utc, "phase": PHASE, "tool": TOOL_CONTRACT, "session": session, "checks": checks, "integrity_finding": why,
                "source": {"run": str(source), "claims": str(Path(source) / "run" / CLAIMS), "line": c["line"], "claim_utc": c["claim_utc"],
                           "best_at_decision": c["best_at_decision"], "why_not_replayed": c["why"]}})
    return row


def verdict_line(row: Mapping[str, Any]) -> str:
    ch, cl = row["checks"], row["claim"]
    tick = f"tick r1 {row['clocks_r1'][0]} r2 {row['clocks_r2'][0]} vs claim {cl['completion_input_tick']} ({'match' if ch['tick_r1'] and ch['tick_r2'] else 'MISMATCH'})"
    chain = f"chain r1 {(row['chain_r1'] or '-')[:12]} r2 {(row['chain_r2'] or '-')[:12]} vs claim {cl['chain'][:12]} ({'match' if ch['chain_r1'] and ch['chain_r2'] else 'MISMATCH'})"
    tail = f"; INTEGRITY FINDING: {row['integrity_finding']}" if row.get("integrity_finding") else ""
    tail += f"; reasons {row['reasons'][:3]}" if row.get("reasons") else ""
    return f"{label_of((row['n'], row['cid'], row['k']))}: {row['verdict']}; {tick}; {chain}; r2 == r1 {ch['r2_equals_r1']}{tail}"


# -- the session ----------------------------------------------------------------------------------------------------------------------------


def lf_sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def git_facts(repo: Path = REPO) -> Dict[str, Any]:
    def git(*a: str) -> Optional[str]:
        try:
            r = subprocess.run(["git", *a], capture_output=True, text=True, cwd=str(repo), timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    st = git("status", "--porcelain", "--untracked-files=no")
    return {"head": git("rev-parse", "HEAD"), "tracked_changes": None if st is None else [x for x in st.splitlines() if x.strip()][:10]}


DIGEST_SNIPPETS = {"lab": ("rl", "import frs_run as m; print(m.code_digest(m.code_manifest()))"),
                   "run3": ("tools/frs", "import run3_manifest as m; print(m.code_digest(m.run3_code_manifest()))"),
                   "D": ("tools/frs", "import order_search as m; print(m.code_digest(m.order_code_manifest()))")}


def code_digests(repo: Path = REPO) -> Dict[str, str]:
    """The lab, run 3 (frontier) and D code digests of this checkout, each in a fresh interpreter (report-only)."""
    out = {}
    for name, (cwd, code) in DIGEST_SNIPPETS.items():
        pre = f"import sys; sys.path.insert(0, {str(repo / 'rl')!r}); sys.path.insert(0, {str(repo / 'tools' / 'frs')!r}); "
        try:
            r = subprocess.run([sys.executable, "-B", "-c", pre + code], capture_output=True, text=True, cwd=str(repo / cwd), timeout=300)
            out[name] = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else f"error: {r.stderr.strip()[-200:]}"
        except (OSError, subprocess.SubprocessError) as exc:
            out[name] = f"error: {exc}"
    return out


class Deps:
    """What a session touches outside its folders; tests replace each (zero native ticks)."""

    def __init__(self, **kw: Any):
        self.pids: Callable[[], Optional[List[int]]] = kw.get("pids") or _real_pids
        self.make_replay: Callable[..., Any] = kw.get("make_replay") or (lambda exe, work, flags, frozen: fv.make_real_replay(exe, work, flags, frozen))
        self.analyse: Callable[..., Any] = kw.get("analyse") or fv.real_analyse
        self.verify: Callable[..., Dict[str, Any]] = kw.get("verify") or fv.verify_twice
        self.kill_job: Callable[[], Any] = kw.get("kill_job") or _real_kill_job
        self.wait_no_battleship: Callable[[float], List[int]] = kw.get("wait_no_battleship") or _real_wait
        self.digests: Callable[[], Dict[str, str]] = kw.get("digests") or code_digests
        self.git: Callable[[], Dict[str, Any]] = kw.get("git") or git_facts
        self.readiness: Callable[[Path], Any] = kw.get("readiness") or _real_readiness
        self.expect_exe: str = kw.get("expect_exe") or EXPECT_EXE
        self.now: Callable[[], float] = kw.get("now") or time.monotonic
        self.guard: Callable[[Path], None] = kw.get("guard") or _real_guard


def _real_guard(lab: Path) -> None:
    """The lab guard for the rest of the process (rl/frs_guard: every write outside the lab root is refused)."""
    if not g.LabGuard.installed:
        g.LabGuard.install(lab)


def _real_pids() -> Optional[List[int]]:
    import frs_machine as fm

    return fm.battleship_pids()


def _real_kill_job() -> Any:
    from m7_runtime import install_kill_on_close_job

    return install_kill_on_close_job()


def _real_wait(timeout: float) -> List[int]:
    from m7_runtime import BATTLESHIP_IMAGE, wait_until_no_process

    return wait_until_no_process(BATTLESHIP_IMAGE, timeout=timeout)


def _real_readiness(lab: Path) -> Any:
    import frs_machine as fm

    try:
        return fm.readiness(lab)
    except Exception as exc:  # noqa: BLE001 - report-only
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def prepare(lab: Path, source: Path, out: Path, specs: Sequence[Key], all_claims: bool, deps: Deps) -> Dict[str, Any]:
    """Every read and check of a session, zero native ticks, nothing written: the claims to replay and every refusal."""
    probs = lock_problems(lab)
    probs += source_problems(source, lab)
    probs += out_problems(out, lab, source)
    exe, eprobs = exe_facts(lab, deps.expect_exe)
    probs += eprobs
    probs += process_problems(deps.pids())
    claims, chosen, skipped = [], [], []
    if (Path(source) / "run" / CLAIMS).is_file():
        try:
            claims = read_claims(Path(source) / "run" / CLAIMS)
            chosen, skipped = select(claims, specs, all_claims, done_claims(out))
        except Refused as exc:
            probs.append(str(exc))
    return {"problems": probs, "claims": claims, "chosen": chosen, "skipped": skipped, "exe": exe}


def describe(P: Mapping[str, Any], source: Path, out: Path) -> List[str]:
    lines = [f"source {source}: {len(P['claims'])} claims parse (words decode to their words_digest)",
             f"output {out}: {len(P['skipped'])} claims already have a row there (skipped)",
             f"executable {str(P['exe'].get('exe_sha256', '?'))[:8]} ({P['exe'].get('exe', '?')})",
             f"to replay ({len(P['chosen'])}, two fresh processes each):"]
    lines += [f"  {label_of(c['key'])}: claimed {c['claimed_completion_input_tick']} / {c['claimed_completion_time_passed']}, words {c['words']}, "
              f"level {c['level']} start {c['start_tick']}, chain {c['chain_claimed'][:12]}" for c in P["chosen"]]
    return lines


def execute(lab: Path, source: Path, out: Path, specs: Sequence[Key], all_claims: bool, deps: Deps, *, max_wall_s: float, argv: Sequence[str]) -> int:
    """The native session: the checks, lab.lock, then each claim's two replays; rows and traces under --out only."""
    P = prepare(lab, source, out, specs, all_claims, deps)
    if P["problems"]:
        return refuse(P["problems"])
    lock = g.LabLock(lab, f"verify_claim {Path(out).name}")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        return refuse([str(exc)])
    if lock.stale is not None:
        lock.release()
        return refuse([f"a stale lab.lock appeared after the check and was taken over: {lock.stale} (look before running again)"])
    status, rows, t0, opened = "INTERRUPTED", [], deps.now(), False
    fs = g.LabFS(lab)
    session = f"{g.utc_compact()}_{os.getpid()}"
    try:
        P = prepare(lab, source, out, specs, all_claims, deps)          # again, under the lock (lab.lock itself is ours now)
        again = [p for p in P["problems"] if not p.startswith(str(Path(lab) / LOCK_NAME))]
        if again:
            status = "REFUSED"
            return refuse(again)
        for ln in describe(P, source, out):
            print(ln, flush=True)
        if not P["chosen"]:
            status = "NOTHING_TO_DO"
            print("nothing to replay", flush=True)
            return EXIT[status]
        deps.kill_job()
        exe = P["exe"]
        fs.mkdir(Path(out) / "run" / "traces")
        fs.append_jsonl(Path(out) / SESSIONS, {
            "event": "open", "session": session, "utc": g.utc(), "tool": TOOL_CONTRACT, "tool_sha256": lf_sha256(Path(__file__)), "argv": list(argv),
            "source": str(source), "out": str(out), "lab": str(lab), "chosen": [list(c["key"]) for c in P["chosen"]],
            "skipped_done": [list(k) for k in P["skipped"]], "flags_verify": source_flags(source), "exe_sha256": exe["exe_sha256"],
            "frozen_sha256": exe["frozen"].get("frozen_sha256"), "exe_copy_sha256": exe["frozen"].get("exe_copy_sha256"), "git": deps.git(),
            "code_digests": deps.digests(), "readiness": deps.readiness(lab), "max_wall_s": max_wall_s})
        opened = True
        replay = deps.make_replay(Path(exe["exe"]), Path(out) / "run" / "vw", dict(fv.FLAGS_VERIFY), exe["frozen"])
        status = "COMPLETED"
        for c in P["chosen"]:
            if deps.now() - t0 >= max_wall_s:
                status = "PARTIAL"
                print(f"wall cap {max_wall_s:.0f} s reached: {len(P['chosen']) - len(rows)} claims not replayed", flush=True)
                break
            label = label_of(c["key"])
            try:
                res = deps.verify(replay, deps.analyse, c["words_bytes"], claim_of(c), label, 0, trace_dir=Path(out) / "run" / "traces")
            except Exception as exc:  # noqa: BLE001 - a crashed verification is an ERROR row, never a clear
                res = {"label": label, "verdict": fv.ERROR, "reasons": [f"{type(exc).__name__}: {exc}"[:300]], "r1": {}, "r2": {}, "errors": [],
                       "words": len(c["words_bytes"]), "wall_s": None}
            row = verification_row(c, res, source, session, g.utc())
            fs.append_jsonl(Path(out) / "run" / VERIFICATIONS, row)
            rows.append(row)
            print(verdict_line(row) + f" ({res.get('wall_s')} s)", flush=True)
        if any(r.get("integrity_finding") for r in rows):
            status = "INTEGRITY_FINDING"
        elif any(r["verdict"] == fv.ERROR for r in rows) and status == "COMPLETED":
            status = "INCOMPLETE"
        return EXIT[status]
    finally:
        try:
            if opened:
                left = deps.wait_no_battleship(30.0)
                fs.append_jsonl(Path(out) / SESSIONS, {
                    "event": "close", "session": session, "utc": g.utc(), "source": str(source), "status": status, "wall_s": round(deps.now() - t0, 1),
                    "battleship_left": left, "verdicts": {label_of((r["n"], r["cid"], r["k"])): r["verdict"] for r in rows},
                    "integrity_findings": [label_of((r["n"], r["cid"], r["k"])) for r in rows if r.get("integrity_finding")]})
                print(f"status {status}: {len(rows)} claims replayed; rows {Path(out) / 'run' / VERIFICATIONS}"
                      + (f"; BattleShip processes left after 30 s: {left}" if left else ""), flush=True)
        finally:
            lock.release()


def refuse(problems: Sequence[str]) -> int:
    for p in problems:
        print(f"refused: {p}", flush=True)
    return EXIT["REFUSED"]


def main(argv: Optional[Sequence[str]] = None, deps: Optional[Deps] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
    ap.add_argument("--source", required=True, help="the closed lab run folder whose run/claims_not_replayed.jsonl is read")
    ap.add_argument("--out", required=True, help="the new lab folder the rows and traces go to (never the source)")
    ap.add_argument("--claim", action="append", default=[], help="N:CID:K (dispatch, cell, k); repeatable")
    ap.add_argument("--all", action="store_true", help="every claim of the source without a row in --out, fastest first")
    ap.add_argument("--dry-run", action="store_true", help="zero native ticks, nothing written, no lock")
    ap.add_argument("--max-wall-min", type=float, default=60.0)
    a = ap.parse_args(argv)
    deps = deps or Deps()
    try:
        if bool(a.claim) == a.all:
            raise Refused("give --claim N:CID:K (one or more) or --all, not both")
        if not 0 < a.max_wall_min <= MAX_WALL_MIN:
            raise Refused(f"--max-wall-min is in (0, {MAX_WALL_MIN:g}]")
        specs = [parse_spec(s) for s in a.claim]
        lab = g.validate_lab_root(Path(a.lab_root))
        source = g.validate_run_dir(Path(a.source), lab)
        out = g.validate_run_dir(Path(a.out), lab)
    except (Refused, g.LabRootError) as exc:
        return refuse([str(exc)])
    if a.dry_run:
        P = prepare(lab, source, out, specs, a.all, deps)
        for ln in describe(P, source, out):
            print(ln)
        for p in P["problems"]:
            print(f"a run would be refused: {p}")
        print("dry run: zero native ticks, nothing written, no lock taken")
        return EXIT["REFUSED"] if P["problems"] else 0
    deps.guard(lab)
    return execute(lab, source, out, specs, a.all, deps, max_wall_s=60.0 * a.max_wall_min, argv=argv)


if __name__ == "__main__":
    sys.exit(main())
