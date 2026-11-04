# tools/glitch

Offline tools behind `GLITCH_CANDIDATES.md` (repository root). They read the ROM, the decomp source and recorded traces.
They never start the game, write to the lab folders or touch `rl/`, `port/`, `decomp/` or `tools/frs/`. Outputs go to the
Git-ignored `logs/glitch/`. Standard-library Python 3.9+ only.

| file | what it does |
| --- | --- |
| `glitch.py` | command line: `extract`, `decomp`, `analyze`, `compare`, `detect` (see `python -I tools/glitch/glitch.py -h`) |
| `geometry.py` | ROM reloc table, VPK0, relocation chains, `MPGeometryData` parsing, decomp-source decode, the game's derived tables |
| `vpk0.py` | VPK0 decoder (port of `torch/lib/libvpk0/vpk0.c`) and a test-only encoder |
| `analysis.py` | geometry checks that map the M1-M14 mechanisms onto a line table |
| `detect.py` | per-tick anomaly detector over lab traces; writes `btt_glitch_event_v1` JSONL |
| `test_glitch.py` | 36 tests, no ROM needed (`python -I tools/glitch/test_glitch.py`) |
| `transn_cos_check.c` | D1 on Mario's Super Jump Punch: libultra `__cosf` against the host `cosf` on the exact stick-derived inputs |

The `analyze` output names places on the stage. It is for explaining and detecting what an agent did. Do not turn it
into rewards, goals, curricula or input sequences.
