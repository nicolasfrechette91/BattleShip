"""M9-g2 run engine: open / P1 / P2 / T0 / training / close audit / verification / close for one session of the g2 line.

Environment-injected like rl/m9_run (whose `Session` it extends: P1 and P2 are g1's methods, unchanged; the clock, the pools, the partial records and the
close checks are inherited). The same engine runs against the real game or the synthetic stand-in. Phases and caps are rl/m9_g2_contract's. A cap or memory
stop ends the session INCOMPLETE; an integrity failure ends it INVALID with no retry; a stop keeps everything written and relaunches nothing.

    open     identities, the approval copy and the pins (0 ticks); for a resumed session the input files, their digests and the carried state
    P1 / P2  g1's: both routes replayed three times each (tables registered); twelve keyed staging-equivalence starts
    T0       (s1) the tape baseline: 400 keyed open-loop episodes; the claimed table
    train    PPO under the controlled frontier (rl/m9_g2_train); attempts pause training at rollout boundaries
    audit    the frozen final policy at every landing from 2,128 to one beyond the frontier, keyed sampling; tick 0 descriptive
    verify   tier 0 = every audit sticky clear and every tape clear; tier 1 = 20 training clears; tier 2 = one keyed clear per passed test; tier 3 = diagnostics;
             then the pinned tape baseline
    close    pins, write guard, the six protected trees, the metadata audit, leftover processes; the s1 rule, the line rule, the final-state record
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import m9_artifacts as A
import m9_contract as C
import m9_g2_arena as AR
import m9_g2_contract as G
import m9_g2_frontier as F
import m9_g2_probe as PR
import m9_g2_report as RPT
import m9_g2_resume as RS
import m9_g2_rule as R
import m9_g2_tape as TP
import m9_g2_train as TR
import m9_lineages as L
import m9_run as RUN
import m9_vec as V
import m9_verify as VF

RUN_CONTRACT = "m9_g2_run_v1"


@dataclass
class G2Config(RUN.RunConfig):
    session: int = 1
    wall_caps_s: Mapping[str, float] = field(default_factory=lambda: dict(G.WALL_CAPS_S))
    tick_caps: Mapping[str, int] = field(default_factory=lambda: dict(G.TICK_CAPS))
    global_cap_s: float = G.GLOBAL_CAP_S
    transition_cap: int = G.TRANSITION_CAP
    verify_threads: int = G.VERIFY_THREADS
    tape_keys: Mapping[int, int] = field(default_factory=lambda: dict(G.TAPE_KEYS))
    audit_n: int = G.AUDIT_EPISODES
    audit_unp: int = G.AUDIT_UNPERTURBED
    audit_det: int = G.AUDIT_DETERMINISTIC
    tick0_n: int = G.TICK0_EPISODES
    first_clears: int = G.FIRST_CLEARS_VERIFIED
    resume: Optional[Mapping[str, Any]] = None            # {final_state: record, expect: {model_zip, curriculum_state, tape_baseline}, previous_sessions: [...]}
    open_record: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class G2Hooks:
    """What the g2 session needs beyond rl/m9_run.RunEnv: the frozen snapshots, the probe and audit policies, the resume loader."""

    snapshot_of: Callable[[Any], Callable[[Path], Dict[str, Any]]]
    make_probe_policy: Callable[[Path, str], Any]
    audit_policy: Callable[[Path], Any]
    resume_model: Callable[[Path, Any, int, int], Any]
    flatten: Callable[[Mapping[str, Any]], Any]


class G2Clock(RUN.Clock):
    """g1's clock with the g2 phase names: a wall cap in training or in the close audit is a registered valid end."""

    def check(self) -> None:
        if self.elapsed() > self.cfg.global_cap_s:
            raise V.CapStop(f"session hard cap reached ({self.elapsed():.0f} s > {self.cfg.global_cap_s:.0f} s) in phase {self.phase}", valid=False)
        s = self.env.sampler
        if s is not None:
            if getattr(s, "breach", None):
                raise V.CapStop(str(s.breach), valid=False)
            last = getattr(s, "last", None)
            if last is not None and int(last.get("battleship", 0)) > self.cfg.max_battleship_processes:
                seq = last.get("seq")
                if not self._over or self._over[-1] != seq:
                    self._over.append(seq)
                if len(self._over) >= 2:
                    raise V.CapStop(f"more than {self.cfg.max_battleship_processes} BattleShip processes ({last.get('battleship')})", valid=False)
            elif last is not None:
                self._over = []
        self._n += 1
        if self.env.private_mb is not None and self._n % 64 == 0:
            mb = self.env.private_mb()
            if mb is not None:
                self.peak_mb = max(self.peak_mb, mb)
                if mb > self.cfg.memory_caps_mb["main_private"]:
                    raise V.CapStop(f"memory cap: main process private {mb:.0f} MB > {self.cfg.memory_caps_mb['main_private']} MB", valid=False)
        if self.phase is not None and self.phase_elapsed() > self.cfg.wall_caps_s[self.phase]:
            raise V.CapStop(f"wall cap of phase {self.phase} reached ({self.phase_elapsed():.0f} s > {self.cfg.wall_caps_s[self.phase]:.0f} s)", valid=self.phase in ("train", "audit"))


def worker_ticks(pool: Any) -> Dict[str, Any]:
    """The workers' own native-tick counts (prefix replays and steps, every job of the pool's phase), a cross-check of the arena's budget accounting."""
    try:
        reps = pool.reports()
    except Exception as exc:                                       # noqa: BLE001 - a report is a cross-check, never a stop
        return {"error": f"{type(exc).__name__}: {exc}"}
    stats = [dict((r or {}).get("stats") or {}) for r in reps]
    return {"native_ticks": sum(int(x.get("native_ticks", 0)) for x in stats), "staged": sum(int(x.get("staged", 0)) for x in stats),
            "episodes": sum(int(x.get("episodes", 0)) for x in stats), "workers_reporting": sum(1 for x in stats if x)}


class G2Session(RUN.Session):
    def __init__(self, cfg: G2Config, env: RUN.RunEnv, hooks: G2Hooks):
        super().__init__(cfg, env)
        self.cfg: G2Config = cfg
        self.hooks = hooks
        self.clock = G2Clock(env, cfg)
        self.frontier: Optional[F.Frontier] = None
        self.t0_records: List[Dict[str, Any]] = []
        self.t0_clears: List[Dict[str, Any]] = []
        self.t0_claimed: Optional[Dict[str, Any]] = None
        self.audit_records: List[Dict[str, Any]] = []
        self.audit_clears: List[Dict[str, Any]] = []
        self.audit_landings: List[int] = []
        self.tape_pinned: Optional[Dict[str, Any]] = None
        self.carried: Optional[Dict[str, Any]] = None
        self.resumed = False

    # -- recording (the g2 scope) --

    def put(self, name: str, obj: Mapping[str, Any]) -> None:
        A.write_json(self.dir / f"{name}.json", A.stamp(dict(obj, scope=G.SCOPE, session=self.cfg.session)))

    def save_state(self, **extra: Any) -> None:
        try:
            A.write_json(self.dir / "state.json", A.stamp(dict({"utc": A.utc(), "phase": self.clock.phase, "phases": dict(self.phases), "clock": self.clock.to_json(), "invalid": list(self.invalid),
                                                                "scope": G.SCOPE, "session": self.cfg.session, "pointer": self.frontier.pointer if self.frontier else None}, **extra)))
        except (OSError, A.ArtifactError):
            pass

    # -- the run --

    def run(self) -> Dict[str, Any]:
        self.dir.mkdir(parents=True, exist_ok=True)
        steps: List[Tuple[str, Callable[[], bool]]] = [("open", self.open), ("p1", self.p1), ("p2", self.p2), ("t0", self.t0), ("train", self.train), ("audit", self.audit), ("verify", self.verify)]
        try:
            for name, fn in steps:
                self.clock.begin(name)
                self.log(f"phase {name} begins (session clock {self.clock.elapsed():.0f} s)")
                self.save_state()
                ok = fn()
                self.clock.end()
                self.phases[name] = bool(ok)
                self.save_state()
                if not ok and name in ("open", "p1", "p2", "t0"):
                    self.stop = {"phase": name, "reason": f"{name.upper()} did not pass", "valid": False}
                    break
        except V.IntegrityStop as exc:
            self.invalid.append(f"{exc.why}: {json.dumps(exc.detail, default=str)[:400]}")
            self.stop = {"phase": self.clock.phase, "reason": f"INTEGRITY: {exc.why}", "valid": False}
        except V.CapStop as exc:
            self.stop = {"phase": self.clock.phase, "reason": exc.reason, "valid": exc.valid}
            self.log(f"stop in phase {self.clock.phase}: {exc.reason}")
        except Exception as exc:                                       # noqa: BLE001 - a software error: recorded, INCOMPLETE, never silent
            self.stop = {"phase": self.clock.phase, "reason": f"software error: {type(exc).__name__}: {exc}", "valid": False, "trace": traceback.format_exc()[-3000:]}
            self.log(f"software error in phase {self.clock.phase}: {exc}")
        finally:
            self.clock.end()
        return self.finish()

    # -- open --

    def open(self) -> bool:
        cfg = self.cfg
        rec: Dict[str, Any] = {"utc": A.utc(), "session": cfg.session, "pins": dict(self.env.identity_now()) if self.env.identity_now else None, "line_contract_sha256": G.line_contract_digest(),
                               "contract_sha256": G.contract_digest(), "rules": {"frontier": G.FRONTIER_RULE_ID, "tape": G.TAPE_RULE_ID, "s1": R.s1_rule_digest(), "line": R.line_rule_digest()},
                               "caps": {"wall_caps_s": dict(cfg.wall_caps_s), "tick_caps": dict(cfg.tick_caps), "transition_cap": cfg.transition_cap, "global_cap_s": cfg.global_cap_s}, **dict(cfg.open_record)}
        if cfg.resume is not None:
            fs = dict(cfg.resume["final_state"])
            try:
                copied = RS.copy_inputs(fs, self.root / "input", expect=dict(cfg.resume["expect"]))
            except RS.ResumeError as exc:
                raise V.IntegrityStop("resume refused: an input differs from the approved digests", {"problem": str(exc)[:400]})
            cs = A.read_json(self.root / "input" / "curriculum_state.json")
            probs = RS.check_resume_compat(cs, line_contract_sha256=G.line_contract_digest(), executable_sha256=(rec["pins"] or {}).get("executable_sha256"), saved_executable=fs.get("executable_sha256"), ppo=G.PPO)
            if probs:
                raise V.IntegrityStop("resume refused", {"problems": probs})
            self.carried = dict(cs["carried"])
            self.tape_pinned = A.read_json(self.root / "input" / "tape_baseline.json")
            # the input copy's FILE hash was checked by copy_inputs against the final-state record and the approval; the table's CONTENT digest must hold too
            if TP.table_digest(self.tape_pinned) != self.tape_pinned.get("sha256") or not self.tape_pinned.get("pinned"):
                raise V.IntegrityStop("the pinned tape table's content digest differs or the table is not pinned", {"sha256": self.tape_pinned.get("sha256")})
            self.resumed = True
            rec["resume"] = {"inputs": copied, "carried_state": self.carried, "saved_counters": fs.get("counters"), "previous_sessions": list(cfg.resume.get("previous_sessions") or []),
                             "tape_baseline_sha256": self.tape_pinned.get("sha256")}
        self.put("open", rec)
        return True

    # -- T0 --

    def t0(self) -> bool:
        cfg, env = self.cfg, self.env
        if self.resumed:
            self.put("t0", {"ok": True, "skipped": "the tape baseline was measured in s1 and is read by digest", "tape_baseline_sha256": self.tape_pinned.get("sha256") if self.tape_pinned else None})
            return True
        jobs = TP.t0_jobs(cfg.tape_keys)
        budget = AR.G2TickBudget(int(cfg.tick_caps["t0"]))
        rec = PR.ProbeRecorder(self.root / "t0" / "episodes.jsonl", phase="t0", now=env.now, artifacts_root=(self.root / "artifacts") if cfg.write_artifacts else None, artifacts_for="all")
        with self.pool("t0", C.FLAGS_EVAL) as pool:
            arena = AR.G2Arena(pool, self.tables, PR.ProbeSource(jobs), budget, now=env.now, guard=self.clock.check, log=env.log)
            runner = PR.ProbeRunner(arena, self.tables, rec, policy=None, tests=None, now=env.now, flatten=self.hooks.flatten)
            res = runner.run()
            arena.wait_settled()
            res["worker_ticks"] = worker_ticks(pool)
        self.t0_records, self.t0_clears = rec.records, rec.clears
        complete = len(rec.records) == len(jobs) and res["stop"] is None
        self.t0_claimed = TP.claimed_table(rec.records, cfg.tape_keys)
        A.write_json(self.root / "t0" / "tape_table.json", A.stamp(dict(self.t0_claimed, note="the CLAIMED table at the end of T0; the pinned table counts verified clears only")), overwrite=False)
        per = {k: {"n": v["n"], "clears_claimed": v["clears_claimed"]} for k, v in self.t0_claimed["landings"].items()}
        self.put("t0", {"ok": complete, "episodes": len(rec.records), "planned": len(jobs), "per_landing": per, "run": res, "claimed_table_sha256": TP.table_digest(self.t0_claimed),
                        "note": "T0 passes on integrity and completion; the tape's clears are the control of the reach rule, never a pass condition"})
        if res["stop"] is not None and not complete:
            raise V.CapStop(f"T0 stopped before completion: {res['stop']['reason']}", valid=False)
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
        rec = TR.G2TrainRecorder(run_dir, fr, self.tables, session=cfg.session, now=env.now, write_artifacts=cfg.write_artifacts, first_clears=cfg.first_clears)
        tape_sha = (self.tape_pinned or {}).get("sha256") if self.resumed else TP.table_digest(self.t0_claimed) if self.t0_claimed else None
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
                   "moves": fr.moves, "attempts": [fr._attempt_summary(a) for a in fr.attempts], "frontier": fr.state(), "recorder": rec.summary(), "arena": sm, "checkpoints": stop.get("checkpoints"),
                   "final_checkpoint": stop.get("final"), "transitions": stop.get("transitions"), "ticks": stop.get("ticks"), "stale_events": arena.stale_events, "resumed": self.resumed,
                   "resumed_seed": stop.get("resumed_seed"), "entropy_note": "per-rollout entropy and explained variance are in training/rollouts.jsonl"}
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
                               "policy_decisions": getattr(policy, "decisions", None)})
        if res["stop"] is not None and not res["stop"]["valid"]:
            raise V.CapStop(f"the close audit stopped early: {res['stop']['reason']}", valid=False)
        return True

    # -- verification --

    def verify(self) -> bool:
        cfg, env = self.cfg, self.env
        jobs: List[VF.VerifyJob] = []
        seen = set()

        def add(rec: Mapping[str, Any], tier: int, group: str) -> None:
            if rec["id"] in seen:
                return
            seen.add(rec["id"])
            jobs.append(VF.VerifyJob(rec["id"], rec["words"], rec["online"], tau=rec["tau"], tier=tier, group=group, meta={"kind": rec.get("kind"), "part": rec.get("part")}))

        audited = set(self.audit_landings)
        for c in self.audit_clears:
            if c["kind"] == "audit_sticky" and c.get("landing") in audited:
                add(c, 0, "audit")
        for c in self.t0_clears:
            add(c, 0, "t0")
        for c in self.train_first_clears:
            add({"id": c["episode"], "words": c["words"], "online": c["online"], "tau": c["tau"], "kind": "train"}, 1, "train")
        if self.frontier is not None:
            for a in self.frontier.attempts:
                for c in a.get("clears_for_verification") or []:
                    add(dict(c, kind="probe"), 2, "probe")
        for c in self.audit_clears:
            if not (c["kind"] == "audit_sticky" and c.get("landing") in audited):
                add(c, 3, "audit_diag")
        out_dir = self.root / "verification"

        def on_result(job: VF.VerifyJob, res: Mapping[str, Any]) -> None:
            self.verified[job.id] = bool(res["exact"])
            A.append_jsonl(out_dir / "replays.jsonl", A.stamp({k: v for k, v in res.items() if k != "breaks"} | {"breaks_n": len(res["breaks"]), "kind": job.meta.get("kind"), "part": job.meta.get("part")}))

        # launches stop VERIFY_LAUNCH_MARGIN_S before the phase's wall cap, so the replays in flight finish inside it (the clock's cap is a stop); the cap itself is unchanged
        rep = VF.run_plan(jobs, env.replay, env.analyse, tick_cap=int(cfg.tick_caps["verify"]), wall_cap_s=max(1.0, float(cfg.wall_caps_s["verify"]) - G.VERIFY_LAUNCH_MARGIN_S),
                          threads=cfg.verify_threads, now=env.now, on_result=on_result, check=self.clock.check)
        self.notes["verification"] = {k: v for k, v in rep.items() if k != "results"}
        by_tier = {}
        for j in jobs:
            d = by_tier.setdefault(j.tier, {"planned": 0, "replayed": 0, "exact": 0})
            d["planned"] += 1
            if j.id in rep["results"]:
                d["replayed"] += 1
                d["exact"] += int(rep["results"][j.id]["exact"])
        self.put("verification", {k: v for k, v in rep.items() if k != "results"} | {"planned": len(jobs), "by_tier": {str(k): v for k, v in sorted(by_tier.items())}})
        if rep["inexact"]:
            self.invalid.append(f"an exact replay of a counted clear failed: {rep['inexact'][:5]}")
        if rep["errors"]:
            self.notes["verification_errors"] = rep["errors"][:5]
        # the pinned tape baseline (s1), written once
        if not self.resumed and self.t0_claimed is not None:
            self.tape_pinned = TP.pinned_table(self.t0_claimed, self.t0_records, self.verified)
            A.write_json(self.dir / "tape_baseline.json", A.stamp(dict(self.tape_pinned)), overwrite=False)
        return not rep["inexact"]

    # -- the decision --

    def facts(self) -> Dict[str, Any]:
        agg = RPT.audit_rows(self.audit_records, self.verified)
        bars = TP.bars(self.tape_pinned) if self.tape_pinned else {}
        ptr = self.frontier.pointer if self.frontier is not None else None
        return {"invalid": list(self.invalid), "phases": dict(self.phases), "training": {"valid_end": bool(self.train_stop.get("valid_end")), "stop": self.train_stop.get("reason")},
                "audit": {int(k): {kk: v[kk] for kk in ("n", "clears", "verified")} for k, v in agg["sticky"].items()}, "audit_detail": agg["sticky"], "bars": bars, "pointer_final": ptr,
                "audit_n": int(self.cfg.audit_n), "unperturbed_n": int(self.cfg.audit_unp),
                "audit_landings": list(self.audit_landings), "unperturbed": agg["unperturbed"], "tick0": agg["tick0"], "deterministic": agg["deterministic"],
                "tape_baseline_sha256": (self.tape_pinned or {}).get("sha256"), "train_fraction": round(float(self.train_stop.get("wall_s") or 0.0) / float(self.cfg.wall_caps_s["train"]), 4)}

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
        # the line
        prev = list((self.cfg.resume or {}).get("previous_sessions") or [])
        this = {"k": self.cfg.session, "outcome": out["outcome"], "D": out["D"], "R": out["R"], "stalled": bool(self.frontier.stalled) if self.frontier else False, "train_fraction": facts["train_fraction"]}
        line = R.apply_line(prev + [this])
        line.update({"sessions": prev + [this], "s2_permitted": line["outcome"] == "CONTINUE", "note": "nothing follows automatically; a next session needs its own approval"})
        out["line"] = {k: line[k] for k in ("outcome", "reasons", "k", "s2_permitted")}
        # the saved state for a later session
        final_dir = self.root / "training" / "checkpoints" / "final"
        if (final_dir / "model.zip").is_file() and (final_dir / "curriculum_state.json").is_file():
            try:
                tb = self.dir / "tape_baseline.json" if (self.dir / "tape_baseline.json").is_file() else self.root / "input" / "tape_baseline.json"
                fs = RS.final_state_record(final_dir=final_dir, tape_baseline_path=tb, session=self.cfg.session, line_contract_sha256=G.line_contract_digest(),
                                           executable_sha256=(close.get("identity") or {}).get("executable_sha256"), extra={"outcome": out["outcome"], "line": out["line"]})
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
    """The wall budget of one s1 session: every phase cap binding, the pool spawns and a grace per phase (pessimistic), and an expected case from g1's
    measured throughputs (decisions record, section 2). A projection, not a promise."""
    phases_sum = sum(wall_caps.values())
    pessimistic = phases_sum + G.POOL_SPAWNS * G.POOL_SPAWN_S + G.WALL_CAP_GRACE_S * len(wall_caps)
    expected = {"open": 20, "p1": 30, "p2": 40, "t0": 560, "train": 4800, "audit": 300, "verify": 420, "close": 90}
    return {"phase_caps_s": dict(wall_caps), "sum_of_caps_s": phases_sum, "pessimistic_total_s": pessimistic, "pessimistic_total_min": round(pessimistic / 60, 1), "global_cap_s": global_cap,
            "fits_global_cap_pessimistic": pessimistic <= global_cap, "slack_pessimistic_s": global_cap - pessimistic, "expected_total_s": sum(expected.values()), "expected_phases_s": expected,
            "expected_native_ticks": {"t0": 1_000_000, "train": 11_000_000, "audit": 450_000, "verify": 550_000},
            "note": "training ends by its 80-minute wall cap in every projection; the session clock starts at the session object and counts the pool spawns; the preflight (unit suite) runs before it"}
