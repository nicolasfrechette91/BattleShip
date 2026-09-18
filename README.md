<p align="center">
  <img src="assets/BattleShip.svg" alt="BattleShip" width="640">
</p>

# BattleShip Reinforcement Learning Fork

This repository is an experimental fork of
[JRickey/BattleShip](https://github.com/JRickey/BattleShip), a native PC port
of Super Smash Bros. for Nintendo 64. This fork focuses on automating Mario's
Break the Targets as the first environment for reinforcement-learning research,
agent training, and input optimization.

The upstream port is built on
[VetriTheRetri/ssb-decomp-re](https://github.com/VetriTheRetri/ssb-decomp-re),
uses [libultraship](https://github.com/Kenix3/libultraship) for PC-native
rendering, audio, and input, and uses
[Torch](https://github.com/HarbourMasters/Torch) to extract assets from a
user-supplied ROM.

## Research objective

The long-term objective is to provide a fast, automated environment where
reinforcement-learning agents can interact with Super Smash Bros. 64, observe
game state, receive rewards, and discover optimized strategies. Mario's Break
the Targets is the initial training environment and benchmark, but the project
is intended to support broader reinforcement-learning experiments over time.

The current Mario Break the Targets benchmark:

- Starts Mario's Break the Targets route automatically.
- Replays 468 gameplay input rows from a known-good input sequence.
- Completes the stage with an internal time of 7.43 seconds.
- Restricts automated playback to Mario's Break the Targets stage so normal
  input remains available elsewhere.
- Supports state tracing for positions, velocities, actions, and target
  progress.

The immediate milestone is a reinforcement-learning episode runner that can
launch the stage, accept agent inputs, expose machine-readable observations,
detect completion or failure, calculate a result, and reset without manual
interaction. The existing replay provides a known-good baseline for validating
the environment before agent training begins.

## Project status

This is a reinforcement-learning research fork, not an official BattleShip
release. The initial Mario Break the Targets environment currently targets the
US version of the game. Other BattleShip features and platform support come
from the upstream project unless explicitly documented as changes in this fork.

## No copyrighted assets are included

No Nintendo assets, including game code, textures, audio, models, text, or ROM
data, are checked into this repository or distributed with builds. Every byte
of Nintendo-owned data used by the port is extracted at build time from a ROM
supplied by the user. You must own a legal copy of Super Smash Bros. for
Nintendo 64 to build or run the project.

The decompiled game code is region-specific, so US and JP are separate builds.
Build the version matching your ROM with `-DSSB64_VERSION=us` or
`-DSSB64_VERSION=jp`. See [BUILDING.md](BUILDING.md) for complete instructions.

| Version | Game code | SHA-1 | MD5 |
| --- | --- | --- | --- |
| US NTSC-U v1.0 | `NALE` | `e2929e10fccc0aa84e5776227e798abc07cedabf` | `f7c52568a31aadf26e14dc2b6416b2ed` |
| JP Nintendo All-Star Dairantou Smash Brothers v1.0 | `NALJ` | `4b71f0e01878696733eefa9c80d11c147ecb4984` | `66db457b130d31a286a23d6e4dd9726e` |

If your ROM does not match the hash for its version, it will not work.

## Building

Follow the upstream-compatible [building instructions](BUILDING.md). Clone the
repository with its submodules, provide the supported ROM for the region you
want to build, and configure a separate build directory for each region.

Example configuration:

```powershell
cmake -S . -B build-us -DSSB64_VERSION=us
cmake --build build-us --config Release
```

```powershell
cmake -S . -B build-jp -DSSB64_VERSION=jp
cmake --build build-jp --config Release
```

## Architecture

BattleShip keeps three main layers separate:

- `decomp/` contains the decompiled SSB64 game code. Port-specific changes in
  this layer should remain protected by `#ifdef PORT` where appropriate.
- `port/` contains the modern C++ integration layer, platform glue, hooks,
  resource factories, input handling, and PC-specific behavior.
- `libultraship/` provides the PC-native runtime, including Fast3D rendering,
  SDL2 input, audio, resource management, and the ImGui interface.

Torch reads the user-supplied ROM during the asset-generation process and
produces `BattleShip.o2r`. The ROM itself is not read during normal gameplay.

### Relevant repository paths

```text
decomp/       Decompiled SSB64 game code and learning-environment integration
port/         PC runtime integration, input, hooks, and diagnostics
libultraship/ Native rendering, audio, input, and resource management
torch/        ROM asset-extraction tool
yamls/        Region-specific asset-extraction definitions
tools/        Code-generation and development utilities
docs/         Architecture, modding, debugging, and bug documentation
```

Additional technical references are available in:

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/build_and_tooling.md`](docs/build_and_tooling.md)
- [`docs/c_conventions.md`](docs/c_conventions.md)
- [`docs/n64_reference.md`](docs/n64_reference.md)
- [`docs/modding.md`](docs/modding.md)

## Credits and licensing

- Original BattleShip PC port:
  [JRickey/BattleShip](https://github.com/JRickey/BattleShip) and its
  contributors.
- Game code, data, sound, textures, models, and trademarks: Nintendo and HAL
  Laboratory. These assets are not included or redistributed, and this project
  is not endorsed by either company.
- Decompilation:
  [VetriTheRetri/ssb-decomp-re](https://github.com/VetriTheRetri/ssb-decomp-re)
  and its contributors. It is included as the `decomp/` submodule. Refer to
  that project for its applicable rights and restrictions.
- Runtime framework: [libultraship](https://github.com/Kenix3/libultraship),
  copyright 2022 kenix3, MIT-licensed and originally created by the Harbour
  Masters team.
- Asset pipeline: [Torch](https://github.com/HarbourMasters/Torch), copyright
  2023 Lywx and the Harbour Masters contributors, MIT-licensed.
- Menu fonts: [Montserrat](https://github.com/JulietaUla/Montserrat) and
  [Inconsolata](https://github.com/cyrealtype/Inconsolata), distributed under
  the SIL Open Font License 1.1.
- Controller mappings: [`gamecontrollerdb.txt`](gamecontrollerdb.txt) from
  [SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB),
  distributed under the zlib license.
- High-resolution texture-pack support is inherited from upstream. SSB
  Reloaded by [GhostlyDark](https://github.com/GhostlyDark) is distributed
  separately and is not included in this repository.

This project is not affiliated with, endorsed by, or authorized by Nintendo,
HAL Laboratory, Harbour Masters, or the upstream BattleShip maintainers. Do not
upload ROMs, extracted `.o2r` archives, or other copyrighted game assets to
issues or pull requests.

## License

Port-specific source code outside the `decomp/`, `libultraship/`, and `torch/`
submodules is distributed under the [MIT License](LICENSE), subject to the
copyright and attribution requirements described in that file.

That license does not grant rights to Nintendo or HAL Laboratory assets, the
decompiled game code, or independently licensed dependencies. Each submodule
and bundled third-party component remains subject to its own license or
applicable terms.
