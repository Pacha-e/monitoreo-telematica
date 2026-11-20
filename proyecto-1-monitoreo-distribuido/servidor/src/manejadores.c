/*
 * manejadores.c - Logica del protocolo por tipo de mensaje.
 *
 * manejar_linea_tcp() aplica el orden de validacion de 6.1 a cada linea
 * TCP y despacha al manejador del tipo; la respuesta queda en c->out y
 * red.c la envia. manejar_udp() procesa un datagrama de TELEMETRY.
 * Las consultas (LIST, STATUS, HISTORY, EVENTS) estan en consultas.c.
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mcd.h"

/* Agrega texto (con su LF) a la respuesta pendiente de la conexion. */
void conn_out(Conexion *c, const char *fmt, ...)
{
    va_list ap;
    size_t libre = OUT_MAX - c->out_len;
    int n;

    va_start(ap, fmt);
    n = vsnprintf(c->out + c->out_len, libre, fmt, ap);
    va_end(ap);
    if (n < 0 || (size_t)n >= libre) {   /* no cabe: se descarta la linea */
        c->out[c->out_len] = '\0';
        c->cerrar = 1;
        return;
    }
    c->out_len += (size_t)n;
}

/*
 * Responde un ERROR. Los errores 400 y 422 seguidos se cuentan y al
 * quinto se cierra la conexion (6); cualquier otra respuesta reinicia la cuenta.
 */
static void err(Conexion *c, unsigned long req, int code, const char *reason,
                const char *field)
{
    char b[160];

    proto_error(b, sizeof b, req, code, reason, field);
    conn_out(c, "%s", b);
    if (code == 400 || code == 422) {
        if (++c->errores_formato >= MAX_ERRORES_FORMATO)
            c->cerrar = 1;
    } else {
        c->errores_formato = 0;
    }
}

/* ---- Manejadores de cada tipo ---- */

static void h_register(Conexion *c, const Msg *m, unsigned long req)
{
    const char *node = proto_campo(m, "node_id");
    const char *period = proto_campo(m, "period");
    char sesion[17];
    unsigned long anterior = 0;
    AuthRes r = auth_nodo(node, proto_campo(m, "secret"));
    int rc;

    if (r == AUTH_CRED) {
        err(c, req, 401, "CREDENCIALES", NULL);
        c->cerrar = 1;
        return;
    }
    if (r != AUTH_OK) {
        err(c, req, 503, r == AUTH_DNS ? "DNS" : "LDAP", NULL);
        return;
    }
    rc = estado_registrar(node, proto_campo(m, "kind"), atoi(period), c->id,
                          sesion, &anterior);
    if (rc != 0) {
        if (rc == -1)
            err(c, req, 503, "CAPACIDAD", NULL);
        else
            err(c, req, 500, "INTERNO", NULL);
        c->cerrar = 1;
        return;
    }
    c->tipo = C_NODO;
    util_copiar(c->node_id, sizeof c->node_id, node);
    if (anterior != 0)
        red_cerrar_conexion(anterior);   /* 7.2 paso 4 */
    c->errores_formato = 0;
    conn_out(c, MCD_VERSION "|REGISTER_OK|req=%lu|node_id=%s|session=%s|period=%s\n",
             req, node, sesion, period);
}

static void h_login(Conexion *c, const Msg *m, unsigned long req)
{
    const char *user = proto_campo(m, "user");
    int admin = 0;
    AuthRes r = auth_usuario(user, proto_campo(m, "password"), &admin);

    if (r == AUTH_OK) {
        c->tipo = C_ADMIN;
        c->es_admin = admin;
        util_copiar(c->user, sizeof c->user, user);
        c->errores_formato = 0;
        conn_out(c, MCD_VERSION "|LOGIN_OK|req=%lu|user=%s|role=%s\n", req, user,
                 admin ? "admin" : "operador");
    } else if (r == AUTH_CRED || r == AUTH_ROL) {
        if (r == AUTH_CRED)
            err(c, req, 401, "CREDENCIALES", NULL);
        else
            err(c, req, 403, "ROL", NULL);
        if (++c->fallos_login >= MAX_LOGIN_FALLOS)
            c->cerrar = 1;               /* tercer intento fallido */
        else
            c->t_ident = util_mono();    /* T_ident se reinicia */
    } else {
        err(c, req, 503, r == AUTH_DNS ? "DNS" : "LDAP", NULL);
    }
}

static void h_event(Conexion *c, const Msg *m, unsigned long req)
{
    Evento ev;
    const char *v;
    int dup;

    if (strcmp(proto_campo(m, "node_id"), c->node_id) != 0) {
        err(c, req, 403, "NODO_AJENO", NULL);
        return;
    }
    memset(&ev, 0, sizeof ev);
    util_copiar(ev.node_id, sizeof ev.node_id, c->node_id);
    util_copiar(ev.msg_id, sizeof ev.msg_id, proto_campo(m, "msg_id"));
    util_copiar(ev.ts, sizeof ev.ts, proto_campo(m, "ts"));
    util_copiar(ev.level, sizeof ev.level, proto_campo(m, "level"));
    util_copiar(ev.event, sizeof ev.event, proto_campo(m, "event"));
    if ((v = proto_campo(m, "value")) != NULL)
        util_copiar(ev.value, sizeof ev.value, v);

    dup = estado_guardar_evento(c->node_id, &ev);
    if (dup < 0) {
        err(c, req, 404, "NODO", NULL);
        return;
    }
    /* El ACK sale despues de guardar el evento y de anotarlo en el log (7.4). */
    registro_nota("TCP", c->peer, dup ? "evento repetido node_id=%s msg_id=%s (no se guarda)"
                                      : "evento guardado node_id=%s msg_id=%s",
                  c->node_id, ev.msg_id);
    c->errores_formato = 0;
    conn_out(c, MCD_VERSION "|ACK|req=%lu|node_id=%s|msg_id=%s|dup=%d\n", req,
             c->node_id, ev.msg_id, dup);
}

static void h_bye(Conexion *c, unsigned long req)
{
    if (c->tipo == C_NODO)
        estado_desconectar(c->node_id, c->id);
    c->errores_formato = 0;
    conn_out(c, MCD_VERSION "|BYE|req=%lu\n", req);
    c->cerrar = 1;
}

/*
 * Paso 6 del orden de validacion: estado de la conexion y perfil.
 * Devuelve 1 si el mensaje puede seguir; 0 si ya se respondio el error.
 */
static int comprobar_estado(Conexion *c, const Msg *m, unsigned long req)
{
    const char *t = m->tipo;
    int es_ident = strcmp(t, "REGISTER") == 0 || strcmp(t, "LOGIN") == 0;

    if (strcmp(t, "BYE") == 0)
        return 1;
    if (c->tipo == C_NUEVA) {
        if (es_ident)
            return 1;
        err(c, req, 401, "SIN_SESION", NULL);
        return 0;
    }
    if (es_ident) {
        err(c, req, 409, "ESTADO", NULL);
        return 0;
    }
    if (c->tipo == C_NODO) {
        if (strcmp(t, "EVENT") == 0)
            return 1;
        err(c, req, 403, "ROL", NULL);
        return 0;
    }
    /* sesion de administracion: EVENT no; EVENTS solo el perfil admin */
    if (strcmp(t, "EVENT") == 0 || (strcmp(t, "EVENTS") == 0 && !c->es_admin)) {
        err(c, req, 403, "ROL", NULL);
        return 0;
    }
    return 1;
}

static void despachar(Conexion *c, const Msg *m, unsigned long req)
{
    const char *t = m->tipo;
    const char *nodo = proto_campo(m, "node_id");

    if (strcmp(t, "REGISTER") == 0)
        h_register(c, m, req);
    else if (strcmp(t, "LOGIN") == 0)
        h_login(c, m, req);
    else if (strcmp(t, "EVENT") == 0)
        h_event(c, m, req);
    else if (strcmp(t, "BYE") == 0)
        h_bye(c, req);
    else if (strcmp(t, "LIST") == 0)
        consulta_list(c, req);
    else if (strcmp(t, "STATUS") == 0)
        consulta_status(c, req, nodo);
    else if (strcmp(t, "HISTORY") == 0)
        consulta_history(c, req, nodo, atoi(proto_campo(m, "n")));
    else if (strcmp(t, "EVENTS") == 0)
        consulta_events(c, req, atoi(proto_campo(m, "n")), nodo);
}

/* Procesa una linea TCP (sin LF ni CR) siguiendo el orden de 6.1. */
void manejar_linea_tcp(Conexion *c, const char *linea, size_t len)
{
    Msg m;
    ErrProto e;
    unsigned long req;

    registro("TCP", c->peer, "<-", linea, len);
    /* pasos 2 a 4: gramatica, version y tipo (req=0: aun no se lee) */
    if (proto_parsear(linea, len, &m, &e) != 0) {
        err(c, 0, e.code, e.reason, e.field);
        return;
    }
    req = proto_req(&m);
    if (strcmp(m.tipo, "TELEMETRY") == 0) {          /* paso 5 */
        err(c, 0, 409, "TRANSPORTE", NULL);
        return;
    }
    if (!comprobar_estado(c, &m, req))                /* paso 6 */
        return;
    if (proto_validar(&m, &e) != 0) {                 /* paso 7 */
        err(c, req, e.code, e.reason, e.field);
        return;
    }
    despachar(c, &m, req);                            /* paso 8 */
}

/* ---- TELEMETRY por UDP (4.4, 7.3) ---- */

static void descartar(const char *peer, const char *motivo, const char *detalle)
{
    registro_nota("UDP", peer, "descartado: %s%s%s", motivo,
                  detalle != NULL ? " " : "", detalle != NULL ? detalle : "");
}

static void llenar_telemetria(const Msg *m, Telemetria *t)
{
    memset(t, 0, sizeof *t);
    util_copiar(t->node_id, sizeof t->node_id, proto_campo(m, "node_id"));
    util_copiar(t->session, sizeof t->session, proto_campo(m, "session"));
    t->m.seq = strtoul(proto_campo(m, "seq"), NULL, 10);
    util_copiar(t->m.ts, sizeof t->m.ts, proto_campo(m, "ts"));
    util_copiar(t->m.cpu, sizeof t->m.cpu, proto_campo(m, "cpu"));
    util_copiar(t->m.temp, sizeof t->m.temp, proto_campo(m, "temp"));
    util_copiar(t->m.bat, sizeof t->m.bat, proto_campo(m, "bat"));
    util_copiar(t->m.opstate, sizeof t->m.opstate, proto_campo(m, "opstate"));
    util_copiar(t->m.uptime, sizeof t->m.uptime, proto_campo(m, "uptime"));
}

/*
 * Procesa un datagrama. Devuelve la longitud del ERROR 404 que hay que
 * enviar al origen (en resp), o 0 si no se responde nada. El limite de un
 * ERROR cada 5 s por origen lo aplica red.c.
 */
int manejar_udp(const char *dat, size_t len, const char *peer, char *resp, size_t cap)
{
    Msg m;
    ErrProto e;
    Telemetria t;
    int tiene_lf = len > 0 && dat[len - 1] == '\n';
    char detalle[48];

    registro("UDP", peer, "<-", dat, tiene_lf ? len - 1 : len);
    if (len > MAX_MSG) {
        descartar(peer, "mas de 512 bytes", NULL);
        return 0;
    }
    if (!tiene_lf || memchr(dat, '\n', len) != dat + len - 1) {
        descartar(peer, "no es exactamente un mensaje terminado en LF", NULL);
        return 0;
    }
    if (proto_parsear(dat, len - 1, &m, &e) != 0) {
        snprintf(detalle, sizeof detalle, "%d %s", e.code, e.reason);
        descartar(peer, "mensaje invalido", detalle);
        return 0;
    }
    if (strcmp(m.tipo, "TELEMETRY") != 0) {
        descartar(peer, "tipo no permitido por UDP", m.tipo);
        return 0;
    }
    if (proto_validar(&m, &e) != 0) {
        snprintf(detalle, sizeof detalle, "%s campo=%s", e.reason, e.field);
        descartar(peer, "telemetria invalida", detalle);
        return 0;
    }
    llenar_telemetria(&m, &t);
    switch (estado_telemetria(&t)) {
    case TEL_NODO_DESCONOCIDO:
        return proto_error(resp, cap, 0, 404, "NODO", NULL);
    case TEL_SESION_INVALIDA:
        return proto_error(resp, cap, 0, 404, "SESION", NULL);
    case TEL_DUPLICADA:
        snprintf(detalle, sizeof detalle, "%s seq=%lu", t.node_id, t.m.seq);
        descartar(peer, "telemetria duplicada", detalle);
        break;
    case TEL_ATRASADA:
        snprintf(detalle, sizeof detalle, "%s seq=%lu", t.node_id, t.m.seq);
        descartar(peer, "telemetria atrasada", detalle);
        break;
    default:
        break;
    }
    return 0;
}
