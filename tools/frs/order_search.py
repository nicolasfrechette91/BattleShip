#!/usr/bin/env python3
"""Option D search: order discovery from tick 0 (docs/frs_option_d_design_2026-11-11.md, decided by the owner on 2026-11-12; build phase
2). Built on run 3's engine (tools/frs/run3_search.py, tools/frs/crossing_search_run3.py) by import and subclassing; no run 3 file is edited.

    root            one tick-0 root (section 5.1). At the open two fresh processes each reach tick 0 with no input word
                    (rl/m8_rd_worker.run_tick0 on run 3's workers, no pin): their tick-0 records (every observation field but
                    host_frame, the record digest, the chain start, the record lines), cell keys and live masks must be equal, else
                    SEARCH_INVALID. The root is level 0, mask 1023, niche (1023, ()), empty prefix; its end record is the tick-0
                    observation (stored, so no dispatch is fused) and the tick-0 record is the pin of every later dispatch, each one a
                    fresh process from tick 0.
    keep            the arrival rule (tools/frs/order_select.Pace, order_select_v2, owner 2026-11-16): a reach at level L < 10 with input
                    tick t whose L-th break came at a is kept only if a <= line(L) and t <= line(L + 1); otherwise it is not kept (the
                    BEYOND verdict) and counts in the rejected-reach readout (report-only); everything else is run 3's keep rule. A
                    reach's break ticks are the job's own (`breaks_all`: the prefix replay's and the burst's), so the rule reads nothing
                    but the trajectory. Every kept cell's origin records them (`d_breaks`, [[tick, target], ...]).
    open line       (owner 2026-11-18, order_select_v4; --open-line-from K, default off = the rule above exactly) a reach with K or more
                    targets broken whose K-th break came at or before line(K) is also kept, whatever its later breaks and its own tick;
                    the archive's own bound (crossing_search.Archive.keep, line(10) without the option) is then the horizon, so no line
                    applies to its tick. The keep, the draw's eligibility, the continuation, the resume and the extent's "inside" read
                    the rule with the option; the milestones do not. With the option the levels >= K are one draw group (owner
                    2026-11-19, order_select_v6): the deepest level's weight in the level draw, the fewest dispatches over all its cells,
                    ties to the deeper level, then the earlier tick, then the cell id (order_select).
    fall cut        (owner 2026-11-19, order_select_v5; v6: grounded states spared; --fall-cut-y Y, needs --open-line-from K, default off
                    = no change) at levels >= K an in-night reach whose position y is below Y and whose key's resource class is not G,
                    inside the rule above, is not kept (the BEYOND verdict, as a rule rejection) and counts in the fall-cut readout
                    (report-only; the grounded reaches below Y it spares are counted too); such a cell is not drawable, so an inherited
                    one stays in the archive (it holds its key) undrawable. The reach records (deep reaches, extent, break record) keep
                    every reach; the continuation, the resume's set, the milestones and levels below K are unchanged.
                    v7 (owner 2026-11-20; --fall-cut-spare-one-live, needs --fall-cut-y, default off): the cut does not apply to a state
                    with exactly one live target (level 9), whose next break is the clear; such a reach below Y is kept by the rules
                    above whatever its class, counted as spared (one_live).
    record bound    (owner 2026-11-20, order_select_v7; --record-bound B, needs --open-line-from K, default off = the archive's own bound
                    only) at levels >= K an in-night reach whose own tick is B or later, inside the arrival rule, is not kept (the BEYOND
                    verdict, as a rule rejection; deep reaches reason record_bound) and counts in the bound's readout (report-only); such a
                    cell is not drawable, so an inherited one stays in the archive undrawable (the plan counts them per level). A burst
                    stops at its first boundary whose state is at a level >= K at a tick >= B (the continuation below, Pace.continues).
                    Clears and claims are unchanged: a clear's reach is level 10 and terminal (never kept), the claim comes from the
                    job's outcome. The bound is checked before the fall cut (a reach past B is counted by the bound only).
    direction key   (owner 2026-11-20, order_select_v7; --floor-direction-key, default off = today's keys) a state grounded on a floor
                    line that moves (rl/m7g_spatial.EXPECTED_LINES: the floor lines of the moving platform's group, PLATFORM_GROUP; line
                    19) gets the platform's direction of motion at the state's tick in its key, at every level: the key's floor field is
                    the line id + 1000 when the platform moves up, + 2000 when it moves down (the frozen archive keeps five key fields,
                    frs_archive.norm_key; native line ids are below 32). The direction is a function of the tick (PLATFORM_PERIOD,
                    PLATFORM_DOWN: the agent's own platform motion, measured in its traces). Other keys are unchanged. The main process
                    applies it to every reach before the keep rule and to every inherited cell at the resume (re-keyed from its tick;
                    idempotent; with the option off an encoded floor field is read back as the plain line id). LIMIT (owner 2026-11-20,
                    accepted): the frozen worker (rl/frs_worker.run_iterate_frs) reports a reach only at the first visit of its
                    FIVE-FIELD key in a burst, so a burst that comes back to the same five-field key after the platform changed direction
                    reports nothing for it, and that state is never keyed here. A new height bucket is a first visit (it gets its
                    direction), and another burst reaching the bucket while the platform moves the other way gets its own key.
    continuation    (owner 2026-11-16, replaces F3) at every 120-word boundary a burst continues while the episode is live (the worker
                    asks only then) and the state at the boundary is inside the arrival rule, up to max_segments x 120 = 720 words. D's
                    jobs carry a boundary window of one segment (the arm's window = segment_words), so each boundary question holds all
                    the reaches of its segment; the main process follows the job's mask through them (a break is always a first visit
                    of a new key) and answers from the job's own trajectory only (no archive state: deterministic). At the ingest each
                    recorded answer is recomputed from the job's exact break ticks; a disagreement is counted (`cont_mismatches`).
    resume          (owner 2026-11-16) --resume-from <D folder>, repeatable: every final representative of the folders (all levels,
                    any retirement state) with its words, end record, chain and niche, and its break ticks from the folder's own
                    lineage; a cell outside this night's arrival rule is dropped; the rest enter through the archive's keep rule at the
                    open, in tick order, ties in the order the folders are given (a new key is a new cell, a strictly earlier tick
                    replaces, an equal or later tick is dropped as later). The selector's counts and the retirement counts start from
                    zero. The folders' root must equal this night's root. Inherited cells meet no milestone (in-night arrivals only).
                    With --resume-child (owner 2026-11-21, default off = the derivation in the main process, as before) the plan and the
                    open run the same derivation (resume_selection: the same folders, arrival rule and key options) in a child Python
                    process that pickles the insertion sequence and the record back through its stdout and exits; at the open it runs
                    where the in-process derivation did, before the workers start, and the main process drops the sequence once it is
                    inserted. The inherited cells, keys, ticks, records and the set digest are the in-process derivation's; only the main
                    process's memory changes (the derivation's ~2 GB on 9 folders is the child's and leaves with it).
    scoreboard      (owner 2026-11-16) a fixed close record in summary.json (order.scoreboard) and report.md; report-only.
    extent          (owner 2026-11-16, report-only) every dispatch row's `extent`: per level and target set the burst was at, over every
                    reach the main process received (rejected ones included), the highest y, the lowest x and the highest x, each with
                    its tick, for all reaches and for those inside the keep window. Read by no rule: nothing kept or drawn changes.
    break record    (E1, owner 2026-11-18, report-only) every dispatch row's `break_record`: per credited break (after the start tick)
                    its tick, target, level, Mario's position and what the job result carries for that tick (the reach: 17 observation
                    fields, key, terminal flag, record digest, chain; None without a reach). Read by no rule.
    hitter record   (owner 2026-11-19, report-only; --hitter-record, default off = no change at all: run 3's pool and worker, no field) the
                    search workers are tools/frs/order_worker.OrderPool with SSB64_RL_ENTITY=1; its proxy, below run 3's, reads the entity
                    object of every reply and hands the reply on without it (run 3's observer, detectors and the worker see an entity-off
                    reply). Every break_record entry gains hitter, hitter_serial, hitter_owner, hitter_first_tick, hitter_weapon_kind,
                    hitter_candidates, hitter_why and hitter_evidence (order_worker.HITTER_RULE: mario / projectile / unseen / ambiguous /
                    unavailable); the scoreboard's break attribution counts the kinds. Read by no rule: keep, draw, retirement, credit,
                    milestones and cell keys are the option-off night's.
    selection       tools/frs/order_select.OrderSelector (section 3; gaps A-F, G1-G5). No trigger draws.
    claims          a clear faster than the frontier's best verified clear, read at the plan, is verified twice from tick 0, as run 3
                    (then against D's own best); exports and native text replays of new bests as run 3.
    milestones      M1 ... M4 and the clear line (section 8, gap E; arrival rule; v3: the L-th break must happen during one of the night's
                    bursts, so a break inherited in a resumed cell's prefix never counts; each cell carries the tick up to which its
                    lineage is inherited), recorded at their first occurrence (milestones.jsonl) and verified at the close by two fresh-process replays of the kept cell's words with the verify flags: both must show
                    at least L targets broken by the recorded tick (the L-th break's) and the recorded chain (D-Q8). Only the first
                    arrival per milestone; no fallback. A disagreement is SEARCH_INVALID (the night is not a test of M1); a verified
                    prefix is exported as a .btt.txt (section 7.3).
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
    memory          run 3's sampler and caps (rl/frs_machine.Sampler), but D's own process-tree snapshot (d_tree_snapshot, owner
                    2026-11-13): a process counts as a child only if it was created at or after its parent, so a run process that reuses
                    a dead parent's PID does not adopt that parent's orphans (the pilot's false memory-cap stop, session log 20.5).

    python -B tools/frs/order_search.py plan --lab-root C:/BattleShip_lab --frontier DIR --rng-seed 11 [--out DIR] [--resume-from DIR ...] ...
    python -B tools/frs/order_search.py run  --lab-root C:/BattleShip_lab --frontier DIR --rng-seed 11 --out DIR --workers 5 --max-wall-min 480
                                              [--resume-from DIR ...]

`plan` is zero native ticks; `run` is native. Writes only under the output folder (`order_*`) through the lab's guard; takes the lab lock, so
D and the frontier never run together; nothing reads native RNG. Zero-tick tests: tools/frs/order_search_tests.py. Run with python -B.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pickle
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Mapping as ABCMapping
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

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
import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_machine as fm  # noqa: E402
import frs_report as frep  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_verify as fv  # noqa: E402
import frs_worker as fw  # noqa: E402
import m7g_spatial as msp  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import order_select as osel  # noqa: E402
import order_worker as ow  # noqa: E402
import run3_anomaly as ra  # noqa: E402
import run3_dseeds as ds  # noqa: E402
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
RESUME_CONTRACT = "order_resume_v1"
RESUME_KIND = "resume"
DEEP_REACH_LEVEL = 7                   # owner 2026-11-16: every reach at level 7 or deeper, kept or not, is logged (deep_reaches.jsonl)
M1_REFERENCE_SLACK = osel.OrderParams.slack   # owner 2026-11-16: M1 also shown at the decided D-Q1 slack (120: line(6) = 408), report-only
CONT_RULE = ("at a segment boundary (n a multiple of segment_words, the episode live): continue iff the state at the boundary is inside the "
             "arrival rule (its level-L break at or before line(L), its tick at or before line(L + 1)); the boundary window is one segment, "
             "so the main process follows the job's mask through every reach; at most max_segments segments")


def cont_rule(pace: osel.Pace) -> str:
    """The continuation rule's text; v7 (owner 2026-11-20): with the record bound, the stop at the first boundary past it."""
    if pace.bound is None:
        return CONT_RULE
    return (CONT_RULE + f"; v7 (owner 2026-11-20): and, when the state at the boundary is at a level >= {pace.open_from}, the boundary tick is "
                        f"below the record bound {pace.bound} (a burst stops at its first boundary at a tick >= {pace.bound})")


OBS_GROUND = mcell.OBS_INDEX["ground_air_state"]
OBS_STATUS = mcell.OBS_INDEX["fighter_status_id"]
OBS_X, OBS_Y = mcell.OBS_INDEX["position_x"], mcell.OBS_INDEX["position_y"]
if osel.GROUNDED != mcell.RES_GROUNDED:                  # the fall cut's grounded exception reads the cell key's resource class (v6)
    raise ImportError(f"order_select.GROUNDED {osel.GROUNDED!r} is not m8_rd_cells.RES_GROUNDED {mcell.RES_GROUNDED!r}")
EXTENT_GROUPS = ("all", "inside")

# -- the moving-floor direction key (owner 2026-11-20, order_select_v7; --floor-direction-key) ------------------------------------------
# The floor lines that move: the stage table's floor lines in the moving platform's group (rl/m7g_spatial: group 2 is the platform's DObj).
MOVING_FLOOR_LINES: Tuple[int, ...] = tuple(sorted(int(ln[0]) for ln in msp.EXPECTED_LINES
                                                   if int(ln[1]) == msp.LINE_FLOOR and int(ln[2]) == msp.PLATFORM_GROUP))
# The platform's direction of motion is a function of the input tick: period 300 ticks (owner 2026-11-20); it moves down on the ticks t
# with 90 <= t mod 300 < 240 and up on every other tick. Measured in the agent's own traces: the sign of the platform group's speed y
# (spatial groups[2].speed[1]) in every step of the 28 D milestone traces in the lab (12,834 ticks, no mismatch, no tick with speed 0;
# step 0 of the night-6 build, C:/BattleShip_lab/analysis/night6_step0_2026-11-20).
PLATFORM_PERIOD = 300
PLATFORM_DOWN = (90, 240)                                # [first, last + 1) residues of the descent
DIR_UP, DIR_DOWN = "up", "down"
DIR_FLOOR_OFFSET = {DIR_UP: 1000, DIR_DOWN: 2000}        # the key's floor field: line id + offset (native line ids are 0 ... 31)
if not MOVING_FLOOR_LINES or max(MOVING_FLOOR_LINES) >= min(DIR_FLOOR_OFFSET.values()) or len(msp.EXPECTED_LINES) > msp.MAX_LINES:
    raise ImportError(f"the moving floor lines {MOVING_FLOOR_LINES} do not fit the direction key's floor field")


def platform_direction(tick: int) -> str:
    """The moving platform's direction of motion at an input tick (up or down)."""
    r = int(tick) % PLATFORM_PERIOD
    return DIR_DOWN if PLATFORM_DOWN[0] <= r < PLATFORM_DOWN[1] else DIR_UP


def plain_floor(floor: int) -> int:
    """A key's floor field without the direction: the line id (an unencoded field, -1 included, is returned as it is)."""
    f = int(floor)
    return f % 1000 if f >= 1000 else f


def direction_key(key: Sequence[Any], tick: int, on: bool, lines: Optional[Sequence[int]] = None) -> Tuple[Any, ...]:
    """The cell key with the moving floor's direction (on): a grounded key (class G) whose floor field is a moving line (`lines`, default
    MOVING_FLOOR_LINES read at the call) gets the line id + 1000 (up) or + 2000 (down) at `tick`; every other key is unchanged. Off: the
    plain key (an encoded floor field read back as its line id, so a folder written with the option resumes into a night without it under
    today's keys). Deterministic and idempotent."""
    k = fa.norm_key(key)
    f = plain_floor(k[4])
    if on and k[2] == mcell.RES_GROUNDED and f in tuple(int(x) for x in (MOVING_FLOOR_LINES if lines is None else lines)):
        f += DIR_FLOOR_OFFSET[platform_direction(tick)]
    return (k[0], k[1], k[2], k[3], f)


def direction_key_record(lines: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """The direction key's definition, recorded in the plan when the option is on; the run refuses another definition."""
    lines = MOVING_FLOOR_LINES if lines is None else lines
    return {"contract": "order_floor_direction_v1", "lines": [int(x) for x in lines], "period": PLATFORM_PERIOD,
            "down_residues": [PLATFORM_DOWN[0], PLATFORM_DOWN[1] - 1], "floor_field": {"up": "line + 1000", "down": "line + 2000"},
            "source": "lines: rl/m7g_spatial.EXPECTED_LINES floor lines of PLATFORM_GROUP; direction: the sign of the platform group's speed y "
                      "per input tick in the agent's own traces (28 D milestone traces, 12,834 ticks)",
            "limit": "the frozen worker reports a reach at the first visit of its five-field key in a burst: a revisit of the same five-field key "
                     "after the platform changed direction is not reported, so it is never keyed (owner 2026-11-20: partial version accepted)"}


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


# -- D's process-tree snapshot (owner 2026-11-13, fix A) -------------------------------------------------------------------------------------
# rl/frs_machine.tree_snapshot finds descendants by parent PID alone. An orphan keeps its dead parent's PID, and Windows reuses PIDs, so a
# process of the run given that PID adopts the orphan and its whole subtree: in the boot of 2026-11-12, csrss and wininit (dead parent 912)
# and every service under them, about 180 processes and 5 GB, which stopped the pilot on the registered working-set cap (session log 20.5).
# D's snapshot keeps a child only if its creation time is known and not earlier than its parent's; the rest of the record is run 3's.


def guarded_tree(root: int, parent_of: Mapping[int, int], created: Callable[[int], Optional[int]]) -> List[int]:
    """The root and its descendants by parent PID, a child kept only if created(child) is known and >= created(parent). The root is always
    in the list; when its own creation time is unknown nothing is adopted under it (a process that cannot be read is not counted)."""
    children: Dict[int, List[int]] = {}
    for pid, ppid in parent_of.items():
        if pid != ppid:
            children.setdefault(int(ppid), []).append(int(pid))
    times: Dict[int, Optional[int]] = {}

    def t(pid: int) -> Optional[int]:
        if pid not in times:
            times[pid] = created(pid)
        return times[pid]

    tree: List[int] = []
    seen = set()
    stack = [int(root)]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        tree.append(p)
        tp = t(p)
        if tp is None:
            continue
        for c in children.get(p, []):
            if c not in seen:
                tc = t(c)
                if tc is not None and tc >= tp:
                    stack.append(c)
    return tree


def d_tree_snapshot(root_pid: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """rl/frs_machine.tree_snapshot's record (same keys, same memory sums, same system figures) over guarded_tree instead of the bare
    parent-PID walk. None off Windows or on failure, as run 3's."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        k32 = fm._k32()
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE)]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE)]
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)
        if snap in (None, wintypes.HANDLE(-1).value, -1):
            return None
        parent_of: Dict[int, int] = {}
        name_of: Dict[int, str] = {}
        try:
            pe = PE()
            pe.dwSize = ctypes.sizeof(PE)
            ok = k32.Process32FirstW(snap, ctypes.byref(pe))
            while ok:
                parent_of[int(pe.th32ProcessID)] = int(pe.th32ParentProcessID)
                name_of[int(pe.th32ProcessID)] = str(pe.szExeFile)
                ok = k32.Process32NextW(snap, ctypes.byref(pe))
        finally:
            k32.CloseHandle(snap)

        def created(pid: int) -> Optional[int]:
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                return None
            try:
                ft = [wintypes.FILETIME() for _ in range(4)]
                if not k32.GetProcessTimes(h, *[ctypes.byref(x) for x in ft]):
                    return None
                return (int(ft[0].dwHighDateTime) << 32) | int(ft[0].dwLowDateTime)
            finally:
                k32.CloseHandle(h)

        root = int(root_pid if root_pid is not None else os.getpid())
        tree = guarded_tree(root, parent_of, created)
        priv = ws = main = 0.0
        for pid in tree:
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                continue
            try:
                pmc = fm._PMC()
                pmc.cb = ctypes.sizeof(fm._PMC)
                if k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    priv += pmc.PrivateUsage / 2 ** 20
                    ws += pmc.WorkingSetSize / 2 ** 20
                    if pid == root:
                        main = pmc.PrivateUsage / 2 ** 20
            finally:
                k32.CloseHandle(h)
        mem = fm.memory_status() or {}
        return {"main_private_mb": round(main, 1), "tree_private_mb": round(priv, 1), "tree_working_set_mb": round(ws, 1),
                "processes": len(tree), "battleship": sum(1 for p in tree if name_of.get(p, "").lower() == "battleship.exe"),
                "system_available_mb": round(mem.get("available_mb", 0.0), 1), "system_commit_free_mb": round(mem.get("commit_free_mb", 0.0), 1)}
    except Exception:  # noqa: BLE001 - a measurement fault is reported as no sample, never raised into the run (as run 3's)
        return None


def sampler_snapshot(env_snapshot: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    """D's snapshot in place of run 3's real one; any other (a test's injected snapshot) is kept."""
    return d_tree_snapshot if env_snapshot is fm.tree_snapshot else env_snapshot


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


# -- resume from D's own folders (owner 2026-11-16; zero native ticks) ------------------------------------------------------------------------
# The ruling: D may resume from its own folders; the selector's counts and the retirement counts start from zero; a cell outside this
# night's arrival rule is dropped; the rest enter through the archive's keep rule. Nothing here reads a coordinate, target id or route as a
# preference: a cell's niche and break ticks are records of its own trajectory.

RESUME_FILES = ("plan.json", "run/root.json", "run/summary.json", "run/cells.jsonl", "run/dispatches.jsonl")


def _jsonl(p: Path) -> Any:
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                yield json.loads(ln)


def break_pairs(x: Any) -> Tuple[Tuple[int, int], ...]:
    """[[tick, target], ...] as a sorted tuple of (tick, target) pairs (ties on one tick by target label, run 3's order)."""
    return tuple(sorted((int(t), int(i)) for t, i in (x or ())))


def resume_folder(d: Path) -> Dict[str, Any]:
    """A D folder admitted as a resume source: run3_dseeds' admission (contract, lab mode, a clean status, a clean integrity record: no guard
    violation, prefix mismatch, tick-0 inequality or game left, root equal, D's code unchanged during the run, every recorded milestone
    verified) except its verified-M1 condition, which belongs to the hand-off and not to a resume; plus its tick-0 root."""
    d = Path(d)
    rec = ds.read_d_folder(d, accepted=[d])            # every admission problem is listed, none raised; the resume's own rule is applied here
    probs = [p for p in rec["admission_problems"] if p != "M1 not verified"]
    if probs:
        raise SearchError(f"refused: the D folder {d} is not admitted as a resume source ({'; '.join(probs)})")
    missing = [f for f in RESUME_FILES if not (d / f).is_file()]
    if missing:
        raise SearchError(f"refused: the D folder {d} lacks {missing}")
    root = json.loads((d / "run" / "root.json").read_text(encoding="utf-8"))
    reads = root.get("reads") or []
    if root.get("equal") is not True or not reads or not reads[0].get("digest") or not reads[0].get("chain") or not reads[0].get("key"):
        raise SearchError(f"refused: the D folder {d} records no equal tick-0 root")
    return {"dir": str(d), "archive_id": rec["archive_id"], "status": rec["status"], "utc_start": rec["utc_start"], "utc_end": rec["utc_end"], "m1": rec["m1"],
            "admission_problems_ignored": [p for p in rec["admission_problems"] if p not in probs],
            "selection_contract": (rec["plan"] or {}).get("selection_contract"), "pace": (rec["plan"] or {}).get("pace"),
            "root": {"digest": reads[0]["digest"], "chain": reads[0]["chain"], "key": list(reads[0]["key"])},
            "files_sha256": {f: g.sha256_file(d / f) for f in RESUME_FILES}}


class LineageIndex:
    """Every kept row's order niche and break pairs (tick, target) from its folder's own lineage. The tick-0 root has none. A burst row has
    its parent representative's (found by parent_digest) plus its dispatch's breaks at or before its tick, which must be exactly the
    targets the parent's mask has and the row's has not; the niche is run 3's child_niche of the parent's. A resumed row (origin kind
    `resume`) carries its own niche and break pairs. A row that records its break pairs (origin d_breaks, this build on) must agree."""

    def __init__(self, rows: Sequence[Mapping[str, Any]], dispatch_breaks: Mapping[int, Sequence[Sequence[int]]]):
        self.bydig: Dict[str, Mapping[str, Any]] = {}
        for r in rows:
            self.bydig.setdefault(str(r["digest"]), r)
        self.disp = dispatch_breaks
        self.memo: Dict[str, Tuple[rs.Niche, Tuple[Tuple[int, int], ...]]] = {}

    def of(self, r: Mapping[str, Any]) -> Tuple[rs.Niche, Tuple[Tuple[int, int], ...]]:
        path: List[Mapping[str, Any]] = []
        cur: Optional[Mapping[str, Any]] = r
        base: Optional[Tuple[rs.Niche, Tuple[Tuple[int, int], ...]]] = None
        while cur is not None:
            dg = str(cur["digest"])
            if dg in self.memo:
                base = self.memo[dg]
                break
            o = cur.get("origin") or {}
            kind = o.get("kind")
            if kind == "root":
                if int(cur["key"][3]) != osel.ROOT_MASK or int(cur["tick"]) != 0:
                    raise SearchError(f"cell {cur.get('cid')}: a root row that is not the tick-0 root ({cur['key']}, tick {cur['tick']})")
                base = self.memo[dg] = (rs.seed_niche(osel.ROOT_MASK), ())
                break
            if kind == RESUME_KIND:
                base = self.memo[dg] = (rl3.niche_of_label(o["niche"]), break_pairs(o.get("d_breaks")))
                break
            if kind != "burst":
                raise SearchError(f"cell {cur.get('cid')}: origin kind {kind!r} is not root, burst or resume")
            path.append(cur)
            pd = o.get("parent_digest")
            nxt = self.bydig.get(str(pd)) if pd else None
            if nxt is None:
                raise SearchError(f"cell {cur.get('cid')}: its parent representative {str(pd)[:16]} is not among the folder's rows")
            cur = nxt
        assert base is not None
        niche, pairs = base
        for row in reversed(path):
            o = row["origin"]
            prev = osel.mask_of_order(niche)
            m = int(row["key"][3])
            new = break_pairs([(t, i) for t, i in (self.disp.get(int(o["n"])) or []) if int(t) <= int(row["tick"])])
            gone = sorted(i for i in range(osel.TARGETS_TOTAL) if (prev >> i) & 1 and not (m >> i) & 1)
            if m & ~prev or sorted(i for _t, i in new) != gone:
                raise SearchError(f"cell {row.get('cid')}: dispatch {o['n']}'s breaks {list(new)} are not the targets its mask lost {gone}")
            niche = rs.child_niche(niche, m, int(row["tick"]), [[t, i] for t, i in new])
            pairs = break_pairs(pairs + new)
            if o.get("d_breaks") is not None and break_pairs(o["d_breaks"]) != pairs:
                raise SearchError(f"cell {row.get('cid')}: its recorded break ticks {o['d_breaks']} are not its lineage's {list(pairs)}")
            self.memo[str(row["digest"])] = (niche, pairs)
        return niche, pairs


def resume_candidates(d: Path, rec: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every final representative of an admitted D folder (all levels, any retirement state; the tick-0 root aside), each checked: its words
    give its tick and words digest, its key's level is its level, it has its end record, end-record digest and chain, its niche from the
    folder's own lineage is the recorded one and starts at the tick-0 root, and it carries one break tick per target broken."""
    d = Path(d)
    rows: List[Dict[str, Any]] = []
    for i, r in enumerate(_jsonl(d / "run" / "cells.jsonl")):
        if r.get("ev") not in (cs.NEW, cs.REPLACED):
            continue
        if not r.get("key") or r.get("words_hex") is None or not r.get("digest"):
            raise SearchError(f"refused: {d} cells.jsonl row {i + 1}: not a kept representative with its key, words and digest")
        rows.append(r)
    disp = {int(x["n"]): list(x.get("breaks_after_start") or []) for x in _jsonl(d / "run" / "dispatches.jsonl")
            if x.get("kind", "burst") == "burst" and x.get("n") is not None}
    final: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        final[int(r["cid"])] = r
    lx = LineageIndex(rows, disp)
    cands: List[Dict[str, Any]] = []
    roots = 0
    for cid in sorted(final):
        r = final[cid]
        if (r.get("origin") or {}).get("kind") == "root":
            roots += 1
            continue
        level, tick = int(r["level"]), int(r["tick"])
        k = fa.norm_key(r["key"])
        words = bytes.fromhex(r["words_hex"])
        if level >= osel.TARGETS_TOTAL or mcell.level_of_mask(k[3]) != level:
            raise SearchError(f"refused: {d} cell {cid}: level {level} / key level {mcell.level_of_mask(k[3])}")
        if len(words) != tick or mcell.words_digest(words) != r["digest"]:
            raise SearchError(f"refused: {d} cell {cid}: its words do not give its tick and words digest")
        end = r.get("end")
        if not isinstance(end, list) or len(end) != len(mcell.OBS_FIELDS):
            raise SearchError(f"refused: {d} cell {cid}: no 17-field end record")
        if len(bytes.fromhex(str(r.get("end_digest") or ""))) != 32 or len(bytes.fromhex(str(r.get("chain") or ""))) != 32:
            raise SearchError(f"refused: {d} cell {cid}: no end-record digest or chain")
        niche, pairs = lx.of(r)
        label = rs.niche_label(niche)
        if label != r.get("niche") or not label.startswith(f"{osel.ROOT_MASK}:"):
            raise SearchError(f"refused: {d} cell {cid}: its niche from the folder's own lineage {label} is not the recorded {r.get('niche')}")
        if len(pairs) != level:
            raise SearchError(f"refused: {d} cell {cid}: {len(pairs)} break ticks at level {level}")
        cands.append({"folder": str(d), "d_archive_id": rec["archive_id"], "d_cid": cid, "digest": r["digest"], "key": list(k), "level": level, "tick": tick,
                      "words_hex": r["words_hex"], "end": list(end), "end_digest": r["end_digest"], "chain": r["chain"], "niche": label,
                      "breaks": [list(p) for p in pairs]})
    rep = {"dir": str(d), "rows": len(rows), "finals": len(final), "roots_skipped": roots, "candidates": len(cands), "dispatches": len(disp),
           "per_level": dict(sorted(Counter(str(c["level"]) for c in cands).items(), key=lambda kv: int(kv[0])))}
    return cands, rep


def _lr(level: Any, res: Any) -> str:
    return f"{int(level)}|{res}"


def resume_finals(seq: Sequence[Mapping[str, Any]]) -> Dict[Tuple[Any, ...], Mapping[str, Any]]:
    """The resume's final representative per key (the archive's keep rule, mirrored), under the keys the night keeps them by (v7: the
    sequence entry's key; an entry without one, its candidate's plain key)."""
    final: Dict[Tuple[Any, ...], Mapping[str, Any]] = {}
    for e in seq:
        final[tuple(e["key"]) if "key" in e else fa.norm_key(e["cand"]["key"])] = e["cand"]
    return final


RESUME_CHILD_CONTRACT = "order_resume_child_v1"
# The child's program: the same resume_selection on the same folders and parameters, its result pickled to stdout; an error is pickled
# too (its traceback), so stderr is not read (no pipe can fill and block). Run with -B (order_search asserts it).
_RESUME_CHILD_CODE = """
import json, pickle, sys, traceback
sys.path[:0] = json.loads(sys.argv[1])
out = sys.stdout.buffer
try:
    from pathlib import Path
    import order_search as O
    import order_select as osel
    a = json.loads(sys.argv[2])
    p = dict(a["params"])
    p["level_weights"] = tuple(p["level_weights"])
    seq, rec = O.resume_selection([Path(x) for x in a["folders"]], osel.Pace(osel.OrderParams(**p)))
    msg = ("ok", seq, rec, O.peak_private_mb())
except BaseException:
    msg = ("error", traceback.format_exc()[-4000:], None, O.peak_private_mb() if "O" in globals() else None)
pickle.dump(msg, out, protocol=pickle.HIGHEST_PROTOCOL)
out.flush()
"""


def resume_child_plan_record() -> Dict[str, Any]:
    """The resume-in-a-child option's record (owner 2026-11-21), in the plan only when it is on; the run refuses another."""
    return {"contract": RESUME_CHILD_CONTRACT,
            "rule": ("the plan and the open derive the resume (resume_selection: the same folders, arrival rule and key options) in a child "
                     "Python process that pickles the insertion sequence and the record to the main process through its stdout and exits; "
                     "at the open this happens where the in-process derivation did, before the workers start; the main process checks the "
                     "set digest against the plan's as before and drops the sequence once it is inserted"),
            "why": "the derivation's memory (about 2 GB on 9 folders) is held by the child and returned to the system when it exits"}


def peak_private_mb() -> Optional[float]:
    """This process's peak private bytes (commit charge) in MB on Windows (K32GetProcessMemoryInfo PeakPagefileUsage); None elsewhere or on
    failure. Report-only."""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class _PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wt.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(pmc)
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return None
        return round(pmc.PeakPagefileUsage / 2 ** 20, 1)
    except (OSError, AttributeError, ValueError):
        return None


def resume_selection_child(folders: Sequence[Path], dp: osel.OrderParams) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """resume_selection(folders, Pace(dp)) run in a child Python process (owner 2026-11-21, --resume-child): the same code on the same
    inputs, so the same insertion sequence and record; the child's derivation memory leaves with it. Returns (sequence, record, the child's
    report: wall seconds, peak private MB, exit code, inserts); with no folder ([], None, None) as resume_selection. A child that fails,
    returns nothing or exits non-zero raises SearchError."""
    if not folders:
        return [], None, None
    paths = [str(REPO / "rl"), str(HERE)]
    args = {"folders": [str(Path(d)) for d in folders], "params": dp.as_record()}
    t0 = time.perf_counter()
    proc = subprocess.Popen([sys.executable, "-B", "-c", _RESUME_CHILD_CODE, json.dumps(paths), json.dumps(args)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=str(HERE))
    assert proc.stdout is not None
    try:
        status, seq, rec, peak = pickle.load(proc.stdout)
    except Exception as exc:                             # nothing (or not a whole result) came back: the child died
        proc.kill()
        proc.wait()
        raise SearchError(f"the resume derivation in a child process returned no result ({exc!r}; exit {proc.returncode})")
    finally:
        proc.stdout.close()
    rc = proc.wait()
    if status != "ok":
        raise SearchError(f"the resume derivation in a child process failed: {seq}")
    if rc != 0:
        raise SearchError(f"the resume derivation's child process exited {rc} after its result")
    return seq, rec, {"wall_s": round(time.perf_counter() - t0, 1), "child_peak_private_mb": peak, "exit_code": rc, "inserts": len(seq)}


def resume_selection(folders: Sequence[Path], pace: osel.Pace) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """The resume (zero native ticks): every folder's candidates through this night's arrival rule, then the archive's keep rule mirrored,
    in tick order, ties in the order the folders are given, then by D cell id; this night's tick-0 root holds the root's key at tick 0.
    Returns the insertion sequence (each entry new or replaced, in order, with its candidate) and the record (None with no folder)."""
    if not folders:
        return [], None
    seen: List[str] = []
    for d in folders:
        n = g.norm(Path(d))
        if n in seen:
            raise SearchError(f"refused: {d} is given twice as --resume-from")
        seen.append(n)
    recs, reps, sources = [], [], []
    for d in folders:
        rec = resume_folder(Path(d))
        cands, rep = resume_candidates(Path(d), rec)
        recs.append(rec)
        reps.append(rep)
        sources.append(cands)
    roots = {(r["root"]["digest"], r["root"]["chain"], json.dumps(r["root"]["key"])) for r in recs}
    if len(roots) != 1:
        raise SearchError(f"refused: the resume folders' tick-0 roots differ ({sorted(x[0][:16] for x in roots)})")
    root_key = direction_key(recs[0]["root"]["key"], 0, pace.dir_key)   # v7: the keys as this night keeps them (option off: today's)
    held: Dict[Tuple[Any, ...], int] = {root_key: 0}
    queue = sorted(((int(c["tick"]), i, int(c["d_cid"]), c) for i, cands in enumerate(sources) for c in cands), key=lambda x: x[:3])
    seq: List[Dict[str, Any]] = []
    per: Dict[str, Counter] = {}
    reasons: Counter = Counter()
    h = hashlib.sha256()
    for tick, i, d_cid, c in queue:
        lv = int(c["level"])
        why = pace.reason_ticks(lv, tick, [p[0] for p in c["breaks"]])     # v4: with the open line when it is set
        pc = per.setdefault(_lr(lv, c["key"][2]), Counter())
        pc["candidates"] += 1
        if why is not None:
            pc["dropped_rule"] += 1
            reasons[why[0]] += 1
            continue
        k = direction_key(c["key"], tick, pace.dir_key)                   # v7: re-keyed from the cell's own tick when the option is on
        if k not in held:
            verdict = cs.NEW
        elif tick < held[k]:
            verdict = cs.REPLACED
        else:
            pc["dropped_later"] += 1
            continue
        held[k] = tick
        pc["inherited" if verdict == cs.NEW else "replaced_in_resume"] += 1
        seq.append({"verdict": verdict, "folder_index": i, "cand": c, "key": list(k)})
        h.update(f"{verdict}:{i}:{d_cid}:{c['digest']}:{tick};".encode("utf-8"))
    tot = Counter()
    for pc in per.values():
        tot.update(pc)
    final_keys: Dict[Tuple[Any, ...], Mapping[str, Any]] = {}
    for e in seq:
        final_keys[tuple(e["key"])] = e["cand"]
    record = {"contract": RESUME_CONTRACT, "folders": recs, "reports": reps, "root": dict(recs[0]["root"]),
              "rule": "all final representatives; a cell outside this night's arrival rule is dropped; the rest enter through the archive's keep "
                      "rule in tick order (ties: folder order, then D cell id); selector and retirement counts start at zero",
              "counts": {k: int(tot.get(k, 0)) for k in ("candidates", "inherited", "replaced_in_resume", "dropped_rule", "dropped_later")},
              "dropped_rule_reasons": dict(reasons), "inserts": len(seq), "cells_after": int(tot.get("inherited", 0)),
              "per_level_res": {k: {x: int(v.get(x, 0)) for x in ("candidates", "inherited", "replaced_in_resume", "dropped_rule", "dropped_later")}
                                for k, v in sorted(per.items(), key=lambda kv: (int(kv[0].split("|")[0]), kv[0]))},
              "set_digest": h.hexdigest()}
    if pace.dir_key:                                     # v7, only with the option: the inherited moving-floor cells, per level and direction
        mf: Counter = Counter(f"{int(c['level'])}|{'up' if k[4] < DIR_FLOOR_OFFSET[DIR_DOWN] else 'down'}" for k, c in final_keys.items()
                     if k[2] == mcell.RES_GROUNDED and int(k[4]) >= DIR_FLOOR_OFFSET[DIR_UP])
        record["floor_direction_cells"] = {k: int(mf[k]) for k in sorted(mf, key=lambda s: (-int(s.split("|")[0]), s))}
    return seq, record


# -- the exploration-extent record (owner 2026-11-16; report-only) ------------------------------------------------------------------------


def burst_extent(reaches: Sequence[Sequence[Any]], breaks_all: Sequence[Sequence[int]], pace: osel.Pace) -> Dict[str, Dict[str, Any]]:
    """Per "level|live mask" a burst was at: over every reach (a first visit of a key in the job, kept or not), the highest y, the lowest
    x and the highest x, each as [value, tick], and the reach count; under "all" for every reach, under "inside" for the reaches inside the
    keep window (the arrival rule, from the job's own break ticks). Read by no rule."""
    pairs = break_pairs(breaks_all)
    out: Dict[str, Dict[str, Any]] = {}
    for r in sorted(reaches, key=lambda r: int(r[0])):
        j, m, obs = int(r[0]), int(r[1][3]), r[2]
        lv = mcell.level_of_mask(m)
        x, y = float(obs[OBS_X]), float(obs[OBS_Y])
        groups = ["all"]
        if lv < osel.TARGETS_TOTAL:
            bt = [int(t) for t, _i in pairs if int(t) <= j]
            if len(bt) != lv:
                raise SearchError(f"a reach at level {lv}, tick {j} carries {len(bt)} break ticks")
            if pace.keeps_ticks(lv, j, bt):
                groups.append("inside")
        e = out.setdefault(f"{lv}|{m}", {"level": lv, "mask": m})
        for gname in groups:
            d = e.setdefault(gname, {"reaches": 0, "max_y": None, "min_x": None, "max_x": None})
            d["reaches"] += 1
            if d["max_y"] is None or y > d["max_y"][0]:
                d["max_y"] = [y, j]
            if d["min_x"] is None or x < d["min_x"][0]:
                d["min_x"] = [x, j]
            if d["max_x"] is None or x > d["max_x"][0]:
                d["max_x"] = [x, j]
    return out


def merge_extent(acc: Dict[str, Any], d: Mapping[str, Any], n: int) -> None:
    """Fold one burst's extent group into a running one: [value, tick, dispatch] per extreme, reaches and bursts counted."""
    acc["reaches"] = acc.get("reaches", 0) + int(d["reaches"])
    acc["bursts"] = acc.get("bursts", 0) + 1
    for k, better in (("max_y", lambda a, b: a > b), ("min_x", lambda a, b: a < b), ("max_x", lambda a, b: a > b)):
        v = d.get(k)
        if v is not None and (acc.get(k) is None or better(v[0], acc[k][0])):
            acc[k] = [v[0], v[1], int(n)]


# -- E1: the break record (owner 2026-11-18; report-only) ------------------------------------------------------------------------------


HITTER_FIELDS = ("hitter", "hitter_serial", "hitter_owner", "hitter_first_tick", "hitter_weapon_kind", "hitter_candidates", "hitter_why",
                 "hitter_evidence")
NO_HITTER_EVENT = "no hitter event for this break in the job result"


def hitter_plan_record() -> Dict[str, Any]:
    """The plan's record of the hitter option (owner 2026-11-19); a plan with the option off has no such key."""
    return {"contract": ow.HITTER_CONTRACT, "worker": ow.ORDER_WORKER_CONTRACT, "search_flags_added": dict(ow.ENTITY_FLAGS), "rule": ow.HITTER_RULE,
            "fields": list(HITTER_FIELDS), "read_by": "no rule (report-only): break_record entries in dispatches.jsonl, the scoreboard's break "
                                                      "attribution, the summary"}


def hitter_events(res: Mapping[str, Any]) -> Dict[Tuple[int, int], Mapping[str, Any]]:
    """{(tick, target): the worker's hitter event of that break} from one job result (empty without the record)."""
    out: Dict[Tuple[int, int], Mapping[str, Any]] = {}
    for ev in (res.get("d_hitters") or {}).get("events") or []:
        for t in ev.get("targets") or []:
            out[(int(ev["tick"]), int(t))] = ev
    return out


def hitter_fields(ev: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The hitter fields of one credited break (HITTER_FIELDS); kind "unavailable" when the job result holds no event for it."""
    if ev is None:
        return dict(zip(HITTER_FIELDS, ("unavailable", None, None, None, None, [], NO_HITTER_EVENT, None)))
    return dict(zip(HITTER_FIELDS, (ev["kind"], ev.get("serial"), ev.get("owner"), ev.get("first_tick"), ev.get("weapon_kind"),
                                    list(ev.get("candidates") or []), ev.get("why"), ev.get("evidence"))))


def break_record(res: Mapping[str, Any], hitter: bool = False) -> List[Dict[str, Any]]:
    """One entry per credited break (a break after the dispatch's start tick L: the row's breaks_after_start, in break order): its tick,
    target and the level it gave (breaks counted from tick 0), Mario's position and what the job result carries for that tick: the reach
    at the break tick (a first visit of a key in the job) with the 17 observation fields by name, the cell key, the terminal flag, the
    record digest and the chain. `reach` is None when the result holds no reach at that tick (the step was not live). With the hitter
    record (owner 2026-11-19) every entry also carries HITTER_FIELDS. Read by no rule."""
    L = int(res["L"])
    at = {int(r[0]): r for r in (res.get("reaches") or [])}
    evs = hitter_events(res) if hitter else {}
    out: List[Dict[str, Any]] = []
    for idx, (t, i) in enumerate(break_pairs(res.get("breaks_all"))):
        if t <= L:
            continue
        e: Dict[str, Any] = {"tick": t, "target": i, "level": idx + 1}
        r = at.get(t)
        if r is None:
            e["reach"] = None
        else:
            obs = tuple(r[2])
            e.update({"x": obs[OBS_X], "y": obs[OBS_Y], "obs": mcell.obs_dict(obs), "key": list(r[1]), "terminal": bool(r[5]),
                      "record_digest": bytes(r[3]).hex(), "chain": bytes(r[4]).hex()})
        if hitter:
            e.update(hitter_fields(evs.get((t, i))))
        out.append(e)
    return out


def resume_check(plan_resume: Optional[Mapping[str, Any]], folders: Sequence[Path]) -> Optional[str]:
    """Why `run`'s --resume-from folders are not the plan's (their list, order and file digests); None when they are."""
    want = [f["dir"] for f in (plan_resume or {}).get("folders") or []]
    got = [str(Path(d)) for d in folders]
    if [g.norm(Path(x)) for x in want] != [g.norm(Path(x)) for x in got]:
        return f"the --resume-from folders {got} are not the plan's {want}: plan again with the same flags"
    for f in (plan_resume or {}).get("folders") or []:
        for rel, h in f["files_sha256"].items():
            if g.sha256_file(Path(f["dir"]) / rel) != h:
                return f"{Path(f['dir']) / rel} changed since the plan: plan again"
    return None


# -- the plan (zero native ticks) -----------------------------------------------------------------------------------------------------------


def engine_params(dp: osel.OrderParams, **kw: Any) -> C.Params3:
    """Run 3's engine parameters for D: its CONT arm, caps, keyed seed and record interval; breadth share = D's; no triggers; the archive
    retires nothing (D's retirement is the selector's)."""
    kw.setdefault("retire_after", 0)
    p = C.Params3(breadth_share=float(dp.breadth_share), trigger_classes=(), **kw)
    p.check()
    return p


def d_arm(ep: C.Params3) -> Dict[str, int]:
    """D's arm (owner 2026-11-16): run 3's CONT arm with the boundary window set to one segment (window = segment_words), so each boundary
    question carries every reach of its segment (the continuation rule, CONT_RULE). The worker reads the window from the job."""
    a = dict(ep.arm())
    a["window"] = int(a["segment_words"])
    return a


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
               readiness_override: Optional[Mapping[str, Any]] = None, resume: Sequence[Path] = (), hitter_record: bool = False,
               resume_child: bool = False) -> Dict[str, Any]:
    """The plan (section 7.1 step 2): the root, the pace table, the parameters, the frontier reference read, the resume. Zero ticks. With the
    hitter record (owner 2026-11-19) it also holds `hitter_record`; without it the plan has no such key. With the resume in a child (owner
    2026-11-21) the derivation runs in a child process and the plan holds `resume_child`; without it, no such key."""
    dp.check()
    ep.check()
    pace = osel.Pace(dp)
    fb = read_frontier_best(frontier_dir)
    osel.claim_wanted(1, fb["completion_input_tick"])
    for d in resume:
        if g.norm(Path(d)) == g.norm(Path(out)) or g.under(g.norm(Path(d)), g.norm(Path(out))) or g.under(g.norm(Path(out)), g.norm(Path(d))):
            raise SearchError(f"refused: the resume folder {d} overlaps the output folder {out}")
    if resume_child and not resume:
        raise SearchError("refused: --resume-child derives a resume in a child process: it needs --resume-from")
    if resume_child:
        _seq, res_rec, _info = resume_selection_child([Path(d) for d in resume], dp)
    else:
        _seq, res_rec = resume_selection([Path(d) for d in resume], pace)
    digest = code or code_digest(order_code_manifest())
    ref = osel.Pace(osel.OrderParams(goal=dp.goal, slack=M1_REFERENCE_SLACK, level_weights=dp.level_weights, breadth_share=dp.breadth_share,
                                     retire_after=dp.retire_after))
    sources = [fb["summary"]] + [str(Path(f["dir"]) / "run" / "summary.json") for f in (res_rec or {}).get("folders") or []]
    keep_rule: Dict[str, Any] = {"selection_contract": osel.SELECT_CONTRACT, "rule": "arrival: L-th break <= line(L) and own tick <= line(L + 1)",
                                 "windows": {str(L): [pace.line(L), pace.window_end(L)] for L in range(osel.TARGETS_TOTAL)}}
    if pace.open_from is not None:                       # owner 2026-11-18: only with the option, so the plan with it off is v3's
        k = pace.open_from
        keep_rule.update({"open_line_from": k, "open_line": pace.line(k), "archive_bound": archive_bound(dp),
                          "open_rule": (f"levels >= {k}: also kept and drawable when the {k}-th break <= line({k}) = {pace.line(k)}; no line on the later "
                                        f"breaks or the own tick (the archive's own bound is the horizon); the windows above still keep what they keep; "
                                        f"keep, draw, continuation and resume read it, the milestones do not; the levels >= {k} are one draw "
                                        f"group: the deepest level's weight in the level draw (the levels below {k} weighted as if {k} were the "
                                        f"deepest), the fewest dispatches over all its cells, no rotation (ties: deeper level, earlier tick, "
                                        f"cell id)")})
    if pace.cut_y is not None:                           # owner 2026-11-19: only with the option, so the plan with it off is v4's
        k = int(pace.open_from)                          # OrderParams.check: the cut needs the open line
        final = resume_finals(_seq)
        below: Counter = Counter(str(cd["level"]) for cd in final.values()
                                 if pace.below_cut(int(cd["level"]), float(cd["end"][OBS_Y]), str(cd["key"][2])))
        spared: Counter = Counter(str(cd["level"]) for cd in final.values()
                                  if pace.below_y(int(cd["level"]), float(cd["end"][OBS_Y])) and str(cd["key"][2]) == osel.GROUNDED)
        keep_rule.update({"fall_cut_y": float(pace.cut_y), "fall_cut_from": k,
                          "fall_cut_rule": (f"levels >= {k}: a state with position y < {pace.cut_y:g} whose resource class is not "
                                            f"{osel.GROUNDED} (grounded) is not kept as a cell and its cell is not drawable (exploitation or "
                                            f"breadth); an inherited such cell stays kept, undrawable; grounded states below it are kept and "
                                            f"drawable; reaches are still recorded; levels below {k}, the continuation and the milestones unchanged"),
                          "fall_cut_inherited_undrawable": {lv: int(below[lv]) for lv in sorted(below, key=int, reverse=True)},
                          "fall_cut_inherited_grounded_spared": {lv: int(spared[lv]) for lv in sorted(spared, key=int, reverse=True)}})
        if pace.spare_one_live:                          # owner 2026-11-20 (v7): only with the option, so the plan with it off is v6's
            one: Counter = Counter(str(cd["level"]) for cd in final.values() if pace.one_live(int(cd["level"]))
                                   and pace.below_y(int(cd["level"]), float(cd["end"][OBS_Y])) and str(cd["key"][2]) != osel.GROUNDED)
            keep_rule.update({"fall_cut_one_live": (f"the fall cut does not apply to a state with exactly one live target (level "
                                                    f"{osel.TARGETS_TOTAL - 1}): its next break is the clear; such a state below Y is kept and "
                                                    f"drawable whatever its resource class"),
                              "fall_cut_inherited_one_live_spared": {lv: int(one[lv]) for lv in sorted(one, key=int, reverse=True)}})
    if pace.bound is not None:                           # owner 2026-11-20 (v7): only with the option, so the plan with it off is v6's
        k = int(pace.open_from)                          # OrderParams.check: the bound needs the open line
        past: Counter = Counter(str(cd["level"]) for cd in resume_finals(_seq).values() if pace.past_bound(int(cd["level"]), int(cd["tick"])))
        keep_rule.update({"record_bound": int(pace.bound), "record_bound_from": k,
                          "record_bound_rule": (f"levels >= {k}: a state whose own tick is {pace.bound} or later is not kept and its cell is not "
                                                f"drawable (exploitation or breadth); an inherited such cell stays kept, undrawable; a burst stops "
                                                f"at its first boundary whose state is at a level >= {k} at a tick >= {pace.bound}; reaches are "
                                                f"still recorded; clears, claims, the milestones and levels below {k} unchanged"),
                          "record_bound_inherited_undrawable": {lv: int(past[lv]) for lv in sorted(past, key=int, reverse=True)}})
    if pace.dir_key:                                     # owner 2026-11-20 (v7): only with the option, so the plan with it off is v6's
        keep_rule["floor_direction_key"] = direction_key_record()
    plan = {"contract": ORDER_CONTRACT, "mode": "lab", "utc": g.utc(), "lab_root": str(lab_root), "out": str(out),
            "archive_id": ARCHIVE_ID.format(seed=int(ep.rng_seed)), "key_family": KEY_FAMILY,
            "root": {"level": 0, "mask": osel.ROOT_MASK, "niche": rs.niche_label(rs.seed_niche(osel.ROOT_MASK)), "words": 0,
                     "read": "at the open: two fresh processes reach tick 0 with no input word; tick-0 records, keys and masks must be equal"},
            "pace": {"goal": dp.goal, "slack": dp.slack, "lines": {str(L): pace.line(L) for L in range(osel.TARGETS_TOTAL + 1)}},
            "milestones": {name: {"level": L, "line": pace.line(L)} for name, L in list(osel.MILESTONES) + [(osel.CLEAR_LINE, osel.TARGETS_TOTAL)]},
            "gate": {"milestone": "M1", "level": 6, "line": pace.line(6)},
            "gate_reference": {"milestone": "M1", "level": 6, "slack": M1_REFERENCE_SLACK, "line": ref.line(6),
                               "note": "report-only: the earliest in-night 6th break against line(6) at the decided D-Q1 slack"},
            "keep_rule": keep_rule,
            "continuation": cont_rule(pace),
            "params": dp.as_record(), "params_fingerprint": osel.params_fingerprint(dp), "selection_contract": osel.SELECT_CONTRACT,
            "engine_params": ep.as_dict(), "arm": d_arm(ep), "frontier": fb, "claim_threshold": fb["completion_input_tick"],
            "sources": sources, "code": {"contract": MANIFEST_CONTRACT, "entries": list(ENTRY_MODULES), "digest": digest},
            "readiness_override": None if readiness_override is None else dict(readiness_override), "resume": res_rec}
    if hitter_record:                                    # owner 2026-11-19: only with the option, so the plan with it off is v4's
        plan["hitter_record"] = hitter_plan_record()
    if resume_child:                                     # owner 2026-11-21: only with the option, so the plan with it off is c74e042's
        plan["resume_child"] = resume_child_plan_record()
    return plan


def plan_and_write(lab_root: Path, frontier_dir: Path, out: Path, dp: osel.OrderParams, ep: C.Params3, *, code: Optional[str] = None,
                   readiness_override: Optional[Mapping[str, Any]] = None, resume: Sequence[Path] = (), hitter_record: bool = False,
                   resume_child: bool = False) -> Dict[str, Any]:
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
    plan = build_plan(lab_root, frontier_dir, out, dp, ep, code=code, readiness_override=readiness_override, resume=resume, hitter_record=hitter_record,
                      resume_child=resume_child)
    fs = g.LabFS(Path(lab_root))
    fs.mkdir(out)
    fs.write_json(pp, plan)
    return plan


def archive_bound(dp: osel.OrderParams) -> int:
    """The bound the archive's own keep rule applies to every state's tick (crossing_search.Archive.keep: a tick past it is BEYOND): line(10)
    (the arrival rule is stricter at every level, so it never binds); with the open line (owner 2026-11-18: no line on a level >= K state's
    own tick) the horizon, which no reach passes."""
    return int(mcell.HORIZON) if dp.open_line_from is not None else osel.pace_line(osel.TARGETS_TOTAL, dp.goal, dp.slack)


def engine_plan(plan: Mapping[str, Any], ep: C.Params3) -> Dict[str, Any]:
    """What run 3's engine core reads from a plan, for D: an empty archive (the root is kept at the open), the pace line as the per-level
    reference (lead = line(L) - tick), the frontier's best as the claim reference, no seed, no inherited run. The archive's bound is
    archive_bound (line(10), or the horizon with the open line)."""
    lines = {int(L): int(t) for L, t in plan["pace"]["lines"].items()}
    fb = plan["frontier"]
    top = lines[osel.TARGETS_TOTAL]
    if plan["params"].get("open_line_from") is not None:
        top = int(mcell.HORIZON)
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
        # the hitter record (owner 2026-11-19, report-only): on exactly when the plan holds it, and then this code's record
        self.hitter_plan: Optional[Dict[str, Any]] = self.order_plan.get("hitter_record")
        if self.hitter_plan is not None and self.hitter_plan != hitter_plan_record():
            raise SearchError("refused: the plan's hitter record is not this code's (plan again)")
        self.hitter = self.hitter_plan is not None
        # the resume in a child process (owner 2026-11-21): on exactly when the plan holds it, and then this code's record
        self.resume_child_plan: Optional[Dict[str, Any]] = self.order_plan.get("resume_child")
        if self.resume_child_plan is not None and self.resume_child_plan != resume_child_plan_record():
            raise SearchError("refused: the plan's resume-child record is not this code's (plan again)")
        self.resume_child = self.resume_child_plan is not None
        self.resume_child_info: Optional[Dict[str, Any]] = None
        self.hit_stats: Dict[str, Any] = {"credited": 0, "by_kind": Counter(), "by_level_kind": Counter(), "unavailable_why": Counter(),
                                          "jobs_with_record": 0, "jobs_without_record": 0, "tracker_errors": 0}
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
        self.c.update({"rejected_reaches": 0, "milestone_ticks": 0, "cont_checked": 0, "cont_mismatches": 0, "deep_reaches": 0, "new_in_night": 0})
        if self.pace.cut_y is not None:                      # owner 2026-11-19: only with the fall cut, so the counters with it off are v4's
            self.c["cut_reaches"] = 0
        if self.pace.bound is not None:                      # owner 2026-11-20 (v7): only with the record bound
            self.c["bound_reaches"] = 0
        self.cut_open: Dict[str, int] = {}                   # the fall cut: per level, the inherited cells it makes undrawable at the open
        self.bound_open: Dict[str, int] = {}                 # v7: the record bound's, per level
        # v7 (owner 2026-11-20): the direction key's definition is the plan's, or the night is refused (plan again)
        self.dir_plan: Optional[Dict[str, Any]] = (self.order_plan.get("keep_rule") or {}).get("floor_direction_key")
        if self.pace.dir_key and self.dir_plan != direction_key_record():
            raise SearchError("refused: the plan's floor-direction key is not this code's (plan again)")
        self.arm = d_arm(params)                             # the boundary window = one segment (CONT_RULE); jobs carry it
        self.breaks_of: Dict[int, Tuple[Tuple[int, int], ...]] = {}   # every kept cell's break pairs (tick, target), sorted (v2)
        self._insert_pairs: Optional[Tuple[Tuple[int, int], ...]] = None   # set while the open keeps the root and the resumed cells
        # v3 (owner 2026-11-16): per cell, the input tick up to which its lineage's breaks are inherited: 0 for the night's root lineage, a
        # resumed cell's own tick; a cell kept from a burst takes the dispatched cell's value. Its breaks after that tick happened tonight.
        self.inherited_until: Dict[int, int] = {}
        self._insert_inh: Optional[int] = None
        self.resume_plan: Optional[Dict[str, Any]] = self.order_plan.get("resume")
        self.resume_folders: List[Path] = [Path(f["dir"]) for f in (self.resume_plan or {}).get("folders") or []]
        self.resume_seq: List[Dict[str, Any]] = []
        self.resume_open: Dict[str, Any] = {}
        self.clf = mcell.Classifier()                        # status classes, for the scoreboard's status at a break (report-only)
        self.sb: Dict[str, Any] = {"first": {}, "best": {}, "inherited_best": {}, "dispatches": Counter(), "dispatches_res": Counter(),
                                   "bursts": Counter(), "bursts_by_level": {}, "breaks": {}, "deep": Counter(), "new_by_level": Counter(),
                                   "extent6": {}}
        self.scoreboard: Optional[Dict[str, Any]] = None
        self.sets_orders_open: Dict[str, Dict[str, int]] = {}
        orig_keep = self.archive.keep

        def keep(key: Sequence[Any], level: int, tick: int, words: bytes, end: Sequence[Any], end_digest: bytes, chain: bytes, origin: Mapping[str, Any],
                 n_dispatch: int, **kw: Any) -> Tuple[str, Optional[cs.Cell]]:
            lv, t = int(level), int(tick)
            # v7 (owner 2026-11-20): the key as this night keeps it: with --floor-direction-key a state grounded on a moving floor line gets
            # the platform's direction at its tick in the floor field; off, the plain key (today's). The frozen ingest compares it with the
            # dispatched cell's stored key (self_key), which went through here too. LIMIT: a reach exists only at the first visit of its
            # five-field key in the burst (the frozen worker), so a same-burst revisit after the platform turned is never keyed.
            key = direction_key(key, t, self.pace.dir_key)
            pairs = self.reach_pairs(lv, t)
            arrival = osel.arrival_tick([p[0] for p in pairs], lv) if lv < osel.TARGETS_TOTAL else None
            deep = self._cur is not None and lv >= DEEP_REACH_LEVEL
            if not kw.get("terminal") and lv < osel.TARGETS_TOTAL:
                why = self.pace.reason_ticks(lv, t, [p[0] for p in pairs])     # v4: with the open line when it is set
                if why is not None:
                    self.archive.counts[cs.BEYOND] += 1          # the arrival rule: not kept; counted in the rejected-reach readout
                    self.pace.rejected.note(lv, t, why[0], why[1])
                    self.c["rejected_reaches"] += 1
                    if deep:
                        self.log_deep_reach(key, lv, t, arrival, cs.BEYOND, why)
                    return cs.BEYOND, None
                if self.pace.bound is not None and self._insert_pairs is None and self.pace.past_bound(lv, t):
                    self.archive.counts[cs.BEYOND] += 1          # the record bound (owner 2026-11-20, v7), in-night reaches only: not kept,
                    self.pace.bound_reaches.note(lv, t)          # as a rule rejection; checked before the fall cut
                    self.c["bound_reaches"] += 1
                    if deep:
                        self.log_deep_reach(key, lv, t, arrival, cs.BEYOND, ("record_bound", t - int(self.pace.bound)))
                    return cs.BEYOND, None
                if self.pace.cut_y is not None and self._insert_pairs is None and self.pace.below_y(lv, float(end[OBS_Y])):
                    y = float(end[OBS_Y])                        # the fall cut (owner 2026-11-19), in-night reaches only
                    if str(key[2]) == osel.GROUNDED:             # v6: a grounded state below Y is spared (counted, then the keep rule)
                        self.pace.cut.spare(lv)
                    elif self.pace.one_live(lv):                 # v7: one live target, spared (counted, then the keep rule)
                        self.pace.cut.spare_one_live(lv)
                    else:                                        # not kept, as a rule rejection
                        self.archive.counts[cs.BEYOND] += 1
                        self.pace.cut.note(lv, t, y)
                        self.c["cut_reaches"] += 1
                        if deep:
                            self.log_deep_reach(key, lv, t, arrival, cs.BEYOND, ("fall_cut", round(float(self.pace.cut_y) - y, 3)))
                        return cs.BEYOND, None
            if lv < osel.TARGETS_TOTAL:
                origin = dict(origin, d_breaks=[list(p) for p in pairs])
            verdict, c = orig_keep(key, level, tick, words, end, end_digest, chain, origin, n_dispatch, **kw)
            if verdict in (cs.NEW, cs.REPLACED) and c is not None:
                self.breaks_of[int(c.cid)] = pairs
                if self._insert_pairs is not None:
                    self.inherited_until[int(c.cid)] = int(self._insert_inh if self._insert_inh is not None else 0)
                elif self._cur is not None:
                    self.inherited_until[int(c.cid)] = int(self._cur[0]["d_inh0"])
                if self._cur is not None:
                    info = self._cur[0]
                    niche = rs.child_niche(info["niche"], int(c.key[3]), int(c.tick), self._post, self.niche_live)
                    self._kept.append((verdict, c, niche))
                    self.note_arrival(self.sb, c, pairs, niche, in_night=True, after=int(info["d_inh0"]))
                    self.c["new_in_night"] += int(verdict == cs.NEW)
                    self.sb["new_by_level"][str(lv)] += int(verdict == cs.NEW)
            if deep:
                self.log_deep_reach(key, lv, t, arrival, verdict, None)
            return verdict, c

        self.archive.keep = keep  # an instance attribute: DeterministicSchedule wraps this one in turn

    # -- the arrival rule's inputs and the scoreboard's arrivals -------------------------------------------------------------------------------

    def reach_pairs(self, level: int, tick: int) -> Tuple[Tuple[int, int], ...]:
        """A reach's break pairs: the job's own (breaks_all: the prefix replay's and the burst's) at or before its tick; at the open, the root's
        (none) and each resumed cell's. One pair per target broken, or SearchError."""
        if self._insert_pairs is not None:
            pairs = self._insert_pairs
        elif self._cur is not None:
            pairs = break_pairs([(t, i) for t, i in (self._cur[1].get("breaks_all") or []) if int(t) <= int(tick)])
        else:
            raise SearchError(f"a reach at level {level}, tick {tick} with no job and no inserted break ticks")
        if len(pairs) != int(level):
            raise SearchError(f"a reach at level {level}, tick {tick} carries {len(pairs)} break ticks ({list(pairs)[:12]})")
        return pairs

    def note_arrival(self, sb: Dict[str, Any], c: Any, pairs: Sequence[Tuple[int, int]], niche: Any, *, in_night: bool, after: int = 0) -> None:
        """Scoreboard (report-only): for every level L <= the cell's, its L-th break against the best so far (the order of its first L
        targets); in the night, the first kept arrival at each level (wall time, dispatch, tick). In the night (v3), a level counts only if
        its L-th break happened during one of the night's bursts: its tick is after `after`, the tick up to which the lineage is inherited."""
        order = list(niche[1]) if niche is not None else []
        key_best = "best" if in_night else "inherited_best"
        for L in range(1, int(c.level) + 1):
            t = int(pairs[L - 1][0])
            if in_night and t <= int(after):
                continue
            b = sb[key_best].get(str(L))
            if b is None or t < b["tick"]:
                sb[key_best][str(L)] = {"tick": t, "order": "-".join(str(x) for x in order[:L]), "cid": int(c.cid), "cell_tick": int(c.tick),
                                        "n": int(self._cur[0]["n"]) if (in_night and self._cur is not None) else 0,
                                        "elapsed_s": round(self.elapsed(), 1) if in_night else 0.0, "inherited_until": int(after) if in_night else None}
            if in_night and str(L) not in sb["first"]:
                sb["first"][str(L)] = {"tick": t, "elapsed_s": round(self.elapsed(), 1), "n": int(self._cur[0]["n"]) if self._cur is not None else None,
                                       "cid": int(c.cid), "order": "-".join(str(x) for x in order[:L]), "inherited_until": int(after)}

    def log_deep_reach(self, key: Sequence[Any], level: int, tick: int, arrival: Optional[int], verdict: str, why: Optional[Tuple[str, int]]) -> None:
        """Every reach at level >= DEEP_REACH_LEVEL of an in-night burst, kept or not (owner 2026-11-16): deep_reaches.jsonl. Report-only."""
        info = self._cur[0] if self._cur is not None else {}
        row = {"n": info.get("n"), "cid": info.get("cid"), "k": info.get("k"), "start_level": info.get("level"), "start_tick": info.get("tick"),
               "level": int(level), "tick": int(tick), "arrival": arrival, "key": list(key), "verdict": verdict,
               "reason": why[0] if why else None, "over": why[1] if why else None, "utc": g.utc()}
        self.c["deep_reaches"] += 1
        self.sb["deep"][f"{int(level)}|{verdict}"] += 1
        with self._lock:
            self.fs.append_jsonl(self.dir / "deep_reaches.jsonl", row)

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
        if self.resume_plan is not None:                    # the resume, derived again from the same folders: the plan's set, or refused
            bad = resume_check(self.resume_plan, self.resume_folders)
            if bad:
                raise Refused(f"resume: {bad}")
            try:
                if self.resume_child:                       # owner 2026-11-21: the same derivation in a child process that exits here
                    self.resume_seq, rec, self.resume_child_info = resume_selection_child(self.resume_folders, self.dp)
                else:
                    self.resume_seq, rec = resume_selection(self.resume_folders, self.pace)
            except (SearchError, rl3.LoadError, ValueError, OSError) as exc:
                raise Refused(f"resume: {exc}")
            if rec is None or rec["set_digest"] != self.resume_plan["set_digest"]:
                raise Refused(f"resume: the inserted set {None if rec is None else rec['set_digest'][:16]} is not the plan's {self.resume_plan['set_digest'][:16]}")
        self.fs.mkdir(self.dir)
        self.fs.write_json(self.dir / "config.json", self.config_record(ready))
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=sampler_snapshot(env.snapshot), now=env.now,
                                  extra=lambda: {"cells": len(self.archive.cells), "phase": self.phase, "dispatches": self.c["dispatches"], "jobs": self.c["jobs"],
                                                 "words_mb": round(self.archive.words_bytes / 2 ** 20, 1)}).start()
        self.phase = "root"
        self.pool = ow.OrderPool(env.worker_spec, env.now) if self.hitter else r3w.Run3Pool(env.worker_spec, env.now)
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
        if self.resume_plan is not None:
            want = self.resume_plan["root"]
            if r0["digest"] != want["digest"] or r0["chain"] != want["chain"] or list(r0["key"]) != list(want["key"]):
                self.root["resume_root_equal"] = False
                self.fs.write_json(self.dir / "root.json", self.root)
                self.mark("SEARCH_INVALID", f"the tick-0 root ({r0['digest'][:16]}) is not the resume folders' ({want['digest'][:16]}): their cells' chains "
                                            f"would not replay")
                return
            self.root["resume_root_equal"] = True
            self.fs.write_json(self.dir / "root.json", self.root)
        self.pin = {"obs": list(r0["obs"]), "digest": r0["digest"], "chain": r0["chain"], "lines": r0["lines"]}
        self._insert_pairs, self._insert_inh = (), 0         # the night's own root: nothing inherited
        try:
            verdict, c = self.archive.keep(tuple(r0["key"]), 0, 0, b"", tuple(r0["obs"]), bytes.fromhex(r0["digest"]), bytes.fromhex(r0["chain"]), {"kind": "root"}, 0)
        finally:
            self._insert_pairs, self._insert_inh = None, None
        if verdict != cs.NEW or c is None:
            raise SearchError(f"the root was not kept ({verdict})")
        self.emit_cell(cs.NEW, c, None)
        niches: Dict[int, rs.Niche] = {c.cid: rs.seed_niche(osel.ROOT_MASK)}
        self.root["cid"] = c.cid
        if self.resume_plan is not None:
            niches.update(self.insert_resumed())
        y_of = (lambda cid: float(self.archive.cells[int(cid)].end[OBS_Y])) if self.pace.cut_y is not None else None
        self.selector = osel.OrderSelector(self.archive, self.dp, niches=niches, breaks=self.tick_view(), best_claim=None,
                                           inherited_until=self.inherited_until, y_of=y_of)
        self.sets_orders_open = self.sets_orders()
        if self.pace.cut_y is not None:                      # owner 2026-11-19: the inherited cells the cut makes undrawable (they stay kept)
            self.cut_open = self.selector.cut_undrawable()
            self.log(f"fall cut: y < {self.pace.cut_y:g} at levels >= {self.pace.open_from} not kept, not drawable; inherited cells made undrawable "
                     f"at the open, per level: {json.dumps(self.cut_open)}")
        if self.pace.bound is not None:                      # owner 2026-11-20 (v7): the inherited cells the bound makes undrawable (kept)
            self.bound_open = self.selector.bound_undrawable()
            self.log(f"record bound: tick >= {self.pace.bound} at levels >= {self.pace.open_from} not kept, not drawable; inherited cells made "
                     f"undrawable at the open, per level: {json.dumps(self.bound_open)}")
        if self.pace.dir_key:                                # owner 2026-11-20 (v7)
            self.log(f"floor-direction key: moving floor lines {list(MOVING_FLOOR_LINES)}, period {PLATFORM_PERIOD}, down on residues "
                     f"{PLATFORM_DOWN[0]}..{PLATFORM_DOWN[1] - 1}; inherited moving-floor cells per level|direction: "
                     f"{json.dumps((self.resume_plan or {}).get('floor_direction_cells'))}")
        if self.readiness_use and self.readiness_use.get("applied"):
            self.event(f"READINESS OVERRIDE (owner): free commit {self.readiness_use['commit_free_mb']:.0f} MB admitted at >= "
                       f"{self.readiness_use['min_commit_free_mb']} MB (registered {self.readiness_use['registered_min_commit_free_mb']} MB); "
                       f"reason: {self.readiness_use['reason']}")
        self.phase_wall["open"] = round(env.now() - self.t0, 1)
        self.log(f"open done in {self.phase_wall['open']:.0f} s; {cfg.n_workers} workers ready; root cell {c.cid} (key {list(c.key)}); pace lines "
                 f"{self.order_plan['pace']['lines']}; claim threshold {self.order_plan['claim_threshold']}; params {self.dp.as_record()}; arm {cs.ARM_NAME} {self.arm}")
        self.write_progress()

    def tick_view(self) -> "TickView":
        return TickView(self.breaks_of)

    def insert_resumed(self) -> Dict[int, rs.Niche]:
        """The resume (owner 2026-11-16): the planned sequence through the archive's keep rule (each verdict must be the plan's), one
        cells.jsonl row per insertion (origin kind resume: its folder, D cell id and digest, niche and break pairs). Returns the niches of the
        inherited representatives. Their dispatch counts and retirement start from zero; they meet no milestone."""
        niches: Dict[int, rs.Niche] = {}
        counts: Counter = Counter()
        for e in self.resume_seq:
            cd = e["cand"]
            pairs = break_pairs(cd["breaks"])
            origin = {"kind": RESUME_KIND, "folder": cd["folder"], "d_archive_id": cd["d_archive_id"], "d_cid": int(cd["d_cid"]), "d_digest": cd["digest"],
                      "niche": cd["niche"]}
            self._insert_pairs, self._insert_inh = pairs, int(cd["tick"])   # a resumed cell: every break of its words is inherited
            try:
                verdict, c = self.archive.keep(tuple(cd["key"]), int(cd["level"]), int(cd["tick"]), bytes.fromhex(cd["words_hex"]), tuple(cd["end"]),
                                               bytes.fromhex(cd["end_digest"]), bytes.fromhex(cd["chain"]), origin, 0)
            finally:
                self._insert_pairs, self._insert_inh = None, None
            if verdict != e["verdict"] or c is None:
                raise SearchError(f"resume: D cell {cd['d_cid']} of {cd['folder']} was {verdict}; the plan says {e['verdict']}")
            niches[c.cid] = rl3.niche_of_label(cd["niche"])
            counts[verdict] += 1
            row = {"ev": verdict, "cid": c.cid, "key": list(c.key), "level": c.level, "tick": c.tick, "lead": c.lead, "slack": self.archive.slack_of(c.tick),
                   "digest": c.digest, "end_digest": c.end_digest.hex(), "chain": c.chain.hex(), "origin": c.origin, "n": 0, "seen": c.seen, "replaced": c.replaced,
                   "first_at_level": False, "utc": g.utc(), "words_hex": c.words.hex(), "end": list(c.end), "niche": cd["niche"],
                   "group": rs.glabel((int(c.level), int(c.key[3]), cd["niche"]))}
            if verdict == cs.REPLACED and c.previous:
                row["previous"] = dict(c.previous)
            with self._lock:
                self.fs.append_jsonl(self.dir / "cells.jsonl", row)
        for cid, niche in niches.items():                   # the inherited bests over the representatives the archive holds
            self.note_arrival(self.sb, self.archive.cells[cid], self.breaks_of[cid], niche, in_night=False)
        self.resume_open = {"inserted": {k: int(v) for k, v in sorted(counts.items())}, "cells": len(niches), "set_digest": self.resume_plan["set_digest"]}
        self.log(f"resume: {len(niches)} cells inherited from {len(self.resume_folders)} D folder(s) ({json.dumps(self.resume_open['inserted'])}; set "
                 f"{self.resume_plan['set_digest'][:16]}); counts and retirement start at zero")
        if self.resume_child:                               # owner 2026-11-21: the sequence is not read after the insertion; drop it
            self.resume_seq = []
            self.log(f"resume in a child process: {json.dumps(self.resume_child_info)}; the insertion sequence is dropped")
        return niches

    def sets_orders(self) -> Dict[str, Dict[str, int]]:
        """Per level: cells, distinct target sets (live masks) and orders (niches) among the selector's cells (report-only)."""
        per: Dict[int, Dict[str, set]] = {}
        for _cid, gk in self.selector.group.items():
            d = per.setdefault(int(gk[0]), {"cells": set(), "sets": set(), "orders": set()})
            d["cells"].add(_cid)
            d["sets"].add(int(gk[1]))
            d["orders"].add(str(gk[2]))
        return {str(lv): {k: len(v) for k, v in per[lv].items()} for lv in sorted(per, reverse=True)}

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
                            "root": c.root, "inherited": c.inherited, "cleared": c.cleared, "fused": False,
                            "d_pairs0": tuple(self.breaks_of[int(c.cid)]), "d_mask0": int(c.key[3]), "d_res": str(c.key[2]),
                            "d_inh0": int(self.inherited_until.get(int(c.cid), 0))}
        self.reserved += int(want)
        return job

    # -- ingest: milestones ------------------------------------------------------------------------------------------------------------------

    def emit(self, row: Dict[str, Any]) -> None:
        """The burst row carries its exploration extent (owner 2026-11-16, report-only; level-6 extents also feed the scoreboard) and its
        break record (E1, owner 2026-11-18, report-only), with the hitter fields when the hitter record is on (owner 2026-11-19)."""
        if self._cur is not None and row.get("kind", "burst") == "burst" and row.get("n") == self._cur[0]["n"]:
            res = self._cur[1]
            ext = burst_extent(res.get("reaches") or [], res.get("breaks_all") or [], self.pace)
            row["extent"] = ext
            row["break_record"] = break_record(res, self.hitter)
            if self.hitter:
                self.note_hitters(res, row["break_record"])
            for e in ext.values():
                if int(e["level"]) == 6:
                    acc = self.sb["extent6"].setdefault(str(e["mask"]), {})
                    for gname in EXTENT_GROUPS:
                        if gname in e:
                            merge_extent(acc.setdefault(gname, {}), e[gname], int(row["n"]))
        super().emit(row)

    def note_hitters(self, res: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> None:
        """The hitter record's night counts (report-only): credited breaks by kind and by level, why a break is unavailable, the jobs that
        carried the worker's record and the tracker's own errors."""
        hs = self.hit_stats
        rec = res.get("d_hitters")
        hs["jobs_with_record" if rec is not None else "jobs_without_record"] += 1
        hs["tracker_errors"] += len((rec or {}).get("errors") or [])
        for e in entries:
            hs["credited"] += 1
            hs["by_kind"][str(e["hitter"])] += 1
            hs["by_level_kind"][f"{int(e['level'])}|{e['hitter']}"] += 1
            if e["hitter"] == "unavailable":
                hs["unavailable_why"][str(e.get("hitter_why"))] += 1

    def hitter_summary(self) -> Optional[Dict[str, Any]]:
        if not self.hitter:
            return None
        hs = self.hit_stats
        by_level: Dict[str, Dict[str, int]] = {}
        for k, v in sorted(hs["by_level_kind"].items(), key=lambda kv: (-int(kv[0].split("|", 1)[0]), kv[0])):
            lv, kind = k.split("|", 1)
            by_level.setdefault(lv, {})[kind] = int(v)
        return {"contract": ow.HITTER_CONTRACT, "worker": ow.ORDER_WORKER_CONTRACT, "search_flags_added": dict(ow.ENTITY_FLAGS),
                "credited_breaks": hs["credited"], "by_kind": {k: int(hs["by_kind"].get(k, 0)) for k in ow.KINDS}, "by_level": by_level,
                "unavailable_why": dict(hs["unavailable_why"]), "jobs_with_record": hs["jobs_with_record"],
                "jobs_without_record": hs["jobs_without_record"], "tracker_errors": hs["tracker_errors"]}

    def commit(self, info: Mapping[str, Any], c: cs.Cell, res: Mapping[str, Any]) -> None:
        super().commit(info, c, res)
        self.log_milestones(info)
        self.score_dispatch(info, res)

    def score_dispatch(self, info: Mapping[str, Any], res: Mapping[str, Any]) -> None:
        """Scoreboard counters of one ingested burst (report-only), and the check of its boundary answers against its exact break ticks."""
        sb = self.sb
        lv0 = str(int(info["level"]))
        sb["dispatches"][lv0] += 1
        sb["dispatches_res"][f"{lv0}|{info.get('d_res')}"] += 1
        L = int(res["L"])
        n_words = len(res.get("words") or b"")
        sb["bursts"][str(n_words)] += 1
        sb["bursts_by_level"].setdefault(lv0, Counter())[str(n_words)] += 1
        row = self._row or {}
        if row.get("n") == info.get("n") and row.get("outcome") == "clear" and (row.get("claimed") or {}).get("completion_input_tick") is not None:
            t10 = int(row["claimed"]["completion_input_tick"])
            rec10 = {"tick": t10, "elapsed_s": round(self.elapsed(), 1), "n": int(info["n"]), "cid": int(info["cid"]), "order": None}
            sb["first"].setdefault(str(osel.TARGETS_TOTAL), rec10)
            if str(osel.TARGETS_TOTAL) not in sb["best"] or t10 < sb["best"][str(osel.TARGETS_TOTAL)]["tick"]:
                sb["best"][str(osel.TARGETS_TOTAL)] = rec10
        allp = break_pairs(res.get("breaks_all"))
        obs_at = {int(r[0]): r[2] for r in (res.get("reaches") or [])}
        evs = hitter_events(res) if self.hitter else {}
        for idx, (t, _i) in enumerate(allp):
            if int(t) <= L:
                continue
            d = sb["breaks"].setdefault(str(idx + 1), {"breaks": 0, "hitter": Counter(), "status_at_break": Counter()})
            d["breaks"] += 1
            if self.hitter:                                 # owner 2026-11-19: the hitter record's kind (report-only)
                d["hitter"][str(hitter_fields(evs.get((int(t), int(_i))))["hitter"])] += 1
            else:
                d["hitter"]["unknown (entity off)"] += 1
            o = obs_at.get(int(t))
            d["status_at_break"]["no reach at the break tick" if o is None else self.clf.name(o[OBS_STATUS])] += 1
        for e in info.get("cont") or []:
            if e[2] is None:
                continue
            tick = int(e[4])
            p = [x for x in allp if int(x[0]) <= tick]
            lv = len(p)
            arr = osel.arrival_tick([x[0] for x in p], lv) if lv < osel.TARGETS_TOTAL else None
            go = lv < osel.TARGETS_TOTAL and self.pace.continues(lv, tick, [x[0] for x in p])   # v7: and not past the record bound
            self.c["cont_checked"] += 1
            if [int(e[2]), e[3], bool(e[5])] != [lv, arr, go]:
                self.c["cont_mismatches"] += 1
                self.event(f"boundary answer of dispatch {info['n']} segment {e[0]}: recorded level {e[2]} arrival {e[3]} go {e[5]}, exact {lv} {arr} {go}")

    def window_decision(self, info: Dict[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
        """The continuation rule (owner 2026-11-16): the job's mask followed through the reaches of every boundary question so far (each
        holds its whole segment), the state at the boundary inside the arrival rule and (v7, owner 2026-11-20) not at a level >= K at a tick
        >= the record bound. From the job's own trajectory only."""
        tr = info.setdefault("d_track", {"pairs": list(info["d_pairs0"]), "mask": int(info["d_mask0"]), "seen_to": int(payload["L"])})
        for rj, rk in sorted(((int(r[0]), r[1]) for r in payload["reaches"]), key=lambda x: x[0]):
            if rj <= tr["seen_to"]:
                continue
            m = int(rk[3])
            if m != tr["mask"]:
                if m & ~tr["mask"]:
                    raise SearchError(f"dispatch {info['n']}: a live target came back at tick {rj} ({tr['mask']:#x} -> {m:#x})")
                tr["pairs"] += [(rj, i) for i in range(osel.TARGETS_TOTAL) if (tr["mask"] >> i) & 1 and not (m >> i) & 1]
                tr["mask"] = m
        t_now = int(payload["L"]) + int(payload["words"])
        tr["seen_to"] = t_now
        lv = mcell.level_of_mask(tr["mask"])
        if lv >= osel.TARGETS_TOTAL:
            return {"go": False, "level": lv, "arrival": None, "tick": t_now}
        ticks = sorted(int(t) for t, _i in tr["pairs"])
        arrival = osel.arrival_tick(ticks, lv)
        return {"go": self.pace.continues(lv, t_now, ticks), "level": lv, "arrival": arrival, "tick": t_now}

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
        if self.pace.cut_y is not None:                      # owner 2026-11-19: only with the fall cut (report-only)
            rec["fall_cut"] = {"reaches": self.pace.cut.snapshot(), "grounded_spared": self.pace.cut.spared_snapshot(),
                               "undrawable_cells": sel.cut_undrawable()}
            if self.pace.spare_one_live:                     # owner 2026-11-20 (v7): only with the exemption
                rec["fall_cut"]["one_live_spared"] = self.pace.cut.one_live_snapshot()
        if self.pace.bound is not None:                      # owner 2026-11-20 (v7): only with the record bound (report-only)
            rec["record_bound"] = {"reaches": self.pace.bound_reaches.snapshot(), "undrawable_cells": sel.bound_undrawable()}
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
        rec = self._config_record(ready, c, p, mods)
        if self.hitter:                                     # owner 2026-11-19: only with the option, so the record with it off is v4's
            rec["hitter_record"] = dict(self.hitter_plan or {}, search_flags=dict(fv.FLAGS_EXPLORE, **ow.ENTITY_FLAGS),
                                        worker_module_sha256=lf_sha256(Path(ow.__file__)))
        if self.resume_child:                               # owner 2026-11-21: only with the option
            rec["resume_child"] = dict(self.resume_child_plan or {}, derivation=self.resume_child_info)
        return rec

    def _config_record(self, ready: Mapping[str, Any], c: Any, p: Mapping[str, Any], mods: Sequence[Any]) -> Dict[str, Any]:
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
                "root": p["root"], "pace": p["pace"], "milestones": p["milestones"], "gate": p["gate"], "gate_reference": p.get("gate_reference"),
                "keep_rule": p.get("keep_rule"), "continuation": p.get("continuation"), "frontier": p["frontier"], "claim_threshold": p["claim_threshold"],
                "sources": p["sources"], "rng_seed": int(self.p.rng_seed),
                "resume": None if self.resume_plan is None else {k: v for k, v in self.resume_plan.items() if k != "reports"},
                "origins": {"root": "two fresh-process tick-0 reads at the open (section 5.1); the tick-0 record is every dispatch's pin",
                            "keep": "the arrival rule (order_select_v2): L-th break <= line(L) and own tick <= line(L + 1), line(L) = (G x L) // 10 + s; "
                                    "run 3's keep rule inside it",
                            "continuation": CONT_RULE,
                            "resume": "--resume-from D folders: final representatives through the arrival rule, then the archive's keep rule at the open; "
                                      "counts and retirement from zero; no milestone from an inherited cell",
                            "selection": "tools/frs/order_select.OrderSelector (section 3; gaps A-F, G1-G5); no trigger draws",
                            "draw_id": f"<archive id>|{KEY_FAMILY}|<prefix words digest>, iteration k = 0.. per representative",
                            "claims": "a clear faster than the frontier's best (read at the plan), then than D's own best, verified twice from tick 0 (run 3)",
                            "milestones": "first cell kept in the night with at least L targets whose L-th break came at or before line(L); clear line on the "
                                          "completion input tick; verified at the close by two fresh-process replays (D-Q8)",
                            "rng": "keyed draws (det_schedule), seed --rng-seed; native RNG never read"}}

    def summary(self) -> Dict[str, Any]:
        s = cs.Search.summary(self)
        s["contract"] = ORDER_CONTRACT
        th = s.get("throughput") or {}                       # owner 2026-11-16: run 3's figure counts every NEW verdict, the root and the
        wall = self.search_wall if self.search_wall else max(0.0, self.env.now() - self.t_search)  # resumed cells included; D's counts the
        th["new_cells_per_h"] = round(self.c["new_in_night"] / max(1e-9, wall / 3600.0), 1)       # cells kept by the night's dispatches only
        th["new_cells_per_h_basis"] = "cells kept as NEW by the night's dispatches (the root and the resumed cells excluded)"
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
                      "niche_live": dict(self.niche_live), "exports": list(self.exports), "text_replays": list(self.text_replays), "hourly_records": list(self.hourly),
                      "keep_rule": self.order_plan.get("keep_rule"), "continuation": {"rule": cont_rule(self.pace), "checked": self.c["cont_checked"],
                                                                                      "mismatches": self.c["cont_mismatches"]},
                      "resume": None if self.resume_plan is None else {"plan": {k: self.resume_plan.get(k) for k in ("counts", "dropped_rule_reasons", "inserts",
                                                                                                                   "cells_after", "set_digest", "root")},
                                                                       "open": dict(self.resume_open), "root_equal": self.root.get("resume_root_equal"),
                                                                       "folders": [f["dir"] for f in self.resume_plan.get("folders") or []]},
                      "scoreboard": self.scoreboard}
        if self.hitter:                                     # owner 2026-11-19: only with the option
            s["order"]["hitter_record"] = self.hitter_summary()
        if self.resume_child and s["order"].get("resume") is not None:   # owner 2026-11-21: only with the option (report-only)
            s["order"]["resume"]["child"] = {"contract": RESUME_CHILD_CONTRACT, "derivation": self.resume_child_info,
                                             "sequence_dropped": not self.resume_seq}
        if self.pace.cut_y is not None:                     # owner 2026-11-19: only with the fall cut (report-only)
            s["order"]["fall_cut"] = {"y": float(self.pace.cut_y), "from_level": self.pace.open_from, "reaches_cut": self.pace.cut.summary(),
                                      "grounded_spared": self.pace.cut.spared_summary(),
                                      "reaches_cut_total": int(self.c.get("cut_reaches", 0)), "inherited_undrawable_at_open": dict(self.cut_open),
                                      "undrawable_cells_now": sel.cut_undrawable() if sel is not None else {}}
            if self.pace.spare_one_live:                    # owner 2026-11-20 (v7): only with the exemption
                s["order"]["fall_cut"]["one_live_spared"] = self.pace.cut.one_live_summary()
        if self.pace.bound is not None:                     # owner 2026-11-20 (v7): only with the record bound (report-only)
            s["order"]["record_bound"] = {"bound": int(self.pace.bound), "from_level": self.pace.open_from, "reaches_not_kept": self.pace.bound_reaches.summary(),
                                          "reaches_not_kept_total": int(self.c.get("bound_reaches", 0)), "inherited_undrawable_at_open": dict(self.bound_open),
                                          "undrawable_cells_now": sel.bound_undrawable() if sel is not None else {}}
        if self.pace.dir_key:                               # owner 2026-11-20 (v7): only with the direction key (report-only counts)
            mf: Counter = Counter()
            for c in self.archive.cells:
                if c.key is not None and str(c.key[2]) == mcell.RES_GROUNDED and int(c.key[4]) >= DIR_FLOOR_OFFSET[DIR_UP]:
                    mf[f"{int(c.level)}|{DIR_DOWN if int(c.key[4]) >= DIR_FLOOR_OFFSET[DIR_DOWN] else DIR_UP}"] += 1
            s["order"]["floor_direction_key"] = {"definition": self.dir_plan, "cells_by_level_direction": {k: int(mf[k]) for k in sorted(mf)},
                                                 "inherited_at_plan": (self.resume_plan or {}).get("floor_direction_cells")}
        return s

    def build_scoreboard(self, s: Mapping[str, Any]) -> Dict[str, Any]:
        """The fixed close record (owner 2026-11-16), report-only: read by no rule."""
        sel, sb = self.selector, self.sb
        levels_in_archive = sorted({int(c.level) for c in self.archive.cells if c.words is not None and c.level < osel.TARGETS_TOTAL})
        deepest_in_night = max((int(k) for k in sb["first"]), default=None)
        per_level: Dict[str, Dict[str, Any]] = {}
        readout = sel.level_readout() if sel is not None else {}
        for L in range(1, osel.TARGETS_TOTAL + 1):
            k = str(L)
            row = {"line": self.pace.line(L), "first_in_night": sb["first"].get(k), "best_in_night": sb["best"].get(k), "inherited_best": sb["inherited_best"].get(k)}
            if any(v is not None for v in row.values() if not isinstance(v, int)):
                per_level[k] = row
        sets_orders_close = self.sets_orders() if sel is not None else {}
        cells6: Dict[str, Dict[str, Any]] = {}
        for c in self.archive.cells:
            if c.words is None or not 6 <= int(c.level) < osel.TARGETS_TOTAL:
                continue
            src = "inherited" if (c.origin or {}).get("kind") == RESUME_KIND else "night"
            d = cells6.setdefault(str(c.level), {"cells": 0, "by_resource_class": Counter(), "grounded": 0, "airborne": 0, "by_source": Counter()})
            d["cells"] += 1
            d["by_resource_class"][str(c.key[2])] += 1
            d["grounded" if int(c.end[OBS_GROUND]) == 0 else "airborne"] += 1
            d["by_source"][src] += 1
        kept6: Dict[str, Dict[str, Any]] = {}             # the archive's level-6 cells per target set: the same extremes, from end records
        for c in self.archive.cells:
            if c.words is None or int(c.level) != 6:
                continue
            k6 = kept6.setdefault(str(int(c.key[3])), {"cells": 0, "max_y": None, "min_x": None, "max_x": None})
            k6["cells"] += 1
            x, y = float(c.end[OBS_X]), float(c.end[OBS_Y])
            for k, v, better in (("max_y", y, lambda a, b: a > b), ("min_x", x, lambda a, b: a < b), ("max_x", x, lambda a, b: a > b)):
                if k6[k] is None or better(v, k6[k][0]):
                    k6[k] = [v, int(c.tick), int(c.cid)]
        extent6 = {m: {"bursts": {g_: dict(sb["extent6"].get(m, {}).get(g_) or {}) for g_ in EXTENT_GROUPS}, "kept_cells": kept6.get(m)}
                   for m in sorted(set(sb["extent6"]) | set(kept6), key=int)}
        left: List[str] = []
        wd = self.dir / "workers"
        if wd.is_dir():
            for w in sorted(p for p in wd.iterdir() if p.is_dir()):
                for sub in ("rt", "ep"):
                    if (w / sub).is_dir():
                        left += [f"{w.name}/{sub}/{x.name}" for x in sorted((w / sub).iterdir())]
        ver = {v["milestone"]: v for v in self.ms_verifications}
        m1row = self.ms_rows.get("M1") or {}
        ref = self.order_plan.get("gate_reference") or {}
        b6 = sb["best"].get("6")
        work, integ = s.get("work") or {}, s.get("integrity") or {}
        dispatched = {lv: int(n) for lv, n in sorted(sb["dispatches"].items(), key=lambda kv: -int(kv[0]))}
        res6 = {k.split("|", 1)[1]: int(v) for k, v in sorted(sb["dispatches_res"].items()) if k.split("|", 1)[0] == "6"}
        deep = {}
        for k, v in sorted(sb["deep"].items()):
            lv, verdict = k.split("|", 1)
            deep.setdefault(lv, {})[verdict] = int(v)
        return {
            "deepest_level": {"in_archive": max(levels_in_archive, default=None), "first_reached_in_night": deepest_in_night},
            "levels": per_level,
            "sets_orders": {"open": self.sets_orders_open, "close": sets_orders_close},
            "level6plus_cells": {lv: {"cells": d["cells"], "by_resource_class": dict(sorted(d["by_resource_class"].items())), "grounded": d["grounded"],
                                      "airborne": d["airborne"], "by_source": dict(d["by_source"])} for lv, d in sorted(cells6.items(), key=lambda kv: -int(kv[0]))},
            "break_attribution": {lv: {"breaks": d["breaks"], "hitter": dict(d["hitter"]), "status_at_break": dict(d["status_at_break"].most_common())}
                                  for lv, d in sorted(sb["breaks"].items(), key=lambda kv: -int(kv[0]))},
            "break_attribution_note": ((f"hitter = the hitter record's kind ({ow.HITTER_CONTRACT}, owner 2026-11-19, report-only: mario / projectile / "
                                        f"unseen / ambiguous / unavailable); status_at_break is Mario's status class on the break tick (the reach at "
                                        f"that tick)") if self.hitter else
                                       "hitter unknown: the entity block is off in search workers; status_at_break is Mario's status class on the break "
                                       "tick (the reach at that tick), not a hitter"),
            "dispatches_by_level": dispatched,
            "level6_dispatches_by_start_resource_class": res6,
            "dispatches_by_level_and_resource_class": {k: int(v) for k, v in sorted(sb["dispatches_res"].items())},
            "retirements": {"events_by_level": {k: int(v) for k, v in sorted(sel.retired_by_level.items(), key=lambda kv: -int(kv[0]))} if sel else {},
                            "retired_at_close_by_level": {lv: d.get("retired") for lv, d in readout.items()}},
            "new_cells_in_night_by_level": {k: int(v) for k, v in sorted(sb["new_by_level"].items(), key=lambda kv: -int(kv[0]))},
            "deep_reaches": {"min_level": DEEP_REACH_LEVEL, "total": self.c["deep_reaches"], "by_level_and_verdict": deep, "file": "deep_reaches.jsonl"},
            "burst_lengths": {"all": {k: int(v) for k, v in sorted(sb["bursts"].items(), key=lambda kv: int(kv[0]))},
                              "by_start_level": {lv: {k: int(v) for k, v in sorted(c.items(), key=lambda kv: int(kv[0]))}
                                                 for lv, c in sorted(sb["bursts_by_level"].items(), key=lambda kv: -int(kv[0]))}},
            "continuation": {"boundaries": self.c["boundaries"], "continued": self.c["continued"], "checked": self.c["cont_checked"],
                             "mismatches": self.c["cont_mismatches"]},
            "m1": {"official": {"line": self.pace.line(6), "slack": self.dp.slack, "met": "M1" in self.ms_rows, "tick": m1row.get("tick"),
                                "cell_tick": m1row.get("cell_tick"), "n": m1row.get("n"), "verdict": (ver.get("M1") or {}).get("verdict")},
                   "reference": {"line": ref.get("line"), "slack": ref.get("slack"), "earliest_6th_break_in_night": None if b6 is None else b6["tick"],
                                 "order": None if b6 is None else b6["order"], "met": b6 is not None and ref.get("line") is not None and b6["tick"] <= int(ref["line"]),
                                 "verified_by_M1_replays": (ver.get("M1") or {}).get("verdict") == M_VERIFIED and m1row.get("tick") is not None
                                 and ref.get("line") is not None and int(m1row["tick"]) <= int(ref["line"])},
                   "inherited_earliest_6th_break": (sb["inherited_best"].get("6") or {}).get("tick")},
            "integrity": {"status": s.get("status"), "stop": (s.get("stop") or {}).get("reason"),
                          **{k: work.get(k) for k in ("mismatches", "tick0_unequal", "lifecycle_failures", "aborted", "fused_mismatch")},
                          **{k: integ.get(k) for k in ("guard_violations_main", "battleship_left", "root_equal", "order_code_digest", "order_code_digest_end",
                                                       "order_code_changed_during_run", "lab_code_changed_during_run", "milestones_not_verified")},
                          "resume_root_equal": self.root.get("resume_root_equal"), "cont_mismatches": self.c["cont_mismatches"]},
            "lowest_free_commit_mb": _finite((self.sampler.peak or {}).get("system_commit_free_min_mb")) if self.sampler is not None else None,
            "leftover_worker_folders": left,
            "level6_extents": extent6,
            "level6_extents_note": "per level-6 target set (live mask): bursts' highest y / lowest x / highest x as [value, tick, dispatch] over all "
                                   "reaches and over reaches inside the keep window; kept cells' as [value, tick, cell id] from end records"}

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
        try:
            self.scoreboard = self.build_scoreboard(s)
        except Exception as exc:  # noqa: BLE001 - a report, never the close
            self.scoreboard = {"error": f"{type(exc).__name__}: {exc}"[:400]}
            self.log(f"the scoreboard failed: {self.scoreboard['error']}")
        s["order"]["scoreboard"] = self.scoreboard
        self.fs.write_text(self.dir / "summary.json", frep.compact_json(s), atomic=True)
        self.fs.write_text(self.dir / "report.md", report_md(s), atomic=True)
        self.fs.write_text(self.dir / "progress.md", progress_md(s, final=True), atomic=True)
        return s

    def write_progress(self) -> None:
        try:
            self.fs.write_text(self.dir / "progress.md", progress_md(self.summary(), final=False), atomic=True)
        except (OSError, g.LabRootError):
            pass


class TickView(ABCMapping):
    """The selector's view of the engine's break pairs: cell id -> sorted break ticks. A live view (the engine's dict, not a copy)."""

    def __init__(self, pairs: Mapping[int, Sequence[Tuple[int, int]]]):
        self.pairs = pairs

    def __getitem__(self, cid: int) -> Tuple[int, ...]:
        return tuple(int(t) for t, _i in self.pairs[cid])

    def __iter__(self) -> Any:
        return iter(self.pairs)

    def __len__(self) -> int:
        return len(self.pairs)


class OrderNight(det.DeterministicSchedule, ra.AnomalyIngest, OrderEngine):
    """Option D: deterministic scheduling (D4), anomaly keeping, D's engine."""

    def on_boundary(self, w: int, payload: Dict[str, Any]) -> None:
        """det_schedule.on_boundary's protocol with D's continuation rule (owner 2026-11-16, CONT_RULE) in place of F3: the answer reads the
        job's own trajectory and the pace lines only, so it is deterministic without an as-of archive. Only an abort forces "do not
        continue" (a stop for a cap lets in-flight jobs end as they would have). Each answer is recorded as [segment, reaches, level,
        arrival, tick, go] in the dispatch row's `cont`, and recomputed from the job's exact break ticks at the ingest."""
        info = self.inflight.get(w)
        aborting = self.pool is not None and self.pool.abort.is_set()
        if aborting or info is None or info["k"] != int(payload["iteration"]):
            d: Dict[str, Any] = {"go": False, "level": None, "arrival": None, "tick": None}
        else:
            d = self.window_decision(info, payload)
        go = bool(d["go"])
        self.c["boundaries"] += 1
        self.c["continued"] += int(go)
        if info is not None:
            info["cont"].append([int(payload["segment"]), len(payload["reaches"]), d.get("level"), d.get("arrival"), d.get("tick"), int(go)])
        try:
            self.pool.conns[w].send(("continue", {"iteration": payload["iteration"], "segment": payload["segment"], "go": go}))
        except (OSError, BrokenPipeError):
            pass


# -- rendering ----------------------------------------------------------------------------------------------------------------------------------


def _f(x: Any) -> str:
    return frep.fmt(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else ("-" if x is None else str(x))


def _finite(x: Any) -> Any:
    return None if x is None or (isinstance(x, float) and x in (float("inf"), float("-inf"))) else (round(x, 1) if isinstance(x, float) else x)


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


def scoreboard_md(sc: Optional[Mapping[str, Any]]) -> List[str]:
    """The fixed scoreboard (owner 2026-11-16) as markdown; report-only."""
    if not sc:
        return ["", "## Scoreboard", "", "- not built"]
    if sc.get("error"):
        return ["", "## Scoreboard", "", f"- failed: {sc['error']}"]
    so = sc.get("sets_orders") or {}
    out = ["", "## Scoreboard (report-only)", "", f"- deepest level: in the archive {_f((sc['deepest_level'] or {}).get('in_archive'))}, "
           f"first reached in the night {_f((sc['deepest_level'] or {}).get('first_reached_in_night'))}", "",
           "| level | line | first in night (tick, wall s, dispatch) | best in night (tick, order) | inherited best (tick, order) | sets / orders open | sets / orders close | dispatches | retirements |",
           "| ---: | ---: | --- | --- | --- | --- | --- | ---: | ---: |"]
    for L in range(10, 0, -1):
        k = str(L)
        row = (sc.get("levels") or {}).get(k) or {}
        fi, be, ih = row.get("first_in_night") or {}, row.get("best_in_night") or {}, row.get("inherited_best") or {}
        op, cl = (so.get("open") or {}).get(k) or {}, (so.get("close") or {}).get(k) or {}
        disp = (sc.get("dispatches_by_level") or {}).get(k)
        ret = ((sc.get("retirements") or {}).get("events_by_level") or {}).get(k)
        if not (fi or be or ih or op or cl or disp):
            continue
        out.append(f"| {L} | {_f(row.get('line'))} | {_f(fi.get('tick'))}, {_f(fi.get('elapsed_s'))}, {_f(fi.get('n'))} | {_f(be.get('tick'))}, {be.get('order') or '-'} | "
                   f"{_f(ih.get('tick'))}, {ih.get('order') or '-'} | {_f(op.get('sets'))} / {_f(op.get('orders'))} | {_f(cl.get('sets'))} / {_f(cl.get('orders'))} | "
                   f"{_f(disp)} | {_f(ret)} |")
    m1 = sc.get("m1") or {}
    of, rf = m1.get("official") or {}, m1.get("reference") or {}
    out += ["", f"- M1 at {of.get('line')} (slack {of.get('slack')}): met {of.get('met')}, tick {_f(of.get('tick'))}, verdict {of.get('verdict')}; "
                f"M1 at {rf.get('line')} (slack {rf.get('slack')}, report-only): earliest in-night 6th break {_f(rf.get('earliest_6th_break_in_night'))} "
                f"({rf.get('order') or '-'}), met {rf.get('met')}, verified by M1's replays {rf.get('verified_by_M1_replays')}; inherited earliest 6th break "
                f"{_f(m1.get('inherited_earliest_6th_break'))}",
            f"- level 6+ cells: {json.dumps(sc.get('level6plus_cells'))}",
            f"- level-6 extents (bursts all / inside the window / kept cells): {json.dumps(sc.get('level6_extents'))}",
            f"- level-6 dispatches by starting resource class: {json.dumps(sc.get('level6_dispatches_by_start_resource_class'))}",
            f"- break attribution ({sc.get('break_attribution_note')}): {json.dumps(sc.get('break_attribution'))}",
            f"- reaches at level >= {(sc.get('deep_reaches') or {}).get('min_level')}: {(sc.get('deep_reaches') or {}).get('total')} "
            f"{json.dumps((sc.get('deep_reaches') or {}).get('by_level_and_verdict'))} (each in deep_reaches.jsonl)",
            f"- burst lengths (words): {json.dumps((sc.get('burst_lengths') or {}).get('all'))}; continuation {json.dumps(sc.get('continuation'))}",
            f"- integrity: {json.dumps(sc.get('integrity'))}",
            f"- lowest free commit {_f(sc.get('lowest_free_commit_mb'))} MB; leftover worker folders {len(sc.get('leftover_worker_folders') or [])} "
            f"{(sc.get('leftover_worker_folders') or [])[:12]}"]
    return out


def report_md(s: Mapping[str, Any]) -> str:
    o = s.get("order") or {}
    lines = ["# Option D: night report", ""] + _summary_lines(s) + scoreboard_md(o.get("scoreboard"))
    kr = o.get("keep_rule") or {}
    if kr.get("open_line_from") is not None:
        lines += ["", "## Open line (owner 2026-11-18)", "", f"- from level {kr['open_line_from']}: {kr.get('open_rule')}; archive bound {kr.get('archive_bound')}"]
    fc = o.get("fall_cut")
    if fc:
        lines += ["", "## Fall cut (owner 2026-11-19)", "", f"- {kr.get('fall_cut_rule')}",
                  f"- reaches not kept by the cut: {fc.get('reaches_cut_total')}; per level {json.dumps(fc.get('reaches_cut'))}; grounded reaches below "
                  f"Y spared, per level {json.dumps(fc.get('grounded_spared'))} (inherited, at the plan: "
                  f"{json.dumps(kr.get('fall_cut_inherited_grounded_spared'))})",
                  f"- inherited cells made undrawable at the open {json.dumps(fc.get('inherited_undrawable_at_open'))} (plan: "
                  f"{json.dumps(kr.get('fall_cut_inherited_undrawable'))}); undrawable at the close {json.dumps(fc.get('undrawable_cells_now'))}"]
        if fc.get("one_live_spared") is not None:
            lines.append(f"- one live target (owner 2026-11-20): {kr.get('fall_cut_one_live')}; reaches spared, per level "
                         f"{json.dumps(fc.get('one_live_spared'))} (inherited, at the plan: {json.dumps(kr.get('fall_cut_inherited_one_live_spared'))})")
    rb = o.get("record_bound")
    if rb:
        lines += ["", "## Record bound (owner 2026-11-20)", "", f"- {kr.get('record_bound_rule')}",
                  f"- reaches not kept by the bound: {rb.get('reaches_not_kept_total')}; per level {json.dumps(rb.get('reaches_not_kept'))}",
                  f"- inherited cells made undrawable at the open {json.dumps(rb.get('inherited_undrawable_at_open'))} (plan: "
                  f"{json.dumps(kr.get('record_bound_inherited_undrawable'))}); undrawable at the close {json.dumps(rb.get('undrawable_cells_now'))}"]
    fd = o.get("floor_direction_key")
    if fd:
        d_ = fd.get("definition") or {}
        lines += ["", "## Floor-direction key (owner 2026-11-20)", "",
                  f"- moving floor lines {d_.get('lines')}, period {d_.get('period')}, down on residues {d_.get('down_residues')}, floor field "
                  f"{json.dumps(d_.get('floor_field'))}",
                  f"- limit: {d_.get('limit')}",
                  f"- moving-floor cells at the close, per level|direction {json.dumps(fd.get('cells_by_level_direction'))} (inherited at the plan: "
                  f"{json.dumps(fd.get('inherited_at_plan'))})"]
    hr = o.get("hitter_record")
    if hr:
        lines += ["", "## Hitter record (owner 2026-11-19; report-only)", "",
                  f"- {hr.get('contract')}, search flags + {json.dumps(hr.get('search_flags_added'))}: {hr.get('credited_breaks')} credited breaks, by kind "
                  f"{json.dumps(hr.get('by_kind'))}; unavailable {json.dumps(hr.get('unavailable_why'))}; jobs with / without the record "
                  f"{hr.get('jobs_with_record')} / {hr.get('jobs_without_record')}; tracker errors {hr.get('tracker_errors')}",
                  f"- by level: {json.dumps(hr.get('by_level'))}"]
    rz = o.get("resume")
    if rz:
        lines += ["", "## Resume", "", f"- folders {rz.get('folders')}; root equal {rz.get('root_equal')}; plan {json.dumps((rz.get('plan') or {}).get('counts'))}; "
                                       f"open {json.dumps(rz.get('open'))}"]
    lines += ["", "## Rejected reaches (whole night; report-only)", ""]
    for lv, r in (o.get("rejected") or {}).items():
        lines.append(f"- level {lv}: {r['count']} rejected, earliest {r['earliest_tick']} (+{r['distance']}, {r.get('reason')}); "
                     f"late arrival {r.get('late_arrival', 0)} (min +{r.get('late_arrival_min_distance', '-')}), "
                     f"window passed {r.get('window_passed', 0)} (min +{r.get('window_passed_min_distance', '-')})")
    sel = o.get("selection") or {}
    lines += ["", "## Selection", "", f"- streams {json.dumps(sel.get('streams'))}; rotation {json.dumps(sel.get('rotation'))}",
              f"- within-1 violations at the close: {sel.get('within_one_violations')}", f"- same-tick breaks {json.dumps(sel.get('same_tick'))}",
              "", "## Integrity", "", f"- {json.dumps(s.get('integrity'), default=str)[:1500]}"]
    return "\n".join(lines) + "\n"


# -- the command line ---------------------------------------------------------------------------------------------------------------------------


def order_params_from_args(a: argparse.Namespace) -> osel.OrderParams:
    lw = tuple(float(x) for x in a.level_weights.split(",")) if a.level_weights else osel.OrderParams.level_weights
    p = osel.OrderParams(goal=a.goal, slack=a.slack, level_weights=lw, breadth_share=a.breadth_share, retire_after=a.retire_after,
                         open_line_from=a.open_line_from, fall_cut_y=getattr(a, "fall_cut_y", None),
                         fall_cut_spare_one_live=bool(getattr(a, "fall_cut_spare_one_live", False)), record_bound=getattr(a, "record_bound", None),
                         floor_direction_key=bool(getattr(a, "floor_direction_key", False)))
    p.check()
    return p


def engine_params_from_args(a: argparse.Namespace, dp: osel.OrderParams) -> C.Params3:
    return engine_params(dp, max_segments=a.max_segments, max_cells=a.max_cells, max_dispatches=a.max_dispatches, rng_seed=a.rng_seed,
                         check_slots=a.check_slots, summary_every_s=a.summary_every_s, summary_every_dispatches=a.summary_every_dispatches)


def run_command(lab: Path, frontier: Path, out: Path, a: argparse.Namespace) -> str:
    return (f"python -B tools/frs/order_search.py run --lab-root {Path(lab).as_posix()} --frontier {Path(frontier).as_posix()} --out {Path(out).as_posix()} "
            f"--rng-seed {a.rng_seed} --workers {a.workers} --max-ticks {a.max_ticks} --max-wall-min {a.max_wall_min:g} --summary-every-s {a.summary_every_s:g}"
            + (f" --max-cells {a.max_cells}" if a.max_cells != C.Params3.max_cells else "") + (f" --max-dispatches {a.max_dispatches}" if a.max_dispatches else "")
            + (f" --min-commit-free-mb {a.min_commit_free_mb} --override-reason \"{a.override_reason}\"" if a.min_commit_free_mb is not None else "")
            + (f" --goal {a.goal}" if a.goal != osel.OrderParams.goal else "") + (f" --slack {a.slack}" if a.slack != osel.OrderParams.slack else "")
            + (f" --open-line-from {a.open_line_from}" if a.open_line_from is not None else "")
            + (f" --fall-cut-y={a.fall_cut_y!r}" if getattr(a, "fall_cut_y", None) is not None else "")
            + (" --fall-cut-spare-one-live" if getattr(a, "fall_cut_spare_one_live", False) else "")
            + (f" --record-bound {a.record_bound}" if getattr(a, "record_bound", None) is not None else "")
            + (" --floor-direction-key" if getattr(a, "floor_direction_key", False) else "")
            + (" --hitter-record" if getattr(a, "hitter_record", False) else "")
            + (" --resume-child" if getattr(a, "resume_child", False) else "")
            + "".join(f" --resume-from {Path(d).as_posix()}" for d in (a.resume_from or [])))


def cmd_plan(lab: Path, frontier: Path, out: Path, a: argparse.Namespace) -> int:
    dp = order_params_from_args(a)
    ep = engine_params_from_args(a, dp)
    P = plan_and_write(lab, frontier, out, dp, ep, readiness_override=readiness_override_record(a.min_commit_free_mb, a.override_reason),
                       resume=[Path(d) for d in (a.resume_from or [])], hitter_record=bool(a.hitter_record),
                       resume_child=bool(getattr(a, "resume_child", False)))
    if P["readiness_override"]:
        print("readiness override (owner):", json.dumps(P["readiness_override"]))
    if P.get("hitter_record"):
        print("hitter record (owner 2026-11-19, report-only):", P["hitter_record"]["contract"], "search flags +", json.dumps(P["hitter_record"]["search_flags_added"]))
    if P.get("resume_child"):
        print("resume in a child process (owner 2026-11-21):", P["resume_child"]["contract"], "; the plan's own derivation also ran in a child")
    print("root:", json.dumps(P["root"]))
    print("pace lines:", json.dumps(P["pace"]["lines"]), "gate:", json.dumps(P["gate"]), "reference:", json.dumps(P["gate_reference"]))
    print("keep windows (line(L), line(L + 1)):", json.dumps(P["keep_rule"]["windows"]))
    if P["keep_rule"].get("open_line_from") is not None:
        print("open line (owner 2026-11-18):", P["keep_rule"]["open_rule"], "| archive bound", P["keep_rule"]["archive_bound"])
    if P["keep_rule"].get("fall_cut_y") is not None:
        print("fall cut (owner 2026-11-19):", P["keep_rule"]["fall_cut_rule"], "| inherited cells made undrawable, per level:",
              json.dumps(P["keep_rule"]["fall_cut_inherited_undrawable"]))
    if P["keep_rule"].get("fall_cut_one_live") is not None:
        print("fall cut, one live target (owner 2026-11-20):", P["keep_rule"]["fall_cut_one_live"], "| inherited cells spared, per level:",
              json.dumps(P["keep_rule"]["fall_cut_inherited_one_live_spared"]))
    if P["keep_rule"].get("record_bound") is not None:
        print("record bound (owner 2026-11-20):", P["keep_rule"]["record_bound_rule"], "| inherited cells made undrawable, per level:",
              json.dumps(P["keep_rule"]["record_bound_inherited_undrawable"]))
    if P["keep_rule"].get("floor_direction_key") is not None:
        print("floor-direction key (owner 2026-11-20):", json.dumps({k: v for k, v in P["keep_rule"]["floor_direction_key"].items() if k != "source"}),
              "| inherited moving-floor cells per level|direction:", json.dumps((P["resume"] or {}).get("floor_direction_cells")))
    if P["resume"]:
        rz = P["resume"]
        print("resume:", json.dumps({"folders": [f["dir"] for f in rz["folders"]], "counts": rz["counts"], "dropped_rule_reasons": rz["dropped_rule_reasons"],
                                     "set": rz["set_digest"][:16], "root": rz["root"]["digest"][:16]}))
        print("resume per level|class:", json.dumps(rz["per_level_res"]))
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
    bad = run_flag_problems(plan, dp, ep, frontier, readiness_override_record(a.min_commit_free_mb, a.override_reason), bool(a.hitter_record),
                            resume_child=bool(getattr(a, "resume_child", False))) \
        or (resume_check(plan.get("resume"), [Path(d) for d in (a.resume_from or [])]) if (plan.get("resume") or a.resume_from) else None)
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
                      readiness_override: Optional[Mapping[str, Any]] = None, hitter_record: bool = False, *, resume_child: bool = False) -> Optional[str]:
    """`run` takes exactly the plan's parameters, frontier, readiness override, hitter option and resume-child option (U10, as run 3): a flag
    that differs is refused, plan again."""
    if plan.get("readiness_override") != (None if readiness_override is None else dict(readiness_override)):
        return f"the readiness override differs from the saved plan's ({plan.get('readiness_override')}): plan again with the same flags"
    if plan.get("hitter_record") != (hitter_plan_record() if hitter_record else None):
        return (f"--hitter-record {'on' if hitter_record else 'off'} differs from the saved plan's "
                f"({'on' if plan.get('hitter_record') is not None else 'off'}, or another hitter contract): plan again with the same flags")
    if plan.get("resume_child") != (resume_child_plan_record() if resume_child else None):
        return (f"--resume-child {'on' if resume_child else 'off'} differs from the saved plan's "
                f"({'on' if plan.get('resume_child') is not None else 'off'}, or another contract): plan again with the same flags")
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
    ap.add_argument("--open-line-from", type=int, default=None, metavar="K",
                    help="owner 2026-11-18: open the pace line from level K (1-9): a state with K or more targets broken is also kept and drawable "
                         "when its K-th break <= line(K), with no line on later breaks or its own tick; the "
                         "levels >= K are one draw group (the deepest level's weight; fewest dispatches over all its cells, ties deeper level, "
                         "earlier tick, cell id); default off (order_select_v3's behaviour)")
    ap.add_argument("--fall-cut-y", type=float, default=None, metavar="Y",
                    help="owner 2026-11-19, needs --open-line-from K: at levels >= K a state whose position y is below Y and whose resource class "
                         "is not G (grounded) is not kept as a cell and is not drawable; inherited such cells stay kept but undrawable; grounded "
                         "states are spared; reaches are still recorded; default off (no change). Write a negative value as --fall-cut-y=-2700; "
                         "plan and run take the same value")
    ap.add_argument("--fall-cut-spare-one-live", action="store_true",
                    help="owner 2026-11-20, needs --fall-cut-y: the fall cut does not apply to a state with exactly one live target (level 9; "
                         "its next break is the clear); default off (no change); plan and run take the same flag")
    ap.add_argument("--record-bound", type=int, default=None, metavar="B",
                    help="owner 2026-11-20, needs --open-line-from K: at levels >= K a state whose own tick is B or later is not kept and not "
                         "drawable; inherited such cells stay kept but undrawable; a burst stops at its first boundary at a level >= K at a tick "
                         ">= B; clears and claims unchanged; default off (the archive's own bound only); plan and run take the same value")
    ap.add_argument("--floor-direction-key", action="store_true",
                    help="owner 2026-11-20: a state grounded on a moving floor line (line 19) gets the platform's direction at its tick in its "
                         "cell key (floor field + 1000 up / + 2000 down), at every level; inherited cells are re-keyed at the resume; applied in "
                         "the main process only (a same-burst revisit of a five-field key after the platform turned is not reported by the "
                         "frozen worker); default off (today's keys); plan and run take the same flag")
    ap.add_argument("--hitter-record", action="store_true",
                    help="owner 2026-11-19, report-only: D's search workers run with SSB64_RL_ENTITY=1 (tools/frs/order_worker.py) and every "
                         "break_record entry gains the hitter fields (mario / projectile with its serial, owner and first tick / unseen / "
                         "ambiguous / unavailable); nothing kept, drawn, retired or credited changes; default off (no change); plan and run "
                         "take the same flag")
    ap.add_argument("--resume-child", action="store_true",
                    help="owner 2026-11-21, needs --resume-from: the plan and the open derive the resume in a child process that exits before "
                         "the workers start (the same code, folders and options, so the same inherited cells, keys and records); the open "
                         "drops the insertion sequence once inserted; lowers the main process's memory; default off (no change); plan and run "
                         "take the same flag")
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
    ap.add_argument("--resume-from", action="append", default=[], metavar="DIR",
                    help="a D folder (order_*) to resume from, repeatable, in priority order for equal ticks (owner 2026-11-16); plan and run take the same list")
    a = ap.parse_args(argv)
    try:
        lab = g.validate_lab_root(Path(a.lab_root))
        out = g.validate_run_dir(Path(a.out) if a.out else lab / f"{FOLDER_PREFIX}{dt.date.today().isoformat()}", lab)
        frontier = g.validate_run_dir(Path(a.frontier), lab)
        a.resume_from = [g.validate_run_dir(Path(d), lab) for d in (a.resume_from or [])]
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    for d in a.resume_from:
        if not d.name.startswith(FOLDER_PREFIX):
            raise SystemExit(f"refused: a resume folder is a D folder ({FOLDER_PREFIX}*): {d}")
        if g.norm(d) == g.norm(out) or g.under(g.norm(d), g.norm(out)) or g.under(g.norm(out), g.norm(d)):
            raise SystemExit(f"refused: the resume folder {d} overlaps the output folder")
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
