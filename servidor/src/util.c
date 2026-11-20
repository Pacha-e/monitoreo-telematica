/*
 * util.c - Utilidades pequenas: configuracion por entorno, tiempo,
 * conversion de enteros/decimales y aleatorios.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mcd.h"

Config cfg;

/* Lee un entero de la variable de entorno; si falta o no es valido usa def. */
static long env_entero(const char *nombre, long def, long min, long max)
{
    const char *v = getenv(nombre);
    char *fin;
    long x;

    if (v == NULL || *v == '\0')
        return def;
    errno = 0;
    x = strtol(v, &fin, 10);
    if (errno != 0 || *fin != '\0' || x < min || x > max) {
        fprintf(stderr, "aviso: %s=%s no es valido, se usa %ld\n", nombre, v, def);
        return def;
    }
    return x;
}

static void env_texto(const char *nombre, const char *def, char *dst, size_t n)
{
    const char *v = getenv(nombre);

    util_copiar(dst, n, (v != NULL && *v != '\0') ? v : def);
}

/* Valores por defecto de la especificacion (secciones 8 y 12). */
void config_cargar(void)
{
    env_texto("MCD_LDAP_HOST", "ldap.monitoreo.lab", cfg.ldap_host, sizeof cfg.ldap_host);
    env_texto("MCD_LDAP_BASE", "dc=monitoreo,dc=lab", cfg.ldap_base, sizeof cfg.ldap_base);
    cfg.ldap_port    = (int)env_entero("MCD_LDAP_PORT", 389, 1, 65535);
    cfg.ldap_timeout = (int)env_entero("MCD_LDAP_TIMEOUT", 3, 1, 60);
    cfg.t_ident      = (double)env_entero("MCD_T_IDENT", 60, 1, 86400);
    cfg.t_inact      = (double)env_entero("MCD_T_INACTIVIDAD", 300, 1, 86400);
}

void util_ahora_iso(char *buf, size_t n)
{
    time_t t = time(NULL);
    struct tm tm;

    gmtime_r(&t, &tm);
    strftime(buf, n, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

/* Reloj monotonico en segundos: no se ve afectado por cambios de hora. */
double util_mono(void)
{
    struct timespec ts;

    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

void util_copiar(char *dst, size_t n, const char *src)
{
    size_t l = strlen(src);

    if (n == 0)
        return;
    if (l >= n)
        l = n - 1;
    memcpy(dst, src, l);
    dst[l] = '\0';
}

/*
 * Entero decimal sin signo: 1 a 10 digitos, sin ceros a la izquierda
 * (salvo el propio 0) y <= max. Devuelve 1 si es valido.
 */
int util_uint(const char *v, unsigned long long max, unsigned long long *out)
{
    size_t n = strlen(v);
    unsigned long long x = 0;

    if (n == 0 || n > 10 || (n > 1 && v[0] == '0'))
        return 0;
    for (size_t i = 0; i < n; i++) {
        if (v[i] < '0' || v[i] > '9')
            return 0;
        x = x * 10 + (unsigned long long)(v[i] - '0');
    }
    if (x > max)
        return 0;
    if (out != NULL)
        *out = x;
    return 1;
}

/*
 * Decimal con un decimal opcional y, si con_signo, signo '-' opcional:
 * "[-]D{1,3}[.D]" de 1 a 5 caracteres, dentro de [min, max].
 */
int util_decimal(const char *v, int con_signo, double min, double max)
{
    size_t n = strlen(v), i = 0;
    int neg = 0, digitos = 0;
    double x = 0;

    if (n == 0 || n > 5)
        return 0;
    if (con_signo && v[0] == '-') {
        neg = 1;
        i = 1;
    }
    for (; i < n && v[i] >= '0' && v[i] <= '9'; i++, digitos++)
        x = x * 10 + (v[i] - '0');
    if (digitos < 1 || digitos > 3)
        return 0;
    if (i < n) {
        if (v[i] != '.' || i + 2 != n || v[i + 1] < '0' || v[i + 1] > '9')
            return 0;
        x += (v[i + 1] - '0') / 10.0;
    }
    if (neg)
        x = -x;
    return x >= min && x <= max;
}

/* nbytes (<= 16) aleatorios de /dev/urandom, en hexadecimal minuscula. */
int util_hex_aleatorio(char *out, size_t nbytes)
{
    static const char hex[] = "0123456789abcdef";
    unsigned char b[16];
    FILE *f;

    if (nbytes > sizeof b)
        return -1;
    f = fopen("/dev/urandom", "rb");
    if (f == NULL)
        return -1;
    if (fread(b, 1, nbytes, f) != nbytes) {
        fclose(f);
        return -1;
    }
    fclose(f);
    for (size_t i = 0; i < nbytes; i++) {
        out[2 * i]     = hex[b[i] >> 4];
        out[2 * i + 1] = hex[b[i] & 0x0f];
    }
    out[2 * nbytes] = '\0';
    return 0;
}
