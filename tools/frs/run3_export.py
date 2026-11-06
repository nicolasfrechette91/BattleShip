#!/usr/bin/env python3
"""Run 3 exports of verified clears (2026-11-06 session, step 8; MINOR table O7 and the owner's rule "a bk2 for every verified clear").

    btti            the BattleShip BTT text replay of a clear's words (decomp/src/sys/netreplay.c reads "%x,%d,%d" rows, '#' comments):
                    one row per word from the run's tick 0, buttons in hex, then stick_x and stick_y; written as <name>.btt.txt
                    (TEXT_SUFFIX: the lab guard refuses any path holding ".btti", the human TAS replays' extension).
    bk2             the same rows as a BizHawk-format N64 input movie (a zip holding Header.txt, Comments.txt and Input Log.txt), the
                    inverse of tools/bk2_to_btt_inputs.py: its converter reads the file back to exactly these rows (tested). Frame 0
                    is the run's tick 0 (the BTT session start), not power-on: a file-format export of the words. Writing it runs
                    no BizHawk (docs/rl_decisions_2026-11-04.md section 3).
    text replay     one native replay of the words through the text-replay path (SSB64_RL_BTT, SSB64_BTT_INPUT, no stepping; the path
                    btti and bk2 exports use; SSB64_RL_EXIT_ON_END=1, the M1a exit after the episode, SSB64_MAX_FRAMES as a backstop),
                    for each NEW verified best only, at the close when no other game process runs (the pinned executable keeps one
                    shared port log, so only result.json is read): its completion clocks must equal the verified ones (review D12).

Standard library plus the repo's own modules.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

_RL = Path(__file__).resolve().parents[2] / "rl"
if str(_RL) not in sys.path:
    sys.path.insert(0, str(_RL))

import m8_rd_cells as mcell  # noqa: E402

EXPORT_CONTRACT = "run3_export_v1"
# the lab guard (rl/frs_guard.py G3, rl/m8_rd_worker.FORBIDDEN_FRAGMENTS) refuses any path holding ".btti", so that a lab process never
# touches the human TAS replays: the run's own words in the .btti format are written as .btt.txt (the native reader ignores the extension)
TEXT_SUFFIX = ".btt.txt"
# flag position -> N64 button bit, as tools/bk2_to_btt_inputs.BUTTON_BITS (positions 0..3 are the virtual analog directions, unused here)
BUTTON_BITS = {4: 0x0800, 5: 0x0400, 6: 0x0200, 7: 0x0100, 8: 0x1000, 9: 0x2000, 10: 0x4000, 11: 0x8000, 12: 0x0008, 13: 0x0004, 14: 0x0002,
               15: 0x0001, 16: 0x0020, 17: 0x0010}
MNEMONIC = "UDLRUDLRSZBAudlrLR"
LOG_KEY = ("LogKey:#Reset|Power|#P1 X Axis|P1 Y Axis|P1 A Up|P1 A Down|P1 A Left|P1 A Right|P1 DPad U|P1 DPad D|P1 DPad L|P1 DPad R|P1 Start|"
           "P1 Z|P1 B|P1 A|P1 C Up|P1 C Down|P1 C Left|P1 C Right|P1 L|P1 R|")
ROW_RE = re.compile(r"^\|(?P<console>[^|]*)\|\s*(?P<x>[+-]?\d+)\s*,\s*(?P<y>[+-]?\d+)\s*,(?P<flags>[^|]*)\|$")
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def triples(words: bytes) -> List[Tuple[int, int, int]]:
    return [tuple(mcell.TRIPLES[w]) for w in bytes(words)]  # type: ignore[misc]


def btti_text(words: bytes, comment: str) -> str:
    lines = ["# BattleShip BTT input v1", f"# {comment}"[:400], "# buttons_hex,stick_x,stick_y"]
    lines += [f"{b:04X},{x},{y}" for b, x, y in triples(words)]
    return "\n".join(lines) + "\n"


def bk2_row(b: int, x: int, y: int) -> str:
    flags = ["."] * 18
    for pos, bit in BUTTON_BITS.items():
        if b & bit:
            flags[pos] = MNEMONIC[pos]
    if b & ~sum(BUTTON_BITS.values()):
        raise ValueError(f"button word {b:#06x} has a bit with no bk2 flag")
    return f"|..|{x:5d},{y:5d},{''.join(flags)}|"


def parse_bk2_row(line: str) -> Tuple[int, int, int]:
    """The rules of tools/bk2_to_btt_inputs.parse_row (re-implemented for the run's own round-trip check; the tests compare the two)."""
    m = ROW_RE.match(line.rstrip("\r\n"))
    if not m or any(ch != "." for ch in m.group("console")) or len(m.group("flags")) != 18:
        raise ValueError(f"unsupported bk2 row {line!r}")
    flags = m.group("flags")
    x, y = int(m.group("x")), int(m.group("y"))
    if flags[0] != "." or flags[1] != "." or flags[2] != "." or flags[3] != ".":
        raise ValueError("virtual analog directions are not used")
    b = 0
    for pos, bit in BUTTON_BITS.items():
        if flags[pos] != ".":
            b |= bit
    return b, max(-80, min(80, x)), max(-80, min(80, y))


def bk2_bytes(words: bytes, comment: str) -> bytes:
    rows = [bk2_row(*t) for t in triples(words)]
    header = "\n".join(["MovieVersion BizHawk v2.0.0", "Author BattleShip run 3 (exported words, no emulator involved)", "Platform N64",
                        "Core Mupen64Plus", "rerecordCount 0", "StartsFromSavestate False", f"Frames {len(rows)}"]) + "\n"
    log = "\n".join(["[Input]", LOG_KEY] + rows + ["[/Input]"]) + "\n"
    notes = ("Frame 0 is the RL episode's tick 0 (the BTT session start of BattleShip), not power-on.\n" + comment + "\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in (("Header.txt", header), ("Comments.txt", notes), ("Input Log.txt", log)):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode("utf-8"))
    return buf.getvalue()


def bk2_rows(data: bytes) -> List[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read("Input Log.txt").decode("utf-8-sig")
    rows, inside = [], False
    for line in text.splitlines():
        if line == "[Input]":
            inside = True
        elif line == "[/Input]":
            inside = False
        elif inside and line.startswith("|"):
            rows.append(line)
    return rows


def export_clear(fs: Any, out_dir: Path, name: str, words: bytes, meta: Mapping[str, Any]) -> Dict[str, Any]:
    """Write <name>.btt.txt (the .btti format) and <name>.bk2 through the lab's guarded writer; returns their paths, sha256 and the
    round-trip check."""
    comment = " ".join(f"{k}={meta[k]}" for k in sorted(meta))
    btti = btti_text(words, comment)
    bk2 = bk2_bytes(words, comment)
    back = [parse_bk2_row(r) for r in bk2_rows(bk2)]
    ok = back == triples(words)
    fs.mkdir(out_dir)
    pb, pk = Path(out_dir) / f"{name}{TEXT_SUFFIX}", Path(out_dir) / f"{name}.bk2"
    fs.write_text(pb, btti)
    with open(pk, "wb") as f:
        f.write(bk2)
    return {"contract": EXPORT_CONTRACT, "name": name, "frames": len(words), "btti": str(pb), "bk2": str(pk),
            "btti_sha256": hashlib.sha256(btti.encode("utf-8")).hexdigest(), "bk2_sha256": hashlib.sha256(bk2).hexdigest(),
            "words_digest": mcell.words_digest(words), "roundtrip_ok": ok}


TextReplayFn = Callable[[bytes, str], Dict[str, Any]]


def make_text_replay(executable: Path, work_root: Path, frozen: Optional[Mapping[str, Any]] = None) -> TextReplayFn:
    """A native text replay of words (fresh process, private runtime, no stepping); the pinned files are re-hashed first when given."""
    exe = Path(executable)

    def replay(words: bytes, label: str) -> Dict[str, Any]:
        import frs_verify as fv
        import m8_rd_worker as mw
        from m7_runtime import prepare_worker_runtime

        if frozen is not None:
            bad = fv.frozen_exe_problems(exe.parent, frozen)
            if bad:
                return {"ok": False, "error": f"pin drift: {bad[:3]}"}
        work = Path(work_root) / label
        if work.exists():
            return {"ok": False, "error": f"{work} exists"}
        runtime = work / "runtime"
        out = work / "out"
        text = btti_text(words, f"run 3 text replay {label}")
        btti = work / f"words{TEXT_SUFFIX}"
        try:
            work.mkdir(parents=True)
            btti.write_text(text, encoding="ascii", newline="\n")
            out.mkdir()
            prepare_worker_runtime(runtime, exe)
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith("SSB64_")}
            env.update({"SSB64_RL_BTT": "1", "SSB64_BTT_INPUT": str(btti), "SSB64_RL_EXIT_ON_END": "1", "SSB64_MAX_FRAMES": str(len(words) + 1500),
                        "SSB64_SAVE_PATH": str(out / "save.bin"), "SSB64_RL_RESULT_PATH": str(out / "result.json")})
            t0 = time.perf_counter()
            r = subprocess.run([str(exe)], cwd=str(runtime), env=env, timeout=600, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            wall = round(time.perf_counter() - t0, 2)
            rp = out / "result.json"
            result = json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else None
            return {"ok": True, "exit_code": r.returncode, "wall_s": wall, "result": result, "btti_sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
                    "frames": len(words)}
        except Exception as exc:  # noqa: BLE001 - recorded, never raised into the close
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            try:
                if runtime.exists():
                    mw.remove_tree_retry(runtime, runtime=True)
            except Exception:  # noqa: BLE001
                pass

    return replay


def text_replay_verdict(rep: Mapping[str, Any], cit: int, ctp: int) -> Dict[str, Any]:
    res = rep.get("result") or {}
    got = [res.get("completion_input_tick"), res.get("completion_time_passed")]
    ok = bool(rep.get("ok")) and res.get("outcome") == "clear" and got == [int(cit), int(ctp)]
    return {"equal": ok, "clocks_text": got, "clocks_verified": [int(cit), int(ctp)], "exit_code": rep.get("exit_code"), "error": rep.get("error"),
            "wall_s": rep.get("wall_s"), "outcome": res.get("outcome")}
