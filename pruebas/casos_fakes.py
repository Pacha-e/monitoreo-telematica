"""Pruebas de los nodos y del cliente reales frente a un servidor MCD falso que se
porta mal a propósito (intlib.ServidorFalso): situaciones que el servidor real casi
nunca produce, pero que el protocolo obliga a manejar (secciones 7.4, 7.9 y 9)."""
import time

from mcdlib import ADMIN, eq, esperar, ok
from mcdlib import prueba
from intlib import ServidorFalso, cliente, lanzar_nodo


def sin_excepciones(proc):
    ok("Traceback" not in proc.err(), "el programa lanzó una excepción: %s" % proc.err()[-500:])


@prueba
def integ_nodo_error_404_por_udp_se_registra_de_nuevo_sin_esperar(ctx):
    falso = ServidorFalso("udp404")
    nodo = lanzar_nodo(falso.puerto, "nodo-31", "nodo_red.py", backoff_max=30)
    try:
        ok(esperar(lambda: len(falso.registros) >= 2, 10, 0.05), "el nodo no volvió a registrarse")
        espera = falso.registros[1][0] - falso.registros[0][0]
        ok(espera < 0.9, "el reregistro debe ser inmediato (sin los 1 s del backoff): %.2f s" % espera)
        ok("por UDP" in nodo.err() and "se registra de nuevo" in nodo.err(), nodo.err()[-400:])
        sin_excepciones(nodo)
    finally:
        nodo.terminar()
        falso.cerrar()


@prueba
def integ_nodo_404_continuo_no_provoca_tormenta_de_registros(ctx):
    falso = ServidorFalso("siempre404")
    nodo = lanzar_nodo(falso.puerto, "nodo-31", "nodo_red.py", backoff_max=30)
    try:
        time.sleep(5)
        n = len(falso.registros)
        ok(3 <= n <= 12, "con 404 continuo el nodo debe frenar los reregistros (5 s): %d registros" % n)
        ok(nodo.vivo(), "el nodo sigue vivo")
        sin_excepciones(nodo)
    finally:
        nodo.terminar()
        falso.cerrar()


@prueba
def integ_nodo_sin_ack_reconecta_y_reenvia_el_mismo_msg_id(ctx):
    falso = ServidorFalso("sin_ack")
    nodo = lanzar_nodo(falso.puerto, "nodo-32", "nodo_sensor.py",
                       extra=["--t-ack", "1", "--forzar-evento", "CRITICO:FALLA:1"])
    try:
        ok(esperar(lambda: len(falso.eventos) >= 3, 15, 0.1), "el evento no se reenvió: %s" % falso.eventos)
        ids = {e[2] for e in falso.eventos}
        eq(len(ids), 1, "todos los envíos llevan el mismo msg_id: %s" % falso.eventos)
        ok(len({e[0] for e in falso.eventos}) >= 3, "cada reenvío va por una conexión nueva")
        ok("vence T_ack" in nodo.err(), "el nodo anota el vencimiento de T_ack")
        sin_excepciones(nodo)
    finally:
        nodo.terminar()
        falso.cerrar()


@prueba
def integ_nodo_mensaje_invalido_del_servidor_cierra_y_reintenta(ctx):
    falso = ServidorFalso("basura")
    nodo = lanzar_nodo(falso.puerto, "nodo-33", "nodo_red.py")
    try:
        ok(esperar(lambda: len(falso.registros) >= 2, 10, 0.1), "no reintentó tras la línea inválida")
        ok("mensaje inválido del servidor" in nodo.err(), nodo.err()[-400:])
        ok(esperar(lambda: falso.telemetrias >= 2, 10, 0.1), "tras el reintento el nodo opera con normalidad")
        ok(nodo.vivo(), "el nodo sigue vivo")
        sin_excepciones(nodo)
    finally:
        nodo.terminar()
        falso.cerrar()


@prueba
def integ_nodo_503_en_el_registro_usa_espera_creciente(ctx):
    falso = ServidorFalso("503")
    nodo = lanzar_nodo(falso.puerto, "nodo-34", "nodo_sensor.py", backoff_max=30)
    try:
        ok(esperar(lambda: len(falso.registros) >= 3, 15, 0.1), "no llegó al tercer intento")
        t = [r[0] for r in falso.registros]
        ok(t[1] - t[0] >= 0.9, "primera espera ~1 s: %.2f" % (t[1] - t[0]))
        ok(t[2] - t[1] >= 1.9, "segunda espera ~2 s (se duplica): %.2f" % (t[2] - t[1]))
        ok(esperar(lambda: falso.telemetrias >= 1, 10, 0.1), "con el registro aceptado empieza la telemetría")
        ok("registro rechazado: ERROR 503 LDAP" in nodo.err(), nodo.err()[-400:])
        sin_excepciones(nodo)
    finally:
        nodo.terminar()
        falso.cerrar()


@prueba
def integ_cliente_respuesta_incompleta_se_trata_como_falla_de_red(ctx):
    falso = ServidorFalso("lista_corta")
    try:
        t0 = time.time()
        r = cliente(falso.puerto, ADMIN, "lista", extra=["--reintentos", "2", "--backoff-max", "1"])
        eq(r.rc, 4, "respuesta inválida -> error de red tras los reintentos")
        ok("respuesta inválida" in r.stderr or "cerró la conexión" in r.stderr, r.stderr[-300:])
        ok(falso.logins >= 3, "el cliente reconectó y repitió el LOGIN en cada intento: %d" % falso.logins)
        ok("Traceback" not in r.stderr, "sin excepciones sin manejar")
        ok(time.time() - t0 < 30, "terminó en tiempo razonable")
    finally:
        falso.cerrar()
