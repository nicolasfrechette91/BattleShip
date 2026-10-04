"""M9-g1: the lineage registry (the agent's own verified rd4 clears as start-state sources) and its tables.

Decision 5: only the two replay-verified rd4 clears (iterations 11206 and 11286). They are read from the rd4 tree, which is only read
(`runs/m8_rd_rd4/routes/{T_clear,T_t}`: canonical Track 1 words, native action digest, the verifying replay's raw replies). They are START
STATES and a backward curriculum only: never action targets, never a source of weights. Human recordings, the fixtures and the TAS are never read.

For each lineage this module (a) re-derives and checks the registered facts (length, words digest, native action digest, completion clocks,
Track 1 range, actions.jsonl equal to the words, consumed ticks 0..n-1), (b) derives the per-tick CHAIN table from the verifying replay's
replies (chain[i] = the record chain digest of the state after i ticks) and, from a fresh replay of this session, the per-tick v3 OBSERVATION
digest table (v3[i] = the digest of the observation the policy sees at input tick i, built from every reply 0..i-1), and (c) computes the
landing states: the first input tick of every grounded segment of the trunk. P1 replays each lineage from tick 0 and requires every replay
to agree with the registered chain; the tables are then written once and every staged start checks every prefix tick against them.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_cells as mcell
import m9_contract as C
import m9_verify as V

LINEAGE_CONTRACT = "m9_lineages_v1"
TABLE_FILES = ("words.bin", "chain.bin", "v3.bin")
RD4_ARCHIVE_META = "runs/m8_rd_rd4/archive/archive_meta.json"


class LineageError(RuntimeError):
    pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Lineage:
    name: str
    words: bytes
    native_action_digest: str
    words_sha256: str
    completion_time_passed: int
    completion_input_tick: int
    route_dir: str
    iteration: int
    file_sha256: Dict[str, str] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return len(self.words)

    def registration(self) -> Dict[str, Any]:
        return {"name": self.name, "words": self.length, "words_sha256": self.words_sha256, "native_action_digest": self.native_action_digest,
                "completion_time_passed": self.completion_time_passed, "completion_input_tick": self.completion_input_tick, "route_dir": self.route_dir,
                "iteration": self.iteration, "source_file_sha256": dict(self.file_sha256), "role": "start states and a backward curriculum only"}


def load_lineage(repo: Path, entry: Mapping[str, Any]) -> Lineage:
    """One registered lineage, every registered fact re-derived from the rd4 route files (read only)."""
    d = Path(repo) / str(entry["route_dir"])
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    words = bytes.fromhex(meta["track1_words_hex"])
    problems: List[str] = []
    if len(words) != int(entry["words"]) or int(meta["words"]) != len(words):
        problems.append(f"{len(words)} words, registered {entry['words']}")
    if any(w >= mcell.TRACK1_WORDS for w in words):
        problems.append("a word outside Track 1 (0..71)")
    digest = mcell.words_digest(words)
    if digest != meta["native_action_digest"]:
        problems.append("the words' native action digest differs from the route's recorded digest")
    if entry.get("native_action_digest") and digest != entry["native_action_digest"]:
        problems.append("the native action digest differs from the registered one")
    rows = [json.loads(ln) for ln in (d / "actions.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(rows) != len(words):
        problems.append(f"actions.jsonl has {len(rows)} rows")
    else:
        for i, (r, w) in enumerate(zip(rows, words)):
            if (int(r["buttons"]), int(r["stick_x"]), int(r["stick_y"])) != mcell.TRIPLES[w] or int(r["consumed_tick"]) != i or int(r["sequence_index"]) != i:
                problems.append(f"actions.jsonl row {i} differs from word {w}")
                break
    facts = (meta.get("replay") or {}).get("clear_facts") or {}
    clocks = (int(facts.get("completion_time_passed", -1)), int(facts.get("completion_input_tick", -1)))
    if clocks != (int(entry["completion_time_passed"]), int(entry["completion_input_tick"])):
        problems.append(f"completion clocks {clocks}, registered {(entry['completion_time_passed'], entry['completion_input_tick'])}")
    if clocks[0] == clocks[1]:
        problems.append("the two completion clocks are equal (never collapsed)")
    if not facts.get("all"):
        problems.append("the route's recorded clear facts are not all true")
    if not (meta.get("replay") or {}).get("exact"):
        problems.append("the route was not recorded as an exact replay")
    if problems:
        raise LineageError(f"lineage {entry['name']}: " + "; ".join(problems))
    return Lineage(name=str(entry["name"]), words=words, native_action_digest=digest, words_sha256=hashlib.sha256(words).hexdigest(),
                   completion_time_passed=clocks[0], completion_input_tick=clocks[1], route_dir=str(entry["route_dir"]), iteration=int(entry["iteration"]),
                   file_sha256={n: sha256_file(d / n) for n in ("actions.jsonl", "metadata.json", "trace.json.gz")})


def load_registered(repo: Path) -> Dict[str, Lineage]:
    out = {e["name"]: load_lineage(repo, e) for e in C.LINEAGES}
    a, b = out["T_clear"].words, out["T_t"].words
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    if k != C.SHARED_PREFIX:
        raise LineageError(f"T_clear and T_t share {k} words, registered {C.SHARED_PREFIX}")
    return out


def shared_prefix(a: bytes, b: bytes) -> int:
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    return k


def load_route_trace(repo: Path, lineage: Lineage) -> Dict[str, Any]:
    with gzip.open(Path(repo) / lineage.route_dir / "trace.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def load_pin_tick0(repo: Path) -> Dict[str, Any]:
    meta = json.loads((Path(repo) / RD4_ARCHIVE_META).read_text(encoding="utf-8"))
    return dict(meta["pin_tick0"])


# -- tables -------------------------------------------------------------------------------------------------------------------------


def landing_starts(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> List[int]:
    """The first input tick of every grounded segment (live observations with ground_air_state == 0), tick 0 included when the episode starts
    grounded. Input tick t is the observation after consumed tick t - 1."""
    out: List[int] = []
    prev = False
    for s in [initial] + list(steps):
        o = s["observation"]
        g = mcell.is_live(o) and int(o["ground_air_state"]) == 0
        if g and not prev:
            out.append(int(o["input_tick"]))
        prev = g
    return out


def check_landings(starts: Sequence[int], registered: Sequence[int] = C.LANDINGS) -> List[str]:
    """The registered landing states must be exactly the grounded-segment starts from 1,248 up (the trunk's own segments)."""
    lo = min(registered)
    got = sorted((t for t in starts if t >= lo), reverse=True)
    if got != sorted(registered, reverse=True):
        return [f"computed landing states {got} differ from the registered {list(registered)}"]
    return []


def build_tables(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]], pipeline_cls: Any = None) -> Tuple[List[bytes], List[bytes]]:
    """(chain, v3): chain[i] for i = 0..n, v3[i] = the 32-byte digest of the observation at input tick i (the tick-0 observe reply, then every reply)."""
    chain = V.trace_chain(initial, steps)
    if pipeline_cls is None:
        import m9_obs

        pipeline_cls = m9_obs.V3Pipeline
    pipe = pipeline_cls(initial)
    v3 = [bytes.fromhex(pipe.digest())]
    for s in steps:
        pipe.feed(s)
        v3.append(bytes.fromhex(pipe.digest()))
    return chain, v3


def save_tables(directory: Path, name: str, words: bytes, chain: Sequence[bytes], v3: Sequence[bytes]) -> Dict[str, str]:
    d = Path(directory) / name
    d.mkdir(parents=True, exist_ok=True)
    if len(chain) != len(words) + 1 or len(v3) != len(words) + 1:
        raise LineageError(f"table lengths {len(chain)} / {len(v3)} for {len(words)} words")
    for fname, blob in (("words.bin", bytes(words)), ("chain.bin", b"".join(chain)), ("v3.bin", b"".join(v3))):
        p = d / fname
        if p.exists():
            raise LineageError(f"{p} exists (a table is written once)")
        p.write_bytes(blob)
    return {n: sha256_file(d / n) for n in TABLE_FILES}


class Tables:
    """The registered tables of one lineage as read by a worker: words, chain digests, v3 digests."""

    def __init__(self, words: bytes, chain: Sequence[bytes], v3: Sequence[bytes]):
        self.words, self.chain, self.v3 = bytes(words), list(chain), list(v3)
        if len(self.chain) != len(self.words) + 1 or len(self.v3) != len(self.words) + 1:
            raise LineageError("table lengths do not match the words")


def load_tables(directory: Path, name: str) -> Tables:
    d = Path(directory) / name
    words = (d / "words.bin").read_bytes()
    chain_b, v3_b = (d / "chain.bin").read_bytes(), (d / "v3.bin").read_bytes()
    n = len(words) + 1
    if len(chain_b) != 32 * n or len(v3_b) != 32 * n:
        raise LineageError(f"{d}: table sizes do not match {len(words)} words")
    return Tables(words, [chain_b[32 * i:32 * i + 32] for i in range(n)], [v3_b[32 * i:32 * i + 32] for i in range(n)])


def load_all_tables(directory: Path, names: Sequence[str]) -> Dict[str, Tables]:
    return {n: load_tables(directory, n) for n in names}


# -- P1 evaluation --------------------------------------------------------------------------------------------------------------------


def p1_lineage(lineage: Lineage, route_trace: Mapping[str, Any], replays: Sequence[Mapping[str, Any]], analyse: V.Analyser, pin_tick0: Mapping[str, Any],
               *, promoted: Optional[Sequence[Mapping[str, Any]]] = None, pipeline_cls: Any = None, landings: Sequence[int] = C.LANDINGS) -> Dict[str, Any]:
    """P1 for one lineage: every replay trace (>= 2, fresh processes) and every promoted-standby replay result must be exact and agree with the
    chain of the rd4 verifying replay; the v3 tables of the replays must agree; the tick-0 record must equal the archive's pin. Returns the
    verdict and the tables to register (written only when `ok`)."""
    problems: List[str] = []
    ref_chain = V.trace_chain(route_trace["initial"], route_trace["steps"])
    rec0 = mcell.tick0_record(route_trace["initial"])
    if mcell.record_digest(rec0).hex() != pin_tick0["digest"] or ref_chain[0].hex() != pin_tick0["chain"]:
        problems.append("the rd4 route trace's tick-0 record differs from the archive pin")
    landing = landing_starts(route_trace["initial"], route_trace["steps"])
    problems += check_landings(landing, landings) if len(lineage.words) >= C.SHARED_PREFIX and lineage.name == C.TAPE_LINEAGE else []
    per: List[Dict[str, Any]] = []
    promotion: List[str] = []
    v3_ref: Optional[List[bytes]] = None
    for k, tr in enumerate(replays):
        ev = V.evaluate_trace(tr, lineage.words, analyse, expect_clear=True)
        row: Dict[str, Any] = {"replay": k, "exact": ev["exact"], "problems": list(ev["problems"]), "ticks": ev["ticks"], "chain_final": ev["chain_final"],
                               "completion_time_passed": ev["completion_time_passed"], "completion_input_tick": ev["completion_input_tick"]}
        if (ev["completion_time_passed"], ev["completion_input_tick"]) != (lineage.completion_time_passed, lineage.completion_input_tick):
            row["problems"].append("completion clocks differ from the registered ones")
        chain = V.trace_chain(tr["initial"], tr["steps"])
        if chain != ref_chain:
            first = next((i for i, (a, b) in enumerate(zip(chain, ref_chain)) if a != b), min(len(chain), len(ref_chain)))
            row["problems"].append(f"per-tick chain differs from the rd4 verifying replay (first difference at tick {first})")
        if mcell.record_digest(mcell.tick0_record(tr["initial"])).hex() != pin_tick0["digest"]:
            row["problems"].append("tick-0 record differs from the archive pin")
        _chain, v3 = build_tables(tr["initial"], tr["steps"], pipeline_cls)
        if v3_ref is None:
            v3_ref = v3
        elif v3 != v3_ref:
            first = next((i for i, (a, b) in enumerate(zip(v3, v3_ref)) if a != b), min(len(v3), len(v3_ref)))
            row["problems"].append(f"v3 observation table differs between replays (first difference at tick {first})")
        row["exact"] = not row["problems"]
        per.append(row)
    for k, pr in enumerate(promoted or []):
        row = {"promoted_replay": k, "problems": []}
        if pr.get("native_action_digest") != lineage.native_action_digest:
            row["problems"].append("native action digest differs")
        if (pr.get("result_json") or {}).get("outcome") != "clear" or (pr.get("result_json") or {}).get("completion_input_tick") != lineage.completion_input_tick \
                or (pr.get("result_json") or {}).get("completion_time_passed") != lineage.completion_time_passed:
            row["problems"].append("the native result is not the registered clear with both clocks")
        if (pr.get("startup") or {}).get("mode") != "standby_promoted":
            # a standby that was not ready (cold fallback) is a lifecycle condition, not an integrity failure: the replay may be exact, but the promotion equivalence
            # P1 asks for was not exercised, so P1 is not passed (INCOMPLETE), never INVALID
            promotion.append(f"not a standby promotion ({(pr.get('startup') or {}).get('mode')})")
        row["exact"] = not row["problems"]
        per.append(row)
    for r in per:
        problems += [f"replay {r.get('replay', r.get('promoted_replay'))}: {p}" for p in r["problems"]]
    ok = not problems and not promotion and len(replays) >= 2 and v3_ref is not None
    return {"lineage": lineage.name, "ok": ok, "problems": problems, "promotion_problems": promotion, "replays": per, "landing_starts": landing,
            "chain": ref_chain if ok else None, "v3": v3_ref if ok else None}


def contract_description() -> Dict[str, Any]:
    return {"contract": LINEAGE_CONTRACT, "lineages": [dict(x) for x in C.LINEAGES], "shared_prefix": C.SHARED_PREFIX, "landings": list(C.LANDINGS),
            "tables": "words.bin, chain.bin (32 B x (n+1)), v3.bin (32 B x (n+1))", "p1": "three replays per lineage (two fresh, one promoted standby), "
            "every one exact and equal to the rd4 verifying replay's chain; v3 tables equal across replays"}
