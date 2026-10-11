#!/usr/bin/env python3
"""Writes docs/rl_m8_sd1_approval.json (the M8-sd1 approval) from the freshly computed identity, AFTER the verified sd1 source snapshot (the approval names the snapshot's digest) and
tied to HEAD (the snapshot must have been taken at the current HEAD, and the approval records it). The authorisation is quoted VERBATIM from a file the user supplies (the authorising
message, one line per line) together with the date the user wrote it; nothing is hard-coded.

    python -B -X utf8 tools/m8_sd1/write_approval.py --session sd1 --snapshot D:/BattleShip_source_snapshots/<date>_m8_sd1 \\
        --independent "<how the snapshot was independently re-hashed>" --authorisation-file <the verbatim authorisation text> --authorised-on YYYY-MM-DD \\
        [--source "the user's message of YYYY-MM-DD (Part C)"]

The record carries identity() in full (the nine contract digests, the record reference, the margin, the tiers, the pins, the base facts of the four earlier trees with the inherited record,
both overlay digests, the code and tool hashes, the source fingerprint, the D: folders), the source snapshot, the verbatim authorisation with its date, the sd line's consequences for every
outcome, and the task block with created_utc.

Refuses: an existing approval (never overwritten); a snapshot that is not PASS, not an sd1 snapshot, or not at the current HEAD; a snapshot whose source fingerprint differs from the
current one; an open check with problems; an empty authorisation; a malformed date. Nothing else is written.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "rl"))
sys.path.insert(0, str(REPO / "rl" / "tools"))

import m8_sd1_artifacts as art  # noqa: E402
import m8_sd1_rule as rule5  # noqa: E402
import m8_sd1_session as S  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, choices=["sd1"], help="the session this approval authorises (sd1)")
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--independent", required=True)
    ap.add_argument("--authorisation-file", type=Path, required=True)
    ap.add_argument("--authorised-on", required=True, help="YYYY-MM-DD, the date of the user's authorising message")
    ap.add_argument("--source", default=None, help="where the authorisation comes from (default: the user's message of <date> (Part C))")
    a = ap.parse_args()
    if not sys.flags.dont_write_bytecode:
        print("refused: run with python -B")
        return 2
    target = S.APPROVAL
    if target.exists():
        print(f"refused: {target} exists (never overwritten)")
        return 2
    sj = a.snapshot / "snapshot.json"
    if not sj.is_file():
        print(f"refused: no snapshot record at {sj}")
        return 2
    snap = json.loads(sj.read_text(encoding="utf-8-sig"))
    if snap.get("result") != "PASS":
        print("refused: the snapshot record is not PASS")
        return 2
    if snap.get("tool") != "m8_sd1_source_snapshot_v1":
        print(f"refused: the snapshot is {snap.get('tool')!r}, not an sd1 snapshot (rl/m8_sd1_snapshot.py snapshot)")
        return 2
    text = [ln.rstrip("\r\n") for ln in a.authorisation_file.read_text(encoding="utf-8-sig").splitlines()]
    if not any(ln.strip() for ln in text):
        print("refused: the authorisation file is empty")
        return 2
    d = a.authorised_on
    if len(d) != 10 or d[4] != "-" or d[7] != "-" or not d.replace("-", "").isdigit() or not S._real_date(d):
        print("refused: --authorised-on must be a real YYYY-MM-DD date")
        return 2
    ident = S.identity()
    if snap.get("git_head") != ident["git_head"]:
        print(f"refused: the snapshot was taken at {snap.get('git_head')}, HEAD is {ident['git_head']}")
        return 2
    if snap.get("source_fingerprint") != ident["source_fingerprint"]:
        print(f"refused: the snapshot's source fingerprint {snap.get('source_fingerprint')} differs from the current {ident['source_fingerprint']}")
        return 2
    op = S.open_protocol5(record_reference=S.RECORD_REFERENCE)
    if not op["ok"]:
        print(json.dumps({"refused": "the open check has problems", "problems": op["problems"]}, indent=1))
        return 2
    cov = S.ses1.combined_coverage()
    t_rec, m = rule5.T_REC, rule5.MARGIN
    rec = dict(ident,
               approval=f"APPROVED: M8-sd1, exactly one detached speed-search session, once (Part C of the launch session of {d}): approval with fresh identities (the record reference "
                        f"{t_rec} / {rule5.T_REC_TIME_PASSED} pinned, the margin {m}, the progress bar {t_rec - m}, the nine contract digests, both overlay digests, the inherited record "
                        "facts of rd4's closed tree, the source fingerprint), the verified D: source snapshot named below, the preflight (the four earlier trees against their increments, the "
                        "open protocol R1-R5, the D: coverage, readiness), one session as designed (the open: P1, 16 identity replays and the record re-verified in full; exploration under "
                        "m8_rd_select_v4 from iteration 13,886; the clear pool replayed fastest first and the inherited descriptive replays after it; the close checks; the decision under "
                        "m8_sd1_rule_v1), waited to completion; no retries, extensions, repairs, and NO sd2 and NO rd5; afterwards the D: increment, the unchanged earlier trees, the coverage "
                        "and the results record",
               revision=1,
               authorisation={"source": a.source or f"the user's message of {d} (Part C)", "authorised_on": d, "text": text},
               source_snapshot={"dest": str(a.snapshot), "snapshot_json_sha256": hashlib.sha256(sj.read_bytes()).hexdigest(), "result": snap["result"], "files": snap["n_files"],
                                "git_head": snap["git_head"], "source_fingerprint": snap.get("source_fingerprint"), "tool": snap.get("tool"), "independent_verification": a.independent},
               line_consequence={"line": rule5.LINE, "if_this_session_is": {
                   "PROGRESS": "the best verified clear (completion_input_tick <= 2,291) is the archive's new record reference; an sd2 under the same design may be proposed (its own authorisation)",
                   "RECORD_BELOW_MARGIN": "the best verified clear (2,291 < completion_input_tick < 2,315) is the new reference, not progress; an sd2 may be proposed (its own authorisation)",
                   "NO_SHORTER_CLEAR": "the reference stays 2,315; an sd2 may be proposed only with a stated reason read from the diagnostics",
                   "INCOMPLETE": "counts as sd1 once exploration started (a repeat is sd2, with its reason stated); does not count before exploration started (repair and a new approval, then sd1 again)",
                   "INVALID": "repair and a new approval; whether it counts is the user's decision (recorded as None)"},
                   "rd_line": "unchanged: sd1 neither consumes nor grants rd5", "third_session": "none without a review"},
               backup_coverage_before_approval={kk: cov.get(kk) for kk in ("ok", "source_files", "uncovered", "increments", "skipped")}, written_utc=art.utc())
    art.write_json5(target, rec, overwrite=False)
    print(json.dumps({"written": str(target), "sha256": S.sha256_file(target), "session": a.session, "snapshot_json_sha256": rec["source_snapshot"]["snapshot_json_sha256"], "git_head": ident["git_head"],
                      "source_fingerprint": ident["source_fingerprint"], "record_reference": ident["record_reference"]["completion_input_tick"], "margin": ident["margin"],
                      "inherited_descriptive": op["inherited_summary"], "authorised_on": d}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
