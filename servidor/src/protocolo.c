/*
 * protocolo.c - Gramatica y validacion de mensajes MCD/1.0.
 *
 * proto_parsear() cubre los pasos 2 a 4 del orden de validacion (6.1):
 * gramatica (400 FORMATO), version (400 VERSION) y tipo (400 TIPO).
 * proto_validar() cubre el paso 7: campos obligatorios, desconocidos,
 * repetidos y valores (422). Los pasos 1, 5, 6 y 8 estan en red.c y
 * manejadores.c porque dependen de la conexion y del estado.
 */
#include <stdio.h>
#include <string.h>

#include "mcd.h"

static int fallo(ErrProto *e, int code, const char *reason, const char *field)
{
    e->code = code;
    e->reason = reason;
    e->field = field;
    return code;
}

/* ---- Gramatica (4.2) ---- */

static int es_seguro(char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '.' || c == '-' ||
           c == '_' || c == ':';
}

/* tipo = 1*16( A-Z / "_" ) */
static int tipo_valido(const char *t)
{
    size_t n = strlen(t);

    if (n < 1 || n > 16)
        return 0;
    for (size_t i = 0; i < n; i++)
        if (!((t[i] >= 'A' && t[i] <= 'Z') || t[i] == '_'))
            return 0;
    return 1;
}

/* campo = clave "=" valor; clave = a-z *15(a-z / DIGIT / "_"); valor = 1*64seguro */
static int campo_valido(char *tok, Campo *dst)
{
    char *eq = strchr(tok, '=');
    size_t kl, vl;

    if (eq == NULL)
        return 0;
    kl = (size_t)(eq - tok);
    vl = strlen(eq + 1);
    if (kl < 1 || kl > 16 || vl < 1 || vl > 64)
        return 0;
    if (!(tok[0] >= 'a' && tok[0] <= 'z'))
        return 0;
    for (size_t i = 1; i < kl; i++)
        if (!((tok[i] >= 'a' && tok[i] <= 'z') ||
              (tok[i] >= '0' && tok[i] <= '9') || tok[i] == '_'))
            return 0;
    for (size_t i = 0; i < vl; i++)
        if (!es_seguro(eq[1 + i]))
            return 0;
    memcpy(dst->clave, tok, kl);
    dst->clave[kl] = '\0';
    memcpy(dst->valor, eq + 1, vl + 1);
    return 1;
}

/* Primer elemento: solo se exige que parezca una version. */
static int version_con_forma(const char *v)
{
    size_t n = strlen(v);

    if (n < 1 || n > 16)
        return 0;
    for (size_t i = 0; i < n; i++)
        if (!(es_seguro(v[i]) || v[i] == '/'))
            return 0;
    return 1;
}




int proto_parsear(const char *linea, size_t len, Msg *m, ErrProto *e)
{
    char tmp[MAX_MSG + 1];
    char *tok[MAX_CAMPOS + 2];
    int nt = 0;
    char *p;

    memset(m, 0, sizeof *m);
    if (len == 0 || len > MAX_MSG || memchr(linea, '\0', len) != NULL)
        return fallo(e, 400, "FORMATO", NULL);
    memcpy(tmp, linea, len);
    tmp[len] = '\0';

    for (p = tmp;;) {
        char *bar;
        if (nt == MAX_CAMPOS + 2)
            return fallo(e, 400, "FORMATO", NULL);   /* mas de 16 campos */
        tok[nt++] = p;
        bar = strchr(p, '|');
        if (bar == NULL)
            break;
        *bar = '\0';
        p = bar + 1;
    }
    if (nt < 2 || !tipo_valido(tok[1]))
        return fallo(e, 400, "FORMATO", NULL);
    for (int i = 2; i < nt; i++) {
        if (!campo_valido(tok[i], &m->campo[m->n]))
            return fallo(e, 400, "FORMATO", NULL);
        m->n++;
    }
    if (!version_con_forma(tok[0]))
        return fallo(e, 400, "FORMATO", NULL);
    if (strcmp(tok[0], MCD_VERSION) != 0)
        return fallo(e, 400, "VERSION", NULL);
    util_copiar(m->tipo, sizeof m->tipo, tok[1]);
    if (!proto_tipo_conocido(m->tipo))
        return fallo(e, 400, "TIPO", NULL);
    return 0;
}

const char *proto_campo(const Msg *m, const char *clave)
{
    for (int i = 0; i < m->n; i++)
        if (strcmp(m->campo[i].clave, clave) == 0)
            return m->campo[i].valor;
    return NULL;
}

/* req de la peticion, o 0 si falta o no es valido (se usa en los ERROR). */
unsigned long proto_req(const Msg *m)
{
    const char *v = proto_campo(m, "req");
    unsigned long long x;

    if (v != NULL && util_uint(v, 999999999ULL, &x) && x >= 1)
        return (unsigned long)x;
    return 0;
}

/* ERROR (5.10) con LF final. Devuelve la longitud escrita. */
int proto_error(char *buf, size_t n, unsigned long req, int code,
                const char *reason, const char *field)
{
    if (field != NULL)
        return snprintf(buf, n, MCD_VERSION "|ERROR|req=%lu|code=%d|reason=%s|field=%s\n",
                        req, code, reason, field);
    return snprintf(buf, n, MCD_VERSION "|ERROR|req=%lu|code=%d|reason=%s\n",
                    req, code, reason);
}
