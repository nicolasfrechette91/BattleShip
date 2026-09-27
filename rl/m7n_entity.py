"""M7n: reader of the native `btt_entity_v1` diagnostic (SSB64_RL_ENTITY=1): the agent's action-state progress and
flags that the frozen RLObservation does not carry, plus every live weapon (projectile) under a per-process spawn
serial. Strict parse (every key checked), typed snapshot, and the numerical invariants a valid stream must satisfy.

The `entity` object is additive: with the flag unset a reply is byte-identical to the M7g executable's.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ENTITY_ENV = "SSB64_RL_ENTITY"
CONTRACT = "btt_entity_v1"
SCHEMA = 1
REPLY_KEY = "entity"
STATUS_KEY = "entity_diag"
MAX_WEAPONS = 8

ANOMALY_BITS = {0: "weapon_overflow", 1: "bad_weapon", 2: "track_overflow"}

# nWPKind* of decomp/src/wp/wpdef.h (names for reports only; the observation never uses the kind)
WEAPON_KIND_NAMES = {0: "fireball", 1: "blaster", 2: "charge_shot", 3: "samus_bomb", 4: "cutter", 5: "egg_throw",
                     6: "yoshi_star", 7: "boomerang", 8: "spin_attack", 9: "thunder_jolt_air", 10: "thunder_jolt_ground",
                     11: "thunder_head", 12: "thunder_trail", 13: "pk_fire", 14: "pk_thunder_head", 15: "pk_thunder_trail"}


class EntityError(ValueError):
    pass


@dataclass(frozen=True)
class EntityFighter:
    valid: int
    status_total_tics: int
    hitlag_tics: int
    jumps_max: int
    attack_active: int
    cliff_hold: int
    shield_active: int
    fastfall: int
    hitstun: int


@dataclass(frozen=True)
class EntityWeapon:
    serial: int
    kind: int
    owned: int
    lr: int
    ga: int
    lifetime: int
    attack_state: int
    translate: Tuple[float, float]
    velocity: Tuple[float, float]


@dataclass(frozen=True)
class EntitySnapshot:
    input_tick: int
    scene_active: int
    live: int
    anomaly_flags: int
    fighter: EntityFighter
    weapon_total: int
    weapons: Tuple[EntityWeapon, ...]


_TOP_KEYS = {"contract", "entity_schema", "input_tick", "scene_active", "live", "anomaly_flags", "fighter",
             "weapon_total", "weapons"}
_FIGHTER_KEYS = {"valid", "status_total_tics", "hitlag_tics", "jumps_max", "attack_active", "cliff_hold",
                 "shield_active", "fastfall", "hitstun"}
_WEAPON_KEYS = {"serial", "kind", "owned", "lr", "ga", "lifetime", "attack_state", "translate", "velocity"}

_U32 = (0, 2 ** 32 - 1)
_S32 = (-2 ** 31, 2 ** 31 - 1)


def _int(v: Any, what: str, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise EntityError(f"{what}: expected an integer, got {v!r}")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise EntityError(f"{what}: {v} outside [{lo}, {hi}]")
    return v


def _num(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EntityError(f"{what}: expected a number, got {v!r}")
    return float(v)


def _pair(v: Any, what: str) -> Tuple[float, float]:
    if not isinstance(v, list) or len(v) != 2:
        raise EntityError(f"{what}: expected [x, y]")
    return (_num(v[0], what), _num(v[1], what))


def _keys(obj: Any, expected: set, what: str) -> None:
    if not isinstance(obj, dict):
        raise EntityError(f"{what}: expected an object")
    if set(obj) != expected:
        raise EntityError(f"{what}: keys {sorted(set(obj) ^ expected)} unexpected or missing")


def parse_entity(obj: Any) -> EntitySnapshot:
    _keys(obj, _TOP_KEYS, "entity")
    if obj["contract"] != CONTRACT or _int(obj["entity_schema"], "entity_schema") != SCHEMA:
        raise EntityError(f"entity: contract {obj['contract']!r} schema {obj['entity_schema']!r}")
    f = obj["fighter"]
    _keys(f, _FIGHTER_KEYS, "entity.fighter")
    fighter = EntityFighter(valid=_int(f["valid"], "fighter.valid", 0, 1),
                            status_total_tics=_int(f["status_total_tics"], "status_total_tics", *_U32),
                            hitlag_tics=_int(f["hitlag_tics"], "hitlag_tics", *_U32),
                            jumps_max=_int(f["jumps_max"], "jumps_max", *_S32),
                            attack_active=_int(f["attack_active"], "attack_active", 0, 1),
                            cliff_hold=_int(f["cliff_hold"], "cliff_hold", 0, 1),
                            shield_active=_int(f["shield_active"], "shield_active", 0, 1),
                            fastfall=_int(f["fastfall"], "fastfall", 0, 1),
                            hitstun=_int(f["hitstun"], "hitstun", 0, 1))
    raw = obj["weapons"]
    if not isinstance(raw, list) or len(raw) > MAX_WEAPONS:
        raise EntityError(f"entity.weapons: expected a list of at most {MAX_WEAPONS} weapons")
    weapons: List[EntityWeapon] = []
    for i, w in enumerate(raw):
        _keys(w, _WEAPON_KEYS, f"entity.weapons[{i}]")
        weapons.append(EntityWeapon(serial=_int(w["serial"], "weapon.serial", *_U32),
                                    kind=_int(w["kind"], "weapon.kind", *_S32), owned=_int(w["owned"], "weapon.owned", 0, 1),
                                    lr=_int(w["lr"], "weapon.lr", *_S32), ga=_int(w["ga"], "weapon.ga", 0, 1),
                                    lifetime=_int(w["lifetime"], "weapon.lifetime", *_S32),
                                    attack_state=_int(w["attack_state"], "weapon.attack_state", *_S32),
                                    translate=_pair(w["translate"], "weapon.translate"),
                                    velocity=_pair(w["velocity"], "weapon.velocity")))
    return EntitySnapshot(input_tick=_int(obj["input_tick"], "input_tick", *_U32),
                          scene_active=_int(obj["scene_active"], "scene_active", 0, 1),
                          live=_int(obj["live"], "live", 0, 1),
                          anomaly_flags=_int(obj["anomaly_flags"], "anomaly_flags", *_U32), fighter=fighter,
                          weapon_total=_int(obj["weapon_total"], "weapon_total", *_U32), weapons=tuple(weapons))


def entity_of(reply: Mapping[str, Any]) -> EntitySnapshot:
    """The parsed entity object of an observe or step reply; EntityError when absent."""
    if REPLY_KEY not in reply:
        raise EntityError(f"reply {reply.get('op')!r} has no {REPLY_KEY!r} object (is {ENTITY_ENV}=1 effective?)")
    return parse_entity(reply[REPLY_KEY])


def require_entity_status(status: Mapping[str, Any]) -> None:
    if status.get(STATUS_KEY) is not True:
        raise EntityError(f"status reply lacks {STATUS_KEY}: true (the process was not booted with {ENTITY_ENV}=1)")


def anomaly_names(flags: int) -> List[str]:
    return [ANOMALY_BITS.get(b, f"bit{b}") for b in range(32) if flags >> b & 1]


def owned_weapons(snap: EntitySnapshot) -> List[EntityWeapon]:
    """The agent's own live weapons, in ascending spawn serial (the deterministic order the observation uses)."""
    return sorted((w for w in snap.weapons if w.owned), key=lambda w: w.serial)


def check_snapshot(snap: EntitySnapshot, observation: Mapping[str, Any], *, prev: Optional[EntitySnapshot] = None,
                   prev_observation: Optional[Mapping[str, Any]] = None, jumps_max: Optional[int] = None) -> List[str]:
    """Numerical invariants of one entity snapshot against the observation it is paired with (and the previous
    snapshot of the same episode, when given). Returns problem strings (empty = all hold).

    * pairing: input_tick equals the observation's; live implies scene_active; no anomaly bit;
    * fighter: valid iff the observation's fighter is valid (while live); jumps_max equals the character constant
      (when given) and is >= jumps_used; hitlag / progress finite integers;
    * action progress: with the status id unchanged, status_total_tics advances by exactly 1 per update, or restarts
      at 0 when the same status is re-entered; a status change always reads 0 on its first update (measured on the
      TAS: every one of its status changes; ftmain.c zeroes the counter in the change and increments afterwards);
    * weapons: serials unique; a serial present in both snapshots keeps its kind and its lifetime never increases;
      weapon_total >= len(weapons); at most one row per serial."""
    p: List[str] = []
    if snap.input_tick != int(observation["input_tick"]):
        p.append(f"input_tick {snap.input_tick} != observation {observation['input_tick']}")
    if snap.live and not snap.scene_active:
        p.append("live without scene_active")
    if snap.anomaly_flags:
        p.append(f"anomaly flags {anomaly_names(snap.anomaly_flags)}")
    if not snap.live:
        return p
    f = snap.fighter
    if int(observation.get("fighter_valid", 0)) != f.valid:
        p.append(f"fighter valid {f.valid} vs observation {observation.get('fighter_valid')}")
    if f.valid:
        if jumps_max is not None and f.jumps_max != jumps_max:
            p.append(f"jumps_max {f.jumps_max} != {jumps_max}")
        if f.jumps_max < int(observation.get("jumps_used", 0)):
            p.append(f"jumps_max {f.jumps_max} < jumps_used {observation.get('jumps_used')}")
        if prev is not None and prev.live and prev.fighter.valid and prev_observation is not None:
            same = int(prev_observation["fighter_status_id"]) == int(observation["fighter_status_id"])
            d = f.status_total_tics - prev.fighter.status_total_tics
            if same and d != 1 and f.status_total_tics != 0:
                # the same id may be re-entered (a second aerial fireball): a fresh count from 0, like any change
                p.append(f"status_total_tics {prev.fighter.status_total_tics} -> {f.status_total_tics} with the same status")
            if not same and f.status_total_tics != 0:
                p.append(f"status change but status_total_tics {f.status_total_tics}")
    serials = [w.serial for w in snap.weapons]
    if len(set(serials)) != len(serials):
        p.append(f"duplicate weapon serials {serials}")
    if snap.weapon_total < len(snap.weapons):
        p.append(f"weapon_total {snap.weapon_total} < rows {len(snap.weapons)}")
    if prev is not None and prev.live:
        before = {w.serial: w for w in prev.weapons}
        for w in snap.weapons:
            b = before.get(w.serial)
            if b is None:
                continue
            if b.kind != w.kind:
                p.append(f"serial {w.serial} changed kind {b.kind} -> {w.kind}")
            if w.lifetime > b.lifetime:
                p.append(f"serial {w.serial} lifetime rose {b.lifetime} -> {w.lifetime}")
        if snap.weapons and max(serials) < max((w.serial for w in prev.weapons), default=0) and \
                any(s not in before for s in serials):
            p.append("a new weapon received a serial below an earlier one")
    return p
