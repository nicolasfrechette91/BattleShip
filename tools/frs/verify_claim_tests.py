#!/usr/bin/env python3
"""Tests of tools/frs/verify_claim.py: the claims parsing, the refusals, the output-folder logic and a whole session on a stub replay.
Zero native ticks: no BattleShip process is started (the replay, the process list, the job object and the code digests are stubs).

    python -B tools/frs/verify_claim_tests.py [test ...]
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "rl"))

import frs_verify as fv  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import verify_claim as vc  # noqa: E402
from infra_testlib import check, cleanup, run_suite, tmpdir  # noqa: E402

LAB = Path("C:/BattleShip_lab")
NIGHT5 = LAB / "order_2026-11-19_night5"
NIGHT5_OUT = LAB / "verify_2026-11-20_night5_claims"
EXE_FILES = ("BattleShip.exe", "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt", "config.yml")
FROZEN_FILES = ("BattleShip.cfg.json", "imgui.ini")


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def words_of(n: int, salt: int) -> bytes:
    return bytes((i * 7 + salt) % len(mcell.TRIPLES) for i in range(n))


def claim_row(n: int, cid: int, k: int, words: bytes, *, chain: str = "ab" * 32, **over: Any) -> Dict[str, Any]:
    row = {"mode": "lab", "kind": "claim", "verdict": "NOT_REPLAYED", "why": "slower than or equal to the best verified clear at decision",
           "n": n, "cid": cid, "k": k, "level": 9, "start_tick": len(words) - 60, "lead": -5, "claimed_completion_input_tick": len(words),
           "claimed_completion_time_passed": len(words) - 1, "words": len(words), "words_digest": mcell.words_digest(words),
           "chain_claimed": chain, "best_at_decision": 900, "reference_completion_input_tick": 900, "utc": "2026-11-20T05:00:00Z",
           "words_hex": words.hex()}
    row.update(over)
    return row


def write_jsonl(p: Path, rows: List[Any]) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows), encoding="utf-8", newline="\n")
    return p


def make_lab(root: Path, claims: List[Any]) -> Dict[str, Path]:
    """A lab root with a fake import (exe folder + frozen_runtime.json pinning it) and one closed D-like source run with its claims."""
    lab = root / "lab"
    exe = lab / "import" / "exe"
    exe.mkdir(parents=True)
    for i, n in enumerate(EXE_FILES + FROZEN_FILES):
        (exe / n).write_bytes(f"fake {n} {i}\n".encode())
    frozen = {"exe_copy_sha256": {n: sha(exe / n) for n in EXE_FILES}, "frozen_sha256": {n: sha(exe / n) for n in FROZEN_FILES},
              "runtime_files": {}}
    (lab / "import" / "frozen_runtime.json").write_text(json.dumps(frozen), encoding="utf-8")
    source = lab / "order_x"
    run = source / "run"
    write_jsonl(run / vc.CLAIMS, claims)
    (run / "summary.json").write_text("{}\n", encoding="utf-8")
    (run / "config.json").write_text(json.dumps({"import": str(lab / "import"), "flags_verify": dict(fv.FLAGS_VERIFY)}), encoding="utf-8")
    return {"lab": lab, "source": source, "exe": exe, "expect": frozen["exe_copy_sha256"]["BattleShip.exe"][:8]}


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def refusals(fn: Any) -> str:
    try:
        fn()
    except vc.Refused as exc:
        return str(exc)
    raise AssertionError("not refused")


# -- the claims ----------------------------------------------------------------------------------------------------------------------------


def unit_parse_specs_and_rows() -> Dict[str, Any]:
    check(vc.parse_spec("8175:74147:0") == (8175, 74147, 0) and vc.parse_spec(" 1:2:3 ") == (1, 2, 3), "N:CID:K parses")
    for bad in ("8175:74147", "a:b:c", "-1:2:3", "1:2:3:4", ""):
        check("N:CID:K" in refusals(lambda: vc.parse_spec(bad)), f"{bad!r} is refused")
    w = words_of(300, 1)
    c = vc.parse_claim_row(claim_row(7, 3, 1, w), 4)
    check(c["key"] == (7, 3, 1) and c["words_bytes"] == w and c["line"] == 4 and c["claimed_completion_input_tick"] == 300, f"a good row: {c['key']}")
    check(vc.claim_of(c) == {"words_digest": mcell.words_digest(w), "completion_input_tick": 300, "completion_time_passed": 299, "chain": "ab" * 32},
          "the claim frs_verify.verdict checks: digest, both clocks, chain")
    cases = {"kind": dict(kind="clear"), "verdict": dict(verdict="VERIFIED"), "non-integer": dict(n="7"), "bool": dict(k=True),
             "negative": dict(cid=-1), "tick": dict(claimed_completion_input_tick=0), "not hexadecimal": dict(words_hex="zz"),
             "alphabet": dict(words_hex=bytes([len(mcell.TRIPLES)]).hex() + w[1:].hex()), "decoded words": dict(words=299),
             "words_digest": dict(words_digest="00" * 32), "chain_claimed": dict(chain_claimed="xyz"), "no words_hex": dict(words_hex=None),
             "missing": dict(reference_completion_input_tick=None)}
    seen = {}
    for name, over in cases.items():
        try:
            vc.parse_claim_row(dict(claim_row(7, 3, 1, w), **over), 1)
            raise AssertionError(f"{name}: accepted")
        except ValueError as exc:
            seen[name] = str(exc)[:60]
    check(seen["alphabet"].startswith("words [72]") and "decoded words digest" in seen["words_digest"], f"reasons: {seen}")
    for bad in ([], "x", None):
        try:
            vc.parse_claim_row(bad, 1)
            raise AssertionError(f"{bad!r}: accepted")
        except ValueError as exc:
            check("not an object" in str(exc), f"{bad!r}: {exc}")
    return {"refused": len(seen)}


def unit_read_claims_file() -> Dict[str, Any]:
    d = tmpdir("vclaim_rows_")
    try:
        w1, w2 = words_of(200, 1), words_of(210, 2)
        good = write_jsonl(d / "a.jsonl", [claim_row(1, 10, 0, w1), "", claim_row(2, 20, 0, w2)])
        cl = vc.read_claims(good)
        check([c["key"] for c in cl] == [(1, 10, 0), (2, 20, 0)] and [c["line"] for c in cl] == [1, 3], "blank lines skipped, lines kept")
        dup = write_jsonl(d / "b.jsonl", [claim_row(1, 10, 0, w1), claim_row(1, 10, 0, w2)])
        check("repeats line 1" in refusals(lambda: vc.read_claims(dup)), "a repeated (n, cid, k) refuses the file")
        bad = write_jsonl(d / "c.jsonl", [claim_row(1, 10, 0, w1), "{not json", claim_row(3, 30, 0, w2, words_digest="11" * 32)])
        msg = refusals(lambda: vc.read_claims(bad))
        check("2 rows do not parse" in msg and "line 2" in msg and "line 3" in msg, f"one bad row refuses the whole file: {msg[:160]}")
        empty = write_jsonl(d / "d.jsonl", [""])
        check("holds no claim" in refusals(lambda: vc.read_claims(empty)), "an empty claims file is refused")
        check(refusals(lambda: vc.read_claims(d / "missing.jsonl")).startswith(str(d / "missing.jsonl")), "a missing file is refused")
        return {"claims": len(cl)}
    finally:
        cleanup(d)


def unit_select() -> Dict[str, Any]:
    cl = [vc.parse_claim_row(claim_row(n, n * 10, 0, words_of(t, n)), n) for n, t in ((1, 320), (2, 300), (3, 300), (4, 310))]
    chosen, skipped = vc.select(cl, [], True, {})
    check([c["key"][0] for c in chosen] == [2, 3, 4, 1] and skipped == [], "--all: fastest claimed clear first, then n")
    chosen, skipped = vc.select(cl, [], True, {(2, 20, 0): "VERIFIED", (1, 10, 0): "ERROR"})
    check([c["key"][0] for c in chosen] == [3, 4] and skipped == [(2, 20, 0), (1, 10, 0)], "--all skips every claim with a row, whatever its verdict")
    chosen, _ = vc.select(cl, [(4, 40, 0), (2, 20, 0)], False, {})
    check([c["key"][0] for c in chosen] == [4, 2], "--claim keeps the asked order")
    check("not in the source" in refusals(lambda: vc.select(cl, [(9, 90, 0)], False, {})), "an unknown claim is refused")
    check("never replayed again" in refusals(lambda: vc.select(cl, [(2, 20, 0)], False, {(2, 20, 0): "VERIFIED"})), "a claim with a row is refused")
    check("asked twice" in refusals(lambda: vc.select(cl, [(2, 20, 0), (2, 20, 0)], False, {})), "a claim asked twice is refused")
    return {"claims": len(cl)}


# -- the refusals --------------------------------------------------------------------------------------------------------------------------


def unit_lock_exe_processes() -> Dict[str, Any]:
    d = tmpdir("vclaim_pins_")
    try:
        L = make_lab(d, [claim_row(1, 10, 0, words_of(200, 1))])
        lab = L["lab"]
        check(vc.lock_problems(lab) == [], "no lock, no problem")
        (lab / "lab.lock").write_text(json.dumps({"pid": 999999991, "utc": "x", "what": "stale"}) + "\n", encoding="utf-8")
        p = vc.lock_problems(lab)
        check(len(p) == 1 and "lab.lock exists" in p[0] and "999999991" in p[0], f"any lab.lock refuses, a stale one too: {p}")
        (lab / "lab.lock").unlink()
        facts, probs = vc.exe_facts(lab, L["expect"])
        check(probs == [] and facts["exe_sha256"].startswith(L["expect"]), f"the pinned folder is accepted: {probs}")
        _f, probs = vc.exe_facts(lab)
        check(probs == [f"the frozen executable is {L['expect']}, not {vc.EXPECT_EXE}"], f"an executable other than 30a3913b is refused: {probs}")
        (L["exe"] / "BattleShip.o2r").write_bytes(b"tampered\n")
        (L["exe"] / "imgui.ini").unlink()
        _f, probs = vc.exe_facts(lab, L["expect"])
        check(sorted(probs) == ["BattleShip.o2r differs from frozen_runtime.json", "frozen imgui.ini differs from frozen_runtime.json"],
              f"a changed or missing pinned file is refused: {probs}")
        (lab / "import" / "frozen_runtime.json").write_text("{", encoding="utf-8")
        _f, probs = vc.exe_facts(lab, L["expect"])
        check(len(probs) == 1 and "cannot be read" in probs[0], f"an unreadable frozen_runtime.json is refused: {probs}")
        check(vc.process_problems([]) == [] and vc.process_problems(None) == ["the BattleShip process list cannot be read"]
              and vc.process_problems([42, 7]) == ["BattleShip processes are running: [7, 42]"], "running or unreadable processes refuse")
        return {"ok": True}
    finally:
        cleanup(d)


def unit_source_problems() -> Dict[str, Any]:
    d = tmpdir("vclaim_src_")
    try:
        L = make_lab(d, [claim_row(1, 10, 0, words_of(200, 1))])
        lab, src, run = L["lab"], L["source"], L["source"] / "run"
        check(vc.source_problems(src, lab) == [], "a closed run with claims, this import and the verify flags")
        cfg = json.loads((run / "config.json").read_text(encoding="utf-8"))
        (run / "config.json").write_text(json.dumps(dict(cfg, flags_verify=dict(fv.FLAGS_VERIFY, SSB64_RL_ENTITY="0"))), encoding="utf-8")
        check(any("flags_verify" in p for p in vc.source_problems(src, lab)), "other verify flags are refused")
        (run / "config.json").write_text(json.dumps(dict(cfg, **{"import": "C:/elsewhere/import"})), encoding="utf-8")
        check(any("ran with import" in p for p in vc.source_problems(src, lab)), "another import is refused")
        (run / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (run / "summary.json").unlink()
        check(any("not closed" in p for p in vc.source_problems(src, lab)), "a run without its close summary is refused")
        (run / vc.CLAIMS).unlink()
        check(len(vc.source_problems(src, lab)) == 2, "and a run without a claims file")
        (run / "config.json").unlink()
        check(any("config.json cannot be read" in p for p in vc.source_problems(src, lab)), "a run without config.json is refused")
        return {"ok": True}
    finally:
        cleanup(d)


def unit_out_folder() -> Dict[str, Any]:
    d = tmpdir("vclaim_out_")
    try:
        L = make_lab(d, [claim_row(1, 10, 0, words_of(200, 1))])
        lab, src = L["lab"], L["source"]
        out = lab / "verify_x"
        check(vc.out_problems(out, lab, src) == [] and vc.done_claims(out) == {}, "a new folder in the lab is accepted")
        for bad, what in ((src, "overlap"), (src / "run" / "v", "overlap"), (lab / "import" / "v", "import folder"), (d / "outside", "not inside the lab root"),
                          (lab, "not inside the lab root")):
            p = vc.out_problems(bad, lab, src)
            check(any(what in x for x in p), f"{bad} is refused ({what}): {p}")
        check(any("overlap" in x for x in vc.out_problems(lab / "order_x", lab, lab / "order_x" / "run")), "an out folder containing the source is refused")
        run = out / "run"
        (run / "traces").mkdir(parents=True)
        (run / "vw").mkdir()
        (run / "traces" / "clear_n1_c10_k0_r1.json.gz").write_bytes(b"")
        write_jsonl(out / vc.SESSIONS, [{"event": "open", "source": str(src)}])
        write_jsonl(run / vc.VERIFICATIONS, [{"n": 1, "cid": 10, "k": 0, "verdict": "VERIFIED", "phase": vc.PHASE, "source": {"run": str(src).upper()}}])
        check(vc.out_problems(out, lab, src) == [] and vc.done_claims(out) == {(1, 10, 0): "VERIFIED"}, "this tool's folder for this source is accepted")
        stray = [(out / "notes.txt", "file"), (run / "dispatches.jsonl", "file"), (run / "traces" / "reference.json.gz", "file"), (out / "sessions.jsonl.bak", "file")]
        for p, _kind in stray:
            p.write_text("x", encoding="utf-8")
            check(any(str(p) in x for x in vc.out_problems(out, lab, src)), f"a foreign entry {p.name} is refused")
            p.unlink()
        (run / "vw" / "s0_clear_n1_c10_k0_r1").mkdir()
        check(any("is not empty" in x for x in vc.out_problems(out, lab, src)), "leftover replay work in run/vw is refused")
        (run / "vw" / "s0_clear_n1_c10_k0_r1").rmdir()
        write_jsonl(out / vc.SESSIONS, [{"event": "open", "source": str(src)}, {"event": "open", "source": str(lab / "order_y")}])
        check(any("another source" in x for x in vc.out_problems(out, lab, src)), "sessions of another source are refused")
        write_jsonl(out / vc.SESSIONS, [{"event": "open", "source": str(src)}])
        write_jsonl(run / vc.VERIFICATIONS, [{"n": 1, "cid": 10, "k": 0, "verdict": "VERIFIED", "phase": "search", "source": {"run": str(src)}}])
        check(any("not this tool's" in x for x in vc.out_problems(out, lab, src)), "rows of another tool are refused")
        (out / vc.SESSIONS).unlink()
        check(any("without sessions.jsonl" in x for x in vc.out_problems(out, lab, src)), "verifications without sessions are refused")
        write_jsonl(out / vc.SESSIONS, ["{broken"])
        check(any("does not parse" in x for x in vc.out_problems(out, lab, src)), "an unparsable sessions file is refused")
        f = lab / "a_file"
        f.write_text("x", encoding="utf-8")
        check(vc.out_problems(f, lab, src) == [f"{f} exists and is not a folder"], "a file as --out is refused")
        return {"ok": True}
    finally:
        cleanup(d)


def unit_not_imported() -> Dict[str, Any]:
    """No module of the checkout imports verify_claim except its tests: no lab run loads it, so no code digest covers it."""
    pat = re.compile(r"^\s*(import\s+verify_claim\b|from\s+verify_claim\s+import)", re.M)
    hits = []
    for sub in ("rl", "tools", "replay"):
        for p in (REPO / sub).rglob("*.py"):
            if p.name != "verify_claim_tests.py" and pat.search(p.read_text(encoding="utf-8", errors="replace")):
                hits.append(p.relative_to(REPO).as_posix())
    check(hits == [], f"verify_claim is imported by {hits}")
    return {"importers": 0}


# -- a whole session on a stub replay ------------------------------------------------------------------------------------------------------


class StubVerify:
    """Stands in for frs_verify.verify_twice: writes both traces, builds both replays' results by `mode`, and takes the verdict from the
    real rule (frs_verify.verdict). Also records that lab.lock was held by this process during every replay."""

    def __init__(self, lab: Path, modes: Mapping[str, str]):
        self.lab, self.modes, self.calls, self.lock_seen = lab, dict(modes), [], []

    def __call__(self, replay: Any, analyse: Any, words: bytes, claim: Mapping[str, Any], label: str, slot: int, trace_dir: Optional[Path] = None):
        self.calls.append(label)
        lock = self.lab / "lab.lock"
        self.lock_seen.append(lock.is_file() and json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid())
        mode = self.modes.get(label, "ok")
        if mode == "raise":
            raise RuntimeError("the game could not start")
        good = {"outcome": "clear", "ticks": len(words), "ticks_ok": True, "action_digest": mcell.words_digest(words), "action_digest_ok": True,
                "facts_all": True, "completion_input_tick": claim["completion_input_tick"], "completion_time_passed": claim["completion_time_passed"],
                "final_chain": claim["chain"], "breaks": [[10 * i + 5, i] for i in range(10)], "targets": 10}
        r1, r2 = dict(good), dict(good)
        if mode == "chain":
            r1["final_chain"] = r2["final_chain"] = "cd" * 32
        elif mode == "r2tick":
            r2["completion_input_tick"] = claim["completion_input_tick"] + 1
        elif mode == "error":
            r1 = {"outcome": "error", "ticks": 0}
        if trace_dir is not None:
            for i, r in ((1, r1), (2, r2)):
                Path(trace_dir).mkdir(parents=True, exist_ok=True)
                with gzip.open(Path(trace_dir) / f"{label}_r{i}.json.gz", "wt", encoding="utf-8") as f:
                    json.dump({"initial": {"observation": {"input_tick": 0}}, "steps": [], "result": r.get("outcome")}, f)
        v = fv.verdict(r1, r2, claim)
        return {"label": label, "verdict": v["verdict"], "reasons": v["reasons"], "r1": r1, "r2": r2, "errors": [],
                "completion_input_tick": r1.get("completion_input_tick"), "completion_time_passed": r1.get("completion_time_passed"),
                "words": len(words), "wall_s": 0.01}


def stub_deps(L: Mapping[str, Any], verify: StubVerify, **over: Any) -> vc.Deps:
    kw = dict(pids=lambda: [], make_replay=lambda exe, work, flags, frozen: ("replay", str(exe), dict(flags)), analyse=lambda *a: {},
              verify=verify, kill_job=lambda: None, wait_no_battleship=lambda t: [], digests=lambda: {"lab": "l", "run3": "r", "D": "d"},
              git=lambda: {"head": "h", "tracked_changes": []}, readiness=lambda lab: {"problems": []}, expect_exe=L["expect"],
              guard=lambda lab: None)
    kw.update(over)
    return vc.Deps(**kw)


def run_main(args: List[str], deps: vc.Deps) -> Dict[str, Any]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = vc.main(args, deps)
    return {"code": code, "out": buf.getvalue()}


def e2e_stub_session() -> Dict[str, Any]:
    d = tmpdir("vclaim_e2e_")
    try:
        W = {n: words_of(t, n) for n, t in ((1, 330), (2, 310), (3, 320), (4, 340), (5, 300))}
        L = make_lab(d, [claim_row(n, n * 100, 0, w) for n, w in W.items()])
        lab, src, out = L["lab"], L["source"], L["lab"] / "verify_x"
        base = ["--lab-root", str(lab), "--source", str(src), "--out", str(out)]
        before = tree_digest(src)
        stub = StubVerify(lab, {"clear_n2_c200_k0": "chain", "clear_n3_c300_k0": "r2tick", "clear_n4_c400_k0": "error", "clear_n6_c600_k0": "raise"})
        deps = stub_deps(L, stub)

        (lab / "lab.lock").write_text(json.dumps({"pid": os.getpid()}) + "\n", encoding="utf-8")
        r = run_main(base + ["--claim", "1:100:0"], deps)
        check(r["code"] == 2 and "lab.lock exists" in r["out"] and not out.exists() and stub.calls == [], f"a held lock refuses, nothing written: {r}")
        (lab / "lab.lock").unlink()
        r = run_main(base + ["--claim", "1:100:0"], stub_deps(L, stub, pids=lambda: [4242]))
        check(r["code"] == 2 and "4242" in r["out"] and not out.exists(), "a running BattleShip process refuses")
        r = run_main(base + ["--claim", "1:100:0", "--all"], deps)
        check(r["code"] == 2 and "not both" in r["out"], "--claim and --all together are refused")
        r = run_main(base + ["--claim", "1:100:0", "--dry-run"], deps)
        check(r["code"] == 0 and "clear_n1_c100_k0: claimed 330 / 329" in r["out"] and not out.exists() and not (lab / "lab.lock").exists(),
              f"a dry run lists the claim and writes nothing: {r['out'][-300:]}")

        r = run_main(base + ["--claim", "1:100:0"], deps)
        check(r["code"] == 0 and stub.calls == ["clear_n1_c100_k0"] and stub.lock_seen == [True], f"one claim VERIFIED under our lock: {r}")
        check(not (lab / "lab.lock").exists(), "the lock is released")
        rows = vc.read_jsonl(out / "run" / vc.VERIFICATIONS)
        sess = vc.read_jsonl(out / vc.SESSIONS)
        check(len(rows) == 1 and rows[0]["verdict"] == "VERIFIED" and rows[0]["integrity_finding"] is None and all(rows[0]["checks"].values()),
              f"the row: {rows[0]['verdict']} {rows[0]['checks']}")
        check([s["event"] for s in sess] == ["open", "close"] and sess[1]["status"] == "COMPLETED" and sess[0]["chosen"] == [[1, 100, 0]]
              and sess[0]["code_digests"] == {"lab": "l", "run3": "r", "D": "d"} and sess[0]["flags_verify"] == dict(fv.FLAGS_VERIFY), f"sessions: {sess}")
        check(sorted(p.name for p in (out / "run" / "traces").iterdir()) == ["clear_n1_c100_k0_r1.json.gz", "clear_n1_c100_k0_r2.json.gz"], "both traces")
        import crossing_search as cs

        cand = {"n": 1, "cid": 100, "k": 0, "level": 9, "start_tick": 270, "lead": -5, "words": W[1], "claim": rows[0]["claim"]}
        shape = set(cs.clear_row(cand, {"verdict": "VERIFIED"}, 900))
        extra = {"utc", "phase", "tool", "session", "checks", "integrity_finding", "source"}
        check(set(rows[0]) == shape | extra and rows[0]["words_hex"] == W[1].hex() and rows[0]["completion_input_tick"] == 330
              and rows[0]["phase"] == "post_close" and rows[0]["source"]["line"] == 1, f"the crossing-search row plus {sorted(extra)}")

        r = run_main(base + ["--claim", "1:100:0"], deps)
        check(r["code"] == 2 and "never replayed again" in r["out"] and len(stub.calls) == 1, "a verified claim is never replayed again")
        r = run_main(base + ["--all"], deps)
        check(r["code"] == 3 and stub.calls[1:] == ["clear_n5_c500_k0", "clear_n2_c200_k0", "clear_n3_c300_k0", "clear_n4_c400_k0"],
              f"--all: the rest, fastest first; an integrity finding exits 3: {r} {stub.calls}")
        rows = {(x["n"]): x for x in vc.read_jsonl(out / "run" / vc.VERIFICATIONS)}
        check(rows[5]["verdict"] == "VERIFIED" and rows[5]["integrity_finding"] is None, "claim 5 VERIFIED")
        check(rows[2]["verdict"] == "NONDETERMINISTIC" and rows[2]["integrity_finding"] and not rows[2]["checks"]["chain_r1"]
              and not rows[2]["checks"]["chain_r2"] and rows[2]["checks"]["r2_equals_r1"], f"a chain mismatch is an integrity finding: {rows[2]['checks']}")
        check(rows[3]["verdict"] == "NONDETERMINISTIC" and rows[3]["integrity_finding"] and rows[3]["checks"]["tick_r1"]
              and not rows[3]["checks"]["tick_r2"] and not rows[3]["checks"]["r2_equals_r1"], f"replay 2 differing is an integrity finding: {rows[3]['checks']}")
        check(rows[4]["verdict"] == "ERROR" and rows[4]["integrity_finding"] is None, "a replay that could not run is ERROR, not a finding")
        lines = [ln for ln in r["out"].splitlines() if ln.startswith("clear_n")]
        check(any("clear_n2_c200_k0: NONDETERMINISTIC" in ln and "chain" in ln and "MISMATCH" in ln and "INTEGRITY FINDING" in ln for ln in lines),
              f"the report line names the mismatch: {lines}")
        sess = vc.read_jsonl(out / vc.SESSIONS)
        check(sess[-1]["status"] == "INTEGRITY_FINDING" and sess[-1]["integrity_findings"] == ["clear_n2_c200_k0", "clear_n3_c300_k0"]
              and sess[-2]["skipped_done"] == [[1, 100, 0]], f"the close row: {sess[-1]}")
        r = run_main(base + ["--all"], deps)
        check(r["code"] == 0 and "nothing to replay" in r["out"] and len(vc.read_jsonl(out / vc.SESSIONS)) == 4, "nothing left: exit 0, no session rows")
        check(tree_digest(src) == before, "the source folder is byte-identical (never written)")
        vw = out / "run" / "vw"
        check(not (lab / "lab.lock").exists() and (not vw.exists() or not any(vw.iterdir())), "no lock, no replay work left")

        # what the replay browser lists from this folder: the two VERIFIED clears, addressed by their r1 traces
        sys.path.insert(0, str(REPO / "replay"))
        import replay_lab

        scan = replay_lab.scan_lab(lab, {})
        listed = sorted((x["run"], x["completion_tick"], Path(x["path"]).name) for x in scan["rows"])
        check(listed == [("verify_x", 300, "clear_n5_c500_k0_r1.json.gz"), ("verify_x", 330, "clear_n1_c100_k0_r1.json.gz")],
              f"the browser lists the VERIFIED rows only: {listed} ({scan['text']})")
        ep = replay_lab.load_clear(out / "run" / "traces" / "clear_n1_c100_k0_r1.json.gz")
        check(ep.metadata["native_action_digest"] == mcell.words_digest(W[1]) and len(ep.rows) == 330
              and Path(ep.metadata["runtime_config"]).resolve() == (L["exe"] / "BattleShip.cfg.json").resolve(),
              "the viewer loads the verified words with the frozen config")
        return {"rows": len(rows), "listed": len(listed)}
    finally:
        cleanup(d)


def e2e_stub_wall_cap_and_crash() -> Dict[str, Any]:
    d = tmpdir("vclaim_cap_")
    try:
        W = {n: words_of(t, n) for n, t in ((1, 300), (2, 310), (3, 320))}
        L = make_lab(d, [claim_row(n, n * 100, 0, w) for n, w in W.items()])
        lab, src, out = L["lab"], L["source"], L["lab"] / "verify_cap"
        clock = iter(range(0, 10 ** 6, 1000))
        stub = StubVerify(lab, {"clear_n2_c200_k0": "raise"})
        r = run_main(["--lab-root", str(lab), "--source", str(src), "--out", str(out), "--all", "--max-wall-min", str(2500 / 60.0)],
                     stub_deps(L, stub, now=lambda: float(next(clock))))
        rows = vc.read_jsonl(out / "run" / vc.VERIFICATIONS)
        check(r["code"] == 4 and [x["verdict"] for x in rows] == ["VERIFIED", "ERROR"] and "wall cap" in r["out"], f"the cap stops new claims: {r}")
        check("RuntimeError: the game could not start" in rows[1]["reasons"][0] and rows[1]["integrity_finding"] is None, "a crash is an ERROR row")
        check(vc.read_jsonl(out / vc.SESSIONS)[-1]["status"] == "PARTIAL" and not (lab / "lab.lock").exists(), "PARTIAL, lock released")
        r = run_main(["--lab-root", str(lab), "--source", str(src), "--out", str(out), "--claim", "2:200:0"], stub_deps(L, stub))
        check(r["code"] == 2 and "verdict ERROR" in r["out"], "an ERROR row is not replayed again either (the owner decides)")
        return {"rows": len(rows)}
    finally:
        cleanup(d)


# -- the real night-5 records (read only, zero native ticks) ------------------------------------------------------------------------------


def real_night5_records() -> Dict[str, Any]:
    if not (NIGHT5 / "run" / vc.CLAIMS).is_file():
        return {"skipped": "no night-5 folder on this machine"}
    cl = vc.read_claims(NIGHT5 / "run" / vc.CLAIMS)
    best = min(cl, key=lambda c: (c["claimed_completion_input_tick"], c["n"]))
    check(len(cl) == 33 and best["key"] == (8175, 74147, 0) and best["claimed_completion_input_tick"] == 970
          and best["claimed_completion_time_passed"] == 969, f"33 claims parse, the fastest is 970 n8175 c74147 k0: {best['key']}")
    check(vc.source_problems(NIGHT5, LAB) == [], f"night 5 is a closed source: {vc.source_problems(NIGHT5, LAB)}")
    facts, probs = vc.exe_facts(LAB)
    check(probs == [] and facts["exe_sha256"].startswith("30a3913b"), f"the lab executable is 30a3913b and pinned: {probs}")
    check(vc.out_problems(NIGHT5_OUT, LAB, NIGHT5) == [], f"the planned output folder is accepted: {vc.out_problems(NIGHT5_OUT, LAB, NIGHT5)}")
    check(vc.out_problems(NIGHT5 / "run", LAB, NIGHT5) != [] and vc.out_problems(NIGHT5, LAB, NIGHT5) != [], "night 5's own folder is refused")
    return {"claims": len(cl), "fastest": best["claimed_completion_input_tick"], "out_exists": NIGHT5_OUT.exists()}


TESTS = {"unit_parse_specs_and_rows": unit_parse_specs_and_rows, "unit_read_claims_file": unit_read_claims_file, "unit_select": unit_select,
         "unit_lock_exe_processes": unit_lock_exe_processes, "unit_source_problems": unit_source_problems, "unit_out_folder": unit_out_folder,
         "unit_not_imported": unit_not_imported, "e2e_stub_session": e2e_stub_session, "e2e_stub_wall_cap_and_crash": e2e_stub_wall_cap_and_crash,
         "real_night5_records": real_night5_records}

if __name__ == "__main__":
    sys.exit(run_suite("verify_claim tests", TESTS, sys.argv[1:]))
