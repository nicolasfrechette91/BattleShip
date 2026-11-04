#include "port_log.h"

#include <stdio.h>
#include <stdarg.h>
#include <string.h>

static FILE *sLogFile = NULL;
static int sFlushImportant = 0;

void port_log_set_flush_important(int on)
{
	sFlushImportant = on;
}

void port_log_init(const char *path)
{
	if (sLogFile != NULL) return;
	sLogFile = fopen(path, "w");
}

void port_log_close(void)
{
	if (sLogFile != NULL) {
		fclose(sLogFile);
		sLogFile = NULL;
	}
}

int port_log_get_fd(void)
{
	if (sLogFile == NULL) return -1;
	return fileno(sLogFile);
}

void port_log(const char *fmt, ...)
{
	if (sLogFile == NULL) return;
	va_list ap;
	va_start(ap, fmt);
	vfprintf(sLogFile, fmt, ap);
	va_end(ap);
	#if defined(BATTLESHIP_UWP)
	/* Xbox Device Portal may terminate a failed UWP process before stdio's
	 * normal-exit flush runs. Keep startup diagnostics durable so failures
	 * can be diagnosed from LocalState without attaching a debugger. */
	fflush(sLogFile);
	#endif
	/* fflush on every call costs seconds per frame on a slow drive when
	 * figatree watchdogs fire 28x per frame during a stuck APPEAR. Rely on
	 * stdio's buffer + OS-on-exit flush for normal logging; crash dumps
	 * have their own flush path. */
	if (sFlushImportant && (strncmp(fmt, "SSB64 RL", 8) == 0 || strstr(fmt, "ERROR") != NULL ||
	                        strstr(fmt, "FATAL") != NULL)) {
		fflush(sLogFile);
	}
}
