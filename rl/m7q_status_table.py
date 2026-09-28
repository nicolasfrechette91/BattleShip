"""M7q: the character-independent action-class table `btt_action_class_table_v2` (fighter status id -> class).

Derived exactly like v1 (rl/m7n_status_table.py: the decomp enums, classified by enumerator NAME, per-character own
ranges, the explicit `unmapped` fallback), with three rule changes and one new class, all from the mechanics audit
(docs/rl_mechanics_observation_audit_2026-09-28.md) and the v4 proposal (docs/rl_observation_v4_proposal_2026-09-28.md):

    FallSpecial                         airborne  -> helpless      no new jump / attack / special until landing
                                                                   (steering, fast fall and the platform drop remain)
    StopCeil                            airborne  -> air_lock      temporary move lock (interrupt and physics NULL),
                                                                   ends into Fall with the double jump kept
    LandingLight, LandingHeavy          landing   -> landing_free  interruptible from animation frame 4
    LandingAir*, LandingAirNull,        landing   -> landing_lag   proc_interrupt NULL until the animation ends
    LandingFallSpecial                                             (LandingFallSpecial: validated for Mario only,
                                                                   recorded as character_dependent)

The v1 file, id and digest are not modified. Validation status is part of the table: only Mario is validated.

    python rl/m7q_status_table.py build     # regenerate rl/data/m7n_action_classes_v2.json from the decomp headers
    python rl/m7q_status_table.py check     # the checked-in table equals a fresh derivation (digest included)
    python rl/m7q_status_table.py show mario
    python rl/m7q_status_table.py diff      # every (character, id) whose class differs from v1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7n_status_table as v1  # noqa: E402

REPO_ROOT = v1.REPO_ROOT
DECOMP = v1.DECOMP
TABLE_PATH = RL_DIR / "data" / "m7n_action_classes_v2.json"
TABLE_ID = "btt_action_class_table_v2"

CLASSES: Tuple[str, ...] = (
    "idle_ground", "dash_run", "jump_squat", "airborne", "helpless", "air_lock", "landing_free", "landing_lag",
    "crouch_pass", "shield", "roll", "damage", "cliff", "attack_ground", "attack_air", "special_n", "special_hi",
    "special_lw", "item", "appear_entry", "dead", "other", "unmapped",
)
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}
UNMAPPED = v1.UNMAPPED
CHARACTER_DIRS = v1.CHARACTER_DIRS
VALIDATED = v1.VALIDATED

# Common enumerators whose v2 class is correct for Mario but depends on a per-character argument elsewhere
# (ftCommonFallSpecialSetStatus's is_allow_interrupt): recorded in the table, checked at character onboarding.
CHARACTER_DEPENDENT = ("LandingFallSpecial",)

RULE_CHANGES = {
    "FallSpecial": ("airborne", "helpless"), "StopCeil": ("airborne", "air_lock"),
    "LandingLight": ("landing", "landing_free"), "LandingHeavy": ("landing", "landing_free"),
    "LandingAir*": ("landing", "landing_lag"), "LandingFallSpecial": ("landing", "landing_lag"),
}


def classify_v2(short: str) -> str:
    """v2 class of one enumerator by its short name: v1's classify() with the v2 rule changes applied first."""
    if short == "FallSpecial":
        return "helpless"
    if short == "StopCeil":
        return "air_lock"
    if short in ("LandingLight", "LandingHeavy"):
        return "landing_free"
    if short.startswith("LandingAir") or short == "LandingFallSpecial":
        return "landing_lag"
    c = v1.classify(short)
    if c == "landing":   # any other Landing* name (none today) would be a new case for review, never silently v1's
        raise ValueError(f"{short}: unclassified landing status under v2")
    return c


def _class_map(values: Dict[str, int], prefix_re: str) -> Tuple[Dict[int, str], Dict[int, str]]:
    by_id: Dict[int, str] = {}
    names: Dict[int, str] = {}
    for name, value in values.items():      # insertion order = declaration order; aliases never override
        if value in by_id:
            continue
        by_id[value] = classify_v2(v1._short(name, prefix_re))
        names[value] = name
    return by_id, names


def derive() -> Dict[str, Any]:
    common_text = (DECOMP / "ftdef.h").read_text(encoding="utf-8", errors="replace")
    common = v1.parse_enum(common_text, "FTCommonStatus")
    special_start = common["nFTCommonStatusSpecialStart"]
    common_classes, common_names = _class_map({k: v for k, v in common.items() if v < special_start},
                                              r"^nFTCommonStatus")
    dependent = {str(i): {"class": common_classes[i], "reason": "ftCommonFallSpecialSetStatus(..., is_allow_interrupt) "
                          "is a per-character argument; Mario passes FALSE (uninterruptible), other characters unverified"}
                 for i, n in common_names.items() if v1._short(n, r"^nFTCommonStatus") in CHARACTER_DEPENDENT}
    characters: Dict[str, Any] = {}
    for key, d in CHARACTER_DIRS.items():
        header = DECOMP / "ftchar" / d / f"{d}.h"
        text = header.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"typedef\s+enum\s+(ft\w+Status)\s*\{", text)
        if not m:
            raise ValueError(f"{header}: no ft<Char>Status enum")
        enum_name = m.group(1)
        values = v1.parse_enum(text, enum_name, known=common)
        own = {k: v for k, v in values.items() if v >= special_start}
        classes, names = _class_map(own, r"^nFT\w+?Status")
        characters[key] = {
            "header": header.relative_to(REPO_ROOT).as_posix(), "enum": enum_name, "validated": key in VALIDATED,
            "ids": {str(i): classes[i] for i in sorted(classes)}, "names": {str(i): names[i] for i in sorted(names)},
            "count": len(classes), "max_id": max(classes) if classes else special_start - 1,
        }
    table = {
        "table_id": TABLE_ID, "classes": list(CLASSES), "unmapped_class": UNMAPPED,
        "derived_from": v1.TABLE_ID, "rule_changes": {k: list(v) for k, v in RULE_CHANGES.items()},
        "character_dependent": dependent,
        "common_header": (DECOMP / "ftdef.h").relative_to(REPO_ROOT).as_posix(),
        "special_start": special_start,
        "common": {str(i): common_classes[i] for i in sorted(common_classes)},
        "common_names": {str(i): common_names[i] for i in sorted(common_names)},
        "characters": characters,
        "rule": "classify_v2() of rl/m7q_status_table.py on the enumerator name; an id outside the table -> 'unmapped'",
    }
    table["sha256"] = v1.table_digest(table)
    return table


table_digest = v1.table_digest


def load_table(path: Path = TABLE_PATH) -> Dict[str, Any]:
    table = json.loads(path.read_text(encoding="utf-8"))
    if table.get("table_id") != TABLE_ID or table.get("sha256") != table_digest(table):
        raise ValueError(f"{path}: not a valid {TABLE_ID} (id or digest)")
    if list(table.get("classes", [])) != list(CLASSES):
        raise ValueError(f"{path}: class list differs from the module's")
    return table


def aerial_attack_ids(table: Dict[str, Any]) -> Tuple[int, ...]:
    """The common ids of the aerial attack statuses (nFTCommonStatusAttackAir*): the only statuses whose motion
    flag 1 the v4 observation interprets (as the landing-lag flag)."""
    return tuple(sorted(int(i) for i, n in table["common_names"].items() if n.startswith("nFTCommonStatusAttackAir")))


class ActionClassifier:
    """id -> v2 class index for one character (common range + that character's own range; else `unmapped`)."""

    def __init__(self, table: Dict[str, Any], character: str):
        if table.get("table_id") != TABLE_ID:
            raise ValueError(f"table {table.get('table_id')!r} is not {TABLE_ID}")
        if character not in table["characters"]:
            raise ValueError(f"no action-class table for character {character!r} (known: {sorted(table['characters'])})")
        self.table_id = table["table_id"]
        self.table_sha256 = table["sha256"]
        self.character = character
        self.validated = bool(table["characters"][character]["validated"])
        self.special_start = int(table["special_start"])
        self._map: Dict[int, int] = {int(k): CLASS_INDEX[v] for k, v in table["common"].items()}
        self._map.update({int(k): CLASS_INDEX[v] for k, v in table["characters"][character]["ids"].items()})
        self.unmapped_index = CLASS_INDEX[UNMAPPED]
        self.unmapped_seen: Dict[int, int] = {}

    def index(self, status_id: int) -> int:
        i = self._map.get(int(status_id))
        if i is None:
            self.unmapped_seen[int(status_id)] = self.unmapped_seen.get(int(status_id), 0) + 1
            return self.unmapped_index
        return i

    def name(self, status_id: int) -> str:
        return CLASSES[self.index(status_id)]


def diff_v1(table: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every (scope, id) whose class differs between the stored v1 table and this v2 table."""
    t2 = table or load_table()
    t1 = v1.load_table()
    out: Dict[str, Any] = {"common": {}, "characters": {}}
    for i, c in t2["common"].items():
        if t1["common"].get(i) != c:
            out["common"][i] = {"name": t2["common_names"][i], "v1": t1["common"].get(i), "v2": c}
    for ch, d in t2["characters"].items():
        for i, c in d["ids"].items():
            if t1["characters"][ch]["ids"].get(i) != c:
                out["characters"].setdefault(ch, {})[i] = {"name": d["names"][i], "v1": t1["characters"][ch]["ids"].get(i), "v2": c}
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("build", "check", "show", "diff"))
    ap.add_argument("character", nargs="?", default="mario")
    args = ap.parse_args(argv)
    table = derive()
    if args.command == "build":
        TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TABLE_PATH.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {TABLE_PATH.relative_to(REPO_ROOT).as_posix()} sha256 {table['sha256'][:16]} "
              f"special_start {table['special_start']} characters {len(table['characters'])} classes {len(CLASSES)}")
        return 0
    if args.command == "check":
        stored = load_table()
        same = stored == table
        print(f"{'IDENTICAL' if same else 'DIFFERENT'}: stored {stored['sha256'][:16]} derived {table['sha256'][:16]}")
        return 0 if same else 1
    if args.command == "diff":
        print(json.dumps(diff_v1(table), indent=1))
        return 0
    ch = table["characters"][args.character]
    counts: Dict[str, int] = {}
    for c in list(table["common"].values()) + list(ch["ids"].values()):
        counts[c] = counts.get(c, 0) + 1
    print(json.dumps({"character": args.character, "validated": ch["validated"], "special_start": table["special_start"],
                      "own_ids": {k: f"{ch['names'][k]} -> {v}" for k, v in ch["ids"].items()},
                      "class_counts": counts, "aerial_attack_ids": aerial_attack_ids(table)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
