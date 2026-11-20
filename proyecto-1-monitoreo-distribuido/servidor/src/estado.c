/*
 * estado.c - Tabla de nodos, historiales y eventos (secciones 3.3, 7.2 a 7.8).
 *
 * Un unico mutex (mtx_tabla) protege la tabla de nodos, los historiales
 * por nodo, los msg_id recordados, la lista global de eventos y el
 * contador de eventos internos. Orden de candados: tabla -> log.
 * Nunca se hace E/S de red ni LDAP con este candado tomado.
 */
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mcd.h"

typedef struct {
    int           usado;
    char          node_id[33];
    char          kind[8];
    int           period;
    EstadoNodo    estado;
    char          session[17];       /* vacio = sesion invalida */
    unsigned long conn_id;           /* conexion TCP vigente, 0 si ninguna */
    unsigned long last_seq;
    int           hay_telemetria;    /* en la sesion actual */
    long          last_seen;
    unsigned long lost, dups, ooo;
    Muestra       hist[MAX_MUESTRAS];
    int           hist_n, hist_pos;  /* buffer circular */
    char          msgids[MAX_MSGID][24];
    int           msgid_n, msgid_pos;
} Nodo;

static pthread_mutex_t mtx_tabla = PTHREAD_MUTEX_INITIALIZER;
static Nodo    nodos[MAX_NODOS];
static Evento  eventos[MAX_EVENTOS];
static int     ev_n, ev_pos;         /* buffer circular de eventos */
static unsigned long srv_seq;        /* contador de msg_id=srv-<n> */

const char *estado_nombre(EstadoNodo e)
{
    switch (e) {
    case NODO_ACTIVO:       return "ACTIVO";
    case NODO_SIN_REPORTE:  return "SIN_REPORTE";
    default:                return "DESCONECTADO";
    }
}

void estado_init(void)
{
    pthread_mutex_lock(&mtx_tabla);
    memset(nodos, 0, sizeof nodos);
    ev_n = ev_pos = 0;
    srv_seq = 0;
    pthread_mutex_unlock(&mtx_tabla);
}

/* Todas las funciones static de abajo suponen mtx_tabla tomado. */

static Nodo *buscar(const char *node_id)
{
    for (int i = 0; i < MAX_NODOS; i++)
        if (nodos[i].usado && strcmp(nodos[i].node_id, node_id) == 0)
            return &nodos[i];
    return NULL;
}

static void guardar_evento(const Evento *ev)
{
    eventos[ev_pos] = *ev;
    ev_pos = (ev_pos + 1) % MAX_EVENTOS;
    if (ev_n < MAX_EVENTOS)
        ev_n++;
}

/* Evento interno CONECTIVIDAD (7.3 y 7.8) con msg_id=srv-<n>. */
static void evento_interno(Nodo *n, const char *level, const char *value,
                           EstadoNodo anterior)
{
    Evento ev;

    memset(&ev, 0, sizeof ev);
    util_copiar(ev.node_id, sizeof ev.node_id, n->node_id);
    snprintf(ev.msg_id, sizeof ev.msg_id, "srv-%lu", ++srv_seq);
    snprintf(ev.ts, sizeof ev.ts, "%ld", (long)time(NULL));
    util_copiar(ev.level, sizeof ev.level, level);
    util_copiar(ev.event, sizeof ev.event, "CONECTIVIDAD");
    util_copiar(ev.value, sizeof ev.value, value);
    guardar_evento(&ev);
    registro_sys("%s estado=%s anterior=%s msg_id=%s", n->node_id,
                 estado_nombre(n->estado), estado_nombre(anterior), ev.msg_id);
}

static void agregar_muestra(Nodo *n, const Muestra *m)
{
    n->hist[n->hist_pos] = *m;
    n->hist_pos = (n->hist_pos + 1) % MAX_MUESTRAS;
    if (n->hist_n < MAX_MUESTRAS)
        n->hist_n++;
}

/* i = 0 es la muestra mas reciente. */
static const Muestra *muestra_reciente(const Nodo *n, int i)
{
    return &n->hist[(n->hist_pos - 1 - i + 2 * MAX_MUESTRAS) % MAX_MUESTRAS];
}

/* ---- Registro, desconexion, watchdog ---- */

/*
 * 7.2: crea o reutiliza la entrada, genera sesion nueva y deja el nodo
 * ACTIVO. Devuelve 0, -1 si la tabla esta llena (503 CAPACIDAD) o -2 si
 * no hay aleatorios (500 INTERNO). conn_anterior recibe la conexion que
 * dejo de ser la vigente (0 si no habia).
 */
int estado_registrar(const char *node_id, const char *kind, int period,
                     unsigned long conn_id, char session[17],
                     unsigned long *conn_anterior)
{
    char nueva[17];
    Nodo *n;
    EstadoNodo anterior = NODO_DESCONECTADO;

    if (util_hex_aleatorio(nueva, 8) != 0)
        return -2;
    pthread_mutex_lock(&mtx_tabla);
    n = buscar(node_id);
    if (n == NULL) {
        for (int i = 0; i < MAX_NODOS && n == NULL; i++)
            if (!nodos[i].usado)
                n = &nodos[i];
        if (n == NULL) {
            pthread_mutex_unlock(&mtx_tabla);
            return -1;
        }
        memset(n, 0, sizeof *n);
        n->usado = 1;
        util_copiar(n->node_id, sizeof n->node_id, node_id);
        n->estado = NODO_DESCONECTADO;
    }
    anterior = n->estado;
    *conn_anterior = n->conn_id;
    util_copiar(n->kind, sizeof n->kind, kind);
    n->period = period;
    n->estado = NODO_ACTIVO;
    memcpy(n->session, nueva, sizeof nueva);
    memcpy(session, nueva, sizeof nueva);
    n->conn_id = conn_id;
    n->last_seq = 0;
    n->hay_telemetria = 0;
    n->last_seen = (long)time(NULL);
    n->lost = n->dups = n->ooo = 0;
    registro_sys("%s estado=ACTIVO anterior=%s (registro)", n->node_id,
                 estado_nombre(anterior));
    pthread_mutex_unlock(&mtx_tabla);
    return 0;
}

/* 7.7: solo si conn_id sigue siendo la conexion vigente del nodo. */
void estado_desconectar(const char *node_id, unsigned long conn_id)
{
    Nodo *n;

    pthread_mutex_lock(&mtx_tabla);
    n = buscar(node_id);
    if (n != NULL && n->conn_id == conn_id) {
        EstadoNodo anterior = n->estado;
        n->estado = NODO_DESCONECTADO;
        n->session[0] = '\0';
        n->conn_id = 0;
        registro_sys("%s estado=DESCONECTADO anterior=%s", n->node_id,
                     estado_nombre(anterior));
    }
    pthread_mutex_unlock(&mtx_tabla);
}

/* 7.8: mas de 3 periodos sin telemetria aceptada (reloj del servidor). */
void estado_watchdog(time_t ahora)
{
    pthread_mutex_lock(&mtx_tabla);
    for (int i = 0; i < MAX_NODOS; i++) {
        Nodo *n = &nodos[i];
        if (n->usado && n->estado == NODO_ACTIVO &&
            (long)ahora - n->last_seen > 3L * n->period) {
            n->estado = NODO_SIN_REPORTE;
            evento_interno(n, "ADVERTENCIA", "SIN_REPORTE", NODO_ACTIVO);
        }
    }
    pthread_mutex_unlock(&mtx_tabla);
}

/* ---- Telemetria y eventos ---- */

/* 7.3: sesion, duplicados, atrasados y perdidas. */
TelRes estado_telemetria(const Telemetria *t)
{
    TelRes r = TEL_OK;
    Nodo *n;

    pthread_mutex_lock(&mtx_tabla);
    n = buscar(t->node_id);
    if (n == NULL) {
        r = TEL_NODO_DESCONOCIDO;
    } else if (n->session[0] == '\0' || strcmp(n->session, t->session) != 0) {
        r = TEL_SESION_INVALIDA;
    } else if (t->m.seq == n->last_seq) {
        n->dups++;
        r = TEL_DUPLICADA;
    } else if (t->m.seq < n->last_seq) {
        n->ooo++;
        r = TEL_ATRASADA;
    } else {
        if (t->m.seq > n->last_seq + 1)
            n->lost += t->m.seq - n->last_seq - 1;
        agregar_muestra(n, &t->m);
        n->last_seq = t->m.seq;
        n->last_seen = (long)time(NULL);
        n->hay_telemetria = 1;
        if (n->estado == NODO_SIN_REPORTE) {
            n->estado = NODO_ACTIVO;
            evento_interno(n, "INFO", "RECUPERADO", NODO_SIN_REPORTE);
        }
    }
    pthread_mutex_unlock(&mtx_tabla);
    return r;
}

/*
 * 7.4: guarda el evento una sola vez por (node_id, msg_id), recordando los
 * ultimos MAX_MSGID de cada nodo. Devuelve 0 si es nuevo, 1 si ya estaba
 * guardado y -1 si el nodo no existe.
 */
int estado_guardar_evento(const char *node_id, const Evento *ev)
{
    Nodo *n;
    int dup = 0;

    pthread_mutex_lock(&mtx_tabla);
    n = buscar(node_id);
    if (n == NULL) {
        pthread_mutex_unlock(&mtx_tabla);
        return -1;
    }
    for (int i = 0; i < n->msgid_n && !dup; i++)
        dup = strcmp(n->msgids[i], ev->msg_id) == 0;
    if (!dup) {
        util_copiar(n->msgids[n->msgid_pos], sizeof n->msgids[0], ev->msg_id);
        n->msgid_pos = (n->msgid_pos + 1) % MAX_MSGID;
        if (n->msgid_n < MAX_MSGID)
            n->msgid_n++;
        guardar_evento(ev);
    }
    pthread_mutex_unlock(&mtx_tabla);
    return dup;
}

/* ---- Consultas: copian los datos y sueltan el candado antes de responder ---- */

static int cmp_resumen(const void *a, const void *b)
{
    return strcmp(((const NodoResumen *)a)->node_id, ((const NodoResumen *)b)->node_id);
}

int estado_listar(NodoResumen out[MAX_NODOS])
{
    int k = 0;

    pthread_mutex_lock(&mtx_tabla);
    for (int i = 0; i < MAX_NODOS; i++) {
        if (!nodos[i].usado)
            continue;
        util_copiar(out[k].node_id, sizeof out[k].node_id, nodos[i].node_id);
        util_copiar(out[k].kind, sizeof out[k].kind, nodos[i].kind);
        out[k].estado = nodos[i].estado;
        out[k].last_seen = nodos[i].last_seen;
        k++;
    }
    pthread_mutex_unlock(&mtx_tabla);
    qsort(out, (size_t)k, sizeof out[0], cmp_resumen);
    return k;
}

/* 0 si existe, -1 si el nodo no esta en la tabla. */
int estado_status(const char *node_id, NodoStatus *out)
{
    Nodo *n;

    pthread_mutex_lock(&mtx_tabla);
    n = buscar(node_id);
    if (n == NULL) {
        pthread_mutex_unlock(&mtx_tabla);
        return -1;
    }
    memset(out, 0, sizeof *out);
    util_copiar(out->node_id, sizeof out->node_id, n->node_id);
    out->estado = n->estado;
    out->last_seen = n->last_seen;
    out->hay_telemetria = n->hay_telemetria;
    if (n->hay_telemetria)
        out->ultima = *muestra_reciente(n, 0);
    out->lost = n->lost;
    out->dups = n->dups;
    out->ooo = n->ooo;
    pthread_mutex_unlock(&mtx_tabla);
    return 0;
}

/* Hasta n muestras, la mas reciente primero. -1 si el nodo no existe. */
int estado_historial(const char *node_id, int n, Muestra out[MAX_MUESTRAS])
{
    Nodo *nd;
    int k;

    pthread_mutex_lock(&mtx_tabla);
    nd = buscar(node_id);
    if (nd == NULL) {
        pthread_mutex_unlock(&mtx_tabla);
        return -1;
    }
    k = nd->hist_n < n ? nd->hist_n : n;
    for (int i = 0; i < k; i++)
        out[i] = *muestra_reciente(nd, i);
    pthread_mutex_unlock(&mtx_tabla);
    return k;
}

/*
 * Hasta n eventos, el mas reciente primero (orden de almacenamiento), de
 * todos los nodos o solo de node_id si no es NULL. -1 si ese nodo no existe.
 */
int estado_eventos(const char *node_id, int n, Evento out[MAX_EVENTOS])
{
    int k = 0;

    pthread_mutex_lock(&mtx_tabla);
    if (node_id != NULL && buscar(node_id) == NULL) {
        pthread_mutex_unlock(&mtx_tabla);
        return -1;
    }
    for (int i = 0; i < ev_n && k < n; i++) {
        const Evento *ev = &eventos[(ev_pos - 1 - i + 2 * MAX_EVENTOS) % MAX_EVENTOS];
        if (node_id == NULL || strcmp(ev->node_id, node_id) == 0)
            out[k++] = *ev;
    }
    pthread_mutex_unlock(&mtx_tabla);
    return k;
}
