/*
 * consultas.c - Respuestas a LIST, STATUS, HISTORY y EVENTS (5.9, 7.6).
 *
 * Cada consulta toma una copia de los datos con el candado de la tabla
 * (estado_*) y arma RESPONSE + ITEM despues de soltarlo, sin E/S de red.
 */
#include <stdio.h>
#include <string.h>

#include "mcd.h"

static void err404(Conexion *c, unsigned long req)
{
    char b[96];

    proto_error(b, sizeof b, req, 404, "NODO", NULL);
    conn_out(c, "%s", b);
    c->errores_formato = 0;
}

static void cabecera(Conexion *c, unsigned long req, const char *op, int items)
{
    c->errores_formato = 0;
    conn_out(c, MCD_VERSION "|RESPONSE|req=%lu|op=%s|items=%d\n", req, op, items);
}

void consulta_list(Conexion *c, unsigned long req)
{
    NodoResumen r[MAX_NODOS];
    int n = estado_listar(r);

    cabecera(c, req, "LIST", n);
    for (int i = 0; i < n; i++)
        conn_out(c, MCD_VERSION "|ITEM|req=%lu|idx=%d|node_id=%s|kind=%s|state=%s|last_seen=%ld\n",
                 req, i + 1, r[i].node_id, r[i].kind, estado_nombre(r[i].estado),
                 r[i].last_seen);
}

/* Sin telemetria valida en la sesion los campos de la muestra valen NA (4.5). */
void consulta_status(Conexion *c, unsigned long req, const char *node_id)
{
    NodoStatus s;
    const Muestra *m;
    int t;
    char seq[16] = "NA";

    if (estado_status(node_id, &s) != 0) {
        err404(c, req);
        return;
    }
    m = &s.ultima;
    t = s.hay_telemetria;
    if (t)
        snprintf(seq, sizeof seq, "%lu", m->seq);
    cabecera(c, req, "STATUS", 1);
    conn_out(c, MCD_VERSION "|ITEM|req=%lu|idx=1|node_id=%s|state=%s|last_seen=%ld|seq=%s"
             "|cpu=%s|temp=%s|bat=%s|opstate=%s|uptime=%s|lost=%lu|dups=%lu|ooo=%lu\n",
             req, s.node_id, estado_nombre(s.estado), s.last_seen, seq,
             t ? m->cpu : "NA", t ? m->temp : "NA", t ? m->bat : "NA",
             t ? m->opstate : "NA", t ? m->uptime : "NA", s.lost, s.dups, s.ooo);
}

void consulta_history(Conexion *c, unsigned long req, const char *node_id, int n)
{
    Muestra h[MAX_MUESTRAS];
    int k = estado_historial(node_id, n, h);

    if (k < 0) {
        err404(c, req);
        return;
    }
    cabecera(c, req, "HISTORY", k);
    for (int i = 0; i < k; i++)
        conn_out(c, MCD_VERSION "|ITEM|req=%lu|idx=%d|node_id=%s|seq=%lu|ts=%s|cpu=%s"
                 "|temp=%s|bat=%s|opstate=%s\n", req, i + 1, node_id, h[i].seq,
                 h[i].ts, h[i].cpu, h[i].temp, h[i].bat, h[i].opstate);
}

void consulta_events(Conexion *c, unsigned long req, int n, const char *node_id)
{
    Evento ev[MAX_EVENTOS];
    int k = estado_eventos(node_id, n, ev);

    if (k < 0) {
        err404(c, req);
        return;
    }
    cabecera(c, req, "EVENTS", k);
    for (int i = 0; i < k; i++) {
        conn_out(c, MCD_VERSION "|ITEM|req=%lu|idx=%d|node_id=%s|msg_id=%s|ts=%s|level=%s|event=%s",
                 req, i + 1, ev[i].node_id, ev[i].msg_id, ev[i].ts, ev[i].level,
                 ev[i].event);
        if (ev[i].value[0] != '\0')
            conn_out(c, "|value=%s", ev[i].value);
        conn_out(c, "\n");
    }
}
