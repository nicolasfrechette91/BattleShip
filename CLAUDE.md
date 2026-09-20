# BattleShip Reinforcement-Learning Fork

BattleShip is a native PC port of Super Smash Bros. 64 built from the completed
decompilation. This fork is a stable desktop-only sandbox for reinforcement-
learning research.

Mario's Break the Targets is the initial environment and benchmark.

## Supported scope

Supported:

- Windows x64 desktop
- Linux desktop and future headless training
- US game version as the initial RL target
- JP builds where existing support remains functional

Unsupported and intentionally removed:

- Android
- UWP and Xbox packaging

Do not restore removed platforms unless explicitly requested.

## Current objective

Phase 1 is an automated episode environment that can:

1. Launch Mario's Break the Targets.
2. Accept frame-level controller actions.
3. Expose structured, machine-readable observations.
4. Detect completion, failure, and timeout.
5. Produce machine-readable episode results.
6. Reset and start another episode without manual interaction.
7. Eventually run faster than real time without rendering.

The existing scripted baseline contains 468 gameplay input rows and completes
with an internal time of 7.43 seconds. Preserve this as a regression baseline.

Do not implement, validate, or compare RNG seeds. RNG seed checking is not
required for this project.

## Repository ownership

The parent repository belongs to the current user, not JRickey.

- Do not assume access to JRickey repositories, branches, issues, credentials,
  connectors, or GitHub identity.
- Do not push to JRickey repositories.
- Do not open issues or pull requests against upstream unless explicitly asked.
- Treat upstream repositories as reference sources only.
- Do not merge upstream automatically.
- External updates are selected deliberately for this stable sandbox.

## Repository structure

- `decomp/`: completed SSB64 decompilation and minimal PC-port hooks.
- `port/`: native C++ integration, runtime hooks, input, and diagnostics.
- `libultraship/`: pinned native runtime dependency.
- `torch/`: pinned ROM asset-extraction dependency.
- `tools/`: build and asset-generation utilities.
- `yamls/`: region-specific asset definitions.
- `docs/`: architecture and debugging documentation.
- `rl/`: Python environment, protocol clients, training, evaluation, and tests.
- `port/rl/`: native game-to-RL bridge, when introduced.

Prefer new RL code under `rl/` and `port/rl/`. Minimize changes to inherited
files.

## Documentation

Read the document relevant to the task before editing code.

| Topic | File |
| --- | --- |
| Architecture, dependencies, and source layout | `docs/architecture.md` |
| C types, naming, macros, and conventions | `docs/c_conventions.md` |
| N64 memory, graphics, audio, threading, input, and endianness | `docs/n64_reference.md` |
| CMake, generated files, logs, and LP64 compatibility | `docs/build_and_tooling.md` |
| GBI tracing | `docs/debug_gbi_trace.md` |
| IDO bitfield-layout verification | `docs/debug_ido_bitfield_layout.md` |
| Resolved bugs | `docs/bugs/README.md` |

Check `docs/` before starting an investigation so existing findings are not
duplicated.

Document significant port bugs under `docs/bugs/` and link them from
`docs/bugs/README.md`.

## Decomp preservation

Treat `decomp/` as byte-accurate source.

- Do not modernize matching code for style.
- Do not remove fake variables, unusual casts, gotos, or compiler-matching
  constructs from the non-PORT implementation.
- Never make an unconditional semantic correction to matching code merely to
  satisfy a modern compiler.
- Put PC-only behavior behind `#ifdef PORT`.
- Preserve the original non-PORT code path unchanged.
- Before excluding an unreferenced function from PORT builds, search the entire
  decomp repository for direct and indirect symbolic references.
- Prefer a port-side adapter over changing decomp code.
- If a decomp edit is unavoidable, verify both the PC build and the applicable
  decomp validation process.

The recent `unref_800036B4` handling is the preferred pattern: retain the
byte-accurate function for non-PORT builds and exclude it only from PORT builds.

## Submodules

`decomp`, `libultraship`, and `torch` are pinned submodules.

- Do not update a submodule merely because a newer commit exists.
- Do not modify `libultraship` or `torch` unless the requested feature requires
  it.
- Never assume a detached submodule HEAD can be pushed directly.
- Inspect its branch and remotes before making changes.
- Do not change submodule remote URLs without explicit approval.

When a submodule change is required:

1. Create or switch to a branch inside the submodule.
2. Make and verify the change.
3. Commit and push to the user's appropriate fork.
4. Return to the parent repository.
5. Stage and commit the updated submodule pointer separately.

Never push submodule changes to JRickey-owned repositories.

## RL architecture rules

Define and document the environment contract before implementing a learning
algorithm.

The contract must explicitly define:

- Action representation and valid ranges.
- Observation fields, types, shapes, and units.
- Reward components.
- Success and failure conditions.
- Episode termination and truncation.
- Reset behavior.
- Frame-advance behavior.
- Protocol version.

Additional requirements:

- Use game frames or internal game time, not wall-clock time.
- Keep rewards and training-framework dependencies outside byte-accurate game
  logic.
- Do not link PyTorch, Gymnasium, Stable-Baselines3, or another ML framework
  directly into the game executable.
- Keep the native game bridge independent of the selected ML framework.
- Do not require rendering for environment operation.
- First validate the environment with the known scripted replay.
- Then add a random-agent smoke test.
- Add an ML algorithm only after reset, stepping, observations, actions, and
  termination have automated tests.
- Do not add RNG seed checking.

Do not choose the final IPC transport or ML library without first comparing the
requirements and documenting the decision.

## Windows build

Configure the US build:

    cmake -S . -B build-us -G "Visual Studio 18 2026" -A x64 -DSSB64_VERSION=us

Build:

    cmake --build build-us --config Release

Expected executable:

    build-us/Release/BattleShip.exe

JP uses a separate `build-jp` directory with `-DSSB64_VERSION=jp`.

Do not reuse a CMake build directory created from another checkout or source
path.

## Verification

Before reporting a C or C++ change complete:

1. Run `git diff --check`.
2. Inspect the complete relevant diff.
3. Build the US Release configuration.
4. Run relevant automated tests or replay validation.
5. Report the exact commands and outcomes.

For RL environment changes, verify:

- Observation schema and types.
- Action ranges and controller mapping.
- Frame-step behavior.
- Success detection.
- Failure detection.
- Timeout handling.
- Reset behavior.
- Scripted baseline regression.
- Protocol compatibility.
- Repeated episode execution.

Do not claim verification that was not actually performed.

## Working rules

- Inspect `git status` before editing.
- Preserve all pre-existing user changes.
- Re-read a file immediately before editing it.
- Keep changes focused on the requested milestone.
- Prefer new files over broad inherited-code refactors.
- Do not perform unrelated cleanup.
- Do not commit, push, merge, rebase, or create a pull request unless explicitly
  requested.
- Never use destructive Git commands.
- Never commit ROMs, `.o2r` files, generated game assets, build directories,
  training runs, datasets, logs, or model checkpoints.
- Do not expose or inspect ROM contents unless explicitly required.
- Do not suppress compiler errors when a safe PORT-specific correction exists.

For multi-file architectural work:

1. Explore the relevant code.
2. Present a phased implementation plan.
3. Implement one independently verifiable milestone at a time.
4. Build and test after each milestone.
5. Continue automatically within the approved scope unless a decision would
   materially change the architecture.

Use parallel agents only for read-only investigations or isolated worktrees.
Never allow multiple agents to edit the same checkout concurrently.

## Context management

- Use focused investigations instead of reading entire large directories.
- Read large files in relevant sections.
- Search for callers, declarations, macros, string references, generated
  references, and tests before changing an interface.
- Use a fresh Claude session for a new implementation milestone.
- Preserve modified-file lists, decisions, failures, and verification commands
  when compacting context.