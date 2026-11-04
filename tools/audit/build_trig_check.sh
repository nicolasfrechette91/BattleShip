#!/usr/bin/env bash
# Build tools/audit/trig_ulp_check with GCC or Clang (Linux, WSL, macOS).
# Offline audit tool: no game, no ROM. See REVIEW_2026-11-03.md, finding D1.
#
#   tools/audit/build_trig_check.sh [OUT_DIR]      (default: build-audit/)
#
# Needs the decomp submodule checked out at its pinned commit. The decomp's
# trig sources carry `#pragma weak sinf = __sinf`; GCC/Clang honour it, which
# would make the harness's "host" column call libultra itself, so the weak
# aliases are stripped from the two objects with objcopy before linking.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/build-audit}"
CC="${CC:-cc}"
D="${DECOMP_DIR:-$ROOT/decomp}"   # override to point at another checkout of the pinned decomp
if [[ ! -f "$D/src/libultra/gu/sinf.c" ]]; then
	echo "decomp/src/libultra/gu/sinf.c not found: check out the decomp submodule first" >&2
	exit 2
fi
mkdir -p "$OUT"
# Same options the port applies to these two files on non-MSVC (CMakeLists.txt).
DEFS=(-D_LANGUAGE_C -DF3DEX_GBI_2=1 -DPORT=1 -DNON_MATCHING=1 -DNON_EQUIVALENT=1 -DAVOID_UB=1)
for f in sinf cosf; do
	"$CC" -O2 -ffp-contract=off -fno-strict-aliasing -fno-builtin "${DEFS[@]}" -I"$D/include" -I"$D/src" \
		-c "$D/src/libultra/gu/$f.c" -o "$OUT/sgi_$f.o"
done
objcopy -N sinf -N fsin "$OUT/sgi_sinf.o"
objcopy -N cosf -N fcos "$OUT/sgi_cosf.o"
"$CC" -O2 -ffp-contract=off -fno-builtin -c "$ROOT/tools/audit/trig_ulp_check.c" -o "$OUT/trig_ulp_check.o"
"$CC" -O2 "$OUT/trig_ulp_check.o" "$OUT/sgi_sinf.o" "$OUT/sgi_cosf.o" -lm -o "$OUT/trig_ulp_check"
echo "built $OUT/trig_ulp_check"
