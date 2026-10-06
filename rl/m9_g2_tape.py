"""M9-g2: the tape baseline `m9_g2_tape_baseline_v1` (decision 4; proposal 5; decision R9).

T0 (s1 only): the open-loop tape (T_clear's words by tick index, neutral after the end) at the six registered landings, 200 keyed episodes at 2,128 and 40 at
each other landing, sticky p = 0.25 on the keys `m9|g2|reach|<landing>|<k>` (the same family the close audit uses with k = 0..19 in every session). The claimed
table is written at the end of T0; the pinned table counts a tape clear only when its full replay is exact (verification tier 0) and carries p_hat and
B(landing) = max(10, ceil(20 p_hat) + 5) per landing, with the sha256 of its canonical form. A later session reads the pinned table by digest and runs the
drift check (5 keyed tape episodes at 2,128 with identical outcomes and record digests) at its open.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m9_curriculum as CU
import m9_g2_contract as G
import m9_vec as V

TAPE_CONTRACT = G.TAPE_RULE_ID
DRIFT_KEYS = 5


def _start(i: int, tau: int) -> CU.Start:
    return CU.Start(int(i), "landing", int(tau), G.TRUNK, int(tau) <= G.SHARED_PREFIX, -1)


def t0_jobs(keys: Mapping[int, int] = G.TAPE_KEYS) -> List[V.StartJob]:
    """The T0 jobs, interleaved by k across landings (every landing progresses while the pool runs), landings largest first within a k."""
    jobs: List[V.StartJob] = []
    kmax = max(keys.values())
    for k in range(kmax):
        for lam in sorted(keys, reverse=True):
            if k < keys[lam]:
                jobs.append(V.StartJob(len(jobs), _start(len(jobs), lam), G.reach_label(lam, k), driver="tape", kind="t0_tape", tier=0, job_id=f"t0_tape-{lam}-{k:03d}",
                                       extra={"landing": lam, "k": k}))
    return jobs


def drift_jobs(landing: int = 2128, n: int = DRIFT_KEYS) -> List[V.StartJob]:
    """A later session's drift check: the first n tape keys at 2,128 (identical outcomes and record digests required)."""
    return [V.StartJob(k, _start(k, landing), G.reach_label(landing, k), driver="tape", kind="drift_tape", tier=0, job_id=f"drift_tape-{landing}-{k:03d}", extra={"landing": landing, "k": k})
            for k in range(n)]


def claimed_table(records: Sequence[Mapping[str, Any]], keys: Mapping[int, int] = G.TAPE_KEYS) -> Dict[str, Any]:
    """The claimed T0 table: per landing the per-key outcomes (c = claimed clear, f = fall, h = horizon, e = ended) and the counts."""
    per: Dict[int, Dict[str, Any]] = {lam: {"keys": int(n), "outcomes": {}, "clears_claimed": 0, "n": 0} for lam, n in keys.items()}
    for r in records:
        lam = int(r["landing"])
        if lam not in per:
            continue
        row = per[lam]
        row["n"] += 1
        row["outcomes"][str(int(r["k"]))] = "c" if r["clear"] else r["end_reason"][0]
        row["clears_claimed"] += int(bool(r["clear"]))
    for lam, row in per.items():
        row["complete"] = row["n"] == row["keys"] and len(row["outcomes"]) == row["keys"]
    return {"tape": TAPE_CONTRACT, "lineage": G.TRUNK, "sticky_p": G.STICKY_P, "label": G.KEYS["reach_label"], "landings": {str(k): v for k, v in sorted(per.items(), reverse=True)},
            "complete": all(v["complete"] for v in per.values())}


def pinned_table(claimed: Mapping[str, Any], records: Sequence[Mapping[str, Any]], verified: Mapping[str, bool]) -> Dict[str, Any]:
    """The pinned baseline: a tape clear counts only when its replay is exact; p_hat and B per landing; the digest of the canonical record."""
    rows: Dict[str, Any] = {}
    by_id = {r["episode"]: r for r in records}
    for lam_s, row in dict(claimed["landings"]).items():
        lam = int(lam_s)
        ver = 0
        unver: List[str] = []
        inexact: List[str] = []
        for k_s, oc in dict(row["outcomes"]).items():
            if oc != "c":
                continue
            eid = f"t0_tape-{lam}-{int(k_s):03d}"
            v = verified.get(eid)
            if v is True:
                ver += 1
            elif v is False:
                inexact.append(eid)
            else:
                unver.append(eid)
        keys = int(row["keys"])
        pinned = row["complete"] and not unver and not inexact
        rows[lam_s] = {"keys": keys, "n": row["n"], "clears_claimed": row["clears_claimed"], "clears_verified": ver, "unverified": unver, "inexact": inexact,
                       "p_hat": round(ver / keys, 6) if keys else None, "B": G.bar_from_counts(ver, keys) if pinned else None, "pinned": pinned,
                       "outcomes": dict(row["outcomes"])}
    out = {"tape": TAPE_CONTRACT, "lineage": G.TRUNK, "sticky_p": G.STICKY_P, "label": G.KEYS["reach_label"], "bar": "max(10, ceil(20 p_hat) + 5)", "landings": rows,
           "pinned": all(v["pinned"] for v in rows.values()), "note": "a tape clear counts only when its full replay is exact; B is None where the baseline is unpinned"}
    out["sha256"] = table_digest(out)
    return out


def table_digest(table: Mapping[str, Any]) -> str:
    body = {k: v for k, v in table.items() if k not in ("sha256", "task", "created_utc")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def bars(table: Mapping[str, Any]) -> Dict[int, Optional[int]]:
    return {int(k): v.get("B") for k, v in dict(table["landings"]).items()}


def contract_description() -> Dict[str, Any]:
    return dict(G.tape_description(), drift_keys=DRIFT_KEYS)
