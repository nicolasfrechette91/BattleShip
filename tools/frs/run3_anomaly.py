#!/usr/bin/env python3
"""Run 3 anomaly keeping (2026-11-04 session, step 4; design and decisions in SESSION_LOG_2026-11-04.md sections 8 and 9).

Read-only by construction: nothing here changes a reply, a word, a tick or a selection. Two halves:

    worker side     `JobObserver`, fed every reply of one `iterate_frs` job by tools/frs/run3_worker.py's transparent process proxy:
                      - D6: every burst reply is scanned for a null (JSON for a native NaN or inf), NaN or inf anywhere in its
                        observation and spatial blocks (none in 348,584 stored lab replies). The first one raises `NonFiniteReply`;
                        the worker then returns the burst truncated before that tick (`end_reason` "nonfinite"), rebuilt here with
                        the same m8_rd_cells functions the worker uses, so the engine ingests the earlier reaches unchanged;
                      - the live detectors of tools/glitch/detect.py (`LiveScanner`) on the burst ticks, with the explore flags
                        (spatial only): btt_glitch_event_v1 events returned with the job.
    main side       `AnomalyIngest`, a mixin for the crossing-search engine placed after `DeterministicSchedule`, so it runs at
                    in-order ingest: it appends the events to glitch_events.jsonl (source filled from the dispatch), one row per
                    burst with an event to anomaly_bursts.jsonl (words from tick 0, kept whatever the archive does with the
                    burst), and for a non-finite reply a replay file under anomalies/. Events never gate, rank, reward or select.

Standard library plus the repo's own modules. No coordinate, target id, route or tick is in any rule.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (REPO / "rl", REPO / "tools" / "glitch"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import detect as gd  # noqa: E402
import geometry as gg  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402

ANOMALY_CONTRACT = "run3_anomaly_v1"
NONFINITE_DETECTOR = {"name": "tools/frs/run3_anomaly.py", "version": 1}
MAX_FIELDS = 32
_WORD = {t: i for i, t in enumerate(mcell.TRIPLES)}


# -- D6 -------------------------------------------------------------------------------------------------------------------------------------


def nonfinite_fields(reply: Mapping[str, Any]) -> List[str]:
    """Dotted paths of every null, NaN or inf number in the reply's observation and spatial blocks (at most MAX_FIELDS)."""
    out: List[str] = []

    def walk(x: Any, path: str) -> None:
        if len(out) >= MAX_FIELDS:
            return
        if x is None:
            out.append(path)
        elif isinstance(x, float):
            if not math.isfinite(x):
                out.append(path)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{path}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")

    for block in ("observation", "spatial"):
        if block not in reply:
            out.append(block)
        else:
            walk(reply[block], block)
    return out


class NonFiniteReply(Exception):
    def __init__(self, step: int, fields: Sequence[str]):
        super().__init__(f"non-finite reply at step {step}: {list(fields)[:6]}")
        self.step = int(step)
        self.fields = list(fields)


# -- the worker side ------------------------------------------------------------------------------------------------------------------------


class GeometryCache:
    """One parsed line table per worker process (keyed by the table's digest), so a job does not rebuild it."""

    def __init__(self) -> None:
        self._by_digest: Dict[str, gg.Geometry] = {}

    def get(self, initial: Mapping[str, Any]) -> gg.Geometry:
        lines = (initial.get("spatial") or {}).get("lines")
        key = hashlib.sha256(json.dumps(lines, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        geo = self._by_digest.get(key)
        if geo is None:
            geo = gg.lines_from_trace_reply(initial)
            self._by_digest[key] = geo
        return geo


class JobObserver:
    """Sees every reply of one job, in order, through the process proxy. Never modifies or retains anything it is not told to."""

    def __init__(self, job: Mapping[str, Any], geometry: GeometryCache, params: Optional[gd.Params] = None):
        self.job = job
        self.L = len(bytes(job["words"]))
        self.geometry = geometry
        self.params = params or gd.Params()
        self.source = {"trace": f"{job.get('archive_id')}|{job.get('iteration')}", "draw_id": job.get("archive_id"),
                       "iteration": job.get("iteration"), "cell": job.get("cell")}
        self.tick0: Optional[Mapping[str, Any]] = None
        self.scanner: Optional[gd.LiveScanner] = None
        self.mask: Optional[int] = None
        self.prefix_breaks: List[Tuple[int, int]] = []
        self.last_prefix: Optional[Mapping[str, Any]] = None
        self.burst_replies: List[Mapping[str, Any]] = []
        self.burst_words = bytearray()
        self.decisions: List[Dict[str, Any]] = []
        self.ask_s = 0.0
        self.step_s = 0.0
        self.steps = 0
        self.nonfinite: Optional[Dict[str, Any]] = None
        self.scan_error: Optional[str] = None
        self.scan_s = 0.0

    # -- proxy callbacks --------------------------------------------------------------------------------------------------------------------

    def on_observe(self, reply: Mapping[str, Any]) -> None:
        if self.tick0 is not None:
            return
        self.tick0 = reply
        self.mask = int(reply["spatial"]["target_live_mask"])
        try:
            self.scanner = gd.LiveScanner(reply, self.geometry.get(reply), self.params, self.source, emit_from=self.L)
        except Exception as exc:  # noqa: BLE001 - the detectors are diagnostics: a failure is recorded, never raised
            self.scan_error = f"{type(exc).__name__}: {exc}"[:300]

    def on_step(self, i: int, triple: Tuple[int, int, int], reply: Mapping[str, Any], step_s: float) -> None:
        self.steps += 1
        self.step_s += step_s
        if i >= self.L:
            bad = nonfinite_fields(reply)
            if bad:
                self.nonfinite = {"step": i, "consumed_tick": reply.get("consumed_tick"), "fields": bad, "reply": reply,
                                  "word": _WORD.get(tuple(int(v) for v in triple))}
                raise NonFiniteReply(i, bad)
            self.burst_replies.append(reply)
            self.burst_words.append(_WORD[tuple(int(v) for v in triple)])
        else:
            sp = reply.get("spatial") or {}
            m = sp.get("target_live_mask")
            if m is not None and self.mask is not None and int(m) != self.mask:
                for b in range(mcell.TARGETS_TOTAL):
                    if (self.mask & ~int(m)) >> b & 1:
                        self.prefix_breaks.append((i + 1, b))
                self.mask = int(m)
            self.last_prefix = reply
        if self.scanner is not None and self.scan_error is None:
            t0 = time.perf_counter()
            try:
                self.scanner.feed(i, reply, stick_x=int(triple[1]))
            except Exception as exc:  # noqa: BLE001 - see on_observe
                self.scan_error = f"{type(exc).__name__}: {exc}"[:300]
            self.scan_s += time.perf_counter() - t0

    def on_decision(self, payload: Mapping[str, Any], go: Optional[bool], ask_s: float) -> None:
        self.ask_s += ask_s
        self.decisions.append({"segment": payload["segment"], "words": payload["words"], "in_window": len(payload["reaches"]),
                               "go": bool(go), "answered": go is not None})

    # -- results ---------------------------------------------------------------------------------------------------------------------------

    def glitch(self) -> Dict[str, Any]:
        events = self.scanner.finish() if self.scanner is not None and self.scan_error is None else []
        return {"contract": ANOMALY_CONTRACT, "detector": gd.DETECTOR, "events": events,
                "counts": dict(self.scanner.counts) if self.scanner is not None else {}, "error": self.scan_error,
                "geometry_sha256": self.scanner.geo.sha256() if self.scanner is not None else None,
                "scan_s": round(self.scan_s, 4)}

    def rebuild(self, clf: mcell.Classifier) -> Dict[str, Any]:
        """The burst as rl/frs_worker.run_iterate_frs records it, from the burst replies seen so far (same functions, same order)."""
        if self.tick0 is None:
            raise RuntimeError("no tick-0 observe was seen")
        chain = bytes(self.job["chain"]) if self.L > 0 else mcell.chain_start(mcell.tick0_record(self.tick0))
        mask_at_L = int(self.mask) if self.mask is not None else int(self.tick0["spatial"]["target_live_mask"])
        scanner = mcell.BurstScanner(mask_at_L)
        reaches: List[Tuple[int, Tuple[Any, ...], Tuple[Any, ...], bytes, bytes, bool]] = []
        seen = set()
        for idx, rep in enumerate(self.burst_replies):
            j = self.L + idx + 1
            o, sp = rep["observation"], rep["spatial"]
            rd = mcell.record_digest(mcell.record_of(rep))
            chain = mcell.chain_next(chain, rd)
            state = rep["state"]
            ended = state == mcell.STATE_ENDED
            fell = mcell.is_native_failure(o, state)
            key = mcell.cell_key(o, sp, clf)
            if key is not None and key not in seen:
                seen.add(key)
                reaches.append((j, key, mcell.obs_tuple(o), rd, chain, ended or fell))
            scanner.feed(j, o, sp, state)
        return {"words": bytes(self.burst_words), "reaches": reaches, "labels": scanner.labels(),
                "breaks_all": list(self.prefix_breaks) + list(scanner.breaks), "t_end": scanner.t, "final_chain": chain.hex()}

    def selfcheck(self, res: Mapping[str, Any], clf: mcell.Classifier) -> Dict[str, Any]:
        """Tests only: the rebuild of a normal burst must equal what the worker returned."""
        r = self.rebuild(clf)
        diffs = []
        for k in ("words", "labels", "t_end", "final_chain"):
            if r[k] != res.get(k):
                diffs.append(k)
        if [list(x) for x in r["breaks_all"]] != [list(x) for x in res.get("breaks_all") or []]:
            diffs.append("breaks_all")
        norm = lambda rs: [(int(a), list(b), list(c), bytes(d).hex(), bytes(e).hex(), bool(f)) for a, b, c, d, e, f in rs]
        if norm(r["reaches"]) != norm(res.get("reaches") or []):
            diffs.append("reaches")
        return {"ok": not diffs, "diffs": diffs, "reaches": len(r["reaches"])}

    def nonfinite_event(self) -> Dict[str, Any]:
        """The btt_glitch_event_v1 row of the non-finite reply (built here: the reply cannot be parsed into a detector state)."""
        nf = self.nonfinite or {}
        step = int(nf.get("step", -1))
        prev = self.burst_replies[-1] if self.burst_replies else (self.last_prefix or self.tick0 or {})
        key = json.dumps([self.source.get("trace"), "nonfinite", step, nf.get("fields")], default=str)
        po = (prev.get("observation") or {}) if prev else {}
        return {"schema": gd.EVENT_SCHEMA, "event_id": hashlib.sha256(key.encode()).hexdigest()[:16], "kind": "nonfinite",
                "mechanisms": ["D6"], "step": step, "step_from": step - 1, "step_to": step, "input_tick": step + 1,
                "consumed_tick": nf.get("consumed_tick"), "score": float(len(nf.get("fields") or [])), "threshold": 0,
                "source": dict(self.source), "geometry_sha256": self.scanner.geo.sha256() if self.scanner is not None else None,
                "ecb": list(self.scanner.ecb) if self.scanner is not None else None,
                "fighter": {"prev": {"step": step - 1, "pos": [po.get("position_x"), po.get("position_y")],
                                     "vel_air": [po.get("air_velocity_x"), po.get("air_velocity_y")], "status": po.get("fighter_status_id")},
                            "curr": {"step": step, "fields": nf.get("fields")}},
                "evidence": {"fields": nf.get("fields"), "word": nf.get("word")}, "platform_sensitive": [],
                "detector": NONFINITE_DETECTOR, "needs_replay": True}


# -- the main side --------------------------------------------------------------------------------------------------------------------------


class AnomalyIngest:
    """Mixin for the crossing-search engine. Place it AFTER DeterministicSchedule in the bases, so `handle` runs in dispatch
    order: `class E(DeterministicSchedule, AnomalyIngest, crossing_search.Search)`. Logging only: the result goes to the
    engine's own `handle` unchanged and first."""

    def __init__(self, *args: Any, anomaly_build: Optional[Mapping[str, Any]] = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.anomaly_build = dict(anomaly_build or {})
        self.anomaly_stats: Dict[str, Any] = {"events": 0, "bursts": 0, "nonfinite": 0, "scan_errors": 0, "by_kind": {}, "counts": {},
                                              "samples": {}, "sample_cap": gd.Params().stop_samples}

    def handle(self, w: Any, kind: str, payload: Dict[str, Any]) -> None:
        info = self.inflight.get(w)
        info = dict(info) if info is not None else None
        super().handle(w, kind, payload)
        if info is None or not isinstance(payload, dict) or not payload.get("ok"):
            return
        sc = payload.get("run3_selfcheck")
        if sc is not None:                                  # tests only (worker spec run3_selfcheck)
            st = self.anomaly_stats.setdefault("selfcheck", {"checked": 0, "failed": 0, "diffs": []})
            st["checked"] += 1
            if not sc.get("ok"):
                st["failed"] += 1
                st["diffs"] = (st["diffs"] + [[info.get("n"), sc.get("diffs")]])[:8]
        try:
            self._keep_anomalies(info, payload)
        except Exception as exc:  # noqa: BLE001 - logging must never stop or change the run
            self.log(f"anomaly logging failed for dispatch {info.get('n')}: {type(exc).__name__}: {exc}"[:300])

    def _keep_anomalies(self, info: Mapping[str, Any], res: Mapping[str, Any]) -> None:
        glitch = res.get("glitch") or {}
        counts = self.anomaly_stats["counts"]
        for k, v in (glitch.get("counts") or {}).items():           # every class of every burst, for the run summary
            counts[k] = counts.get(k, 0) + int(v)
        events = [e for e in glitch.get("events") or [] if not str(e.get("kind")).endswith("_sample")]
        samples = [e for e in glitch.get("events") or [] if str(e.get("kind")).endswith("_sample")]
        if glitch.get("error"):
            self.anomaly_stats["scan_errors"] += 1
        nf = res.get("nonfinite")
        if nf:
            events.append(nf["event"])
        if not events and not samples:
            return
        parent = bytes(info["words"])
        burst = bytes(res.get("words") or b"")
        words = parent + burst + (bytes([nf["word"]]) if nf and nf.get("word") is not None else b"")
        source = {"run_folder": str(self.dir), "n": info["n"], "cid": info["cid"], "k": info["k"], "draw_id": info["draw_id"],
                  "level": info["level"], "start_tick": info["tick"], "parent_digest": info["digest"],
                  "words_digest": mcell.words_digest(words), "words_from_tick0": len(words)}
        for ev in samples:                                           # audit samples: the first sample_cap per class of the run
            cls = str((ev.get("evidence") or {}).get("class"))
            kept = self.anomaly_stats["samples"].get(cls, 0)
            if kept >= self.anomaly_stats["sample_cap"]:
                continue
            self.anomaly_stats["samples"][cls] = kept + 1
            self.fs.append_jsonl(self.dir / "glitch_samples.jsonl", dict(ev, source=dict(ev.get("source") or {}, **source),
                                                                          build=dict(self.anomaly_build), words_hex=words.hex()))
        if not events:
            return
        ids = []
        for ev in events:
            row = dict(ev)
            row["source"] = dict(ev.get("source") or {}, **source)
            row["build"] = dict(self.anomaly_build)
            self.fs.append_jsonl(self.dir / "glitch_events.jsonl", row)
            ids.append(row["event_id"])
            k = str(row.get("kind"))
            self.anomaly_stats["by_kind"][k] = self.anomaly_stats["by_kind"].get(k, 0) + 1
        self.anomaly_stats["events"] += len(events)
        self.anomaly_stats["bursts"] += 1
        row = {"contract": ANOMALY_CONTRACT, "n": info["n"], "cid": info["cid"], "k": info["k"], "draw_id": info["draw_id"],
               "level": info["level"], "start_tick": info["tick"], "outcome": res.get("end_reason"), "words_hex": words.hex(),
               "words_digest": source["words_digest"], "parent_digest": info["digest"], "event_ids": ids,
               "kinds": sorted({str(e.get("kind")) for e in events}), "build": dict(self.anomaly_build)}
        self.fs.append_jsonl(self.dir / "anomaly_bursts.jsonl", row)
        if nf:
            self.anomaly_stats["nonfinite"] += 1
            path = self.dir / "anomalies" / f"nonfinite_{nf['event']['event_id']}.json.gz"
            self.fs.mkdir(path.parent)
            import frs_verify as fv  # light import at use: the engine already has it loaded

            fv.save_trace(path, {"contract": ANOMALY_CONTRACT, "kind": "nonfinite", "event": nf["event"], "words_hex": words.hex(),
                                 "L": int(res["L"]), "step": nf["step"], "fields": nf["fields"], "replies_from_L": nf.get("replies")})
            self.event(f"non-finite reply kept: dispatch {info['n']} cell {info['cid']} k {info['k']} step {nf['step']} "
                       f"fields {nf['fields'][:3]}; the burst is ingested up to the tick before; replay {path.name}")

    def summary(self) -> Dict[str, Any]:
        s = super().summary()
        s["anomalies"] = dict(self.anomaly_stats)
        return s
