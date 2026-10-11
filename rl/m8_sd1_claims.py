"""M8-sd1: the claims plan `m8_sd1_claims_v1` for a speed session (pure; the frozen claims engine `m8_rd_claims` is imported, never edited).

The frozen engine labels every burst and registers `t`, `l0`, `left` and `clear` candidates as before; the stored registry keeps all of them. sd1's plan decides only the ORDER and
the POOL (docs/rl_m8_sd1_proposal_2026-10-07.md section 5, as decided on 2026-10-11):

    the pool          the `clear`-kind candidates (one per clearing job: its full trajectory) whose registered clear tick (`first.clear`, the scanner's input tick of the native
                      EpisodeEnded with no target left) is below T_rec, ordered by that tick ascending, then by cid; replayed three at a time, fastest first, until the first EXACT
                      replay: the fastest exact replay is the session's best verified clear and nothing slower can change the outcome, so the pool then closes (an inexact replay is
                      INVALID for the session, never skipped)
    the INCOMPLETE    only the pool candidates with first.clear <= T_rec - M (the ones that could be PROGRESS) count: one of them left unverified at a cap before any exact replay is
    test              INCOMPLETE; a slower one is reported
    never replayed    `left`, `l0` and `t` candidates (the `t` record of ten targets is the same trajectory as the fastest clear, truncated at the same tick, so replaying it would be a
                      duplicate), and the `left`-kind twin of a clearing job
    exactness         the engine's exactness (digest, every consumed tick, the break table, the four clear facts) AND the replay's completion_input_tick equal to the candidate's
                      registered clear tick; completion_time_passed is recorded beside it
    inherited         every clear-event trajectory of rd4's registry that no rd4 replay verified (read from rd4's ledger_T.json, candidates_T.jsonl.gz and replays.jsonl, by that rule and
    descriptive       nothing else), replayed AFTER the pool as reported facts: never an outcome input; an inexact one is flagged (INHERITED_REPLAY_INEXACT), never INVALID (decided 2026-10-11)

No registered measure (the outcome, the selection, the cell key) reads this plan except through the verified clears it produces.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_cells as mcell
import m8_rd_claims as mclaims

CLAIMS5_CONTRACT = "m8_sd1_claims_v1"
BATCH = 3
INHERITED_CID_BASE = 100_000                        # the replay index of an inherited candidate never collides with a session cid


def contract_digest() -> str:
    d = {"contract": CLAIMS5_CONTRACT, "base": mclaims.CLAIMS_CONTRACT, "base_digest": mclaims.contract_digest(),
         "pool": "clear-kind candidates with first.clear < T_rec, ordered by (first.clear, cid)", "batch": BATCH,
         "order": "fastest first, three at a time, until the first exact replay; the pool then closes; an inexact replay is INVALID, never skipped",
         "incomplete_reads": "pool candidates with first.clear <= T_rec - M left unverified at a cap before any exact replay",
         "never_replayed": ["left", "l0", "t"], "exactness": "the engine's exactness and completion_input_tick == first.clear; completion_time_passed recorded",
         "inherited_descriptive": "every clear-event trajectory of rd4's registry that no rd4 replay verified; after the pool; reported only; inexact -> flag INHERITED_REPLAY_INEXACT"}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the pool ------------------------------------------------------------------------------------------------------------------------------------------


def clear_tick(cand: Mapping[str, Any]) -> Optional[int]:
    v = (cand.get("first") or {}).get("clear")
    return None if v is None else int(v)


def pool5(ledger: mclaims.ArmLedger, T: int, t_rec: int) -> List[Tuple[Dict[str, Any], int]]:
    """The clear-kind candidates within T whose registered clear tick is below T_rec, fastest first (then by cid), each with its counted length (the whole trajectory)."""
    out = [(c, n) for c, n in ledger.within(T, "clear") if clear_tick(c) is not None and clear_tick(c) < int(t_rec)]
    out.sort(key=lambda cn: (clear_tick(cn[0]), cn[0]["cid"]))
    return out


def progress_pool5(ledger: mclaims.ArmLedger, T: int, t_rec: int, margin: int) -> List[Tuple[Dict[str, Any], int]]:
    return [(c, n) for c, n in pool5(ledger, T, t_rec) if clear_tick(c) <= int(t_rec) - int(margin)]


def pool_sizes5(ledger: mclaims.ArmLedger, T: int, t_rec: int, margin: int) -> Dict[str, Any]:
    cands = ledger.candidates
    clears = [c for c, _n in ledger.within(T, "clear")]
    ticks = sorted(clear_tick(c) for c in clears if clear_tick(c) is not None)
    return {"candidates": len(cands), "left": sum(1 for c in cands if c["kind"] == "left"), "clear_kind": len(clears), "t": len(ledger.within(T, "t")), "l0": len(ledger.within(T, "l0")),
            "pool": len(pool5(ledger, T, t_rec)), "progress_pool": len(progress_pool5(ledger, T, t_rec, margin)), "clear_ticks_registered": ticks,
            "fastest_registered": ticks[0] if ticks else None, "t_rec": int(t_rec), "margin": int(margin)}


def exact_clear_clock(rep: Mapping[str, Any]) -> Optional[int]:
    """The completion_input_tick of an exact clear replay (None otherwise)."""
    if not rep.get("exact") or not rep.get("clear"):
        return None
    v = (rep.get("clear_facts") or {}).get("completion_input_tick")
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def plan_replays5(ledger: mclaims.ArmLedger, T: int, done: Mapping[int, Mapping[str, Any]], t_rec: int, margin: int, batch: int = BATCH) -> Tuple[List[Tuple[Dict[str, Any], int]], Dict[str, Any]]:
    """The next replays (<= `batch`): the fastest unreplayed pool candidates, in order; none once an exact clear replay exists (the pool is closed). Also reports the pool's state."""
    pool = pool5(ledger, T, t_rec)
    best_tick: Optional[int] = None
    best_cid: Optional[int] = None
    for cid, r in done.items():
        c = exact_clear_clock(r)
        if c is not None and (best_tick is None or (c, int(cid)) < (best_tick, int(best_cid))):
            best_tick, best_cid = c, int(cid)
    remaining = [(c, n) for c, n in pool if c["cid"] not in done]
    remaining_progress = [(c, n) for c, n in remaining if clear_tick(c) <= int(t_rec) - int(margin)]
    closed = best_tick is not None
    todo = [] if closed else remaining[:batch]
    info = {"pool": len(pool), "replayed": sum(1 for c, _n in pool if c["cid"] in done), "remaining": len(remaining), "remaining_progress": len(remaining_progress),
            "closed": closed, "best_cid": best_cid, "best_completion_input_tick": best_tick,
            "remaining_faster_than_best": sum(1 for c, _n in remaining if best_tick is not None and clear_tick(c) < best_tick)}
    return todo, info


# -- exactness of a clear claim ---------------------------------------------------------------------------------------------------------------------------


def exactness5(rep: Mapping[str, Any], cand: Mapping[str, Any]) -> List[str]:
    """What makes a clear replay a verified clear beyond the engine's exactness: the four facts hold over the whole trajectory, and the replay's completion_input_tick equals the
    registered clear tick; completion_time_passed must be an integer (it is recorded, never compared)."""
    problems: List[str] = []
    if not rep.get("exact"):
        problems.append("inexact replay: " + "; ".join(str(p) for p in (rep.get("problems") or [])[:3]))
    facts = rep.get("clear_facts") or {}
    if not rep.get("clear") or not facts.get("all"):
        problems.append(f"the claimed clear does not hold over the whole trajectory: {facts}")
    cit, ctp = facts.get("completion_input_tick"), facts.get("completion_time_passed")
    if not isinstance(cit, int) or isinstance(cit, bool) or not isinstance(ctp, int) or isinstance(ctp, bool):
        problems.append(f"the completion clocks are not integers: {cit!r} / {ctp!r}")
    elif clear_tick(cand) is not None and cit != clear_tick(cand):
        problems.append(f"completion_input_tick {cit} differs from the registered clear tick {clear_tick(cand)}")
    if int(rep.get("counted", -1)) != len(bytes(cand["words"])):
        problems.append(f"{rep.get('counted')} counted words, the trajectory has {len(bytes(cand['words']))}")
    return problems


def verified_clear_record(rep: Mapping[str, Any], cand: Mapping[str, Any]) -> Dict[str, Any]:
    facts = rep["clear_facts"]
    words = bytes(cand["words"])
    return {"cid": int(cand["cid"]), "iteration": int(cand["iteration"]), "kind": cand["kind"], "completion_input_tick": int(facts["completion_input_tick"]),
            "completion_time_passed": int(facts["completion_time_passed"]), "native_action_digest": mcell.words_digest(words), "words": len(words), "registered_clear_tick": clear_tick(cand),
            "label": rep.get("label"), "trace": rep.get("trace"), "t": int(rep.get("t", 0))}


# -- the inherited descriptive candidates (rd4's registry, read only) ----------------------------------------------------------------------------------------


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def registry_words(rd4_dir: Path, session: str = "rd4") -> Dict[int, bytes]:
    """cid -> words of every candidate of rd4's registry (candidates_T.jsonl.gz, words_hex)."""
    p = Path(rd4_dir) / "sessions" / session / "candidates_T.jsonl.gz"
    out: Dict[int, bytes] = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                d = json.loads(ln)
                if "cid" in d and "words_hex" in d:
                    out[int(d["cid"])] = bytes.fromhex(d["words_hex"])
    return out


def rd4_replays(rd4_dir: Path, session: str = "rd4") -> List[Dict[str, Any]]:
    p = Path(rd4_dir) / "sessions" / session / "verification" / "replays.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def clear_trajectories(rd4_dir: Path, session: str = "rd4") -> Dict[str, Any]:
    """rd4's registered clear-event trajectories (one per clearing job, by iteration) and which of them an rd4 replay verified (an exact replay with the clear facts whose candidate
    belongs to that iteration). Reads only."""
    rd4_dir = Path(rd4_dir)
    led = _read(rd4_dir / "sessions" / session / "ledger_T.json")
    cands = list(led.get("candidates") or [])
    by_cid = {int(c["cid"]): c for c in cands}
    jobs: Dict[int, Dict[str, Any]] = {}
    for c in cands:
        if clear_tick(c) is None:
            continue
        it = int(c["iteration"])
        j = jobs.setdefault(it, {"iteration": it, "first_clear": clear_tick(c), "cids": [], "clear_cid": None})
        j["cids"].append(int(c["cid"]))
        if c["kind"] == "clear":
            j["clear_cid"] = int(c["cid"])
    verified: Dict[int, List[int]] = {}
    for r in rd4_replays(rd4_dir, session):
        if r.get("exact") and r.get("clear") and int(r["cid"]) in by_cid:
            verified.setdefault(int(by_cid[int(r["cid"])]["iteration"]), []).append(int(r["cid"]))
    for it, j in jobs.items():
        j["verified_by_rd4"] = sorted(verified.get(it, []))
    return {"jobs": [jobs[it] for it in sorted(jobs, key=lambda i: (jobs[i]["first_clear"], i))], "candidates_by_cid": by_cid, "replays_exact_clear": sum(len(v) for v in verified.values())}


def inherited_unverified_clears(rd4_dir: Path, session: str = "rd4") -> List[Dict[str, Any]]:
    """Every clear-event trajectory of rd4's registry that no rd4 replay verified, as replayable candidates (the clear-kind candidate's full words, breaks, first events and clear tick),
    fastest first. The rule, and nothing else, selects them."""
    tr = clear_trajectories(rd4_dir, session)
    words = registry_words(rd4_dir, session)
    out: List[Dict[str, Any]] = []
    for j in tr["jobs"]:
        if j["verified_by_rd4"] or j["clear_cid"] is None:
            continue
        c = tr["candidates_by_cid"][j["clear_cid"]]
        w = words.get(int(c["cid"]))
        if w is None or len(w) != int(c.get("length", len(w))) or int(c["event_j"]) != clear_tick(c):
            raise ValueError(f"rd4 candidate {c['cid']}: its stored words or clear tick are inconsistent")
        out.append({"kind": "clear", "arm": "T", "iteration": int(c["iteration"]), "cum_before": int(c["cum_before"]), "event_j": int(c["event_j"]), "t": c.get("t"),
                    "words": w, "breaks": [[int(a), int(b)] for a, b in c["breaks"]], "first": dict(c["first"]), "cid": INHERITED_CID_BASE + int(c["cid"]), "rd4_cid": int(c["cid"]),
                    "inherited": True, "source": f"runs/m8_rd_rd4/sessions/{session}/ledger_T.json"})
    out.sort(key=lambda c: (clear_tick(c), c["rd4_cid"]))
    return out


def record_candidate(rd4_dir: Path, record_reference: Mapping[str, Any], session: str = "rd4") -> Dict[str, Any]:
    """The record itself as a replayable candidate (its registered words, breaks and events), for the claim-level re-verification at the open; its words must hash to the reference's digest."""
    tr = clear_trajectories(rd4_dir, session)
    c = tr["candidates_by_cid"].get(int(record_reference["cid"]))
    if c is None or int(c["iteration"]) != int(record_reference["iteration"]) or c["kind"] != record_reference["kind"]:
        raise ValueError(f"the record reference names candidate {record_reference['cid']} of iteration {record_reference['iteration']} ({record_reference['kind']}), which rd4's registry does not hold")
    w = registry_words(rd4_dir, session).get(int(c["cid"]))
    if w is None:
        raise ValueError(f"rd4's registry holds no words for candidate {c['cid']}")
    if c["kind"] == "t":
        w = w[:int(c["event_j"])]
    if len(w) != int(record_reference["words"]) or mcell.words_digest(w) != record_reference["native_action_digest"]:
        raise ValueError("the record's registered words do not hash to the reference's native action digest")
    return {"kind": "clear", "arm": "T", "iteration": int(c["iteration"]), "cum_before": int(c["cum_before"]), "event_j": int(c["event_j"]), "t": c.get("t"), "words": w,
            "breaks": [[int(a), int(b)] for a, b in c["breaks"] if int(a) <= len(w)], "first": {"clear": int(record_reference["completion_input_tick"])},
            "cid": INHERITED_CID_BASE - 1, "rd4_cid": int(c["cid"]), "inherited": True, "record": True, "source": f"runs/m8_rd_rd4/sessions/{session}/ledger_T.json"}


def plan_inherited5(inherited: Sequence[Mapping[str, Any]], done: Mapping[int, Mapping[str, Any]], batch: int = BATCH) -> List[Tuple[Dict[str, Any], int]]:
    """The next inherited descriptive replays (<= `batch`), fastest first, each counted over its whole trajectory."""
    return [(dict(c), len(bytes(c["words"]))) for c in inherited if c["cid"] not in done][:batch]


def inherited_record(rep: Mapping[str, Any], cand: Mapping[str, Any]) -> Dict[str, Any]:
    """The reported fact of one inherited descriptive replay: exact or not (the engine's exactness and the clock check), both clocks, the problems."""
    problems = exactness5(rep, cand)
    facts = rep.get("clear_facts") or {}
    return {"rd4_cid": int(cand["rd4_cid"]), "replay_cid": int(cand["cid"]), "iteration": int(cand["iteration"]), "registered_clear_tick": clear_tick(cand), "words": len(bytes(cand["words"])),
            "native_action_digest": mcell.words_digest(bytes(cand["words"])), "exact": not problems, "engine_exact": bool(rep.get("exact")), "problems": problems,
            "completion_input_tick": facts.get("completion_input_tick"), "completion_time_passed": facts.get("completion_time_passed"), "t": rep.get("t"), "label": rep.get("label"),
            "trace": rep.get("trace"), "reported_only": True}


def inherited_ticks(inherited: Sequence[Mapping[str, Any]]) -> int:
    return sum(len(bytes(c["words"])) for c in inherited)
