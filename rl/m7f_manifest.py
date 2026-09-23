"""M7f Phase F: reproducible replay-selection manifest for the target-identity diagnosis.

Reads the historical M7d/M7e evidence read-only (evaluation rows under runs/<m>/_eval and preserved training artifacts
under runs/<m>/<run>/metrics/episodes.jsonl), groups every replayable row by its native action digest (identical
canonical action sequences are replayed once and weighted by their row count), and applies explicit inclusion rules
(strata). Selection is deterministic: fixed populations are taken whole; the one sampled stratum orders candidates by
sha256(SAMPLE_SALT + digest), which depends on nothing but the digests (no RNG state anywhere).

Walks prune NTFS junctions (the worker runtime .tcc links); nothing is ever written below runs/m7d or runs/m7e.

Usage:
    python rl/m7f_manifest.py --out docs/rl_target_ceiling_m7f_manifest.json
    python rl/m7f_manifest.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
RUNS = REPO_ROOT / "runs"
MILESTONES = ("m7d", "m7e")
SAMPLE_SALT = "m7f-selection-bias-v1"
SAMPLE_SIZE = 200
# Measured on this machine (M7d/M7e replays, M7f equivalence traces): cold boot to fresh ~2.1-2.9 s, stepping
# ~0.6 ms/step with both M6 flags; N=5 workers with one pre-booted process each.
COST_BOOT_S = 2.9
COST_STEP_S = 0.0006
WORKERS = 5

_SET_RE = re.compile(r"^curve_t(\d+)$")


def _walk(root: Path, filename: str) -> List[Path]:
    """os.walk with junction/symlink pruning (Path.rglob enters junctions on Windows)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not os.path.isjunction(os.path.join(dirpath, d))
                             and not os.path.islink(os.path.join(dirpath, d)))
        if filename in filenames:
            out.append(Path(dirpath) / filename)
    return sorted(out)


def _rel(p: Path) -> str:
    return Path(p).resolve().relative_to(REPO_ROOT).as_posix()


def _run_facts(run: str) -> Dict[str, Any]:
    m = re.match(r"^(m7[de])_s(\d)_(v[12])$", run)
    if not m:
        return {"seed": None, "reward_contract": None}
    return {"seed": int(m.group(2)), "reward_contract": f"btt_reward_{m.group(3)}"}


def _set_facts(set_label: str) -> Dict[str, Any]:
    if set_label == "initial":
        return {"set_kind": "initial", "checkpoint_transitions": 0}
    if set_label == "final":
        return {"set_kind": "final", "checkpoint_transitions": None}
    m = _SET_RE.match(set_label)
    if m:
        return {"set_kind": "curve", "checkpoint_transitions": int(m.group(1))}
    return {"set_kind": set_label, "checkpoint_transitions": None}


def load_rows() -> List[Dict[str, Any]]:
    """Every historical episode row (evaluation + training) of M7d and M7e, with its provenance."""
    rows: List[Dict[str, Any]] = []
    for m in MILESTONES:
        for ev in _walk(RUNS / m / "_eval", "evaluation.json"):
            parts = ev.relative_to(RUNS / m / "_eval").parts  # <run>/<set>/<mode>/evaluation.json
            run, set_label, mode = parts[0], parts[1], parts[2]
            data = json.loads(ev.read_text(encoding="utf-8"))
            for r in data.get("episodes") or []:
                rows.append({
                    "milestone": m, "source": "evaluation", "run": run, "set": set_label, "mode": mode,
                    **_run_facts(run), **_set_facts(set_label),
                    "episode_id": r.get("episode_id"), "digest": r.get("native_action_digest"),
                    "artifact_dir": r.get("artifact_dir"), "targets": r.get("targets_broken"),
                    "length": r.get("length"), "end_reason": r.get("end_reason"),
                    "break_ticks": r.get("target_break_ticks"), "last_consumed_tick": r.get("last_consumed_tick"),
                    "raw_return": r.get("raw_return"), "startup_mode": r.get("startup_mode"),
                    "row_file": _rel(ev),
                })
        for run_dir in sorted(p for p in (RUNS / m).iterdir() if p.is_dir() and not p.name.startswith("_")):
            ep = run_dir / "metrics" / "episodes.jsonl"
            if not ep.is_file():
                continue
            for line in ep.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                rows.append({
                    "milestone": m, "source": "training", "run": run_dir.name, "set": "training", "mode": "training",
                    **_run_facts(run_dir.name), "set_kind": "training",
                    "checkpoint_transitions": r.get("sb3_num_timesteps_at_end"),
                    "checkpoint_label": r.get("checkpoint_label"),
                    "episode_id": r.get("episode_id"), "digest": r.get("native_action_digest"),
                    "artifact_dir": r.get("artifact_dir"), "targets": r.get("targets_broken"),
                    "length": r.get("steps"), "end_reason": r.get("end_reason"),
                    "break_ticks": r.get("target_break_ticks"), "last_consumed_tick": r.get("last_consumed_tick"),
                    "raw_return": r.get("return"), "startup_mode": r.get("startup_mode"), "row_file": _rel(ep),
                })
    for r in rows:
        r["replayable"] = bool(r["artifact_dir"]) and (REPO_ROOT / r["artifact_dir"] / "actions.jsonl").is_file()
    return rows


def group_by_digest(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Unique canonical action sequences. The replay source is the lexicographically first artifact among rows with
    that digest; every duplicate group must agree on its outcome (checked, reported)."""
    groups: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = r["digest"]
        if not d:
            continue
        g = groups.setdefault(d, {"digest": d, "rows": [], "artifacts": set()})
        g["rows"].append(r)
        if r["replayable"]:
            g["artifacts"].add(r["artifact_dir"])
    for g in groups.values():
        outcomes = {(r["targets"], r["length"], tuple(r["break_ticks"] or ()), r["end_reason"]) for r in g["rows"]}
        g["consistent"] = len(outcomes) == 1
        g["artifact_dir"] = sorted(g["artifacts"])[0] if g["artifacts"] else None
        g["replayable"] = g["artifact_dir"] is not None
        r0 = g["rows"][0]
        g["expected"] = {"targets": r0["targets"], "length": r0["length"], "end_reason": r0["end_reason"],
                         "break_ticks": r0["break_ticks"], "last_consumed_tick": r0["last_consumed_tick"]}
    return groups


def _key(r: Mapping[str, Any]) -> str:
    return f"{r['milestone']}/{r['run']}/{r['set']}/{r['mode']}"


STRATA: Tuple[Tuple[str, str, str, str], ...] = (
    ("m7e_final_stochastic", "all M7e final stochastic evaluation rows (3 seeds x 100)",
     "per-seed break/miss frequencies of the final policies; the census for the M7e ceiling claims",
     "nothing about checkpoints other than final"),
    ("m7e_final_deterministic", "every unique M7e final deterministic sequence (one per seed, weight 100)",
     "which targets the argmax policy of each seed takes", "anything about stochastic behaviour"),
    ("m7e_checkpoint_curve", "all M7e initial and curve stochastic rows (100 + 9 x 60 per seed) and every unique "
                             "initial/curve deterministic sequence",
     "whether later checkpoints acquire targets earlier ones never break (checkpoint trajectory per seed)",
     "fine-grained per-checkpoint rates (60 episodes per point, SE ~ 0.06 on a rate)"),
    ("m7d_final", "all M7d final stochastic rows (6 runs x 100) and every unique M7d final deterministic sequence",
     "M7d vs M7e and reward v1 vs v2 differences at the end of training, incl. seed 0 where v1 beat v2",
     "M7d checkpoint trajectories"),
    ("six_target_all", "every replayable six-target row anywhere (evaluation + preserved training)",
     "which six-target subsets exist and which targets a six-target episode never contains",
     "how common each six-target subset is in training (37 of 47 training six-target rows have no actions)"),
    ("random_baseline", "the random-baseline rows that kept actions (3 per milestone, identical across milestones)",
     "which targets random play reaches in the preserved episodes", "random-play frequencies (3 of 100 kept)"),
    ("selection_bias_sample", f"{SAMPLE_SIZE} unique replayable sequences not selected above, ordered by "
                              f"sha256('{SAMPLE_SALT}' + digest)",
     "whether per-target frequencies in the targeted strata generalise to the rest of the replayable evidence",
     "the non-replayable rows (4,491 training rows, 97+97 random rows without actions)"),
)


def select(rows: Sequence[Mapping[str, Any]], groups: Mapping[str, Mapping[str, Any]]) -> Dict[str, List[str]]:
    """Stratum -> sorted list of selected digests (replayable only)."""
    def digests(pred) -> List[str]:
        return sorted({r["digest"] for r in rows if pred(r) and groups[r["digest"]]["replayable"]})

    sel: Dict[str, List[str]] = {}
    sel["m7e_final_stochastic"] = digests(lambda r: r["milestone"] == "m7e" and r["source"] == "evaluation"
                                          and r["set"] == "final" and r["mode"] == "stochastic")
    sel["m7e_final_deterministic"] = digests(lambda r: r["milestone"] == "m7e" and r["set"] == "final"
                                             and r["mode"] == "deterministic")
    sel["m7e_checkpoint_curve"] = digests(lambda r: r["milestone"] == "m7e" and r["source"] == "evaluation"
                                          and r["set_kind"] in ("initial", "curve") and r["run"] != "random_baseline")
    sel["m7d_final"] = digests(lambda r: r["milestone"] == "m7d" and r["set"] == "final"
                               and r["mode"] in ("stochastic", "deterministic"))
    sel["six_target_all"] = digests(lambda r: r["targets"] == 6)
    sel["random_baseline"] = digests(lambda r: r["run"] == "random_baseline")
    taken = set().union(*sel.values())
    pool = sorted(d for d, g in groups.items() if g["replayable"] and d not in taken)
    pool.sort(key=lambda d: hashlib.sha256((SAMPLE_SALT + d).encode("ascii")).hexdigest())
    sel["selection_bias_sample"] = sorted(pool[:SAMPLE_SIZE])
    return sel


def build_manifest() -> Dict[str, Any]:
    rows = load_rows()
    groups = group_by_digest(rows)
    sel = select(rows, groups)
    selected = sorted(set().union(*sel.values()))
    membership: Dict[str, List[str]] = defaultdict(list)
    for name, ds in sel.items():
        for d in ds:
            membership[d].append(name)
    sequences = []
    for d in selected:
        g = groups[d]
        n_actions = g["expected"]["length"]
        sequences.append({
            "digest": d, "artifact_dir": g["artifact_dir"], "strata": membership[d], "expected": g["expected"],
            "consistent": g["consistent"],
            "rows": [{k: r[k] for k in ("milestone", "source", "run", "seed", "reward_contract", "set", "set_kind",
                                         "checkpoint_transitions", "mode", "episode_id", "artifact_dir", "row_file",
                                         "startup_mode", "raw_return")} for r in g["rows"]],
            "actions": n_actions,
        })
    total_actions = sum(s["actions"] for s in sequences)
    serial = len(sequences) * COST_BOOT_S + total_actions * COST_STEP_S
    population = {
        "rows_total": len(rows),
        "rows_by_source": dict(Counter(f"{r['milestone']}/{r['source']}" for r in rows)),
        "rows_replayable": sum(1 for r in rows if r["replayable"]),
        "unique_digests": len(groups),
        "unique_replayable": sum(1 for g in groups.values() if g["replayable"]),
        "inconsistent_duplicate_groups": sum(1 for g in groups.values() if not g["consistent"]),
        "max_targets_any_row": max(r["targets"] or 0 for r in rows),
        "rows_by_targets": dict(sorted(Counter(r["targets"] for r in rows).items())),
    }
    strata_doc = []
    for name, rule, supports, cannot in STRATA:
        ds = sel[name]
        rows_n = sum(1 for d in ds for r in groups[d]["rows"])
        strata_doc.append({"name": name, "inclusion_rule": rule, "selected_unique": len(ds),
                           "weighted_rows": rows_n, "supports": supports, "cannot_support": cannot})
    return {
        "schema": "battleship_m7f_replay_manifest_v1",
        "contract": "btt_target_identity_v1",
        "selection": {"deterministic": True, "sample_salt": SAMPLE_SALT, "sample_size": SAMPLE_SIZE,
                      "dedup_key": "native_action_digest (sha256 of 'buttons,stick_x,stick_y,consumed_tick\\n' lines)",
                      "weights": "every historical row sharing a digest; aggregate summaries weight by population rows"},
        "population": population,
        "strata": strata_doc,
        "selected_unique_sequences": len(sequences),
        "selected_total_actions": total_actions,
        "expected_runtime": {"model": f"{COST_BOOT_S} s boot + {COST_STEP_S * 1000:.1f} ms/step per sequence, "
                                      f"{WORKERS} workers with one pre-booted process each (<= 10 processes)",
                             "serial_s": round(serial, 1),
                             "wall_s_estimate": round(max(serial / WORKERS,
                                                          total_actions * COST_STEP_S / WORKERS), 1)},
        "sequences": sequences,
    }


def self_test() -> int:
    bad = []
    rows = [
        {"digest": "a", "replayable": True, "artifact_dir": "x/2", "targets": 6, "length": 3600, "break_ticks": [1],
         "end_reason": "horizon", "last_consumed_tick": 3599, "milestone": "m7e", "source": "evaluation",
         "set": "final", "mode": "stochastic", "set_kind": "final", "run": "m7e_s0_v2"},
        {"digest": "a", "replayable": True, "artifact_dir": "x/1", "targets": 6, "length": 3600, "break_ticks": [1],
         "end_reason": "horizon", "last_consumed_tick": 3599, "milestone": "m7d", "source": "evaluation",
         "set": "final", "mode": "stochastic", "set_kind": "final", "run": "m7d_s0_v2"},
        {"digest": "b", "replayable": False, "artifact_dir": None, "targets": 3, "length": 10, "break_ticks": [2],
         "end_reason": "fall", "last_consumed_tick": 9, "milestone": "m7e", "source": "training", "set": "training",
         "mode": "training", "set_kind": "training", "run": "m7e_s0_v2"},
    ]
    g = group_by_digest(rows)
    if g["a"]["artifact_dir"] != "x/1" or not g["a"]["consistent"] or g["b"]["replayable"]:
        bad.append("grouping")
    rows[1] = {**rows[1], "targets": 5}
    if group_by_digest(rows)["a"]["consistent"]:
        bad.append("inconsistency_not_detected")
    s = select(rows[:1] + rows[2:], group_by_digest(rows[:1] + rows[2:]))
    if s["m7e_final_stochastic"] != ["a"] or s["six_target_all"] != ["a"] or "b" in s["selection_bias_sample"]:
        bad.append("select")
    print(f"m7f_manifest self-test: {'PASS' if not bad else 'FAIL'} (3 cases) {bad}")
    return 0 if not bad else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "rl_target_ceiling_m7f_manifest.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    man = build_manifest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in man.items() if k != "sequences"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
