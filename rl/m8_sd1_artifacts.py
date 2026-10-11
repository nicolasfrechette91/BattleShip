"""M8-sd1 artifacts: every sd1 record carries the task block and `created_utc` at the source (standard library only; rl/m9_artifacts.py imported unchanged).

Design: docs/rl_m8_sd1_proposal_2026-10-07.md section 9, as decided on 2026-10-11 (one stamped header row per JSONL file, plus archive_meta.json). Every JSON object sd1 writes
carries, at its top level,

    "task": {"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"},
    "created_utc": "2026-10-11T18:32:46Z"

and the writers here REFUSE an object without both. `created_utc` is the UTC time of the FIRST write of that file (never a file time; a rewrite of state.json or of archive_meta.json keeps
the first value; a copy, a backup or a re-verification never restamps). A JSONL file (plain or gzip) opens with ONE stamped header row `{"task", "created_utc", "schema", "header": true}`;
the rows that follow are unstamped (their format is the engine's). The archive data files keep their frozen `m8_rd_archive_v2` row formats and are stamped once, in archive_meta.json.

`audit_tree5` walks a whole sd1 tree and names every JSON-like file without a valid stamp. The exemptions are explicit (`exempt_reason`): the frozen archive row files (cells.jsonl,
bursts.idx.jsonl, events.jsonl under archive/, archive.prev/, archive.tmp/), `base/` (byte copies of rd4's closing files, which rd4 never stamped), the two digest-pinned overlay row
files under derived/ (their stamped companion record carries the identity), the M4 per-action rows of a saved route (its metadata.json carries the stamp), and the frozen rd1 worker's own
directories under sessions/<id>/ (failures/, workers/, vw/: raw-reply preservation and process working directories written by code that is never edited).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import m8_rd_archive as march
import m9_artifacts as A

ARTIFACTS5_CONTRACT = "m8_sd1_artifacts_v1"
HEADER_KEY = "header"
ARCHIVE_DIRS = ("archive", "archive.prev", "archive.tmp")
ARCHIVE_ROW_FILES = ("cells.jsonl", "bursts.idx.jsonl", "events.jsonl")
OVERLAY_ROW_FILES = ("derived/open_overlay.jsonl", "derived/rd4_closing_overlay.jsonl")
WORKER_DIRS = ("failures", "workers", "vw")
ArtifactError = A.ArtifactError


def utc() -> str:
    return A.utc()


def task_block() -> Dict[str, str]:
    return A.task_block()


def stamp(obj: Mapping[str, Any], *, created_utc: Optional[str] = None) -> Dict[str, Any]:
    """`obj` with `task` and `created_utc` first (kept when already present; `created_utc` is the first write's time)."""
    return A.stamp(obj, created_utc=created_utc)


def check(obj: Any, where: str = "artifact") -> None:
    A.check(obj, where)


def is_stamped(obj: Any) -> bool:
    try:
        A.check(obj)
        return True
    except (ArtifactError, TypeError, ValueError):
        return False


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, default=str) + "\n"


def contract_description() -> Dict[str, Any]:
    return {"contract": ARTIFACTS5_CONTRACT, "base": A.contract_description(), "task": task_block(),
            "created_utc": "ISO 8601 UTC, seconds, Z; the FIRST write of the file; kept by every rewrite (state.json, archive_meta.json across checkpoints); never a file time; never restamped by a copy, a backup or a re-verification",
            "json_objects": "every .json / .json.gz object sd1 writes carries both fields at its top level (verification traces included)",
            "jsonl_files": f"every .jsonl / .jsonl.gz file sd1 writes opens with one stamped header row {{task, created_utc, schema, {HEADER_KEY}: true}}; the rows keep the engine's format",
            "archive": "the five archive data files keep the frozen m8_rd_archive_v2 row formats; the archive is stamped once, at the top level of archive_meta.json, with created_utc fixed at the first materialisation and carried through every checkpoint",
            "exemptions": {"archive_row_files": list(ARCHIVE_ROW_FILES), "base": "byte copies of rd4's closing files", "overlay_row_files": list(OVERLAY_ROW_FILES),
                           "route_actions": "routes/*/actions.jsonl (M4 rows; metadata.json carries the stamp)", "worker_dirs": list(WORKER_DIRS)}}


def contract_digest() -> str:
    import hashlib

    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- writers ---------------------------------------------------------------------------------------------------------------------------------------


def _existing_created_utc(path: Path) -> Optional[str]:
    try:
        prev = json.loads(path.read_text(encoding="utf-8-sig")).get("created_utc")
    except (OSError, ValueError, AttributeError):
        return None
    return prev if isinstance(prev, str) and A.UTC_RE.match(prev) else None


def write_json5(path: Path, obj: Mapping[str, Any], *, overwrite: bool = True, created_utc: Optional[str] = None) -> Path:
    """Atomic write of a stamped JSON object (indent 1, as the rd line's records). A rewrite keeps the file's first `created_utc`; `overwrite=False` refuses an existing file."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise ArtifactError(f"{path} exists (never overwritten)")
    prev = _existing_created_utc(path) if path.exists() else None
    rec = stamp(obj, created_utc=prev or created_utc)
    check(rec, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(rec), encoding="utf-8", newline="\n")
    march.replace_retry(tmp, path)
    return path


def write_json_gz5(path: Path, obj: Mapping[str, Any], *, created_utc: Optional[str] = None) -> Path:
    path = Path(path)
    rec = stamp(obj, created_utc=created_utc)
    check(rec, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, separators=(",", ":"), default=str)
    march.replace_retry(tmp, path)
    return path


def header_row(schema: str, *, created_utc: Optional[str] = None) -> Dict[str, Any]:
    row = stamp({"schema": str(schema), HEADER_KEY: True}, created_utc=created_utc)
    check(row, "header")
    return row


def is_header(row: Any) -> bool:
    return isinstance(row, Mapping) and row.get(HEADER_KEY) is True and isinstance(row.get("schema"), str) and is_stamped(row)


def _opener(path: Path) -> Any:
    return gzip.open if path.name.endswith(".gz") else open


def jsonl_header(path: Path, schema: str, *, created_utc: Optional[str] = None) -> bool:
    """Create `path` with its stamped header row when it does not exist yet (or is empty). Returns True when the header was written now."""
    path = Path(path)
    if path.exists() and path.stat().st_size > 0:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with _opener(path)(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(header_row(schema, created_utc=created_utc), default=str, separators=(",", ":")) + "\n")
    return True


def append_jsonl5(path: Path, row: Mapping[str, Any], schema: str) -> None:
    """One engine-format row appended after the (ensured) header."""
    path = Path(path)
    jsonl_header(path, schema)
    with _opener(path)(path, "at", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")


def write_jsonl_gz5(path: Path, rows: Iterable[Mapping[str, Any]], schema: str, *, created_utc: Optional[str] = None) -> Path:
    """A whole JSONL (gzip when the name ends in .gz) file: the stamped header row, then the rows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with _opener(path)(tmp, "wt", encoding="utf-8", newline="\n") as f:        # the opener follows the FINAL name (gzip for .gz), not the temporary one
        f.write(json.dumps(header_row(schema, created_utc=created_utc), default=str, separators=(",", ":")) + "\n")
        for r in rows:
            f.write(json.dumps(r, default=str, separators=(",", ":")) + "\n")
    march.replace_retry(tmp, path)
    return path


def read_jsonl5(path: Path) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """(the header row or None, the rows after it)."""
    path = Path(path)
    if not path.is_file():
        return None, []
    with _opener(path)(path, "rt", encoding="utf-8") as f:
        lines = [json.loads(ln) for ln in f if ln.strip()]
    if lines and is_header(lines[0]):
        return lines[0], lines[1:]
    return None, lines


def rows_of(path: Path) -> List[Dict[str, Any]]:
    return read_jsonl5(path)[1]


def read_json5(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# -- the audit -----------------------------------------------------------------------------------------------------------------------------------------


def exempt_reason(rel: str) -> Optional[str]:
    """Why a JSON-like file under an sd1 root is not required to carry the stamp (None: it must)."""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    if rel in OVERLAY_ROW_FILES:
        return "digest-pinned overlay row file; its stamped companion record derived/open_overlay.json carries the identity"
    if parts[0] == "base":
        return "a byte copy of rd4's closing archive files (rd4 never stamped; the copy is never restamped)"
    if len(parts) >= 2 and parts[-2] in ARCHIVE_DIRS and parts[-1] in ARCHIVE_ROW_FILES:
        return "frozen m8_rd_archive_v2 row format; archive_meta.json carries the stamp"
    if len(parts) >= 3 and parts[0] == "routes" and parts[-1] == "actions.jsonl":
        return "M4 per-action rows; the route's metadata.json carries the stamp"
    if len(parts) >= 3 and parts[0] == "sessions" and parts[2] in WORKER_DIRS:
        return "written by the frozen rd1 worker (raw-reply preservation, process working directories)"
    return None


def audit_tree5(root: Path) -> Dict[str, Any]:
    """Every JSON-like file under `root` must carry the stamp (objects at their top level; JSONL files in their header row) unless exempt. Reads only."""
    root = Path(root)
    checked = 0
    exempt: List[str] = []
    bad: List[str] = []
    headers = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or not A.is_stamped_name(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        why = exempt_reason(rel)
        if why is not None:
            exempt.append(rel)
            continue
        checked += 1
        try:
            if p.name.endswith(".jsonl") or p.name.endswith(".jsonl.gz"):
                with _opener(p)(p, "rt", encoding="utf-8") as f:
                    first = None
                    for ln in f:
                        if ln.strip():
                            first = json.loads(ln)
                            break
                if first is None:
                    bad.append(f"{rel}: empty (no header row)")
                elif not is_header(first):
                    bad.append(f"{rel}: the first row is not a stamped header")
                else:
                    headers += 1
            elif p.name.endswith(".json.gz"):
                with gzip.open(p, "rt", encoding="utf-8") as f:
                    check(json.load(f), rel)
            else:
                check(read_json5(p), rel)
        except (ArtifactError, ValueError, OSError) as exc:
            bad.append(f"{rel}: {exc}"[:240])
    return {"ok": not bad, "files": checked, "headers": headers, "exempt": len(exempt), "exempt_files": exempt, "failures": bad, "contract": ARTIFACTS5_CONTRACT}


def created_utc_of(path: Path) -> Optional[str]:
    """The `created_utc` a stamped JSON file (or a JSONL header) carries, or None."""
    path = Path(path)
    if path.name.endswith(".jsonl") or path.name.endswith(".jsonl.gz"):
        h, _rows = read_jsonl5(path)
        return None if h is None else h.get("created_utc")
    if path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f).get("created_utc")
    return read_json5(path).get("created_utc")
