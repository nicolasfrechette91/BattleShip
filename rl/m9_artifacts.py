"""M9-g1 artifacts: the task block and `created_utc` at the source, and the only writers of M9 records (standard library only).

Decision 10 (proposal section 7): every M9 artifact records, at the top level of its JSON object,

    "task": {"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"},
    "created_utc": "2026-10-04T18:32:46Z"

and the writers in this module REFUSE to write an object without both. `task` is the run's single task identity (never inferred from a
path or a stage), registered below (a test pins it to rl/experiment_config.SUPPORTED_TASKS); `created_utc` is the UTC time at which the
artifact was first written (ISO 8601, seconds, `Z`; never a file time, never rewritten by a copy or a re-verification: a re-verification
writes its own record with its own time and a pointer to its source).

Writers: write_json (atomic), write_json_gz, append_jsonl (one stamped object per line), write_episode_artifact (the M4 layout that
rl/run_artifacts.read_artifact validates, plus the two top-level fields). `audit_tree` walks a run tree and names every JSON-like file
that lacks them. Nothing here reads a clock for any purpose other than the stamp.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import m9_contract as C

ARTIFACT_CONTRACT = "m9_artifacts_v1"
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
# the project's task registry (rl/experiment_config.SUPPORTED_TASKS); m9_tests pins this copy to it
REGISTERED_TASKS: Dict[str, Dict[str, str]] = {"ssb64_us_mario_btt_v1": {"character": "mario", "stage": "btt_mario"}}
STAMPED_SUFFIXES = (".json", ".jsonl", ".json.gz", ".jsonl.gz")


class ArtifactError(ValueError):
    """An M9 artifact lacks, or carries an invalid, `task` block or `created_utc` (the writer refuses it)."""


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def task_block() -> Dict[str, str]:
    return dict(C.TASK)


def validate_task(task: Any) -> None:
    if not isinstance(task, Mapping) or set(task) != {"id", "character", "stage"}:
        raise ArtifactError(f"task block must be exactly {{id, character, stage}}, got {task!r}")
    reg = REGISTERED_TASKS.get(str(task["id"]))
    if reg is None:
        raise ArtifactError(f"unregistered task id {task['id']!r}")
    if task["character"] != reg["character"] or task["stage"] != reg["stage"]:
        raise ArtifactError(f"task {task['id']!r} is registered with {reg}, got {dict(task)}")


def check(obj: Any, where: str = "artifact") -> None:
    """Raise ArtifactError unless `obj` is a JSON object carrying a registered top-level `task` and a valid `created_utc`."""
    if not isinstance(obj, Mapping):
        raise ArtifactError(f"{where}: an M9 artifact is a JSON object, got {type(obj).__name__}")
    if "task" not in obj:
        raise ArtifactError(f"{where}: missing top-level `task` (refused)")
    if "created_utc" not in obj:
        raise ArtifactError(f"{where}: missing top-level `created_utc` (refused)")
    validate_task(obj["task"])
    if not isinstance(obj["created_utc"], str) or not UTC_RE.match(obj["created_utc"]):
        raise ArtifactError(f"{where}: `created_utc` must be ISO 8601 UTC with seconds and Z, got {obj['created_utc']!r}")


def stamp(obj: Mapping[str, Any], *, created_utc: Optional[str] = None) -> Dict[str, Any]:
    """`obj` with the two fields first. Fields already present are validated and kept (a record is never re-stamped)."""
    out: Dict[str, Any] = {}
    out["task"] = obj["task"] if "task" in obj else task_block()
    out["created_utc"] = obj["created_utc"] if "created_utc" in obj else (created_utc or utc())
    for k, v in obj.items():
        if k not in ("task", "created_utc"):
            out[k] = v
    check(out, "stamp")
    return out


def _replace_retry(tmp: Path, dst: Path, attempts: int = 24, delay: float = 0.25) -> None:
    last: Optional[OSError] = None
    for _ in range(attempts):
        try:
            os.replace(tmp, dst)
            return
        except OSError as exc:      # Windows: a sharing violation while a reader holds the file
            last = exc
            time.sleep(delay)
    raise last if last else OSError(f"cannot replace {dst}")


def dumps(obj: Any, *, indent: Optional[int] = 1) -> str:
    return json.dumps(obj, indent=indent, default=str, sort_keys=False) + "\n"


def write_json(path: Path, obj: Mapping[str, Any], *, overwrite: bool = True) -> Path:
    """Atomic write of a stamped JSON object. Refuses an object without `task` and `created_utc`; refuses to replace an existing
    file when `overwrite` is false (a registration is written once)."""
    path = Path(path)
    check(obj, str(path))
    if path.exists() and not overwrite:
        raise ArtifactError(f"{path} exists (never overwritten)")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(obj), encoding="utf-8", newline="\n")
    _replace_retry(tmp, path)
    return path


def write_json_gz(path: Path, obj: Mapping[str, Any]) -> Path:
    path = Path(path)
    check(obj, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, default=str, separators=(",", ":"))
    _replace_retry(tmp, path)
    return path


def append_jsonl(path: Path, obj: Mapping[str, Any]) -> None:
    path = Path(path)
    check(obj, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, default=str, separators=(",", ":")) + "\n")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_json_gz(path: Path) -> Dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# -- the M4 episode artifact (rl/run_artifacts layout) plus the two fields ----------------------------------------------------------

M4_SCHEMA = 1
M4_FORMAT = "battleship_btt_episode"
M4_ACTION_CONTRACT = "rlaction_native_v1"


def write_episode_artifact(root: Path, episode_id: str, rows: Sequence[Tuple[int, int, int, int]], meta: Mapping[str, Any],
                           *, status: str, terminal: Mapping[str, Any], labels: Mapping[str, Any],
                           preservation_reason: str, created_utc: Optional[str] = None) -> Path:
    """<root>/<episode_id>/{metadata.json, actions.jsonl} in the M4 form (rl/run_artifacts.read_artifact validates it): one row per
    submitted native action from tick 0 (a prefix word is a submitted action; the canonical words are the replay truth), plus the top-level
    `task` and `created_utc`. `meta` carries M9's own fields (lineage, start, perturbation, digests); `labels.experiment` keeps the block
    the replay browser reads today."""
    directory = Path(root) / episode_id
    if directory.exists():
        raise ArtifactError(f"{directory} exists (never overwritten)")
    stamp_utc = created_utc or utc()
    n = len(rows)
    metadata: Dict[str, Any] = {
        "task": task_block(), "created_utc": stamp_utc,
        "artifact_schema": M4_SCHEMA, "format": M4_FORMAT, "action_contract": M4_ACTION_CONTRACT, "source_action_contract": C.ACTION_CONTRACT,
        "episode_id": episode_id,
        "labels": dict(labels, experiment={"task_id": C.TASK_ID, "gate": C.GATE, "milestone": C.MILESTONE, "scope": C.SCOPE,
                                           "compatibility_view": {"task_id": C.TASK_ID, "character": C.TASK["character"], "stage": C.TASK["stage"]}}),
        "preserved": True, "preservation_reasons": [{"reason": preservation_reason, "note": None, "sequence_index": n}],
        "action_count": n, "actions_with_result": n, "status": status, "finish_note": None, "terminal": dict(terminal),
        "anomaly_events": [], "detectors": [], "initial_observation": None, "final_observation": None,
        "diagnostics": {"created_utc": stamp_utc, "wall_s": None},
        "m9": dict(meta),
    }
    check(metadata, str(directory))
    directory.mkdir(parents=True)
    with open(directory / "actions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for i, (b, x, y, t) in enumerate(rows):
            f.write(json.dumps({"sequence_index": i, "buttons": int(b), "stick_x": int(x), "stick_y": int(y), "consumed_tick": int(t)},
                               separators=(",", ":")) + "\n")
    write_json(directory / "metadata.json", metadata)
    return directory


# -- the audit ----------------------------------------------------------------------------------------------------------------------


def is_stamped_name(name: str) -> bool:
    return name.endswith(STAMPED_SUFFIXES) and not name.endswith(".tmp")


def audit_tree(root: Path, *, skip_dirs: Iterable[str] = ()) -> Dict[str, Any]:
    """Every JSON-like file under `root` (and every line of every .jsonl) must carry the two fields. Returns the files checked and the
    failures; reads files, writes nothing."""
    root = Path(root)
    skip = set(skip_dirs)
    checked = 0
    lines = 0
    bad: List[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or not is_stamped_name(p.name) or p.name == "actions.jsonl":
            continue                                   # an episode artifact's per-action rows (the M4 layout) belong to its stamped metadata.json
        if any(part in skip for part in p.relative_to(root).parts):
            continue
        checked += 1
        try:
            if p.name.endswith(".jsonl") or p.name.endswith(".jsonl.gz"):
                opener = gzip.open if p.name.endswith(".gz") else open
                with opener(p, "rt", encoding="utf-8") as f:           # type: ignore[operator]
                    for ln in f:
                        if ln.strip():
                            lines += 1
                            check(json.loads(ln), f"{p}:{lines}")
            elif p.name.endswith(".json.gz"):
                check(read_json_gz(p), str(p))
            else:
                check(read_json(p), str(p))
        except (ArtifactError, ValueError, OSError) as exc:
            bad.append(f"{p.relative_to(root).as_posix()}: {exc}"[:240])
    return {"files": checked, "jsonl_lines": lines, "failures": bad, "ok": not bad}


def contract_description() -> Dict[str, Any]:
    return {"contract": ARTIFACT_CONTRACT, "task": dict(C.TASK), "created_utc": "ISO 8601 UTC, seconds, Z; first-write time; never a file time",
            "placement": "top level of every JSON object (every .jsonl line included)", "writers_refuse": "an object without both fields",
            "m4_episode_layout": {"schema": M4_SCHEMA, "format": M4_FORMAT, "action_contract": M4_ACTION_CONTRACT}}
