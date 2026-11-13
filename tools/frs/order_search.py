#!/usr/bin/env python3
"""Option D search: order discovery from tick 0 (docs/frs_option_d_design_2026-11-11.md, decided by the owner on 2026-11-12; build phase
2). Built on run 3's engine (tools/frs/run3_search.py, tools/frs/crossing_search_run3.py) by import and subclassing; no run 3 file is edited.

    root            one tick-0 root (section 5.1). At the open two fresh processes each reach tick 0 with no input word
                    (rl/m8_rd_worker.run_tick0 on run 3's workers, no pin): their tick-0 records (every observation field but
                    host_frame, the record digest, the chain start, the record lines), cell keys and live masks must be equal, else
                    SEARCH_INVALID. The root is level 0, mask 1023, niche (1023, ()), empty prefix; its end record is the tick-0
                    observation (stored, so no dispatch is fused) and the tick-0 record is the pin of every later dispatch, each one a
                    fresh process from tick 0.
    keep            the pace rule (tools/frs/order_select.Pace): a reach at level L < 10 with input tick t > line(L) is not kept (the
                    BEYOND verdict) and counts in the rejected-reach readout (report-only); everything else is run 3's keep rule.
    F3              a CONT boundary continues only on a reach the pace rule would keep (section 4.4): run 3's as-of answer over the
                    reported reaches inside the line.
    selection       tools/frs/order_select.OrderSelector (section 3; gaps A-F, G1-G5). No trigger draws.
    claims          a clear faster than the frontier's best verified clear, read at the plan, is verified twice from tick 0, as run 3
                    (then against D's own best); exports and native text replays of new bests as run 3.
    milestones      M1 ... M4 and the clear line (section 8, gap E), recorded at their first occurrence (milestones.jsonl) and verified
                    at the close by two fresh-process replays of the arrival's prefix with the verify flags: both must show at least L
                    targets broken by the recorded tick and the recorded chain (D-Q8). Only the first arrival per milestone; no
                    fallback. A disagreement is SEARCH_INVALID (the night is not a test of M1); a verified prefix is exported as a
                    .btt.txt (section 7.3).
    records         dispatches.jsonl, cells.jsonl (the root's NEW row first), root.json, milestones.jsonl, milestone_verifications.jsonl,
                    hourly.jsonl / hourly.md (section 7.2), run 3's files (verifications, claims not replayed, exports, best times, text
                    replays, anomalies, schedule), summary.json, report.md, progress.md.
    code digest     D's own manifest: every repository file D's entry modules import, in a fresh interpreter, each hashed with its line
                    endings normalised to LF (owner 2026-11-12), recorded at the plan, enforced at the open; a change during the run is
                    SEARCH_INVALID at the close.
    archive id      frs_order_v1|seed<rng seed>: no run 3 archive id, so no frontier burst is repeated (section 5.3); the same seed gives
                    the same night (E1).
    readiness       the registered readiness rule (rl/frs_machine.readiness) at the open, unchanged by default. An explicit owner
                    override (--min-commit-free-mb with --override-reason, given to both plan and run) lowers only the free-commit
                    minimum, for that folder only; any other readiness problem still refuses. It is recorded in plan.json, config.json,
                    summary.json and report.md.

    python -B tools/frs/order_search.py plan --lab-root C:/BattleShip_lab --frontier DIR --rng-seed 11 [--out DIR] ...
    python -B tools/frs/order_search.py run  --lab-root C:/BattleShip_lab --frontier DIR --rng-seed 11 --out DIR --workers 5 --max-wall-min 480

`plan` is zero native ticks; `run` is native. Writes only under the output folder (`order_*`) through the lab's guard; takes the lab lock, so
D and the frontier never run together; nothing reads native RNG. Zero-tick tests: tools/frs/order_search_tests.py. Run with python -B.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (REPO / "rl", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import crossing_search as cs  # noqa: E402
import crossing_search_run2 as r2  # noqa: E402
import crossing_search_run3 as C  # noqa: E402
import det_schedule as det  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_machine as fm  # noqa: E402
import frs_report as frep  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_verify as fv  # noqa: E402
import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import order_select as osel  # noqa: E402
import run3_anomaly as ra  # noqa: E402
import run3_export as rx  # noqa: E402
import run3_load as rl3  # noqa: E402
import run3_manifest as rm  # noqa: E402
import run3_search as r3  # noqa: E402
import run3_select as rs  # noqa: E402
import run3_worker as r3w  # noqa: E402

ORDER_CONTRACT = "frs_order_search_v1"
MANIFEST_CONTRACT = "order_code_manifest_v1"
ENTRY_MODULES = ("order_search", "order_select") + tuple(rm.ENTRY_MODULES)
KEY_FAMILY = "order1"
ARCHIVE_ID = "frs_order_v1|seed{seed}"
FOLDER_PREFIX = "order_"
MILESTONE_NAMES = [name for name, _L in osel.MILESTONES] + [osel.CLEAR_LINE]
M_VERIFIED, M_NOT_VERIFIED, M_ERROR, M_NOT_RUN = "VERIFIED", "NOT_VERIFIED", "ERROR", "NOT_RUN"
SearchError, Refused = cs.SearchError, cs.Refused


# -- D's code manifest (T-M2): line endings normalised to LF ------------------------------------------------------------------------------


def lf_sha256(p: Path) -> str:
    """sha256 of the file's bytes with CRLF normalised to LF: the same content gives the same hash in any checkout (owner 2026-11-12)."""
    return hashlib.sha256(Path(p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def order_code_manifest(repo: Path = REPO, entries: Sequence[str] = ENTRY_MODULES) -> Dict[str, str]:
    """{repo-relative posix path: LF-normalised sha256} of every repository file D's entry modules import, in a fresh interpreter (run 3's
    entry modules and their function-level imports, tools/frs/run3_manifest.ENTRY_MODULES, plus D's two modules)."""
    repo = Path(repo).resolve()
    frs = repo / "tools" / "frs"
    code = ("import json, sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import importlib; [importlib.import_module(m) for m in %r]; "
            "print(json.dumps(sorted({m.__file__ for m in list(sys.modules.values()) if getattr(m, '__file__', None)})))"
            % (str(repo / "rl"), str(frs), list(entries)))
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, cwd=str(frs), timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"D's code manifest could not be computed: {r.stderr[-800:]}")
    root = os.path.normcase(str(repo))
    out: Dict[str, str] = {}
    for f in json.loads(r.stdout.strip().splitlines()[-1]):
        p = Path(f).resolve()
        if os.path.normcase(str(p)).startswith(root + os.sep):
            out[p.relative_to(repo).as_posix()] = lf_sha256(p)
    return dict(sorted(out.items()))


def code_digest(manifest: Mapping[str, str]) -> str:
    return rm.code_digest(manifest)


def changed_files(manifest: Mapping[str, str], repo: Path = REPO) -> List[str]:
    out = []
    for rel, h in manifest.items():
        p = Path(repo) / rel
        if not p.is_file() or lf_sha256(p) != h:
            out.append(rel)
    return out


# -- the frontier's best (read only, at the plan; D-Q6) ------------------------------------------------------------------------------------


def read_frontier_best(d: Path) -> Dict[str, Any]:
    """Section 6.2: the frontier chain's latest verified best, read only, from a run 3 folder (the chain's last night): completion tick,
    clocks, chain and words digests. The folder must be a clean run 3 lab run with a clean integrity record and no frozen claims. Nothing
    else of it is read: no cell, no niche, no rate."""
    d = Path(d)
    pp, sp = d / "plan.json", d / "run" / "summary.json"
    for f in (pp, sp):
        if not f.is_file():
            raise SearchError(f"refused: {d} is not a frontier (run 3) folder: missing {f.relative_to(d).as_posix()}")
    plan = json.loads(pp.read_text(encoding="utf-8"))
    summary = json.loads(sp.read_text(encoding="utf-8"))
    if ORDER_CONTRACT in (plan.get("contract"), summary.get("contract")):
        raise SearchError(f"refused: {d} is a D folder, not the frontier")
    if plan.get("contract") != C.RUN3_CONTRACT or summary.get("contract") != C.RUN3_CONTRACT or summary.get("mode") != "lab":
        raise SearchError(f"refused: {d} is not a {C.RUN3_CONTRACT} lab run")
    if summary.get("status") not in rl3.CLEAN_STATUSES:
        raise SearchError(f"refused: the frontier folder {d} did not stop cleanly (status {summary.get('status')})")
    integ = summary.get("integrity") or {}
    if integ.get("guard_violations_main") or integ.get("prefix_mismatches") or integ.get("battleship_left") or integ.get("reference_ok") is not True \
            or integ.get("run3_code_changed_during_run") or integ.get("run3_code_digest_end") != integ.get("run3_code_digest"):
        raise SearchError(f"refused: the frontier folder {d}'s integrity record is not clean")
    x = summary.get("run3") or {}
    if x.get("claims_frozen"):
        raise SearchError(f"refused: the frontier folder {d} froze its claims")
    best = x.get("best") or {}
    cit = best.get("completion_input_tick")
    if not isinstance(cit, int) or isinstance(cit, bool) or cit <= 0:
        raise SearchError(f"refused: {d} records no verified best ({best!r})")
    return {"dir": str(d), "summary": str(sp), "summary_sha256": g.sha256_file(sp), "status": summary.get("status"), "utc_end": summary.get("utc_end"),
            "completion_input_tick": int(cit), "completion_time_passed": best.get("completion_time_passed"), "chain": best.get("chain"),
            "words_digest": best.get("words_digest"), "n": best.get("n"), "source": best.get("source")}


# -- the plan (zero native ticks) -----------------------------------------------------------------------------------------------------------


def engine_params(dp: osel.OrderParams, **kw: Any) -> C.Params3:
    """Run 3's engine parameters for D: its CONT arm, caps, keyed seed and record interval; breadth share = D's; no triggers; the archive
    retires nothing (D's retirement is the selector's)."""
    kw.setdefault("retire_after", 0)
    p = C.Params3(breadth_share=float(dp.breadth_share), trigger_classes=(), **kw)
    p.check()
    return p


def readiness_override_record(min_commit_free_mb: Optional[int], reason: str) -> Optional[Dict[str, Any]]:
    """The owner's explicit free-commit override (--min-commit-free-mb with --override-reason), or None: the registered rule, unchanged."""
    reason = str(reason or "").strip()
    if min_commit_free_mb is None and not reason:
        return None
    if min_commit_free_mb is None or not reason:
        raise SearchError("refused: --min-commit-free-mb and --override-reason go together (an owner override names its reason)")
    reg = int(fm.READINESS["min_commit_free_mb"])
    if not 0 < int(min_commit_free_mb) < reg:
        raise SearchError(f"refused: --min-commit-free-mb is between 1 and the registered {reg} MB")
    return {"min_commit_free_mb": int(min_commit_free_mb), "reason": reason, "registered_min_commit_free_mb": reg,
            "scope": "owner override for this folder only; only the free-commit minimum is lowered; any other readiness problem refuses"}


def readiness_verdict(ready: Mapping[str, Any], override: Optional[Mapping[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """(admitted, the override's use or None). Without an override, the registered rule. With one, a refusal is admitted only when every
    problem is the free-commit minimum and free commit is at least the override's value."""
    if ready.get("ok"):
        return True, (None if override is None else dict(override, applied=False))
    if override is None:
        return False, None
    probs = [str(p) for p in ready.get("problems") or []]
    free = (ready.get("memory") or {}).get("commit_free_mb")
    ok = bool(probs) and all(p.startswith("free commit ") for p in probs) and free is not None and float(free) >= float(override["min_commit_free_mb"])
    return ok, dict(override, applied=ok, registered_problems=probs, commit_free_mb=free)


def build_plan(lab_root: Path, frontier_dir: Path, out: Path, dp: osel.OrderParams, ep: C.Params3, *, code: Optional[str] = None,
               readiness_override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The plan (section 7.1 step 2): the root, the pace table, the parameters, the frontier reference read. Zero ticks."""
    dp.check()
    ep.check()
    pace = osel.Pace(dp)
    fb = read_frontier_best(frontier_dir)
    osel.claim_wanted(1, fb["completion_input_tick"])
    digest = code or code_digest(order_code_manifest())
    return {"contract": ORDER_CONTRACT, "mode": "lab", "utc": g.utc(), "lab_root": str(lab_root), "out": str(out),
            "archive_id": ARCHIVE_ID.format(seed=int(ep.rng_seed)), "key_family": KEY_FAMILY,
            "root": {"level": 0, "mask": osel.ROOT_MASK, "niche": rs.niche_label(rs.seed_niche(osel.ROOT_MASK)), "words": 0,
                     "read": "at the open: two fresh processes reach tick 0 with no input word; tick-0 records, keys and masks must be equal"},
            "pace": {"goal": dp.goal, "slack": dp.slack, "lines": {str(L): pace.line(L) for L in range(osel.TARGETS_TOTAL + 1)}},
            "milestones": {name: {"level": L, "line": pace.line(L)} for name, L in list(osel.MILESTONES) + [(osel.CLEAR_LINE, osel.TARGETS_TOTAL)]},
            "gate": {"milestone": "M1", "level": 6, "line": pace.line(6)},
            "params": dp.as_record(), "params_fingerprint": osel.params_fingerprint(dp), "selection_contract": osel.SELECT_CONTRACT,
            "engine_params": ep.as_dict(), "arm": ep.arm(), "frontier": fb, "claim_threshold": fb["completion_input_tick"],
            "sources": [fb["summary"]], "code": {"contract": MANIFEST_CONTRACT, "entries": list(ENTRY_MODULES), "digest": digest},
            "readiness_override": None if readiness_override is None else dict(readiness_override)}


def plan_and_write(lab_root: Path, frontier_dir: Path, out: Path, dp: osel.OrderParams, ep: C.Params3, *, code: Optional[str] = None,
                   readiness_override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    out = Path(out)
    if not out.name.startswith(FOLDER_PREFIX):
        raise SearchError(f"refused: D's folder name starts with {FOLDER_PREFIX!r} ({out.name})")
    pp = out / "plan.json"
    if pp.is_file():
        old = json.loads(pp.read_text(encoding="utf-8"))
        if old.get("contract") != ORDER_CONTRACT:
            raise SearchError(f"refused: {out} holds another tool's plan ({old.get('contract')}); D plans only into its own folder")
    if (out / "run").exists():
        raise SearchError(f"refused: {out / 'run'} exists (a run folder is never re-planned)")
    plan = build_plan(lab_root, frontier_dir, out, dp, ep, code=code, readiness_override=readiness_override)
    fs = g.LabFS(Path(lab_root))
    fs.mkdir(out)
    fs.write_json(pp, plan)
    return plan


def engine_plan(plan: Mapping[str, Any], ep: C.Params3) -> Dict[str, Any]:
    """What run 3's engine core reads from a plan, for D: an empty archive (the root is kept at the open), the pace line as the per-level
    reference (lead = line(L) - tick), the frontier's best as the claim reference, no seed, no inherited run."""
    lines = {int(L): int(t) for L, t in plan["pace"]["lines"].items()}
    fb = plan["frontier"]
    top = lines[osel.TARGETS_TOTAL]
    archive = r2.ResumeArchive(plan["archive_id"], lines, top, ep)
    best = {"n": None, "cid": None, "k": None, "level": None, "start_tick": None, "completion_input_tick": int(fb["completion_input_tick"]),
            "completion_time_passed": fb.get("completion_time_passed"), "chain": fb.get("chain"), "words_digest": fb.get("words_digest"), "breaks": [],
            "arrival": {}, "source": f"frontier {fb['dir']}", "utc": fb.get("utc_end"), "words": None}
    compat = dict(plan, seed_set_digest=None, seeds=[], seed_ticks=0, route=None,
                  e7={"rule": "none: the pace line (section 4) is D's keep and eligibility rule", "lines": dict(plan["pace"]["lines"]), "bound_max_L": top})
    return {"plan": compat, "seeds": [], "R": {"arrival": lines, "expected": {"completion_input_tick": int(fb["completion_input_tick"])}, "words": None},
            "meta": {"pin_tick0": {}, "archive_id": plan["archive_id"]}, "bound": top, "archive": archive, "R1": {}, "bound_run1": top, "best": best,
            "order": dict(plan)}


# -- the engine ---------------------------------------------------------------------------------------------------------------------------


def root_differences(reads: Sequence[Mapping[str, Any]]) -> List[str]:
    """Why two tick-0 reads differ: any observation field but host_frame, the record digest, the chain start, the record lines, the key,
    the live mask."""
    if len(reads) != 2 or not all(r.get("ok") for r in reads):
        return [f"a tick-0 read failed: {[r.get('error') or r.get('kind') for r in reads if not r.get('ok')][:2]}"]
    a, b = reads
    out = [f"observation {k}" for k in sorted(mcell.obs_diffs(tuple(a["obs"]), tuple(b["obs"])))]
    out += [k for k in ("digest", "chain", "lines", "key", "mask") if a.get(k) != b.get(k)]
    return out


class OrderEngine(C.Run3Engine):
    """Run 3's engine with D's open (the tick-0 root), keep (the pace rule), selection, milestones, records and code manifest."""

    readiness_override: Optional[Dict[str, Any]] = None     # the plan's owner override (cmd_run sets it); None = the registered rule
    readiness_use: Optional[Dict[str, Any]] = None          # how the open used it (recorded in config.json and the summary)

    def __init__(self, cfg: cs.SearchConfig, env: Any, P: Mapping[str, Any], params: C.Params3, *, order_params: osel.OrderParams,
                 text_replay: Optional[rx.TextReplayFn] = None):
        r3.Run3Core.__init__(self, cfg, env, P, params)      # run 3's core; Run3Engine.__init__ (run 3's plan, start table, selector) is replaced
        self.p3 = params
        self.dp = order_params
        self.dp.check()
        self.pace = osel.Pace(self.dp)
        self.order_plan: Dict[str, Any] = dict(P["order"])
        if self.order_plan.get("params") != self.dp.as_record() or self.order_plan.get("engine_params") != params.as_dict():
            raise SearchError("refused: the parameters differ from the plan's")
        self.order_code_expect: Optional[str] = (self.order_plan.get("code") or {}).get("digest")
        self.order_code: Dict[str, str] = {}
        self.order_code_dig = ""
        self.selector: Any = None                            # built at the open, once the root is kept
        self.root: Dict[str, Any] = {}
        self.text_replay_fn = text_replay
        self.best_start = {k: v for k, v in self.best.items() if k != "words"}
        self._cur: Optional[Tuple[Mapping[str, Any], Mapping[str, Any]]] = None
        self._kept: List[Tuple[str, Any, rs.Niche]] = []
        self._row: Optional[Dict[str, Any]] = None
        self._post: List[List[int]] = []
        self.niche_live = rs.Counter()
        self._events_logged = 0
        self.hourly: List[Dict[str, Any]] = []
        self.hourly_md: List[str] = []
        self._next_record_t: Optional[float] = None
        self._final_record = False
        self.exports: List[Dict[str, Any]] = []
        self.text_replays: List[Dict[str, Any]] = []
        self.claims_frozen: Optional[Dict[str, Any]] = None
        self.ms_rows: Dict[str, Dict[str, Any]] = {}
        self.ms_verifications: List[Dict[str, Any]] = []
        self.deepest_history: List[Tuple[float, Optional[int]]] = []
        self.c.update({"rejected_reaches": 0, "milestone_ticks": 0})
        orig_keep = self.archive.keep

        def keep(key: Sequence[Any], level: int, tick: int, words: bytes, end: Sequence[Any], end_digest: bytes, chain: bytes, origin: Mapping[str, Any],
                 n_dispatch: int, **kw: Any) -> Tuple[str, Optional[cs.Cell]]:
            lv, t = int(level), int(tick)
            if not kw.get("terminal") and lv < osel.TARGETS_TOTAL and not self.pace.keeps(lv, t):
                self.archive.counts[cs.BEYOND] += 1              # the pace rule: not kept; counted in the rejected-reach readout
                self.pace.rejected.note(lv, t)
                self.c["rejected_reaches"] += 1
                return cs.BEYOND, None
            verdict, c = orig_keep(key, level, tick, words, end, end_digest, chain, origin, n_dispatch, **kw)
            if verdict in (cs.NEW, cs.REPLACED) and c is not None and self._cur is not None:
                info = self._cur[0]
                self._kept.append((verdict, c, rs.child_niche(info["niche"], int(c.key[3]), int(c.tick), self._post, self.niche_live)))
            return verdict, c

        self.archive.keep = keep  # an instance attribute: DeterministicSchedule wraps this one in turn

    # -- open: checks, D's code digest, the workers, the tick-0 root -------------------------------------------------------------------------

    def open(self) -> None:
        cfg, env = self.cfg, self.env
        if self.dir.exists():
            raise Refused(f"{self.dir} exists (a run folder is never overwritten)")
        ready = env.readiness()
        admitted, self.readiness_use = readiness_verdict(ready, self.readiness_override)
        if not admitted:
            raise Refused(f"readiness: {ready['problems']}" + ("" if self.readiness_override is None else
                                                               f" (the owner override, free commit >= {self.readiness_override['min_commit_free_mb']} MB, does not admit it)"))
        pids = env.battleship_pids()
        if pids is None or pids:
            raise Refused(f"BattleShip processes already running (or unreadable): {pids}")
        bad = env.import_problems()
        if bad:
            raise Refused(f"import pins: {bad[:6]}")
        self.code = env.code_manifest()
        self.code_dig = fr.code_digest(self.code)
        if cfg.expect_code and self.code_dig != cfg.expect_code:
            raise Refused(f"lab code digest {self.code_dig[:16]} differs from the expected {cfg.expect_code[:16]}")
        if not self.order_code_expect:
            raise Refused("no recorded D code digest (the plan records code.digest)")
        self.order_code = order_code_manifest()
        self.order_code_dig = code_digest(self.order_code)
        if self.order_code_dig != self.order_code_expect:
            raise Refused(f"D's code digest {self.order_code_dig[:16]} differs from the plan's {str(self.order_code_expect)[:16]} ({len(self.order_code)} files)")
        self.fs.mkdir(self.dir)
        self.fs.write_json(self.dir / "config.json", self.config_record(ready))
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=env.snapshot, now=env.now,
                                  extra=lambda: {"cells": len(self.archive.cells), "phase": self.phase, "dispatches": self.c["dispatches"], "jobs": self.c["jobs"],
                                                 "words_mb": round(self.archive.words_bytes / 2 ** 20, 1)}).start()
        self.phase = "root"
        self.pool = r3w.Run3Pool(env.worker_spec, env.now)
        self.pool.start(cfg.n_workers)
        reads = self.root_reads()
        if self.stopping:
            return
        differs = root_differences(reads)
        self.root = {"equal": not differs, "differs": differs, "reads": [{k: r.get(k) for k in ("ok", "digest", "chain", "lines", "key", "mask", "obs", "pid", "worker", "wall_s")}
                                                                         for r in reads], "utc": g.utc()}
        self.fs.write_json(self.dir / "root.json", self.root)
        if differs:
            self.mark("SEARCH_INVALID", f"tick-0 inequality at the root: {differs[:6]}")
            return
        r0 = reads[0]
        if r0.get("key") is None or int(r0["mask"]) != osel.ROOT_MASK:
            self.mark("SEARCH_INVALID", f"the tick-0 state is not a root with every target live (key {r0.get('key')}, mask {r0.get('mask')})")
            return
        self.pin = {"obs": list(r0["obs"]), "digest": r0["digest"], "chain": r0["chain"], "lines": r0["lines"]}
        verdict, c = self.archive.keep(tuple(r0["key"]), 0, 0, b"", tuple(r0["obs"]), bytes.fromhex(r0["digest"]), bytes.fromhex(r0["chain"]), {"kind": "root"}, 0)
        if verdict != cs.NEW or c is None:
            raise SearchError(f"the root was not kept ({verdict})")
        self.emit_cell(cs.NEW, c, None)
        self.selector = osel.OrderSelector(self.archive, self.dp, niches={c.cid: rs.seed_niche(osel.ROOT_MASK)}, best_claim=None)
        self.root["cid"] = c.cid
        if self.readiness_use and self.readiness_use.get("applied"):
            self.event(f"READINESS OVERRIDE (owner): free commit {self.readiness_use['commit_free_mb']:.0f} MB admitted at >= "
                       f"{self.readiness_use['min_commit_free_mb']} MB (registered {self.readiness_use['registered_min_commit_free_mb']} MB); "
                       f"reason: {self.readiness_use['reason']}")
        self.phase_wall["open"] = round(env.now() - self.t0, 1)
        self.log(f"open done in {self.phase_wall['open']:.0f} s; {cfg.n_workers} workers ready; root cell {c.cid} (key {list(c.key)}); pace lines "
                 f"{self.order_plan['pace']['lines']}; claim threshold {self.order_plan['claim_threshold']}; params {self.dp.as_record()}; arm {cs.ARM_NAME} {self.arm}")
        self.write_progress()

    def root_reads(self) -> List[Dict[str, Any]]:
        """Section 5.1: two fresh processes reach tick 0 with no input word (one worker each, or one worker twice): both replies."""
        cfg, env, pool = self.cfg, self.env, self.pool
        assert pool is not None
        ws = [0, 1] if cfg.n_workers >= 2 else [0, 0]
        reads: List[Dict[str, Any]] = []
        for w in ws:
            pool.send(w, {"kind": "tick0", "pin": None})
            t = env.now()
            got: Optional[Tuple[str, Dict[str, Any]]] = None
            while got is None:
                for ww, kind, payload in pool.poll2(0.2, lambda _w, _p: None):
                    if ww == w:
                        got = (kind, payload)
                if got is None and env.now() - t > cfg.job_timeout_s:
                    self.mark("SEARCH_INCOMPLETE", f"the tick-0 read on worker {w} did not return in {cfg.job_timeout_s:.0f} s", abort=True)
                    return reads
            kind, payload = got
            if kind in ("died", "fatal") or not isinstance(payload, dict):
                reads.append({"ok": False, "kind": kind, "error": json.dumps(payload, default=str)[:300], "worker": w})
                continue
            reads.append(dict(payload, worker=w))
        return reads

    # -- dispatch: D's key family; the root's prefix is empty ------------------------------------------------------------------------------

    def build_job(self, w: int, c: cs.Cell, draw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        cfg = self.cfg
        if c.words is None or not getattr(c, "verified", False) or len(c.end) != len(mcell.OBS_FIELDS):
            raise SearchError(f"cell {c.cid}: every D cell carries its end record (no fused dispatch)")
        max_words = self.arm["segment_words"] * self.arm["max_segments"]
        want = c.tick + min(max_words, mcell.HORIZON - c.tick)
        if self.used_ticks() + self.reserved + want + self.verify_ticks_pending() > cfg.max_ticks:
            self.mark("TICK_CAP", f"the tick cap {cfg.max_ticks:,} would be exceeded by the next dispatch")
            return None
        k = c.next_k
        c.next_k += 1
        draw_id = f"{self.archive.archive_id}|{KEY_FAMILY}|{c.digest}"
        job = {"kind": fw.JOB_KIND, "iteration": k, "cell": c.cid, "rep": (c.cid, c.tick), "words": bytes(c.words), "end": tuple(c.end), "end_digest": bytes(c.end_digest),
               "chain": bytes(c.chain), "terminal": False, "pin": self.pin, "archive_id": draw_id, "allowance": int(want), **self.arm}
        self.c["dispatches"] += 1
        self.inflight[w] = {"n": self.c["dispatches"], "cid": c.cid, "k": k, "level": c.level, "tick": c.tick, "lead": c.lead, "draw_id": draw_id, "draw": dict(draw),
                            "fresh": c.fresh, "seen": c.seen, "breaks": c.breaks, "digest": c.digest, "words": bytes(c.words), "reserved": int(want), "cont": [],
                            "root": c.root, "inherited": c.inherited, "cleared": c.cleared, "fused": False}
        self.reserved += int(want)
        return job

    # -- ingest: milestones ------------------------------------------------------------------------------------------------------------------

    def commit(self, info: Mapping[str, Any], c: cs.Cell, res: Mapping[str, Any]) -> None:
        super().commit(info, c, res)
        self.log_milestones(info)

    def log_milestones(self, info: Mapping[str, Any]) -> None:
        met = self.selector.milestones.met
        for name in MILESTONE_NAMES:
            rec = met.get(name)
            if rec is None or name in self.ms_rows:
                continue
            row = dict(rec, utc=g.utc(), elapsed_s=round(self.elapsed(), 1))
            if name == osel.CLEAR_LINE:
                cand = next((x for x in self.vqueue if int(x["n"]) == int(rec["n"])), None)
                words = bytes(cand["words"]) if cand is not None else None
                row.update({"tick": rec["completion_input_tick"], "chain": (cand or {}).get("claim", {}).get("chain")})
            else:
                cell = self.archive.cells[int(rec["cid"])]
                words = bytes(cell.words) if cell.words is not None and cell.digest == rec["digest"] else None
            row["words_hex"] = words.hex() if words is not None else None
            row["words"] = len(words) if words is not None else None
            self.ms_rows[name] = row
            self.fs.append_jsonl(self.dir / "milestones.jsonl", {k: v for k, v in row.items()})
            self.event(f"MILESTONE {name}: {rec.get('arrival_level', rec['level'])} targets at tick {row['tick']} (line {rec['line']}) from dispatch {rec['n']}, "
                       f"cell {rec['cid']}; verified at the close")

    # -- the close: claims and text replays (run 3), then the milestones -----------------------------------------------------------------------

    def close_verifications(self) -> None:
        super().close_verifications()
        self.verify_milestones()

    def verify_milestones(self) -> None:
        deadline = self.t0 + self.cfg.max_wall_s - self.cfg.write_reserve_s
        for name in MILESTONE_NAMES:
            row = self.ms_rows.get(name)
            if row is None:
                continue
            if self.env.now() >= deadline:
                out = {"milestone": name, "n": row["n"], "verdict": M_NOT_RUN, "reasons": ["the close deadline"]}
            elif not row.get("words_hex") or not row.get("chain"):
                out = {"milestone": name, "n": row["n"], "verdict": M_ERROR, "reasons": ["the arrival's words or chain were not recorded"]}
            else:
                out = self.verify_milestone(row)
            out["utc"] = g.utc()
            self.ms_verifications.append(out)
            self.fs.append_jsonl(self.dir / "milestone_verifications.jsonl", out)
            if out["verdict"] == M_VERIFIED:
                words = bytes.fromhex(row["words_hex"])
                try:
                    stem = f"{name}_n{row['n']}_t{row['tick']}"
                    self.fs.mkdir(self.dir / "milestones")
                    path = self.dir / "milestones" / f"{stem}{rx.TEXT_SUFFIX}"
                    text = rx.btti_text(words, f"milestone={name} n={row['n']} cid={row['cid']} tick={row['tick']} level>={row['level']}")
                    self.fs.write_text(path, text)
                    ex = {"milestone": name, "n": row["n"], "btti": str(path), "btti_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "frames": len(words)}
                except Exception as exc:  # noqa: BLE001 - recorded; the milestone stays verified
                    ex = {"milestone": name, "n": row["n"], "error": f"{type(exc).__name__}: {exc}"[:300]}
                ex["utc"] = g.utc()
                self.exports.append(ex)
                self.fs.append_jsonl(self.dir / "exports.jsonl", ex)
                self.event(f"milestone {name} VERIFIED by two replays: {row['tick']} (line {row['line']})")
            elif out["verdict"] == M_NOT_VERIFIED:
                self.mark("SEARCH_INVALID", f"milestone {name} (dispatch {row['n']}): its replays disagree with the record: {out['reasons'][:3]}")
            else:
                self.mark("SEARCH_INCOMPLETE", f"milestone {name} (dispatch {row['n']}) could not be verified: {out['reasons'][:2]}")

    def verify_milestone(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        """Two fresh-process replays of the arrival's prefix with the verify flags (D-Q8, gap E): each must show at least `level` targets
        broken by the recorded tick and the recorded chain, and the two must agree."""
        env = self.env
        words = bytes.fromhex(row["words_hex"])
        name, L, t = row["milestone"], int(row["level"]), int(row["tick"])
        label = f"milestone_{name}_n{row['n']}"
        reps = []
        for i in (1, 2):
            tr, errors = fv.replay_with_retry(env.replay, words, f"{label}_r{i}", 0)
            fv.save_trace(self.dir / "traces" / f"{label}_r{i}.json.gz", tr)
            r = fv.evaluate(tr, words, env.analyse)
            r["errors"] = errors
            self.c["milestone_ticks"] += int(r.get("ticks") or 0)
            self.c["verify_ticks"] += int(r.get("ticks") or 0)
            reps.append(r)
        r1, r2 = reps
        base = {"milestone": name, "n": row["n"], "cid": row["cid"], "level": L, "tick": t, "line": row["line"], "chain_recorded": row["chain"],
                "r1": {k: r1.get(k) for k in ("outcome", "ticks", "ticks_ok", "action_digest_ok", "final_chain", "breaks", "completion_input_tick", "errors")},
                "r2": {k: r2.get(k) for k in ("outcome", "ticks", "ticks_ok", "action_digest_ok", "final_chain", "breaks", "completion_input_tick", "errors")}}
        if r1.get("outcome") == "error" or r2.get("outcome") == "error":
            return dict(base, verdict=M_ERROR, reasons=["a replay could not run"])
        reasons = []
        for i, r in ((1, r1), (2, r2)):
            if not r.get("ticks_ok"):
                reasons.append(f"replay {i}: a consumed tick differs")
            if not r.get("action_digest_ok"):
                reasons.append(f"replay {i}: the native action digest differs from the words")
            broken = sum(1 for bt, _i in (r.get("breaks") or []) if int(bt) <= t)
            if broken < L:
                reasons.append(f"replay {i}: {broken} targets broken by tick {t}, fewer than {L}")
            if r.get("final_chain") != row["chain"]:
                reasons.append(f"replay {i}: the chain differs from the recorded one")
            if name == osel.CLEAR_LINE and r.get("completion_input_tick") != t:
                reasons.append(f"replay {i}: completion input tick {r.get('completion_input_tick')} is not the recorded {t}")
        if [r1.get(k) for k in ("final_chain", "breaks", "action_digest", "ticks")] != [r2.get(k) for k in ("final_chain", "breaks", "action_digest", "ticks")]:
            reasons.append("the two replays differ")
        return dict(base, verdict=M_VERIFIED if not reasons else M_NOT_VERIFIED, reasons=reasons)

    # -- hourly records (section 7.2) ------------------------------------------------------------------------------------------------------------

    def write_record(self, at: str) -> Dict[str, Any]:
        sel = self.selector
        if sel is None:
            return {}
        per = sel.period
        wall = at != "dispatches"
        verified = [v for v in self.vrows if v["verdict"] == fv.VERIFIED]
        readout = sel.level_readout()
        eligible: Dict[str, int] = {}
        for cid in sel.breadth_pool():
            k = str(self.archive.cells[cid].level)
            eligible[k] = eligible.get(k, 0) + 1
        for lv, d in readout.items():
            e = self.archive.earliest.get(int(lv)) or {}
            d.update({"eligible": eligible.get(lv, 0), "dispatched": int(per["by_level"].get(lv, 0)), "earliest_arrival": e.get("tick"),
                      "earliest_arrival_vs_line": (int(e["tick"]) - self.pace.line(int(lv))) if e.get("tick") is not None else None})
        streams = {k: int(v) for k, v in sorted(per["streams"].items())}
        nd = int(per["dispatches"])
        bshare = round(streams.get("breadth", 0) / nd, 4) if nd else None
        rot = sel.rotation_levels()
        deepest = max(rot) if rot else None
        el = round(self.elapsed(), 1)
        flags = []
        wv = sel.within_one_violations()
        if wv:
            flags.append({"flag": "budget_counts_not_within_1", "detail": wv[:8]})
        if wall and nd and not 0.18 <= (bshare or 0.0) <= 0.22:
            flags.append({"flag": "breadth_share_outside_0.18_0.22", "detail": bshare})
        if wall:
            self.deepest_history.append((el, deepest))
            old = [d for t, d in self.deepest_history if el - t >= 7200.0]
            if old and deepest is not None and old[-1] is not None and deepest <= old[-1]:
                flags.append({"flag": "deepest_active_level_not_grown_in_2_h", "detail": [old[-1], deepest]})
        mb = (self.sampler.last or {}).get("main_private_mb") if (self.sampler is not None and wall) else None
        soft = float((self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB))["main_private"])
        if mb is not None and float(mb) > 0.8 * soft:
            flags.append({"flag": "memory_above_80pct_of_soft_budget", "detail": [mb, soft]})
        ex_h = max(1e-9, (self.env.now() - self.t_search) / 3600.0)
        rec = {"contract": ORDER_CONTRACT, "at": at, "index": len(self.hourly), "utc": g.utc() if wall else None, "elapsed_s": el if wall else None,
               "dispatches": self.c["dispatches"] if wall else None, "ingested_total": sel.n_ingested,
               "period": {"dispatches": nd, "ingested": int(per["ingested"]), "streams": streams, "breadth_share": bshare},
               "levels": readout, "deepest_active_level": deepest, "rejected": self.pace.rejected.snapshot(), "same_tick": sel.same_tick.snapshot(),
               "milestones": sel.milestones.records(), "rotation": {k: int(v) for k, v in sorted(sel.dstat.items())},
               "claims": self.c["clears_claimed"], "verified": len(verified), "best_verified": int(self.best["completion_input_tick"]),
               "claim_threshold": int(self.order_plan["claim_threshold"]), "memory_main_mb": mb, "jobs_per_h": round(self.c["jobs"] / ex_h, 1) if wall else None,
               "flags": flags, "status": self.status if wall else None, "owner_tables": self.owner_tables()}
        for name in ("milestones",):
            rec[name] = [{k: v for k, v in m.items() if k != "utc"} for m in rec[name]]
        sel.period = rs._new_period()
        self.hourly.append({"at": at, "index": rec["index"], "ingested_total": rec["ingested_total"], "flags": [f["flag"] for f in flags]})
        self.fs.append_jsonl(self.dir / "hourly.jsonl", rec)
        self.hourly_md.append(hourly_md(rec))
        try:
            self.fs.write_text(self.dir / "hourly.md", "# Option D: hourly records\n\n" + "\n".join(reversed(self.hourly_md)), atomic=True)
        except (OSError, g.LabRootError):
            pass
        return rec

    def owner_tables(self) -> Dict[str, Any]:
        """For the owner only, read by no rule (section 7.2): the first target broken (level-1 sets) and the sets in the rotation per level."""
        sel = self.selector
        first: Dict[str, Dict[str, Any]] = {}
        for c in self.archive.cells:
            if c.level == 1 and c.key is not None:
                gone = [i for i in range(osel.TARGETS_TOTAL) if not (int(c.key[3]) >> i) & 1]
                k = str(gone[0]) if gone else "?"
                d = first.setdefault(k, {"cells": 0, "earliest": None})
                d["cells"] += 1
                d["earliest"] = c.tick if d["earliest"] is None else min(d["earliest"], c.tick)
        sets: Dict[str, List[Dict[str, Any]]] = {}
        for lv, ss in sel.rotation_levels().items():
            rows = [{"set": osel.slabel(s), "count": int(sel.set_count[s]), "orders": len(sel.rot_by_set[s]), "earliest": sel._set_first(s)[0]} for s in ss]
            sets[str(lv)] = sorted(rows, key=lambda r: (r["earliest"], r["set"]))[:50]
        return {"first_break": dict(sorted(first.items())), "sets": dict(sorted(sets.items(), key=lambda kv: -int(kv[0])))}

    # -- records -------------------------------------------------------------------------------------------------------------------------------

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        c, p = self.cfg, self.order_plan
        mods = (sys.modules[__name__], osel, C, r3, rs, cs, r2)
        return {"mode": "lab", "contract": ORDER_CONTRACT, "utc": g.utc(), "files_sha256": {Path(m.__file__).name: lf_sha256(Path(m.__file__)) for m in mods},
                "lab_code_digest": self.code_dig, "lab_code_files": len(self.code), "expect_code": c.expect_code,
                "order_code": {"contract": MANIFEST_CONTRACT, "entries": list(ENTRY_MODULES), "digest": self.order_code_dig, "expected": self.order_code_expect,
                               "files": dict(self.order_code)},
                "arm": cs.ARM_NAME, "arm_params": self.arm, "params": self.p.as_dict(), "order_params": self.dp.as_record(), "params_fingerprint": p.get("params_fingerprint"),
                "selection_contract": osel.SELECT_CONTRACT, "key_family": KEY_FAMILY, "archive_id": p["archive_id"], "n_workers": c.n_workers, "max_ticks": c.max_ticks,
                "max_wall_s": c.max_wall_s, "job_timeout_s": c.job_timeout_s, "mismatch_limit": c.mismatch_limit, "lifecycle_limit": c.lifecycle_limit,
                "verify_parallel_close": c.verify_parallel, "max_battleship_processes": fm.MAX_BATTLESHIP, "memory_caps_mb": dict(self.env.caps or fm.CAPS_MB),
                "memory_soft_budget_mb": dict(self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB)), "readiness": ready,
                "readiness_override": self.readiness_use,
                "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY, "backend": self.env.backend, "import": str(Path(c.lab_root) / "import"),
                "root": p["root"], "pace": p["pace"], "milestones": p["milestones"], "gate": p["gate"], "frontier": p["frontier"], "claim_threshold": p["claim_threshold"],
                "sources": p["sources"], "rng_seed": int(self.p.rng_seed),
                "origins": {"root": "two fresh-process tick-0 reads at the open (section 5.1); the tick-0 record is every dispatch's pin",
                            "keep": "the pace line line(L) = (G x L) // 10 + s (tools/frs/order_select.Pace); run 3's keep rule inside it",
                            "selection": "tools/frs/order_select.OrderSelector (section 3; gaps A-F, G1-G5); no trigger draws",
                            "draw_id": f"<archive id>|{KEY_FAMILY}|<prefix words digest>, iteration k = 0.. per representative",
                            "claims": "a clear faster than the frontier's best (read at the plan), then than D's own best, verified twice from tick 0 (run 3)",
                            "milestones": "first kept arrival with at least L targets broken at a tick <= line(L); clear line on the completion input tick; "
                                          "verified at the close by two fresh-process replays (D-Q8)",
                            "rng": "keyed draws (det_schedule), seed --rng-seed; native RNG never read"}}

    def summary(self) -> Dict[str, Any]:
        s = cs.Search.summary(self)
        s["contract"] = ORDER_CONTRACT
        sel = self.selector
        verified = self.verified_clears()
        best = self.best_start if self.claims_frozen else {k: v for k, v in self.best.items() if k != "words"}
        ver = {v["milestone"]: v for v in self.ms_verifications}
        ms = []
        for name in MILESTONE_NAMES:
            row = self.ms_rows.get(name)
            if row is not None:
                v = ver.get(name) or {}
                ms.append(dict({k: x for k, x in row.items() if k != "words_hex"}, verdict=v.get("verdict"), reasons=v.get("reasons")))
        m1 = ver.get("M1") or {}
        s["order"] = {"plan": {k: self.order_plan.get(k) for k in ("archive_id", "key_family", "pace", "milestones", "gate", "params_fingerprint", "claim_threshold")},
                      "frontier": self.order_plan.get("frontier"), "root": self.root, "readiness_override": self.readiness_use,
                      "gate_m1": {"met": "M1" in self.ms_rows, "verified": m1.get("verdict") == M_VERIFIED, "tick": (self.ms_rows.get("M1") or {}).get("tick")},
                      "milestones": ms, "milestone_verifications": list(self.ms_verifications),
                      "best": best, "best_start": self.best_start, "best_history": list(self.best_history), "claims_frozen": self.claims_frozen,
                      "faster_than_frontier": 0 if self.claims_frozen else sum(1 for v in verified if int(v["completion_input_tick"]) < int(self.best_start["completion_input_tick"])),
                      "claims": {"claimed": self.c["clears_claimed"], "replayed": len(self.vrows), "not_replayed": self.c["claims_not_replayed"],
                                 "last_not_replayed": self.not_replayed[-12:]},
                      "end_records": r3.Run3Core.end_record_stats(self),
                      "rejected": self.pace.rejected.summary(), "rejected_reaches": self.c["rejected_reaches"],
                      "selection": None if sel is None else {"contract": osel.SELECT_CONTRACT, "ingested": sel.n_ingested, "streams": dict(sel.cum["streams"]),
                                                             "rotation": {k: int(v) for k, v in sorted(sel.dstat.items())}, "retired_now": len(sel.retired),
                                                             "within_one_violations": sel.within_one_violations(), "levels": sel.level_readout(),
                                                             "same_tick": sel.same_tick.summary(), "moves": int(sel.cnt["moves"])},
                      "niche_live": dict(self.niche_live), "exports": list(self.exports), "text_replays": list(self.text_replays), "hourly_records": list(self.hourly)}
        return s

    def write_summary(self) -> Dict[str, Any]:
        if not self._final_record and self.selector is not None and self.selector.n_ingested:
            self._final_record = True
            try:
                self.write_record("close")
            except Exception as exc:  # noqa: BLE001 - a record, never the close
                self.log(f"the closing record failed: {type(exc).__name__}: {exc}"[:300])
        if self.order_code and "order_code_digest_end" not in self.integrity:
            end = code_digest(order_code_manifest())
            changed = changed_files(self.order_code)
            self.integrity.update({"order_code_digest": self.order_code_dig, "order_code_digest_end": end, "order_code_changed_during_run": changed})
            if end != self.order_code_dig or changed:
                self.mark("SEARCH_INVALID", f"D's code changed during the run: {changed[:6] or 'the imported set changed'}")
        self.integrity["root_equal"] = self.root.get("equal")
        self.integrity["milestones_not_verified"] = [v["milestone"] for v in self.ms_verifications if v["verdict"] != M_VERIFIED]
        if self.sampler is not None:
            self.sampler.stop()
        s = self.summary()
        self.fs.write_text(self.dir / "summary.json", frep.compact_json(s), atomic=True)
        self.fs.write_text(self.dir / "report.md", report_md(s), atomic=True)
        self.fs.write_text(self.dir / "progress.md", progress_md(s, final=True), atomic=True)
        return s

    def write_progress(self) -> None:
        try:
            self.fs.write_text(self.dir / "progress.md", progress_md(self.summary(), final=False), atomic=True)
        except (OSError, g.LabRootError):
            pass


class OrderNight(det.DeterministicSchedule, ra.AnomalyIngest, OrderEngine):
    """Option D: deterministic scheduling (D4), anomaly keeping, D's engine."""

    def continuation_asof(self, reaches: Sequence[Sequence[Any]], seq: int) -> Dict[str, Any]:
        """F3 read with the pace filter (section 4.4): only a reach the pace rule would keep can continue a burst."""
        inside = []
        for j, k in reaches:
            lv = mcell.level_of_mask(int(k[3]))
            if lv >= osel.TARGETS_TOTAL or self.pace.keeps(lv, int(j)):
                inside.append((j, k))
        d = super().continuation_asof(inside, seq)
        d["outside_line"] = len(reaches) - len(inside)
        return d


# -- rendering ----------------------------------------------------------------------------------------------------------------------------------


def _f(x: Any) -> str:
    return frep.fmt(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else ("-" if x is None else str(x))


def hourly_md(rec: Mapping[str, Any]) -> str:
    lines = [f"## Record {rec['index']} ({rec['at']}; {_f(rec.get('elapsed_s'))} s; {_f(rec['ingested_total'])} ingested)", "",
             f"period: {rec['period']['dispatches']} dispatches, streams {json.dumps(rec['period']['streams'])}, breadth share {_f(rec['period']['breadth_share'])}; "
             f"deepest active level {_f(rec['deepest_active_level'])}; claims {rec['claims']}, verified {rec['verified']}; best {rec['best_verified']} "
             f"(threshold {rec['claim_threshold']})", "",
             "| level | line | cells | eligible | active | retired | sets | orders | in draw | dispatched | earliest arrival (vs line) | set counts | order spread | rejected (earliest, +over) |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- | ---: | --- |"]
    rej = rec.get("rejected") or {}
    for lv, d in rec["levels"].items():
        r = rej.get(lv) or {}
        lines.append(f"| {lv} | {d['line']} | {d['cells']} | {d['eligible']} | {d['active']} | {d['retired']} | {d['sets']} | {d['orders']} | {d['in_draw']} | "
                     f"{d['dispatched']} | {_f(d['earliest_arrival'])} ({_f(d['earliest_arrival_vs_line'])}) | {_f(d['set_count_min'])} .. {_f(d['set_count_max'])} | "
                     f"{_f(d['order_spread_max'])} | {r.get('count', 0)} ({_f(r.get('earliest_tick'))}, +{_f(r.get('distance'))}) |")
    for lv, r in sorted(rej.items(), key=lambda kv: -int(kv[0])):
        if lv not in rec["levels"]:
            lines.append(f"| {lv} | | | | | | | | | | | | | {r['count']} ({r['earliest_tick']}, +{r['distance']}) |")
    if rec.get("milestones"):
        lines += ["", "milestones: " + "; ".join(f"{m['milestone']} tick {m.get('tick', m.get('completion_input_tick'))} (line {m['line']}, dispatch {m['n']})"
                                                 for m in rec["milestones"])]
    if rec.get("same_tick"):
        lines += ["", f"same-tick breaks (level reached: ticks, targets): {json.dumps(rec['same_tick'])}"]
    if rec.get("flags"):
        lines += ["", "**flags:** " + "; ".join(f"{f['flag']} {json.dumps(f['detail'], default=str)[:200]}" for f in rec["flags"])]
    return "\n".join(lines) + "\n"


def _summary_lines(s: Mapping[str, Any]) -> List[str]:
    o = s.get("order") or {}
    gm = o.get("gate_m1") or {}
    lines = [f"- status **{s['status']}** ({(s.get('stop') or {}).get('reason')})",
             f"- root equal at the open: {(o.get('root') or {}).get('equal')}; pace lines {json.dumps(((o.get('plan') or {}).get('pace') or {}).get('lines'))}",
             f"- gate M1 (level 6 at or before {((o.get('plan') or {}).get('gate') or {}).get('line')}): met {gm.get('met')}, verified {gm.get('verified')}, tick {_f(gm.get('tick'))}",
             f"- dispatches {_f(s['work']['dispatches'])}, ticks {_f(s['work']['ticks_total'])}, cells {_f(s['archive']['cells'])}, rejected reaches {_f(o.get('rejected_reaches'))}",
             f"- claims {(o.get('claims') or {}).get('claimed')}, verified clears {s['clears']['verified']}, best {_f((o.get('best') or {}).get('completion_input_tick'))} "
             f"(frontier {_f((o.get('best_start') or {}).get('completion_input_tick'))})"]
    for m in o.get("milestones") or []:
        lines.append(f"- {m['milestone']}: tick {m.get('tick')} (line {m['line']}), dispatch {m['n']}, cell {m['cid']}: {m.get('verdict')} {m.get('reasons') or ''}")
    ov = o.get("readiness_override")
    if ov:
        lines.append(f"- readiness: owner override (free commit >= {ov['min_commit_free_mb']} MB instead of the registered {ov['registered_min_commit_free_mb']} MB), "
                     f"applied {ov.get('applied')}, free commit at the open {_f(ov.get('commit_free_mb'))} MB, problems {ov.get('registered_problems') or []}; "
                     f"reason: {ov['reason']}")
    return lines


def progress_md(s: Mapping[str, Any], *, final: bool) -> str:
    return "\n".join([f"# Option D {'report' if final else 'progress'} ({s.get('utc_end')})", ""] + _summary_lines(s)) + "\n"


def report_md(s: Mapping[str, Any]) -> str:
    o = s.get("order") or {}
    lines = ["# Option D: night report", ""] + _summary_lines(s) + ["", "## Rejected reaches (whole night; report-only)", ""]
    for lv, r in (o.get("rejected") or {}).items():
        lines.append(f"- level {lv}: {r['count']} rejected, earliest {r['earliest_tick']} (+{r['distance']} over the line)")
    sel = o.get("selection") or {}
    lines += ["", "## Selection", "", f"- streams {json.dumps(sel.get('streams'))}; rotation {json.dumps(sel.get('rotation'))}",
              f"- within-1 violations at the close: {sel.get('within_one_violations')}", f"- same-tick breaks {json.dumps(sel.get('same_tick'))}",
              "", "## Integrity", "", f"- {json.dumps(s.get('integrity'), default=str)[:1500]}"]
    return "\n".join(lines) + "\n"


# -- the command line ---------------------------------------------------------------------------------------------------------------------------


def order_params_from_args(a: argparse.Namespace) -> osel.OrderParams:
    lw = tuple(float(x) for x in a.level_weights.split(",")) if a.level_weights else osel.OrderParams.level_weights
    p = osel.OrderParams(goal=a.goal, slack=a.slack, level_weights=lw, breadth_share=a.breadth_share, retire_after=a.retire_after)
    p.check()
    return p


def engine_params_from_args(a: argparse.Namespace, dp: osel.OrderParams) -> C.Params3:
    return engine_params(dp, max_segments=a.max_segments, max_cells=a.max_cells, max_dispatches=a.max_dispatches, rng_seed=a.rng_seed,
                         check_slots=a.check_slots, summary_every_s=a.summary_every_s, summary_every_dispatches=a.summary_every_dispatches)


def run_command(lab: Path, frontier: Path, out: Path, a: argparse.Namespace) -> str:
    return (f"python -B tools/frs/order_search.py run --lab-root {Path(lab).as_posix()} --frontier {Path(frontier).as_posix()} --out {Path(out).as_posix()} "
            f"--rng-seed {a.rng_seed} --workers {a.workers} --max-ticks {a.max_ticks} --max-wall-min {a.max_wall_min:g} --summary-every-s {a.summary_every_s:g}"
            + (f" --max-cells {a.max_cells}" if a.max_cells != C.Params3.max_cells else "") + (f" --max-dispatches {a.max_dispatches}" if a.max_dispatches else "")
            + (f" --min-commit-free-mb {a.min_commit_free_mb} --override-reason \"{a.override_reason}\"" if a.min_commit_free_mb is not None else ""))


def cmd_plan(lab: Path, frontier: Path, out: Path, a: argparse.Namespace) -> int:
    dp = order_params_from_args(a)
    ep = engine_params_from_args(a, dp)
    P = plan_and_write(lab, frontier, out, dp, ep, readiness_override=readiness_override_record(a.min_commit_free_mb, a.override_reason))
    if P["readiness_override"]:
        print("readiness override (owner):", json.dumps(P["readiness_override"]))
    print("root:", json.dumps(P["root"]))
    print("pace lines:", json.dumps(P["pace"]["lines"]), "gate:", json.dumps(P["gate"]))
    print("params:", json.dumps(P["params"]), "fingerprint", P["params_fingerprint"][:16])
    print("frontier best (claim threshold):", json.dumps({k: P["frontier"][k] for k in ("completion_input_tick", "completion_time_passed", "dir", "status")}))
    print("D code digest:", P["code"]["digest"][:16], "archive id:", P["archive_id"])
    print(f"wrote {Path(out) / 'plan.json'}")
    print("run with:", run_command(lab, frontier, out, a))
    return 0


def cmd_run(lab: Path, frontier: Path, out: Path, a: argparse.Namespace) -> int:
    import frs_lab as fl
    from m7_runtime import install_kill_on_close_job

    run_dir = Path(out) / "run"
    if run_dir.exists():
        print(f"refused: {run_dir} exists (never overwritten)")
        return 2
    saved = Path(out) / "plan.json"
    if not saved.is_file():
        print(f"refused: no {saved}: run `plan` first")
        return 2
    plan = json.loads(saved.read_text(encoding="utf-8"))
    if plan.get("contract") != ORDER_CONTRACT:
        print(f"refused: {saved} is not a D plan ({plan.get('contract')})")
        return 2
    dp = order_params_from_args(a)
    ep = engine_params_from_args(a, dp)
    bad = run_flag_problems(plan, dp, ep, frontier, readiness_override_record(a.min_commit_free_mb, a.override_reason))
    if bad:
        print(f"refused: {bad}")
        return 2
    install_kill_on_close_job()
    imp = Path(lab) / "import"
    frozen = json.loads((imp / "frozen_runtime.json").read_text(encoding="utf-8"))
    cfg = cs.SearchConfig(lab_root=Path(lab), out=Path(out), run_dir=run_dir, frontier_dir=Path(frontier), n_workers=a.workers, max_ticks=a.max_ticks,
                          max_wall_s=60.0 * a.max_wall_min, expect_code=None)
    text = rx.make_text_replay(imp / "exe" / "BattleShip.exe", run_dir / "text_replays", frozen)
    eng = OrderNight(cfg, fl.real_env(Path(lab), run_dir), engine_plan(plan, ep), ep, order_params=dp, text_replay=text,
                     anomaly_build={"exe_sha256": frozen["exe_copy_sha256"].get("BattleShip.exe"), "platform": sys.platform})
    eng.readiness_override = plan.get("readiness_override")
    code = eng.run()
    print(f"exit {code}: {run_dir / 'report.md'} (progress: {run_dir / 'progress.md'}, hourly: {run_dir / 'hourly.md'})")
    return code


def run_flag_problems(plan: Mapping[str, Any], dp: osel.OrderParams, ep: C.Params3, frontier: Path,
                      readiness_override: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """`run` takes exactly the plan's parameters, frontier and readiness override (U10, as run 3): a flag that differs is refused, plan again."""
    if plan.get("readiness_override") != (None if readiness_override is None else dict(readiness_override)):
        return f"the readiness override differs from the saved plan's ({plan.get('readiness_override')}): plan again with the same flags"
    if plan.get("params") != dp.as_record():
        return f"the selection parameters differ from the saved plan's ({plan.get('params')}): plan again with the same flags"
    if plan.get("engine_params") != ep.as_dict():
        return "the engine parameters (segments, caps, seed, records) differ from the saved plan's: plan again with the same flags"
    fb = read_frontier_best(frontier)
    if g.norm(Path(fb["dir"])) != g.norm(Path(plan["frontier"]["dir"])) or fb["summary_sha256"] != plan["frontier"]["summary_sha256"]:
        return "the frontier folder or its summary differs from the one read at the plan: plan again"
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=("plan", "run"))
    ap.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
    ap.add_argument("--frontier", required=True, help="the frontier chain's latest run 3 folder: only its best verified clear is read (the claim threshold)")
    ap.add_argument("--out", default=None, help="default <lab root>/order_<date>")
    ap.add_argument("--rng-seed", type=int, required=True)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--goal", type=int, default=osel.OrderParams.goal)
    ap.add_argument("--slack", type=int, default=osel.OrderParams.slack)
    ap.add_argument("--level-weights", default="", help="comma list, deepest level first (default 0.4,0.3,0.2,0.1)")
    ap.add_argument("--breadth-share", type=float, default=osel.OrderParams.breadth_share)
    ap.add_argument("--retire-after", type=int, default=osel.OrderParams.retire_after)
    ap.add_argument("--max-segments", type=int, default=C.Params3.max_segments)
    ap.add_argument("--check-slots", type=int, default=C.Params3.check_slots)
    ap.add_argument("--summary-every-s", type=float, default=C.Params3.summary_every_s)
    ap.add_argument("--summary-every-dispatches", type=int, default=C.Params3.summary_every_dispatches)
    ap.add_argument("--max-cells", type=int, default=C.Params3.max_cells)
    ap.add_argument("--max-dispatches", type=int, default=C.Params3.max_dispatches)
    ap.add_argument("--max-ticks", type=int, default=cs.SearchConfig.max_ticks)
    ap.add_argument("--max-wall-min", type=float, default=480.0)
    ap.add_argument("--min-commit-free-mb", type=int, default=None,
                    help="owner override: the free-commit minimum at the open for this folder only (default: the registered rule); needs --override-reason")
    ap.add_argument("--override-reason", default="", help="the owner's reason for --min-commit-free-mb (recorded in the plan, config and summary)")
    a = ap.parse_args(argv)
    try:
        lab = g.validate_lab_root(Path(a.lab_root))
        out = g.validate_run_dir(Path(a.out) if a.out else lab / f"{FOLDER_PREFIX}{dt.date.today().isoformat()}", lab)
        frontier = g.validate_run_dir(Path(a.frontier), lab)
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    if g.norm(out) == g.norm(frontier) or g.under(g.norm(out), g.norm(frontier)) or g.under(g.norm(frontier), g.norm(out)):
        raise SystemExit("refused: the output folder and the frontier folder overlap (the frontier is read only)")
    if not out.name.startswith(FOLDER_PREFIX):
        raise SystemExit(f"refused: D's folder name starts with {FOLDER_PREFIX!r}")
    if not 1 <= a.workers <= 5:
        raise SystemExit("refused: 1 to 5 workers (one standby each: at most 10 game processes)")
    if not 1 <= a.check_slots <= a.workers:
        raise SystemExit("refused: --check-slots is 1 to --workers")
    if a.max_ticks < 1 or a.max_wall_min <= 0:
        raise SystemExit("refused: --max-ticks and --max-wall-min are positive")
    try:
        engine_params_from_args(a, order_params_from_args(a))
        readiness_override_record(a.min_commit_free_mb, a.override_reason)
    except (SearchError, osel.OrderParamsError) as exc:
        raise SystemExit(str(exc))
    if not (lab / "import" / "import_manifest.json").is_file():
        raise SystemExit("refused: no lab import (rl/frs_lab.py import first)")
    g.LabGuard.install(lab)
    lock = g.LabLock(lab, f"order_search {a.command}")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    try:
        if a.command == "plan":
            return cmd_plan(lab, frontier, out, a)
        return cmd_run(lab, frontier, out, a)
    except (SearchError, osel.OrderParamsError) as exc:
        print(str(exc))
        return 3
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
