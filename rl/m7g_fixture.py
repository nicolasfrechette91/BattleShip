"""M7g: Track 1 crossing fixtures -- contract, formats, digests, stage geometry and crossing evidence.

Pure functions only (no process, no socket). The game-backed side is rl/m7g_crossing.py (replay, verification,
fixture building) and rl/m7g_capture.py (live user capture); the contract is documented in
docs/rl_crossing_fixtures_m7g.md and docs/rl_crossing_fixture_m7g.schema.json.

A crossing fixture is VALIDATION EVIDENCE ONLY: a canonical Track 1 (`btt_s9_b8_v1`) action sequence, replayed from
native tick 0 in a fresh process, whose native trajectory enters the region left of the tall wall. It is never a PPO
demonstration, behaviour-cloning data, a curriculum start/prefix, reward shaping, a route label or an archive seed;
nothing in the training stack imports this module.

Formats defined here:
  * btt_track1_script_v1   human-editable run-length text: `<count> <stick> <button>` per line;
  * btt_track1_draft_v1    JSON written by the capture/import tools (a candidate, not yet a fixture);
  * btt_crossing_fixture_v1 JSON of a validated fixture (sequence + provenance + native evidence + verification).

Stage geometry is decoded from the checked-in stage source decomp/src/relocData/124_GRBonus1MarioFile2.c (the same
ROM data the port loads; M7f matched its target DObjDescs to native positions exactly). The left-of-wall boundary is
DERIVED from it: x strictly less than the minimum x of the closed solid polygon that contains the spawn floor.

Self-test:  python rl/m7g_fixture.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

REPO_ROOT = RL_DIR.parent

FIXTURE_CONTRACT = "btt_crossing_fixture_v1"
DRAFT_CONTRACT = "btt_track1_draft_v1"
CAPTURE_LOG_FORMAT = "btt_track1_capture_log_v1"
SCRIPT_FORMAT = "btt_track1_script_v1"
EVIDENCE_SCHEMA = "btt_crossing_evidence_v1"
GEOMETRY_SCHEMA = "btt_stage_geometry_mario_v1"
CROSSINGS = ("lower_precision", "upper_moving_platform")
SOURCES = ("user_recorded", "imported", "independently_searched")
TASK = {"character": "mario", "stage": "break_the_targets_mario", "game_version": "us"}
STAGE_SOURCE = REPO_ROOT / "decomp" / "src" / "relocData" / "124_GRBonus1MarioFile2.c"
LEFT_TARGET_IDS = (1, 6, 8)
TRAJECTORY_FIELDS = ("consumed_tick", "position_x", "position_y", "ground_air_state", "fighter_status_id",
                     "ground_surface")
ROUTE_RULE = "btt_route_rule_v1"
# The user-marked reference point of the lower crossing (screenshot, 2026-09-23): the top-left corner of the raised
# right step. A reference for reporting the takeoff offset, not a requirement.
MARKED_LOWER_CORNER = (2100.0, -450.0)

# Tolerances for matching a grounded native position to a flat floor line (world units). Grounded Mario stands
# exactly on flat lines in every trace checked (docs/rl_crossing_fixtures_m7g.md); the tolerance only absorbs float
# rounding and is reported, never tuned.
FLOOR_Y_TOL = 1.0
FLOOR_X_TOL = 1.0

from battleship_client import StepState  # noqa: E402  (RLStepState, port/rl/rl.h)

# M7 fall rule (btt_native_failure_v1, rl/btt_parallel.py): game_status 5 with targets left and no EpisodeEnded.
GAME_STATUS_END = 5
STEP_STATE_EPISODE_ENDED = int(StepState.EPISODE_ENDED)


class FixtureError(ValueError):
    """A sequence, draft or fixture violates its contract."""


# -- Track 1 (the frozen btt_s9_b8_v1 tables, imported, never copied) ---------------------------------

def _track1():
    import btt_learning as bl

    return bl


def track1_contract() -> str:
    return _track1().TRACK1_CONTRACT


def validate_track1(seq: Sequence[Any]) -> List[Tuple[int, int]]:
    """Every element must be one of the 72 (stick, button) index pairs. Returns plain int tuples."""
    bl = _track1()
    out: List[Tuple[int, int]] = []
    for i, a in enumerate(seq):
        try:
            out.append(bl.track1_indices(tuple(a) if isinstance(a, list) else a))
        except ValueError as exc:
            raise FixtureError(f"action {i}: {exc}") from None
    return out


def track1_to_native(seq: Sequence[Tuple[int, int]]) -> List[Tuple[int, int, int]]:
    bl = _track1()
    out = []
    for a in seq:
        n = bl.track1_to_native(a)
        out.append((int(n.buttons), int(n.stick_x), int(n.stick_y)))
    return out


def native_to_track1_exact(rows: Sequence[Tuple[int, int, int]]) -> List[Tuple[int, int]]:
    """Exact inverse; raises FixtureError naming the first row that is not one of the 72 Track 1 actions.
    Never clamps, rounds or substitutes (a raw analog TAS is rejected, not approximated)."""
    bl = _track1()
    out = []
    for i, row in enumerate(rows):
        if len(row) != 3 or not all(_is_int(v) for v in row):
            raise FixtureError(f"native row {i} {list(row)!r}: values must be integers (a float or boolean is never "
                               "truncated into a Track 1 action)")
        b, x, y = row
        try:
            out.append(bl.native_to_track1(b, x, y))
        except ValueError as exc:
            raise FixtureError(f"native row {i} (buttons=0x{b:04X}, stick=({x},{y})) is not a Track 1 action: "
                               f"{exc}") from None
    return out


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def non_track1_rows(rows: Sequence[Tuple[int, int, int]]) -> List[int]:
    bl = _track1()
    bad = []
    for i, row in enumerate(rows):
        try:
            if len(row) != 3 or not all(_is_int(v) for v in row):
                raise ValueError("non-integer")
            bl.native_to_track1(*row)
        except ValueError:
            bad.append(i)
    return bad


LIVE_INPUTS = ("keyboard", "xinput")


def capture_source_kind(input_name: Optional[str], resumed_from: Optional[Mapping[str, Any]]) -> str:
    """Source kind of a capture: user_recorded only for live keyboard/XInput play whose replayed prefix (if any)
    was itself user_recorded; a live continuation of an imported/searched prefix is 'imported'; the test provider
    stays 'scripted' (never a valid fixture source)."""
    if input_name not in LIVE_INPUTS:
        return str(input_name)
    if resumed_from and resumed_from.get("prefix_length", 0) > 0 and resumed_from.get("source_kind") != "user_recorded":
        return "imported"
    return "user_recorded"


RECORDING_MARKERS = ("session.jsonl", "draft.json")  # a directory holding either is a capture recording


def recording_dir_of(path: Path) -> Optional[Path]:
    """The capture recording directory that `path` lies in (or is), if any. Tools refuse to write there."""
    p = Path(path).resolve()
    for d in [p] + list(p.parents):
        if d.is_dir() and any((d / m).is_file() for m in RECORDING_MARKERS):
            return d
    return None


def read_text_file(path: Path) -> str:
    """UTF-8 (with or without BOM) or BOM-marked UTF-16, as Windows editors and PowerShell redirection write."""
    raw = Path(path).read_bytes()
    try:
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return raw.decode("utf-16")
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FixtureError(f"{path}: not UTF-8 or BOM-marked UTF-16 text ({exc})") from None


GAMEPLAY_CVARS = ("gEnhancements.TapJumpDisabled.P1", "gEnhancements.CasualRules.AutoZCancel",
                  "gEnhancements.StageHazardsDisabled")  # port/enhancements: the settings that change BTT physics


def gameplay_config(path: Path) -> Dict[str, Any]:
    """Fingerprint of the configuration a capture or replay runs with: sha256 of the file plus the effective values
    of the port settings that change Mario's physics (absent = the port default 0)."""
    p = Path(path)
    raw = p.read_bytes()
    doc = json.loads(raw.decode("utf-8-sig"))
    eff: Dict[str, Any] = {}
    for name in GAMEPLAY_CVARS:
        node: Any = doc.get("CVars", {})
        for part in name.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        eff[name] = node if node is not None else 0
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "effective_gameplay_cvars": eff}


# -- digests -------------------------------------------------------------------------------------------

def track1_digest(seq: Sequence[Tuple[int, int]]) -> str:
    """sha256 over ASCII lines 'stick,button\\n' (Track 1 indices, decimal, in order)."""
    h = hashlib.sha256()
    for s, b in seq:
        h.update(f"{int(s)},{int(b)}\n".encode("ascii"))
    return h.hexdigest()


def native_action_digest(rows: Sequence[Tuple[int, int, int]], consumed: Optional[Sequence[int]] = None) -> str:
    """The M7 tracker's native_action_digest: sha256 over 'buttons,stick_x,stick_y,consumed_tick\\n'. A fixture
    starts at tick 0 and consumes one tick per action, so the canonical consumed ticks are 0..n-1."""
    ticks = range(len(rows)) if consumed is None else consumed
    h = hashlib.sha256()
    for (b, x, y), t in zip(rows, ticks):
        h.update(f"{int(b)},{int(x)},{int(y)},{int(t)}\n".encode("ascii"))
    return h.hexdigest()


GAMEPLAY_EXCLUDED = ("host_frame",)  # host-side callback count: identical in every run so far, but a capture detail


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def trajectory_digest(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]], *,
                      include_host_frame: bool = False) -> str:
    """sha256 over the initial observe reply and every step reply's (state, step_count, consumed_tick, observation)
    in canonical JSON. host_frame is excluded unless include_host_frame (it counts host callbacks, not game state)."""
    drop = () if include_host_frame else GAMEPLAY_EXCLUDED
    h = hashlib.sha256()
    h.update(_canon({"state": initial.get("state"), "step_count": initial.get("step_count"),
                     "observation": {k: v for k, v in (initial.get("observation") or {}).items() if k not in drop}}))
    for r in steps:
        h.update(b"\n")
        h.update(_canon({"state": r.get("state"), "step_count": r.get("step_count"),
                         "consumed_tick": r.get("consumed_tick"),
                         "observation": {k: v for k, v in (r.get("observation") or {}).items() if k not in drop}}))
    return h.hexdigest()


def targets_digest(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """sha256 over every reply's M7f `targets` object (None when the diagnostic was off)."""
    if "targets" not in initial:
        return None
    h = hashlib.sha256(_canon(initial["targets"]))
    for r in steps:
        h.update(b"\n")
        h.update(_canon(r.get("targets")))
    return h.hexdigest()


def policy_obs_v1_digest(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Tuple[str, int]:
    """sha256 over the little-endian float32 btt_policy_obs_v1 vectors (initial + every step), exactly as M7f."""
    from btt_learning import POLICY_FIELDS

    h = hashlib.sha256()
    n = 0
    for reply in [initial] + list(steps):
        obs = reply["observation"]
        vec = [float(obs[name]) for name in POLICY_FIELDS]
        h.update(struct.pack("<%df" % len(vec), *vec))
        n += 1
    return h.hexdigest(), n


def returns_v1_v2(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    """btt_reward_v1 / v2 returns of a trace, step by step exactly as the M5/M7 wrappers (M7f validate formula)."""
    from m7f_validate import returns

    return returns({"initial": initial, "steps": list(steps)})


# -- script format -------------------------------------------------------------------------------------

STICK_ALIASES: Dict[str, int] = {}
BUTTON_ALIASES: Dict[str, int] = {}
_STICK_NAMES = (("n", "neutral", "0"), ("r", "right", "1"), ("ur", "up-right", "2"), ("u", "up", "3"),
                ("ul", "up-left", "4"), ("l", "left", "5"), ("dl", "down-left", "6"), ("d", "down", "7"),
                ("dr", "down-right", "8"))
_BUTTON_NAMES = (("-", "none", "0"), ("a", "1"), ("b", "2"), ("cu", "c-up", "3"), ("cl", "c-left", "4"),
                 ("l", "5"), ("r", "6"), ("z", "7"))
for _i, _names in enumerate(_STICK_NAMES):
    for _n in _names:
        STICK_ALIASES[_n] = _i
for _i, _names in enumerate(_BUTTON_NAMES):
    for _n in _names:
        BUTTON_ALIASES[_n] = _i
SCRIPT_STICK = tuple(n[0].upper() for n in _STICK_NAMES)     # canonical output tokens
SCRIPT_BUTTON = ("-", "A", "B", "CU", "CL", "L", "R", "Z")


def parse_script(text: str) -> List[Tuple[int, int]]:
    """btt_track1_script_v1: '#' comments, blank lines, an optional 'format btt_track1_script_v1' line, then
    '<count> <stick> <button>' rows (count >= 1; stick = index 0-8 or N R UR U UL L DL D DR; button = index 0-7 or
    - A B CU CL L R Z; case-insensitive). The first row is consumed at native tick 0. Strict: any other text is an
    error naming the line."""
    seq: List[Tuple[int, int]] = []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if parts[0].lower() == "format":
            if len(parts) != 2 or parts[1] != SCRIPT_FORMAT:
                raise FixtureError(f"line {ln}: unsupported format declaration {line!r} (expected {SCRIPT_FORMAT})")
            continue
        if len(parts) != 3:
            raise FixtureError(f"line {ln}: expected '<count> <stick> <button>', got {raw.strip()!r}")
        if not re.fullmatch(r"[1-9][0-9]*", parts[0]):
            raise FixtureError(f"line {ln}: count must be a positive integer, got {parts[0]!r}")
        stick = STICK_ALIASES.get(parts[1].lower())
        button = BUTTON_ALIASES.get(parts[2].lower())
        if stick is None:
            raise FixtureError(f"line {ln}: unknown stick state {parts[1]!r}")
        if button is None:
            raise FixtureError(f"line {ln}: unknown button state {parts[2]!r}")
        seq.extend([(stick, button)] * int(parts[0]))
    if not seq:
        raise FixtureError("script contains no actions")
    return seq


def format_script(seq: Sequence[Tuple[int, int]], header: Sequence[str] = ()) -> str:
    """Canonical run-length text of a Track 1 sequence (parse_script(format_script(s)) == s)."""
    lines = [f"format {SCRIPT_FORMAT}"] + [f"# {h}" for h in header]
    i = 0
    tick = 0
    while i < len(seq):
        j = i
        while j < len(seq) and seq[j] == seq[i]:
            j += 1
        s, b = seq[i]
        lines.append(f"{j - i} {SCRIPT_STICK[s]} {SCRIPT_BUTTON[b]}    # ticks {tick}-{tick + j - i - 1}")
        tick += j - i
        i = j
    return "\n".join(lines) + "\n"


# -- sequence import -------------------------------------------------------------------------------------

def load_sequence(path: Path) -> Tuple[List[Tuple[int, int]], Dict[str, Any]]:
    """Load a Track 1 sequence from any supported source; every row must map EXACTLY to one of the 72 actions.

    Supported: .txt script (btt_track1_script_v1), .json draft (btt_track1_draft_v1), .json fixture
    (btt_crossing_fixture_v1), .json list of [stick, button] or of [buttons, stick_x, stick_y], .btti native replay,
    an M4 episode artifact directory (actions.jsonl, rows checked for consumed ticks 0..n-1)."""
    p = Path(path)
    meta: Dict[str, Any] = {"path": str(p)}
    if p.is_dir():
        from run_artifacts import read_artifact

        art = read_artifact(p)
        rows = [(a.buttons, a.stick_x, a.stick_y) for a in art.actions]
        ticks = [a.consumed_tick for a in art.actions]
        if ticks != list(range(len(rows))):
            raise FixtureError(f"{p}: artifact consumed ticks are not 0..{len(rows) - 1}")
        meta.update({"kind": "m4_artifact", "native_rows": len(rows),
                     "recorded_native_action_digest": (art.metadata.get("labels") or {}).get("native_action_digest")})
        return native_to_track1_exact(rows), meta
    if p.suffix.lower() == ".btti":
        from btti_replay import read_btti_rows

        rows = [(r.buttons, r.stick_x, r.stick_y) for r in read_btti_rows(str(p))]
        meta.update({"kind": "btti", "native_rows": len(rows)})
        return native_to_track1_exact(rows), meta
    text = read_text_file(p)
    if p.suffix.lower() == ".jsonl":  # the capture autosave (btt_track1_capture_log_v1), e.g. after a crash
        lines = [ln for ln in text.splitlines() if ln.strip()]
        head = json.loads(lines[0]) if lines else {}
        if head.get("format") != CAPTURE_LOG_FORMAT or head.get("action_contract") != track1_contract():
            raise FixtureError(f"{p}: not a {CAPTURE_LOG_FORMAT} autosave")
        recs = [json.loads(ln) for ln in lines[1:]]
        if [r.get("i") for r in recs] != list(range(len(recs))) or \
                [r.get("consumed_tick") for r in recs] != list(range(len(recs))):
            raise FixtureError(f"{p}: autosave rows are not contiguous from tick 0")
        meta.update({"kind": CAPTURE_LOG_FORMAT,
                     "source_kind": capture_source_kind(head.get("input"), head.get("resumed_from")),
                     "capture_header": head})
        return validate_track1([[r["s"], r["b"]] for r in recs]), meta
    if p.suffix.lower() == ".json":
        doc = json.loads(text)
        if isinstance(doc, dict) and doc.get("contract") in (DRAFT_CONTRACT, FIXTURE_CONTRACT):
            if doc.get("action_contract") != track1_contract():
                raise FixtureError(f"{p}: action_contract {doc.get('action_contract')!r} != {track1_contract()}")
            seq = validate_track1(doc["sequence"]["track1"])
            meta.update({"kind": doc["contract"], "declared_track1_digest": doc["sequence"].get("track1_digest"),
                         "source_kind": (doc.get("source") or {}).get("kind"), "document": doc})
            if doc["sequence"].get("track1_digest") not in (None, track1_digest(seq)):
                raise FixtureError(f"{p}: track1_digest does not match the stored sequence")
            if doc["sequence"].get("native") is not None and \
                    [tuple(r) for r in doc["sequence"]["native"]] != track1_to_native(seq):
                raise FixtureError(f"{p}: native rows are not the Track 1 table images of track1")
            return seq, meta
        if isinstance(doc, list) and doc and all(isinstance(r, list) for r in doc):
            if all(len(r) == 2 for r in doc):
                meta["kind"] = "json_track1"
                return validate_track1(doc), meta
            if all(len(r) == 3 for r in doc):
                meta["kind"] = "json_native"
                return native_to_track1_exact([tuple(r) for r in doc]), meta
        raise FixtureError(f"{p}: unrecognised JSON sequence document")
    meta["kind"] = SCRIPT_FORMAT
    return parse_script(text), meta


# -- stage geometry (decoded from the checked-in stage source) ------------------------------------------

LINE_KINDS = ("floor", "ceil", "rwall", "lwall")  # MPLineInfo order (decomp/src/mp/mpdef.h nMPLineKind*)
VERTEX_FLAG_PASS = 0x4000   # MAP_VERTEX_COLL_PASS: drop-through (solid from above only)
VERTEX_FLAG_CLIFF = 0x8000  # MAP_VERTEX_COLL_CLIFF: ledge-grabbable


@dataclass(frozen=True)
class Line:
    index: int
    group: int              # yakumono line group id (1 static, 2 moving platform)
    kind: str               # floor / ceil / rwall / lwall
    vertex_ids: Tuple[int, ...]
    points: Tuple[Tuple[float, float], ...]  # static: world; dynamic: relative to the group's DObj translate
    flags: int              # the first vertex's flags (the line's flags, mpcollision.c)
    dynamic: bool

    @property
    def x_span(self) -> Tuple[float, float]:
        xs = [p[0] for p in self.points]
        return min(xs), max(xs)

    @property
    def y_span(self) -> Tuple[float, float]:
        ys = [p[1] for p in self.points]
        return min(ys), max(ys)


@dataclass
class StageGeometry:
    lines: List[Line]
    vertices: List[Tuple[int, int, int]]
    spawn: Tuple[float, float]
    platform_translate: Tuple[float, float]
    platform_y_range: Tuple[float, float]
    platform_period_ticks: int
    source_sha256: str
    derived: Dict[str, Any] = field(default_factory=dict)

    def static_floors(self) -> List[Line]:
        return [ln for ln in self.lines if ln.kind == "floor" and not ln.dynamic]

    def platform_lines(self) -> List[Line]:
        return [ln for ln in self.lines if ln.dynamic]


def _block(text: str, decl_regex: str) -> str:
    m = re.search(decl_regex + r"\s*=\s*\{", text)
    if not m:
        raise FixtureError(f"stage source: declaration {decl_regex!r} not found")
    depth, i = 1, m.end()
    while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i - 1]


def decode_stage_geometry(path: Path = STAGE_SOURCE) -> StageGeometry:
    """Decode MPGeometryData of Mario's Break the Targets map from the checked-in decomp source and derive the
    region boundaries used as crossing evidence. Raises FixtureError if the source no longer has the expected form."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    verts = [(int(x), int(y), int(f, 16)) for x, y, f in re.findall(
        r"\{\s*\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\}\s*,\s*(0x[0-9A-Fa-f]+)\s*\}",
        _block(text, r"MPVertexData\s+dGRBonus1MarioFile2_gap_0x1F60\[26\]"))]
    ids = [int(v) for v in re.findall(r"\d+", _block(text, r"u16\s+dGRBonus1MarioFile2_gap_0x1F60_sub_0x9C\[44\]"))]
    links = [(int(a), int(b)) for a, b in re.findall(r"\{\s*(\d+)\s*,\s*(\d+)\s*\}", _block(
        text, r"MPVertexLinks\s+dGRBonus1MarioFile2_gap_0x1F60_sub_0xF4\[20\]"))]
    info_text = _block(text, r"MPLineInfo\s+dGRBonus1MarioFile2_gap_0x1F60_sub_0x144\[2\]")
    groups = []
    for gm in re.finditer(r"\{\s*(\d+)\s*,\s*\{((?:\s*\{\s*\d+\s*,\s*\d+\s*\}\s*,?)+)\s*\}\s*\}", info_text):
        groups.append((int(gm.group(1)), [(int(a), int(b)) for a, b in re.findall(r"\{\s*(\d+)\s*,\s*(\d+)\s*\}",
                                                                                  gm.group(2))]))
    mapobjs = [(int(k), int(x), int(y)) for k, x, y in re.findall(
        r"\{\s*(\d+)\s*,\s*\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\}\s*\}",
        _block(text, r"MPMapObjData\s+dGRBonus1MarioFile2_gap_0x1F60_sub_0x168\[5\]"))]
    layer1 = re.findall(r"\{\s*(\d+)\s*,\s*\(void\*\)[^,]+,\s*\{\s*([-\d.e]+)f\s*,\s*([-\d.e]+)f\s*,",
                        _block(text, r"DObjDesc\s+dGRBonus1MarioFile2_Layer1DObj\[\]"))
    # Moving-platform script (joint table 1 -> script 1): TRAY start value, then two TRAY targets reached over
    # `rate` frames each (SetVal0RateBlock), looping via SetAnim.
    anim = _block(text, r"u32\s+dGRBonus1MarioFile2_Layer1Anim_AnimJoint_data\[11\]")
    tray_targets = [float(v) for v in re.findall(
        r"AOBJ_FLAG_TRAY,\s*\d+\),\s*0x[0-9A-Fa-f]+,\s*/\*\s*(-?\d+\.\d+)f", anim)]
    rates = [int(v) for v in re.findall(r"aobjEvent32SetVal0RateBlock\(AOBJ_FLAG_TRAY,\s*(\d+)\)", anim)]
    if len(verts) != 26 or len(ids) != 44 or len(links) != 20 or len(groups) != 2 or len(mapobjs) != 5:
        raise FixtureError(f"stage source shape changed: {len(verts)} vertices, {len(ids)} ids, {len(links)} links, "
                           f"{len(groups)} groups, {len(mapobjs)} map objects")
    if len(layer1) < 3 or len(tray_targets) != 3 or len(rates) != 2 or "aobjEvent32SetAnim" not in anim:
        raise FixtureError("stage source: moving-platform DObj / animation script not in the expected form")
    lines: List[Line] = []
    for group_id, per_kind in groups:
        for kind, (start, count) in zip(LINE_KINDS, per_kind):
            for li in range(start, start + count):
                first, n = links[li]
                vids = tuple(ids[first:first + n])
                dynamic = group_id != 1
                lines.append(Line(index=li, group=group_id, kind=kind, vertex_ids=vids,
                                  points=tuple((float(verts[v][0]), float(verts[v][1])) for v in vids),
                                  flags=verts[vids[0]][2], dynamic=dynamic))
    lines.sort(key=lambda ln: ln.index)
    if [ln.index for ln in lines] != list(range(20)):
        raise FixtureError("stage source: line groups do not cover lines 0..19 exactly once")
    spawn = next(((float(x), float(y)) for k, x, y in mapobjs if k == 0x21), None)
    if spawn is None:
        raise FixtureError("stage source: no 1P spawn map object (kind 0x21)")
    tx, ty = float(layer1[2][1]), float(layer1[2][2])  # Layer1DObj[2]: the group-2 (yakumono) DObj
    if ty != tray_targets[0]:
        raise FixtureError(f"moving-platform DObj y {ty} != animation start {tray_targets[0]}")
    geo = StageGeometry(lines=lines, vertices=verts, spawn=spawn, platform_translate=(tx, ty),
                        platform_y_range=(min(tray_targets), max(tray_targets)),
                        platform_period_ticks=sum(rates),
                        source_sha256=hashlib.sha256(raw).hexdigest())
    geo.derived = derive_regions(geo)
    return geo


def derive_regions(geo: StageGeometry) -> Dict[str, Any]:
    """Region boundaries derived from the collision data (never hand-entered):

    * main solid = the closed polygon of static lines connected (by shared vertex ids) to the floor under the spawn;
    * left_boundary_x = its minimum x (the tall wall's left face); left region = x strictly less than that;
    * wall_right_face_x = x of its vertical wall line through the spawn floor's left end;
    * wall_top_y = its maximum y; ledge = its floor line at that height; overhang underside = its ceiling line
      whose right end meets the ledge's right face;
    * moving platform = the dynamic floor line(s), world span = relative points + DObj translate, surface y range
      from the TRAY animation targets."""
    static = [ln for ln in geo.lines if not ln.dynamic]
    sx, sy = geo.spawn
    below = [ln for ln in static if ln.kind == "floor" and ln.x_span[0] <= sx <= ln.x_span[1] and ln.y_span[1] <= sy]
    if not below:
        raise FixtureError("no static floor under the spawn")
    spawn_floor = max(below, key=lambda ln: ln.y_span[1])
    comp_v = set(spawn_floor.vertex_ids)
    comp = {spawn_floor.index}
    changed = True
    while changed:
        changed = False
        for ln in static:
            if ln.index not in comp and comp_v & set(ln.vertex_ids):
                comp.add(ln.index)
                comp_v |= set(ln.vertex_ids)
                changed = True
    comp_lines = [ln for ln in static if ln.index in comp]
    degree: Dict[int, int] = {}
    for ln in comp_lines:
        for a, b in zip(ln.vertex_ids, ln.vertex_ids[1:]):
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
    closed = all(d == 2 for d in degree.values())
    xs = [geo.vertices[v][0] for v in comp_v]
    ys = [geo.vertices[v][1] for v in comp_v]
    left_x, top_y = float(min(xs)), float(max(ys))
    fl_left = min(spawn_floor.points, key=lambda p: p[0])
    face = [ln for ln in comp_lines if ln.kind in ("rwall", "lwall") and ln.x_span[0] == ln.x_span[1] == fl_left[0]
            and ln.y_span[0] <= fl_left[1] <= ln.y_span[1]]
    ledge = [ln for ln in comp_lines if ln.kind == "floor" and ln.y_span == (top_y, top_y)]
    if not closed or len(face) != 1 or len(ledge) != 1:
        raise FixtureError(f"main solid polygon not as expected: closed={closed} faces={len(face)} ledges={len(ledge)}")
    ledge_ln = ledge[0]
    overhang = [ln for ln in comp_lines if ln.kind == "ceil" and ln.x_span[1] == ledge_ln.x_span[1]]
    # The raised right step (its top-left corner is the user-marked lower-platform reference point, 2026-09-23):
    # the main-solid floor that starts at the top of the wall rising from the spawn floor's right end.
    fl_right = max(spawn_floor.points, key=lambda p: p[0])
    rwall = [ln for ln in comp_lines if ln.kind in ("rwall", "lwall") and ln.x_span[0] == ln.x_span[1] == fl_right[0]
             and ln.y_span[0] <= fl_right[1] <= ln.y_span[1]]
    step = [ln for ln in comp_lines if ln.kind == "floor" and rwall
            and min(ln.points, key=lambda q: q[0]) == (fl_right[0], rwall[0].y_span[1])]
    if len(rwall) != 1 or len(step) != 1:
        raise FixtureError(f"right step not found: walls={len(rwall)} steps={len(step)}")
    tx, ty = geo.platform_translate
    plat = [ln for ln in geo.lines if ln.dynamic and ln.kind == "floor"]
    if len(plat) != 1:
        raise FixtureError("expected exactly one dynamic floor line (the moving platform)")
    p = plat[0]
    rel_y = p.y_span[0]
    y0, y1 = geo.platform_y_range
    left_side_floors = [ln.index for ln in static if ln.kind == "floor" and ln.x_span[1] <= left_x]
    return {
        "spawn_floor_line": spawn_floor.index,
        "main_solid_lines": sorted(comp),
        "main_solid_closed": closed,
        "left_boundary_x": left_x,
        "left_region_rule": f"position_x < {left_x}",
        "wall_right_face_line": face[0].index,
        "wall_right_face_x": float(fl_left[0]),
        "wall_top_y": top_y,
        "ledge_line": ledge_ln.index,
        "ledge_x_span": list(ledge_ln.x_span),
        "overhang_line": overhang[0].index if overhang else None,
        "overhang_underside_y": overhang[0].y_span[0] if overhang else None,
        "right_step_line": step[0].index,
        "right_step_corner": [fl_right[0], rwall[0].y_span[1]],
        "moving_platform_line": p.index,
        "moving_platform_x_span": [p.x_span[0] + tx, p.x_span[1] + tx],
        "moving_platform_surface_y_range": [rel_y + y0, rel_y + y1],
        "moving_platform_period_ticks": geo.platform_period_ticks,
        "left_side_floor_lines": left_side_floors,
        "cliff_flag_lines": [ln.index for ln in geo.lines if ln.flags & VERTEX_FLAG_CLIFF],
        "pass_through_lines": [ln.index for ln in geo.lines if ln.flags & VERTEX_FLAG_PASS],
    }


def geometry_summary(geo: StageGeometry) -> Dict[str, Any]:
    return {"schema": GEOMETRY_SCHEMA, "source": str(STAGE_SOURCE.relative_to(REPO_ROOT)).replace("\\", "/"),
            "source_sha256": geo.source_sha256, "spawn": list(geo.spawn),
            "platform_translate": list(geo.platform_translate), "platform_dobj_y_range": list(geo.platform_y_range),
            "lines": [{"index": ln.index, "group": ln.group, "kind": ln.kind, "points": [list(p) for p in ln.points],
                       "flags": ln.flags, "dynamic": ln.dynamic} for ln in geo.lines],
            "derived": geo.derived}


# -- crossing evidence -------------------------------------------------------------------------------------

def classify_ground(geo: StageGeometry, obs: Mapping[str, Any]) -> Optional[str]:
    """Which surface a grounded native observation stands on: 'L<n>' for a static floor line, 'moving_platform'
    (grounded inside the platform's x span at a height where no static floor exists, within its surface range),
    'ground_unmatched', or None when airborne / not a live fighter."""
    if obs.get("fighter_valid") != 1 or obs.get("btt_active") != 1 or obs.get("ground_air_state") != 0:
        return None
    x, y = float(obs["position_x"]), float(obs["position_y"])
    for ln in geo.static_floors():
        (x0, x1), (y0, y1) = ln.x_span, ln.y_span
        if y0 == y1 and abs(y - y0) <= FLOOR_Y_TOL and x0 - FLOOR_X_TOL <= x <= x1 + FLOOR_X_TOL:
            return f"L{ln.index}"
    d = geo.derived
    px0, px1 = d["moving_platform_x_span"]
    py0, py1 = d["moving_platform_surface_y_range"]
    if px0 - FLOOR_X_TOL <= x <= px1 + FLOOR_X_TOL and py0 - FLOOR_Y_TOL <= y <= py1 + FLOOR_Y_TOL:
        return "moving_platform"
    return "ground_unmatched"


def _point(i: int, r: Mapping[str, Any]) -> Dict[str, Any]:
    o = r["observation"]
    return {"step_index": i, "consumed_tick": r.get("consumed_tick"), "input_tick": o.get("input_tick"),
            "time_passed": o.get("time_passed"), "x": o.get("position_x"), "y": o.get("position_y"),
            "ground_air_state": o.get("ground_air_state"), "fighter_status_id": o.get("fighter_status_id")}


def is_fall(reply: Mapping[str, Any]) -> bool:
    o = reply.get("observation") or {}
    return (reply.get("state") != STEP_STATE_EPISODE_ENDED and o.get("game_status") == GAME_STATUS_END
            and o.get("btt_active") == 1 and (o.get("targets_remaining") or 0) > 0)


def crossing_evidence(geo: StageGeometry, initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]],
                      *, submitted: Optional[int] = None) -> Dict[str, Any]:
    """Native crossing evidence of one replayed trace (the tick-0 observe reply + one reply per consumed action).

    Only native observations are used; nothing is interpolated. `first_left_entry` is the minimum crossing proof.
    Wall-top height is reported separately and is never treated as a crossing."""
    d = geo.derived
    left_x, face_x, top_y = d["left_boundary_x"], d["wall_right_face_x"], d["wall_top_y"]
    ledge_x0, ledge_x1 = d["ledge_x_span"]
    live = [(i, r) for i, r in enumerate(steps)
            if (r.get("observation") or {}).get("fighter_valid") == 1 and (r.get("observation") or {}).get("btt_active") == 1]
    ev: Dict[str, Any] = {"schema": EVIDENCE_SCHEMA, "geometry_source_sha256": geo.source_sha256,
                          "left_region_rule": d["left_region_rule"], "steps": len(steps), "live_steps": len(live)}
    first_left = next(((i, r) for i, r in live if float(r["observation"]["position_x"]) < left_x), None)
    ev["first_left_entry"] = _point(*first_left) if first_left else None
    ev["left_region_steps"] = sum(1 for _, r in live if float(r["observation"]["position_x"]) < left_x)
    if live:
        i_minx, r_minx = min(live, key=lambda t: (float(t[1]["observation"]["position_x"]), t[0]))
        i_maxy, r_maxy = max(live, key=lambda t: (float(t[1]["observation"]["position_y"]), -t[0]))
        ev["min_x"] = _point(i_minx, r_minx)
        ev["max_y"] = _point(i_maxy, r_maxy)
    else:
        ev["min_x"] = ev["max_y"] = None
    # wall-top height evidence (never a crossing proof on its own)
    at_top = [(i, r) for i, r in live if float(r["observation"]["position_y"]) >= top_y]
    over_ledge = [(i, r) for i, r in at_top if float(r["observation"]["position_x"]) <= ledge_x1]
    ground: List[Tuple[int, Optional[str]]] = [(i, classify_ground(geo, r["observation"])) for i, r in enumerate(steps)]
    ledge_name = f"L{d['ledge_line']}"
    ledge_contacts = [i for i, g in ground if g == ledge_name]
    ev["wall_top"] = {
        "wall_top_y": top_y, "ledge_x_span": [ledge_x0, ledge_x1],
        "first_at_or_above_wall_top": _point(*at_top[0]) if at_top else None,
        "steps_at_or_above_wall_top": len(at_top),
        "first_over_ledge": _point(*over_ledge[0]) if over_ledge else None,
        "ledge_ground_contacts": len(ledge_contacts),
        "first_ledge_contact": _point(ledge_contacts[0], steps[ledge_contacts[0]]) if ledge_contacts else None,
        "min_x_at_or_above_wall_top": min((float(r["observation"]["position_x"]) for _, r in at_top), default=None),
    }
    # moving-platform contact evidence
    plat = [i for i, g in ground if g == "moving_platform"]
    runs: List[List[int]] = []
    for i in plat:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    riding = sum(1 for run in runs for a, b in zip(run, run[1:])
                 if steps[a]["observation"]["position_y"] != steps[b]["observation"]["position_y"])
    ev["moving_platform"] = {
        "surface_y_range": d["moving_platform_surface_y_range"], "x_span": d["moving_platform_x_span"],
        "grounded_steps": len(plat), "contact_runs": len(runs),
        "riding_steps": riding,  # consecutive grounded steps on it with a changed height = carried by a moving floor
        "first_contact": _point(plat[0], steps[plat[0]]) if plat else None,
        "last_contact": _point(plat[-1], steps[plat[-1]]) if plat else None,
        "y_range": [min(steps[i]["observation"]["position_y"] for i in plat),
                    max(steps[i]["observation"]["position_y"] for i in plat)] if plat else None,
    }
    unmatched = [i for i, g in ground if g == "ground_unmatched"]
    ev["ground_unmatched_steps"] = len(unmatched)
    ev["ground_unmatched_first"] = _point(unmatched[0], steps[unmatched[0]]) if unmatched else None
    # The crossing's own takeoff (approach surface): the last grounded step before the FIRST left-region step on any
    # surface other than the ledge top (standing on the ledge is part of crossing over it). The path is 'over_ledge'
    # only if Mario is over the ledge between that takeoff and the entry. Earlier ledge visits (an attempt that fell
    # back to the right, for instance) are reported separately and never decide the identity.
    approach = None
    path = None
    crossing_over: List[int] = []
    takeoff = None
    if first_left:
        fl = first_left[0]
        takeoff = next((i for i in range(fl - 1, -1, -1) if ground[i][1] is not None and ground[i][1] != ledge_name),
                       None)
        if takeoff is not None:
            approach = {"surface": ground[takeoff][1], **_point(takeoff, steps[takeoff]),
                        "steps_from_takeoff_to_entry": fl - takeoff}
        lo = takeoff if takeoff is not None else -1
        crossing_over = [i for i, _ in over_ledge if lo < i <= fl]
        path = "over_ledge" if crossing_over else "not_over_ledge"
    ev["approach_surface"] = approach
    ev["crossing_path"] = path
    ev["crossing_over_ledge_step"] = crossing_over[0] if crossing_over else None
    ev["earlier_over_ledge_steps"] = sum(1 for i, _ in over_ledge if takeoff is not None and i <= takeoff)
    ev["wall_right_face_x"] = face_x
    if first_left:  # the last grounded step of any kind (the ledge included) before the entry, for transparency
        lg = next((i for i in range(first_left[0] - 1, -1, -1) if ground[i][1] is not None), None)
        ev["last_grounded_before_entry"] = ({"surface": ground[lg][1], **_point(lg, steps[lg])}
                                           if lg is not None else None)
    else:
        ev["last_grounded_before_entry"] = None
    # The route as native surface-contact runs (every grounded stretch, in order) and the complete per-tick native
    # trajectory: the evidence a reviewer needs when the route classifier disagrees with the declared crossing.
    runs_all: List[Dict[str, Any]] = []
    for i, g in ground:
        if g is None:
            continue
        if runs_all and runs_all[-1]["surface"] == g and runs_all[-1]["last_step"] == i - 1:
            runs_all[-1]["last_step"] = i
            runs_all[-1]["last_consumed_tick"] = steps[i].get("consumed_tick")
        else:
            runs_all.append({"surface": g, "first_step": i, "last_step": i,
                             "first_consumed_tick": steps[i].get("consumed_tick"),
                             "last_consumed_tick": steps[i].get("consumed_tick"),
                             "x": steps[i]["observation"]["position_x"], "y": steps[i]["observation"]["position_y"]})
    ev["surface_runs"] = runs_all
    ev["trajectory"] = {"fields": list(TRAJECTORY_FIELDS),
                        "rows": [[r.get("consumed_tick"), (r.get("observation") or {}).get("position_x"),
                                  (r.get("observation") or {}).get("position_y"),
                                  (r.get("observation") or {}).get("ground_air_state"),
                                  (r.get("observation") or {}).get("fighter_status_id"), g]
                                 for r, (_, g) in zip(steps, ground)]}
    # targets (M7f diagnostic, when present)
    ev["targets"] = None
    if "targets" in initial:
        from m7f_targets import check_trace

        chk = check_trace(initial, steps)
        entry_tick = ev["first_left_entry"]["consumed_tick"] if first_left else None
        events = [{"target_id": e["target_id"], "consumed_tick": e["consumed_tick"], "input_tick": e["input_tick"],
                   "break_pos": e["break_pos"]} for e in chk.events]
        after = [e["target_id"] for e in events if entry_tick is not None and e["consumed_tick"] >= entry_tick]
        ev["targets"] = {"diag_ok": chk.ok, "diag_problems": chk.problems[:10], "breaks": events,
                         "broken_ids": [e["target_id"] for e in events],
                         "broken_after_first_left_entry": after,
                         "left_targets_broken": [t for t in (e["target_id"] for e in events) if t in LEFT_TARGET_IDS],
                         "final_remaining_mask": chk.final.remaining_mask if chk.final else None}
    # terminal
    n = len(steps)
    last = steps[-1] if steps else None
    if last is None:
        term = "empty"
    elif last.get("state") == STEP_STATE_EPISODE_ENDED:
        term = "clear"
    elif is_fall(last):
        term = "native_failure"
    else:
        term = "sequence_end"
    ev["terminal"] = {"kind": term, "submitted": n if submitted is None else submitted,
                      "last_consumed_tick": last.get("consumed_tick") if last else None,
                      "final_game_status": (last or {}).get("observation", {}).get("game_status"),
                      "final_targets_remaining": (last or {}).get("observation", {}).get("targets_remaining")}
    ev["crossed"] = first_left is not None
    return ev


def classify_crossing(ev: Mapping[str, Any], geo: StageGeometry) -> Dict[str, Any]:
    """The route classifier (btt_route_rule_v1). It proposes a route label from native evidence; it NEVER decides
    whether a crossing is kept (that needs only exact Track 1 actions, a native left-region entry and exact
    repeatability) and never relabels a declared crossing:

    * upper_moving_platform: the approach surface (the last grounded surface other than the ledge top before the
      first left-region step) is the moving platform;
    * lower_precision: the approach surface is the raised right step L1, the floor whose top-left corner the user
      marked in a screenshot (2026-09-23) as the lower-platform reference point. The mark identifies the
      lower-platform AREA; it does not prove every lower crossing takes off from exactly L1, so any other outcome is
      a classification to review, not a rejection;
    * anything else (another static floor, an unmatched ground point, no grounded takeoff): 'unclassified'.
    The path (over the ledge or not) does not change the proposal; route_assessment flags an unusual path."""
    if not ev.get("crossed"):
        return {"rule": ROUTE_RULE, "identity": None, "reason": "no native left-region entry"}
    ap = ev.get("approach_surface")
    if ap is None:
        return {"rule": ROUTE_RULE, "identity": "unclassified", "reason": "no grounded takeoff before the entry"}
    step = f"L{geo.derived['right_step_line']}"
    if ap["surface"] == "moving_platform":
        return {"rule": ROUTE_RULE, "identity": "upper_moving_platform",
                "reason": "approach surface is the moving platform"}
    if ap["surface"] == step:
        return {"rule": ROUTE_RULE, "identity": "lower_precision",
                "reason": f"approach surface {step} is the raised right step"}
    return {"rule": ROUTE_RULE, "identity": "unclassified",
            "reason": f"approach surface {ap['surface']} is neither the moving platform nor the right step {step}"}


def route_assessment(declared: str, ev: Mapping[str, Any], geo: StageGeometry) -> Dict[str, Any]:
    """The declared crossing (the user's claim, never relabelled) next to the classifier's proposal and the native
    takeoff. agreement: 'confirmed' (the classifier agrees), 'mismatch' (it proposes the other crossing) or
    'unclassified' (it proposes neither). review_required whenever it is not 'confirmed', or when the route
    evidence itself is incomplete (grounded steps on no decoded floor line, entry not over the ledge)."""
    cls = classify_crossing(ev, geo)
    ident = cls.get("identity")
    agreement = "confirmed" if ident == declared else ("mismatch" if ident in CROSSINGS else "unclassified")
    ap = ev.get("approach_surface")
    takeoff = None
    if ap:
        cx, cy = MARKED_LOWER_CORNER
        dx, dy = float(ap["x"]) - cx, float(ap["y"]) - cy
        takeoff = {"surface": ap["surface"], "consumed_tick": ap.get("consumed_tick"), "x": ap["x"], "y": ap["y"],
                   "steps_from_takeoff_to_entry": ap.get("steps_from_takeoff_to_entry"),
                   "offset_from_marked_lower_corner": {"dx": dx, "dy": dy, "distance": (dx * dx + dy * dy) ** 0.5}}
    notes = []  # neutral facts only: whether the crossing is kept is the builder's statement, not the assessment's
    if agreement != "confirmed":
        notes.append(f"declared {declared}; classifier proposes {ident!r} ({cls['reason']})")
    if ev.get("ground_unmatched_steps"):
        notes.append(f"{ev['ground_unmatched_steps']} grounded steps lie on no decoded floor line")
    if ev.get("crossed") and ev.get("crossing_path") != "over_ledge":
        notes.append(f"left entry not over the ledge (path {ev.get('crossing_path')})")
    if ev.get("targets") is not None and not ev["targets"].get("diag_ok"):
        notes.append("the M7f target-identity diagnostic reported invariant problems")
    return {"declared": declared, "classifier": cls, "agreement": agreement,
            "review_required": bool(notes), "notes": notes, "takeoff": takeoff,
            "marked_lower_corner": list(MARKED_LOWER_CORNER)}


# -- draft and fixture documents ----------------------------------------------------------------------------

def make_draft(seq: Sequence[Tuple[int, int]], source: Mapping[str, Any], *, session: Optional[Mapping[str, Any]] = None
               ) -> Dict[str, Any]:
    seq = validate_track1(seq)
    native = track1_to_native(seq)
    return {"contract": DRAFT_CONTRACT, "action_contract": track1_contract(), "task": dict(TASK),
            "start": {"tick": 0, "reset": "fresh_process", "hidden_prefix": False},
            "sequence": {"length": len(seq), "track1": [list(a) for a in seq], "native": [list(r) for r in native],
                         "track1_digest": track1_digest(seq), "native_action_digest": native_action_digest(native)},
            "source": dict(source), "session": dict(session or {})}


FIXTURE_TOP_KEYS = ("contract", "fixture_id", "crossing", "source", "task", "action_contract", "start", "sequence",
                    "provenance", "geometry", "evidence", "route", "verification", "usage_restrictions")
MIN_VERIFICATIONS = 8  # the full rl/m7g_crossing.py verification matrix
USAGE_RESTRICTIONS = ("validation evidence only: never a PPO demonstration, behaviour-cloning data, curriculum "
                      "start or prefix, reward shaping, route label or training-archive seed")


EVIDENCE_REQUIRED = ("schema", "geometry_source_sha256", "first_left_entry", "min_x", "max_y", "wall_top",
                     "moving_platform", "approach_surface", "last_grounded_before_entry", "crossing_path",
                     "surface_runs", "trajectory", "targets", "terminal", "crossed", "ground_unmatched_steps")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def validate_fixture_document(doc: Any, *, geo: Optional[StageGeometry] = None) -> List[str]:
    """Consistency of a btt_crossing_fixture_v1 document without the game. Returns problems ([] = valid); never
    raises for malformed content. Nothing stored is trusted when it can be re-derived: the geometry is decoded
    afresh from the stage source, the classification is recomputed from the stored native evidence, and the digests,
    native rows and fixture_id are recomputed from the Track 1 sequence. (The evidence itself is only reproduced by
    replaying the fixture: rl/m7g_crossing.py verify.)"""
    try:
        return _validate_fixture_document(doc, geo or decode_stage_geometry())
    except Exception as exc:  # malformed document -> a problem, never a crash
        return [f"malformed fixture document: {type(exc).__name__}: {exc}"]


def _validate_fixture_document(doc: Any, geo: StageGeometry) -> List[str]:
    p: List[str] = []
    if not isinstance(doc, dict) or doc.get("contract") != FIXTURE_CONTRACT:
        return [f"contract {doc.get('contract') if isinstance(doc, dict) else type(doc).__name__!r} != "
                f"{FIXTURE_CONTRACT}"]
    missing = [k for k in FIXTURE_TOP_KEYS if k not in doc]
    extra = [k for k in doc if k not in FIXTURE_TOP_KEYS]
    if missing or extra:
        return [f"top-level keys: missing {missing} extra {extra}"]
    if doc["crossing"] not in CROSSINGS:
        p.append(f"crossing {doc['crossing']!r} not in {CROSSINGS}")
    src = doc["source"]
    if not isinstance(src, dict) or src.get("kind") not in SOURCES:
        p.append(f"source.kind {src.get('kind') if isinstance(src, dict) else src!r} not in {SOURCES}")
    if doc["task"] != TASK:
        p.append(f"task {doc['task']!r} != {TASK}")
    if doc["action_contract"] != track1_contract():
        p.append(f"action_contract {doc['action_contract']!r}")
    if doc["start"] != {"tick": 0, "reset": "fresh_process", "hidden_prefix": False}:
        p.append(f"start {doc['start']!r}: fixtures start at native tick 0 in a fresh process with no hidden prefix")
    if doc["usage_restrictions"] != USAGE_RESTRICTIONS:
        p.append("usage_restrictions text altered")
    sq = doc["sequence"]
    try:
        seq = validate_track1(sq["track1"])
    except FixtureError as exc:
        return p + [str(exc)]
    if not seq:
        return p + ["sequence is empty"]
    native = track1_to_native(seq)
    if sq.get("length") != len(seq) or len(sq.get("native") or []) != len(seq):
        p.append("sequence length fields disagree")
    if [tuple(r) for r in sq.get("native") or []] != native:
        p.append("native rows are not the exact Track 1 table images of track1")
    if sq.get("track1_digest") != track1_digest(seq):
        p.append("track1_digest mismatch")
    nad = native_action_digest(native)
    if sq.get("native_action_digest") != nad:
        p.append("native_action_digest mismatch")
    if doc["fixture_id"] != f"{doc['crossing']}_{nad[:12]}":
        p.append(f"fixture_id {doc['fixture_id']!r} != {doc['crossing']}_{nad[:12]}")
    pv = doc["provenance"]
    if not isinstance(pv, dict) or not _HEX64.fullmatch(str(pv.get("executable_sha256"))) or \
            not isinstance(pv.get("revisions"), dict) or not isinstance(pv.get("verified_utc"), str) or \
            not _HEX64.fullmatch(str((pv.get("user_config") or {}).get("sha256"))):
        p.append("provenance needs executable_sha256, revisions, verified_utc and user_config.sha256")
    g = doc["geometry"]
    if g.get("source_sha256") != geo.source_sha256:
        p.append("geometry.source_sha256 differs from the current stage source (stale fixture or edited geometry)")
    if json.loads(json.dumps(g.get("derived"))) != json.loads(json.dumps(geo.derived)):
        p.append("geometry.derived differs from the regions derived from the current stage source")
    ev = doc["evidence"]
    missing_ev = [k for k in EVIDENCE_REQUIRED if k not in ev]
    if missing_ev:
        return p + [f"evidence keys missing: {missing_ev}"]
    if ev["schema"] != EVIDENCE_SCHEMA or ev["geometry_source_sha256"] != geo.source_sha256:
        p.append("evidence schema or geometry source mismatch")
    # Hard crossing gates: a native left-region entry by the stored trajectory, every action consumed.
    if ev["crossed"] is not True or not ev["first_left_entry"]:
        p.append("evidence shows no native left-region entry")
    elif not float(ev["first_left_entry"]["x"]) < geo.derived["left_boundary_x"]:
        p.append("first_left_entry is not left of the derived boundary")
    if (ev["terminal"] or {}).get("submitted") != len(seq):
        p.append(f"evidence.terminal.submitted {(ev['terminal'] or {}).get('submitted')!r} != sequence length "
                 f"{len(seq)} (actions after the terminal step were never consumed)")
    traj = ev["trajectory"] or {}
    rows = traj.get("rows") or []
    if traj.get("fields") != list(TRAJECTORY_FIELDS) or len(rows) != len(seq) or \
            [r[0] for r in rows] != list(range(len(seq))):
        p.append("evidence.trajectory must hold one row per consumed tick 0..length-1")
    elif ev["first_left_entry"]:
        k = ev["first_left_entry"]["step_index"]
        if not (0 <= k < len(rows) and float(rows[k][1]) < geo.derived["left_boundary_x"]
                and all(float(r[1]) >= geo.derived["left_boundary_x"] for r in rows[:k] if r[1] is not None)):
            p.append("the trajectory does not show the first left-region entry where the evidence says")
    # Route: the declared crossing is kept; the classifier's proposal and the agreement are recomputed and must match
    # what is stored, but disagreement is recorded for review, never a reason to reject or relabel the crossing.
    # Compared on structured fields only (never the prose notes), and only under the rule the fixture was assessed
    # with: a later revision of the route rule must never invalidate a preserved genuine crossing.
    stored = doc["route"]
    if not isinstance(stored, dict) or stored.get("declared") != doc["crossing"]:
        p.append("route.declared must equal the declared crossing (never relabelled)")
    elif (stored.get("classifier") or {}).get("rule") == ROUTE_RULE:
        route = json.loads(json.dumps(route_assessment(doc["crossing"], ev, geo)))
        keys = ("declared", "agreement", "review_required", "takeoff", "marked_lower_corner")
        if {k: stored.get(k) for k in keys} != {k: route[k] for k in keys} or \
                (stored.get("classifier") or {}).get("identity") != route["classifier"]["identity"]:
            p.append(f"stored route {stored!r} != recomputed {route!r}")
    elif (stored.get("classifier") or {}).get("rule") is None:
        p.append("route.classifier.rule missing")
    ver = doc["verification"]
    count = ver.get("count")
    if not _is_int(count) or count < MIN_VERIFICATIONS or ver.get("all_identical") is not True:
        p.append(f"verification incomplete: {count!r} executions, all_identical={ver.get('all_identical')!r}")
    bad_runs = [n for n, r in (ver.get("runs") or {}).items() if r.get("submitted") != len(seq)]
    if not ver.get("runs") or bad_runs:
        p.append(f"verification runs missing or not covering every action: {bad_runs}")
    return p


# -- self-test ----------------------------------------------------------------------------------------------

def _obs(x: float, y: float, ga: int, *, tick: int, status: int = 1, targets: int = 10) -> Dict[str, Any]:
    return {"observation_schema": 1, "host_frame": 0, "input_tick": tick, "time_passed": max(0, tick - 1),
            "game_status": status, "btt_active": 1, "targets_remaining": targets, "fighter_valid": 1,
            "position_x": x, "position_y": y, "air_velocity_x": 0.0, "air_velocity_y": 0.0,
            "ground_velocity_x": 0.0, "facing_direction": -1, "ground_air_state": ga, "fighter_status_id": 0,
            "jumps_used": 0}


def self_test() -> int:
    bad: List[str] = []

    def expect(cond: bool, name: str) -> None:
        if not cond:
            bad.append(name)

    geo = decode_stage_geometry()
    d = geo.derived
    expect(d["left_boundary_x"] == -2100.0 and d["wall_right_face_x"] == -1800.0 and d["wall_top_y"] == 3000.0,
           f"derived boundaries {d}")
    expect(d["ledge_line"] == 0 and d["ledge_x_span"] == [-2100.0, -1200.0] and d["overhang_underside_y"] == 2700.0,
           "ledge/overhang")
    expect(d["moving_platform_line"] == 19 and d["moving_platform_x_span"] == [2100.0, 3300.0]
           and d["moving_platform_surface_y_range"] == [1800.0, 3600.0] and d["moving_platform_period_ticks"] == 300,
           f"platform {d['moving_platform_x_span']} {d['moving_platform_surface_y_range']}")
    expect(d["main_solid_closed"] and d["spawn_floor_line"] == 4 and geo.spawn == (0.0, -2547.0), "main solid")
    expect(d["cliff_flag_lines"] == [] and d["pass_through_lines"] == [2, 19], f"flags {d['pass_through_lines']}")
    # script round trip and strictness
    seq = [(0, 0)] * 5 + [(1, 3)] * 2 + [(5, 2)] + [(8, 7)] * 3
    expect(parse_script(format_script(seq)) == seq, "script_round_trip")
    expect(parse_script("5 n -\n2 R cu\n1 left B\n3 dr z\n") == seq, "script_aliases")
    for text in ("0 N -", "1 N", "1 X -", "1 N Q", "format other_v1\n1 N -", "", "1.5 N -"):
        try:
            parse_script(text)
            bad.append(f"script_accepted {text!r}")
        except FixtureError:
            pass
    # exact Track 1 import: analog / C-down / multi-button rows are rejected with the row index
    native = track1_to_native(seq)
    expect(native_to_track1_exact(native) == seq, "native_round_trip")
    for row in ((0, 79, 0), (0x0004, 0, 0), (0x8000 | 0x4000, 0, 0), (0x1000, 0, 0)):
        try:
            native_to_track1_exact(native[:3] + [row])
            bad.append(f"native_accepted {row}")
        except FixtureError as exc:
            expect("native row 3" in str(exc), f"row_index_reported {exc}")
    expect(non_track1_rows(native[:2] + [(0, 79, 0)]) == [2], "non_track1_rows")
    expect(track1_digest(seq) != track1_digest(seq[:-1]) and len(native_action_digest(native)) == 64, "digests")
    # evidence: synthetic trace -> ground on start floor, step, moving platform (riding), ledge, then left region
    tr = [(0.0, -2550.0, 0), (2600.0, -450.0, 0), (2700.0, 1900.0, 0), (2700.0, 1910.0, 0), (1000.0, 3200.0, 1),
          (-1300.0, 3000.0, 0), (-2000.0, 3100.0, 1), (-2300.0, 2500.0, 1), (-3300.0, 700.0, 1)]
    initial = {"state": 1, "step_count": 0, "observation": _obs(0.0, -2547.0, 1, tick=0)}
    steps = [{"state": 1, "step_count": i + 1, "consumed_tick": i, "observation": _obs(x, y, g, tick=i + 1)}
             for i, (x, y, g) in enumerate(tr)]
    ev = crossing_evidence(geo, initial, steps)
    expect(ev["crossed"] and ev["first_left_entry"]["consumed_tick"] == 7, f"left entry {ev['first_left_entry']}")
    expect(ev["moving_platform"]["grounded_steps"] == 2 and ev["moving_platform"]["riding_steps"] == 1, "platform ev")
    expect(ev["wall_top"]["ledge_ground_contacts"] == 1 and ev["wall_top"]["first_over_ledge"]["consumed_tick"] == 5,
           f"wall top {ev['wall_top']}")
    expect(ev["approach_surface"]["surface"] == "moving_platform" and ev["crossing_path"] == "over_ledge",
           f"approach {ev['approach_surface']}")
    expect(classify_crossing(ev, geo)["identity"] == "upper_moving_platform", "classify_upper")
    tr2 = [(0.0, -2550.0, 0), (2150.0, -450.0, 0), (800.0, 2000.0, 1), (-1250.0, 3050.0, 1), (-2200.0, 2900.0, 1)]
    steps2 = [{"state": 1, "step_count": i + 1, "consumed_tick": i, "observation": _obs(x, y, g, tick=i + 1)}
              for i, (x, y, g) in enumerate(tr2)]
    ev2 = crossing_evidence(geo, initial, steps2)
    c2 = classify_crossing(ev2, geo)
    r2 = route_assessment("lower_precision", ev2, geo)
    expect(c2["identity"] == "lower_precision" and ev2["approach_surface"]["surface"] == "L1"
           and r2["agreement"] == "confirmed" and r2["takeoff"]["offset_from_marked_lower_corner"]["dx"] == 50.0,
           f"classify_lower {ev2['approach_surface']} {r2}")
    expect(d["right_step_line"] == 1 and d["right_step_corner"] == [2100.0, -450.0], f"right step {d}")
    # a takeoff from the drop-through platform L2 is not the user-identified lower crossing: unclassified
    tr4 = [(0.0, -2550.0, 0), (1500.0, -1500.0, 0), (800.0, 2000.0, 1), (-1250.0, 3050.0, 1), (-2200.0, 2900.0, 1)]
    steps4 = [{"state": 2, "step_count": i + 1, "consumed_tick": i, "observation": _obs(x, y, g, tick=i + 1)}
              for i, (x, y, g) in enumerate(tr4)]
    expect(classify_crossing(crossing_evidence(geo, initial, steps4), geo)["identity"] == "unclassified",
           "l2_takeoff_unclassified")
    # wall-top height without a left entry is not a crossing
    tr3 = [(0.0, -2550.0, 0), (-1300.0, 3000.0, 0), (-1900.0, 3400.0, 1), (-1500.0, 3100.0, 1)]
    steps3 = [{"state": 1, "step_count": i + 1, "consumed_tick": i, "observation": _obs(x, y, g, tick=i + 1)}
              for i, (x, y, g) in enumerate(tr3)]
    ev3 = crossing_evidence(geo, initial, steps3)
    expect(not ev3["crossed"] and ev3["wall_top"]["steps_at_or_above_wall_top"] == 3
           and classify_crossing(ev3, geo)["identity"] is None, "wall_top_is_not_crossing")
    fall = dict(steps3[-1], observation=_obs(-1500.0, -9700.0, 1, tick=4, status=GAME_STATUS_END))
    expect(crossing_evidence(geo, initial, steps3[:-1] + [fall])["terminal"]["kind"] == "native_failure", "fall")
    clear = dict(steps3[-1], state=STEP_STATE_EPISODE_ENDED,
                 observation=_obs(-1500.0, 3100.0, 1, tick=4, status=GAME_STATUS_END, targets=0))
    expect(crossing_evidence(geo, initial, steps3[:-1] + [clear])["terminal"]["kind"] == "clear", "clear")
    # anchoring regressions (M7g-a review): the identity comes from the takeoff of the crossing itself, never from an
    # earlier over-ledge visit that fell back to the right
    def trace(points: Sequence[Tuple[float, float, int]]) -> List[Dict[str, Any]]:
        return [{"state": 2, "step_count": i + 1, "consumed_tick": i, "observation": _obs(x, y, g, tick=i + 1)}
                for i, (x, y, g) in enumerate(points)]

    a_pts = [(0.0, -2550.0, 0), (2150.0, -450.0, 0), (-500.0, 2600.0, 1), (-1300.0, 3050.0, 1), (-1300.0, 3000.0, 0),
             (-1000.0, 2000.0, 1), (0.0, -2550.0, 0), (2700.0, 1900.0, 0), (2700.0, 1910.0, 0), (0.0, 3300.0, 1),
             (-1500.0, 3100.0, 1), (-2200.0, 3050.0, 1)]
    ev_a = crossing_evidence(geo, initial, trace(a_pts))
    expect(classify_crossing(ev_a, geo)["identity"] == "upper_moving_platform" and ev_a["earlier_over_ledge_steps"] == 2,
           f"scenario_A {ev_a['approach_surface']}")
    c_pts = [(0.0, -2550.0, 0), (2700.0, 1900.0, 0), (-1300.0, 3050.0, 1), (-1000.0, 2000.0, 1), (0.0, -2550.0, 0),
             (2150.0, -450.0, 0), (-500.0, 2600.0, 1), (-1250.0, 3050.0, 1), (-2200.0, 2950.0, 1)]
    ev_c = crossing_evidence(geo, initial, trace(c_pts))
    expect(classify_crossing(ev_c, geo)["identity"] == "lower_precision", f"scenario_C {ev_c['approach_surface']}")
    b_pts = [(0.0, -2550.0, 0), (2700.0, 1900.0, 0), (-1300.0, 3050.0, 1), (-1000.0, 2000.0, 1), (0.0, -2550.0, 0),
             (2150.0, -450.0, 0), (3500.0, -3500.0, 1), (-2300.0, -5000.0, 1)]
    ev_b = crossing_evidence(geo, initial, trace(b_pts))
    # the proposal follows the takeoff surface (L1 here); the unusual path is flagged for review, not re-labelled
    rb = route_assessment("lower_precision", ev_b, geo)
    expect(ev_b["crossing_path"] == "not_over_ledge" and classify_crossing(ev_b, geo)["identity"] == "lower_precision"
           and rb["review_required"] and any("not over the ledge" in n for n in rb["notes"]),
           f"scenario_B {ev_b['crossing_path']} {rb}")
    # native rows must be integers: a float is rejected, never truncated
    for row in ((0, 80.7, 0), (32768.5, 0, 0), (0, True, 0)):
        try:
            native_to_track1_exact([row])
            bad.append(f"non_integer_accepted {row}")
        except FixtureError:
            pass
    expect(non_track1_rows([(0, 80.7, 0), (0, 80, 0)]) == [0], "non_integer_flagged")
    # document validation: complete synthetic fixtures (built the way build_fixture builds them)
    def make_doc(declared: str, e: Mapping[str, Any], n: int) -> Dict[str, Any]:
        seq_n = [(5, 0)] * n
        dr = make_draft(seq_n, {"kind": "imported"})
        return {"contract": FIXTURE_CONTRACT,
                "fixture_id": f"{declared}_{dr['sequence']['native_action_digest'][:12]}",
                "crossing": declared, "source": {"kind": "imported"}, "task": dict(TASK),
                "action_contract": track1_contract(),
                "start": {"tick": 0, "reset": "fresh_process", "hidden_prefix": False}, "sequence": dr["sequence"],
                "provenance": {"executable_sha256": "a" * 64, "revisions": {"head": "x"},
                               "verified_utc": "20260923T000000Z", "user_config": {"sha256": "b" * 64}},
                "geometry": geometry_summary(geo), "evidence": e, "route": route_assessment(declared, e, geo),
                "verification": {"count": 8, "all_identical": True, "runs": {"cold_nrr": {"submitted": n}}},
                "usage_restrictions": USAGE_RESTRICTIONS}

    doc = make_doc("upper_moving_platform", ev, 9)
    expect(validate_fixture_document(doc) == [] and doc["route"]["agreement"] == "confirmed"
           and not doc["route"]["review_required"], f"valid_doc {validate_fixture_document(doc)} {doc['route']}")
    expect(doc["evidence"]["trajectory"]["rows"][7][1] == -2300.0 and
           [r["surface"] for r in doc["evidence"]["surface_runs"]] == ["L4", "L1", "moving_platform", "L0"],
           f"trajectory / surface runs {doc['evidence']['surface_runs']}")
    # A genuine crossing whose declared route the classifier does not confirm is KEPT as declared and flagged for
    # review (the user's mark identifies the lower-platform area, not an exact line): a mismatch, an unmatched
    # ground point, and a left entry that is not over the ledge all validate, with review_required.
    kept = [("mismatch", make_doc("lower_precision", ev, 9), "mismatch"),
            ("under_stage", make_doc("lower_precision", ev_b, 8), "confirmed"),
            ("l2_takeoff", make_doc("lower_precision", crossing_evidence(geo, initial, steps4), 5), "unclassified")]
    ev_u = json.loads(json.dumps(ev))
    ev_u["ground_unmatched_steps"] = 1
    kept.append(("unmatched_ground", make_doc("upper_moving_platform", ev_u, 9), "confirmed"))
    for name, dk, agreement in kept:
        probs = validate_fixture_document(dk)
        expect(probs == [] and dk["route"]["agreement"] == agreement and dk["route"]["review_required"]
               and dk["crossing"] == dk["route"]["declared"], f"kept_{name} {probs} {dk['route']}")
    expect(kept[0][1]["route"]["takeoff"]["surface"] == "moving_platform"
           and kept[2][1]["route"]["takeoff"]["surface"] == "L2", "takeoff recorded")
    forged = json.loads(json.dumps(kept[0][1]))  # a mismatch dressed up as confirmed must not validate
    forged["route"].update(agreement="confirmed", review_required=False, notes=[])
    expect(validate_fixture_document(forged) != [], "route_forged_accepted")
    reworded = json.loads(json.dumps(kept[0][1]))  # prose notes never decide validity
    reworded["route"]["notes"] = ["reworded note"]
    expect(validate_fixture_document(reworded) == [], "notes_wording_invalidates")
    older = json.loads(json.dumps(kept[0][1]))  # a later rule revision never invalidates a preserved crossing
    older["route"]["classifier"].update(rule="btt_route_rule_v0", identity="lower_precision")
    older["route"].update(agreement="confirmed", review_required=False)
    expect(validate_fixture_document(older) == [], f"older_rule_invalidates {validate_fixture_document(older)}")
    relabelled = json.loads(json.dumps(kept[0][1]))
    relabelled["route"]["declared"] = "upper_moving_platform"
    expect(validate_fixture_document(relabelled) != [], "route_declared_relabel_accepted")
    for mutate, name in ((lambda x: x.update(crossing="lower_precision"), "declared_changed_without_route"),
                         (lambda x: x["sequence"].update(track1_digest="0" * 64), "digest"),
                         (lambda x: x.update(start={"tick": 5, "reset": "fresh_process", "hidden_prefix": False}), "start"),
                         (lambda x: x["sequence"]["native"].__setitem__(0, [0, 79, 0]), "native_image"),
                         (lambda x: x.update(evidence=ev3, route=route_assessment(x["crossing"], ev3, geo)),
                          "no_crossing"),
                         (lambda x: x.update(extra=1), "extra_key"),
                         (lambda x: x.update(verification={"count": 2, "all_identical": True}), "few_verifications"),
                         (lambda x: x["verification"].update(all_identical="yes"), "all_identical_string"),
                         (lambda x: x.update(task={**TASK, "character": "luigi"}), "task"),
                         (lambda x: x.update(provenance={}), "provenance"),
                         (lambda x: x["geometry"]["derived"].update(left_boundary_x=0.0), "geometry_derived"),
                         (lambda x: x["geometry"].update(source_sha256="0" * 64), "geometry_source"),
                         (lambda x: x["evidence"].update(crossed=False), "crossed_false"),
                         (lambda x: x["evidence"]["trajectory"]["rows"].pop(), "trajectory_short"),
                         (lambda x: x["evidence"]["trajectory"]["rows"][7].__setitem__(1, -1000.0), "trajectory_entry"),
                         (lambda x: x["evidence"]["terminal"].update(submitted=7), "trailing_actions"),
                         (lambda x: x["verification"]["runs"]["cold_nrr"].update(submitted=7), "run_shorter"),
                         (lambda x: x["sequence"].update(native_action_digest=None), "null_digest"),
                         (lambda x: x.update(sequence=None), "null_sequence"),
                         (lambda x: x["evidence"].pop("first_left_entry"), "missing_evidence_key")):
        d2 = json.loads(json.dumps(doc))
        mutate(d2)
        try:
            probs = validate_fixture_document(d2)
            expect(probs != [], f"doc_{name}_accepted")
        except Exception as exc:  # the validator must report, never raise
            bad.append(f"doc_{name}_raised {type(exc).__name__}")
    print(f"m7g_fixture self-test: {'PASS' if not bad else 'FAIL'} ({len(bad)} failed) {bad}")
    return 0 if not bad else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--geometry", action="store_true", help="print the decoded stage geometry and derived regions")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.geometry:
        print(json.dumps(geometry_summary(decode_stage_geometry()), indent=1))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
