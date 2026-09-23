"""M7g: game-backed crossing-fixture replay, verification and fixture building.

Every execution starts a FRESH BattleShip process (private runtime directory = a byte copy of the user configuration,
M2 lifecycle, kill-on-close job) and replays a canonical native action sequence from native tick 0: no hidden prefix,
the tick-0 observe reply is non-consuming, the first action consumes tick 0, one action per tick. Replies are captured
raw (the M7f `client.request` shadowing precedent), so the 17-field observation and the M7f `targets` diagnostic of
every tick are kept. Nothing here trains, and nothing is written outside --out / runs/m7g and, for a validated
fixture, rl/fixtures/m7g.

Verification matrix (`verify`): the same sequence in
  cold_nrr    no-render + Raphnet bypass (the historical training host mode), diagnostic on  -> reference + evidence
  cold_nrr_r2 the same again                                                            -> cold repeatability
  cold_nr     no-render only                                                             -> Raphnet bypass neutral
  visible     normal rendered window                                                     -> visible trajectory
  diag_off    no-render + Raphnet bypass, diagnostic off                                 -> diagnostic neutral
  parked      no-render + Raphnet bypass, parked 12 s at tick 0 before the first action   -> "what a standby is"
  standby     the real M7c lifecycle (btt_parallel.M7BattleShipBTTEnv, standby on): a cold episode, then a
              promoted pre-booted standby episode, both replaying the sequence            -> promotion equivalence
All trajectories (every step's state / step_count / consumed_tick / 16 gameplay observation fields) must be identical;
action digests, btt_policy_obs_v1 bytes and reward v1/v2 returns must be identical; `targets` must be identical
across the diagnostic-on runs and pass the M7f invariants.

Usage:
  python rl/m7g_crossing.py evidence <source> [--mode no_render_raphnet] [--allow-non-track1] [--out DIR]
  python rl/m7g_crossing.py verify <source> [--out DIR] [--quick]
  python rl/m7g_crossing.py build <draft> --crossing lower_precision|upper_moving_platform
                                    --source user_recorded|imported|independently_searched [--note TEXT]
  python rl/m7g_crossing.py check-fixture <fixture.json>      (document consistency only, no game)
build exit codes: 0 fixture written, route confirmed; 3 fixture written AS DECLARED, route classification needs review
(never relabelled); 1 no fixture (no native left entry, or a hard gate failed; the draft is never modified).
<source> = a draft/fixture JSON, a btt_track1_script_v1 text file, a .btti, a JSON action list or an M4 artifact dir.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7g_fixture as fx  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
RUN_ROOT = REPO_ROOT / "runs" / "m7g"
FIXTURE_DIR = RL_DIR / "fixtures" / "m7g"
USER_CONFIG = REPO_ROOT / "build-us" / "Release" / "BattleShip.cfg.json"

MODES: Dict[str, Dict[str, str]] = {
    "normal": {},
    "no_render": {"SSB64_RL_NO_RENDER": "1"},
    "no_render_raphnet": {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"},
}
DIAG = {"SSB64_RL_TARGET_DIAG": "1"}
PARK_S = 12.0
# Reported (and flagged for route review where relevant), never gating a genuine crossing: host-frame counting,
# route-evidence quality, and the M7f diagnostic's own internal consistency (its repeatability stays a hard gate).
INFORMATIONAL_CHECKS = ("host_frame_identical_cold_modes", "ground_matched", "target_diag_invariants")
EXIT_FIXTURE_CONFIRMED, EXIT_NO_FIXTURE, EXIT_FIXTURE_REVIEW = 0, 1, 3

Row = Tuple[int, int, int]


def log(msg: str) -> None:
    print(f"[m7g_crossing] {msg}", flush=True)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_gz(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fp:
        json.dump(obj, fp, separators=(",", ":"))


def write_json_exclusive(path: Path, obj: Any) -> None:
    """Create `path` atomically and only if it does not exist (a hard link of a complete temp file): a preserved
    fixture is never overwritten, even by a concurrent build."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8", newline="\n")
    try:
        os.link(tmp, path)
    except FileExistsError:
        raise fx.FixtureError(f"fixture already exists (not overwritten): {path}") from None
    finally:
        tmp.unlink()


def refuse_recording_dir(path: Path, what: str) -> None:
    """Outputs never go into a capture recording directory (one holding session.jsonl or draft.json)."""
    rec = fx.recording_dir_of(path)
    if rec is not None:
        raise fx.FixtureError(f"{what} {path} would be inside the capture recording {rec}; choose another location")


def read_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        return json.load(fp)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    from m7_runtime import replace_with_retry

    tmp.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8", newline="\n")
    replace_with_retry(tmp, path)  # Windows: a scanner/indexer may briefly hold the destination (M7a)


# -- one fresh-process replay -------------------------------------------------------------------------------

def replay(rows: Sequence[Row], work: Path, *, mode: str = "no_render_raphnet", diag: bool = True,
           park_s: float = 0.0, extra_env: Optional[Mapping[str, str]] = None, rank: int = 0, index: int = 0,
           executable: Path = EXE, on_step: Optional[Callable[[int, Dict[str, Any]], Optional[bool]]] = None
           ) -> Dict[str, Any]:
    """Launch a fresh process, check freshness at tick 0, submit rows[i] expecting consumed_tick i, capture every raw
    reply. Stops at EpisodeEnded (the clear is finished natively: exit code + result JSON) or at the M7 fall rule
    (btt_native_failure_v1; the process is then disposed). on_step(i, reply) returning True stops early."""
    from battleship_client import StepState
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, prepare_worker_runtime

    work = Path(work).resolve()
    runtime = work / "runtime"
    prepare_worker_runtime(runtime, executable)
    port, _busy = PortCandidates(rank).claim()
    (work / "episodes").mkdir(parents=True, exist_ok=True)
    env = {**MODES[mode], **(DIAG if diag else {}), **dict(extra_env or {})}
    cfg = LaunchConfig(executable=Path(executable), working_dir=runtime, run_root=work / "episodes", port=port,
                       startup_timeout=30.0, ready_timeout=90.0, request_timeout=15.0, exit_timeout=30.0,
                       extra_env=env)
    trace: Dict[str, Any] = {"mode": mode, "diag": diag, "park_s": park_s, "extra_env": env, "rows": len(rows),
                             "executable": str(executable)}
    replies: List[Dict[str, Any]] = []
    episode = BattleShipEpisode(cfg, index=index)
    problems: List[str] = []
    with episode:
        t0 = time.perf_counter()
        fresh = episode.start()
        trace["startup_s"] = round(time.perf_counter() - t0, 3)
        trace["fresh"] = {"state": fresh.state_name, "step_count": fresh.step_count, "can_step": fresh.can_step}
        client = episode.client
        original = client.request

        def request(op: str, **payload: Any) -> Dict[str, Any]:
            reply = original(op, **payload)
            replies.append(reply)
            return reply

        client.request = request
        trace["status"] = client.request("status")
        if park_s > 0:
            time.sleep(park_s)  # parked at tick 0 before the first action: the standby condition (M7c / M7f)
        trace["initial"] = client.request("observe")
        io = trace["initial"].get("observation") or {}
        if not (fresh.can_step and fresh.step_count == 0 and trace["initial"].get("step_count") == 0
                and io.get("input_tick") == 0 and io.get("time_passed") == 0):
            problems.append(f"not fresh at tick 0: {trace['fresh']} observe step_count "
                            f"{trace['initial'].get('step_count')} input_tick {io.get('input_tick')}")
        steps: List[Dict[str, Any]] = []
        last = None
        t1 = time.perf_counter()
        for i, (b, x, y) in enumerate(rows):
            result = client.step(int(b), int(x), int(y))
            reply = replies[-1]
            steps.append(reply)
            obs = reply.get("observation") or {}
            if (result.consumed_tick != i or obs.get("input_tick") != i + 1 or result.step_count != i + 1) \
                    and len(problems) < 20:
                problems.append(f"step {i}: consumed_tick {result.consumed_tick} input_tick {obs.get('input_tick')} "
                                f"step_count {result.step_count} (expected {i} / {i + 1} / {i + 1})")
            last = result
            if result.state == StepState.EPISODE_ENDED or fx.is_fall(reply):
                break
            if on_step is not None and on_step(i, reply):
                break
        trace["stepping_s"] = round(time.perf_counter() - t1, 3)
        trace["steps"] = steps
        trace["submitted"] = len(steps)
        trace["unsent"] = len(rows) - len(steps)
        trace["final_state"] = last.state_name if last is not None else None
        if last is not None and last.state == StepState.EPISODE_ENDED:
            done = episode.finish(last)
            trace["exit_code"] = done.exit_code
            trace["result"] = dict(done.result)
        else:
            trace["exit_code"] = None
            trace["result"] = None
    trace["cleanup"] = episode.cleanup_action
    trace["pid"] = episode.pid
    trace["problems"] = problems
    trace["action_digest"] = fx.native_action_digest(rows[:len(trace["steps"])],
                                                     [s["consumed_tick"] for s in trace["steps"]])
    return trace


def standby_replay(rows: Sequence[Row], work: Path, *, rank: int = 1, executable: Path = EXE) -> Dict[str, Any]:
    """The real M7c lifecycle: M7BattleShipBTTEnv with one pre-booted standby. Episode 1 is a cold start, episode 2
    a promoted standby; both replay `rows` from tick 0 through the unchanged M3 action conversion."""
    from battleship_env import native_to_action
    from battleship_process import LaunchConfig
    from btt_parallel import M7BattleShipBTTEnv, StandbySettings
    from m7_runtime import PortCandidates, prepare_worker_runtime

    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    prepare_worker_runtime(work / "runtime", executable)
    env_vars = {**MODES["no_render_raphnet"], **DIAG}
    launch = LaunchConfig(executable=Path(executable), working_dir=work / "runtime", run_root=work / "episodes",
                          extra_env=env_vars, request_timeout=15.0, exit_timeout=15.0)
    base = M7BattleShipBTTEnv(launch, max_episode_steps=len(rows) + 10, rank=rank, ports=PortCandidates(rank),
                              standby=StandbySettings(True, 1, 120.0), generation_runtime_root=work / "runtime_gens",
                              profile={"reward_contract": "none (m7g fixture replay)", "horizon": len(rows) + 10})

    episodes = []
    try:
        for _ep in range(2):
            _obs, info = base.reset()
            # the promoted (or cold) episode's own client, shadowed like M7f so the raw replies keep `targets`
            client = base._episode.client
            replies: List[Dict[str, Any]] = []
            original = client.request

            def request(op: str, _orig: Any = original, _sink: List[Dict[str, Any]] = replies,
                        **payload: Any) -> Dict[str, Any]:
                reply = _orig(op, **payload)
                _sink.append(reply)
                return reply

            client.request = request
            initial = client.request("observe")  # non-consuming: the tick-0 reply, with the diagnostic
            steps: List[Dict[str, Any]] = []
            consumed: List[int] = []
            for b, x, y in rows:
                _o, _r, term, trunc, sinfo = base.step(native_to_action(int(b), int(x), int(y)))
                steps.append(replies[-1])
                consumed.append(int(sinfo["consumed_tick"]))
                if term or trunc:
                    break
            episodes.append({"startup_mode": info["m7_startup"]["mode"], "pid": info.get("pid"), "initial": initial,
                             "steps": steps, "submitted": len(steps),
                             "action_digest": fx.native_action_digest(rows[:len(steps)], consumed)})
    finally:
        base.close()
    return {"mode": "standby_lifecycle", "episodes": episodes, "report": base.standby_report()}


# -- verification matrix ------------------------------------------------------------------------------------

def _summary(trace: Mapping[str, Any]) -> Dict[str, Any]:
    init, steps = trace["initial"], trace["steps"]
    pol, npol = fx.policy_obs_v1_digest(init, steps)
    return {"submitted": len(steps), "trajectory_digest": fx.trajectory_digest(init, steps),
            "trajectory_digest_with_host_frame": fx.trajectory_digest(init, steps, include_host_frame=True),
            "targets_digest": fx.targets_digest(init, steps), "policy_obs_v1_digest": pol, "policy_obs_vectors": npol,
            "returns": fx.returns_v1_v2(init, steps), "final_state": trace.get("final_state"),
            "exit_code": trace.get("exit_code"), "result": trace.get("result"),
            "action_digest": trace.get("action_digest"), "problems": trace.get("problems", []),
            "startup_s": trace.get("startup_s"), "stepping_s": trace.get("stepping_s")}


def verify(seq: Sequence[Tuple[int, int]], out: Path, *, quick: bool = False,
           capture_trajectory_digest: Optional[str] = None, executable: Path = EXE) -> Dict[str, Any]:
    """Run the verification matrix for a Track 1 sequence and return the report (also written to out/)."""
    from m7_runtime import file_fingerprint, list_processes_named, repository_revisions, sha256_file

    seq = fx.validate_track1(seq)
    rows = fx.track1_to_native(seq)
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):  # never write into an existing directory (a capture directory above all)
        raise RuntimeError(f"verification output directory exists and is not empty: {out}")
    refuse_recording_dir(out, "verification output")
    out.mkdir(parents=True, exist_ok=True)
    if list_processes_named():
        raise RuntimeError(f"other BattleShip processes are running: {list_processes_named()}")
    geo = fx.decode_stage_geometry()
    cfg_before = file_fingerprint(USER_CONFIG)
    plan = [("cold_nrr", dict(mode="no_render_raphnet")), ("cold_nrr_r2", dict(mode="no_render_raphnet")),
            ("cold_nr", dict(mode="no_render")), ("visible", dict(mode="normal")),
            ("diag_off", dict(mode="no_render_raphnet", diag=False)),
            ("parked", dict(mode="no_render_raphnet", park_s=PARK_S))]
    if quick:
        plan = plan[:2]
    runs: Dict[str, Dict[str, Any]] = {}
    traces: Dict[str, Dict[str, Any]] = {}
    for k, (name, kw) in enumerate(plan):
        log(f"{name}: {len(rows)} actions ({kw})")
        tr = replay(rows, out / "work" / name, index=k, executable=executable, **kw)
        write_gz(out / f"{name}.json.gz", tr)
        traces[name] = tr
        runs[name] = _summary(tr)
    if not quick:
        log("standby: real M7c lifecycle (cold episode, then a promoted standby)")
        sb = standby_replay(rows, out / "work" / "standby", executable=executable)
        write_gz(out / "standby.json.gz", sb)
        for j, ep in enumerate(sb["episodes"]):
            runs[f"standby_ep{j + 1}_{ep['startup_mode']}"] = {**_summary(ep), "startup_mode": ep["startup_mode"]}
    ref = runs["cold_nrr"]
    ref_trace = traces["cold_nrr"]
    evidence = fx.crossing_evidence(geo, ref_trace["initial"], ref_trace["steps"], submitted=ref_trace["submitted"])
    classification = fx.classify_crossing(evidence, geo)
    diag_runs = [n for n in runs if n != "diag_off"]  # every run but diag_off has the target diagnostic on
    checks: Dict[str, Any] = {}

    def chk(name: str, ok: bool, detail: Any = None) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    chk("track1_exact", True, f"{len(seq)} actions, all in the 72-action btt_s9_b8_v1 space; native rows are table images")
    chk("fresh_tick0", all(not any("not fresh" in p for p in traces[n]["problems"]) for n in traces),
        {n: traces[n]["fresh"] for n in traces})
    chk("first_action_consumes_tick0", all(traces[n]["steps"] and traces[n]["steps"][0]["consumed_tick"] == 0
                                           for n in traces))
    chk("contiguous_ticks", all(not traces[n]["problems"] for n in traces),
        {n: traces[n]["problems"][:3] for n in traces if traces[n]["problems"]})
    same_len = all(r["submitted"] == ref["submitted"] for r in runs.values())
    chk("identical_trajectories", same_len and all(r["trajectory_digest"] == ref["trajectory_digest"]
                                                   for r in runs.values()),
        {n: r["trajectory_digest"][:16] for n, r in runs.items()})
    chk("all_actions_consumed", all(r["submitted"] == len(seq) for r in runs.values()),
        {n: r["submitted"] for n, r in runs.items() if r["submitted"] != len(seq)} or f"{len(seq)} in every run")
    chk("identical_action_digests", all(r.get("action_digest") == fx.native_action_digest(rows) for r in runs.values()))
    chk("identical_policy_obs_v1", all(r["policy_obs_v1_digest"] == ref["policy_obs_v1_digest"] for r in runs.values()))
    chk("identical_rewards", all(r["returns"] == ref["returns"] for r in runs.values()), ref["returns"])
    chk("identical_targets_diag", all(runs[n]["targets_digest"] == ref["targets_digest"] for n in diag_runs)
        and runs.get("diag_off", {}).get("targets_digest") is None)
    chk("target_diag_invariants", bool(evidence["targets"]) and evidence["targets"]["diag_ok"],
        (evidence["targets"] or {}).get("diag_problems"))
    # route-evidence quality, recorded and flagged for review, never a reason to drop a genuine crossing
    chk("ground_matched", evidence["ground_unmatched_steps"] == 0, evidence["ground_unmatched_first"])
    chk("host_frame_identical_cold_modes", len({runs[n]["trajectory_digest_with_host_frame"] for n in traces
                                                if n != "parked"}) == 1, "informational")
    if capture_trajectory_digest is not None:
        chk("matches_capture", capture_trajectory_digest == ref["trajectory_digest"],
            {"capture": capture_trajectory_digest, "replay": ref["trajectory_digest"]})
    if not quick:
        modes = [r.get("startup_mode") for n, r in runs.items() if n.startswith("standby_")]
        chk("standby_promoted", modes == ["cold_start", "standby_promoted"], modes)
    chk("native_left_region_entry", evidence["crossed"], evidence["first_left_entry"])
    required = [n for n in checks if n not in INFORMATIONAL_CHECKS and n != "native_left_region_entry"]
    report = {"schema": "btt_crossing_verification_v1", "utc": utc_stamp(), "quick": quick,
              "executable_sha256": sha256_file(Path(executable)), "revisions": repository_revisions(),
              "sequence": {"length": len(seq), "track1_digest": fx.track1_digest(seq),
                           "native_action_digest": fx.native_action_digest(rows)},
              "runs": runs, "checks": checks, "replay_ok": all(checks[n]["ok"] for n in required),
              "crossed": evidence["crossed"], "evidence": evidence, "classification": classification,
              "executions": len(runs), "geometry": fx.geometry_summary(geo),
              "user_config_before": cfg_before, "user_config_after": file_fingerprint(USER_CONFIG),
              "gameplay_config": fx.gameplay_config(USER_CONFIG), "leftover_battleship": list_processes_named()}
    report["user_config_unchanged"] = cfg_before.get("sha256") == report["user_config_after"].get("sha256")
    write_json(out / "verification.json", report)
    return report


# -- fixture building --------------------------------------------------------------------------------------

def build_fixture(draft_path: Path, crossing: str, source_kind: str, *, note: str = "",
                  out_root: Optional[Path] = None, fixture_dir: Path = FIXTURE_DIR) -> Tuple[Optional[Path], Dict[str, Any]]:
    """Verify a draft and write rl/fixtures/m7g/<fixture_id>.json when the sequence is a genuine, reproducible crossing:
    exact Track 1 actions from tick 0, a native left-region entry, every action consumed and 8 identical executions
    (plus the source/capture/integrity gates). The route classifier never gates: a crossing it does not confirm is
    written AS DECLARED with route.agreement 'mismatch' / 'unclassified' and review_required, never relabelled or
    dropped. Never writes a fixture for a sequence that does not cross, never overwrites an existing fixture, and
    never writes into the draft's directory (the capture recording is only read)."""
    from m7_runtime import portable_path

    if crossing not in fx.CROSSINGS or source_kind not in fx.SOURCES:
        raise fx.FixtureError(f"crossing must be one of {fx.CROSSINGS}, source one of {fx.SOURCES}")
    seq, meta = fx.load_sequence(Path(draft_path))
    draft = meta.get("document") or {}  # only for draft/fixture JSON (a plain action list carries no metadata)
    recorded_kind = meta.get("source_kind")
    session_capture = (draft.get("session") or {}).get("capture") or {}
    capture_digest = session_capture.get("trajectory_digest")
    # The source kind is evidence, not a free label: it must agree with what the draft recorded, user_recorded needs
    # a live capture (and its capture-vs-replay match), and a plain file can only be imported or searched.
    source_problems = []
    if recorded_kind is not None and recorded_kind != source_kind:
        source_problems.append(f"--source {source_kind} contradicts the draft's recorded source kind {recorded_kind!r}")
    if recorded_kind is None and source_kind == "user_recorded":
        source_problems.append("user_recorded needs a capture draft (rl/m7g_capture.py play), not a plain file")
    if source_kind == "user_recorded" and capture_digest is None:
        source_problems.append("user_recorded draft without a capture trajectory digest")
    rows = fx.track1_to_native(seq)
    nad = fx.native_action_digest(rows)
    fixture_id = f"{crossing}_{nad[:12]}"
    path = fixture_dir / f"{fixture_id}.json"
    if path.exists():  # a preserved record is never replaced; remove it by hand if that is really intended
        raise fx.FixtureError(f"fixture already exists (not overwritten): {path}")
    twins = [p for c in fx.CROSSINGS if c != crossing for p in [fixture_dir / f"{c}_{nad[:12]}.json"] if p.exists()]
    if twins:  # lower and upper fixtures stay distinct: one recording is never both
        raise fx.FixtureError(f"this sequence is already preserved as another crossing: {twins[0]}")
    out = Path(out_root) if out_root else RUN_ROOT / "fixtures" / fixture_id / utc_stamp()
    draft_dir = Path(meta.get("path") or ".").resolve()
    draft_dir = draft_dir if draft_dir.is_dir() else draft_dir.parent
    if out.resolve() == draft_dir or draft_dir in out.resolve().parents:
        raise fx.FixtureError(f"verification output {out} would be inside the draft's directory {draft_dir}")
    refuse_recording_dir(out, "verification output")
    refuse_recording_dir(fixture_dir, "fixture directory")
    report = verify(seq, out, capture_trajectory_digest=capture_digest)
    problems = source_problems + [n for n, c in report["checks"].items()
                                  if not c["ok"] and n not in INFORMATIONAL_CHECKS]
    if not report["user_config_unchanged"] or report["leftover_battleship"]:
        problems.append("user configuration changed or processes leaked")
    captured_cfg = (session_capture.get("gameplay_config") or {}).get("effective_gameplay_cvars")
    if captured_cfg is not None and captured_cfg != report["gameplay_config"]["effective_gameplay_cvars"]:
        problems.append(f"gameplay settings changed since the capture: {captured_cfg} -> "
                        f"{report['gameplay_config']['effective_gameplay_cvars']}")
    route = fx.route_assessment(crossing, report["evidence"], fx.decode_stage_geometry())
    report["build"] = {"fixture_id": fixture_id, "declared_crossing": crossing, "problems": problems, "route": route,
                       "draft_preserved": portable_path(meta.get("path"))}
    if problems and report["crossed"]:
        report["build"]["note"] = ("the reference replay DID enter the left region, but the crossing failed a hard gate "
                                   "(see problems), so it is not a fixture; the capture recording is untouched")
    elif not problems:
        report["build"]["note"] = ("genuine crossing: written as declared" + (
            "; the route classification needs review (not relabelled)" if route["review_required"] else
            "; route confirmed by the classifier"))
    write_json(out / "verification.json", report)
    if problems:
        return None, report
    draft_source = dict(draft.get("source") or {})
    if draft_source.get("note"):
        draft_source["draft_note"] = draft_source.pop("note")
    if isinstance(draft_source.get("resumed_from"), dict):
        draft_source["resumed_from"] = {**draft_source["resumed_from"],
                                        "path": portable_path(draft_source["resumed_from"].get("path"))}
    if isinstance(draft_source.get("imported_from"), dict):
        draft_source["imported_from"] = {k: v for k, v in draft_source["imported_from"].items() if k != "document"}
        draft_source["imported_from"]["path"] = portable_path(draft_source["imported_from"].get("path"))
    doc = {"contract": fx.FIXTURE_CONTRACT, "fixture_id": fixture_id, "crossing": crossing,
           "source": {**draft_source, "kind": source_kind, "draft": portable_path(meta.get("path")), "note": note},
           "task": dict(fx.TASK), "action_contract": fx.track1_contract(),
           "start": {"tick": 0, "reset": "fresh_process", "hidden_prefix": False},
           "sequence": {"length": len(seq), "track1": [list(a) for a in seq], "native": [list(r) for r in rows],
                        "track1_digest": fx.track1_digest(seq), "native_action_digest": nad},
           "provenance": {"executable_sha256": report["executable_sha256"], "revisions": report["revisions"],
                          "verified_utc": report["utc"], "verification_dir": portable_path(out),
                          "user_config": report["gameplay_config"],
                          "capture": {k: session_capture.get(k) for k in ("trajectory_digest", "mode", "realtime",
                                                                          "started_utc", "gameplay_config")}
                          if session_capture else None},
           "geometry": report["geometry"], "evidence": report["evidence"], "route": route,
           "verification": {"count": report["executions"], "all_identical": report["replay_ok"],
                            "runs": {n: {k: r.get(k) for k in ("submitted", "trajectory_digest",
                                                                "policy_obs_v1_digest", "returns", "startup_mode")}
                                     for n, r in report["runs"].items()},
                            "checks": {n: c["ok"] for n, c in report["checks"].items()}},
           "usage_restrictions": fx.USAGE_RESTRICTIONS}
    doc_problems = fx.validate_fixture_document(doc)
    if doc_problems:
        report["build"]["problems"] = doc_problems
        write_json(out / "verification.json", report)
        return None, report
    twins = [p for c in fx.CROSSINGS if c != crossing for p in [fixture_dir / f"{c}_{nad[:12]}.json"] if p.exists()]
    if twins:  # re-checked at write time: a concurrent build of the other crossing may have finished meanwhile
        raise fx.FixtureError(f"this sequence was preserved as another crossing during verification: {twins[0]}")
    write_json_exclusive(path, doc)
    return path, report


# -- CLI --------------------------------------------------------------------------------------------------

def _load_rows(source: Path, allow_non_track1: bool) -> Tuple[List[Row], Dict[str, Any]]:
    try:
        seq, meta = fx.load_sequence(source)
        return fx.track1_to_native(seq), {**meta, "track1": True}
    except fx.FixtureError as exc:
        if not allow_non_track1:
            raise
        rows: List[Row]
        if source.suffix.lower() == ".btti":
            from btti_replay import read_btti_rows

            rows = [(r.buttons, r.stick_x, r.stick_y) for r in read_btti_rows(str(source))]
        elif source.is_dir():
            from run_artifacts import read_artifact

            rows = [(a.buttons, a.stick_x, a.stick_y) for a in read_artifact(source).actions]
        else:
            raise
        return rows, {"path": str(source), "track1": False, "non_track1_rows": fx.non_track1_rows(rows),
                      "note": f"NOT a fixture candidate: {exc}"}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evidence", help="replay any sequence once and print native crossing evidence")
    e.add_argument("source", type=Path)
    e.add_argument("--mode", default="no_render_raphnet", choices=sorted(MODES))
    e.add_argument("--allow-non-track1", action="store_true",
                   help="replay raw native rows (e.g. the TAS as a detector control); never a fixture")
    e.add_argument("--out", type=Path)
    v = sub.add_parser("verify", help="run the verification matrix (no fixture is written)")
    v.add_argument("source", type=Path)
    v.add_argument("--out", type=Path)
    v.add_argument("--quick", action="store_true")
    b = sub.add_parser("build", help="verify a draft; write a fixture for a genuine reproducible crossing (exit 0 "
                                     "route confirmed, 3 route needs review, 1 no fixture)")
    b.add_argument("draft", type=Path)
    b.add_argument("--crossing", required=True, choices=fx.CROSSINGS)
    b.add_argument("--source", required=True, choices=fx.SOURCES)
    b.add_argument("--note", default="")
    c = sub.add_parser("check-fixture", help="document-level validation of a fixture file (no game)")
    c.add_argument("fixture", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "check-fixture":
        doc = json.loads(args.fixture.read_text(encoding="utf-8"))
        problems = fx.validate_fixture_document(doc)
        print(json.dumps({"fixture": str(args.fixture), "valid": not problems, "problems": problems}, indent=1))
        return 0 if not problems else 1
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    leaked = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
    if leaked:
        raise SystemExit(f"SSB64_* variables in the environment would leak into the child: {leaked}")
    if args.cmd == "evidence":
        rows, meta = _load_rows(args.source, args.allow_non_track1)
        out = args.out or RUN_ROOT / "evidence" / f"{utc_stamp()}_{args.source.stem}"
        if out.exists() and any(out.iterdir()):
            raise SystemExit(f"output directory exists and is not empty: {out}")
        refuse_recording_dir(out, "evidence output")
        tr = replay(rows, out / "work", mode=args.mode)
        write_gz(out / "trace.json.gz", tr)
        geo = fx.decode_stage_geometry()
        ev = fx.crossing_evidence(geo, tr["initial"], tr["steps"], submitted=tr["submitted"])
        rec = {"source": meta, "mode": args.mode, "submitted": tr["submitted"], "unsent": tr["unsent"],
               "problems": tr["problems"], "result": tr["result"], "evidence": ev,
               "classification": fx.classify_crossing(ev, geo), "summary": _summary(tr)}
        if args.source.is_dir():  # a historical artifact: the replay must reproduce what was recorded
            from run_artifacts import read_artifact

            md = read_artifact(args.source).metadata
            final = {k: v for k, v in (md.get("final_observation") or {}).items() if k != "host_frame"}
            got = {k: v for k, v in (tr["steps"][-1]["observation"] if tr["steps"] else {}).items() if k != "host_frame"}
            rec["reproduction"] = {"recorded_native_action_digest": meta.get("recorded_native_action_digest"),
                                   "replay_action_digest": tr["action_digest"],
                                   "digest_matches": meta.get("recorded_native_action_digest") == tr["action_digest"],
                                   "final_observation_matches": final == got, "recorded_final": final,
                                   "replayed_final": got}
            print(json.dumps({k: v for k, v in rec["reproduction"].items() if "final" not in k or k.endswith("matches")},
                             indent=1))
        write_json(out / "evidence.json", rec)
        print(json.dumps({k: rec[k] for k in ("source", "submitted", "problems", "classification")}, indent=1))
        print(json.dumps({k: ev[k] for k in ("crossed", "first_left_entry", "min_x", "max_y", "approach_surface",
                                             "crossing_path", "terminal")}, indent=1))
        if ev["targets"]:
            print("targets broken:", ev["targets"]["broken_ids"], "after crossing:",
                  ev["targets"]["broken_after_first_left_entry"], "diag_ok:", ev["targets"]["diag_ok"])
        print(f"-> {out / 'evidence.json'}")
        return 0 if not tr["problems"] else 1
    if args.cmd == "verify":
        seq, _meta = fx.load_sequence(args.source)
        out = args.out or RUN_ROOT / "verify" / f"{utc_stamp()}_{args.source.stem}"
        rep = verify(seq, out, quick=args.quick)
        for n, c in rep["checks"].items():
            print(f"{'PASS' if c['ok'] else 'FAIL'}  {n}")
        print(f"replay_ok={rep['replay_ok']} crossed={rep['crossed']} classification={rep['classification']}")
        print(f"-> {out / 'verification.json'}")
        return 0 if rep["replay_ok"] else 1
    path, rep = build_fixture(args.draft, args.crossing, args.source, note=args.note)
    b = rep["build"]
    route = b["route"]
    print(f"route: declared {route['declared']}, classifier {route['classifier']['identity']!r} "
          f"({route['classifier']['reason']}), agreement {route['agreement']}; takeoff {route['takeoff']}")
    if path is None:
        print("NO FIXTURE WRITTEN:", json.dumps(b["problems"], indent=1))
        if b.get("note"):
            print(b["note"])
        print(f"the draft is untouched: {b['draft_preserved']}")
        return EXIT_NO_FIXTURE
    if route["review_required"]:
        print("FIXTURE WRITTEN AS DECLARED, ROUTE CLASSIFICATION NEEDS REVIEW (not relabelled):")
        for n in route["notes"]:
            print(f"  - {n}")
        print(f"fixture: {path}")
        return EXIT_FIXTURE_REVIEW
    print(f"fixture written (route confirmed): {path}")
    return EXIT_FIXTURE_CONFIRMED


if __name__ == "__main__":
    sys.exit(main())
