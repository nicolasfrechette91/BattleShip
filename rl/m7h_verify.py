"""M7h verification shared by the campaign driver, the analysis and the readiness proof (no training here).

Prefix rows. One rule, m7h_curriculum.prefix_rows(labels, rows), says which rows of a recorded episode were replayed by
the prefix phase: rows [0, L) with L from the artifact label `m7h_start` (0 without the label). Every other view of the
same episode must agree with it, and verify_curriculum_run() checks that they do:

    capture        the artifact (metadata labels + actions.jsonl; consumed ticks 0..n-1, so a row index is a tick)
    training       the episode row's `m7h` block (start kind, prefix_length, rows, policy steps; the Monitor's
                   validate_episode_row reads prefix_length) and the parent's selection log (the start dispatched to
                   that env before the episode)
    replay         the prefix digest over rows [0, L) (= the label's = the archive entry's) and, with the game, a fresh
                   tick-0 replay whose observation after row L-1 equals the delivered o_L (replay_boundary)
    analysis       the left-region class recomputed from a replay with the same boundary (replay_boundary), and the
                   genuine-entry replays of section 4 (verify_left_entries), which read the same L

verify_curriculum_run() also re-checks the E4 invariants on every curriculum run (reset contract, accounting, returns,
PPO steps between automatic resets, VecNormalize counts, delivered observations, archive provenance). It never reads
the crossing fixtures, the TAS or another run's directory.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import m7h_curriculum as mc

EPS = 1e-4
TICK0_FAMILY = (mc.START_TICK0, mc.START_TICK0_INITIAL, mc.START_TICK0_ARCHIVE_EMPTY, mc.START_TICK0_AFTER_FAILURE)


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def jsonl(p: Path) -> List[Dict[str, Any]]:
    """Complete lines only (a torn last line is ignored, as the M7 readers do)."""
    p = Path(p)
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                break
    return out


def artifacts_of(root: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    """Every written artifact below <root>/workers/*/artifacts (training) or <root>/w*/artifacts (E3 workers)."""
    root = Path(root)
    out = []
    for adir in sorted(list(root.glob("workers/*/artifacts")) + list(root.glob("w*/artifacts"))):
        for a in sorted(adir.iterdir()):
            if (a / "metadata.json").is_file():
                out.append((a, read_json(a / "metadata.json")))
    return out


def artifact_rows(a: Path) -> List[Dict[str, Any]]:
    return jsonl(Path(a) / "actions.jsonl")


def _digest(rows: Iterable[Mapping[str, Any]]) -> str:
    return mc.native_digest((r["buttons"], r["stick_x"], r["stick_y"], r["consumed_tick"]) for r in rows)


def _family(kind: Optional[str]) -> str:
    return "tick0" if kind in TICK0_FAMILY or kind is None else str(kind)


# -- capture: one artifact ----------------------------------------------------------------------------------------


def boundary_record(a: Path, meta: Mapping[str, Any]) -> Dict[str, Any]:
    """The prefix boundary of one artifact by the one rule, plus the capture-level checks that make it exact."""
    acts = artifact_rows(a)
    labels = meta.get("labels") or {}
    p: List[str] = []
    try:
        L, kind = mc.prefix_rows(labels, len(acts))
    except mc.CurriculumError as exc:
        return {"episode_id": meta.get("episode_id"), "rows": len(acts), "L": None, "kind": None,
                "status": meta.get("status"), "problems": [str(exc)]}
    ticks = [r["consumed_tick"] for r in acts]
    expect = list(range(len(acts)))
    if meta.get("status") == "failed" and ticks and ticks[-1] is None:
        ticks, expect = ticks[:-1], expect[:-1]
    if ticks != expect:
        p.append("consumed ticks are not 0..n-1 (a row index is not its tick)")
    if (meta.get("initial_observation") or {}).get("input_tick") != 0:
        p.append("initial observation is not tick 0")
    full = labels.get("native_action_digest")
    if full is not None and _digest(acts) != full:
        p.append("full native digest differs from the label")
    st = labels.get(mc.START_LABEL) or {}
    if kind == mc.START_PREFIX and _digest(acts[:L]) != st.get("prefix_digest"):
        p.append("digest of rows [0, L) differs from the label's prefix digest")
    if kind in (mc.START_PREFIX_IN_PROGRESS, mc.START_PREFIX_FAILED) and meta.get("status") not in ("aborted", "failed"):
        p.append(f"an unfinished prefix phase in a {meta.get('status')} episode")
    return {"episode_id": meta.get("episode_id"), "rows": len(acts), "L": L, "kind": kind,
            "status": meta.get("status"), "problems": p}


# -- training: the selection log ----------------------------------------------------------------------------------


def selection_starts(log_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """episode_id -> the start the parent gave that env before the episode (kind family, L, vec_step). Within one
    vector step the log holds ingests (episode ends) first, then selections, then deliveries."""
    pending: Dict[int, Dict[str, Any]] = {}
    out: Dict[str, Dict[str, Any]] = {}
    last_end: Dict[int, int] = {}
    for ev in log_rows:
        e = ev.get("event")
        if e == "initial_reset":
            for i in range(int(ev["envs"])):
                pending[i] = {"kind": mc.START_TICK0_INITIAL, "L": 0, "vec_step": ev["vec_step"]}
        elif e in ("ingest", "no_report"):
            i = int(ev["env"])
            if ev.get("episode_id") is not None:
                # the episode's PPO transitions = vector steps since this env's previous automatic reset
                out[str(ev["episode_id"])] = dict(pending.get(i) or {"kind": None, "L": None}, env=i,
                                                  ended_vec_step=ev["vec_step"],
                                                  vec_steps=int(ev["vec_step"]) - last_end.get(i, 0))
            last_end[i] = int(ev["vec_step"])
            pending[i] = None
        elif e == "select":
            i = int(ev["env"])
            if ev["kind"] == mc.START_PREFIX:
                pending[i] = {"kind": "dispatched", "L": int(ev["length"]), "vec_step": ev["vec_step"]}
            else:
                pending[i] = {"kind": ev["kind"], "L": 0, "vec_step": ev["vec_step"]}
        elif e == "delivered":
            i = int(ev["env"])
            L = int(ev.get("prefix_length") or 0) if ev["kind"] == mc.START_PREFIX else 0
            pending[i] = {"kind": ev["kind"], "L": L, "vec_step": ev["vec_step"]}
    return out


# -- a whole curriculum run -----------------------------------------------------------------------------------------


def _vecnorm_count(ckpt: Path) -> float:
    with open(ckpt / "vecnormalize.pkl", "rb") as fh:
        return float(pickle.load(fh).obs_rms.count)


def verify_curriculum_run(run_dir: Path, *, run_id: str, horizon: int = mc.HORIZON, n_envs: int = 5,
                          complete: bool = True) -> Dict[str, Any]:
    """Every prefix-row view agrees; the E4 invariants hold; the archive has own-run provenance. `complete=False`
    for a stopped (partial) run: no final set is required, in-flight artifacts are checked by the boundary rule."""
    from m7_evaluation import CheckpointError, read_checkpoint_set

    run_dir = Path(run_dir)
    p: List[str] = []
    rows = jsonl(run_dir / "metrics" / "episodes.jsonl")
    by_id = {str(r["episode_id"]): r for r in rows}
    log_rows = jsonl(run_dir / "curriculum" / "selection.jsonl")
    starts = selection_starts(log_rows)
    bad: Dict[str, int] = {k: 0 for k in (
        "missing_m7h", "reset_contract", "first_row_not_tick0", "consumed_ticks", "digest_disagrees",
        "rows_ne_prefix_plus_policy", "over_horizon", "horizon_not_3600", "return_formula",
        "total_ne_prefix_plus_policy", "policy_left_before_boundary", "log_L_ne_row_L", "log_kind_ne_row_kind",
        "row_without_log_start", "policy_steps_ne_vec_steps", "artifact_boundary_problems", "artifact_L_ne_row_L",
        "artifact_kind_ne_row_kind", "artifact_rows_ne_row_rows", "artifact_policy_rows_ne_steps",
        "artifact_digest_ne_row", "prefix_digest_ne_row")}
    # 1. rows (training diagnostics view) + the selection log (parent view)
    for r in rows:
        x = r.get("m7h") or {}
        if not x:
            bad["missing_m7h"] += 1
            continue
        L, steps, end = int(x.get("prefix_length") or 0), int(r.get("steps") or 0), r.get("end_reason")
        bad["reset_contract"] += int(not (x.get("reset_contract") or {}).get("ok"))
        bad["first_row_not_tick0"] += int(bool(x.get("rows")) and x.get("first_row_consumed_tick") != 0)
        bad["consumed_ticks"] += int(not x.get("consumed_ticks_ok"))
        bad["digest_disagrees"] += int(not x.get("full_digest_agrees"))
        if end != "lifecycle_failure":
            bad["rows_ne_prefix_plus_policy"] += int(not x.get("rows_equal_prefix_plus_policy"))
        bad["over_horizon"] += int(int(x.get("rows") or 0) > horizon)
        bad["horizon_not_3600"] += int(end == "horizon" and x.get("rows") != horizon)
        want = -0.001 * steps + 1.0 * int(r["targets_broken"]) + (10.0 if r.get("cleared") else 0.0) + \
            (-5.0 if end == "fall" else 0.0)
        bad["return_formula"] += int(end != "lifecycle_failure" and abs(float(r["return"]) - want) > 1e-6)
        if x.get("targets_broken_total") is not None:
            bad["total_ne_prefix_plus_policy"] += int(
                x["targets_broken_total"] != int(x.get("prefix_targets_broken") or 0) + int(r["targets_broken"]))
        fpl = x.get("first_policy_left_step")
        bad["policy_left_before_boundary"] += int(fpl is not None and int(fpl) < L)
        s = starts.get(str(r["episode_id"]))
        if log_rows:
            if s is None:
                bad["row_without_log_start"] += 1
            else:
                bad["log_L_ne_row_L"] += int(s["L"] != L)
                bad["log_kind_ne_row_kind"] += int(_family(s["kind"]) != _family(x.get("start_kind")))
                if end != "lifecycle_failure":      # PPO transitions = vector steps between automatic resets
                    bad["policy_steps_ne_vec_steps"] += int(steps != s["vec_steps"])
    # 2. artifacts (capture view) against the rows
    arts = artifacts_of(run_dir)
    kinds: Dict[str, int] = {}
    no_row = 0
    for a, meta in arts:
        b = boundary_record(a, meta)
        kinds[str(b["kind"])] = kinds.get(str(b["kind"]), 0) + 1
        if b["problems"]:
            bad["artifact_boundary_problems"] += 1
            p.extend(f"{a.name}: {x}" for x in b["problems"][:2])
        r = by_id.get(str(meta.get("episode_id")))
        if r is None:
            no_row += 1
            continue
        x = r.get("m7h") or {}
        if b["L"] is None:
            continue
        bad["artifact_L_ne_row_L"] += int(b["L"] != int(x.get("prefix_length") or 0))
        bad["artifact_kind_ne_row_kind"] += int(_family(b["kind"]) != _family(x.get("start_kind")))
        bad["artifact_rows_ne_row_rows"] += int(b["rows"] != x.get("rows"))
        if r.get("end_reason") != "lifecycle_failure":
            bad["artifact_policy_rows_ne_steps"] += int(b["rows"] - b["L"] != int(r.get("steps") or 0))
        bad["artifact_digest_ne_row"] += int((meta.get("labels") or {}).get("native_action_digest")
                                             != r.get("native_action_digest"))
        if b["kind"] == mc.START_PREFIX:
            bad["prefix_digest_ne_row"] += int(((meta.get("labels") or {}).get(mc.START_LABEL) or {}).get(
                "prefix_digest") != x.get("prefix_digest"))
    # 3. checkpoint sets: VecNormalize counted every returned observation exactly once
    sets: Dict[str, Any] = {}
    cands = sorted((run_dir / "checkpoints").glob("ckpt_*")) if (run_dir / "checkpoints").is_dir() else []
    cands += [d for d in (run_dir / "final",) if d.is_dir()]
    count_bad = 0
    for d in cands:
        try:
            meta = read_checkpoint_set(d)
        except CheckpointError as exc:
            p.append(f"checkpoint {d.name}: {exc}")
            continue
        t = int(meta["num_timesteps"])
        c = _vecnorm_count(d)
        ok = abs(c - (EPS + n_envs + t)) < 1e-6 or (t == 0 and abs(c - EPS) < 1e-9)
        count_bad += int(not ok)
        has_archive = (d / "curriculum_archive.json").is_file()
        sets[d.name] = {"t": t, "obs_rms_count": c, "count_ok": ok, "archive": has_archive}
        if not has_archive and t > 0:     # ckpt_000000000 is written before training: nothing is archived yet
            p.append(f"checkpoint {d.name}: no curriculum archive in a curriculum run's set")
    bad["vecnormalize_count"] = count_bad
    if complete and "final" not in sets:
        p.append("no final checkpoint set")
    # 4. archive provenance (the latest set that holds one)
    prov = archive_provenance(run_dir, run_id=run_id, rows=by_id, arts={str(m.get("episode_id")): a for a, m in arts})
    p.extend(prov["problems"])
    # 5. the run's own counters
    summ = read_json(run_dir / "training_summary.json") if (run_dir / "training_summary.json").is_file() else {}
    cur = summ.get("curriculum") or {}
    if summ:
        if cur.get("delivered_equals_archived_end") != cur.get("prefix_dispatches", 0) - cur.get("lifecycle_failures", 0):
            p.append(f"delivered observations {cur.get('delivered_equals_archived_end')} != prefix dispatches "
                     f"{cur.get('prefix_dispatches')} - lifecycle failures {cur.get('lifecycle_failures')}")
        if int(cur.get("lifecycle_failures") or 0) > 3:
            p.append(f"{cur.get('lifecycle_failures')} prefix-phase lifecycle failures")
        if cur.get("auto_resets") and not cur.get("invariant_checks"):
            p.append("no reward / done / terminal-observation invariant check was recorded")
    if any(ev.get("event") == "select" and ev.get("vec_step") == 0 for ev in log_rows):
        p.append("a selection outside an automatic reset")
    p += [f"{k}: {v}" for k, v in bad.items() if v]
    counts = {"rows": len(rows), "artifacts": len(arts), "artifacts_without_row": no_row, "artifact_kinds": kinds,
              "prefix_rows_starts": sum(1 for r in rows if (r.get("m7h") or {}).get("start_kind") == mc.START_PREFIX),
              "selection_events": len(log_rows), "checkpoint_sets": len(sets)}
    return {"run_dir": str(run_dir), "ok": not p, "problems": p[:60], "problem_count": len(p), "violations": bad,
            "counts": counts, "checkpoint_sets": sets, "archive": prov, "curriculum": cur}


def archive_provenance(run_dir: Path, *, run_id: str, rows: Mapping[str, Mapping[str, Any]],
                       arts: Mapping[str, Path]) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    labels = ["final", "interrupted"] + [d.name for d in sorted((run_dir / "checkpoints").glob("ckpt_*"), reverse=True)] \
        if (run_dir / "checkpoints").is_dir() else ["final", "interrupted"]
    src = None
    for lab in labels:
        d = run_dir / lab if lab in ("final", "interrupted") else run_dir / "checkpoints" / lab
        if (d / "curriculum_archive.json").is_file():
            src = d
            break
    if src is None:
        return {"set": None, "entries": 0, "problems": ["no archive in any checkpoint set"]}
    data = read_json(src / "curriculum_archive.json")
    archive = mc.Archive.from_json(data, (src / "curriculum_prefixes.bin").read_bytes())   # re-verifies prefix digests
    c = {"other_run": 0, "source_not_a_row": 0, "full_digest_ne_row": 0, "prefix_digest_ne_artifact": 0,
         "artifact_rechecked": 0, "ineligible_length": 0}
    for e in archive.entries.values():
        s = e.source
        c["other_run"] += int(s.get("run_id") != run_id)
        row = rows.get(str(s.get("episode_id")))
        if row is None:
            c["source_not_a_row"] += 1
        elif row.get("native_action_digest") != s.get("full_digest"):
            c["full_digest_ne_row"] += 1
        c["ineligible_length"] += int(e.eligible and not 1 <= e.length <= mc.MAX_PREFIX_TICKS)
        a = arts.get(str(s.get("episode_id")))
        if a is not None:
            c["artifact_rechecked"] += 1
            c["prefix_digest_ne_artifact"] += int(_digest(artifact_rows(a)[:e.length]) != e.digest)
    problems = [f"archive {k}: {v}" for k, v in c.items() if k != "artifact_rechecked" and v]
    if data.get("run_id") != run_id:
        problems.append(f"archive run_id {data.get('run_id')} != {run_id}")
    return {"set": src.name, "entries": len(archive.entries), "eligible": len(archive.eligible()), **c,
            "problems": problems}


# -- evaluation is tick-0 only ---------------------------------------------------------------------------------------


FINISHED_STATUSES = ("terminal", "truncated", "failed")
KEPT = "kept_with_preserved_artifact"
TICK0_COUNTERS = ("with_start_label", "initial_not_tick0", "first_row_not_tick0", "ticks_not_contiguous",
                  "digest_mismatch", "rows_with_m7h")


def _tail(path: Any) -> str:
    """<mode>/workers/wNN/artifacts/<episode id> of an artifact path: where it lies inside its label (copy-proof)."""
    return "/".join(Path(str(path).replace("\\", "/")).parts[-5:]) if path else ""


def _ledger(mode_dir: Path) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """episode_id -> the worker's own disposition record (dispositions.jsonl, kind episode_dir) of every worker."""
    out: Dict[str, Dict[str, Any]] = {}
    p: List[str] = []
    for f in sorted(Path(mode_dir).glob("workers/w*/dispositions.jsonl")):
        for r in jsonl(f):
            if r.get("kind") != "episode_dir":
                continue
            eid = str(r.get("episode_id"))
            if eid in out:
                p.append(f"{Path(mode_dir).name}: episode {eid} recorded twice in the worker ledgers")
            out[eid] = r
    return out, p


def _kept(led: Optional[Mapping[str, Any]], a: Path, rank: Any, worker_episode: Any) -> bool:
    return bool(led) and led.get("decision") == KEPT and _tail(led.get("artifact_dir")) == _tail(a) \
        and (led.get("rank"), led.get("worker_episode")) == (rank, worker_episode)


def verify_eval_tick0(label_dir: Path) -> Dict[str, Any]:
    """Every evaluation episode of one label is a tick-0 start, and every preserved artifact is accounted for.

    Tick 0, on every artifact (counted or excess): no m7h_start label, a tick-0 initial observation, consumed ticks
    0..n-1 (a failed episode may end on a row without a tick), the native digest of its rows equal to its label; no
    curriculum key in any evaluation row.

    Accounting (amendment 1): the artifacts are exactly the counted rows plus the excess episodes the evaluator
    recorded. m7_evaluation stops once the quota is met and counts the other episodes that finished on that same
    vector step as excess_episodes_not_counted; preserve_all still writes their artifact. Each counted row names its
    own artifact (episode id, location, rank, worker episode, native digest), recorded as preserved in its worker's
    ledger. Each excess artifact must be recorded as preserved in its worker's ledger, be a finished evaluation episode
    of the same run id, be its worker's next episode after its last counted one (one per worker), have ended on the
    final vector step (native_steps_at_end = vec_steps), and come after every counted episode of that step in rank
    order (the collection order). A missing or invalid excess record, a count that differs from the artifacts, an
    unrecorded or aborted artifact, or any other extra artifact fails."""
    label_dir = Path(label_dir)
    c = {"artifacts": 0, "rows": 0, "excess_recorded": 0, "excess_artifacts": 0, **{k: 0 for k in TICK0_COUNTERS}}
    problems: List[str] = []
    excess_ids: List[str] = []
    for mode in ("stochastic", "deterministic"):
        mdir = label_dir / mode
        arts: Dict[str, Tuple[Path, Dict[str, Any]]] = {}
        for a in sorted(mdir.glob("workers/w*/artifacts/*")):
            if not (a / "metadata.json").is_file():
                continue
            meta = read_json(a / "metadata.json")
            eid = str(meta.get("episode_id"))
            if eid in arts:
                problems.append(f"{mode}: two artifacts carry episode id {eid}")
            arts[eid] = (a, meta)
        # tick 0 and capture identity, on every artifact
        for a, meta in arts.values():
            c["artifacts"] += 1
            labels = meta.get("labels") or {}
            c["with_start_label"] += int(mc.START_LABEL in labels)
            c["initial_not_tick0"] += int((meta.get("initial_observation") or {}).get("input_tick") != 0)
            acts = artifact_rows(a)
            c["first_row_not_tick0"] += int(bool(acts) and acts[0]["consumed_tick"] != 0)
            ticks, expect = [r["consumed_tick"] for r in acts], list(range(len(acts)))
            if meta.get("status") == "failed" and ticks and ticks[-1] is None:
                ticks, expect = ticks[:-1], expect[:-1]
            c["ticks_not_contiguous"] += int(ticks != expect)
            c["digest_mismatch"] += int(labels.get("native_action_digest") is None
                                        or _digest(acts) != labels.get("native_action_digest"))
        f = mdir / "evaluation.json"
        if not f.is_file():
            if arts:
                problems.append(f"{mode}: {len(arts)} artifacts but no evaluation.json")
            continue
        doc = read_json(f)
        eps = doc.get("episodes") or []
        c["rows"] += len(eps)
        c["rows_with_m7h"] += sum(1 for e in eps if any(str(k).startswith("m7h") for k in e))
        n_ex = doc.get("excess_episodes_not_counted")
        if not isinstance(n_ex, int) or isinstance(n_ex, bool) or n_ex < 0:
            problems.append(f"{mode}: no valid excess record (excess_episodes_not_counted = {n_ex!r})")
            n_ex = 0
        c["excess_recorded"] += n_ex
        ledger, lp = _ledger(mdir)
        problems += lp
        vec_steps, workers = doc.get("vec_steps"), doc.get("workers")
        # counted rows: each names its own preserved artifact
        row_ids: set = set()
        last_counted: Dict[Any, int] = {}
        final_step_ranks: List[int] = []
        run_ids: set = set()
        for e in eps:
            eid = str(e.get("episode_id"))
            if eid in row_ids:
                problems.append(f"{mode}: episode {eid} counted twice")
            row_ids.add(eid)
            got = arts.get(eid)
            if got is None:
                problems.append(f"{mode}: counted episode {eid} has no artifact (every episode is preserved)")
                continue
            a, meta = got
            lab = meta.get("labels") or {}
            rank, we = lab.get("rank"), lab.get("worker_episode")
            if _tail(e.get("artifact_dir")) != _tail(a) or (rank, we) != (e.get("rank"), e.get("worker_episode")) \
                    or lab.get("native_action_digest") != e.get("native_action_digest") \
                    or not isinstance(rank, int) or a.parent.parent.name != f"w{rank:02d}":
                problems.append(f"{mode}: counted episode {eid} and its artifact disagree (location, rank, worker "
                                f"episode or digest)")
                continue
            if not _kept(ledger.get(eid), a, rank, we):
                problems.append(f"{mode}: counted episode {eid} is not recorded as preserved in its worker ledger")
            last_counted[rank] = max(last_counted.get(rank, 0), int(we))
            run_ids.add(lab.get("run_id"))
            if vec_steps is not None and lab.get("native_steps_at_end") == vec_steps:
                final_step_ranks.append(rank)
        # the rest: exactly the recorded excess episodes
        extra = [(eid, a, meta) for eid, (a, meta) in sorted(arts.items()) if eid not in row_ids]
        c["excess_artifacts"] += len(extra)
        if len(extra) != n_ex:
            problems.append(f"{mode}: {len(extra)} preserved artifacts beyond the {len(eps)} counted rows, but the "
                            f"evaluator recorded {n_ex} excess episodes")
        excess_ranks: set = set()
        for eid, a, meta in extra:
            lab = meta.get("labels") or {}
            rank, we = lab.get("rank"), lab.get("worker_episode")
            why: List[str] = []
            if not _kept(ledger.get(eid), a, rank, we):
                why.append("not recorded as preserved in its worker ledger")
            if meta.get("status") not in FINISHED_STATUSES or lab.get("episode_status") != meta.get("status") \
                    or lab.get("end_reason") in (None, "aborted"):
                why.append(f"not a finished episode (status {meta.get('status')}, end {lab.get('end_reason')})")
            if lab.get("role") != "evaluation" or len(run_ids) != 1 or lab.get("run_id") not in run_ids:
                why.append(f"role / run id {lab.get('role')} / {lab.get('run_id')} differ from the counted episodes")
            if not isinstance(rank, int) or not isinstance(workers, int) or not 0 <= rank < workers \
                    or a.parent.parent.name != f"w{rank:02d}":
                why.append(f"rank {rank} / worker directory {a.parent.parent.name}")
            else:
                if we != last_counted.get(rank, 0) + 1:
                    why.append(f"worker episode {we} is not rank {rank}'s next after its last counted "
                               f"{last_counted.get(rank, 0)}")
                if rank in excess_ranks:
                    why.append(f"a second excess episode of rank {rank}")
                if not final_step_ranks or any(r >= rank for r in final_step_ranks):
                    why.append(f"not after every counted episode of the final vector step in rank order "
                               f"(counted there: {sorted(final_step_ranks)})")
                excess_ranks.add(rank)
            if vec_steps is None or lab.get("native_steps_at_end") != vec_steps:
                why.append(f"did not end on the final vector step ({lab.get('native_steps_at_end')} != {vec_steps})")
            if why:
                problems.append(f"{mode}: excess artifact {eid}: {'; '.join(why)}")
            else:
                excess_ids.append(eid)
    problems = [f"{k}: {c[k]}" for k in TICK0_COUNTERS if c[k]] + problems
    if c["artifacts"] != c["rows"] + c["excess_recorded"]:
        problems.append(f"{c['artifacts']} artifacts for {c['rows']} evaluation rows + {c['excess_recorded']} recorded "
                        f"excess episodes (every episode is preserved)")
    return {"label_dir": str(label_dir), "ok": not problems, "problems": problems, **c, "excess_episode_ids": excess_ids}


# -- replay (the game): the boundary and the left-region class from tick 0 ------------------------------------------


def _left_indices(steps: Sequence[Mapping[str, Any]]) -> List[int]:
    return [i for i, s in enumerate(steps) if mc.is_left(s["observation"])]


def replay_boundary(actions: Sequence[Tuple[int, int, int, Optional[int]]], *, L: int, work: Path, executable: Path,
                    extra_env: Mapping[str, str], index: int, expected_digest: Optional[str],
                    boundary_observation: Optional[Mapping[str, Any]] = None,
                    final_observation: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """A fresh process, tick 0, every row resubmitted (M7f stepping trace). Checks consumed ticks, the digest, the
    observation after row L-1 (the delivered o_L) and returns the left-region facts on each side of L."""
    import shutil

    import m7f_trace as tr
    from m7_runtime import remove_worker_runtime

    trace = tr.run_stepping_trace(f"m7h_boundary_{index}", Path(executable), list(actions), Path(work),
                                  extra_env=dict(extra_env), index=index)
    steps = trace.get("steps") or []
    p: List[str] = []
    if trace.get("consumed_tick_mismatch") is not None or trace.get("unsent"):
        p.append(f"replay not exact: mismatch {trace.get('consumed_tick_mismatch')} unsent {trace.get('unsent')}")
    if expected_digest is not None and trace.get("action_digest") != expected_digest:
        p.append("replayed digest differs")
    host_equal = None
    if L > 0 and boundary_observation is not None and len(steps) >= L:
        got = mc.observation_dict(steps[L - 1]["observation"])
        diffs = mc.observation_diffs(got, boundary_observation)
        host_equal = got.get("host_frame") == boundary_observation.get("host_frame")
        if diffs:
            p.append(f"observation after row L-1 differs from the delivered o_L: {diffs}")
    if final_observation is not None and steps:
        got = mc.observation_dict(steps[-1]["observation"])
        diffs = mc.observation_diffs(got, final_observation)
        if diffs:
            p.append(f"final observation differs: {diffs}")
    left = _left_indices(steps)
    prefix_left = sum(1 for i in left if i < L)
    first_policy = next((i for i in left if i >= L), None)
    remove_worker_runtime(Path(work) / "runtime")
    shutil.rmtree(Path(work) / "episodes", ignore_errors=True)
    return {"ok": not p, "problems": p, "rows": len(steps), "L": L, "prefix_left_steps": prefix_left,
            "first_policy_left_step": first_policy, "boundary_host_frame_equal": host_equal,
            "stepping_s": trace.get("stepping_s")}


def track1_actions(actions: bytes) -> List[Tuple[int, int, int, int]]:
    return [(*mc.track1_triple(a), i) for i, a in enumerate(actions)]


def verify_left_entries(run_dir: Path, *, out_dir: Path, executable: Path, extra_env: Mapping[str, str],
                        extra: int = 5, index_base: int = 9700) -> Dict[str, Any]:
    """Section 4: the first genuine_new_policy_entry episode of a run and up to `extra` more, replayed from tick 0 in
    fresh processes (evaluation-only target diagnostic on). Verified when the replay is exact, its digest equals the
    run's, no prefix row is a live left step and the first live left step is the recorded one, on a row >= L.
    g = 1 iff at least one is verified."""
    recs = [r for r in jsonl(Path(run_dir) / "curriculum" / "left_episodes.jsonl") if r.get("class") == mc.CLASS_GENUINE]
    chosen = recs[:1 + int(extra)]
    out = []
    for k, r in enumerate(chosen):
        acts = track1_actions(bytes.fromhex(r["actions_hex"]))
        res = replay_boundary(acts, L=int(r["prefix_length"]), work=Path(out_dir) / f"entry_{k:02d}",
                              executable=executable, extra_env=extra_env, index=index_base + k,
                              expected_digest=r["full_digest"])
        want = (r.get("left") or {}).get("first_policy_left_step")
        if res["prefix_left_steps"] != 0:
            res["problems"].append(f"{res['prefix_left_steps']} live left steps on prefix rows")
        if res["first_policy_left_step"] is None or res["first_policy_left_step"] != want or \
                res["first_policy_left_step"] < int(r["prefix_length"]):
            res["problems"].append(f"first live left step {res['first_policy_left_step']} (recorded {want}, "
                                   f"L {r['prefix_length']})")
        res["ok"] = not res["problems"]
        out.append({"episode_id": r["episode_id"], "vec_step": r["vec_step"], "L": r["prefix_length"], **res})
    verified = sum(1 for x in out if x["ok"])
    return {"genuine_episodes_recorded": len(recs), "replayed": len(out), "verified": verified,
            "g": int(verified > 0), "entries": out}
