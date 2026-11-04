/*
 * trig_ulp_check.c -- offline audit tool (no game, no ROM, no native run).
 *
 * Compares libultra's software trig (__sinf / __cosf, compiled from the
 * pinned decomp's src/libultra/gu/sinf.c and cosf.c, the code the N64 ran)
 * with two references, over EVERY float in each range:
 *
 *   host   the host C library's sinf / cosf (glibc on Linux, ucrt on
 *          Windows/MSVC). On MSVC this is exactly what the bare sinf()/cosf()
 *          call sites of the decomp resolve to in BattleShip.exe, because
 *          MSVC ignores the decomp's `#pragma weak sinf = __sinf`
 *          (CMakeLists.txt, comment above the SSB64_LIBULTRA_PORT block).
 *   cr     (float)sin((double)x), a correctly rounded float in practice.
 *
 * Why: the bare calls feed gameplay on MSVC builds, for example every
 * weapon hitbox offset (decomp/src/wp/wpprocess.c wpProcessUpdateHitOffsets
 * -> src/sys/vector.c syVectorRotate3D), so any 1-ulp difference between
 * host and libultra trig is a difference between the Windows port, the
 * Linux port (GCC/Clang honour the pragma) and the original game.
 * See REVIEW_2026-11-03.md, finding D1.
 *
 * Build: tools/audit/build_trig_check.sh (GCC/Clang), or on Windows the
 * commands in MORNING_RUNBOOK.md (cl.exe). Usage:
 *   trig_ulp_check                 the default gameplay angle ranges
 *   trig_ulp_check LO HI           one range [LO, HI), 0 <= LO < HI
 * Only non-negative ranges are walked (cos is even; the libultra sin
 * handles the sign separately, so the negative half mirrors the positive).
 *
 * Optional (MSVC x64 only, opt-in): define TRIG_FMA3_TOGGLE to repeat the
 * host column with the CRT's FMA3 code paths disabled (_set_FMA3_enable(0)),
 * which tells whether ucrt sinf/cosf results depend on the CPU's FMA3
 * support. Not compiled in the cloud review (no MSVC there).
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

float __sinf(float);
float __cosf(float);

/* libultra's NaN branch references this (port/stubs/libc_compat.c defines it
 * in the real build). Set from its bit pattern in main(): MSVC's C mode does
 * not accept NAN as a static initializer on every SDK. */
float __libm_qnan_f;

typedef struct {
	unsigned long long n, host_diff, cr_diff, host_gt1, cr_gt1;
	float host_first, cr_first;
} Tally;

static uint32_t bits_of(float f) {
	uint32_t u;
	memcpy(&u, &f, sizeof u);
	return u;
}

static float float_of(uint32_t u) {
	float f;
	memcpy(&f, &u, sizeof f);
	return f;
}

static unsigned long ulp_distance(float a, float b) {
	const long long d = (long long)bits_of(a) - (long long)bits_of(b);
	return (unsigned long)(d < 0 ? -d : d); /* same sign in the ranges walked */
}

static void tally(Tally *t, float x, float sgi, float host, float cr) {
	if (sgi != host) {
		if (t->host_diff == 0) t->host_first = x;
		t->host_diff++;
		if (ulp_distance(sgi, host) > 1) t->host_gt1++;
	}
	if (sgi != cr) {
		if (t->cr_diff == 0) t->cr_first = x;
		t->cr_diff++;
		if (ulp_distance(sgi, cr) > 1) t->cr_gt1++;
	}
	t->n++;
}

static void report(const char *fn, float lo, float hi, const Tally *t) {
	printf("%s [%.9g, %.9g) floats=%llu  vs_host: %llu (%.4f%%, >1ulp %llu, first x=%.9g)  vs_cr: %llu (%.4f%%, >1ulp %llu, first x=%.9g)\n",
	       fn, lo, hi, t->n, t->host_diff, 100.0 * (double)t->host_diff / (double)t->n, t->host_gt1, t->host_first,
	       t->cr_diff, 100.0 * (double)t->cr_diff / (double)t->n, t->cr_gt1, t->cr_first);
}

static void walk(float lo, float hi) {
	Tally s, c;
	uint32_t u;
	memset(&s, 0, sizeof s);
	memset(&c, 0, sizeof c);
	for (u = bits_of(lo); u < bits_of(hi); u++) {
		const float x = float_of(u);
		tally(&s, x, __sinf(x), sinf(x), (float)sin((double)x));
		tally(&c, x, __cosf(x), cosf(x), (float)cos((double)x));
	}
	report("sinf", lo, hi, &s);
	report("cosf", lo, hi, &c);
}

#if defined(_MSC_VER) && defined(TRIG_FMA3_TOGGLE)
static void walk_fma3(float lo, float hi) {
	unsigned long long n = 0, ds = 0, dc = 0;
	uint32_t u;
	for (u = bits_of(lo); u < bits_of(hi); u++) {
		const float x = float_of(u);
		float s1, c1, s0, c0;
		_set_FMA3_enable(1);
		s1 = sinf(x);
		c1 = cosf(x);
		_set_FMA3_enable(0);
		s0 = sinf(x);
		c0 = cosf(x);
		ds += (s1 != s0);
		dc += (c1 != c0);
		n++;
	}
	_set_FMA3_enable(1);
	printf("fma3 [%.9g, %.9g) floats=%llu  host sinf FMA3-on vs off: %llu  host cosf: %llu\n", lo, hi, n, ds, dc);
}
#endif

int main(int argc, char **argv) {
	static const float ranges[][2] = {
		{0.000001f, 0.5f}, {0.5f, 3.14159274f}, {3.14159274f, 6.28318548f}, {6.28318548f, 25.1327419f},
	};
	size_t i;
	__libm_qnan_f = float_of(0x7fc00000u);
	if (argc == 3) {
		const float lo = strtof(argv[1], NULL), hi = strtof(argv[2], NULL);
		if (!(lo >= 0.0f) || !(hi > lo)) {
			fprintf(stderr, "usage: %s [LO HI] with 0 <= LO < HI\n", argv[0]);
			return 2;
		}
		walk(lo, hi);
#if defined(_MSC_VER) && defined(TRIG_FMA3_TOGGLE)
		walk_fma3(lo, hi);
#endif
		return 0;
	}
	if (argc != 1) {
		fprintf(stderr, "usage: %s [LO HI] with 0 <= LO < HI\n", argv[0]);
		return 2;
	}
	for (i = 0; i < sizeof ranges / sizeof ranges[0]; i++) {
		walk(ranges[i][0], ranges[i][1]);
#if defined(_MSC_VER) && defined(TRIG_FMA3_TOGGLE)
		walk_fma3(ranges[i][0], ranges[i][1]);
#endif
	}
	return 0;
}
