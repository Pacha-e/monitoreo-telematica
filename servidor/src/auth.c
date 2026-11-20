/*
 * auth.c - Autenticacion contra LDAP con libldap (7.2, 7.5, 12).
 *
 * Cada verificacion abre y cierra su propia conexion LDAP, asi que no se
 * comparte ningun manejador entre hilos. El nombre del servidor LDAP se
 * resuelve con getaddrinfo antes de cada intento para distinguir una
 * falla de DNS (503 DNS) de una falla del LDAP (503 LDAP).
 *
 * Espera de reintento (7.9): tras una falla de DNS o LDAP el servicio no
 * vuelve a contactar al LDAP hasta que pase la espera 1, 2, 4, 8, 16, 30 s
 * y mientras tanto responde la misma falla de inmediato. mtx_ldap protege
 * solo ese estado de espera.
 */
#include <ldap.h>
#include <netdb.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>

#include "mcd.h"

static pthread_mutex_t mtx_ldap = PTHREAD_MUTEX_INITIALIZER;
static double  prox_intento;       /* instante monotonico del proximo intento */
static int     espera_actual;      /* 0 = sin falla pendiente */
static AuthRes ultima_falla = AUTH_LDAP;

/* Devuelve 1 (y la falla a repetir en *res) si aun estamos en espera. */
static int en_espera(AuthRes *res)
{
    int bloqueado;

    pthread_mutex_lock(&mtx_ldap);
    bloqueado = espera_actual > 0 && util_mono() < prox_intento;
    if (bloqueado)
        *res = ultima_falla;
    pthread_mutex_unlock(&mtx_ldap);
    return bloqueado;
}

static AuthRes falla_servicio(AuthRes tipo)
{
    pthread_mutex_lock(&mtx_ldap);
    espera_actual = espera_actual == 0 ? 1 : (espera_actual * 2 > 30 ? 30 : espera_actual * 2);
    prox_intento = util_mono() + espera_actual;
    ultima_falla = tipo;
    pthread_mutex_unlock(&mtx_ldap);
    return tipo;
}

static void servicio_ok(void)
{
    pthread_mutex_lock(&mtx_ldap);
    espera_actual = 0;
    pthread_mutex_unlock(&mtx_ldap);
}

/* Resuelve el nombre y abre (sin conectar aun) un manejador LDAP. */
static LDAP *abrir(AuthRes *err)
{
    struct addrinfo h, *r = NULL;
    char puerto[8], uri[320];
    struct timeval tv = { cfg.ldap_timeout, 0 };
    int ver = LDAP_VERSION3, g, rc;
    LDAP *ld = NULL;

    if (en_espera(err))
        return NULL;
    memset(&h, 0, sizeof h);
    h.ai_socktype = SOCK_STREAM;
    snprintf(puerto, sizeof puerto, "%d", cfg.ldap_port);
    g = getaddrinfo(cfg.ldap_host, puerto, &h, &r);
    if (g != 0) {
        registro_sys("DNS: no se pudo resolver '%s': %s", cfg.ldap_host, gai_strerror(g));
        *err = falla_servicio(AUTH_DNS);
        return NULL;
    }
    freeaddrinfo(r);
    snprintf(uri, sizeof uri, "ldap://%s:%d", cfg.ldap_host, cfg.ldap_port);
    rc = ldap_initialize(&ld, uri);
    if (rc != LDAP_SUCCESS) {
        registro_sys("LDAP: ldap_initialize fallo: %s", ldap_err2string(rc));
        *err = falla_servicio(AUTH_LDAP);
        return NULL;
    }
    ldap_set_option(ld, LDAP_OPT_PROTOCOL_VERSION, &ver);
    ldap_set_option(ld, LDAP_OPT_NETWORK_TIMEOUT, &tv);
    ldap_set_option(ld, LDAP_OPT_TIMEOUT, &tv);
    return ld;
}

/* Codigos con los que el servidor LDAP contesta, pero indican fallo del servicio. */
static int servicio_caido(int rc)
{
    return rc == LDAP_SERVER_DOWN || rc == LDAP_TIMEOUT || rc == LDAP_CONNECT_ERROR ||
           rc == LDAP_UNAVAILABLE || rc == LDAP_BUSY || rc == LDAP_LOCAL_ERROR ||
           rc == LDAP_NO_MEMORY || rc == LDAP_OPERATIONS_ERROR;
}

/* Bind simple (7.2 y 7.5). Las claves tienen al menos 8 caracteres, asi
 * que nunca se envia un bind anonimo con clave vacia. */
static AuthRes bind_simple(LDAP *ld, const char *dn, const char *clave)
{
    struct berval cred;
    int rc;

    cred.bv_val = (char *)clave;
    cred.bv_len = strlen(clave);
    rc = ldap_sasl_bind_s(ld, dn, LDAP_SASL_SIMPLE, &cred, NULL, NULL, NULL);
    if (rc == LDAP_SUCCESS) {
        servicio_ok();
        return AUTH_OK;
    }
    if (servicio_caido(rc)) {
        registro_sys("LDAP: bind sin servicio: %s", ldap_err2string(rc));
        return falla_servicio(AUTH_LDAP);
    }
    servicio_ok();   /* el LDAP respondio: el rechazo es de las credenciales */
    return AUTH_CRED;
}

AuthRes auth_nodo(const char *node_id, const char *secret)
{
    char dn[320];
    AuthRes r = AUTH_LDAP;
    LDAP *ld = abrir(&r);

    if (ld == NULL)
        return r;
    snprintf(dn, sizeof dn, "cn=%s,ou=devices,%s", node_id, cfg.ldap_base);
    r = bind_simple(ld, dn, secret);
    ldap_unbind_ext_s(ld, NULL, NULL);
    return r;
}

/* 7.5 paso 3: perfil segun los grupos groupOfNames que tienen al usuario. */
static AuthRes buscar_perfil(LDAP *ld, const char *dn_usuario, int *es_admin)
{
    char base[320], filtro[400];
    char *attrs[] = { "cn", NULL };
    struct timeval tv = { cfg.ldap_timeout, 0 };
    LDAPMessage *res = NULL, *e;
    int rc, admin = 0, oper = 0;

    snprintf(base, sizeof base, "ou=groups,%s", cfg.ldap_base);
    snprintf(filtro, sizeof filtro, "(&(objectClass=groupOfNames)(member=%s))", dn_usuario);
    rc = ldap_search_ext_s(ld, base, LDAP_SCOPE_ONELEVEL, filtro, attrs, 0,
                           NULL, NULL, &tv, 0, &res);
    if (rc != LDAP_SUCCESS) {
        if (res != NULL)
            ldap_msgfree(res);
        if (servicio_caido(rc)) {
            registro_sys("LDAP: busqueda de grupos sin servicio: %s", ldap_err2string(rc));
            return falla_servicio(AUTH_LDAP);
        }
        registro_sys("LDAP: busqueda de grupos rechazada: %s", ldap_err2string(rc));
        return AUTH_ROL;
    }
    for (e = ldap_first_entry(ld, res); e != NULL; e = ldap_next_entry(ld, e)) {
        struct berval **v = ldap_get_values_len(ld, e, "cn");
        for (int i = 0; v != NULL && v[i] != NULL; i++) {
            if (v[i]->bv_len == 6 && strncasecmp(v[i]->bv_val, "admins", 6) == 0)
                admin = 1;
            else if (v[i]->bv_len == 10 && strncasecmp(v[i]->bv_val, "operadores", 10) == 0)
                oper = 1;
        }
        if (v != NULL)
            ldap_value_free_len(v);
    }
    ldap_msgfree(res);
    if (!admin && !oper)
        return AUTH_ROL;
    *es_admin = admin;   /* admin tiene prioridad sobre operador */
    return AUTH_OK;
}

AuthRes auth_usuario(const char *user, const char *password, int *es_admin)
{
    char dn[320];
    AuthRes r = AUTH_LDAP;
    LDAP *ld = abrir(&r);

    if (ld == NULL)
        return r;
    snprintf(dn, sizeof dn, "uid=%s,ou=people,%s", user, cfg.ldap_base);
    r = bind_simple(ld, dn, password);
    if (r == AUTH_OK)
        r = buscar_perfil(ld, dn, es_admin);
    ldap_unbind_ext_s(ld, NULL, NULL);
    return r;
}
