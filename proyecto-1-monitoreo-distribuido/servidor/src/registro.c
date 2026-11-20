/*
 * registro.c - Logging (seccion 11): consola y archivo, con marca de
 * tiempo UTC, canal, IP:puerto y direccion. Los valores de secret y
 * password se enmascaran siempre y los bytes no imprimibles se escapan.
 *
 * El candado del log es una hoja del orden de candados: se toma el de la
 * tabla antes que este, nunca al reves.
 */
#include <ctype.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

#include "mcd.h"

#define LOG_MAX_MSG 1000   /* bytes de mensaje que se escriben como maximo */

static pthread_mutex_t mtx_log = PTHREAD_MUTEX_INITIALIZER;
static FILE *f_log;

int registro_init(const char *ruta)
{
    f_log = fopen(ruta, "a");
    return f_log != NULL ? 0 : -1;
}

/* Si s empieza por una clave cuyo valor es secreto, devuelve su longitud. */
static size_t clave_secreta(const char *s, size_t n)
{
    static const char *const claves[] = { "secret=", "password=" };

    for (size_t k = 0; k < ARRAY_LEN(claves); k++) {
        size_t l = strlen(claves[k]);
        if (n >= l && strncasecmp(s, claves[k], l) == 0)
            return l;
    }
    return 0;
}

/*
 * Copia s[0..n) a d enmascarando los valores secretos (hasta el siguiente
 * '|' o el fin) y escapando como \xNN lo que no es ASCII imprimible.
 * cap debe ser >= 4*n + 16.
 */
static size_t sanear(const char *s, size_t n, char *d, size_t cap)
{
    static const char hex[] = "0123456789abcdef";
    size_t o = 0;

    for (size_t i = 0; i < n && o + 5 < cap;) {
        size_t kl = clave_secreta(s + i, n - i);
        if (kl > 0) {
            memcpy(d + o, s + i, kl);
            memcpy(d + o + kl, "***", 3);
            o += kl + 3;
            i += kl;
            while (i < n && s[i] != '|')
                i++;
            continue;
        }
        unsigned char ch = (unsigned char)s[i++];
        if (ch >= 0x20 && ch <= 0x7e) {
            d[o++] = (char)ch;
        } else {
            d[o++] = '\\';
            d[o++] = 'x';
            d[o++] = hex[ch >> 4];
            d[o++] = hex[ch & 0x0f];
        }
    }
    d[o] = '\0';
    return o;
}

void registro(const char *canal, const char *peer, const char *dir,
              const char *msg, size_t n)
{
    char ts[32], texto[4 * LOG_MAX_MSG + 64], extra[32] = "";

    util_ahora_iso(ts, sizeof ts);
    if (n > LOG_MAX_MSG) {
        snprintf(extra, sizeof extra, "...(%zu bytes)", n);
        n = LOG_MAX_MSG;
    }
    sanear(msg, n, texto, sizeof texto);

    pthread_mutex_lock(&mtx_log);
    printf("%s %s %s %s %s%s\n", ts, canal, peer, dir, texto, extra);
    fflush(stdout);
    if (f_log != NULL) {
        fprintf(f_log, "%s %s %s %s %s%s\n", ts, canal, peer, dir, texto, extra);
        fflush(f_log);
    }
    pthread_mutex_unlock(&mtx_log);
}

/* Nota interna ("--") asociada a un canal y un origen. */
void registro_nota(const char *canal, const char *peer, const char *fmt, ...)
{
    char buf[512];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    registro(canal, peer, "--", buf, strlen(buf));
}

/* Evento interno del servidor: canal SYS, sin origen. */
void registro_sys(const char *fmt, ...)
{
    char buf[512];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    registro("SYS", "-", "--", buf, strlen(buf));
}
