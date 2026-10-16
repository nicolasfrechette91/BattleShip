# Native savestates for search only: feasibility study (2026-10-16)

## 0. Status, scope, sources and method

**Status: offline design study; zero native ticks.** No BattleShip.exe, lab command, suite, launcher or build was started and nothing was
compiled. Checkout `C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip`, branch `main`, HEAD = `origin/main` = `be1dc29` ("Record the
segment optimiser decisions and the November agenda"), clean before the study. No `C:/BattleShip_lab/lab.lock` existed and no BattleShip or
Python process was running at the start. New files: this record and the Git-ignored working files under `logs/frs_savestate/` (appendix).
Nothing under `rl/`, `tools/`, `port/`, `decomp/`, `runs/`, `C:/BattleShip_lab/` or D: was created, modified or deleted.

**The question** (`docs/rl_decisions_2026-10-16_addendum.md`, part 3): whether to allow native savestates for search only. Unchanged in any
case: every claimed clear is verified by exact replay from tick 0, twice, in fresh processes with the verify flags. This record proposes and
measures nothing; it decides nothing and launches nothing.

**Sources read.** `docs/project_handoff.md`; the addendum, parts 2 and 3; `docs/frs_segment_optimiser_proposal_2026-10-16.md` section 3;
`docs/frs_prefix_cost_2026-10-14.md` sections 0, 2, 4.3, 4.4 and 6; `docs/rl_throughput_m6.md` (the startup split only); the port layer
(`port/port.cpp`, `port/gameloop.cpp`, `port/stubs/n64_stubs.c`, `port/coroutine_win32.cpp`, `port/port_watchdog.cpp`, `port/port_save.cpp`,
`port/bridge/lbreloc_bridge.cpp`, `port/resource/RelocPointerTable.*`, `port/bridge/lbreloc_byteswap.cpp`, `port/port_aobj_fixup.*`,
`port/rl/*`); the decomp's PORT hooks on the boot, tick and scene paths (`decomp/src/sys/main.c`, `taskman.c`, `malloc.c`, `audio.c`,
`netinput.c`, `objman.c`, `decomp/src/sc/scmanager.c`, `sc1pmode/sc1pmanager.c`, `sc1pbonusstage.c`, `sc1pbonusstagefiles.c`); the
worker's flag map and mismatch classes (`rl/m8_rd_worker.py`, grep only); the PE section table of `build-us/Release/BattleShip.exe`
(SHA-256 prefix `30a3913b32c44353`, the registered executable) read with a standard-library script; and the port log of the last run
(`%APPDATA%/BattleShip/ssb64.log`, read-only, for the boot timeline). No ROM content was read.

**Rules applied.** Memory is treated as opaque regions throughout: nothing here locates, names, reads or reasons about any random-number state,
and the only comparison a snapshot is ever subjected to in this design is whole-region byte equality inside the fidelity test. No validation
material or external time is read, mentioned or used; the fidelity material is the agent's own verified clears and archive cells.

## 1. Where the running game's state lives (by region)

**The port does not reproduce the console's fixed memory layout.** The original game's statics, overlays and heaps lived at fixed console
addresses. In the port the decomp is statically linked (overlay loads are no-ops under PORT), its globals live wherever the linker put them in
the executable image, the console arena is replaced by one 16 MiB host heap block allocated once and recycled across scenes
(`decomp/src/sys/taskman.c`, PORT block), and the console threads run as Win32 fibers whose stacks the OS allocates (the console stack
pointers passed to thread creation are ignored, `port/stubs/n64_stubs.c`). The executable is linked with address-space layout randomisation
and high-entropy addressing enabled (PE header, read offline), so the image base, the heap block and every fiber stack sit at different
addresses in every process. Every region below that holds pointers therefore holds process-specific absolute addresses.

| # | Region | Where | Approximate size | Affects the simulation? | Absolute pointers | Notes for a snapshot |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Image static data: the decomp's globals and statics (thread control blocks, message queues, scheduler and task-manager state, input histories, the 1 MiB audio heap, save-data image, scene and battle state, per-character file pointers) plus the port stubs' state (simulated VI rotation, deferred SP/DP completions, thread registry) plus host statics (C runtime, libultraship, port, RL module) | `.data` section of the image (initialised 0.55 MiB, zero-filled 4.33 MiB) | 4.88 MiB total; the decomp's share is most of it but is not separable offline (no map file) | Yes for the decomp and stub parts (this is the console's RAM outside the arena); the host statics are presentation, transport and bookkeeping | Yes: into code, into itself, into R2, into R3 and R4 | Image base randomised per process. A blanket copy would also roll back host objects (mutexes, containers) and must not; the decomp's part needs its own bounds (section 2, "static bounds") |
| R2 | Scene arena: every task-manager and object-manager allocation of the running scene (object pools, fighter and stage structures, collision data, the copies of every asset file the stage loads, display-list buffers, graphics heap, RDP output buffer, object-thread control blocks) | One 16 MiB `malloc` block, allocated at the first scene, zero-filled and reused at every scene transition | 16 MiB reserved; the log of the last run shows 0.7 MiB allocated early in the stage load, the end-of-load figure is not logged | Yes (the core of the simulation) | Yes: into itself, into R1, into code (object procedure pointers), into R3's control blocks | Random base per process. The bonus stage declares no separate file heap, so its asset copies also live here (`sc1pbonusstagefiles.c`) |
| R3 | Coroutine stacks and control blocks: the boot fiber (1 MiB, finished after boot), the service fibers (ids 1 finished; 3 scheduler, 4 audio, 5 game, 6 controller and 8 live, 256 KiB committed each), and two object-thread fibers created by the interface code in the bonus stage (64 KiB each; the log shows two such thread ids) | OS fiber stacks (1 MiB reserve each), opaque OS fiber objects, small wrapper structs in the C runtime heap | about 2.4 MiB committed stack, about 9 MiB reserved | Yes: the parked call chains and locals are the console threads' state | Yes: return addresses, frame pointers, locals; the saved register set lives in the opaque fiber object | The stack ranges are not exposed by the OS from outside the fiber; the saved registers are not copyable through a documented interface (section 2, "coroutines") |
| R4 | Port bridge bookkeeping tied to game memory: the 32-bit token table that maps pointer slots in asset data to host pointers (flat array plus a free list), the loaded-file range registry, and the conversion registries that record which bytes in R2 have already been converted to host layout or format (structure fixups, texture fixup extents, de-swizzle marks, chain-slot marks, animation-stream un-halfswap marks and their allowed ranges) | C runtime heap (hash sets and vectors in `port/bridge/*`, `port/port_aobj_fixup.cpp`, `port/resource/RelocPointerTable.cpp`) | tens to hundreds of KiB | **Yes.** The token table is consulted on every pointer resolution; the conversion registries decide whether a first-use conversion runs. The conversions are lazy: the log of the last run shows texture fixups and animation binds happening frame by frame during the stage load and intro, so first-use conversions can also happen mid-episode | Keys are absolute addresses into R2 | Token slots are only invalidated at scene boundaries (monotone within a scene). The conversion registries assert facts about R2's bytes, so they must move with R2 or be re-derived (section 2). The animation-stream marks are never cleared: their header says the clear is "not wired in" and no caller exists (grep) |
| R5 | Presentation caches: packed display-list cache, texture cache, framebuffer mirrors, Fast3D state, interpolation and GBI trace state | libultraship and port heap | not measured | No. In no-render mode the display list is discarded before it is walked, so these are not touched after boot | Keys are R2 addresses | Evict for the arena range on any restore, as the scene transition already does, to be safe |
| R6 | libultraship runtime: context, SDL window and D3D11 device, audio player (output thread and ring buffer), control deck (SDL joystick), resource manager (archive handles, cache of raw file bytes, a thread pool that is idle during an episode), console variables, ImGui | Heap, OS handles, threads | the bulk of the process's 110 MiB working set | Only through controller reads (ports 1 to 3 are idle; port 0 is supplied by the stepping hook in RL mode) | Not applicable | Cannot be snapshotted or recreated from a snapshot; must stay alive across any in-process reset, and is why a cross-process boot snapshot cannot skip the boot (section 2) |
| R7 | RL harness state: the stepping state machine (mutex, condition variable, state, pending action, counters, latched copies of the latest observation and diagnostics), the transport worker thread and its sockets, the result monitor (one-shot latch, host-frame count), the cached configuration | `port/rl/*` statics and heap | small | No, but it defines the tick contract the harness reports | Not applicable | Must be re-armed by any reset or restore, never rolled back (section 2) |
| R8 | Outside process memory: the port log, the frozen configuration copies (written at exit), the save file (written by the backup path when a record improves, which a clear does), the one-shot result JSON, the private runtime directory, the loopback socket, GPU objects (none created after boot in no-render mode), OS handles | Disk, kernel | n/a | The save file is read at boot into R1 and the save-data image is read at the end of an episode (record comparison) | n/a | A fresh process reads a pristine save; an in-process second episode starts with the save-data image a clear may have updated (section 2, (C)) |
| R9 | Wall-clock-derived profiling fields: the scheduler and task manager measure frame and audio durations with the host counter | inside R1 | bytes | Not today: replays are exact, so these feed nothing the records see | n/a | A snapshot carries stale values; harmless by the same argument, checked by the fidelity test |

Two facts about R3 matter for every option. First, the bonus stage's static setup declares no object threads, yet the log shows two
object-thread coroutines created during the stage (by the interface code): object-thread coroutines are created and destroyed by game code
at run time, and their control blocks live in R2 while their stacks and wrapper objects live in R3. Second, each service fiber is parked at
the same wait inside the same call chain at every tick of a scene (the game thread at the task manager's tic wait, the others at their queue
waits); only a scene transition changes those call chains.

## 2. Mechanism options

**Common ground.** Every in-process mechanism runs on the main thread at the quiescent point the stepping design already has: the host gate
is closed (state WaitingForAction or EpisodeEnded), no fiber is running, the game clock is frozen because no VI retrace is posted, the
transport worker is blocked in the request that asked for the operation, libultraship's threads are idle (the audio output thread only drains
queued samples, which is presentation), and the watchdog only reads counters (its 3 s hang threshold is far above a memory copy). Nothing has
to be stopped or joined; the operation is one more thing the main thread does between two parked iterations. The flag that enables any of them
is PORT-only and default-off, effective only with effective interactive stepping, reported in `status` only when on, and with the flag off every
reply is byte-identical to today's (the rule the four diagnostic flags already follow).

**Where today's boot goes.** The startup split measured for the M6 record (unloaded, no-render): 2.05 s from process start to the transport
listening (process creation, libultraship initialisation, the console boot chain), then 0.36 s from there to WaitingForAction (scene load, the
asset conversions, the frames before tick 0). So the scene load is about 15 % of a boot; the rest is process and runtime initialisation that
no snapshot of game memory can skip. Under the lab's load a boot is 2.2 to 4.8 s (median 3.76 s); the split under load is unmeasured.

**Cross-process restore.** Restoring a snapshot into another process would require the same image base (randomisation is on), the same arena
and fiber-stack addresses (both come from the heap and the OS), the same addresses for every port-side object that R1 or R2 points to, and
identical R4 bookkeeping, and it could still not skip the 85 % of the boot that is R6. It is a port-wide change (fixed-address allocators,
randomisation off, a custom coroutine backend) for a small part of the boot. **Not recommended for any option; everything below is in-process.**

### (A) Boot snapshot: one snapshot at tick 0, restored instead of booting

- **What it is in-process.** After the first boot, copy R2, the decomp part of R1, the live fiber stacks of R3 and the R4 registries at the
  tick-0 quiescent point; at every later candidate, copy them back and re-arm R7, instead of running a scene transition. The prefix is still
  replayed from tick 0 by the harness, so the "replay from tick 0" shape of the search is kept; what is skipped is the scene reload (and the
  frames before tick 0), never the process boot (R6 stays alive, which is the whole point).
- **Static bounds.** A copy of all of `.data` would roll back host objects. The decomp's statics need their own bounds. The cleanest way found
  offline is build-only: a forced-include header for the `ssb64_game` object library (decomp sources, port stubs, the libultra and audio port
  sources) that places their initialised and zero-filled data in two dedicated PE sections, whose bounds the port reads from the image headers
  at run time. No decomp source edit, PORT-only by construction, and the stubs' VI and deferred-completion state is covered because the stubs
  are in that library. Verification that nothing simulation-relevant lies outside those sections is part of the fidelity test, not an
  assumption.
- **Coroutines.** Two variants. *Memory-only:* copy the committed stack range of each live fiber (recorded from inside each coroutine at its
  first run, since the OS exposes a fiber's bounds only to the fiber itself) and leave the opaque fiber objects alone, relying on the fact that
  every fiber is parked at the same wait with the same call depth at the snapshot and at the restore (true within a scene, section 1). The
  residue is the saved register set of the innermost frames, which the OS owns; it is expected identical at the same wait but that is an
  assumption the fidelity test must break or confirm. *Explicit context:* replace the Win32 fiber backend for Windows x64 with the kind of
  explicit-context switch the repository already has for other targets (`coroutine_posix.cpp`, `coroutine_aarch64.S`), so a coroutine's state
  is bytes we own; it needs the Windows stack-bounds fields of the thread block swapped at every switch for stack probes and unwinding
  (300 to 500 lines, the riskiest native change in this record). Object-thread coroutines created or destroyed between snapshot and restore
  must not have their wrapper objects or fibers freed while savestates are on (a deferred-destruction list), or a restored R2 points at freed
  memory.
- **R4.** The conversion registries must be copied with R2 (they are small hash sets: serialise and restore), or the restored memory is read
  as converted when it is not (or converted twice). The token table and file ranges can be left monotone within a scene: tokens embedded in
  restored memory were registered before the snapshot and slots are never freed within a scene. Presentation caches (R5) are evicted for the
  arena range without touching tokens.
- **Size and cost.** About 22 MiB per snapshot (16 MiB arena, up to 4.9 MiB statics, 2.4 MiB stacks, registries); a copy of that size costs a
  few milliseconds to a few tens of milliseconds under load (projection; 0.02 to 0.05 s is used in section 4 including one observe). Removes
  from today's per-candidate cost: the boot wall and its CPU, the close, the standby wait, the scene reload. Keeps: the prefix at 1.1 to 1.4 ms
  per tick (single step) or 0.35 to 0.5 ms (batched, projection).
- **Verdict.** Feasible in-process; cross-process not. It buys over (C) only the scene reload (0.5 to 0.9 s per candidate, projection) at the
  price of all the snapshot machinery; if that machinery is built, (B) follows for little more. Not recommended as a step of its own.

### (B) Mid-episode savestates: snapshot at any tick L, restore and continue

- **What it is.** The same copy as (A), taken at any parked tick inside the stage, kept in RAM under an id, restored on request; removes the
  boot and the prefix. Snapshots are only ever taken and restored at the quiescent point within the same scene, so the "same wait, same
  depth" property of the memory-only variant holds; a snapshot taken after the scene began unloading (native failure, game status 5) is
  refused.
- **Harness shape.** Additive protocol-1 operations `snapshot` (returns an id and the current step count), `restore` (id; reply carries the
  observation after the restore, like `observe`), `free` (id), with `status` carrying `savestate:true` and the number of snapshots held only
  when the flag is on. The worker keeps the archive's chain and end record at L exactly as today and checks, after every restore and before any
  burst, that the record of the restored state equals the stored end record (the restore-time analogue of today's prefix-end check). Step and
  consumed-tick semantics after a restore: the game clock fields come from restored memory; the module's step count is set to the snapshot's
  value and an episode or restore counter is added so no two results are confusable.
- **Memory and disk** (addendum (d)). Raw snapshots are about 22 MiB; the arena is mostly zero so a zero-page-sparse copy is expected several
  times smaller (unmeasured). Per worker, 16 raw snapshots are 0.35 GiB; at N = 5, 1.8 GiB on top of today's 1.1 GiB of game processes and
  the main process's 2.5 GiB soft budget: within 16 GiB only with a cap. One snapshot per archive cell (about 50 k cells) is out of the question
  in RAM (1 TiB raw) and impractical on disk; (B) therefore serves a working set (the segment optimiser's start states, a search's current
  frontier), not the whole archive, and the snapshot budget is a policy to decide (section 9).
- **What it removes.** Boot wall and CPU, close, standby wait, scene reload, and the prefix. The per-candidate wall becomes the segment's ticks
  plus the Python overhead (section 4), which puts the single-threaded selection of the main process (53 to 82 ms per dispatch) on the critical
  path: without incremental eligibility (review item M5 of the prefix-cost record) (B) is capped near 44,000 to 68,000 candidates per hour at
  N = 5, below what five workers could do.
- **Verdict.** Feasible in-process with the (A) machinery plus the registry and lifetime work; the largest gain of the four; the largest native
  change; only worth building after (C) has proven that a process can serve many episodes exactly.

### (C) In-process soft reset through the game's own paths

- **What exists.** The port already has an in-game console reset (`portSCManagerRequestReset` in `scmanager.c`, PORT-only): it winds the audio
  down, points the scene handoff at a target scene, asks the task manager to end the current scene at the frame boundary, and survives the 1P
  manager's nested scene chain through a sticky pending flag consumed at the top of the scene manager's dispatch loop. The RL boot override
  (`rlBootApply`) already enters the bonus stage directly from that dispatch loop by writing the same handoff the bonus character select
  writes, once per process. A scene transition zero-fills the arena, resets the task manager's heaps, evicts every port cache for the arena
  range, resets the structure-fixup registries and the packed display-list cache (`lbRelocInitSetup`), and the stage's start function re-arms
  the interactive input session at tick 0 exactly as at boot.
- **What (C) adds.** PORT-only, flag-gated: a repeatable form of the boot handoff applied when the dispatch loop consumes a pending reset while
  the RL flag is on (so the next scene is the bonus stage again, not the opening room); a `reset` request from the harness that uses the sticky
  reset from WaitingForAction (abort mid-episode) or from EpisodeEnded (after a clear or a fall), re-arms the stepping machine (back to Inactive,
  then WaitingForAction at the next Go-status read, the same predicate as at boot), makes the result record per episode instead of one-shot per
  process, and defers the clean exit to an explicit quit or a retirement count. The save-data image of R1 is re-applied from its boot-time copy
  at every reset so a clear's record update does not leak into the next episode's end-of-episode branch (the fresh-process baseline starts from
  a pristine save). No snapshot of any kind exists in (C): every candidate's tick 0 is produced by game code.
- **What must be excluded or reset.** Nothing is excluded: the game's own scene transition decides. Presentation and audio are reset by the
  game (the audio wind-down is part of the existing reset). The known gap found offline is the animation-stream conversion marks of R4, which
  are never cleared: when the second episode reloads the same asset at the same arena address (allocation is deterministic after the
  zero-fill), the marks say "already converted" while the bytes are freshly loaded. Whether that bites depends on whether the stage uses such
  streams and on the load addresses; it is the first thing the (C) fidelity run tests, and the fix (clear the marks for the arena range in the
  existing per-scene eviction) is a port-side one-liner family, PORT-only, that today's single-episode processes never needed.
- **Threads.** None to quiesce: the reset is requested at the quiescent point and performed by the game over the next few host iterations
  (scene end, scene start, the frames before tick 0); the harness sees Inactive then WaitingForAction, as at boot.
- **Size and cost.** No snapshot memory. The reset costs one scene reload plus the frames before tick 0: 0.36 s unloaded (measured for the M6
  record as the transport-to-fresh stage), 0.5 to 0.9 s under load (projection, section 4). Removes from today's per-candidate cost: the boot
  wall and its CPU, the close and the standby wait. Keeps: the scene reload and the prefix.
- **Verdict.** The smallest native change of the three resets, reuses two existing mechanisms, needs no snapshot, keeps "replay from tick 0"
  literally true for every candidate, and removes the binding cost (the boot). **Recommended first.** Its fidelity question is whether a
  second episode in a process equals a first episode in a fresh process; that is exactly what the fidelity test measures.

### (D) Forward-only chaining without reset (the segment study's continuation path)

- One process, one boot, one episode: a candidate that breaks its target continues into the next segment from the state it reached, so one
  boot evaluates a chain of segments. Nothing new natively. It composes with (A), (B) and (C) (a chain runs after any reset) and is the
  comparison baseline: today's pipeline (one standby per worker, boot-bound as soon as a job is shorter than a boot) and revision 2 (two
  standbys, close off the critical path), both capped by a boot CPU cost nobody has measured.

## 3. Fidelity proof design (to run in November, not now)

**Statement to prove.** For every tested prefix, restore-and-continue (or reset-and-replay for (C)) produces, at every tick, the same canonical
record and the same tick-contract values as a fresh process replaying the same words from tick 0 with the same flags.

**Material.** Only the agent's own data: the registered clear (1,885, cid 1360), the lab clear (1,245), and archive cells drawn by a generic
stratification: 20 cells per level and, within a level, both ground/air states, with prefix lengths spread over 0, 1, 7, 64, 300, 1,000 and
the deepest available; continuation words are the cell's own burst words or Python-seeded random words (Python experiment seeds are allowed).
No coordinates, census numbers or route knowledge select anything.

**Procedure per case (words W, length L, continuation K = 300 ticks or to the episode end).**

1. Fresh reference: a fresh process with the verify flags replays W[0:L+K] from tick 0; keep every per-tick reply line (the record), the chain
   at every tick, and the terminal fields if reached.
2. Under test, in one long-lived process:
   - (C): run W[0:L+K] from tick 0 after a soft reset that followed another episode (alternating clears, falls and aborted prefixes before it);
   - (A): restore the tick-0 snapshot, then run W[0:L+K];
   - (B): run W[0:L] from tick 0 (or from a restore), `snapshot` at L, run J = 200 perturbation words, `restore`, run W[L:L+K].
3. Compare at every tick: the record digest, the chain, `consumed_tick`, `input_tick == consumed_tick + 1`, state names, the relative step
   count, the diagnostic blocks the verify flags add; and at the end `completion_time_passed`, `completion_input_tick` and `targets_broken`
   when the episode ended. `host_frame` and `host_frames` are process-lifetime counters and are excluded (they already are in the M6 proof).
4. Region self-check (snapshot options only): after step 2, take a second snapshot at L+K; restore to L again, run W[L:L+K] again, snapshot at
   L+K again; the two snapshots must be byte-equal region by region (whole-region equality, no parsing).

**Repetition.** At least 60 cases per option across the stratification; 50 consecutive restores of one snapshot in one process (B) or 50
consecutive resets in one process (C) with the reference compared each time; alternation between two snapshots; restores taken after a clear
and after a fall back to a mid-episode L; and for (C) the second, tenth and fiftieth episode of a process against the fresh reference.

**Pass criteria, fixed in advance.** PASS only with zero mismatches over every case, cycle and tick, and byte-equal regions in the self-check.
**A single mismatch means the restore (or reset) does not reproduce the simulation and the option is unusable for search until the cause is
found and fixed; a fix reopens the whole test, never the failing case alone.** Partial passes, tolerances and "later ticks only" are not
defined.

## 4. Cost model: candidates per hour at N = 5 (projections)

Computed by `logs/frs_savestate/cost_model.py` from the recorded constants of `docs/frs_prefix_cost_2026-10-14.md` and the segment study:
boot 3.76 s loaded median, single-step tick 1.1 / 1.25 / 1.4 ms, batched tick 0.35 / 0.42 / 0.5 ms (itself a projection), today's per-job
overhead 2.0 s and revision 2's 0.3 s, selection 53 to 82 ms per dispatch in one main process, and a boot CPU cap of 10,800 per hour if a boot
costs about 2 CPU-seconds (unmeasured). The projected constants, with nothing measured behind them: soft reset 0.5 / 0.7 / 0.9 s under load
(the 0.36 s unloaded scene stage scaled by the boot's loaded-to-unloaded ratio), restore 0.02 / 0.035 / 0.05 s, and 0.15 / 0.2 / 0.3 s of
Python overhead per in-process job (no close, no standby wait). Ranges are low-to-high constants; the in-process columns are capped by the
main process's selection capacity (43,900 to 67,900 dispatches per hour).

| job shape | (D) today, one standby | (D) revision 2 | (D) rev. 2 + batched prefix | (C) soft reset, single step | (C) soft reset + batched prefix | (A) tick-0 restore, single step | (A) tick-0 restore + batched prefix | (B) mid-episode restore |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| segment, prefix 0, 178 ticks | 4,800 | 9,600 (boot CPU cap 10,800) | 9,600 (cap 10,800) | 12,400 to 21,300 | same | 30,000 to 49,200 | same | 30,000 to 49,200 |
| segment, prefix 461, 178 ticks | 4,800 | 9,600 (cap 10,800) | 9,600 (cap 10,800) | 8,600 to 13,300 | 10,700 to 17,900 | 14,500 to 20,600 | 21,700 to 34,100 | 30,000 to 49,200 |
| segment, prefix 1,042, 93 ticks | 4,800 | 9,600 (cap 10,800) | 9,600 (cap 10,800) | 6,500 to 9,500 | 9,700 to 16,100 | 9,300 to 12,700 | 18,000 to 28,300 | 37,500 to 66,100 (selection-capped) |
| archive job, run 2 shape (1,170 + 106) | 4,800 (measured 5,057) | 9,500 (cap 10,800) | 9,600 (cap 10,800) | 6,000 to 8,800 | 9,300 to 15,300 | 8,400 to 11,400 | 16,600 to 25,900 | 36,100 to 62,800 (selection-capped) |

Per-candidate wall at the mid constants (seconds): segment with prefix 461: (D) job 2.8 inside a 3.76 s cycle, (C) 1.7, (A) 1.0, (B) 0.46;
archive job: (D) 3.6 in 3.76, (C) 2.5, (A) 1.8, (B) 0.37.

**Which constant each column depends on.** (D) today and revision 2: the boot wall and, for revision 2, the boot's unmeasured CPU cost (d1
of the prefix-cost record), which is why both are shown with the cap. (C): the loaded scene-reload time (unmeasured; the single most
important number for the recommendation) and the single-step tick. (A): the restore cost (unmeasured) and the single-step tick. (B): the
restore cost, the burst tick and above all the selection time of the main process. The batched-prefix columns add the block tick, itself a
projection of the prefix-cost record. Every in-process column also assumes the per-job Python overhead without a close (unmeasured). Reading:
(C) alone is a 1.3 to 2.8 times gain over today on the segment shapes and 1.3 to 1.8 on the archive shape; (C) makes the prefix the dominant
cost, so the batched prefix becomes the next lever after it (another 1.3 to 1.7 times); (B) is 6 to 10 times today but needs the selection
work to realise it.

## 5. Constraint analysis

- **PORT-only and default-off.** (A) and (B) add no decomp code at all: the arena base and size are already PORT-only globals of the task
  manager, the static bounds come from a build-only section placement, and everything else is `port/rl`, `port/bridge` registry hooks and the
  coroutine layer. (C) adds one PORT-only hook in the scene manager's dispatch (the repeatable handoff) next to the existing PORT-only reset,
  and reuses `rlBootApply`'s pointer-passing style so no decomp layout is mirrored. All of it hangs off one new environment flag effective only
  with effective stepping; `status` reports it only when on; with it off the operation answers `unknown_op` and every reply is byte-identical.
- **Non-PORT byte-matching.** Untouched by (A), (B) and (C) as designed. The audit's item 9.4 (`docs/rl_generalization_audit_2026-10-13.md`,
  decomp commit `e4bc8e24c`: two includes and the controller-callback pointer in `sc1pbonusstage.c` outside `#ifdef PORT`) is where every
  input tick is consumed; none of the options changes that callback, and none depends on its guard. Interaction to note: the November fix of
  9.4 (wrapper under `#ifdef PORT`, `#else` the original callback) must leave the PORT executable's hash unchanged, and the savestate build will
  change the hash; doing the 9.4 fix in its own build first keeps the identity chain readable (section 9, Q7). Not fixed here.
- **Replay truth and claims unchanged.** The native text-replay path (`SSB64_BTT_INPUT`) keeps precedence over stepping and is not touched;
  claims are replayed from tick 0, twice, in fresh processes with the verify flags, exactly as today, and the fresh-process boot path is not
  changed by a flag that is off. The archive's chain definition is unchanged: Python computes every record digest and chain from the streamed
  replies; (B) only reads the stored chain at L and verifies the restored record against the stored end record before continuing.
- **Lab guards.** The lab root, the lab lock, the readiness thresholds (never lowered), the HEAD check, the frozen configuration copies and their
  hashes, the per-tick checks (`tick0`, `prefix_end`, `prefix_ended`, `consumed_tick`, `terminal_expected`, `reverify`, `pin_drift`, `bad_reply`,
  `trace`) all stay. Two guards are added rather than removed: the restore check (B) and a false-claim guard (section 6). One existing
  field changes meaning: `host_frames` counts frames since process start, so for in-process episodes it is reported but never pinned (today's
  verification records it as `host_frames_equal`, informational).
- **Process lifetime.** The M2 contract "fresh episode = new process" becomes "fresh episode = new process or a reset/restore in a process that
  has passed the fidelity test", with an episode counter in `status` and in every job record, and a retirement rule per process (section 9, Q5).
  The one-shot result JSON and the deferred exit become per-episode and explicit.

## 6. Discovery risk: how an imperfect restore could lie, and why the claims path catches it

- **False anomalies.** A restore that misses a region or a registry produces states no replay from tick 0 reaches: stale conversion marks make
  the game read unconverted bytes (impossible velocities, positions or statuses), an unrestored lifetime pointer makes a thread resume into
  freed memory (a crash, or silent garbage), a register residue changes one local. Part 4 of the addendum already rules that an anomaly counts
  as a game discovery only if it reproduces by replay from tick 0; under savestates that rule is load-bearing, and the anomaly detector must
  tag every event with whether it was observed after a restore.
- **False clears.** A clear reached through a bad restore is a candidate word sequence whose replay from tick 0 does not clear. The claims path
  (two fresh-process replays with the verify flags) rejects it: the claim costs two boots and the replays (about 20 to 24 s) and registers
  nothing. What a bad restore can therefore never do is register a false result; what it can do is waste verification time and, worse, steer
  the search with fiction (an archive cell whose stored end record was produced by a bad continuation). Two guards: (i) every registered
  state in the archive is still produced by a chain that Python checks tick by tick, and after a restore the first check is the stored end
  record at L; (ii) a run-level false-claim rate guard: claims refuted by replay are counted, and a run stops (LAB_INVALID) at the first refuted
  claim in the pilot and at a fixed small count afterwards, because a refuted claim under savestates is evidence about the mechanism, not bad
  luck.
- **Why replay from tick 0 is sufficient as the final arbiter.** The claim is a word sequence and nothing else; its verification uses neither the
  snapshot nor the long-lived process. A false clear cannot pass it; a true clear found through a restored state passes it like any other.
  The only thing the claims path cannot catch is a missed true route (a bad restore making the search blind), which is a throughput loss, not a
  false result, and which the fidelity test exists to prevent.

## 7. Minimal native pilot for November (about one hour of native time, verdicts fixed in advance)

Preconditions (zero ticks): the owner's decisions of section 9; the flag implemented for the chosen option; the new executable built, archived
under `D:/BattleShip_exe_archive/<date>_<hash>/` with its runtime files, and its hash recorded; a lab tool with the usual guards; HEAD committed.

- **P0, identity with the flag off (about 10 minutes).** The registered clear (1,885, cid 1360) replayed twice in fresh processes with the verify
  flags on the new executable, flag off, compared to its registered digests and pins; the M6 equivalence regression. Verdict `BUILD_INVALID`
  on any difference, and the pilot stops there.
- **P1, fidelity (about 30 minutes).** Section 3 reduced to the pilot: 12 cases for the chosen option in one long-lived process (for (C): the
  registered clear, the same words again, the lab clear, three stratified archive prefixes with random continuations, two aborted prefixes, a
  fall, then the registered clear again as the tenth, eleventh and twelfth episodes), each compared tick by tick with a fresh-process replay of
  the same words. Verdicts: `FIDELITY_PASS` with zero mismatches; `FIDELITY_FAIL` otherwise, recording the episode index and the first
  mismatching tick, and the pilot stops there. No retry inside the pilot.
- **P2, throughput (about 15 minutes, only after `FIDELITY_PASS`).** N = 5, the segment shape with prefix 461 and 178-tick bursts, five minutes
  of the control (today's pipeline) and five minutes of the option, same executable, same flags; record candidates per hour, the reset or
  restore wall distribution, per-process working set, and the machine sampler's CPU utilisation (the first measurement of the boot's CPU
  cost, by difference). Verdicts on the ratio option / control: `THROUGHPUT_PASS` at 1.8 or more, `MARGINAL` between 1.2 and 1.8, `NO_GAIN`
  below 1.2. These thresholds are the section-4 projection's low end for (C) and are fixed here so the result cannot be argued after the fact.
- **Hard cap** 60 minutes of native time; every launch under the lab's guards; every outcome written to a results record whether PASS or FAIL;
  nothing extended, retried or repaired inside the pilot.

## 8. Effort and risks per option; what cannot be determined offline

| Option | Native change (estimate) | Harness change | Main risks |
| --- | --- | --- | --- |
| (C) soft reset | about 150 to 250 lines: the repeatable handoff at the dispatch loop (decomp, PORT-only), the save-data image re-apply, the stepping re-arm, the `reset` operation, per-episode results, `status` fields | client operation, worker episode lifecycle (episode id, retirement), lifecycle tests, fidelity tool | cross-scene residue that the game's own transition does not reset (the animation-stream marks found offline; anything else only the test shows); the scene-end path after a fall or an abort; semantics of the deferred exit |
| (A) tick-0 restore | about 500 to 800 lines: static bounds (build), stack range capture, deferred coroutine destruction, registry serialisation, cache eviction, `snapshot`/`restore` operations; plus 300 to 500 for the explicit-context backend if the memory-only variant fails | as (C) plus snapshot handling | incomplete region coverage (silent divergence), register residue, lifetime pointers into R3; buys little over (C) |
| (B) mid-episode | (A) plus snapshot ids, memory accounting, refusal rules (about 100 lines more) | worker uses stored chains at L, restore check, snapshot budget policy, selection work (incremental eligibility) to realise the gain | everything in (A); memory budget on 16 GiB; token-table growth over a long process; the main process's selection becomes the bound |
| (D) forward-only | none | revision 2 (two standbys, close off the critical path): one session | bounded by the boot's CPU cost (unmeasured) |

**What cannot be determined offline.**

- The CPU cost of a boot and the machine's utilisation at N = 5 (never sampled); it bounds every (D) column and is measured by difference in P2.
- The split of the loaded boot between process and runtime initialisation and the scene load; only the unloaded split exists (2.05 s / 0.36 s).
- The scene reload time under load, the single constant that decides whether (C) is a 1.3 or a 2.8 times gain.
- The arena's used size at tick 0 and at the end of an episode (the log shows 0.7 MiB early in the load), hence the real snapshot size and
  its sparse-copy ratio.
- Whether first-use conversions actually happen after tick 0 in this stage, and whether the never-cleared animation-stream marks bite on scene
  re-entry (both decide how much of R4 must move with R2).
- Whether the register residue of the memory-only coroutine variant is identical at the same wait (only the fidelity test can say).
- Whether any token value or any wall-clock-derived profiling value influences the records (expected not; test).
- The Python side's capacity at three to ten times today's dispatch rate (selection, ingest, memory growth per cell).
- Whether libultraship's audio and controller paths tolerate in-process episodes indefinitely (leaks, handle counts), hence the retirement count.

## 9. Open questions for the owner (recommendation first)

- **Q1. Which option is piloted in November week 1?** *Recommended: (C), the in-process soft reset.* It is the smallest native change, needs no
  snapshot, keeps every candidate's tick 0 produced by game code, removes the binding cost, and its fidelity test doubles as the proof that a
  process can serve many episodes, which (B) needs anyway. Alternatives: (B) directly (largest gain, largest change, snapshot questions open);
  (D) revision 2 only (Python, bounded by boot CPU); none.
- **Q2. Snapshot restores and the RNG rule** (addendum (b); the owner's decision, not a conclusion of this record). *Recommended: decide only
  (C) now, which involves no snapshot, and take the snapshot question up after (C)'s pilot result, with this record's section 2 as the
  description of what an opaque snapshot is and how it is only ever compared (whole-region equality in the fidelity test).* Alternatives: allow
  opaque snapshots for search now; disallow snapshots entirely (then (A) and (B) are closed and (C) and (D) remain).
- **Q3. Fidelity bar.** *Recommended: section 3 as written, zero tolerance, byte-identical records and contract at every tick on every case,
  plus the region self-check for snapshot options.* Alternative: end-record equality only (rejected here: a projection can hide state).
- **Q4. What counts as found.** *Recommended: unchanged, a clear counts only after replay from tick 0, twice, in fresh processes with the verify
  flags, and the pilot stops at the first refuted claim.* Alternative: tolerate a small refuted-claim count from the start (not recommended
  before the mechanism has a track record).
- **Q5. Process lifetime hygiene for in-process episodes.** *Recommended: retire a process after 50 episodes or at the first mismatch of any
  per-tick check, keep one standby per worker for retirements, and record the episode index in every job.* Alternative: unlimited lifetime.
- **Q6. Memory and disk policy for (B), if it is ever built.** *Recommended: RAM only, at most 16 snapshots per worker, zero-page-sparse copies,
  explicit `free`, refusal above the cap; no disk spill.* Alternative: spill to D: (slow, large, and the evidence roots there are protected).
- **Q7. Build identity order.** *Recommended: fix audit item 9.4 in its own build first and verify the PORT executable's hash is unchanged; then
  the savestate or reset build as a new archived executable with its own runtime files and pins.* Alternative: one build for both (the hash
  check for 9.4 would be lost).
- **Q8. The native batched prefix.** *Recommended: design and build it after (C) has been measured, since (C) makes the prefix the dominant
  per-candidate cost (section 4: another 1.3 to 1.7 times on top of (C)).* Alternative: before (C) (it does not change the boot-per-candidate
  equation, as the segment study found).
- **Q9. Disclosure** (addendum (e)). *Recommended: say in the video that the search used in-process resets or savestates for throughput and
  that every result shown was replayed from tick 0 in a fresh process.* Alternative: no statement.
- **Q10. Pilot scope.** *Recommended: section 7 as written, one hour, verdicts fixed, no retry.* Alternative: a longer first campaign.

## Compliance

- Zero native ticks; nothing launched, built or compiled. Git: HEAD `be1dc29`, tree clean before; after, the only change is this untracked
  record. No commit, push, branch or stash.
- Nothing written under `rl/`, `tools/`, `port/`, `decomp/`, `runs/`, `C:/BattleShip_lab/` or D:. Working files only under `logs/frs_savestate/`
  (`logs/` is Git-ignored, rule `.gitignore:111`, checked with `git check-ignore`). Scripts are standard-library Python, run with `python -B`,
  reading files only.
- Memory treated as opaque regions; no random-number state located, named, read, described or reasoned about; snapshots described as opaque
  byte copies compared only by whole-region equality in the fidelity test. No validation-only material or external time read,
  mentioned or used.
- Line endings: this record and every working file are LF only (CR counts reported in the session report, all 0).

## Appendix. Working files (Git-ignored, `logs/frs_savestate/`)

- `pe_sections.py`: prints the PE section table of an executable (name, virtual and raw size, flags, image base, randomisation flags); run on
  `build-us/Release/BattleShip.exe` for section 1's R1 figures.
- `cost_model.py`: the section-4 model; prints the table and the per-candidate walls; every constant named and marked recorded or projected.
- `cost_model_output.txt`: the printed output of `cost_model.py`.
