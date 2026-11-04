/*
 * transn_cos_check.c -- the D1 trig difference on the one Mario path that reaches host cosf.
 *
 * ftPhysicsGetAirVelTransN (decomp/src/ft/ftphysics.c:430) calls bare cosf() on the TransN joint's z rotation.
 * Mario's Super Jump Punch physics (ftmariospecialhi.c:75,81) goes through it, and ftMarioSpecialHiProcInterrupt
 * (ftmariospecialhi.c:20-46) sets that rotation from the stick:
 *     rot_z = -F_CLC_DTOR32((stick_x - (+-50)) * 0.6F)   for |stick_x| > 50
 * On MSVC the bare cosf is ucrt (the decomp's #pragma weak cosf = __cosf is ignored); on GCC/Clang and the N64 it is
 * libultra __cosf. This prints both for every rotation the stick can produce (|stick_x| 51..80, plus 0), and for any
 * extra float given on the command line (decimal, or 0x-prefixed IEEE bits), so the ucrt column can be read on the
 * exact inputs instead of a range.
 *
 * Build (x64 Native Tools Command Prompt for VS, repository root), same flags as MORNING_RUNBOOK B1:
 *   mkdir build-glitch
 *   cl /nologo /O2 /fp:precise /c /D_LANGUAGE_C /DF3DEX_GBI_2=1 /DPORT=1 /DNON_MATCHING=1 /DNON_EQUIVALENT=1 /DAVOID_UB=1
 *      /Idecomp\include /Idecomp\src /Fobuild-glitch\ decomp\src\libultra\gu\cosf.c
 *   cl /nologo /O2 /fp:precise /Fobuild-glitch\ /Febuild-glitch\transn_cos_check.exe tools\glitch\transn_cos_check.c
 *      build-glitch\cosf.obj
 *   build-glitch\transn_cos_check.exe
 * GCC/Clang (Linux, WSL): strip the weak alias first, or the "host" column is libultra itself:
 *   cc -O2 -ffp-contract=off -fno-strict-aliasing -fno-builtin -D_LANGUAGE_C -DF3DEX_GBI_2=1 -DPORT=1 -DNON_MATCHING=1 \
 *      -DNON_EQUIVALENT=1 -DAVOID_UB=1 -Idecomp/include -Idecomp/src -c decomp/src/libultra/gu/cosf.c -o build-glitch/cosf.o
 *   objcopy -N cosf -N fcos build-glitch/cosf.o
 *   cc -O2 -ffp-contract=off -fno-builtin tools/glitch/transn_cos_check.c build-glitch/cosf.o -lm -o build-glitch/transn_cos_check
 *
 * Output: one line per input: stick, x (bits), libultra (bits), host (bits), ulp difference. The last line counts the
 * inputs where they differ. Any difference on the |stick_x| = 80 rows is a Windows-vs-N64 trajectory difference for an
 * agent restricted to the 8 directions; rows 51..79 matter only for analog inputs.
 */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

float __cosf(float);
float __libm_qnan_f; /* libultra's NaN branch reads it; the port defines it in port/stubs/libc_compat.c */

#define PI32 3.1415927F                                  /* decomp/include/macros.h */
#define F_CLC_DTOR32(x) ((float)(((x) * PI32) / 180.0F)) /* decomp/include/macros.h */
#define TURN_THRESHOLD 50                                /* FTMARIO_SUPERJUMP_TURN_STICK_THRESHOLD */
#define AIR_DRIFT 0.6F                                   /* FTMARIO_SUPERJUMP_AIR_DRIFT */

static uint32_t bits_of(float f)
{
	uint32_t u;
	memcpy(&u, &f, sizeof u);
	return u;
}

static float float_of(uint32_t u)
{
	float f;
	memcpy(&f, &u, sizeof f);
	return f;
}

static long ulp_diff(float a, float b)
{
	int32_t ia = (int32_t)bits_of(a), ib = (int32_t)bits_of(b);
	if (ia < 0) ia = (int32_t)0x80000000 - ia;
	if (ib < 0) ib = (int32_t)0x80000000 - ib;
	return labs((long)ia - (long)ib);
}

static int row(const char *label, float x)
{
	volatile float vx = x;
	float lu = __cosf(vx);
	float host = cosf(vx);
	long d = ulp_diff(lu, host);
	printf("%-10s x=%.9g (0x%08x)  libultra=%.9g (0x%08x)  host=%.9g (0x%08x)  ulp=%ld\n", label, (double)x, bits_of(x),
	       (double)lu, bits_of(lu), (double)host, bits_of(host), d);
	return d != 0;
}

int main(int argc, char **argv)
{
	int differ = 0, total = 0, differ80 = 0;
	char label[32];
	int stick;
	int i;

	__libm_qnan_f = float_of(0x7fc00000u);
#if defined(_MSC_VER)
	printf("host: MSVC %d (ucrt cosf)\n", _MSC_VER);
#else
	printf("host: not MSVC (check that objcopy stripped the weak alias)\n");
#endif
	differ += row("stick 0", 0.0F);
	total++;
	for (stick = -80; stick <= 80; stick++)
	{
		int thr = (stick > 0) ? TURN_THRESHOLD : -TURN_THRESHOLD;
		float rot;
		int d;
		if (stick >= -TURN_THRESHOLD && stick <= TURN_THRESHOLD)
		{
			continue;
		}
		rot = (stick - thr) * AIR_DRIFT;
		snprintf(label, sizeof label, "stick %d", stick);
		d = row(label, -F_CLC_DTOR32(rot));
		differ += d;
		total++;
		if (stick == 80 || stick == -80)
		{
			differ80 += d;
		}
	}
	for (i = 1; i < argc; i++)
	{
		float x = (strncmp(argv[i], "0x", 2) == 0) ? float_of((uint32_t)strtoul(argv[i], NULL, 16)) : strtof(argv[i], NULL);
		differ += row("argv", x);
		total++;
	}
	printf("differ: %d of %d inputs; on the 8-direction inputs (|stick_x| = 80): %d of 2\n", differ, total, differ80);
	return 0;
}
