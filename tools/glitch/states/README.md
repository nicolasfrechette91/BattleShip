# tools/glitch/states

Offline tools behind `STATE_MACHINE_CANDIDATES.md` (repository root). They read the decomp source and recorded traces.
They never start the game, write to the lab folders or touch `rl/`, `port/`, `decomp/` or `tools/frs/`. Outputs go to
the Git-ignored `logs/glitch/states/`. Standard-library Python 3.9+ only.

| file | what it does |
| --- | --- |
| `mario_states.py` | command line: `extract` (static table → JSON + Markdown), `detect` (state signals over traces → `btt_glitch_event_v1` JSONL) |
| `decomp_states.py` | reads the status descriptors, enums, Mario's motion table, motion scripts, animations, attributes and the C bodies of the procs; builds the transition graph, entry/exit facts, windows and BTT reachability |
| `state_detect.py` | the state-machine signals of section 5; plugs into `../detect.py` (`Params.state_table`) |
| `test_states.py` | 35 tests, no ROM (`python -I tools/glitch/states/test_states.py`); the real-decomp class is skipped without the submodule |

The table and the events are for explaining and detecting what an agent did. Do not turn them into rewards, goals,
curricula or input sequences.
