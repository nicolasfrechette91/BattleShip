#!/usr/bin/env python3
"""Run 3 code manifest (2026-11-05 session; SESSION_LOG_2026-11-04.md section 15; owner's choice: a separate manifest, not an extension
of the lab manifest).

    what        {repo-relative path: sha256} of EVERY repository file that run 3's entry modules import (tools/frs, tools/glitch and rl/
                alike), determined in a FRESH interpreter, so the set does not depend on what the caller imported. The entries:
                  - the engine (run3_search), the worker module (run3_worker, the spawned processes' entry point) and the run 3
                    command-line module (crossing_search_run3, step 8: it imports run3_select, run3_load and run3_export);
                  - the modules run 3 imports INSIDE functions, which an import-time closure cannot see: the lab runner's explicit list
                    (rl/frs_run.CODE_MODULES: the launcher, client, standby, runtime, trace and crossing modules) plus
                    m7q_status_table (m8_rd_cells.Classifier, every worker), m7g_spatial (m8_rd_select2.y_floor_min) and m7f_targets
                    (m7g_fixture.crossing_evidence, called by m7n_crossing.analyse_trace on every verification).
                Function-level imports NOT followed (LAZY_EXCLUDED, each with the function that holds it): m8_rd_session's rd-session gates
                and reports, and four fixture / study helpers run 3 never calls (following everything would add 87 training and gate
                files). tools/frs/run3_search_tests.py fails
                when a file of the manifest gains a function-level import of a repository module that is neither covered nor excluded.
    digest      sha256 of the manifest as compact sorted JSON (the same canonical form as rl/frs_run.code_digest).
    refusal     the plan records the digest (P["run3_code_digest"]); tools/frs/run3_search.Run3Core.open recomputes it and refuses, before
                anything is launched, when it differs or is missing. At the close it is recomputed again: a change during the run is
                SEARCH_INVALID. config.json records the manifest; the lab manifest (rl/frs_run.code_manifest) is still recorded as before.
    not here    no audit of the files a process actually loads at run time (owner, 2026-11-05: not now); the executable
                and its runtime files are pinned by the lab import (frozen_runtime.json), not by this manifest.

Zero native ticks. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MANIFEST_CONTRACT = "run3_code_manifest_v1"
RUN3_MODULES = ("run3_search", "run3_worker", "crossing_search_run3")
LAB_RUNTIME_MODULES = ("frs_guard", "frs_machine", "frs_archive", "frs_worker", "frs_verify", "frs_report", "frs_run", "frs_lab", "m7f_trace",
                       "m7n_crossing", "battleship_process", "battleship_client", "m7_standby", "m7_runtime")   # = rl/frs_run.CODE_MODULES
LAZY_MODULES = ("m7q_status_table", "m7g_spatial", "m7f_targets")
ENTRY_MODULES = RUN3_MODULES + LAB_RUNTIME_MODULES + LAZY_MODULES
LAZY_EXCLUDED = {"m7u_gate": "m8_rd_session: rd-session gate m7u (never run by run 3)",
                 "m7u2_gate": "m8_rd_session: rd-session gate m7u2 (never run by run 3)",
                 "m7u3_gate": "m8_rd_session: rd-session gate m7u3 (never run by run 3)",
                 "m8_rd_finish": "m8_rd_session: rd-session finish step (never run by run 3)",
                 "m8_rd_report": "m8_rd_session: rd-session report (never run by run 3)",
                 "btti_replay": "m7f_trace.tas_actions and m7g_fixture.load_sequence (text replays, fixture loading; run 3 replays words)",
                 "m7f_validate": "m7g_fixture.returns_v1_v2 (fixture validation, not called by m7n_crossing.analyse_trace)",
                 "experiment_config": "m7n_crossing.summarise (a report of the M7n study, not called by run 3)",
                 "m7k_target2": "m7n_crossing.replay_candidate (an M7n replay, not called by run 3)",
                 "m8_rd_stub": "crossing_search_run3._plan_child (the stub world's analyse, only when a test passes analyse='stub')"}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run3_code_manifest(repo: Path = REPO, entries: Sequence[str] = ENTRY_MODULES) -> Dict[str, str]:
    """{repo-relative posix path: sha256} of every repository file the entry modules import, in a fresh interpreter."""
    repo = Path(repo).resolve()
    frs = repo / "tools" / "frs"
    code = ("import json, sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import importlib; [importlib.import_module(m) for m in %r]; "
            "print(json.dumps(sorted({m.__file__ for m in list(sys.modules.values()) if getattr(m, '__file__', None)})))"
            % (str(repo / "rl"), str(frs), list(entries)))
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, cwd=str(frs), timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"the run 3 code manifest could not be computed: {r.stderr[-800:]}")
    root = os.path.normcase(str(repo))
    out: Dict[str, str] = {}
    for f in json.loads(r.stdout.strip().splitlines()[-1]):
        p = Path(f).resolve()
        if os.path.normcase(str(p)).startswith(root + os.sep):
            out[p.relative_to(repo).as_posix()] = sha256_file(p)
    return dict(sorted(out.items()))


def code_digest(manifest: Mapping[str, str]) -> str:
    return hashlib.sha256(json.dumps(dict(sorted(manifest.items())), separators=(",", ":")).encode("utf-8")).hexdigest()


def changed_files(manifest: Mapping[str, str], repo: Path = REPO) -> list:
    """The manifest's files whose content differs now (or that are gone)."""
    out = []
    for rel, h in manifest.items():
        p = Path(repo) / rel
        if not p.is_file() or sha256_file(p) != h:
            out.append(rel)
    return out


def lazy_imports(manifest: Mapping[str, str], repo: Path = REPO) -> Dict[str, list]:
    """{module: [files]} of every repository module a manifest file imports inside a function (static, no import executed)."""
    import ast

    dirs = [Path(repo) / d for d in ("rl", "tools/frs", "tools/glitch")]
    known = {p.stem for d in dirs for p in d.glob("*.py")}
    out: Dict[str, list] = {}
    for rel in manifest:
        tree = ast.parse((Path(repo) / rel).read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else []
                for n in names:
                    if n in known:
                        out.setdefault(n, [])
                        if rel not in out[n]:
                            out[n].append(rel)
    return dict(sorted(out.items()))


if __name__ == "__main__":
    m = run3_code_manifest()
    print(json.dumps({"contract": MANIFEST_CONTRACT, "entries": list(ENTRY_MODULES), "files": len(m), "digest": code_digest(m), "manifest": m}, indent=1))
