#!/usr/bin/env bash
# Static scan of the decomp's gameplay sources for paths on which a local may
# be read before it is written (clang -Wsometimes-uninitialized,
# -Wconditional-uninitialized, -Wuninitialized), compiled with the port's own
# PORT-mode definitions. Offline audit tool: no game, no ROM, nothing built.
# See REVIEW_2026-11-03.md, finding D7. Every hit is a CANDIDATE: most are
# switch statements without a default that the game never reaches.
#
#   tools/audit/uninit_scan.sh [OUT_FILE]     (default: build-audit/uninit_scan.txt)
#
# Overrides: CLANG (default clang), DECOMP_DIR, LUS_DIR (other checkouts of the
# pinned submodules), REGION (us|jp, default us).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLANG="${CLANG:-clang}"
D="${DECOMP_DIR:-$ROOT/decomp}"
L="${LUS_DIR:-$ROOT/libultraship}"
REGION="${REGION:-us}"
OUT="${1:-$ROOT/build-audit/uninit_scan.txt}"
[[ -d "$D/src/ft" ]] || { echo "decomp sources not found at $D" >&2; exit 2; }
[[ -d "$L/include" ]] || { echo "libultraship headers not found at $L" >&2; exit 2; }
mkdir -p "$(dirname "$OUT")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/inc"
cp "$ROOT/include/reloc_data.$REGION.h" "$TMP/inc/reloc_data.h"
UC="$(echo "$REGION" | tr '[:lower:]' '[:upper:]')"
FLAGS=(-fsyntax-only -std=gnu11 "-DREGION_$UC=1" "-DVERSION_$UC=1" -DNON_MATCHING=1 -DNON_EQUIVALENT=1 -DAVOID_UB=1
       -DPORT=1 -DF3DEX_GBI_2=1 -D_LANGUAGE_C -DN_MICRO=1 -D_USE_MATH_DEFINES
       -I"$TMP/inc" -I"$ROOT/include" -I"$D/include" -I"$D/src" -I"$ROOT/port" -I"$ROOT/debug_tools" -I"$L/src" -I"$L/include"
       -Wno-everything -Wuninitialized -Wsometimes-uninitialized -Wconditional-uninitialized)
shopt -s nullglob
FILES=("$D"/src/ft/*.c "$D"/src/ft/ftcommon/*.c "$D"/src/ft/ftchar/ftmario/*.c "$D"/src/gr/*.c "$D"/src/gr/grcommon/*.c
       "$D"/src/wp/*.c "$D"/src/wp/wpmario/*.c "$D"/src/mp/*.c "$D"/src/gm/*.c "$D"/src/sys/*.c "$D"/src/lb/*.c "$D"/src/ef/*.c
       "$D"/src/sc/sc1pmode/sc1pbonusstage.c "$D"/src/if/ifcommon.c)
: > "$TMP/raw.txt"
fail=0
for f in "${FILES[@]}"; do
	if ! "$CLANG" "${FLAGS[@]}" "$f" >> "$TMP/raw.txt" 2>&1; then
		fail=$((fail + 1))
		echo "COMPILE FAILED: ${f#"$D"/}" >> "$TMP/raw.txt"
	fi
done
grep -E "warning:|COMPILE FAILED" "$TMP/raw.txt" | sed -E "s#^$D/##; s/ \[-W[a-z-]+\]$//" | sort -u > "$OUT"
echo "files=${#FILES[@]} compile_failures=$fail candidates=$(grep -c 'warning:' "$OUT" || true) -> $OUT"
