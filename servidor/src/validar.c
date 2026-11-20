/*
 * validar.c - Validacion de campos (paso 7 del orden de 6.1).
 *
 * Contiene un validador por campo (4.5) y la tabla de campos de cada
 * tipo de mensaje (5.2 a 5.8). proto_validar() responde con el primer
 * fallo en el orden: obligatorios, desconocidos, repetidos, valores.
 */
#include <string.h>

#include "mcd.h"

typedef int (*Validador)(const char *v);

static int en_lista(const char *v, const char *const *lista, size_t n)
{
    for (size_t i = 0; i < n; i++)
        if (strcmp(v, lista[i]) == 0)
            return 1;
    return 0;
}

static int v_req(const char *v)
{
    unsigned long long x;
    return util_uint(v, 999999999ULL, &x) && x >= 1;
}

/* Inicial a-z; despues a-z, 0-9 y '-' (y '.' '_' si es usuario); 3 a 32. */
static int nombre_valido(const char *v, int es_usuario)
{
    size_t n = strlen(v);

    if (n < 3 || n > 32 || !(v[0] >= 'a' && v[0] <= 'z'))
        return 0;
    for (size_t i = 1; i < n; i++) {
        char c = v[i];
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')
            continue;
        if (es_usuario && (c == '.' || c == '_'))
            continue;
        return 0;
    }
    return 1;
}

static int v_node(const char *v) { return nombre_valido(v, 0); }
static int v_user(const char *v) { return nombre_valido(v, 1); }

static int v_clave(const char *v)
{
    size_t n = strlen(v);
    return n >= 8 && n <= 64;
}

static int v_kind(const char *v)
{
    static const char *const l[] = { "SENSOR", "RED", "IOT", "OTRO" };
    return en_lista(v, l, ARRAY_LEN(l));
}

static int v_period(const char *v)
{
    unsigned long long x;
    return util_uint(v, 60, &x) && x >= 1;
}

static int v_session(const char *v)
{
    if (strlen(v) != 16)
        return 0;
    for (int i = 0; i < 16; i++)
        if (!((v[i] >= '0' && v[i] <= '9') || (v[i] >= 'a' && v[i] <= 'f')))
            return 0;
    return 1;
}

static int v_seq(const char *v)
{
    unsigned long long x;
    return util_uint(v, 4294967295ULL, &x) && x >= 1;
}

static int v_ts(const char *v) { return util_uint(v, 9999999999ULL, NULL); }
static int v_uptime(const char *v) { return util_uint(v, 4294967295ULL, NULL); }
static int v_cpu(const char *v) { return util_decimal(v, 0, 0.0, 100.0); }
static int v_temp(const char *v) { return util_decimal(v, 1, -40.0, 150.0); }

static int v_bat(const char *v)
{
    return strcmp(v, "NA") == 0 || util_uint(v, 100, NULL);
}

static int v_opstate(const char *v)
{
    static const char *const l[] = { "OK", "DEGRADADO", "FALLA", "MANTENIMIENTO" };
    return en_lista(v, l, ARRAY_LEN(l));
}

/* msg_id = <arranque>-<contador>; "srv-<n>" lo genera solo el servidor. */
static int v_msgid(const char *v)
{
    size_t n = strlen(v);
    const char *g = strchr(v, '-');
    char arranque[12];
    unsigned long long c;

    if (n < 3 || n > 20 || g == NULL || strchr(g + 1, '-') != NULL)
        return 0;
    if (g == v || (size_t)(g - v) > 10)
        return 0;
    memcpy(arranque, v, (size_t)(g - v));
    arranque[g - v] = '\0';
    return util_uint(arranque, 9999999999ULL, NULL) &&
           util_uint(g + 1, 999999999ULL, &c) && c >= 1;
}

static int v_level(const char *v)
{
    static const char *const l[] = { "INFO", "ADVERTENCIA", "CRITICO" };
    return en_lista(v, l, ARRAY_LEN(l));
}

static int v_event(const char *v)
{
    static const char *const l[] = { "FALLA", "UMBRAL_TEMP", "UMBRAL_CPU",
        "BATERIA_BAJA", "CAMBIO_ESTADO", "ALARMA", "CONECTIVIDAD" };
    return en_lista(v, l, ARRAY_LEN(l));
}

static int v_value(const char *v) { return strlen(v) <= 32; }

static int v_n_hist(const char *v)
{
    unsigned long long x;
    return util_uint(v, 10, &x) && x >= 1;
}

static int v_n_ev(const char *v)
{
    unsigned long long x;
    return util_uint(v, 20, &x) && x >= 1;
}

/* ---- Campos de cada tipo (5.2 a 5.8) ---- */

typedef struct { const char *clave; Validador val; int obligatorio; } EspCampo;
typedef struct { const char *tipo; const EspCampo *campos; size_t n; } EspTipo;

#define OB 1
#define OP 0

static const EspCampo C_REGISTER[] = {
    { "req", v_req, OB }, { "node_id", v_node, OB }, { "secret", v_clave, OB },
    { "kind", v_kind, OB }, { "period", v_period, OB } };
static const EspCampo C_TELEMETRY[] = {
    { "node_id", v_node, OB }, { "session", v_session, OB }, { "seq", v_seq, OB },
    { "ts", v_ts, OB }, { "cpu", v_cpu, OB }, { "temp", v_temp, OB },
    { "bat", v_bat, OB }, { "opstate", v_opstate, OB }, { "uptime", v_uptime, OB } };
static const EspCampo C_EVENT[] = {
    { "req", v_req, OB }, { "node_id", v_node, OB }, { "msg_id", v_msgid, OB },
    { "ts", v_ts, OB }, { "level", v_level, OB }, { "event", v_event, OB },
    { "value", v_value, OP } };
static const EspCampo C_LOGIN[] = {
    { "req", v_req, OB }, { "user", v_user, OB }, { "password", v_clave, OB } };
static const EspCampo C_LIST[] = { { "req", v_req, OB } };
static const EspCampo C_STATUS[] = {
    { "req", v_req, OB }, { "node_id", v_node, OB } };
static const EspCampo C_HISTORY[] = {
    { "req", v_req, OB }, { "node_id", v_node, OB }, { "n", v_n_hist, OB } };
static const EspCampo C_EVENTS[] = {
    { "req", v_req, OB }, { "n", v_n_ev, OB }, { "node_id", v_node, OP } };
static const EspCampo C_BYE[] = { { "req", v_req, OB } };

#define TIPO(nombre, arr) { nombre, arr, ARRAY_LEN(arr) }
static const EspTipo TIPOS[] = {
    TIPO("REGISTER", C_REGISTER), TIPO("TELEMETRY", C_TELEMETRY),
    TIPO("EVENT", C_EVENT), TIPO("LOGIN", C_LOGIN), TIPO("LIST", C_LIST),
    TIPO("STATUS", C_STATUS), TIPO("HISTORY", C_HISTORY),
    TIPO("EVENTS", C_EVENTS), TIPO("BYE", C_BYE),
};

static const EspTipo *buscar_tipo(const char *t)
{
    for (size_t i = 0; i < ARRAY_LEN(TIPOS); i++)
        if (strcmp(TIPOS[i].tipo, t) == 0)
            return &TIPOS[i];
    return NULL;
}

/* Tipos que el servidor acepta como peticion; el resto es 400 TIPO (paso 4). */
int proto_tipo_conocido(const char *t)
{
    return buscar_tipo(t) != NULL;
}

static const EspCampo *buscar_campo(const EspTipo *t, const char *clave)
{
    for (size_t i = 0; i < t->n; i++)
        if (strcmp(t->campos[i].clave, clave) == 0)
            return &t->campos[i];
    return NULL;
}

static int fallo(ErrProto *e, int code, const char *reason, const char *field)
{
    e->code = code;
    e->reason = reason;
    e->field = field;
    return code;
}

/* Devuelve 0 si el mensaje es correcto o el codigo (422) con e rellenado. */
int proto_validar(const Msg *m, ErrProto *e)
{
    const EspTipo *t = buscar_tipo(m->tipo);

    if (t == NULL)
        return fallo(e, 400, "TIPO", NULL);
    for (size_t k = 0; k < t->n; k++)
        if (t->campos[k].obligatorio && proto_campo(m, t->campos[k].clave) == NULL)
            return fallo(e, 422, "FALTA_CAMPO", t->campos[k].clave);
    for (int i = 0; i < m->n; i++)
        if (buscar_campo(t, m->campo[i].clave) == NULL)
            return fallo(e, 422, "CAMPO_DESCONOCIDO", m->campo[i].clave);
    for (int i = 0; i < m->n; i++)
        for (int j = 0; j < i; j++)
            if (strcmp(m->campo[i].clave, m->campo[j].clave) == 0)
                return fallo(e, 422, "CAMPO_REPETIDO", m->campo[i].clave);
    for (int i = 0; i < m->n; i++) {
        const EspCampo *c = buscar_campo(t, m->campo[i].clave);
        if (!c->val(m->campo[i].valor))
            return fallo(e, 422, "VALOR", c->clave);
    }
    return 0;
}
