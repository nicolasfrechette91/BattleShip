"""Static table of Mario's statuses and transitions, read from the decomp source (no ROM, no game).

What it reads (paths relative to the decomp root, default <repo>/decomp):
  - status descriptors: src/ft/ftcommon/ftcommonstatus.h, src/ft/ftchar/ftmario/ftmariostatus.h
    (motion id, ground/air kinetics, proc_update / proc_interrupt / proc_physics / proc_map);
  - status and motion enums: src/ft/ftdef.h, src/ft/ftchar/ftmario/ftmario.h;
  - Mario's motion table: src/ft/ftdata.c (the PORT branch: animation file id, motion-script offset, animation flags);
  - motion scripts: src/relocData/202_MarioMainMotion.c (word offsets recomputed from the macro definitions in
    src/ft/ftdef.h and checked against the offsets in the symbol names);
  - animations: src/relocData/<file id>_*.c (AObjEvent16 joint streams, replayed with the rules of
    ftAnimParseDObjFigatree, src/ft/ftanim.c);
  - attributes: src/relocData/203_MarioMain.c;
  - the C bodies of every proc and of every function they reference, in src/ft, src/ft/ftcommon,
    src/ft/ftchar/ftmario and src/mp (the call graph, the ftMainSetStatus targets, the window comparisons, the input
    reads, the fields written at entry).

The C is not compiled: functions are found by the decomp's layout (definition line, "{", "}" at column 0) and the
preprocessor is evaluated for one configuration (REGION_US, with or without PORT). Every derived fact carries a
file:line. Heuristic parts are named as such in the output ("heuristic": ...).

Nothing here proposes a route, an input sequence or a place on the stage.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

TABLE_SCHEMA = "btt_state_table_v1"

# --------------------------------------------------------------------------------------------------------------------
# Source loading and a small preprocessor
# --------------------------------------------------------------------------------------------------------------------

_DIRECTIVE = re.compile(r"^\s*#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)$")


def _eval_condition(expr: str, defines: Mapping[str, int]) -> bool:
    expr = re.sub(r"//.*", "", expr)
    expr = re.sub(r"/\*.*?\*/", "", expr)
    expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)", lambda m: "1" if m.group(1) in defines else "0", expr)
    expr = re.sub(r"defined\s+(\w+)", lambda m: "1" if m.group(1) in defines else "0", expr)

    def ident(m: "re.Match[str]") -> str:
        name = m.group(0)
        if name in ("and", "or", "not"):
            return name
        return str(int(defines.get(name, 0)))

    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    expr = re.sub(r"\b[A-Za-z_]\w*\b", ident, expr)
    if not re.fullmatch(r"[\s0-9()<>=!+\-*/andortx]*", expr):
        return False
    try:
        return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - digits and operators only (checked above)
    except Exception:
        return False


def preprocess(lines: Sequence[str], defines: Mapping[str, int]) -> List[str]:
    """Blank out inactive lines and the directives themselves; keeps line numbers."""
    out: List[str] = []
    stack: List[Tuple[bool, bool, bool]] = []  # (parent_active, this_active, any_taken)
    active = True
    for line in lines:
        m = _DIRECTIVE.match(line)
        if not m:
            out.append(line if active else "")
            continue
        kind, rest = m.group(1), m.group(2)
        if kind in ("ifdef", "ifndef", "if"):
            if kind == "ifdef":
                cond = rest.split()[0] in defines if rest.split() else False
            elif kind == "ifndef":
                cond = rest.split()[0] not in defines if rest.split() else True
            else:
                cond = _eval_condition(rest, defines)
            stack.append((active, active and cond, cond))
            active = active and cond
        elif kind == "elif":
            if stack:
                parent, _, taken = stack[-1]
                cond = (not taken) and _eval_condition(rest, defines)
                stack[-1] = (parent, parent and cond, taken or cond)
                active = parent and cond
        elif kind == "else":
            if stack:
                parent, _, taken = stack[-1]
                stack[-1] = (parent, parent and not taken, True)
                active = parent and not taken
        elif kind == "endif":
            if stack:
                parent, _, _ = stack.pop()
                active = parent
        out.append("")
    return out


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


@dataclass
class SourceFile:
    path: Path
    rel: str
    raw: List[str]
    lines: List[str]          # preprocessed, comments stripped, same line count as raw

    def text(self) -> str:
        return "\n".join(self.lines)


def load_source(root: Path, rel: str, defines: Mapping[str, int]) -> SourceFile:
    path = root / rel
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    pre = preprocess(raw, defines)
    stripped = strip_comments("\n".join(pre)).split("\n")
    return SourceFile(path, rel, raw, stripped)


# --------------------------------------------------------------------------------------------------------------------
# Enums, attributes, descriptor tables
# --------------------------------------------------------------------------------------------------------------------

def parse_enum(text: str, enum_name: str, known: Optional[Mapping[str, int]] = None) -> Dict[str, int]:
    m = re.search(r"typedef\s+enum\s+" + re.escape(enum_name) + r"\s*\{(.*?)\}\s*" + re.escape(enum_name) + r"\s*;",
                  text, flags=re.S)
    if not m:
        raise ValueError(f"enum {enum_name} not found")
    body = strip_comments(m.group(1))
    values: Dict[str, int] = {}
    env: Dict[str, int] = dict(known or {})
    cur = -1
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            name, expr = (s.strip() for s in item.split("=", 1))
            expr = re.sub(r"\b[A-Za-z_]\w*\b", lambda mm: str(env.get(mm.group(0), values.get(mm.group(0), 0))), expr)
            cur = int(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - integers only
        else:
            name = item
            cur += 1
        values[name] = cur
        env[name] = cur
    return values


def parse_attributes(text: str) -> Dict[str, Any]:
    """FTAttributes initializer of 203_MarioMain.c: '<value>, /* <name> */' per line (US branch)."""
    attrs: Dict[str, Any] = {}
    for m in re.finditer(r"^\s*([-\w.{}\s,x]+?),?\s*/\*\s*(\w+)\s*\*/", text, flags=re.M):
        val, name = m.group(1).strip().rstrip(","), m.group(2)
        num = re.fullmatch(r"(-?\d+(?:\.\d+)?)f?", val)
        if num:
            attrs[name] = float(num.group(1)) if "." in num.group(1) else int(num.group(1))
        else:
            attrs[name] = val
    return attrs


@dataclass
class StatusDesc:
    sid: int
    name: str
    motion: str
    kinetics: str
    procs: Dict[str, Optional[str]]
    line: str


def parse_status_descs(src: SourceFile, base_id: int) -> List[StatusDesc]:
    out: List[StatusDesc] = []
    raw = src.raw
    for i, line in enumerate(raw):
        m = re.match(r"\s*//\s*Status\s+(\d+)\s+\(0x[0-9A-Fa-f]+\):\s*(.+?)\s*$", line)
        if not m:
            continue
        sid, name = int(m.group(1)), m.group(2).strip()
        body: List[str] = []
        depth = 0
        started = False
        for j in range(i + 1, min(i + 60, len(raw))):
            seg = raw[j]
            if "{" in seg:
                depth += seg.count("{")
                started = True
                seg = seg.split("{", 1)[1]
            if started:
                if "}" in seg:
                    body.append(seg.split("}", 1)[0])
                    break
                body.append(seg)
        fields = [f.strip() for f in strip_comments("\n".join(body)).replace("\n", " ").split(",")]
        fields = [f for f in fields if f]
        if len(fields) < 11:
            continue
        procs = {k: (None if v in ("NULL", "0") else v) for k, v in zip(("update", "interrupt", "physics", "map"), fields[7:11])}
        out.append(StatusDesc(sid, name, fields[0], "air" if "Air" in fields[4] else "ground", procs, f"{src.rel}:{i + 1}"))
    return out


def parse_motion_descs(src: SourceFile, array: str = "dFTMarioMotionDescs") -> List[Tuple[Any, int, int, str]]:
    """PORT branch rows of FTMotionDesc: (anim file token, script offset, anim flags, file:line)."""
    text_lines = src.lines
    start = next(i for i, l in enumerate(text_lines) if re.search(r"FTMotionDesc\s+" + array + r"\s*\[", l))
    rows: List[Tuple[Any, int, int, str]] = []
    for i in range(start + 1, len(text_lines)):
        l = text_lines[i].strip()
        if l.startswith("};"):
            break
        m = re.match(r"\{?\s*&?(\w+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*\}?\s*,?$", l)
        if m:
            rows.append((m.group(1), int(m.group(2), 0), int(m.group(3), 0), f"{src.rel}:{i + 1}"))
    return rows


# --------------------------------------------------------------------------------------------------------------------
# Functions, macros, call graph
# --------------------------------------------------------------------------------------------------------------------

_DEF = re.compile(r"^(?!\s)(?:static\s+)?(?:inline\s+)?[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*$")


@dataclass
class Function:
    name: str
    params: List[str]
    src: SourceFile
    start: int   # 0-based index of the definition line
    end: int     # 0-based index of the closing brace

    @property
    def body_lines(self) -> List[Tuple[int, str]]:
        return [(i + 1, self.src.lines[i]) for i in range(self.start, self.end + 1)]

    @property
    def body(self) -> str:
        return "\n".join(l for _, l in self.body_lines)

    def loc(self, line_no: Optional[int] = None) -> str:
        return f"{self.src.rel}:{line_no if line_no else self.start + 1}"


@dataclass
class Macro:
    name: str
    params: List[str]
    body: str
    loc: str


def index_functions(sources: Iterable[SourceFile]) -> Tuple[Dict[str, Function], Dict[str, Macro]]:
    funcs: Dict[str, Function] = {}
    macros: Dict[str, Macro] = {}
    for sf in sources:
        lines = sf.lines
        i = 0
        while i < len(lines):
            l = lines[i]
            m = _DEF.match(l)
            if m and not l.lstrip().startswith(("if", "else", "while", "for", "switch", "return")):
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and lines[j].strip() == "{":
                    k = j + 1
                    while k < len(lines) and lines[k].rstrip() != "}":
                        k += 1
                    params = []
                    for p in split_args(m.group(2)):
                        p = p.strip()
                        if not p or p == "void":
                            continue
                        fpm = re.search(r"\(\s*\*\s*(\w+)\s*\)", p)
                        params.append(fpm.group(1) if fpm else p.split()[-1].lstrip("*"))
                    name = m.group(1)
                    if name not in funcs:
                        funcs[name] = Function(name, params, sf, i, k)
                    i = k + 1
                    continue
            i += 1
        # function-like macros (from the raw text: the preprocessor pass blanks directives)
        raw = sf.raw
        i = 0
        while i < len(raw):
            m = re.match(r"\s*#\s*define\s+((?:ft|mp)\w+)\(([^)]*)\)\s*(.*)$", raw[i])
            if m:
                body = m.group(3)
                loc = f"{sf.rel}:{i + 1}"
                while body.rstrip().endswith("\\") and i + 1 < len(raw):
                    body = body.rstrip()[:-1] + " "
                    i += 1
                    body += raw[i]
                macros.setdefault(m.group(1), Macro(m.group(1), [p.strip() for p in m.group(2).split(",") if p.strip()],
                                                    strip_comments(body), loc))
            i += 1
    return funcs, macros


def split_args(text: str) -> List[str]:
    args, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def find_calls(text: str, name: str) -> List[Tuple[int, List[str]]]:
    """(offset, args) for each call name(...) in text, with balanced parentheses."""
    out = []
    for m in re.finditer(r"\b" + re.escape(name) + r"\s*\(", text):
        depth, j = 1, m.end()
        while j < len(text) and depth:
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
            j += 1
        out.append((m.start(), split_args(text[m.end():j - 1])))
    return out


def parse_handler_arrays(sources: Iterable[SourceFile]) -> Dict[str, List[str]]:
    arrays: Dict[str, List[str]] = {}
    for sf in sources:
        text = sf.text()
        for m in re.finditer(r"void\s*\(\s*\*\s*(\w+)\s*\[[^\]]*\]\s*\)\s*\(\s*GObj\s*\*\s*\)\s*=\s*\{(.*?)\};", text, flags=re.S):
            arrays[m.group(1)] = [e.strip() for e in m.group(2).split(",") if e.strip()]
    return arrays


# --------------------------------------------------------------------------------------------------------------------
# Motion scripts
# --------------------------------------------------------------------------------------------------------------------

def motion_macro_words(ftdef: SourceFile) -> Dict[str, Tuple[List[str], int, str]]:
    """name -> (params, words, body) for every ftMotion* macro, expanding sub-macros to count u32 words."""
    raw: Dict[str, Tuple[List[str], str]] = {}
    lines = ftdef.raw
    i = 0
    while i < len(lines):
        m = re.match(r"\s*#\s*define\s+(ftMotion\w+)\s*\(([^)]*)\)\s*(.*)$", lines[i])
        if m:
            body = m.group(3)
            while body.rstrip().endswith("\\") and i + 1 < len(lines):
                body = body.rstrip()[:-1] + " "
                i += 1
                body += lines[i]
            raw[m.group(1)] = ([p.strip() for p in m.group(2).split(",") if p.strip()], strip_comments(body).strip())
        i += 1

    memo: Dict[str, int] = {}

    def words(name: str, depth: int = 0) -> int:
        if name in memo:
            return memo[name]
        params, body = raw[name]
        n = 0
        for part in split_args(body):
            sub = re.match(r"(ftMotion\w+)\s*\(", part)
            if sub and sub.group(1) in raw and depth < 8:
                n += words(sub.group(1), depth + 1)
            else:
                n += 1
        memo[name] = n
        return n

    return {k: (v[0], words(k), v[1]) for k, v in raw.items()}


@dataclass
class MotionScript:
    name: str
    offset: int
    commands: List[Tuple[str, List[str], int]]   # (macro, args, source line)
    loc: str
    words: int = 0
    next_contiguous: Optional[str] = None        # the array that follows in memory (a script without End falls into it)


def parse_motion_file(src: SourceFile, macros: Mapping[str, Tuple[List[str], int, str]]) -> Tuple[List[MotionScript], List[str]]:
    """Every top-level array of the file in order. Motion arrays are sized from the macro word counts; other arrays
    (FTThrowHitDesc: 7 words per entry) are sized when the type is known, otherwise the next symbol whose name carries
    its offset (_0xNNNN) resynchronises the count. A mismatch right after a motion array is reported."""
    text = src.text()
    scripts: List[MotionScript] = []
    problems: List[str] = []
    offset = 0
    exact = True
    known_struct_words = {"FTThrowHitDesc": 7}
    for m in re.finditer(r"^(\w+)\s+(\w+)\s*\[\s*\]\s*=\s*\{(.*?)\};", text, flags=re.S | re.M):
        ctype, name, body = m.group(1), m.group(2), m.group(3)
        start_line = text.count("\n", 0, m.start()) + 1
        hexm = re.search(r"_0x([0-9A-Fa-f]{4})$", name)
        if hexm:
            named = int(hexm.group(1), 16)
            if named != offset and exact:
                problems.append(f"{src.rel}:{start_line}: {name} computed at 0x{offset:04X}, name says 0x{hexm.group(1)}")
            offset, exact = named, True
        if ctype != "ftMotionCommand":
            if ctype in known_struct_words:
                offset += 4 * known_struct_words[ctype] * len(re.findall(r"\{", body))
            else:
                exact = False
            continue
        cmds: List[Tuple[str, List[str], int]] = []
        n_words = 0
        for item, pos in _split_top(body, m.start(3)):
            line = text.count("\n", 0, pos) + 1
            mm = re.match(r"(ftMotion\w+)\s*\((.*)\)\s*$", item, flags=re.S)
            if not mm or mm.group(1) not in macros:
                problems.append(f"{src.rel}:{line}: unrecognised motion element {item[:40]!r}")
                n_words += 1
                continue
            cmds.append((mm.group(1), split_args(mm.group(2)), line))
            n_words += macros[mm.group(1)][1]
        if not exact and not hexm:
            problems.append(f"{src.rel}:{start_line}: {name} offset unknown (unsized data before it)")
        if scripts and scripts[-1].offset + 4 * scripts[-1].words == offset:
            scripts[-1].next_contiguous = name
        scripts.append(MotionScript(name, offset, cmds, f"{src.rel}:{start_line}", n_words))
        offset += 4 * n_words
    return scripts, problems


def _split_top(body: str, base: int) -> List[Tuple[str, int]]:
    out, depth, cur, cur_pos = [], 0, "", None
    for idx, ch in enumerate(body):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            if cur.strip():
                out.append((cur.strip(), cur_pos if cur_pos is not None else base + idx))
            cur, cur_pos = "", None
        else:
            if cur_pos is None and not ch.isspace():
                cur_pos = base + idx
            cur += ch
    if cur.strip():
        out.append((cur.strip(), cur_pos if cur_pos is not None else base))
    return out


RELEVANT_EVENTS = {
    "ftMotionCommandSetFlag0": "flag0", "ftMotionCommandSetFlag1": "flag1", "ftMotionCommandSetFlag2": "flag2",
    "ftMotionCommandSetFlag3": "flag3",
    "ftMotionCommandMakeAttackColl": "hitbox_on", "ftMotionCommandMakeAttackCollScaled": "hitbox_on",
    "ftMotionCommandClearAttackCollID": "hitbox_off", "ftMotionCommandClearAttackCollAll": "hitbox_off_all",
    "ftMotionCommandRefreshAttackCollID": "hitbox_refresh",
    "ftMotionCommandSetAirJumpAdd": "air_jump_add", "ftMotionCommandSetAirJumpMax": "air_jump_max",
    "ftMotionCommandSetHitStatusAll": "hit_status_all", "ftMotionCommandSetHitStatusPartAll": "hit_status_parts",
    "ftMotionCommandSetParallelScript": "parallel_script", "ftMotionCommandSetSlopeContour": "slope_contour",
}

# events that ftMainUpdateMotionEventsForward skips on a fast-forwarded entry (src/ft/ftmain.c:893-929)
FORWARD_SKIPPED = {"flag0", "flag1", "flag2", "hitbox_on", "hitbox_off", "hitbox_off_all", "hitbox_refresh",
                   "air_jump_add", "air_jump_max"}


def simulate_script(scripts_by_name: Mapping[str, MotionScript], start: MotionScript, horizon: int = 400) -> Dict[str, Any]:
    """Event timeline of one motion script in animation frames (frame 0 = the frame the status is set)."""
    events: List[Dict[str, Any]] = []
    t = 0
    stack: List[Tuple[MotionScript, int]] = []
    loops: List[Tuple[int, int]] = []     # (command index after LoopBegin, remaining)
    script, pc = start, 0
    end_kind = "fell_off"
    steps = 0
    seen_goto: Set[Tuple[str, int]] = set()
    while steps < 20000:
        steps += 1
        if pc >= len(script.commands):
            nxt = scripts_by_name.get(script.next_contiguous or "")
            if nxt is None:
                end_kind = "fell_off"
                break
            script, pc = nxt, 0          # no End: execution continues into the next array in memory
            continue
        name, args, line = script.commands[pc]
        pc += 1
        short = name.replace("ftMotionCommand", "").replace("ftMotion", "")
        if name == "ftMotionCommandWait":
            t += _int(args[0])
        elif name == "ftMotionCommandWaitAsync":
            t = max(t, _int(args[0]))
        elif name == "ftMotionCommandEnd":
            end_kind = "end"
            break
        elif name == "ftMotionCommandPauseScript":
            end_kind = "pause"
            break
        elif name == "ftMotionCommandGoto":
            target = scripts_by_name.get(args[0].strip())
            if target is None:
                end_kind = f"goto_unresolved:{args[0]}"
                break
            if (target.name, t) in seen_goto or t > horizon:
                end_kind = "loops"
                break
            seen_goto.add((target.name, t))
            script, pc = target, 0
        elif name == "ftMotionCommandSubroutine":
            target = scripts_by_name.get(args[0].strip())
            if target is None:
                continue
            stack.append((script, pc))
            script, pc = target, 0
        elif name == "ftMotionCommandReturn":
            if not stack:
                end_kind = "return_without_call"
                break
            script, pc = stack.pop()
        elif name == "ftMotionCommandLoopBegin":
            loops.append((pc, _int(args[0])))
        elif name == "ftMotionCommandLoopEnd":
            if loops:
                at, remaining = loops[-1]
                remaining -= 1
                if remaining > 0:
                    loops[-1] = (at, remaining)
                    pc = at
                else:
                    loops.pop()
        elif name in RELEVANT_EVENTS:
            ev: Dict[str, Any] = {"frame": t, "event": RELEVANT_EVENTS[name], "line": f"{script.loc.split(':')[0]}:{line}"}
            if name.startswith("ftMotionCommandSetFlag") or name in ("ftMotionCommandSetHitStatusAll", "ftMotionCommandSetHitStatusPartAll",
                                                                     "ftMotionCommandSetSlopeContour", "ftMotionCommandSetAirJumpAdd",
                                                                     "ftMotionCommandSetAirJumpMax"):
                ev["value"] = _int(args[0]) if args else None
            elif name.startswith("ftMotionCommandMakeAttackColl"):
                ev["hitbox"] = _int(args[0])
                ev["damage"] = _int(args[3])
                ev["element"] = _int(args[5])
                ev["size"] = _int(args[6])
            elif name in ("ftMotionCommandClearAttackCollID", "ftMotionCommandRefreshAttackCollID"):
                ev["hitbox"] = _int(args[0])
            events.append(ev)
        if t > horizon:
            end_kind = "horizon"
            break
    return {"events": events, "end_frame": t, "end": end_kind}


def _int(s: str) -> int:
    s = s.strip()
    try:
        return int(s, 0)
    except ValueError:
        m = re.fullmatch(r"\(?\s*(-?\d+)\s*\)?", s)
        return int(m.group(1)) if m else 0


def hitbox_windows(events: Sequence[Mapping[str, Any]]) -> List[List[int]]:
    """[first frame, last frame] of each interval with at least one hitbox on (frames are animation frames)."""
    live: Set[int] = set()
    out: List[List[int]] = []
    start: Optional[int] = None
    for ev in sorted(events, key=lambda e: e["frame"]):
        f, kind = ev["frame"], ev["event"]
        if kind == "hitbox_on":
            if not live:
                start = f
            live.add(ev.get("hitbox", 0))
        elif kind == "hitbox_off_all" or (kind == "hitbox_off" and ev.get("hitbox") in live):
            if kind == "hitbox_off_all":
                live.clear()
            else:
                live.discard(ev.get("hitbox"))
            if not live and start is not None:
                if f - 1 >= start:
                    out.append([start, f - 1])
                start = None
    if live and start is not None:
        out.append([start, None])  # open: cleared by the status change or the animation end
    return out


# --------------------------------------------------------------------------------------------------------------------
# Animations (AObjEvent16 figatrees)
# --------------------------------------------------------------------------------------------------------------------

_FT_TRACK = {"FT_ANIM_ROTX": 1, "FT_ANIM_ROTY": 2, "FT_ANIM_ROTZ": 4, "FT_ANIM_TRAI": 8, "FT_ANIM_TRAX": 16,
             "FT_ANIM_TRAY": 32, "FT_ANIM_TRAZ": 64, "FT_ANIM_SCAX": 128, "FT_ANIM_SCAY": 256, "FT_ANIM_SCAZ": 512}
_ANIM_OPS = {"ftAnimEnd": (0, None, False), "ftAnimBlock": (1, None, True), "ftAnimBlock0": (1, None, False),
             "ftAnimSetValBlockT": (2, None, True), "ftAnimSetValBlock": (2, None, False),
             "ftAnimSetValT": (3, None, True), "ftAnimSetVal": (3, None, False),
             "ftAnimSetValRateBlockT": (4, None, True), "ftAnimSetValRateBlock": (4, None, False),
             "ftAnimSetValRateT": (5, None, True), "ftAnimSetValRate": (5, None, False),
             "ftAnimSetTargetRateBlockT": (6, None, True), "ftAnimSetTargetRateBlock": (6, None, False),
             "ftAnimSetTargetRateT": (6, None, True), "ftAnimSetTargetRate": (6, None, False),
             "ftAnimSetVal0RateBlockT": (7, None, True), "ftAnimSetVal0RateBlock": (7, None, False),
             "ftAnimSetVal0RateT": (8, None, True), "ftAnimSetVal0Rate": (8, None, False),
             "ftAnimSetValAfterBlockT": (9, None, True), "ftAnimSetValAfterBlock": (9, None, False),
             "ftAnimSetValAfterT": (10, None, True), "ftAnimSetValAfter": (10, None, False),
             "ftAnimSetFlagsT": (14, None, True), "ftAnimSetFlags": (14, None, False)}


def _eval_flags(expr: str) -> int:
    expr = expr.strip()
    val = 0
    for part in expr.split("|"):
        part = part.strip().strip("()")
        if part in _FT_TRACK:
            val |= _FT_TRACK[part]
        elif part:
            val |= int(part, 0)
    return val


def anim_words(body: str) -> List[int]:
    """Expand one u16 joint-stream initializer into its 16-bit words."""
    words: List[int] = []
    for item, _ in _split_top(strip_comments(body), 0):
        m = re.match(r"(ftAnim\w+)\s*\((.*)\)\s*$", item, flags=re.S)
        if m:
            name, args = m.group(1), split_args(m.group(2))
            if name == "ftAnimLoop":
                words += [_int(args[0]) & 0xFFFF, _int(args[1]) & 0xFFFF]
                continue
            op, _, toggle = _ANIM_OPS[name]
            flags = _eval_flags(args[0]) if args else 0
            words.append(((op << 11) | (flags << 1) | (1 if toggle else 0)) & 0xFFFF)
            if toggle:
                words.append(_int(args[1]) & 0xFFFF)
        else:
            words.append(_int(item) & 0xFFFF)
    return words


def anim_stream_length(words: Sequence[int]) -> Dict[str, Any]:
    """Total frames until End, replaying the word layout of ftAnimParseDObjFigatree (src/ft/ftanim.c:70-745)."""
    i, total, loops, bit15 = 0, 0, False, False
    guard = 0
    while i < len(words) and guard < 100000:
        guard += 1
        w = words[i]
        op, flags, toggle = w >> 11, (w >> 1) & 0x3FF, w & 1
        i += 1
        if op == 0:
            return {"frames": total, "loops": False, "payload_bit15": bit15}
        if op == 13:   # Loop: offset word, jump back -> the stream never ends
            return {"frames": total, "loops": True, "payload_bit15": bit15}
        if op == 12:   # SetTranslateInterp: one offset word
            i += 1
            continue
        payload = 0
        if op in (1, 14):
            if toggle:
                payload = words[i] if i < len(words) else 0
                i += 1
        elif op in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
            if toggle:
                payload = words[i] if i < len(words) else 0
                i += 1
            per = 2 if op in (4, 5) else (0 if op == 11 else 1)
            i += per * bin(flags).count("1")
        if toggle and payload & 0x8000:
            bit15 = True
        if op in (1, 2, 4, 7, 9, 14) and toggle:
            total += payload
    return {"frames": total, "loops": loops, "payload_bit15": bit15, "unterminated": True}


def parse_anim_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    clean = strip_comments(text)
    arrays = {m.group(1): m.group(2) for m in re.finditer(r"u16\s+(\w+)\s*\[\s*\d*\s*\]\s*=\s*\{(.*?)\};", clean, flags=re.S)}
    table = re.search(r"AObjEvent32\s*\*\s*(\w+_joints)\s*\[\s*\]\s*=\s*\{(.*?)\};", clean, flags=re.S)
    order: List[Optional[str]] = []
    if table:
        for item in split_args(table.group(2)):
            mm = re.search(r"(\w+_joint\d+)", item)
            order.append(mm.group(1) if mm else None)
    lengths = []
    for slot, name in enumerate(order):
        if name and name in arrays:
            info = anim_stream_length(anim_words(arrays[name]))
            lengths.append({"slot": slot, "array": name, **info})
    finite = [l["frames"] for l in lengths if not l["loops"]]
    last = lengths[-1] if lengths else None
    return {"file": path.name, "joints": len(lengths),
            "loops": any(l["loops"] for l in lengths),
            "length_last_joint": None if not last or last["loops"] else last["frames"],
            "length_max": max(finite) if finite else None, "length_min": min(finite) if finite else None,
            "payload_bit15": any(l["payload_bit15"] for l in lengths)}


# --------------------------------------------------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------------------------------------------------

SOURCE_FILES = [
    "src/ft/ftmain.c", "src/ft/ftanimend.c", "src/ft/ftphysics.c", "src/ft/ftparam.c", "src/ft/fthammer.c",
    "src/mp/mpcommon.c",
]
SOURCE_GLOBS = ["src/ft/ftcommon/*.c", "src/ft/ftchar/ftmario/*.c"]
HEADER_FILES = ["src/ft/ftcommon.h", "src/ft/ftchar/ftmario/ftmario.h", "src/ft/ftdef.h", "src/ft/fighter.h"]

# Statuses Mario cannot reach in Break the Targets, with the reason (checked in the code; see STATE_MACHINE_CANDIDATES.md)
BTT_EXCLUDED: List[Tuple[Tuple[int, int], str]] = [
    ((4, 9), "sleep, entry, rebirth: before Go or after a lost stock"),
    ((37, 57), "damage family: nothing on the stage damages Mario"),
    ((60, 65), "Twister, barrel, pipes: not on this stage"),
    ((67, 83), "down / passive: entered from damage or shield-break falls only"),
    ((82, 83), "rebound: needs a clank with another hitbox"),
    ((84, 99), "ledge: no line carries the ledge flag on this stage"),
    ((100, 151), "item and hammer statuses: Mario holds no item (targets cannot be picked up)"),
    ((167, 188), "grab follow-ups, capture, thrown: need another fighter"),
    ((221, 222), "appear: before Go"),
]
BTT_TERMINAL = {0: "DeadDown", 1: "DeadLeftRight", 2: "DeadUpStar", 3: "DeadUpFall"}

STATUS_CONST = re.compile(r"\bnFT(?:Common|Mario)Status\w+\b")
WINDOW_TOKENS = re.compile(r"anim_frame|status_total_tics|motion_vars\.flags\.flag\d|status_vars\.[\w.]+|jumps_used|"
                           r"tics_since_last_z|tap_stick_[xy]|hold_stick_[xy]|stick_range\.[xy]|button_(?:tap|hold|release)|"
                           r"vel_air\.[xy]|is_expend_tornado|is_fastfall")
INPUT_TOKENS = re.compile(r"button_(?:tap|hold|release)\s*&\s*(?:\([^()]*\)|[\w.>\-]+)|"
                          r"stick_range\.[xy]|tap_stick_[xy]|hold_stick_[xy]|tics_since_last_z")
WRITE_FIELD = re.compile(r"\b(?:fp|this_fp)->((?:[\w]+(?:\.|->))*[\w]+)\s*(?:[+\-*/|&]?=)(?!=)")
NOT_TRAVERSED = re.compile(r"^(ftMainSetStatus|ftMainPlayAnim\w*|ftMainUpdateMotion\w*|ftParam(?!SetStickLR)\w*|ftPhysics\w*|"
                           r"mpProcess\w*|mpCollision\w*|gm\w+|ef\w+|sy\w+|lb\w+|gc\w+|func_\w+|it\w+|wp\w+|if\w+|"
                           r"ftPublic\w*|ftCommonDead\w*|port_\w+)$")


def btt_exclusion(sid: int) -> Optional[str]:
    for (lo, hi), why in BTT_EXCLUDED:
        if lo <= sid <= hi:
            return why
    return None


@dataclass
class Model:
    root: Path
    defines: Dict[str, int]
    sources: Dict[str, SourceFile] = field(default_factory=dict)
    funcs: Dict[str, Function] = field(default_factory=dict)
    macros: Dict[str, Macro] = field(default_factory=dict)
    arrays: Dict[str, List[str]] = field(default_factory=dict)
    status_ids: Dict[str, int] = field(default_factory=dict)
    motion_ids: Dict[str, int] = field(default_factory=dict)
    statuses: Dict[int, StatusDesc] = field(default_factory=dict)
    param_setters: Dict[str, int] = field(default_factory=dict)   # function -> index of its status-id parameter
    constants: Dict[str, float] = field(default_factory=dict)     # numeric #defines of the headers
    problems: List[str] = field(default_factory=list)

    def const(self, expr: str) -> Optional[float]:
        """Numeric value of a constant expression made of literals and known #defines, else None."""
        e = strip_comments(str(expr)).strip()
        for _ in range(4):
            e2 = re.sub(r"\b[A-Za-z_]\w*\b", lambda m: repr(self.constants[m.group(0)]) if m.group(0) in self.constants else m.group(0), e)
            if e2 == e:
                break
            e = e2
        e = re.sub(r"(\d+\.?\d*)[fF]\b", r"\1", e)
        if not re.fullmatch(r"[\s0-9.()+\-*/eE]*", e) or not e.strip():
            return None
        try:
            return float(eval(e, {"__builtins__": {}}, {}))  # noqa: S307 - digits and operators only
        except Exception:
            return None

    def caller_args(self, fname: str, param: str, depth: int = 3) -> List[Tuple[str, str]]:
        """(expression, file:line) passed for parameter `param` of fname by its callers, followed through wrappers."""
        f = self.funcs.get(fname)
        if f is None or param not in f.params:
            return []
        idx = f.params.index(param)
        out: List[Tuple[str, str]] = []
        for g in self.funcs.values():
            for off, args in find_calls(g.body, fname):
                if len(args) <= idx:
                    continue
                arg = args[idx]
                line = g.loc(g.start + 1 + g.body.count("\n", 0, off))
                if arg in g.params and depth > 0:
                    out += self.caller_args(g.name, arg, depth - 1) or [(arg, line)]
                else:
                    out.append((arg, line))
        return out

    @classmethod
    def load(cls, root: Path, port: bool = False) -> "Model":
        defines = {"REGION_US": 1}
        if port:
            defines.update({"PORT": 1, "NON_MATCHING": 1, "NON_EQUIVALENT": 1, "AVOID_UB": 1})
        m = cls(root, defines)
        rels = list(SOURCE_FILES) + list(HEADER_FILES)
        for g in SOURCE_GLOBS:
            rels += sorted(str(p.relative_to(root)) for p in root.glob(g))
        for rel in rels:
            if (root / rel).exists():
                m.sources[rel] = load_source(root, rel, defines)
        m.funcs, m.macros = index_functions(m.sources.values())
        m.arrays = parse_handler_arrays(m.sources.values())
        ftdef_text = "\n".join(m.sources["src/ft/ftdef.h"].raw)
        common = parse_enum(ftdef_text, "FTCommonStatus")
        mario_h = "\n".join(m.sources["src/ft/ftchar/ftmario/ftmario.h"].raw)
        mario = parse_enum(mario_h, "ftMarioStatus", common)
        m.status_ids = {**common, **mario}
        cm = parse_enum(ftdef_text, "FTCommonMotion")
        m.motion_ids = {**cm, **parse_enum(mario_h, "ftMarioMotion", cm)}
        common_descs = load_source(root, "src/ft/ftcommon/ftcommonstatus.h", defines)
        mario_descs = load_source(root, "src/ft/ftchar/ftmario/ftmariostatus.h", defines)
        for d in parse_status_descs(common_descs, 0) + parse_status_descs(mario_descs, 220):
            m.statuses[d.sid] = d
        for f in m.funcs.values():
            for _, args in find_calls(f.body, "ftMainSetStatus"):
                if len(args) > 1 and args[1] in f.params:
                    m.param_setters[f.name] = f.params.index(args[1])
        for rel in HEADER_FILES:
            sf = m.sources.get(rel)
            if not sf:
                continue
            raw = sf.raw
            for i, line in enumerate(raw):
                mm = re.match(r"\s*#\s*define\s+([A-Z_][A-Z0-9_]*)\s+(.*)$", line)
                if not mm:
                    continue
                val = mm.group(2)
                j = i
                while val.rstrip().endswith("\\") and j + 1 < len(raw):
                    j += 1
                    val = val.rstrip()[:-1] + " " + raw[j]
                v = m.const(val)
                if v is not None:
                    m.constants[mm.group(1)] = v
        return m

    def resolve(self, f: Function, expr: str) -> List[Dict[str, Any]]:
        """Values an argument expression of f can take: itself when constant, the callers' arguments when a parameter."""
        if expr in f.params:
            return [{"expr": e, "value": self.const(e), "line": l} for e, l in self.caller_args(f.name, expr)]
        return [{"expr": expr, "value": self.const(expr)}]

    # -- call graph -------------------------------------------------------------------------------------------------

    def refs(self, f: Function) -> List[Tuple[str, int]]:
        """Functions (and macros, expanded) referenced in f's body, with their line numbers."""
        out: List[Tuple[str, int]] = []
        for line_no, line in f.body_lines[1:]:
            for m in re.finditer(r"\b(dFTCommonSpecial\w+StatusList)\s*\[\s*fp->fkind\s*\]", line):
                arr = self.arrays.get(m.group(1))
                if arr:
                    out.append((arr[0], line_no))     # index 0 = nFTKindMario
            for m in re.finditer(r"\b([A-Za-z_]\w*)\b", line):
                name = m.group(1)
                if name == f.name:
                    continue
                if name in self.funcs:
                    out.append((name, line_no))
                elif name in self.macros:
                    for mm in re.finditer(r"\b([A-Za-z_]\w*)\b", self.macros[name].body):
                        if mm.group(1) in self.funcs:
                            out.append((mm.group(1), line_no))
        return out

    def direct_sets(self, f: Function) -> List[Dict[str, Any]]:
        """ftMainSetStatus calls in f (and status ids passed to param setters), with arguments."""
        out = []
        body = f.body
        for off, args in find_calls(body, "ftMainSetStatus"):
            line_no = f.start + 1 + body.count("\n", 0, off)
            ids = STATUS_CONST.findall(args[1]) if len(args) > 1 else []
            rel = re.fullmatch(r"\s*fp->status_id\s*\+\s*\(\s*(\w+)\s*-\s*(\w+)\s*\)\s*", args[1]) if len(args) > 1 else None
            relative = None
            if rel and rel.group(1) in self.status_ids and rel.group(2) in self.status_ids:
                relative = self.status_ids[rel.group(1)] - self.status_ids[rel.group(2)]
                ids = []
            elif not ids and len(args) > 1 and args[1] not in f.params:
                ids = STATUS_CONST.findall(body)
            out.append({"ids": sorted({self.status_ids[i] for i in ids if i in self.status_ids}),
                        "frame_begin": args[2] if len(args) > 2 else "?", "anim_speed": args[3] if len(args) > 3 else "?",
                        "flags": args[4] if len(args) > 4 else "?", "line": f.loc(line_no), "offset": off,
                        "param": len(args) > 1 and args[1] in f.params, "relative": relative})
        for name, idx in self.param_setters.items():
            for off, args in find_calls(body, name):
                if len(args) > idx:
                    ids = STATUS_CONST.findall(args[idx])
                    if not ids and re.fullmatch(r"\w+", args[idx]):
                        # a variable: the constants of the caller and of the functions it calls that return one
                        ids = STATUS_CONST.findall(body)
                        for ref, _ in self.refs(f):
                            rf = self.funcs.get(ref)
                            if rf and re.search(r"return\b[^;]*\bnFT(?:Common|Mario)Status", rf.body):
                                ids += STATUS_CONST.findall(rf.body)
                    if ids:
                        line_no = f.start + 1 + body.count("\n", 0, off)
                        g = self.funcs[name]
                        inner = next((s for s in self.direct_sets(g) if s["param"]), {})

                        def mapped(key: str) -> str:
                            v = inner.get(key, "?")
                            return args[g.params.index(v)] if v in g.params and g.params.index(v) < len(args) else v

                        out.append({"ids": sorted({self.status_ids[i] for i in ids if i in self.status_ids}),
                                    "frame_begin": mapped("frame_begin"), "anim_speed": mapped("anim_speed"),
                                    "flags": mapped("flags"), "line": f.loc(line_no), "offset": off,
                                    "via": name, "param": False})
        return out

    def targets(self, fname: str, depth: int = 7, origin: Optional[int] = None) -> Dict[int, List[str]]:
        """Status ids reachable by calling fname, with the first call chain found (breadth first). A status set
        relative to the current one (fp->status_id + (A - B)) resolves against `origin`."""
        found: Dict[int, List[str]] = {}
        frontier: List[Tuple[str, List[str]]] = [(fname, [fname])]
        seen = {fname}
        for _ in range(depth):
            nxt: List[Tuple[str, List[str]]] = []
            for name, chain in frontier:
                f = self.funcs.get(name)
                if f is None:
                    continue
                for s in self.direct_sets(f):
                    for sid in s["ids"]:
                        found.setdefault(sid, chain + [s["line"]])
                    if s.get("relative") is not None and origin is not None:
                        found.setdefault(origin + s["relative"], chain + [s["line"] + " (relative)"])
                for ref, _ in self.refs(f):
                    if ref in seen or NOT_TRAVERSED.match(ref):
                        continue
                    seen.add(ref)
                    nxt.append((ref, chain + [ref]))
            frontier = nxt
        return found

    def setters_of(self, sid: int) -> List[Tuple[Function, Dict[str, Any]]]:
        out = []
        for f in self.funcs.values():
            if f.name == "ftMainSetStatus":
                continue
            for s in self.direct_sets(f):
                # a relative set (fp->status_id + k) produces sid from sid - k; only the aerials call one on Mario's path
                if sid in s["ids"] or (s.get("relative") is not None and sid - s["relative"] in self.statuses and
                                       self.statuses[sid - s["relative"]].name.startswith("AttackAir")):
                    out.append((f, s))
        return out

    AIR_MAP = {"mpCommonCheckFighterLanding", "mpCommonProcFighterLanding", "mpCommonCheckFighterPass",
               "mpCommonCheckFighterPassCliff", "mpCommonCheckFighterCliff", "mpCommonProcFighterCliff",
               "mpCommonCheckFighterCeilHeavy", "mpCommonCheckFighterCeilHeavyCliff", "mpCommonCheckFighterProject",
               "mpCommonProcFighterCliffFloorCeil", "mpCommonProcFighterWaitOrLanding", "mpCommonProcFighterCliffWaitOrLanding",
               "mpCommonProcFighterProject", "mpCommonUpdateFighterKinetics"}
    GROUND_MAP = {"mpCommonCheckFighterOnFloor", "mpCommonProcFighterOnFloor", "mpCommonCheckFighterOnEdge",
                  "mpCommonProcFighterOnEdge", "mpCommonCheckFighterOnCliffEdge", "mpCommonProcFighterOnCliffEdge",
                  "mpCommonSetFighterFallOnEdgeBreak", "mpCommonSetFighterFallOnGroundBreak", "mpCommonUpdateFighterKinetics"}

    def map_kind(self, name: Optional[str]) -> str:
        """Which collision family the map proc runs (air: landing tests; ground: floor-follow tests)."""
        if not name:
            return "?"
        names = {name}
        f = self.funcs.get(name)
        if f:
            names |= {r for r, _ in self.refs(f)}
        air, ground = bool(names & self.AIR_MAP), bool(names & self.GROUND_MAP)
        return "air and ground (branches on fp->ga)" if air and ground else "air" if air else "ground" if ground else "?"

    def fkind_guard(self, f: Function, offset: int) -> List[str]:
        """nFTKind names of an enclosing `if (... fkind == X ...)` block around `offset`, when none is a Mario kind."""
        body = f.body
        kinds: Set[str] = set()
        for m in re.finditer(r"\bif\s*\(", body[:offset]):
            depth, j = 1, m.end()
            while j < len(body) and depth:
                depth += {"(": 1, ")": -1}.get(body[j], 0)
                j += 1
            cond = body[m.end():j - 1]
            ks = re.findall(r"fkind\s*==\s*(nFTKind\w+)", cond)
            if not ks:
                continue
            k = j
            while k < len(body) and body[k].isspace():
                k += 1
            if k < len(body) and body[k] == "{":
                depth, e = 1, k + 1
                while e < len(body) and depth:
                    depth += {"{": 1, "}": -1}.get(body[e], 0)
                    e += 1
                inside = k < offset < e
            else:
                inside = k <= offset < body.find(";", k) + 1
            if inside:
                kinds.update(ks)
        return sorted(kinds) if kinds and not any("Mario" in k for k in kinds) else []

    def exit_hooks(self, f: Function) -> List[Dict[str, Any]]:
        """fp->proc_status = X in a setter: X runs inside the NEXT ftMainSetStatus (src/ft/ftmain.c, proc_status)."""
        out = []
        for m in re.finditer(r"fp->proc_status\s*=\s*(\w+)", f.body):
            g = self.funcs.get(m.group(1))
            out.append({"hook": m.group(1), "writes": sorted({w["field"] for w in self.writes(g)}) if g else [],
                        "line": g.loc() if g else None})
        return out

    # -- per-function facts -----------------------------------------------------------------------------------------

    def window_lines(self, f: Function) -> List[Dict[str, Any]]:
        out = []
        for line_no, line in f.body_lines:
            s = line.strip()
            if not s or not re.search(r"\b(if|else if|while|return|switch)\b|\?|[<>]=?|==|!=", s):
                continue
            toks = sorted(set(WINDOW_TOKENS.findall(s)))
            if toks and re.search(r"[<>]=?|==|!=|&|\?|\bif\b", s):
                out.append({"line": f.loc(line_no), "code": re.sub(r"\s+", " ", s)[:160], "reads": toks})
        return out

    def inputs_read(self, fname: str, depth: int = 4) -> List[str]:
        seen, frontier, toks = {fname}, [fname], set()
        for _ in range(depth):
            nxt = []
            for name in frontier:
                f = self.funcs.get(name)
                if f is None:
                    continue
                for line in f.lines_text():
                    for t in INPUT_TOKENS.findall(line):
                        toks.add(re.sub(r"\s+", " ", t.strip()))
                for ref, _ in self.refs(f):
                    if ref not in seen and not NOT_TRAVERSED.match(ref) and not ref.endswith("SetStatus"):
                        seen.add(ref)
                        nxt.append(ref)
            frontier = nxt
        return sorted(toks)

    def writes(self, f: Function, after_offset: int = -1) -> List[Dict[str, Any]]:
        out = []
        body = f.body
        for m in WRITE_FIELD.finditer(body):
            line_no = f.start + 1 + body.count("\n", 0, m.start())
            out.append({"field": m.group(1), "line": f.loc(line_no), "after_set": m.start() > after_offset >= 0})
        return out


def _lines_text(self: Function) -> List[str]:
    return [l for _, l in self.body_lines]


Function.lines_text = _lines_text  # type: ignore[attr-defined]


KINETIC_HELPERS = {
    "mpCommonSetFighterAir": ["ga=air", "jumps_used=1", "vel_air.z=0"],
    "mpCommonSetFighterGround": ["ga=ground", "jumps_used=0", "vel_ground.x=vel_air.x*lr"],
}
ENTRY_HELPER = re.compile(r"InitStatusVars|SetDisableRise|InitVars|ClampAirVel|ClampGroundVel")


def build_table(root: Path) -> Dict[str, Any]:
    model = Model.load(root, port=False)
    port_model = Model.load(root, port=True)
    problems: List[str] = []

    # data: attributes, motion table, scripts, animations
    attr_src = load_source(root, "src/relocData/203_MarioMain.c", model.defines)
    attrs = parse_attributes("\n".join(preprocess(attr_src.raw, model.defines)))   # names live in the comments
    ftdef = model.sources["src/ft/ftdef.h"]
    mmacros = motion_macro_words(ftdef)
    motion_src = load_source(root, "src/relocData/202_MarioMainMotion.c", model.defines)
    scripts, sp = parse_motion_file(motion_src, mmacros)
    problems += sp
    by_offset = {s.offset: s for s in scripts}
    by_name = {s.name: s for s in scripts}
    port_rows = parse_motion_descs(load_source(root, "src/ft/ftdata.c", {"REGION_US": 1, "PORT": 1}))
    reloc_dir = root / "src/relocData"
    anim_cache: Dict[int, Dict[str, Any]] = {}

    def anim_file(token: Any) -> Optional[int]:
        m = re.fullmatch(r"ll_(\d+)_FileID", str(token))
        if m:
            return int(m.group(1))
        m = re.fullmatch(r"llFTMarioAnim(\w+)FileID", str(token))
        if m:
            hits = sorted(reloc_dir.glob(f"*_FTMarioAnim{m.group(1)}.c"))
            if hits:
                return int(hits[0].name.split("_", 1)[0])
        return None

    def anim_info(fid: Optional[int]) -> Optional[Dict[str, Any]]:
        if fid is None:
            return None
        if fid not in anim_cache:
            hits = sorted(reloc_dir.glob(f"{fid}_*.c"))
            anim_cache[fid] = parse_anim_file(hits[0]) if hits else {"file": None, "missing": True}
        return anim_cache[fid]

    statuses: Dict[str, Any] = {}
    edges: List[Dict[str, Any]] = []
    for sid in sorted(model.statuses):
        d = model.statuses[sid]
        motion_id = model.motion_ids.get(d.motion)
        row = port_rows[motion_id] if motion_id is not None and 0 <= motion_id < len(port_rows) else None
        motion: Dict[str, Any] = {"name": d.motion, "id": motion_id}
        script_info = None
        if row:
            fid = anim_file(row[0])
            motion.update({"anim_file": fid, "script_offset": f"0x{row[1]:X}", "anim_flags": f"0x{row[2]:08X}",
                           "event32_anim": bool(row[2] & 0x8), "transn": bool(row[2] & 0x40000000), "row": row[3]})
            motion["anim"] = anim_info(fid)
            if row[1] != 0x80000000:
                sc = by_offset.get(row[1])
                if sc is None:
                    problems.append(f"status {sid}: no motion script at offset 0x{row[1]:X}")
                else:
                    script_info = {"name": sc.name, "loc": sc.loc, **simulate_script(by_name, sc)}
                    script_info["hitbox_windows"] = hitbox_windows(script_info["events"])
        # entry
        setters = model.setters_of(sid)
        entry = []
        for f, s in setters:
            body = f.body
            after = s["offset"]
            dbl = any(off > after for off, _ in find_calls(body, "ftMainPlayAnimEventsAll"))
            kin = [k for k in KINETIC_HELPERS if find_calls(body, k)]
            writes = model.writes(f, after)
            if s.get("via") and s["via"] in model.funcs:
                g = model.funcs[s["via"]]
                g_set = next((x["offset"] for x in model.direct_sets(g) if x["param"]), -1)
                writes += [{**w, "via": g.name} for w in model.writes(g, g_set)]
                dbl = dbl or any(off > g_set for off, _ in find_calls(g.body, "ftMainPlayAnimEventsAll"))
            for ref, _ in model.refs(f):
                if ENTRY_HELPER.search(ref) and ref in model.funcs:
                    writes += [{**w, "via": ref} for w in model.writes(model.funcs[ref])]
            speeds = model.resolve(f, s["anim_speed"])
            fb = s["frame_begin"]
            continuation = "anim_frame" in fb
            guard = model.fkind_guard(f, after)
            hooks = model.exit_hooks(f) + (model.exit_hooks(model.funcs[s["via"]]) if s.get("via") in model.funcs else [])
            entry.append({"setter": f.name, "line": s["line"], "frame_begin": fb, "continuation": continuation,
                          "fkind_guard": guard, "exit_hooks": hooks,
                          "anim_speed": s["anim_speed"], "anim_speed_values": speeds,
                          "frame_begin_value": None if continuation else model.const(fb),
                          "preserve": s["flags"], "via": s.get("via"), "double_advance": dbl, "kinetics": kin,
                          "implied": sorted({x for k in kin for x in KINETIC_HELPERS[k]}),
                          "writes": sorted({w["field"] for w in writes}),
                          "flag_resets": sorted({w["field"].split(".")[-1] for w in writes if "motion_vars.flags" in w["field"]}),
                          "flags_written_after_set": sorted({w["field"].split(".")[-1] for w in writes
                                                             if "motion_vars.flags" in w["field"] and w.get("after_set")})})
        # exits and windows per proc
        exits: Dict[str, Any] = {}
        windows: List[Dict[str, Any]] = []
        flag_reads: Set[str] = set()
        port_only: List[str] = []
        inputs: Set[str] = set()
        for kind, pname in d.procs.items():
            if not pname:
                continue
            f = model.funcs.get(pname)
            if f is None:
                exits[kind] = {"proc": pname, "unresolved": True}
                continue
            tg = model.targets(pname, origin=sid)
            exits[kind] = {"proc": pname, "loc": f.loc(), "targets": {str(k): v for k, v in sorted(tg.items())}}
            for t, chain in sorted(tg.items()):
                edges.append({"from": sid, "to": t, "via": kind, "proc": pname, "chain": chain})
            windows += [{**w, "proc": kind} for w in model.window_lines(f)]
            for _, line in f.body_lines:
                flag_reads.update(re.findall(r"motion_vars\.flags\.(flag\d)(?!\s*=[^=])", line))
            if kind in ("interrupt", "update", "physics"):
                inputs.update(model.inputs_read(pname))
            pf = port_model.funcs.get(pname)
            if pf:
                for (n1, l1), (n2, l2) in zip(f.body_lines, pf.body_lines):
                    if l1.strip() != l2.strip() and l2.strip():
                        port_only.append(f"{pf.src.rel}:{n2}")
        script_flags0 = {e["event"] for e in (script_info or {}).get("events", []) if e["frame"] == 0 and e["event"].startswith("flag")}
        fresh = [e for e in entry if not e["continuation"] and not e["fkind_guard"]]
        early_flags = {}
        for e in (script_info or {}).get("events", []):
            if e["event"].startswith("flag") and e["frame"] <= 1:
                early_flags.setdefault(e["event"], []).append(e["frame"])
        for e in entry:
            reach_frame = 1 if e["double_advance"] else 0
            e["script_flags_wiped_at_entry"] = sorted(fl for fl in e["flags_written_after_set"]
                                                      if any(fr <= reach_frame for fr in early_flags.get(fl, [])))
        resets_all = set.intersection(*[set(e["flag_resets"]) for e in fresh]) if fresh else set()
        stale = sorted(fl for fl in flag_reads if fl not in resets_all and fl not in script_flags0)
        inherited = sorted({fl for e in entry if e["continuation"] for fl in flag_reads if fl not in e["flag_resets"]})
        anim = motion.get("anim") or {}
        length = anim.get("length_last_joint")
        dur = None
        anim_end = [k for k, v in d.procs.items() if v and model.funcs.get(v) and
                    (re.search(r"ftAnimEnd\w*\(|anim_frame\s*<=\s*0", model.funcs[v].body) or v.startswith("ftAnimEnd"))]
        if length is not None and anim_end:
            rows = []
            for e in fresh:
                for sp in e["anim_speed_values"] or [{"expr": e["anim_speed"], "value": None}]:
                    v = sp.get("value")
                    begin = e["frame_begin_value"] or 0.0
                    off = 1 if e["double_advance"] else 0
                    rows.append({"setter": e["setter"], "anim_speed": sp["expr"], "speed": v, "frame_begin": begin,
                                 "entry_offset": off,
                                 "ends_on_tick": None if not v else math.ceil(round((length - begin) / v, 6)) - off})
            dur = {"anim_frames": length, "by_entry": rows,
                   "ends_on_tick": sorted({r["ends_on_tick"] for r in rows if r["ends_on_tick"] is not None}),
                   "basis": "animation end (gobj anim_frame <= 0) checked by proc_" + ", proc_".join(anim_end) +
                            "; tick 0 = the update that set the status"}
        ga = model.map_kind(d.procs.get("map"))
        if sid == 225:
            ga = "ground, then air from the motion event SetAirJumpMax"
        excl = btt_exclusion(sid)
        statuses[str(sid)] = {
            "id": sid, "name": d.name, "ga": ga, "desc_attack_ga": d.kinetics, "desc": d.line, "procs": d.procs, "motion": motion,
            "script": script_info, "entry": entry, "exits": exits, "windows": windows,
            "motion_flags_read": sorted(flag_reads), "stale_flag_candidates": stale,
            "flags_inherited_by_continuation": inherited, "inputs_read": sorted(inputs),
            "duration": dur, "port_only_lines_in_procs": port_only,
            "btt": {"excluded": excl, "terminal": BTT_TERMINAL.get(sid)},
        }

    # reachability from Wait, inside BTT
    reach: Dict[int, List[int]] = {}
    adj: Dict[int, Set[int]] = {}
    for e in edges:
        if btt_exclusion(e["to"]) is None and btt_exclusion(e["from"]) is None:
            adj.setdefault(e["from"], set()).add(e["to"])
    start = model.status_ids["nFTCommonStatusWait"]
    reach[start] = [start]
    frontier = [start]
    while frontier:
        nxt = []
        for s in frontier:
            for t in sorted(adj.get(s, ())):
                if t not in reach:
                    reach[t] = reach[s] + [t]
                    nxt.append(t)
        frontier = nxt
    for sid, st in statuses.items():
        st["btt"]["reachable"] = int(sid) in reach
        st["btt"]["example_path"] = reach.get(int(sid))
    for sid in BTT_TERMINAL:
        statuses[str(sid)]["btt"]["reachable"] = True
        statuses[str(sid)]["btt"]["note"] = "entered from any status by the death check (ftMainProcPhysicsMap -> ftCommonDeadCheckInterruptCommon)"

    return {
        "schema": TABLE_SCHEMA, "fighter": "Mario", "region": "US", "decomp_root": str(root),
        "configuration": "call graph and windows from the non-PORT path (REGION_US); PORT-only lines listed per status",
        "attributes": {k: attrs[k] for k in ("kneebend_anim_length", "jumps_max", "gravity", "tvel_base", "tvel_fast",
                                             "jump_vel_x", "jump_height_mul", "jump_height_base", "jumpaerial_vel_x",
                                             "jumpaerial_height", "air_accel", "air_speed_max_x", "air_friction",
                                             "dash_speed", "run_speed", "traction", "walkslow_anim_length",
                                             "walkmiddle_anim_length", "walkfast_anim_length", "attack1_followup_frames",
                                             "dash_to_run") if k in attrs},
        "statuses": statuses,
        "edges": edges,
        "problems": problems + model.problems,
        "heuristic": ["call graph: identifier references in C bodies (no type analysis), depth 7, infrastructure prefixes not traversed",
                      "a status set through a variable takes every status constant of the setter's body",
                      "animation end = the last non-NULL joint stream of the figatree (the last writer of gobj->anim_frame)",
                      "stale_flag_candidates: motion flags read by a proc, not written by every setter, not set at script frame 0"],
    }


def _speed(s: str) -> float:
    try:
        return float(s.rstrip("Ff"))
    except (ValueError, AttributeError):
        return 0.0


# --------------------------------------------------------------------------------------------------------------------
# Markdown view
# --------------------------------------------------------------------------------------------------------------------

def _names(table: Mapping[str, Any], ids: Iterable[Any], reachable_only: bool = True) -> str:
    out = []
    for i in sorted({int(x) for x in ids}):
        st = table["statuses"].get(str(i))
        if st is None:
            continue
        if reachable_only and not st["btt"].get("reachable"):
            continue
        out.append(f"{st['name']} ({i})")
    return ", ".join(out) if out else "-"


def render_markdown(table: Mapping[str, Any]) -> str:
    """One row per status Mario can reach in Break the Targets. Exits name only reachable statuses."""
    lines = ["# Mario's status table (Break the Targets)", "",
             "Generated by `tools/glitch/states/mario_states.py extract` from the decomp source (no ROM, no game). "
             "Frames are animation frames; **tick 0 is the update that set the status** (status_total_tics = 0 in "
             "the post-update capture). `+1 entry` means the setter runs the first animation frame twice "
             "(ftMainSetStatus then ftMainPlayAnimEventsAll), so the status starts at animation frame 1 and every "
             "animation-frame event happens one tick earlier than its frame number. `cont.` means a continuation "
             "entry: ftMainSetStatus(..., fighter_gobj->anim_frame, ...) with the motion script fast-forwarded "
             "(ftMainUpdateMotionEventsForward skips SetFlag0/1/2, hitbox creation and the air-jump events).", "",
             "Heuristics: " + "; ".join(table.get("heuristic", [])) + ".", ""]
    attrs = table.get("attributes", {})
    if attrs:
        lines += ["Attributes (src/relocData/203_MarioMain.c): " + ", ".join(f"{k} {v}" for k, v in attrs.items()) + ".", ""]
    lines += ["| id | status | collision | anim frames | ends on tick | entry | exits (reachable statuses) | windows read in the procs | motion script (anim frames) | inputs read |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for sid in sorted(table["statuses"], key=int):
        st = table["statuses"][sid]
        if not st["btt"].get("reachable"):
            continue
        anim = (st["motion"].get("anim") or {})
        frames = "loop" if anim.get("loops") else (anim.get("length_last_joint") if anim else "-")
        dur = st.get("duration") or {}
        ends = ", ".join(str(x) for x in dur.get("ends_on_tick", [])) or "-"
        ent = []
        for e in st["entry"]:
            tags = []
            if e["double_advance"]:
                tags.append("+1 entry")
            if e["continuation"]:
                tags.append("cont.")
            if e["fkind_guard"]:
                tags.append("other fighters only")
            if e["implied"]:
                tags.append(", ".join(x for x in e["implied"] if x.startswith("jumps") or x.startswith("ga")))
            if e.get("script_flags_wiped_at_entry"):
                tags.append("wipes script " + "/".join(e["script_flags_wiped_at_entry"]))
            ent.append(f"`{e['setter']}`" + (f" ({'; '.join(tags)})" if tags else ""))
        exits = []
        for kind in ("update", "interrupt", "physics", "map"):
            ex = st["exits"].get(kind)
            if ex and ex.get("targets"):
                exits.append(f"{kind}: {_names(table, ex['targets'])}")
        win = sorted({w["code"] for w in st["windows"] if re.search(r"anim_frame|status_total_tics|flag\d|kneebend|jumps_used|tics_since|expend", w["code"])})
        sc = st.get("script") or {}
        evs = []
        for e in sc.get("events", []):
            if e["event"].startswith("flag") or e["event"].startswith("air_jump") or e["event"] == "hit_status_all":
                evs.append(f"{e['event']}={e.get('value')}@{e['frame']}")
        hb = sc.get("hitbox_windows") or []
        if hb:
            evs.append("hitboxes " + ", ".join(f"{a}-{b if b is not None else 'end'}" for a, b in hb))
        inputs = ", ".join(sorted({re.sub(r"fp->input\.|fp->input\.pl\.", "", x) for x in st["inputs_read"]}))
        notes = []
        if st["stale_flag_candidates"]:
            notes.append("reads " + "/".join(st["stale_flag_candidates"]) + " not reset by every setter")
        if st["flags_inherited_by_continuation"]:
            notes.append("continuation keeps " + "/".join(st["flags_inherited_by_continuation"]))
        if st["port_only_lines_in_procs"]:
            notes.append("PORT-only lines: " + ", ".join(st["port_only_lines_in_procs"][:3]))
        cell = lambda s: (s or "-").replace("|", "\\|")
        lines.append(f"| {sid} | {st['name']} | {st['ga']} | {frames} | {ends} | {cell('<br>'.join(ent))} | "
                     f"{cell('<br>'.join(exits))} | {cell('<br>'.join(win[:6]))} | {cell(', '.join(evs))} | "
                     f"{cell(inputs)}{('<br>' + cell('; '.join(notes))) if notes else ''} |")
    lines += ["", "Not reachable in Break the Targets (reason): " +
              "; ".join(f"{lo}-{hi} {why}" for (lo, hi), why in BTT_EXCLUDED) + ".", ""]
    if table.get("problems"):
        lines += ["Problems found while reading the sources:", ""] + [f"- {p}" for p in table["problems"]] + [""]
    return "\n".join(lines)
