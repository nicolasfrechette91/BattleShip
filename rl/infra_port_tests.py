#!/usr/bin/env python3
"""INFRA_2026-11-04 fix 1: a launcher can only ever talk to its own game (port race, REVIEW_2026-11-03.md D3).

Zero native ticks: every process here is rl/m8_rd_fakegame.py behind the REAL launcher (rl/battleship_process.py).

    python -B rl/infra_port_tests.py                 all tests
    python -B rl/infra_port_tests.py race_legacy     one test

The race, reproduced deterministically: launcher A starts its child on port P; the child binds 1 s later. Launcher B,
asked for the same port before that bind, finds P free, starts its own child (which binds 2 s later and so fails) and
connects first: to A's child. `race_legacy` runs that with the pre-fix behaviour (no lease, a child that does not answer the
handshake, as today's executable) and asserts that B steps A's game: the bug. `race_fixed` runs the same race with the
handshake and asserts that B is refused before sending anything and that A then gets its own game. `lease_*` show that the
exclusive lease stops the second launcher even earlier, from another Python process too.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import port_lease  # noqa: E402
from battleship_process import (  # noqa: E402
    REQUIRE_IDENTITY_ENV,
    BattleShipEpisode,
    EpisodeFailure,
    EpisodeOutcome,
    LaunchConfig,
)
from infra_testlib import IS_WINDOWS, check, cleanup, env_patch, fake_exe, free_port, read_events, run_suite, tmpdir, wait_for  # noqa: E402


def config(root: Path, exe: Path, log: Path, port: Optional[int], *, legacy: bool, bind_delay: float = 0.0, lease: bool = True,
           require: Optional[bool] = None) -> LaunchConfig:
    env = {"FAKEGAME_LOG": str(log), "FAKEGAME_LOG_REQUESTS": "1", "FAKEGAME_REACCEPT": "1", "FAKEGAME_BOOT_S": "0.2",
           "FAKEGAME_BIND_DELAY_S": str(bind_delay), "FAKEGAME_IDLE_S": "30"}
    if legacy:
        env["FAKEGAME_LEGACY"] = "1"
    return LaunchConfig(executable=exe, run_root=root / "episodes", port=port, startup_timeout=20.0, ready_timeout=20.0, request_timeout=10.0,
                        exit_timeout=10.0, terminate_timeout=5.0, kill_timeout=5.0, extra_env=env, lease_ports=lease, require_identity=require)


def setup(name: str) -> Dict[str, Any]:
    root = tmpdir(f"infra_{name}_")
    return {"root": root, "exe": fake_exe(root), "log": root / "fake.log", "port": free_port()}


def steps_served(log: Path) -> list:
    return [e for e in read_events(log) if e.get("event") == "step_served"]


def race(t: Dict[str, Any], *, legacy: bool, lease: bool) -> Dict[str, Any]:
    """Start A (bind after 1 s) and B (same port, bind after 2 s) back to back; B then connects first."""
    a = BattleShipEpisode(config(t["root"], t["exe"], t["log"], t["port"], legacy=legacy, bind_delay=1.0, lease=lease), index=1)
    b = BattleShipEpisode(config(t["root"], t["exe"], t["log"], t["port"], legacy=legacy, bind_delay=2.0, lease=lease), index=2)
    out: Dict[str, Any] = {"a": a, "b": b}
    a.launch()
    try:
        b.launch()                                  # A's child has not bound yet, so the probe finds the port free
        out["b_launched"] = True
    except EpisodeFailure as exc:
        out["b_launched"] = False
        out["b_failure"] = exc
    return out


def race_legacy() -> Dict[str, Any]:
    """The bug as it is today: B steps A's game."""
    t = setup("race_legacy")
    r: Dict[str, Any] = {}
    try:
        with env_patch(**{REQUIRE_IDENTITY_ENV: None}):
            r = race(t, legacy=True, lease=False)
            a, b = r["a"], r["b"]
            check(r["b_launched"], "without a lease the second launcher is let through (the race window)")
            b.wait_for_transport()
            b.wait_for_fresh_episode()
            check(b.identity == "unverified", f"a legacy child cannot be verified: {b.identity}")
            b.client.step(0, 0, 0)
            served = steps_served(t["log"])
            check(len(served) == 1, f"one step served: {served}")
            check(served[0]["own_nonce"] == a.launch_nonce and served[0]["own_nonce"] != b.launch_nonce,
                  "BUG REPRODUCED: B's step was served by A's game (the process started with A's launch nonce)")
            check(wait_for(lambda: any(e.get("event") == "bind_failed" and e.get("own_nonce") == b.launch_nonce for e in read_events(t["log"])), 5.0),
                  "B's own child failed to bind and is running without a transport")
            return {"cross_talk": True, "served_by_a_pid": served[0]["pid"], "a_pid": a.pid, "b_pid": b.pid}
    finally:
        for k in ("b", "a"):
            if k in r:
                r[k].close()
        cleanup(t["root"])


def race_fixed() -> Dict[str, Any]:
    """The same race past the lease (lease off, as a foreign launcher would be): the handshake refuses B, A works."""
    t = setup("race_fixed")
    r: Dict[str, Any] = {}
    try:
        with env_patch(**{REQUIRE_IDENTITY_ENV: None}):
            r = race(t, legacy=False, lease=False)
            a, b = r["a"], r["b"]
            check(r["b_launched"], "the lease is off here, so B is let through to the handshake")
            try:
                b.wait_for_transport()
                raise AssertionError("B connected to A's game and was not refused")
            except EpisodeFailure as exc:
                check(exc.outcome == EpisodeOutcome.IDENTITY_MISMATCH, f"B refused as identity_mismatch: {exc.outcome}")
                check(exc.diagnostics.get("launch_nonce") == b.launch_nonce, "the failure names B's own nonce")
            check(steps_served(t["log"]) == [], "nothing was sent to A's game by B")
            a.wait_for_transport()
            fresh = a.wait_for_fresh_episode()
            check(a.identity == "verified" and fresh.step_count == 0, f"A reached its own fresh game: {a.identity}")
            if not IS_WINDOWS:
                check(a.peer_pid == a.pid, f"the handshake names A's child: {a.peer_pid} vs {a.pid}")
            a.client.step(0, 0, 0)
            served = steps_served(t["log"])
            check(len(served) == 1 and served[0]["own_nonce"] == a.launch_nonce, f"A's step was served by A's game: {served}")
            return {"b_refused": True, "a_identity": a.identity, "a_pid": a.pid, "peer_pid": a.peer_pid}
    finally:
        for k in ("b", "a"):
            if k in r:
                r[k].close()
        cleanup(t["root"])


def lease_blocks_second_launcher() -> Dict[str, Any]:
    """With the lease (the default), the second launcher is refused before it starts anything, in this process or another."""
    t = setup("lease_block")
    r: Dict[str, Any] = {}
    try:
        r = race(t, legacy=False, lease=True)
        a = r["a"]
        check(not r["b_launched"] and r["b_failure"].outcome == EpisodeOutcome.STARTUP_FAILURE and "leased by another launcher" in str(r["b_failure"]),
              f"B refused by the lease: {r.get('b_failure')}")
        check(r["b"].process is None, "B started no process")
        check(a.lease is not None and a.lease.path.is_file(), "A holds the lease file while its child runs")
        code = ("import sys; sys.path.insert(0, %r); import port_lease; l = port_lease.try_acquire(%d, owner='other');"
                " print('free' if l else 'held'); l and l.release()") % (str(Path(__file__).resolve().parent), t["port"])
        other = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=30)
        check(other.stdout.strip() == "held", f"another Python process cannot take the lease: {other.stdout!r} {other.stderr[-300:]!r}")
        a.wait_for_transport()
        a.wait_for_fresh_episode()
        a.close()
        check(not a.lease.path.exists(), "the lease is released once A's child is gone")
        again = port_lease.try_acquire(t["port"], owner="after")
        check(again is not None, "the port can be leased again after A")
        again.release()
        return {"refused": True, "cross_process": "held"}
    finally:
        for k in ("b", "a"):
            if k in r:
                r[k].close()
        cleanup(t["root"])


def lease_stale_reclaimed() -> Dict[str, Any]:
    """A lease left by a launcher that died is reclaimed; a live one is not."""
    root = tmpdir("infra_stale_")
    try:
        with env_patch(**{port_lease.LEASE_DIR_ENV: str(root / "leases")}):
            port = free_port()
            dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True).stdout.strip()
            d = port_lease.lease_dir()
            d.mkdir(parents=True)
            port_lease.lease_path(port).write_text(json.dumps({"port": port, "pid": int(dead), "token": "x", "created": time.time()}), encoding="utf-8")
            lease = port_lease.try_acquire(port, owner="reclaim")
            check(lease is not None, "a dead launcher's lease is reclaimed")
            check(port_lease.try_acquire(port, owner="second") is None, "a live lease is not")
            lease.release()
            check(not port_lease.lease_path(port).exists(), "release removes the file")
            return {"dead_pid": int(dead)}
    finally:
        cleanup(root)


def require_identity_refuses_legacy() -> Dict[str, Any]:
    """BATTLESHIP_REQUIRE_IDENTITY=1 (or LaunchConfig.require_identity=True) refuses an executable without the handshake."""
    t = setup("require")
    out: Dict[str, Any] = {}
    try:
        for how in ("config", "env"):
            with env_patch(**{REQUIRE_IDENTITY_ENV: "1" if how == "env" else None}):
                ep = BattleShipEpisode(config(t["root"], t["exe"], t["log"], None, legacy=True, require=True if how == "config" else None), index=3)
                try:
                    ep.start()
                    raise AssertionError("a legacy child was accepted although identity is required")
                except EpisodeFailure as exc:
                    check(exc.outcome == EpisodeOutcome.IDENTITY_MISMATCH and "does not answer" in str(exc), f"{how}: {exc}")
                finally:
                    ep.close()
                out[how] = "refused"
        with env_patch(**{REQUIRE_IDENTITY_ENV: None}):
            ep = BattleShipEpisode(config(t["root"], t["exe"], t["log"], None, legacy=True), index=4)
            try:
                ep.start()
                check(ep.identity == "unverified", "without the requirement a legacy child is accepted as unverified")
            finally:
                ep.close()
        out["default"] = "unverified"
        return out
    finally:
        cleanup(t["root"])


def normal_launch_verified() -> Dict[str, Any]:
    """The everyday path: an OS-chosen leased port, the handshake verified, the lease released at close."""
    t = setup("normal")
    try:
        ep = BattleShipEpisode(config(t["root"], t["exe"], t["log"], None, legacy=False), index=5)
        with ep:
            ep.start()
            check(ep.identity == "verified", f"verified: {ep.identity}")
            check(ep.lease is not None and ep.lease.port == ep.port and ep.lease.path.is_file(), "the OS-chosen port is leased")
            rec = port_lease.read_lease(ep.lease.path) or {}
            check(rec.get("pid") == os.getpid() and rec.get("child_pid") == ep.pid, f"the lease names launcher and child: {rec}")
            d = ep.diagnostics()
            check(d["identity"] == "verified" and d["launch_nonce"] == ep.launch_nonce and d["port_lease"], f"diagnostics: {d}")
        check(not ep.lease.path.exists(), "released at close")
        return {"port": ep.port, "identity": ep.identity}
    finally:
        cleanup(t["root"])


GUARD_CHILD = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, %(rl)r)
import frs_guard as g
lab = Path(%(lab)r)
g.LabGuard.install(lab)
import port_lease
from battleship_process import BattleShipEpisode, LaunchConfig
from infra_testlib import fake_exe
exe = fake_exe(lab / "fake")
cfg = LaunchConfig(executable=exe, run_root=lab / "episodes", startup_timeout=20.0, ready_timeout=20.0, request_timeout=10.0,
                   extra_env={"FAKEGAME_BOOT_S": "0.1", "FAKEGAME_IDLE_S": "30"})
ep = BattleShipEpisode(cfg, index=1)
with ep:
    ep.start()
    lease = str(ep.lease.path)
    identity = ep.identity
print(json.dumps({"violations": g.LabGuard.violations[:3], "lease": lease, "lease_dir": str(port_lease.lease_dir()), "identity": identity}))
"""


def lease_inside_lab_guard() -> Dict[str, Any]:
    """Under the lab guard (which refuses and records any write outside the lab root), the lease lives in <lab>/port_leases
    and a launch records no violation. Without this, every lab launch would fail and invalidate the run."""
    lab = tmpdir("infra_guard_lab_")
    try:
        code = GUARD_CHILD % {"rl": str(Path(__file__).resolve().parent), "lab": str(lab)}
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise AssertionError(f"child failed: {(r.stderr or r.stdout)[-1500:]}")
        check(out["violations"] == [], f"no guard violation: {out['violations']}")
        check(Path(out["lease_dir"]).name == "port_leases" and str(lab.resolve()).lower() in out["lease_dir"].lower(),
              f"the lease directory is inside the lab root: {out['lease_dir']}")
        check(out["identity"] == "verified", f"the launch worked: {out}")
        return {"lease_dir": out["lease_dir"], "identity": out["identity"]}
    finally:
        cleanup(lab)


TESTS = {
    "race_legacy": race_legacy,
    "race_fixed": race_fixed,
    "lease_blocks_second_launcher": lease_blocks_second_launcher,
    "lease_stale_reclaimed": lease_stale_reclaimed,
    "require_identity_refuses_legacy": require_identity_refuses_legacy,
    "normal_launch_verified": normal_launch_verified,
    "lease_inside_lab_guard": lease_inside_lab_guard,
}

if __name__ == "__main__":
    sys.exit(run_suite("infra port tests", TESTS, sys.argv[1:]))
