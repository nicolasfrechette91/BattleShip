"""M9-g3 run engine: open / P1 / P2 / T0 (the reused tape verified at the open and the drift check) / training / close audit / verification / close for one
session of the g3 line.

rl/m9_g2_run.G2Session, extended: P1, P2, the verification tiers, the clock, the pools, the partial records and the close checks are inherited unchanged.
Overridden: the open (the reused tape baseline is copied into input/, its file sha256, its content digest, every landing's pin and the executable pin are
verified; a resumed session as g2), T0 (no measurement: the drift check, g2 proposal 5.3 item 3), training (the g3 frontier, recorder and driver), the
close audit (g3 keys), the close (the g3 rules, the final-state record with the g3 line contract). The same engine runs against the real game or the
synthetic stand-in. A cap or memory stop ends the session INCOMPLETE; an integrity failure ends it INVALID with no retry; a stop keeps everything written
and relaunches nothing.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import m9_artifacts as A
import m9_contract as C
import m9_g2_arena as AR
import m9_g2_resume as RS
import m9_g2_run as RUN2
import m9_g2_tape as TP
import m9_g3_contract as G
import m9_g3_frontier as F
import m9_g3_probe as PR
import m9_g3_report as RPT
import m9_g3_rule as R
import m9_g3_train as TR
import m9_vec as V

RUN_CONTRACT = "m9_g3_run_v1"
G3Hooks = RUN2.G2Hooks
worker_ticks = RUN2.worker_ticks


@dataclass
class G3Config(RUN2.G2Config):
    wall_caps_s: Mapping[str, float] = field(default_factory=lambda: dict(G.WALL_CAPS_S))
    tick_caps: Mapping[str, int] = field(default_factory=lambda: dict(G.TICK_CAPS))
    tape_reuse: Optional[Mapping[str, Any]] = None        # s1: {path, file_sha256, content_sha256, executable_sha256 (optional)}; a resumed session reads input/ as g2
    tape_source_records: Optional[Path] = None            # the measuring session's T0 records (read-only), for the drift check's native action digests
    drift_landing: int = G.DRIFT_LANDING
    drift_keys: int = G.DRIFT_KEYS


class G3Session(RUN2.G2Session):
    def __init__(self, cfg: G3Config, env: RUN2.RUN.RunEnv, hooks: G3Hooks):
        super().__init__(cfg, env, hooks)
        self.cfg: G3Config = cfg
        self.drift_records: List[Dict[str, Any]] = []
        self.tape_reuse_record: Optional[Dict[str, Any]] = None

    # -- recording (the g3 scope) --

    def put(self, name: str, obj: Mapping[str, Any]) -> None:
        A.write_json(self.dir / f"{name}.json", A.stamp(dict(obj, scope=G.SCOPE, session=self.cfg.session, gate=G.GATE, line_id=G.LINE_ID)))

    def save_state(self, **extra: Any) -> None:
        try:
            fr = self.frontier
            A.write_json(self.dir / "state.json", A.stamp(dict({"utc": A.utc(), "phase": self.clock.phase, "phases": dict(self.phases), "clock": self.clock.to_json(), "invalid": list(self.invalid),
                                                                "scope": G.SCOPE, "gate": G.GATE, "session": self.cfg.session, "pointer": fr.pointer if fr else None,
                                                                "spacing": fr.spacing_state() if fr else None}, **extra)))
        except (OSError, A.ArtifactError):
            pass

    # -- open --

    def open(self) -> bool:
        cfg = self.cfg
        rec: Dict[str, Any] = {"utc": A.utc(), "session": cfg.session, "pins": dict(self.env.identity_now()) if self.env.identity_now else None, "line_contract_sha256": G.line_contract_digest(),
                               "contract_sha256": G.contract_digest(), "rules": {"frontier": G.FRONTIER_RULE_ID, "frontier_sha256": F.contract_digest(), "tape": G.TAPE_RULE_ID, "s1": R.s1_rule_digest(),
                                                                                "line": R.line_rule_digest()},
                               "caps": {"wall_caps_s": dict(cfg.wall_caps_s), "tick_caps": dict(cfg.tick_caps), "transition_cap": cfg.transition_cap, "global_cap_s": cfg.global_cap_s},
                               "spacing_rule": {"unit": G.SPACING_UNIT, "cap": G.SPACING_CAP}, **dict(cfg.open_record)}
        pins_now = dict(rec["pins"] or {})
        if self.env.pins:
            diffs = sorted(k for k, v in dict(self.env.pins).items() if k in pins_now and pins_now.get(k) != v)
            if diffs:
                raise V.IntegrityStop("pin drift at the open (the executable, the runtime files or the frozen configuration)", {"diffs": diffs})
        if cfg.resume is not None:
            fs = dict(cfg.resume["final_state"])
            try:
                copied = RS.copy_inputs(fs, self.root / "input", expect=dict(cfg.resume["expect"]))
            except RS.ResumeError as exc:
                raise V.IntegrityStop("resume refused: an input differs from the approved digests", {"problem": str(exc)[:400]})
            cs = A.read_json(self.root / "input" / "curriculum_state.json")
            probs = RS.check_resume_compat(cs, line_contract_sha256=G.line_contract_digest(), executable_sha256=pins_now.get("executable_sha256"), saved_executable=fs.get("executable_sha256"), ppo=G.PPO)
            if cs.get("frontier_rule") != G.FRONTIER_RULE_ID:
                probs.append(f"the saved frontier rule {cs.get('frontier_rule')!r} is not {G.FRONTIER_RULE_ID}")
            if probs:
                raise V.IntegrityStop("resume refused", {"problems": probs})
            self.carried = dict(cs["carried"])
            self.tape_pinned = A.read_json(self.root / "input" / "tape_baseline.json")
            if TP.table_digest(self.tape_pinned) != self.tape_pinned.get("sha256") or not self.tape_pinned.get("pinned"):
                raise V.IntegrityStop("the pinned tape table's content digest differs or the table is not pinned", {"sha256": self.tape_pinned.get("sha256")})
            self.resumed = True
            rec["resume"] = {"inputs": copied, "carried_state": self.carried, "saved_counters": fs.get("counters"), "previous_sessions": list(cfg.resume.get("previous_sessions") or []),
                             "tape_baseline_sha256": self.tape_pinned.get("sha256")}
        else:
            if cfg.tape_reuse is None:
                raise V.IntegrityStop("no tape baseline: s1 reuses g2-s1's pinned table by digest (decision 7); nothing is measured", {})
            self.tape_reuse_record = self._reuse_tape(cfg.tape_reuse, executable_now=pins_now.get("executable_sha256"))
            rec["tape_reuse"] = self.tape_reuse_record
        self.put("open", rec)
        return True

    def _reuse_tape(self, spec: Mapping[str, Any], *, executable_now: Optional[str]) -> Dict[str, Any]:
        """Decision 7: the reused pinned table is copied into input/ and verified: file sha256 (source and copy), content digest, every landing pinned with a bar,
        the registered key counts, the label family, the lineage, sticky p, and the executable it was measured with equals the executable now."""
        src = Path(spec["path"])
        dest = self.root / "input"
        dest.mkdir(parents=True, exist_ok=False)
        problems: List[str] = []
        if not src.is_file():
            raise V.IntegrityStop("the reused tape baseline is missing", {"path": str(src)})
        got_src = RS.sha256_file(src)
        shutil.copyfile(src, dest / "tape_baseline.json")
        got = RS.sha256_file(dest / "tape_baseline.json")
        if not (got == got_src == spec.get("file_sha256")):
            problems.append(f"file sha256 {got[:16]} (source {got_src[:16]}) differs from the registered {str(spec.get('file_sha256'))[:16]}")
        table = A.read_json(dest / "tape_baseline.json")
        if TP.table_digest(table) != table.get("sha256"):
            problems.append("the table's content digest differs from its content")
        if table.get("sha256") != spec.get("content_sha256"):
            problems.append(f"content digest {str(table.get('sha256'))[:16]} differs from the registered {str(spec.get('content_sha256'))[:16]}")
        if not table.get("pinned") or any(not v.get("pinned") or v.get("B") is None for v in dict(table.get("landings") or {}).values()):
            problems.append("not every landing of the table is pinned with a bar")
        keys = {int(k): int(v.get("keys", 0)) for k, v in dict(table.get("landings") or {}).items()}
        want_keys = {int(k): int(v) for k, v in dict(self.cfg.tape_keys).items()}          # the registered 200 / 40 in production; a synthetic test may use fewer
        if keys != want_keys:
            problems.append(f"the table's key counts {keys} differ from the registered {want_keys}")
        if table.get("label") != G.KEYS["reach_label"] or table.get("lineage") != G.TRUNK or table.get("sticky_p") != G.STICKY_P:
            problems.append("the table's label family, lineage or sticky p differs from the registered")
        exe_meas = spec.get("executable_sha256")
        if exe_meas is not None:
            if executable_now is None:
                problems.append("the executable pin could not be read at the open")
            elif exe_meas != executable_now:
                problems.append("the executable differs from the one the table was measured with")
        if problems:
            raise V.IntegrityStop("the reused tape baseline failed its verification at the open", {"problems": problems})
        self.tape_pinned = table
        return {"source": str(src), "copy": str(dest / "tape_baseline.json"), "file_sha256": got, "content_sha256": table["sha256"], "pinned": True,
                "bars": {k: v["B"] for k, v in table["landings"].items()}, "p_hat": {k: v["p_hat"] for k, v in table["landings"].items()},
                "measured_with_executable_sha256": exe_meas, "executable_now": executable_now, "keys": keys}

    # -- T0: the drift check of the reused tape --

    def _source_tape_digests(self) -> Dict[str, str]:
        p = self.cfg.tape_source_records
        if p is None or not Path(p).is_file():
            return {}
        out: Dict[str, str] = {}
        for r in A.read_jsonl(Path(p)):
            if int(r.get("landing", -1)) == int(self.cfg.drift_landing) and int(r.get("k", -1)) < int(self.cfg.drift_keys):
                out[f"t0_tape-{int(r['landing'])}-{int(r['k']):03d}"] = str(r.get("native_action_digest"))
        return out

    def t0(self) -> bool:
        """No measurement (decision 7). The drift check: the first DRIFT_KEYS tape keys at 2,128, on the reused table's own labels, must reproduce the table's
        recorded outcomes (and the measuring session's native action digests where its records are given). A difference is INVALID."""
        cfg, env = self.cfg, self.env
        if self.tape_pinned is None:
            raise V.IntegrityStop("no pinned tape table at T0", {})
        jobs = PR.drift_jobs(cfg.drift_landing, cfg.drift_keys)
        budget = AR.G2TickBudget(int(cfg.tick_caps["t0"]))
        rec = PR.ProbeRecorder(self.root / "t0" / "drift.jsonl", phase="t0_drift", now=env.now, artifacts_root=(self.root / "artifacts") if cfg.write_artifacts else None, artifacts_for="all")
        with self.pool("t0", C.FLAGS_EVAL) as pool:
            arena = AR.G2Arena(pool, self.tables, PR.ProbeSource(jobs), budget, now=env.now, guard=self.clock.check, log=env.log)
            runner = PR.ProbeRunner(arena, self.tables, rec, policy=None, tests=None, now=env.now, flatten=self.hooks.flatten)
            res = runner.run()
            arena.wait_settled()
            res["worker_ticks"] = worker_ticks(pool)
        self.drift_records = rec.records
        complete = len(rec.records) == len(jobs) and res["stop"] is None
        expected = dict(self.tape_pinned["landings"][str(int(cfg.drift_landing))]["outcomes"])
        src_digests = self._source_tape_digests()
        rows: List[Dict[str, Any]] = []
        problems: List[str] = []
        for r in sorted(rec.records, key=lambda x: int(x["k"])):
            k = int(r["k"])
            eid = f"t0_tape-{int(cfg.drift_landing)}-{k:03d}"
            want = expected.get(str(k))
            got = "c" if r["clear"] else str(r["end_reason"])[0]
            srd = src_digests.get(eid)
            rows.append({"k": k, "episode": r["episode"], "label": r["label"], "outcome": got, "expected": want, "end_reason": r["end_reason"], "ticks": r["ticks"], "native_action_digest": r["native_action_digest"],
                         "source_native_action_digest": srd})
            if want != got:
                problems.append(f"key {k}: outcome {got!r} differs from the table's {want!r}")
            if srd is not None and srd != r["native_action_digest"]:
                problems.append(f"key {k}: the native action digest differs from the measuring session's record")
        self.put("t0", {"ok": complete and not problems, "reused": True, "measured": False, "tape_baseline_sha256": self.tape_pinned.get("sha256"),
                        "drift": {"landing": int(cfg.drift_landing), "keys": int(cfg.drift_keys), "planned": len(jobs), "episodes": len(rec.records), "rows": rows, "problems": problems,
                                  "source_records": str(cfg.tape_source_records) if cfg.tape_source_records else None}, "run": res,
                        "note": "the tape baseline is g2-s1's pinned table, verified by digest at the open; T0 is the drift check only, never a measurement"})
        if res["stop"] is not None and not complete:
            raise V.CapStop(f"the drift check stopped before completion: {res['stop']['reason']}", valid=False)
        if problems:
            raise V.IntegrityStop("tape drift: the reused table does not reproduce", {"problems": problems})
        return complete

    # -- training --

    def train(self) -> bool:
        cfg, env, hooks = self.cfg, self.env, self.hooks
        n_active, n_staging = G.SPLIT
        Vec = V.make_vec_env_class()
        lengths = {n: len(t.words) for n, t in self.tables.items()}
        fr = F.Frontier(lengths, session=cfg.session, landings=cfg.landings, state=self.carried)
        self.frontier = fr
        run_dir = self.root / "training"
        run_dir.mkdir(parents=True, exist_ok=True)
        budget = AR.G2TickBudget(int(cfg.tick_caps["train"]))
        rec = TR.G3TrainRecorder(run_dir, fr, self.tables, session=cfg.session, now=env.now, write_artifacts=cfg.write_artifacts, first_clears=cfg.first_clears)
        tape_sha = (self.tape_pinned or {}).get("sha256")
        with self.pool("train", C.FLAGS_TRAIN) as pool:
            arena = AR.G2Arena(pool, self.tables, TR.TrainSource(fr, first_episode=fr.next_episode), budget, now=env.now, guard=self.clock.check, log=env.log)
            vec = Vec(arena, n_active, recorder=rec.on_episode, outcome=rec.on_outcome)
            if self.resumed:
                model = hooks.resume_model(self.root / "input" / "model.zip", vec, n_active, cfg.session)
            else:
                model = env.make_model(vec, n_active)
            try:
                stop = TR.train(model, vec, arena, fr, rec, run_dir=run_dir, guard=self.clock.check, now=env.now, session=cfg.session, pool=pool, tables=self.tables, lengths=lengths,
                                snapshot_of=hooks.snapshot_of, make_policy=hooks.make_probe_policy, log=env.log, transition_cap=cfg.transition_cap, tape_table_sha256=tape_sha,
                                artifacts_root=(self.root / "artifacts") if cfg.write_artifacts else None, flatten=hooks.flatten, checkpoint_every=cfg.checkpoint_every, resumed=self.resumed,
                                extra_meta={"split": [n_active, n_staging]})
            except Exception as exc:                                   # noqa: BLE001 - recorded (a software error), then re-raised
                try:
                    self.put("training_summary", {"valid_end": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}", "split": [n_active, n_staging], "pointer_final": fr.pointer,
                                                  "frontier": fr.state(), "arena": arena.summary()})
                except Exception:                                      # noqa: BLE001
                    pass
                raise
            arena.close_unfinished()
            arena.wait_settled(use_guard=False, max_wall_s=120.0)
            sm = arena.summary()
            sm["worker_ticks"] = worker_ticks(pool)
        self.train_first_clears = list(rec.first_clears)
        self.train_stop = stop
        summary = {"stop": {k: v for k, v in stop.items() if k not in ("checkpoints", "detail", "attempts")}, "valid_end": stop["valid_end"], "split": [n_active, n_staging], "pointer_final": fr.pointer,
                   "spacing_final": fr.spacing_state(), "deferred_triggers": fr.deferred, "attempts_per_pointer": {str(k): v for k, v in sorted(fr.line_failed.items())},
                   "moves": fr.moves, "attempts": [fr._attempt_summary(a) | {"spacing": a.get("spacing")} for a in fr.attempts], "frontier": fr.state(), "recorder": rec.summary(), "arena": sm,
                   "checkpoints": stop.get("checkpoints"), "final_checkpoint": stop.get("final"), "transitions": stop.get("transitions"), "ticks": stop.get("ticks"), "stale_events": arena.stale_events,
                   "resumed": self.resumed, "resumed_seed": stop.get("resumed_seed"), "entropy_note": "per-rollout entropy and explained variance are in training/rollouts.jsonl"}
        self.put("training_summary", summary)
        A.write_json(run_dir / "checkpoints.json", A.stamp({"checkpoints": stop.get("checkpoints"), "final": stop.get("final")}))
        if stop.get("integrity"):
            raise V.IntegrityStop(str(stop["reason"]), stop.get("detail") or {})
        if not stop["valid_end"]:
            raise V.CapStop(f"training stopped early: {stop['reason']}", valid=False)
        return True

    # -- the close audit --

    def audit(self) -> bool:
        cfg, env, hooks = self.cfg, self.env, self.hooks
        pointer = self.frontier.pointer if self.frontier is not None else G.TAU0
        landings = F.audit_landings(pointer, cfg.landings)
        self.audit_landings = landings
        final_zip = self.root / "training" / "checkpoints" / "final" / "model.zip"
        policy = hooks.audit_policy(final_zip)
        jobs = PR.audit_jobs(landings, n=cfg.audit_n, n_unp=cfg.audit_unp, n_det=cfg.audit_det, tick0_n=cfg.tick0_n)
        budget = AR.G2TickBudget(int(cfg.tick_caps["audit"]))
        rec = PR.ProbeRecorder(self.root / "audit" / "episodes.jsonl", phase="audit", now=env.now, artifacts_root=(self.root / "artifacts") if cfg.write_artifacts else None, artifacts_for="all")
        with self.pool("audit", C.FLAGS_EVAL) as pool:
            arena = AR.G2Arena(pool, self.tables, PR.ProbeSource(jobs), budget, now=env.now, guard=self.clock.check, log=env.log)
            runner = PR.ProbeRunner(arena, self.tables, rec, policy=policy, tests=None, now=env.now, flatten=hooks.flatten)
            res = runner.run()
            arena.wait_settled(use_guard=False, max_wall_s=120.0)
            res["worker_ticks"] = worker_ticks(pool)
        self.audit_records, self.audit_clears = rec.records, rec.clears
        self.notes["audit"] = {"planned": len(jobs), "completed": len(rec.records), "stop": res["stop"], "landings": landings, "pointer_final": pointer}
        self.put("audit_run", {"run": res, "planned": len(jobs), "completed": len(rec.records), "landings": landings, "pointer_final": pointer, "policy_sha256": getattr(policy, "sha256", None),
                               "policy_decisions": getattr(policy, "decisions", None), "sticky_labels": G.KEYS["reach_label"], "action_keys": G.KEYS["audit_action"]})
        if res["stop"] is not None and not res["stop"]["valid"]:
            raise V.CapStop(f"the close audit stopped early: {res['stop']['reason']}", valid=False)
        return True

    # -- the decision --

    def finish(self) -> Dict[str, Any]:
        env = self.env
        close: Dict[str, Any] = {"phase": "close"}
        self.clock.phase = None
        t_close = env.now()
        try:
            if env.earlier_trees is not None:
                et = dict(env.earlier_trees())
                close["earlier_trees"] = et
                if not et.get("ok"):
                    self.invalid.append(f"a protected tree no longer equals its D: increment: {et.get('problems')}")
            if env.identity_now is not None:
                idn = dict(env.identity_now())
                close["identity"] = idn
                diffs = {k: (idn.get(k), v) for k, v in dict(env.pins).items() if k in idn and idn.get(k) != v}
                if diffs:
                    self.invalid.append(f"pin drift at the close: {sorted(diffs)}")
            v = list(env.provenance_violations())
            close["provenance_violations"] = v
            if v:
                self.invalid.append(f"provenance or write-guard violations: {v[:3]}")
            aud = A.audit_tree(self.root, skip_dirs=("workers", "vw", "input"))
            close["metadata_audit"] = {"files": aud["files"], "jsonl_lines": aud["jsonl_lines"], "failures": aud["failures"][:10], "ok": aud["ok"]}
            if not aud["ok"]:
                self.invalid.append(f"artifacts without the task block or created_utc: {aud['failures'][:3]}")
            if env.leftover_processes is not None:
                close["leftover_battleship_processes"] = env.leftover_processes()
        except Exception as exc:                                       # noqa: BLE001
            close["error"] = f"{type(exc).__name__}: {exc}"
            self.invalid.append(f"a close check failed to run: {close['error']}")
        facts = self.facts()
        facts["invalid"] = list(self.invalid)
        out = R.apply_s1(facts)
        out["stop"] = self.stop
        out["facts"] = {k: v for k, v in facts.items() if k != "invalid"}
        out["clock"] = self.clock.to_json()
        out["session"] = self.cfg.session
        fr = self.frontier
        out["frontier"] = {"pointer_final": fr.pointer if fr else None, "spacing_final": fr.spacing_state() if fr else None, "attempts": len(fr.attempts) if fr else 0,
                           "attempts_per_pointer": {str(k): v for k, v in sorted(fr.line_failed.items())} if fr else {}, "deferred_triggers": fr.deferred if fr else 0,
                           "note": "reported only: no attempt count decides anything"}
        prev = list((self.cfg.resume or {}).get("previous_sessions") or [])
        this = {"k": self.cfg.session, "outcome": out["outcome"], "D": out["D"], "R": out["R"], "train_fraction": facts["train_fraction"], "attempts": len(fr.attempts) if fr else 0,
                "failed_attempts": {str(k): v for k, v in sorted(fr.line_failed.items())} if fr else {}}
        line = R.apply_line(prev + [this])
        line.update({"sessions": prev + [this], "s2_permitted": line["outcome"] == "CONTINUE", "note": "nothing follows automatically; a next session needs its own approval; "
                                                                                                "no attempt count and no NULL s1 ends the line"})
        out["line"] = {k: line[k] for k in ("outcome", "reasons", "k", "s2_permitted")}
        final_dir = self.root / "training" / "checkpoints" / "final"
        if (final_dir / "model.zip").is_file() and (final_dir / "curriculum_state.json").is_file():
            try:
                tb = self.root / "input" / "tape_baseline.json"
                fs = RS.final_state_record(final_dir=final_dir, tape_baseline_path=tb, session=self.cfg.session, line_contract_sha256=G.line_contract_digest(),
                                           executable_sha256=(close.get("identity") or {}).get("executable_sha256"),
                                           extra={"outcome": out["outcome"], "line": out["line"], "gate": G.GATE, "frontier_rule": G.FRONTIER_RULE_ID, "spacing_final": fr.spacing_state() if fr else None})
                fs["sha256_of_this_record_excluded"] = True
                RS.write_final_state(self.dir / "final_state.json", fs)
                out["final_state"] = {k: fs[k] for k in ("model_zip", "curriculum_state", "tape_baseline", "counters")}
            except Exception as exc:                                   # noqa: BLE001
                out["final_state_error"] = f"{type(exc).__name__}: {exc}"
        close["wall_s"] = round(env.now() - t_close, 2)
        self.put("close", close)
        self.put("rule", out)
        self.put("line", line)
        self.save_state(done=True, outcome=out["outcome"], line=line["outcome"])
        return out


def budget_projection(wall_caps: Mapping[str, float] = G.WALL_CAPS_S, global_cap: float = G.GLOBAL_CAP_S) -> Dict[str, Any]:
    """The wall budget of one g3 session: every phase cap binding, the pool spawns and a grace per phase (pessimistic), and an expected case from g2-s1's
    measured phases (T0 replaced by the five-episode drift check; the close hashes seven protected trees). A projection, not a promise."""
    phases_sum = sum(wall_caps.values())
    pessimistic = phases_sum + G.POOL_SPAWNS * G.POOL_SPAWN_S + G.WALL_CAP_GRACE_S * len(wall_caps)
    expected = {"open": 20, "p1": 30, "p2": 40, "t0": 60, "train": 4800, "audit": 300, "verify": 300, "close": 180}
    return {"phase_caps_s": dict(wall_caps), "sum_of_caps_s": phases_sum, "pessimistic_total_s": pessimistic, "pessimistic_total_min": round(pessimistic / 60, 1), "global_cap_s": global_cap,
            "fits_global_cap_pessimistic": pessimistic <= global_cap, "slack_pessimistic_s": global_cap - pessimistic, "expected_total_s": sum(expected.values()), "expected_phases_s": expected,
            "expected_native_ticks": {"t0": 15_000, "train": 12_000_000, "audit": 450_000, "verify": 400_000},
            "note": "training ends by its 80-minute wall cap in every projection; T0 is the five-episode drift check (the tape is reused by digest); the session clock starts at the session object "
                    "and counts the pool spawns; the preflight (unit suite) runs before it"}
