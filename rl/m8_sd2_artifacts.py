"""M8-sd2 artifacts: every sd2 record carries the task block and `created_utc` at the source (standard library only; rl/m9_artifacts.py imported unchanged through rl/m8_sd1_artifacts.py).

The writers are sd1's, re-exported unchanged (the same contract: a stamped JSON object, one stamped header row per JSONL file, `created_utc` = the first write, kept by every
rewrite, never restamped by a copy, a backup or a re-verification). What changes is the audit's exemption list, which names sd2's tree:

    base/                               byte copies of sd1's closing archive files and manifest (sd1 stamped its archive_meta.json; the copy is never restamped)
    derived/open_overlay.jsonl          sd2's open overlay under m8_rd_select_v4 at the new record reference (digest-pinned row file)
    derived/sd1_closing_overlay.jsonl   sd1's closing overlay under m8_rd_select_v4 at sd1's record reference, reproduced (digest-pinned row file)
    the stamped companion derived/open_overlay.json carries both identities

`audit_tree6` walks a whole sd2 tree and names every JSON-like file without a valid stamp. The other exemptions are sd1's (the frozen archive row files, the M4 per-action rows of a saved
route, the frozen rd1 worker's directories under sessions/<id>/).
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import m8_sd1_artifacts as art5
import m9_artifacts as A

ARTIFACTS6_CONTRACT = "m8_sd2_artifacts_v1"
HEADER_KEY = art5.HEADER_KEY
ARCHIVE_DIRS = art5.ARCHIVE_DIRS
ARCHIVE_ROW_FILES = art5.ARCHIVE_ROW_FILES
OVERLAY_ROW_FILES = ("derived/open_overlay.jsonl", "derived/sd1_closing_overlay.jsonl")
WORKER_DIRS = art5.WORKER_DIRS
ArtifactError = A.ArtifactError

# the writers and readers, sd1's unchanged
utc = art5.utc
task_block = art5.task_block
stamp = art5.stamp
check = art5.check
is_stamped = art5.is_stamped
dumps = art5.dumps
write_json5 = art5.write_json5
write_json_gz5 = art5.write_json_gz5
header_row = art5.header_row
is_header = art5.is_header
jsonl_header = art5.jsonl_header
append_jsonl5 = art5.append_jsonl5
write_jsonl_gz5 = art5.write_jsonl_gz5
read_jsonl5 = art5.read_jsonl5
rows_of = art5.rows_of
read_json5 = art5.read_json5
created_utc_of = art5.created_utc_of
_opener = art5._opener


def contract_description() -> Dict[str, Any]:
    return {"contract": ARTIFACTS6_CONTRACT, "base": art5.contract_description(), "task": task_block(),
            "writers": "sd1's writers (m8_sd1_artifacts_v1), unchanged: a stamped JSON object; one stamped header row per JSONL file; created_utc = the first write, kept by every rewrite",
            "archive": "the five archive data files keep the frozen m8_rd_archive_v2 row formats; the archive is stamped once, at the top level of archive_meta.json, with created_utc fixed at sd2's materialisation and carried through every checkpoint",
            "exemptions": {"archive_row_files": list(ARCHIVE_ROW_FILES), "base": "byte copies of sd1's closing archive files and manifest (never restamped)", "overlay_row_files": list(OVERLAY_ROW_FILES),
                           "route_actions": "routes/*/actions.jsonl (M4 rows; metadata.json carries the stamp)", "worker_dirs": list(WORKER_DIRS)}}


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the audit -----------------------------------------------------------------------------------------------------------------------------------------


def exempt_reason(rel: str) -> Optional[str]:
    """Why a JSON-like file under an sd2 root is not required to carry the stamp (None: it must)."""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    if rel in OVERLAY_ROW_FILES:
        return "digest-pinned overlay row file; its stamped companion record derived/open_overlay.json carries the identity"
    if parts[0] == "base":
        return "a byte copy of sd1's closing archive files (the copy is never restamped)"
    if len(parts) >= 2 and parts[-2] in ARCHIVE_DIRS and parts[-1] in ARCHIVE_ROW_FILES:
        return "frozen m8_rd_archive_v2 row format; archive_meta.json carries the stamp"
    if len(parts) >= 3 and parts[0] == "routes" and parts[-1] == "actions.jsonl":
        return "M4 per-action rows; the route's metadata.json carries the stamp"
    if len(parts) >= 3 and parts[0] == "sessions" and parts[2] in WORKER_DIRS:
        return "written by the frozen rd1 worker (raw-reply preservation, process working directories)"
    return None


def audit_tree6(root: Path) -> Dict[str, Any]:
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
    return {"ok": not bad, "files": checked, "headers": headers, "exempt": len(exempt), "exempt_files": exempt, "failures": bad, "contract": ARTIFACTS6_CONTRACT}
