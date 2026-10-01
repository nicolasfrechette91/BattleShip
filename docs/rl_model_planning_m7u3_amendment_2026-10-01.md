# M7u3 amendment 1: hard wall cap 3,600 s -> 4,500 s, and the replication-readout label (2026-10-01)

**Status.** Two minimal, user-authorised changes made **before any M7u3 native tick** (no BattleShip process has been launched
for M7u3; `runs/m7u3` does not exist). Nothing is committed or pushed.

## 1. The cap amendment

| item | before | after |
| --- | --- | --- |
| global hard wall cap (`GLOBAL_CAP_S`, from launch) | 3,600 s | **4,500 s** |

**Reason.** The decisions record (§3) projected a pessimistic total of **3,516 s** against the 3,600 s cap: an 84 s margin
(2.3 %). A run only slightly slower than that stack would end **INCOMPLETE on timing** and waste the run (the evaluation
results would be saved but the rule would not be applied). With 4,500 s the same pessimistic projection leaves a 984 s margin
(21.9 %). The projected (non-pessimistic) total, 2,103 s, is unchanged.

**Changed nothing else:** no threshold, no tick budget (197,839), no per-phase wall cap (p1 120 / training pool 750 / refit 900
/ goal pool 750 / goals 120 / evaluation 1,500 / replays + analysis 900 s), no memory cap (main 3,072 MB; tree 9,216 MB
private and 4,096 MB working set; system >= 1,024 MB available and >= 2,048 MB free commit), no readiness minimum, no
eligibility, arm, goal, seed, rule or model. The rule digest is unchanged (`e56d9fed…`).

Edits (`rl/m7u3_gate.py`, `rl/m7u3_tests.py`):
- `GLOBAL_CAP_S = 3600` -> `4500`; two docstrings say 4,500 s instead of "60-minute".
- `unit_accounting` asserts `GLOBAL_CAP_S == 4500` and reports the cap in its failure message.
- `unit_pools_and_caps` builds its global-cap clock with `global_cap=gate.GLOBAL_CAP_S` (before, it used m7u1's default of
  3,600 s, so it did not exercise the gate's own cap).

**Known cosmetic point.** The stop message of m7u1's `Clock` is the literal text `"60-minute cap reached (<elapsed> s)"`; it is
m7u1's file (unchanged) and it will say "60-minute" even though the cap is 4,500 s if it is ever hit. The elapsed seconds in
the message and the recorded `global_cap_s` in the run state are authoritative.

## 2. The replication-readout label (output wording only)

The M7u2 replication readout (P_frozen versus RC) applies only the **two evaluable** M7u2 PASS conditions (n_P >= 6 and a
lead over RC of >= 6, one unit per goal); the third (`b_S - c_S >= 5` against a scrambled-command control of the *frozen*
model) cannot be evaluated because decision 5 removed S_frozen. Every appearance of the readout is labelled
**"partial replication (S condition not evaluable)"**:

- `rl/m7u3_rule.py`: constant `REPLICATION_READING_LABEL`; `replication_readout` returns it as `reading_label` in every case
  (including `UNAVAILABLE`). The enumerated `label` values and thresholds are unchanged; `apply()` does not reference the
  readout (a test checks this) and the rule digest is unchanged.
- `rl/m7u3_tests.py`: the replication test asserts the label for several outcomes and for `UNAVAILABLE`.
- The results record uses the same wording wherever the readout appears.

## 3. Re-verification on the amended code

| check | result |
| --- | --- |
| `python rl/m7u3_rule.py self-test` | `{"rule": "m7u3_refit_rule_v1", "digest": "e56d9fed952a81b8726804c9c7474da1f962ca1fa47b75ff91a6dfa0c55c8679", "problems": []}` |
| `python rl/m7u3_tests.py unit` after the cap edit | 22 / 22 passed (263 s) |
| `python rl/m7u3_tests.py unit` after the label edit (final code) | 22 / 22 passed; the rule self-test is clean again (digest unchanged) |

## 4. Files

| file | sha256 before | sha256 after |
| --- | --- | --- |
| `rl/m7u3_gate.py` | `4aca3e604b9b284a…` | `53e9dad84313d7a1…` |
| `rl/m7u3_tests.py` | `26a44633fb5ad282…` | `04faa91d11c11a36…` |
| `rl/m7u3_rule.py` | `d09e2330f6dd978a…` | `f95fe97b5d05c697…` |
| `rl/m7u3_refit.py` | `73bbda05…` | unchanged (attested) |
| `rl/m7u3_goals.py`, `rl/m7u3_analysis.py` | `2f92c5e7…`, `0e017eac…` | unchanged |
| proposal | `4590c0b40f5701f6…` | unchanged (byte-identical) |
| decisions record | `aa5773a79c8a3dea…` | unchanged (no hash had been recorded before this session; its modification time, 12:11, precedes the final preparation outputs) |

The pre-amendment `m7u3_{gate,tests,rule}.py` were rebuilt by reversing exactly these edits and are byte-identical to the
hashes above (`4aca3e60…`, `26a44633…`, `d09e2330…`); they are kept in the D: source snapshot under `prepared_reference/` with
a unified diff.

Verified unchanged before the amendment: HEAD = origin/main = `1a68a7b`, no tracked file modified, the nine m7u1 files equal
HEAD, the four M7u2 files equal the hashes in M7u2's approval, P_retrain parameter digest
`13fa9cdbd143249a90c57b576b131c7ebd0edbbc0141f9cbbec19d4f58c916d7`, `runs/m7u3` absent, no BattleShip process.
