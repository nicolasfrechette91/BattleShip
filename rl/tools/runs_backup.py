#!/usr/bin/env python3
"""Independent, verified backup of the Git-ignored `runs/` evidence (M7r prerequisite, design rev 3 section 7).

    python rl/tools/runs_backup.py backup --dest D:\\BattleShip_runs_backup\\2026-09-28
    python rl/tools/runs_backup.py verify --dest D:\\BattleShip_runs_backup\\2026-09-28
    python rl/tools/runs_backup.py check-coverage --dest D:\\BattleShip_runs_backup\\2026-09-28

`backup` copies every regular file under the source (`runs/` by default) to `<dest>/runs/`, hashing the bytes it reads,
and writes `<dest>/manifest.tsv.gz` (sha256, size, mtime_ns, POSIX relative path per file) and `<dest>/junctions.tsv.gz`
(every reparse point that was NOT followed or copied: junctions, symbolic links). It is incremental: a file already in
the backup with the same size and a hash equal to the source's is not rewritten. It then runs `verify`.

`verify` never trusts the copy step: it walks the source again (the inventory must equal the manifest: same paths,
sizes, mtimes), re-hashes every source file by reading the source, hashes every backup file by reading the backup,
walks the backup (no extra or missing file), and writes `<dest>/verification.json` with result PASS or FAIL.

`check-coverage` (used by the M7r gate driver before any launch): PASS record present, the record's manifest hash
equals the manifest on disk, and every regular file under the source now appears in the manifest with the same size
and mtime (nothing new, nothing changed since the backup).

The source is only read. Nothing is deleted anywhere. Python standard library only.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import hashlib
import json
import os
import platform
import stat
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

TOOL = "btt_runs_backup_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "runs"
MANIFEST = "manifest.tsv.gz"
JUNCTIONS = "junctions.tsv.gz"
RECORD = "verification.json"
CHUNK = 4 * 1024 * 1024
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def long_path(p: Path) -> str:
    """Extended-length form on Windows so paths beyond 260 characters work without the registry switch."""
    s = str(Path(p).resolve())
    if platform.system() == "Windows" and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + s
    return s


def is_reparse(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
            return True
        st = entry.stat(follow_symlinks=False)
        return bool(getattr(st, "st_file_attributes", 0) & REPARSE)
    except OSError:
        return True


def walk(root: Path) -> Tuple[Dict[str, Tuple[int, int]], List[Tuple[str, str]], List[str]]:
    """{posix relpath: (size, mtime_ns)} of every regular file, the reparse points skipped, and unreadable entries."""
    files: Dict[str, Tuple[int, int]] = {}
    skipped: List[Tuple[str, str]] = []
    errors: List[str] = []
    base = long_path(root)
    stack = [("", base)]
    while stack:
        rel, path = stack.pop()
        try:
            it = os.scandir(path)
        except OSError as exc:
            errors.append(f"{rel or '.'}: {exc}")
            continue
        with it:
            for e in it:
                r = f"{rel}/{e.name}" if rel else e.name
                if is_reparse(e):
                    try:
                        target = os.readlink(e.path)
                    except OSError:
                        target = ""
                    skipped.append((r, target))
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append((r, e.path))
                    elif e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        files[r] = (st.st_size, st.st_mtime_ns)
                    else:
                        skipped.append((r, "not a regular file"))
                except OSError as exc:
                    errors.append(f"{r}: {exc}")
    return files, sorted(skipped), errors


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            b = fp.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def native(root: Path, rel: str) -> str:
    return long_path(root) + "\\" + rel.replace("/", "\\") if platform.system() == "Windows" else str(root / rel)


def copy_one(src_root: Path, dst_root: Path, rel: str, size: int, mtime_ns: int) -> Tuple[str, str, int, bool]:
    """Copy one file, hashing the bytes read; returns (rel, sha256, bytes, copied). An existing backup file of the same
    size whose hash equals the source's is kept (incremental)."""
    src, dst = native(src_root, rel), native(dst_root, rel)
    if os.path.isfile(dst) and os.path.getsize(dst) == size:
        s = sha256_of(src)
        if sha256_of(dst) == s:
            return rel, s, size, False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    h = hashlib.sha256()
    n = 0
    # Plain buffered writes (a per-file fsync made small files ~50/s on the HDD). Integrity is not assumed: `verify`
    # re-reads every backup file afterwards, and an interrupted copy leaves a short file that verify reports.
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            h.update(b)
            fo.write(b)
            n += len(b)
    os.utime(dst, ns=(mtime_ns, mtime_ns))
    return rel, h.hexdigest(), n, True


class Progress:
    def __init__(self, total: int, label: str, every: float = 30.0):
        self.total, self.label, self.every = total, label, every
        self.done = 0
        self.t0 = self.last = time.time()
        self.lock = threading.Lock()

    def tick(self) -> None:
        with self.lock:
            self.done += 1
            now = time.time()
            if now - self.last >= self.every or self.done == self.total:
                self.last = now
                print(f"[{utc()}] {self.label}: {self.done}/{self.total} ({now - self.t0:.0f} s)", flush=True)


def write_tsv_gz(path: Path, rows: Sequence[Sequence[object]]) -> str:
    data = "".join("\t".join(str(c) for c in r) + "\n" for r in rows).encode("utf-8")
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(dest: Path) -> Dict[str, Tuple[str, int, int]]:
    out: Dict[str, Tuple[str, int, int]] = {}
    with gzip.open(dest / MANIFEST, "rt", encoding="utf-8") as fp:
        for line in fp:
            sha, size, mt, rel = line.rstrip("\n").split("\t", 3)
            out[rel] = (sha, int(size), int(mt))
    return out


def game_running() -> bool:
    if platform.system() != "Windows":
        return False
    import subprocess

    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq BattleShip.exe", "/NH"], capture_output=True, text=True)
    return "BattleShip.exe" in out.stdout


def cmd_backup(source: Path, dest: Path, workers: int) -> int:
    if game_running():
        print("refused: BattleShip.exe is running (runs/ may be changing)", file=sys.stderr)
        return 2
    t0 = time.time()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "runs").mkdir(exist_ok=True)
    files, skipped, errors = walk(source)
    if errors:
        print(f"refused: {len(errors)} unreadable entries in the source, e.g. {errors[:3]}", file=sys.stderr)
        return 2
    # Leftovers of an interrupted earlier version of this tool (write-to-temp-then-rename): only in the backup tree,
    # only this tool's own suffix, never a name that exists in the source.
    stale = [r for r in walk(dest / "runs")[0] if r.endswith(".bak_tmp") and r not in files]
    for r in stale:
        os.remove(native(dest / "runs", r))
    if stale:
        print(f"[{utc()}] removed {len(stale)} temporary files left in the backup by an interrupted copy", flush=True)
    total_bytes = sum(s for s, _ in files.values())
    print(f"[{utc()}] source {source}: {len(files)} regular files, {total_bytes} bytes, {len(skipped)} reparse points "
          f"skipped", flush=True)
    rows: List[Tuple[str, int, int, str]] = []
    copied = kept = 0
    prog = Progress(len(files), "copy")
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(copy_one, source, dest / "runs", rel, s, m) for rel, (s, m) in files.items()]
        for f in cf.as_completed(futs):
            rel, sha, n, did = f.result()
            size, mt = files[rel]
            if n != size:
                print(f"size changed while copying: {rel} ({size} -> {n})", file=sys.stderr)
                return 3
            rows.append((sha, size, mt, rel))
            copied += did
            kept += not did
            prog.tick()
    rows.sort(key=lambda r: r[3])
    manifest_sha = write_tsv_gz(dest / MANIFEST, rows)
    write_tsv_gz(dest / JUNCTIONS, skipped)
    info = {"tool": TOOL, "source": str(source), "dest": str(dest), "created_utc": utc(), "files": len(rows),
            "bytes": total_bytes, "reparse_points_skipped": len(skipped), "copied": copied, "kept_identical": kept,
            "manifest_sha256": manifest_sha, "copy_wall_s": round(time.time() - t0, 1)}
    (dest / "backup_run.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    print(f"[{utc()}] copy done: {json.dumps(info)}", flush=True)
    return cmd_verify(source, dest, workers)


def cmd_verify(source: Path, dest: Path, workers: int) -> int:
    t0 = time.time()
    problems: List[str] = []
    manifest = read_manifest(dest)
    manifest_sha = hashlib.sha256((dest / MANIFEST).read_bytes()).hexdigest()
    src_files, src_skipped, src_errors = walk(source)
    problems += [f"source unreadable: {e}" for e in src_errors[:50]]
    missing_src = sorted(set(manifest) - set(src_files))
    new_src = sorted(set(src_files) - set(manifest))
    changed = sorted(r for r in set(manifest) & set(src_files)
                     if (manifest[r][1], manifest[r][2]) != src_files[r])
    problems += [f"in manifest, not in source: {r}" for r in missing_src[:50]]
    problems += [f"in source, not in manifest: {r}" for r in new_src[:50]]
    problems += [f"size/mtime changed in source: {r}" for r in changed[:50]]
    bak_files, bak_skipped, bak_errors = walk(dest / "runs")
    problems += [f"backup unreadable: {e}" for e in bak_errors[:50]]
    problems += [f"reparse point inside the backup: {r}" for r, _ in bak_skipped[:50]]
    extra = sorted(set(bak_files) - set(manifest))
    absent = sorted(set(manifest) - set(bak_files))
    problems += [f"extra file in backup: {r}" for r in extra[:50]]
    problems += [f"missing from backup: {r}" for r in absent[:50]]
    size_bad = sorted(r for r in set(manifest) & set(bak_files) if bak_files[r][0] != manifest[r][1])
    problems += [f"backup size differs: {r}" for r in size_bad[:50]]

    def both(rel: str) -> Tuple[str, Optional[str], Optional[str]]:
        s = b = None
        try:
            s = sha256_of(native(source, rel))
        except OSError:
            pass
        try:
            b = sha256_of(native(dest / "runs", rel))
        except OSError:
            pass
        return rel, s, b

    hash_bad: List[str] = []
    prog = Progress(len(manifest), "verify")
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for rel, s, b in ex.map(both, sorted(manifest)):
            m = manifest[rel][0]
            if not (s == b == m):
                hash_bad.append(f"{rel}: manifest {m[:12]} source {str(s)[:12]} backup {str(b)[:12]}")
            prog.tick()
    problems += hash_bad[:100]
    total_bytes = sum(v[1] for v in manifest.values())
    bak_bytes = sum(v[0] for v in bak_files.values())
    record = {
        "tool": TOOL,
        "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "result": "PASS" if not problems and not hash_bad else "FAIL",
        "verified_utc": utc(),
        "host": platform.node(),
        "source": str(source.resolve()),
        "backup_root": str(dest.resolve()),
        "backup_files_dir": str((dest / "runs").resolve()),
        "manifest": MANIFEST,
        "manifest_sha256": manifest_sha,
        "files": len(manifest),
        "bytes": total_bytes,
        "backup_files": len(bak_files),
        "backup_bytes": bak_bytes,
        "source_files_now": len(src_files),
        "reparse_points_skipped_in_source": len(src_skipped),
        "checks": {
            "source_inventory_equals_manifest": not (missing_src or new_src or changed),
            "backup_inventory_equals_manifest": not (extra or absent or size_bad),
            "every_hash_equal_manifest_source_backup": not hash_bad,
            "no_reparse_point_in_backup": not bak_skipped,
            "no_unreadable_entries": not (src_errors or bak_errors),
        },
        "hash_mismatches": len(hash_bad),
        "problems": problems[:200],
        "verify_wall_s": round(time.time() - t0, 1),
        "hashes_read_from": "source files re-read from the source volume; backup files read from the backup volume",
        "scope_note": "regular files only; junctions / symbolic links / other reparse points are listed in "
                      f"{JUNCTIONS}, never followed or copied",
        "protection_note": "a copy on another physical disk of the same machine: protects against the loss of the "
                           "source disk, not against the loss of the whole machine",
    }
    tmp = dest / (RECORD + ".tmp")
    tmp.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, dest / RECORD)
    print(f"[{utc()}] verification {record['result']}: files {record['files']} bytes {record['bytes']} "
          f"hash mismatches {len(hash_bad)} problems {len(problems)} ({record['verify_wall_s']} s)", flush=True)
    return 0 if record["result"] == "PASS" else 1


def coverage(source: Path, dest: Path) -> Dict[str, object]:
    """The launch check: PASS record, manifest unchanged since verification, current source covered."""
    out: Dict[str, object] = {"dest": str(dest), "ok": False}
    rec_path = dest / RECORD
    if not rec_path.is_file():
        out["reason"] = f"no {RECORD} at {dest}"
        return out
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    out["record"] = {k: rec.get(k) for k in ("result", "verified_utc", "files", "bytes", "manifest_sha256")}
    if rec.get("result") != "PASS":
        out["reason"] = f"verification result {rec.get('result')!r}"
        return out
    if hashlib.sha256((dest / MANIFEST).read_bytes()).hexdigest() != rec.get("manifest_sha256"):
        out["reason"] = "the manifest on disk differs from the verified one"
        return out
    manifest = read_manifest(dest)
    files, _skipped, errors = walk(source)
    uncovered = sorted(r for r, sm in files.items() if r not in manifest or (manifest[r][1], manifest[r][2]) != sm)
    out["source_files"] = len(files)
    out["uncovered"] = len(uncovered)
    out["uncovered_examples"] = uncovered[:20]
    if errors:
        out["reason"] = f"{len(errors)} unreadable source entries"
        return out
    if uncovered:
        out["reason"] = f"{len(uncovered)} source files are new or changed since the verified backup"
        return out
    out["ok"] = True
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("backup", "verify", "check-coverage"))
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    src = a.source.resolve()
    if a.dest.resolve().drive.lower() == src.drive.lower():
        print("refused: the backup must be on another volume than the source", file=sys.stderr)
        return 2
    if a.command == "backup":
        return cmd_backup(src, a.dest, a.workers)
    if a.command == "verify":
        return cmd_verify(src, a.dest, a.workers)
    cov = coverage(src, a.dest)
    print(json.dumps(cov, indent=1))
    return 0 if cov["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
