"""M8-sd2: the claims plan `m8_sd2_claims_v1` for the second speed session (pure; the frozen claims engine `m8_rd_claims` and sd1's plan `m8_sd1_claims` are imported, never edited).

The plan is sd1's, unchanged (docs/rl_m8_sd2_proposal_2026-10-12.md section 1.1): the pool = the `clear`-kind candidates whose registered clear tick is below T_rec, replayed three at
a time fastest first until the first EXACT replay (an inexact one is INVALID, never skipped); the INCOMPLETE test reads only the pool candidates at or below T_rec - M; `left`, `l0` and
`t` candidates are never replayed; exactness = the engine's plus the replay's completion_input_tick equal to the registered clear tick. What changes is the PREDECESSOR the inherited
descriptive rule reads: every clear-event trajectory of sd1's registry that no sd1 replay verified (read from sd1's ledger_T.json, candidates_T.jsonl.gz and replays.jsonl by that rule
and nothing else) is replayed after the pool as a reported fact. On the real sd1 tree that set is EMPTY (sd1's one clear trajectory was verified by sd1); rd4's three trajectories are
sd1's exact facts and are not replayed again. The record candidate is sd1's clear-kind candidate (its registered words must hash to the reference's digest).

The readers here are generic over the predecessor session: sd1's JSONL registry files open with a stamped header row, which they skip, and sd1's replays.jsonl holds the three
inherited replay rows (cids outside sd1's registry), which they skip too. No cid, iteration or clock of any candidate appears in this module.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

import m8_rd_cells as mcell
import m8_rd_claims as mclaims
import m8_sd1_claims as cl5

CLAIMS6_CONTRACT = "m8_sd2_claims_v1"
PREDECESSOR = "sd1"
BATCH = cl5.BATCH
INHERITED_CID_BASE = cl5.INHERITED_CID_BASE
# sd1's plan, unchanged
clear_tick = cl5.clear_tick
pool5 = cl5.pool5
progress_pool5 = cl5.progress_pool5
pool_sizes5 = cl5.pool_sizes5
exact_clear_clock = cl5.exact_clear_clock
plan_replays5 = cl5.plan_replays5
exactness5 = cl5.exactness5
verified_clear_record = cl5.verified_clear_record
plan_inherited5 = cl5.plan_inherited5
inherited_ticks = cl5.inherited_ticks


def contract_digest() -> str:
    d = {"contract": CLAIMS6_CONTRACT, "base": cl5.CLAIMS5_CONTRACT, "base_digest": cl5.contract_digest(), "engine": mclaims.CLAIMS_CONTRACT, "engine_digest": mclaims.contract_digest(),
         "pool": "clear-kind candidates with first.clear < T_rec, ordered by (first.clear, cid)", "batch": BATCH,
         "order": "fastest first, three at a time, until the first exact replay; the pool then closes; an inexact replay is INVALID, never skipped",
         "incomplete_reads": "pool candidates with first.clear <= T_rec - M left unverified at a cap before any exact replay",
         "never_replayed": ["left", "l0", "t"], "exactness": "the engine's exactness and completion_input_tick == first.clear; completion_time_passed recorded",
         "inherited_descriptive": f"every clear-event trajectory of {PREDECESSOR}'s registry that no {PREDECESSOR} replay verified; after the pool; reported only; inexact -> flag INHERITED_REPLAY_INEXACT",
         "predecessor": PREDECESSOR, "record_candidate": f"{PREDECESSOR}'s clear-kind candidate named by the record reference; its registered words must hash to the reference's digest"}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the predecessor's registry (read only; header rows and inherited replay rows skipped) ----------------------------------------------------------------


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def registry_words(pred_dir: Path, session: str = PREDECESSOR) -> Dict[int, bytes]:
    """cid -> words of every candidate of the predecessor's registry (candidates_T.jsonl.gz, words_hex); a stamped header row carries neither key and is skipped."""
    p = Path(pred_dir) / "sessions" / session / "candidates_T.jsonl.gz"
    out: Dict[int, bytes] = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                d = json.loads(ln)
                if "cid" in d and "words_hex" in d:
                    out[int(d["cid"])] = bytes.fromhex(d["words_hex"])
    return out


def predecessor_replays(pred_dir: Path, session: str = PREDECESSOR, *, include_inherited: bool = False) -> List[Dict[str, Any]]:
    """The rows of the predecessor's replays.jsonl that are replays of ITS OWN candidates: the stamped header row and (unless asked) its inherited descriptive replays are skipped."""
    p = Path(pred_dir) / "sessions" / session / "verification" / "replays.jsonl"
    if not p.is_file():
        return []
    out: List[Dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("header") is True or "cid" not in r:
            continue
        if r.get("inherited") and not include_inherited:
            continue
        out.append(r)
    return out


def clear_trajectories6(pred_dir: Path, session: str = PREDECESSOR) -> Dict[str, Any]:
    """The predecessor's registered clear-event trajectories (one per clearing job, by iteration) and which of them one of ITS replays verified (an exact replay with the clear facts whose
    candidate belongs to that iteration). Reads only."""
    pred_dir = Path(pred_dir)
    led = _read(pred_dir / "sessions" / session / "ledger_T.json")
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
    for r in predecessor_replays(pred_dir, session):
        if r.get("exact") and r.get("clear") and int(r["cid"]) in by_cid:
            verified.setdefault(int(by_cid[int(r["cid"])]["iteration"]), []).append(int(r["cid"]))
    for it, j in jobs.items():
        j["verified_by_predecessor"] = sorted(verified.get(it, []))
    return {"jobs": [jobs[it] for it in sorted(jobs, key=lambda i: (jobs[i]["first_clear"], i))], "candidates_by_cid": by_cid, "replays_exact_clear": sum(len(v) for v in verified.values()),
            "predecessor": session}


def inherited_unverified_clears6(pred_dir: Path, session: str = PREDECESSOR) -> List[Dict[str, Any]]:
    """Every clear-event trajectory of the predecessor's registry that none of its replays verified, as replayable candidates (the clear-kind candidate's full words, breaks, first events and
    clear tick), fastest first. The rule, and nothing else, selects them. On the real sd1 tree: none."""
    tr = clear_trajectories6(pred_dir, session)
    words = registry_words(pred_dir, session)
    out: List[Dict[str, Any]] = []
    for j in tr["jobs"]:
        if j["verified_by_predecessor"] or j["clear_cid"] is None:
            continue
        c = tr["candidates_by_cid"][j["clear_cid"]]
        w = words.get(int(c["cid"]))
        if w is None or len(w) != int(c.get("length", len(w))) or int(c["event_j"]) != clear_tick(c):
            raise ValueError(f"{session} candidate {c['cid']}: its stored words or clear tick are inconsistent")
        out.append({"kind": "clear", "arm": "T", "iteration": int(c["iteration"]), "cum_before": int(c["cum_before"]), "event_j": int(c["event_j"]), "t": c.get("t"),
                    "words": w, "breaks": [[int(a), int(b)] for a, b in c["breaks"]], "first": dict(c["first"]), "cid": INHERITED_CID_BASE + int(c["cid"]), "pred_cid": int(c["cid"]),
                    "pred_session": session, "inherited": True, "source": f"sessions/{session}/ledger_T.json of the predecessor"})
    out.sort(key=lambda c: (clear_tick(c), c["pred_cid"]))
    return out


def record_candidate6(pred_dir: Path, record_reference: Mapping[str, Any], session: str = PREDECESSOR) -> Dict[str, Any]:
    """The record itself as a replayable candidate (its registered words, breaks and events), for the claim-level re-verification at the open; its words must hash to the reference's digest."""
    tr = clear_trajectories6(pred_dir, session)
    c = tr["candidates_by_cid"].get(int(record_reference["cid"]))
    if c is None or int(c["iteration"]) != int(record_reference["iteration"]) or c["kind"] != record_reference["kind"]:
        raise ValueError(f"the record reference names candidate {record_reference['cid']} of iteration {record_reference['iteration']} ({record_reference['kind']}), which {session}'s registry does not hold")
    if c["kind"] != "clear":
        raise ValueError(f"the record reference names a {c['kind']} candidate; a record is a clear (its left twin shares the words and is not the record)")
    w = registry_words(pred_dir, session).get(int(c["cid"]))
    if w is None:
        raise ValueError(f"{session}'s registry holds no words for candidate {c['cid']}")
    if c["kind"] == "t":
        w = w[:int(c["event_j"])]
    if len(w) != int(record_reference["words"]) or mcell.words_digest(w) != record_reference["native_action_digest"]:
        raise ValueError("the record's registered words do not hash to the reference's native action digest")
    return {"kind": "clear", "arm": "T", "iteration": int(c["iteration"]), "cum_before": int(c["cum_before"]), "event_j": int(c["event_j"]), "t": c.get("t"), "words": w,
            "breaks": [[int(a), int(b)] for a, b in c["breaks"] if int(a) <= len(w)], "first": {"clear": int(record_reference["completion_input_tick"])},
            "cid": INHERITED_CID_BASE - 1, "pred_cid": int(c["cid"]), "pred_session": session, "inherited": True, "record": True, "source": f"sessions/{session}/ledger_T.json of the predecessor"}


def inherited_record6(rep: Mapping[str, Any], cand: Mapping[str, Any]) -> Dict[str, Any]:
    """The reported fact of one inherited descriptive replay: exact or not (the engine's exactness and the clock check), both clocks, the problems."""
    problems = exactness5(rep, cand)
    facts = rep.get("clear_facts") or {}
    return {"pred_cid": int(cand["pred_cid"]), "pred_session": cand.get("pred_session"), "replay_cid": int(cand["cid"]), "iteration": int(cand["iteration"]), "registered_clear_tick": clear_tick(cand),
            "words": len(bytes(cand["words"])), "native_action_digest": mcell.words_digest(bytes(cand["words"])), "exact": not problems, "engine_exact": bool(rep.get("exact")), "problems": problems,
            "completion_input_tick": facts.get("completion_input_tick"), "completion_time_passed": facts.get("completion_time_passed"), "t": rep.get("t"), "label": rep.get("label"),
            "trace": rep.get("trace"), "reported_only": True}
