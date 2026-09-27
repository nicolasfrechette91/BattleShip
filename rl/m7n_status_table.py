"""M7n: the character-independent action-class table `btt_action_class_table_v1` (fighter status id -> class).

The table is DERIVED from the decomp enums, never typed by hand:
  * the common range: `typedef enum FTCommonStatus` in decomp/src/ft/ftdef.h (shared by every fighter; the
    character-specific ids start at nFTCommonStatusSpecialStart);
  * each playable character's own range: `typedef enum ft<Char>Status` in decomp/src/ft/ftchar/ft<char>/ft<char>.h.

Every enumerator is classified by its NAME (the decomp's status vocabulary), so the same rule gives the same class
for the same kind of state in every character: Mario's nFTMarioStatusSpecialHi and Link's nFTLinkStatusSpecialHi are
both `special_hi`. A character's specific ids are looked up ONLY in that character's own table: an id in the
character range of a character without a table (or an id absent from its table) maps to the explicit fallback class
`unmapped` and is counted by the observation builder. Nothing ever maps another character's id through Mario's names.

Validation status is part of the table: only characters listed in VALIDATED have had their mapping reviewed against
replayed native traces (M7n: Mario). A run on another character must first validate its mapping (M10 onboarding).

    python rl/m7n_status_table.py build     # regenerate rl/data/m7n_action_classes_v1.json from the decomp headers
    python rl/m7n_status_table.py check     # the checked-in table equals a fresh derivation (digest included)
    python rl/m7n_status_table.py show mario
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
DECOMP = REPO_ROOT / "decomp" / "src" / "ft"
TABLE_PATH = RL_DIR / "data" / "m7n_action_classes_v1.json"

TABLE_ID = "btt_action_class_table_v1"

# Column order of the `action_class` one-hot (btt_policy_obs_v3_entities). `other` = a decomp status that fits no
# class (stage hazards, capture states, ...); `unmapped` = an id absent from the character's table (the explicit
# fallback, never silently another class).
CLASSES: Tuple[str, ...] = (
    "idle_ground", "dash_run", "jump_squat", "airborne", "landing", "crouch_pass", "shield", "roll", "damage",
    "cliff", "attack_ground", "attack_air", "special_n", "special_hi", "special_lw", "item", "appear_entry", "dead",
    "other", "unmapped",
)
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}
UNMAPPED = "unmapped"

# experiment_config.KNOWN_CHARACTERS key -> decomp character directory (ftchar/<dir>/<dir>.h).
CHARACTER_DIRS: Dict[str, str] = {
    "mario": "ftmario", "fox": "ftfox", "donkey_kong": "ftdonkey", "samus": "ftsamus", "luigi": "ftluigi",
    "link": "ftlink", "yoshi": "ftyoshi", "captain_falcon": "ftcaptain", "kirby": "ftkirby", "pikachu": "ftpikachu",
    "jigglypuff": "ftpurin", "ness": "ftness",
}
VALIDATED: Tuple[str, ...] = ("mario",)

_SPECIAL = re.compile(r"Special(?:Air)?(N|Hi|Lw)")


def classify(short: str) -> str:
    """Class of one enumerator by its short name (the `nFT<Char>Status` / `nFTCommonStatus` prefix removed)."""
    m = _SPECIAL.search(short)
    if m:
        return {"N": "special_n", "Hi": "special_hi", "Lw": "special_lw"}[m.group(1)]
    s = short
    if s.startswith("Dead") or s == "Sleep":
        return "dead"
    if s in ("Entry", "EntryNull", "ActionStart") or s.startswith("Rebirth") or s.startswith("Appear"):
        return "appear_entry"
    if s in ("Wait", "ControlStart", "Turn", "TurnRun", "Appeal", "OttottoWait", "Ottotto") or s.startswith("Walk"):
        return "idle_ground"
    if s in ("Dash", "Run", "RunBrake"):
        return "dash_run"
    if s in ("KneeBend", "GuardKneeBend"):
        return "jump_squat"
    if s in ("JumpF", "JumpB", "Fall", "FallAerial", "FallSpecial", "StopCeil") or s.startswith("JumpAerial"):
        return "airborne"   # JumpAerialF/B; Kirby / Jigglypuff JumpAerialF1..5
    if s.startswith("Landing"):
        return "landing"
    if s.startswith("Squat") or s in ("Pass", "GuardPass"):
        return "crouch_pass"
    if s.startswith("Guard"):
        return "shield"
    if s.startswith("Escape"):
        return "roll"
    if s.startswith("Cliff"):
        return "cliff"
    if s.startswith("AttackAir"):
        return "attack_air"
    if (s.startswith("Damage") or s == "WallDamage" or s.startswith("Passive") or s.startswith("Down")
            or s.startswith("ShieldBreak") or s.startswith("Fura") or s.startswith("Thrown") or s.startswith("Capture")
            or s in ("Shouldered", "YoshiEgg")):
        return "damage"
    if (s in ("LightGet", "HeavyGet") or s.startswith("Lift") or s.startswith("LightThrow") or s.startswith("HeavyThrow")
            or "Swing" in s or s.startswith("LGunShoot") or s.startswith("FireFlowerShoot") or s.startswith("Hammer")):
        return "item"
    if (s.startswith("Attack") or s.startswith("Catch") or s in ("ThrowF", "ThrowB") or s.startswith("Rebound")):
        return "attack_ground"
    return "other"


# -- enum parsing ----------------------------------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def parse_enum(text: str, enum_name: str, *, known: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """Enumerator -> value of `typedef enum <enum_name> { ... }` (sequential values, `= <name>` / `= <int>` aliases;
    a reference to an enumerator of another enum is resolved through `known`)."""
    m = re.search(r"typedef\s+enum\s+" + re.escape(enum_name) + r"\s*\{(.*?)\}", _strip_comments(text), flags=re.S)
    if not m:
        raise ValueError(f"enum {enum_name} not found")
    values: Dict[str, int] = {}
    next_value = 0
    for item in m.group(1).split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            name, rhs = (x.strip() for x in item.split("=", 1))
            if re.fullmatch(r"-?\d+", rhs):
                value = int(rhs)
            elif re.fullmatch(r"0x[0-9a-fA-F]+", rhs):
                value = int(rhs, 16)
            elif rhs in values:
                value = values[rhs]
            elif known and rhs in known:
                value = known[rhs]
            else:
                raise ValueError(f"{enum_name}: cannot resolve {name} = {rhs}")
        else:
            name, value = item, next_value
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise ValueError(f"{enum_name}: unexpected enumerator {item!r}")
        values[name] = value
        next_value = value + 1
    return values


def _short(name: str, prefix_re: str) -> str:
    return re.sub(prefix_re, "", name, count=1)


def _class_map(values: Dict[str, int], prefix_re: str) -> Tuple[Dict[int, str], Dict[int, str]]:
    """id -> class and id -> defining enumerator (aliases never override the first, non-alias definition)."""
    by_id: Dict[int, str] = {}
    names: Dict[int, str] = {}
    for name, value in values.items():      # insertion order = declaration order
        if value in by_id:
            continue
        by_id[value] = classify(_short(name, prefix_re))
        names[value] = name
    return by_id, names


def derive() -> Dict[str, Any]:
    common_text = (DECOMP / "ftdef.h").read_text(encoding="utf-8", errors="replace")
    common = parse_enum(common_text, "FTCommonStatus")
    special_start = common["nFTCommonStatusSpecialStart"]
    common_classes, common_names = _class_map({k: v for k, v in common.items() if v < special_start},
                                              r"^nFTCommonStatus")
    characters: Dict[str, Any] = {}
    for key, d in CHARACTER_DIRS.items():
        header = DECOMP / "ftchar" / d / f"{d}.h"
        text = header.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"typedef\s+enum\s+(ft\w+Status)\s*\{", text)
        if not m:
            raise ValueError(f"{header}: no ft<Char>Status enum")
        enum_name = m.group(1)
        values = parse_enum(text, enum_name, known=common)
        own = {k: v for k, v in values.items() if v >= special_start}
        classes, names = _class_map(own, r"^nFT\w+?Status")
        characters[key] = {
            "header": header.relative_to(REPO_ROOT).as_posix(), "enum": enum_name, "validated": key in VALIDATED,
            "ids": {str(i): classes[i] for i in sorted(classes)}, "names": {str(i): names[i] for i in sorted(names)},
            "count": len(classes), "max_id": max(classes) if classes else special_start - 1,
        }
    table = {
        "table_id": TABLE_ID, "classes": list(CLASSES), "unmapped_class": UNMAPPED,
        "common_header": (DECOMP / "ftdef.h").relative_to(REPO_ROOT).as_posix(),
        "special_start": special_start,
        "common": {str(i): common_classes[i] for i in sorted(common_classes)},
        "common_names": {str(i): common_names[i] for i in sorted(common_names)},
        "characters": characters,
        "rule": "classify() of rl/m7n_status_table.py on the enumerator name; an id outside the table -> 'unmapped'",
    }
    table["sha256"] = table_digest(table)
    return table


def table_digest(table: Dict[str, Any]) -> str:
    body = {k: v for k, v in table.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_table(path: Path = TABLE_PATH) -> Dict[str, Any]:
    table = json.loads(path.read_text(encoding="utf-8"))
    if table.get("table_id") != TABLE_ID or table.get("sha256") != table_digest(table):
        raise ValueError(f"{path}: not a valid {TABLE_ID} (id or digest)")
    return table


class ActionClassifier:
    """id -> class index for one character (common range + that character's own range; else `unmapped`)."""

    def __init__(self, table: Dict[str, Any], character: str):
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("build", "check", "show"))
    ap.add_argument("character", nargs="?", default="mario")
    args = ap.parse_args(argv)
    table = derive()
    if args.command == "build":
        TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TABLE_PATH.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {TABLE_PATH.relative_to(REPO_ROOT).as_posix()} sha256 {table['sha256'][:16]} "
              f"special_start {table['special_start']} characters {len(table['characters'])}")
        return 0
    if args.command == "check":
        stored = load_table()
        same = stored == table
        print(f"{'IDENTICAL' if same else 'DIFFERENT'}: stored {stored['sha256'][:16]} derived {table['sha256'][:16]}")
        return 0 if same else 1
    ch = table["characters"][args.character]
    counts: Dict[str, int] = {}
    for c in list(table["common"].values()) + list(ch["ids"].values()):
        counts[c] = counts.get(c, 0) + 1
    print(json.dumps({"character": args.character, "validated": ch["validated"], "special_start": table["special_start"],
                      "own_ids": {k: f"{ch['names'][k]} -> {v}" for k, v in ch["ids"].items()},
                      "class_counts": counts}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
