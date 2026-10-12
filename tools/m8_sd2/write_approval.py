#!/usr/bin/env python3
"""Writes docs/rl_m8_sd2_approval.json (the M8-sd2 approval) from the freshly computed identity, AFTER the verified sd2 source snapshot (the approval names the snapshot's digest) and
tied to HEAD (the snapshot must have been taken at the current HEAD, and the approval records it). The authorisation is quoted VERBATIM from a file the user supplies (the authorising
message, one line per line) together with the date the user wrote it; nothing is hard-coded.

    python -B -X utf8 tools/m8_sd2/write_approval.py --session sd2 --snapshot D:/BattleShip_source_snapshots/<date>_m8_sd2 \\
        --independent "<how the snapshot was independently re-hashed>" --authorisation-file <the verbatim authorisation text> --authorised-on YYYY-MM-DD \\
        [--source "the user's message of YYYY-MM-DD (Part C)"]

The record carries identity() in full (the nine contract digests with m8_rd_select_v4 at the new reference, sd1's session digest at the old one, the record reference and the previous one,
the margin, the tiers, the pins, the base facts of the five earlier trees with the inherited record, both overlay digests, the code and tool hashes, the source fingerprint, the D: folders),
the source snapshot, the verbatim authorisation with its date, the sd line's consequences for every outcome (NOT_STARTED as its own row), the rd line, the review requirement, and the task block
with created_utc. On success it prints THE S2 RULE: from here until the launch, no commit, no edit of any pinned document, no `runs_backup.py verify` or `backup` of any existing increment,
no new folder on D:.

Refuses: an existing approval (never overwritten); a snapshot that is not PASS, not an sd2 snapshot, or not at the current HEAD; a snapshot whose source fingerprint differs from the
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

import m8_sd2_artifacts as art  # noqa: E402
import m8_sd2_rule as rule6  # noqa: E402
import m8_sd2_session as S  # noqa: E402

SNAPSHOT_TOOL = "m8_sd2_source_snapshot_v1"
S2_RULE = ("S2 RULE, from this approval until the launch: no commit, no edit of any pinned document, no `runs_backup.py verify` or `backup` of any existing increment, no new folder on D:. "
           "Any of these makes the full preflight or the run's own preflight refuse (the approval pins HEAD, every code and document hash and the D: folders' top-level files); the launcher "
           "re-checks HEAD against this approval before starting anything.")


def line_consequence() -> dict:
    t_rec, m = rule6.T_REC, rule6.MARGIN
    return {"line": rule6.LINE, "statuses": list(rule6.LINE_STATUSES), "if_this_session_is": {
        "PROGRESS": f"the best verified clear (completion_input_tick <= {t_rec - m:,}) is the archive's new record reference; an sd3 under the same design may be proposed only after a written review "
                    "(status SD3_AFTER_REVIEW_NEW_REFERENCE)",
        "RECORD_BELOW_MARGIN": f"the best verified clear ({t_rec - m:,} < completion_input_tick < {t_rec:,}) is the new reference, not progress; an sd3 only after a written review "
                               "(status SD3_AFTER_REVIEW_NEW_REFERENCE)",
        "NO_SHORTER_CLEAR": f"the reference stays {t_rec:,}; an sd3 only after a written review and with a stated reason read from the diagnostics (status SD3_AFTER_REVIEW_WITH_REASON)",
        "COUNTED_INCOMPLETE": "INCOMPLETE after exploration started: counts as sd2 (the line has had its two sessions); an sd3 only after a written review that states the cause; a verified clear "
                              "found before the stop is reported, and the review decides whether it becomes the reference",
        "NOT_STARTED": "INCOMPLETE before exploration started: does not count; sd2 may be repaired and run again as sd2 after the recorded procedure: " + rule6.NOT_STARTED_PROCEDURE,
        "INVALID": "repair and a new approval; whether it counts is the user's decision (recorded as None); no sd3 before the repair is reviewed (status REPAIR_NEEDED)"},
        "review": "every counted outcome ends in a written review before any sd3", "rd_line": "unchanged: sd2 neither consumes nor grants rd5 (sd1's copy of rd4's status is copied through)",
        "s2_rule": S2_RULE}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, choices=["sd2"], help="the session this approval authorises (sd2)")
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
    if snap.get("tool") != SNAPSHOT_TOOL:
        print(f"refused: the snapshot is {snap.get('tool')!r}, not an sd2 snapshot (rl/m8_sd2_snapshot.py snapshot)")
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
    op = S.open_protocol6(record_reference=S.RECORD_REFERENCE, previous_record_reference=S.PREVIOUS_RECORD_REFERENCE)
    if not op["ok"]:
        print(json.dumps({"refused": "the open check has problems", "problems": op["problems"]}, indent=1))
        return 2
    cov = S.ses1.combined_coverage()
    t_rec, m = rule6.T_REC, rule6.MARGIN
    rec = dict(ident,
               approval=f"APPROVED: M8-sd2, exactly one detached speed-search session, once (Part C of the launch session of {d}): approval with fresh identities (the record reference "
                        f"{t_rec} / {rule6.T_REC_TIME_PASSED} pinned from sd1's verified clear, the previous reference {S.PREVIOUS_RECORD_REFERENCE['completion_input_tick']} / "
                        f"{S.PREVIOUS_RECORD_REFERENCE['completion_time_passed']} beside it, the margin {m}, the progress bar {t_rec - m}, the nine contract digests with m8_rd_select_v4 at "
                        "the new reference and sd1's digest at the old one, both overlay digests, the inherited record facts of sd1's closed tree, the source fingerprint), the verified D: source "
                        "snapshot named below, the preflight (the five earlier trees against their increments, the open protocol R1-R5 at five levels, the D: coverage, readiness), one session "
                        "as designed (the open: P1, 16 identity replays and the record re-verified in full; exploration under m8_rd_select_v4 unchanged from iteration 17,557 with E7 at the new "
                        "bound; the clear pool replayed fastest first and the inherited descriptive replays after it; the close checks; the decision under m8_sd2_rule_v1), waited to "
                        "completion; no retries, extensions, repairs, and NO sd3 and NO rd5; afterwards the D: increment, the unchanged earlier trees, the coverage and the results record",
               revision=1,
               authorisation={"source": a.source or f"the user's message of {d} (Part C)", "authorised_on": d, "text": text},
               source_snapshot={"dest": str(a.snapshot), "snapshot_json_sha256": hashlib.sha256(sj.read_bytes()).hexdigest(), "result": snap["result"], "files": snap["n_files"],
                                "git_head": snap["git_head"], "source_fingerprint": snap.get("source_fingerprint"), "tool": snap.get("tool"), "independent_verification": a.independent},
               line_consequence=line_consequence(),
               backup_coverage_before_approval={kk: cov.get(kk) for kk in ("ok", "source_files", "uncovered", "increments", "skipped")}, written_utc=art.utc())
    art.write_json5(target, rec, overwrite=False)
    print(json.dumps({"written": str(target), "sha256": S.sha256_file(target), "session": a.session, "snapshot_json_sha256": rec["source_snapshot"]["snapshot_json_sha256"], "git_head": ident["git_head"],
                      "source_fingerprint": ident["source_fingerprint"], "record_reference": ident["record_reference"]["completion_input_tick"],
                      "previous_record_reference": ident["previous_record_reference"]["completion_input_tick"], "margin": ident["margin"],
                      "inherited_descriptive": op["inherited_summary"], "authorised_on": d}, indent=1))
    print(S2_RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
