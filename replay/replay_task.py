#!/usr/bin/env python3
"""Which character and stage an episode artifact belongs to, read from what the run recorded (never assumed).

Sources, first match wins:

    labels.experiment.compatibility_view         {"task.character": "mario", "task.stage": "btt_mario"} M7d onward
    labels.experiment.task_id                    "ssb64_us_mario_btt_v1"                             M7b onward
        a registered task id (TASKS, mirroring rl/experiment_config.SUPPORTED_TASKS), else the documented pattern
        ssb64_<version>_<character>_<btt|btp>_v<n> with a known character (the pattern rl/m7n_obs.character_of
        reads; the stage is <btt|btp>_<character>, rl/experiment_config.KNOWN_STAGES)
    labels.contracts.action_class_character      "mario"                                             M7n onward
        the stage then follows from the artifact format battleship_btt_episode: in Break the Targets every
        character plays their own stage, btt_<character>

Anything else (M7a-era runs, most regression and test folders) is unknown: character and stage None, shown as
"?". rl/m7n_obs.character_of falls back to Mario; this module deliberately does not.

KNOWN_CHARACTERS and TASKS are copies of rl/experiment_config (importing it pulls in gymnasium and numpy);
replay_tests.py checks that the copies match.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, NamedTuple, Optional, Tuple

KNOWN_CHARACTERS: Tuple[str, ...] = ("mario", "fox", "donkey_kong", "samus", "luigi", "link", "yoshi",
                                     "captain_falcon", "kirby", "pikachu", "jigglypuff", "ness")
TASKS: Dict[str, Tuple[str, str]] = {"ssb64_us_mario_btt_v1": ("mario", "btt_mario")}
TASK_ID_RE = re.compile(r"ssb64_(?:us|jp)_(?P<character>[a-z_]+?)_(?P<mode>btt|btp)_v\d+$")
BTT_FORMAT = "battleship_btt_episode"

CHARACTER_NAMES: Dict[str, str] = {
    "mario": "Mario", "fox": "Fox", "donkey_kong": "Donkey Kong", "samus": "Samus", "luigi": "Luigi",
    "link": "Link", "yoshi": "Yoshi", "captain_falcon": "Captain Falcon", "kirby": "Kirby", "pikachu": "Pikachu",
    "jigglypuff": "Jigglypuff", "ness": "Ness",
}
UNKNOWN = "?"


class TaskIdentity(NamedTuple):
    character: Optional[str]  # KNOWN_CHARACTERS key, None when not recorded
    stage: Optional[str]  # e.g. btt_mario, None when not recorded
    source: str  # where the character came from, or "not recorded"


def _get(d: Any, *keys: str) -> Any:
    for k in keys:
        d = d.get(k) if isinstance(d, Mapping) else None
    return d


def task_identity(meta: Mapping[str, Any]) -> TaskIdentity:
    labels = meta.get("labels") if isinstance(meta.get("labels"), Mapping) else {}
    view = _get(labels, "experiment", "compatibility_view")
    if isinstance(view, Mapping):  # flat dotted keys ("task.character"), or a nested "task" block
        task = view.get("task") if isinstance(view.get("task"), Mapping) else {
            k[5:]: v for k, v in view.items() if isinstance(k, str) and k.startswith("task.")}
        if task.get("character") in KNOWN_CHARACTERS:
            stage = task.get("stage") if isinstance(task.get("stage"), str) and task.get("stage") else None
            return TaskIdentity(task["character"], stage, "labels.experiment.compatibility_view task.*")
    task_id = _get(labels, "experiment", "task_id")
    if isinstance(task_id, str):
        if task_id in TASKS:
            return TaskIdentity(*TASKS[task_id], "labels.experiment.task_id")
        m = TASK_ID_RE.match(task_id)
        if m and m.group("character") in KNOWN_CHARACTERS:
            c = m.group("character")
            return TaskIdentity(c, f"{m.group('mode')}_{c}", "labels.experiment.task_id (pattern)")
    c = _get(labels, "contracts", "action_class_character")
    if c in KNOWN_CHARACTERS:
        stage = f"btt_{c}" if meta.get("format") == BTT_FORMAT else None
        return TaskIdentity(c, stage, "labels.contracts.action_class_character")
    return TaskIdentity(None, None, "not recorded")


def character_name(character: Optional[str]) -> str:
    """Display name: 'Mario', 'Donkey Kong', or '?' when unknown."""
    if not character:
        return UNKNOWN
    return CHARACTER_NAMES.get(character, character.replace("_", " ").title())


def stage_name(stage: Optional[str]) -> str:
    return stage or UNKNOWN
