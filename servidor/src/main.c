/*
 * main.c - Arranque del servidor: ./servidor <puerto> <archivoDeLogs>
 *
 * Errores de configuracion (argumentos, log, bind) terminan con codigo
 * distinto de 0 (seccion 11). SIGINT/SIGTERM apagan el servicio con codigo 0.
 */
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mcd.h"

static void al_senal(int s)
{
    (void)s;
    red_terminar();
}

static int leer_puerto(const char *s, unsigned short *out)
{
    unsigned long long x;

    if (!util_uint(s, 65535, &x) || x < 1)
        return -1;
    *out = (unsigned short)x;
    return 0;
}

int main(int argc, char **argv)
{
    unsigned short puerto;
    struct sigaction sa;

    if (argc != 3) {
        fprintf(stderr, "uso: %s <puerto> <archivoDeLogs>\n", argv[0]);
        return 2;
    }
    if (leer_puerto(argv[1], &puerto) != 0) {
        fprintf(stderr, "puerto invalido '%s': debe ser un numero de 1 a 65535\n", argv[1]);
        return 2;
    }
    if (registro_init(argv[2]) != 0) {
        perror("no se puede abrir el archivo de logs");
        return 1;
    }
    config_cargar();

    /* SIGPIPE ignorada: escribir en una conexion cerrada devuelve error. */
    signal(SIGPIPE, SIG_IGN);
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = al_senal;   /* sin SA_RESTART: interrumpe accept() */
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    estado_init();
    if (red_iniciar(puerto) != 0)
        return 1;
    red_lanzar_hilos();
    registro_sys("servidor escuchando en el puerto %hu (TCP y UDP), LDAP %s:%d base %s",
                 puerto, cfg.ldap_host, cfg.ldap_port, cfg.ldap_base);
    red_aceptar();
    registro_sys("servidor detenido");
    return 0;
}
