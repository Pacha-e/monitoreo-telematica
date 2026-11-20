/*
 * red.c - Sockets Berkeley, hilos y encuadre TCP (secciones 4.3, 4.4 y 10).
 *
 * - Hilo principal: accept() y un hilo detached por conexion (max 64).
 * - Hilo UDP: recvfrom() de TELEMETRY.
 * - Hilo watchdog: revisa la tabla cada segundo.
 * - Cada hilo de conexion usa SO_RCVTIMEO de 1 s para revisar sus plazos
 *   (T_ident, T_inactividad) y SO_SNDTIMEO de 5 s para que un cliente
 *   lento no lo bloquee indefinidamente.
 *
 * mtx_conn protege solo la tabla de conexiones activas; no se toma junto
 * con el candado de la tabla de nodos.
 */
#include <errno.h>
#include <netdb.h>
#include <netinet/in.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include "mcd.h"

static int fd_tcp = -1, fd_udp = -1;
static volatile sig_atomic_t terminar;
static pthread_mutex_t mtx_conn = PTHREAD_MUTEX_INITIALIZER;
static Conexion *tabla_conn[MAX_CONEXIONES];
static unsigned long ultimo_id;

/* Seguro desde un manejador de senales. */
void red_terminar(void) { terminar = 1; }

/* ---- Sockets de escucha: getaddrinfo con AI_PASSIVE, sin IP escrita ---- */

static int abrir_socket(int tipo, const char *puerto)
{
    struct addrinfo h, *r = NULL;
    struct timeval tv = { 1, 0 };
    int fd, uno = 1, g;
    const char *que = tipo == SOCK_STREAM ? "TCP" : "UDP";

    memset(&h, 0, sizeof h);
    h.ai_family = AF_INET;
    h.ai_socktype = tipo;
    h.ai_flags = AI_PASSIVE;
    g = getaddrinfo(NULL, puerto, &h, &r);
    if (g != 0) {
        fprintf(stderr, "getaddrinfo(%s): %s\n", que, gai_strerror(g));
        return -1;
    }
    fd = socket(r->ai_family, r->ai_socktype, r->ai_protocol);
    if (fd < 0) {
        fprintf(stderr, "socket(%s): %s\n", que, strerror(errno));
        freeaddrinfo(r);
        return -1;
    }
    if (tipo == SOCK_STREAM)
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &uno, sizeof uno);
    /* El timeout de recepcion permite revisar la bandera de apagado. */
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    if (bind(fd, r->ai_addr, r->ai_addrlen) < 0 ||
        (tipo == SOCK_STREAM && listen(fd, 128) < 0)) {
        fprintf(stderr, "bind/listen %s puerto %s: %s\n", que, puerto, strerror(errno));
        close(fd);
        freeaddrinfo(r);
        return -1;
    }
    freeaddrinfo(r);
    return fd;
}

int red_iniciar(unsigned short puerto)
{
    char p[8];

    snprintf(p, sizeof p, "%hu", puerto);
    fd_tcp = abrir_socket(SOCK_STREAM, p);
    if (fd_tcp < 0)
        return -1;
    fd_udp = abrir_socket(SOCK_DGRAM, p);
    if (fd_udp < 0) {
        close(fd_tcp);
        fd_tcp = -1;
        return -1;
    }
    return 0;
}

static void peer_texto(const struct sockaddr *sa, socklen_t sl, char *out, size_t n)
{
    char host[40], serv[8];

    if (getnameinfo(sa, sl, host, sizeof host, serv, sizeof serv,
                    NI_NUMERICHOST | NI_NUMERICSERV) != 0) {
        util_copiar(out, n, "?:?");
        return;
    }
    snprintf(out, n, "%s:%s", host, serv);
}

/* ---- Tabla de conexiones activas ---- */

static int conn_registrar(Conexion *c)
{
    int ok = -1;

    pthread_mutex_lock(&mtx_conn);
    for (int i = 0; i < MAX_CONEXIONES; i++) {
        if (tabla_conn[i] == NULL) {
            tabla_conn[i] = c;
            c->id = ++ultimo_id;
            ok = 0;
            break;
        }
    }
    pthread_mutex_unlock(&mtx_conn);
    return ok;
}

static void conn_quitar(Conexion *c)
{
    pthread_mutex_lock(&mtx_conn);
    for (int i = 0; i < MAX_CONEXIONES; i++)
        if (tabla_conn[i] == c)
            tabla_conn[i] = NULL;
    pthread_mutex_unlock(&mtx_conn);
}

/*
 * Cierra la conexion con ese id (la que un REGISTER nuevo reemplaza, 7.2).
 * shutdown() hace que su hilo vea fin de archivo y termine por su cuenta;
 * el candado garantiza que el descriptor no se ha cerrado todavia.
 */
void red_cerrar_conexion(unsigned long id)
{
    pthread_mutex_lock(&mtx_conn);
    for (int i = 0; i < MAX_CONEXIONES; i++)
        if (tabla_conn[i] != NULL && tabla_conn[i]->id == id)
            shutdown(tabla_conn[i]->fd, SHUT_RDWR);
    pthread_mutex_unlock(&mtx_conn);
}

/*
 * Cierre ordenado tras una respuesta final: si quedan bytes sin leer, un
 * close() directo enviaria RST y el cliente podria perder el ERROR.
 */
static void cerrar_gracil(int fd)
{
    struct timeval tv = { 0, 200000 };
    char tmp[512];
    long total = 0;

    shutdown(fd, SHUT_WR);
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    for (int i = 0; i < 128 && total < 65536; i++) {
        ssize_t n = recv(fd, tmp, sizeof tmp, 0);
        if (n <= 0)
            break;
        total += n;
    }
    close(fd);
}

/* Registra en el log y envia la respuesta pendiente. 0 si el envio fallo. */
int red_enviar(Conexion *c)
{
    size_t i = 0, off = 0;
    int ok = 1;

    while (i < c->out_len) {
        char *lf = memchr(c->out + i, '\n', c->out_len - i);
        size_t l = lf != NULL ? (size_t)(lf - (c->out + i)) : c->out_len - i;
        registro("TCP", c->peer, "->", c->out + i, l);
        i += l + 1;
    }
    while (off < c->out_len) {
        ssize_t n = send(c->fd, c->out + off, c->out_len - off, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            registro_nota("TCP", c->peer, "envio fallido: %s", strerror(errno));
            ok = 0;
            break;
        }
        off += (size_t)n;
    }
    c->out_len = 0;
    return ok;
}

/* ---- Hilo de una conexion TCP ---- */

static void responder_error(Conexion *c, int code, const char *reason)
{
    char b[96];

    proto_error(b, sizeof b, 0, code, reason, NULL);
    conn_out(c, "%s", b);
    red_enviar(c);
}

/* T_ident (sin identificar) y T_inactividad (solo sesiones de administracion). */
static int plazo_vencido(Conexion *c)
{
    double ahora = util_mono();

    if ((c->tipo == C_NUEVA && ahora - c->t_ident > cfg.t_ident) ||
        (c->tipo == C_ADMIN && ahora - c->t_actividad > cfg.t_inact)) {
        responder_error(c, 408, "TIEMPO");
        return 1;
    }
    return 0;
}

/*
 * Encuadre (4.3): extrae del buffer cada linea terminada en LF y la
 * procesa. Devuelve 1 si la conexion debe cerrarse.
 */
static int procesar_lineas(Conexion *c, char *buf, size_t *len)
{
    for (;;) {
        char *lf = memchr(buf, '\n', *len);
        size_t total, cont;

        if (lf == NULL) {
            if (*len >= MAX_MSG) {   /* 512 bytes sin LF: la linea no cabe */
                registro("TCP", c->peer, "<-", buf, *len);
                responder_error(c, 413, "TAMANO");
                return 1;
            }
            return 0;
        }
        total = (size_t)(lf - buf) + 1;
        if (total > MAX_MSG) {
            registro("TCP", c->peer, "<-", buf, total - 1);
            responder_error(c, 413, "TAMANO");
            return 1;
        }
        cont = total - 1;
        if (cont > 0 && buf[cont - 1] == '\r')   /* tolera CRLF (4.3 punto 5) */
            cont--;
        if (cont > 0) {                          /* linea vacia: se ignora */
            c->t_actividad = util_mono();
            manejar_linea_tcp(c, buf, cont);
            if (!red_enviar(c) || c->cerrar)
                return 1;
        }
        memmove(buf, buf + total, *len - total);
        *len -= total;
    }
}

static void *hilo_conexion(void *arg)
{
    Conexion *c = arg;
    char buf[BUF_CONEXION];
    size_t len = 0;
    struct timeval rcv = { 1, 0 }, snd = { 5, 0 };
    int uno = 1;
    const char *motivo = "fin del servicio";

    setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &rcv, sizeof rcv);
    setsockopt(c->fd, SOL_SOCKET, SO_SNDTIMEO, &snd, sizeof snd);
    setsockopt(c->fd, SOL_SOCKET, SO_KEEPALIVE, &uno, sizeof uno);
    c->t_ident = c->t_actividad = util_mono();
    registro_nota("TCP", c->peer, "conexion aceptada id=%lu", c->id);

    while (!terminar) {
        ssize_t n;

        if (procesar_lineas(c, buf, &len)) {
            motivo = "cerrada por el servidor";
            break;
        }
        if (plazo_vencido(c)) {
            motivo = "plazo vencido";
            break;
        }
        n = recv(c->fd, buf + len, sizeof buf - len, 0);
        if (n > 0) {
            len += (size_t)n;
        } else if (n == 0) {
            motivo = len > 0 ? "el cliente cerro con una linea incompleta"
                             : "el cliente cerro";
            break;
        } else if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
            motivo = strerror(errno);
            break;
        }
    }
    /* 7.7: si era la conexion vigente de un nodo, pasa a DESCONECTADO. */
    if (c->tipo == C_NODO)
        estado_desconectar(c->node_id, c->id);
    registro_nota("TCP", c->peer, "conexion cerrada id=%lu (%s)", c->id, motivo);
    conn_quitar(c);
    cerrar_gracil(c->fd);
    free(c);
    return NULL;
}

/* ---- Hilo UDP: un ERROR por origen cada 5 s como maximo (7.3) ---- */

typedef struct { unsigned int addr; unsigned short port; double t; int usado; } LimiteUdp;

static int udp_error_permitido(const struct sockaddr_in *sa)
{
    static LimiteUdp lim[64];   /* solo lo usa el hilo UDP */
    double ahora = util_mono();
    int libre = -1, viejo = 0;

    for (int i = 0; i < 64; i++) {
        if (lim[i].usado && lim[i].addr == sa->sin_addr.s_addr &&
            lim[i].port == sa->sin_port) {
            if (ahora - lim[i].t < 5.0)
                return 0;
            lim[i].t = ahora;
            return 1;
        }
        if (!lim[i].usado && libre < 0)
            libre = i;
        if (lim[i].usado && lim[i].t < lim[viejo].t)
            viejo = i;
    }
    if (libre < 0)
        libre = viejo;
    lim[libre].usado = 1;
    lim[libre].addr = sa->sin_addr.s_addr;
    lim[libre].port = sa->sin_port;
    lim[libre].t = ahora;
    return 1;
}

static void *hilo_udp(void *arg)
{
    char buf[BUF_CONEXION];

    (void)arg;
    while (!terminar) {
        struct sockaddr_storage sa;
        socklen_t sl = sizeof sa;
        char peer[64], resp[128];
        ssize_t n = recvfrom(fd_udp, buf, sizeof buf, 0, (struct sockaddr *)&sa, &sl);
        int rl;

        if (n < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
                registro_sys("recvfrom fallo: %s", strerror(errno));
                usleep(10000);
            }
            continue;
        }
        peer_texto((struct sockaddr *)&sa, sl, peer, sizeof peer);
        rl = manejar_udp(buf, (size_t)n, peer, resp, sizeof resp);
        if (rl <= 0)
            continue;
        if (udp_error_permitido((struct sockaddr_in *)&sa)) {
            registro("UDP", peer, "->", resp, (size_t)rl - 1);
            sendto(fd_udp, resp, (size_t)rl, 0, (struct sockaddr *)&sa, sl);
        } else {
            registro_nota("UDP", peer, "ERROR omitido: limite de 1 cada 5 s por origen");
        }
    }
    return NULL;
}

static void *hilo_watchdog(void *arg)
{
    (void)arg;
    while (!terminar) {
        sleep(1);
        estado_watchdog(time(NULL));
    }
    return NULL;
}

/*
 * Crea un hilo detached con SIGINT/SIGTERM bloqueadas: asi solo el hilo
 * principal recibe la senal de apagado y su accept() se interrumpe.
 */
static int crear_hilo(void *(*fn)(void *), void *arg)
{
    sigset_t bloq, previo;
    pthread_t th;
    int rc;

    sigemptyset(&bloq);
    sigaddset(&bloq, SIGINT);
    sigaddset(&bloq, SIGTERM);
    pthread_sigmask(SIG_BLOCK, &bloq, &previo);
    rc = pthread_create(&th, NULL, fn, arg);
    pthread_sigmask(SIG_SETMASK, &previo, NULL);
    if (rc != 0)
        return -1;
    pthread_detach(th);
    return 0;
}

void red_lanzar_hilos(void)
{
    if (crear_hilo(hilo_udp, NULL) != 0 || crear_hilo(hilo_watchdog, NULL) != 0) {
        fprintf(stderr, "no se pudieron crear los hilos auxiliares\n");
        exit(1);
    }
}

/* Responde 503/500 a una conexion que no se va a atender y la cierra. */
static void rechazar(Conexion *c, int code, const char *reason)
{
    responder_error(c, code, reason);
    close(c->fd);
    free(c);
}

/* Ciclo de accept() del hilo principal (10). */
void red_aceptar(void)
{
    while (!terminar) {
        struct sockaddr_storage sa;
        socklen_t sl = sizeof sa;
        int fd = accept(fd_tcp, (struct sockaddr *)&sa, &sl);
        Conexion *c;

        if (fd < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR &&
                errno != ECONNABORTED) {
                registro_sys("accept fallo: %s", strerror(errno));
                usleep(100000);
            }
            continue;
        }
        c = calloc(1, sizeof *c);
        if (c == NULL) {
            close(fd);
            continue;
        }
        c->fd = fd;
        peer_texto((struct sockaddr *)&sa, sl, c->peer, sizeof c->peer);
        if (conn_registrar(c) != 0) {
            registro_nota("TCP", c->peer, "conexion rechazada: 64 conexiones abiertas");
            rechazar(c, 503, "CAPACIDAD");
        } else if (crear_hilo(hilo_conexion, c) != 0) {
            registro_nota("TCP", c->peer, "no se pudo crear el hilo de la conexion");
            conn_quitar(c);
            rechazar(c, 500, "INTERNO");
        }
    }
    close(fd_tcp);
    close(fd_udp);
}
