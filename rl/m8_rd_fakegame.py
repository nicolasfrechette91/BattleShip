"""M8-rd test helper: a fake BattleShip process that speaks the M1d loopback protocol (NDJSON, protocol 1) over the synthetic
world of rl/m8_rd_stub.py. It lets the REAL lifecycle code (rl/battleship_process.py, rl/m7_standby.py, the real backend in
rl/m8_rd_worker.py, rl/m7f_trace.py) run end to end without a game. It is launched through a one-line .cmd wrapper named like
the executable; tests only. THE WORLD IS SYNTHETIC.

Environment (all optional): FAKEGAME_WORLD (stub world, default easy), FAKEGAME_BOOT_S (seconds spent Inactive), FAKEGAME_LOG
(a file to which one line per start is appended: cwd, port, the sha256 of the BattleShip.cfg.json found in the working
directory, the SSB64_* flags), FAKEGAME_DIE_AT_STEP (exit with code 3 on that step request), FAKEGAME_IDLE_S (give up after
that many idle seconds, default 120). The usual SSB64_RL_* variables are honoured: SSB64_RL_PORT, SSB64_RL_RESULT_PATH.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m8_rd_stub as stub  # noqa: E402

_WORD = {t: i for i, t in enumerate(mcell.TRIPLES)}


def main() -> int:
    port = int(os.environ["SSB64_RL_PORT"])
    result_path = os.environ.get("SSB64_RL_RESULT_PATH")
    world = stub.World(stub.WORLDS[os.environ.get("FAKEGAME_WORLD", "easy")])
    boot = float(os.environ.get("FAKEGAME_BOOT_S", "0.3"))
    die_at = int(os.environ.get("FAKEGAME_DIE_AT_STEP", "0"))
    idle_s = float(os.environ.get("FAKEGAME_IDLE_S", "120"))
    log = os.environ.get("FAKEGAME_LOG")
    cfg = os.path.join(os.getcwd(), "BattleShip.cfg.json")
    cfg_hash = hashlib.sha256(open(cfg, "rb").read()).hexdigest() if os.path.isfile(cfg) else None
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"cwd": os.getcwd(), "port": port, "cfg_sha256": cfg_hash, "pid": os.getpid(),
                                "flags": {k: v for k, v in os.environ.items() if k.startswith("SSB64_")}}) + "\n")
    host_off = 30 + (os.getpid() % 50)
    state = world.initial()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    srv.settimeout(idle_s)
    t_boot = time.monotonic()
    try:
        conn, _addr = srv.accept()
    except OSError:
        return 4
    conn.settimeout(idle_s)
    buf = b""
    steps = 0
    flags = {"no_render": os.environ.get("SSB64_RL_NO_RENDER") == "1", "raphnet_disabled": os.environ.get("SSB64_RAPHNET_DISABLE") == "1",
             "spatial_diag": os.environ.get("SSB64_RL_SPATIAL") == "1", "entity_diag": os.environ.get("SSB64_RL_ENTITY") == "1",
             "target_diag": os.environ.get("SSB64_RL_TARGET_DIAG") == "1", "input_diag": os.environ.get("SSB64_RL_INPUT") == "1"}
    if os.environ.get("FAKEGAME_LIE_SPATIAL") == "1":
        flags["spatial_diag"] = False
    while True:
        while b"\n" not in buf:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return 5
            if not chunk:
                return 0
            buf += chunk
        line, _, buf = buf.partition(b"\n")
        req = json.loads(line.decode("utf-8"))
        op = req.get("op")
        ready = time.monotonic() - t_boot >= boot
        ended = bool(state[14])
        resp = {"protocol": 1, "ok": True, "op": op}
        if op == "ping":
            pass
        elif op == "status":
            st = 6 if ended else (2 if ready else 1)
            resp.update({"state": st, "state_name": {1: "Inactive", 2: "WaitingForAction", 6: "EpisodeEnded"}[st],
                         "can_step": bool(ready and not ended), "step_count": steps, **flags})
        elif op == "observe":
            if not ready:
                resp = {"protocol": 1, "ok": False, "op": op, "error": "no_observation", "message": "not booted"}
            else:
                r = world.reply(state, host_off, observe=True)
                resp.update({k: v for k, v in r.items() if k not in ("ok", "op", "protocol")})
        elif op == "step":
            steps += 1
            if die_at and steps == die_at:
                return 3
            if not ready or ended:
                resp = {"protocol": 1, "ok": False, "op": op, "error": "not_ready", "native_code": -4, "message": "not ready"}
            else:
                word = _WORD[(int(req["buttons"]), int(req["stick_x"]), int(req["stick_y"]))]
                world.advance(state, word)
                r = world.reply(state, host_off)
                resp.update({k: v for k, v in r.items() if k not in ("ok", "op", "protocol")})
        else:
            resp = {"protocol": 1, "ok": False, "op": op, "error": "unknown_op", "message": op}
        conn.sendall((json.dumps(resp, separators=(",", ":")) + "\n").encode("utf-8"))
        if op == "step" and resp.get("ok") and state[14]:
            t = resp["observation"]["input_tick"]
            if result_path:
                with open(result_path, "w", encoding="utf-8") as f:
                    json.dump({"result_schema": 1, "outcome": "clear", "targets_broken": 10, "completion_time_passed": t - 1,
                               "completion_input_tick": t, "time_passed_final": t - 1, "input_cursor_final": t,
                               "host_frames": t + 60}, f)
            time.sleep(0.05)
            return 0


if __name__ == "__main__":
    sys.exit(main())
