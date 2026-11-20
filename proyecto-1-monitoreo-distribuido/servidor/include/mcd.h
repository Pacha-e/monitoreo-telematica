/*
 * mcd.h - Definiciones comunes del servidor MCD/1.0.
 *
 * Referencia normativa: fuentes/MCD-1.0.md. Las secciones citadas en los
 * comentarios (p. ej. "6.1") son las de ese documento.
 */
#ifndef MCD_H
#define MCD_H

#include <stddef.h>
#include <time.h>

/* ---- Limites (seccion 8) ---- */
#define MCD_VERSION          "MCD/1.0"
#define MAX_MSG              512   /* bytes por mensaje, con el LF */
#define MAX_CAMPOS           16
#define MAX_CONEXIONES       64
#define MAX_NODOS            32
#define MAX_MUESTRAS         10
#define MAX_EVENTOS          100
#define MAX_MSGID            64
#define MAX_LOGIN_FALLOS     3
#define MAX_ERRORES_FORMATO  5
#define BUF_CONEXION         1024  /* buffer de encuadre por conexion */
#define OUT_MAX              16384 /* respuesta completa de una consulta */

#define ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))

/* ---- Configuracion por variables de entorno (util.c) ---- */
typedef struct {
    char   ldap_host[256];   /* MCD_LDAP_HOST, defecto ldap.monitoreo.lab */
    int    ldap_port;        /* MCD_LDAP_PORT, defecto 389 */
    char   ldap_base[256];   /* MCD_LDAP_BASE, defecto dc=monitoreo,dc=lab */
    int    ldap_timeout;     /* MCD_LDAP_TIMEOUT (s), defecto 3 */
    double t_ident;          /* MCD_T_IDENT (s), defecto 60 */
    double t_inact;          /* MCD_T_INACTIVIDAD (s), defecto 300 */
} Config;
extern Config cfg;

/* ---- Mensajes (protocolo.c) ---- */
typedef struct { char clave[17]; char valor[65]; } Campo;

typedef struct {
    char  tipo[17];
    Campo campo[MAX_CAMPOS];
    int   n;
} Msg;

/* Error de protocolo: codigo, motivo enumerado y campo culpable (422). */
typedef struct { int code; const char *reason; const char *field; } ErrProto;

/* ---- Estado compartido (estado.c) ---- */
typedef enum { NODO_ACTIVO = 0, NODO_SIN_REPORTE, NODO_DESCONECTADO } EstadoNodo;

/* Una muestra de telemetria ya validada; se guarda como texto para
 * devolver exactamente lo que envio el nodo (p. ej. "41.0"). */
typedef struct {
    unsigned long seq;
    char ts[12];
    char cpu[8];
    char temp[8];
    char bat[4];
    char opstate[16];
    char uptime[12];
} Muestra;

typedef struct {
    char    node_id[33];
    char    session[17];
    Muestra m;
} Telemetria;

typedef struct {
    char node_id[33];
    char msg_id[24];
    char ts[12];
    char level[16];
    char event[16];
    char value[40];   /* vacio si el evento no lleva value */
} Evento;

typedef struct {
    char       node_id[33];
    char       kind[8];
    EstadoNodo estado;
    long       last_seen;
} NodoResumen;

typedef struct {
    char          node_id[33];
    EstadoNodo    estado;
    long          last_seen;
    int           hay_telemetria;   /* 0 -> los campos de la muestra son NA */
    Muestra       ultima;
    unsigned long lost, dups, ooo;
} NodoStatus;

typedef enum {
    TEL_OK = 0, TEL_NODO_DESCONOCIDO, TEL_SESION_INVALIDA,
    TEL_DUPLICADA, TEL_ATRASADA
} TelRes;

/* ---- Conexion TCP (manejadores.c / red.c) ---- */
typedef enum { C_NUEVA = 0, C_NODO, C_ADMIN } TipoConn;

typedef struct Conexion {
    int           fd;
    unsigned long id;               /* identificador unico en el proceso */
    char          peer[64];         /* "ip:puerto" del cliente */
    TipoConn      tipo;
    char          node_id[33];      /* si tipo == C_NODO */
    char          user[40];         /* si tipo == C_ADMIN */
    int           es_admin;         /* perfil admin (1) u operador (0) */
    int           fallos_login;
    int           errores_formato;  /* 400/422 seguidos */
    double        t_ident;          /* inicio del plazo T_ident (monotonico) */
    double        t_actividad;      /* ultima peticion (monotonico) */
    int           cerrar;           /* cerrar tras enviar la respuesta */
    size_t        out_len;
    char          out[OUT_MAX];     /* respuesta pendiente de enviar */
} Conexion;

/* ---- Autenticacion (auth.c) ---- */
typedef enum { AUTH_OK = 0, AUTH_CRED, AUTH_ROL, AUTH_LDAP, AUTH_DNS } AuthRes;

/* ---- util.c ---- */
void   config_cargar(void);
void   util_ahora_iso(char *buf, size_t n);
double util_mono(void);
void   util_copiar(char *dst, size_t n, const char *src);
int    util_uint(const char *v, unsigned long long max, unsigned long long *out);
int    util_decimal(const char *v, int con_signo, double min, double max);
int    util_hex_aleatorio(char *out, size_t nbytes);

/* ---- registro.c ---- */
int  registro_init(const char *ruta);
void registro(const char *canal, const char *peer, const char *dir,
              const char *msg, size_t n);
void registro_nota(const char *canal, const char *peer, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));
void registro_sys(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

/* ---- protocolo.c ---- */
int           proto_parsear(const char *linea, size_t len, Msg *m, ErrProto *e);
int           proto_validar(const Msg *m, ErrProto *e);
int           proto_tipo_conocido(const char *t);
const char   *proto_campo(const Msg *m, const char *clave);
unsigned long proto_req(const Msg *m);
int           proto_error(char *buf, size_t n, unsigned long req, int code,
                          const char *reason, const char *field);

/* ---- estado.c ---- */
const char *estado_nombre(EstadoNodo e);
void   estado_init(void);
int    estado_registrar(const char *node_id, const char *kind, int period,
                        unsigned long conn_id, char session[17],
                        unsigned long *conn_anterior);
void   estado_desconectar(const char *node_id, unsigned long conn_id);
TelRes estado_telemetria(const Telemetria *t);
int    estado_guardar_evento(const char *node_id, const Evento *ev);
void   estado_watchdog(time_t ahora);
int    estado_listar(NodoResumen out[MAX_NODOS]);
int    estado_status(const char *node_id, NodoStatus *out);
int    estado_historial(const char *node_id, int n, Muestra out[MAX_MUESTRAS]);
int    estado_eventos(const char *node_id, int n, Evento out[MAX_EVENTOS]);

/* ---- auth.c ---- */
AuthRes auth_nodo(const char *node_id, const char *secret);
AuthRes auth_usuario(const char *user, const char *password, int *es_admin);

/* ---- manejadores.c / consultas.c ---- */
void conn_out(Conexion *c, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));
void manejar_linea_tcp(Conexion *c, const char *linea, size_t len);
int  manejar_udp(const char *dat, size_t len, const char *peer,
                 char *resp, size_t cap);
void consulta_list(Conexion *c, unsigned long req);
void consulta_status(Conexion *c, unsigned long req, const char *node_id);
void consulta_history(Conexion *c, unsigned long req, const char *node_id, int n);
void consulta_events(Conexion *c, unsigned long req, int n, const char *node_id);

/* ---- red.c ---- */
int  red_iniciar(unsigned short puerto);
void red_lanzar_hilos(void);
void red_aceptar(void);
void red_terminar(void);
int  red_enviar(Conexion *c);
void red_cerrar_conexion(unsigned long id);

#endif /* MCD_H */
