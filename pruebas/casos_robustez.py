"""Pruebas de robustez: concurrencia, LDAP caido, DNS irresoluble, plazos,
limites de capacidad y contenido del log (secciones 7.9, 8, 10 y 11)."""
import re
import threading
import time

from mcdlib import (ADMIN, CLAVE_INCORRECTA, OPERADOR, SINROL, ClienteTCP,
                    ClienteUDP, clave_nodo, eq, error, esperar, login, ok,
                    prueba, registrar_nodo, telemetria)


@prueba
def concurrencia_25_clientes(ctx):
    errores = []
    barrera = threading.Barrier(25)

    def nodo(i):
        try:
            nid = "nodo-%02d" % (6 + i)
            barrera.wait(15)
            c, sess = registrar_nodo(ctx.puerto, nid)
            u = ClienteUDP(ctx.puerto)
            for seq in (1, 2, 3):
                u.enviar(telemetria(nid, sess, seq))
            t, r = c.pedir("EVENT", node_id=nid, msg_id="1791122500-%d" % (i + 1), ts=1,
                           level="INFO", event="ALARMA", value="OK")
            eq(t, "ACK", "ACK del evento de " + nid)
            eq(c.pedir("BYE")[0], "BYE")
            u.cerrar()
            c.cerrar()
        except Exception as e:
            errores.append("nodo %d: %r" % (i, e))

    def admin(i):
        try:
            barrera.wait(15)
            c, role = login(ctx.puerto, ADMIN if i % 2 == 0 else OPERADOR)
            for _ in range(5):
                t, r, items = c.consulta("LIST")
                eq(t, "RESPONSE")
                t, r, items = c.consulta("HISTORY", node_id="nodo-02", n=5)
                eq(t, "RESPONSE")
            eq(c.pedir("BYE")[0], "BYE")
            c.cerrar()
        except Exception as e:
            errores.append("admin %d: %r" % (i, e))

    hilos = [threading.Thread(target=nodo, args=(i,)) for i in range(10)]
    hilos += [threading.Thread(target=admin, args=(i,)) for i in range(15)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(60)
    ok(not errores, "; ".join(errores))
    ok(ctx.srv.vivo(), "el servidor sigue vivo")
    adm = ctx.admin()
    t, r, items = adm.consulta("LIST")
    ids = {i["node_id"] for i in items}
    ok({"nodo-%02d" % k for k in range(6, 16)} <= ids, "los 10 nodos quedaron en la tabla")
    adm.cerrar()


@prueba
def ldap_caido_responde_503_y_se_recupera(ctx):
    ctx.ldap.detener()
    try:
        c = ClienteTCP(ctx.puerto)
        for req in range(1, 5):       # 503 no cuenta como intento fallido: no cierra al tercero
            t, r = c.pedir("LOGIN", user=ADMIN[0], password=ADMIN[1])
            error(t, r, 503, "LDAP", req=req)
        t, r = c.pedir("LIST")
        error(t, r, 401, "SIN_SESION")    # el servidor sigue atendiendo sin LDAP
        n = ClienteTCP(ctx.puerto)
        t, r = n.pedir("REGISTER", node_id="nodo-29", secret=clave_nodo("nodo-29"),
                       kind="IOT", period=5)
        error(t, r, 503, "LDAP", req=1)
        ok(ctx.srv.vivo(), "el proceso sigue vivo con el LDAP caido")
        c.cerrar()
        n.cerrar()
    finally:
        ctx.ldap.iniciar()

    def login_ok():
        c = ClienteTCP(ctx.puerto)
        try:
            return c.pedir("LOGIN", user=ADMIN[0], password=ADMIN[1])[0] == "LOGIN_OK"
        finally:
            c.cerrar()
    ok(esperar(login_ok, 45.0, 0.5), "el login debe volver a funcionar al volver el LDAP")


@prueba
def ldap_con_nombre_irresoluble_no_mata_el_proceso(ctx):
    srv = ctx.nuevo("dns", env={"MCD_LDAP_HOST": "ldap-inexistente.invalid"})
    c = ClienteTCP(srv.puerto)
    c.s.settimeout(60)
    c.enviar("MCD/1.0|LOGIN|req=1|user=admin1|password=%s\n" % ADMIN[1])
    t, r = c.respuesta(plazo=60.0)
    error(t, r, 503, "DNS", req=1)
    t0 = time.time()
    t, r = c.pedir("LOGIN", user=ADMIN[0], password=ADMIN[1])
    error(t, r, 503, "DNS", req=1)
    ok(time.time() - t0 < 2.0, "durante la espera de reintento responde 503 de inmediato")
    n = ClienteTCP(srv.puerto)
    t, r = n.pedir("REGISTER", node_id="nodo-01", secret=clave_nodo("nodo-01"), kind="IOT", period=5)
    error(t, r, 503, "DNS", req=1)
    ok(srv.vivo(), "el proceso sigue vivo")
    c.cerrar()
    n.cerrar()


@prueba
def plazos_t_ident_e_inactividad(ctx):
    srv = ctx.nuevo("plazos", env={"MCD_T_IDENT": "2", "MCD_T_INACTIVIDAD": "2"})
    c = ClienteTCP(srv.puerto)                       # sin identificarse
    error(*c.respuesta(plazo=6.0), 408, "TIEMPO", req=0)
    ok(c.cerrado(), "tras 408 el servidor cierra")
    c = ClienteTCP(srv.puerto)                       # T_ident se reinicia con cada LOGIN fallido
    for req in (1, 2):
        time.sleep(1.4)
        t, r = c.pedir("LOGIN", user=ADMIN[0], password=CLAVE_INCORRECTA)
        error(t, r, 401, "CREDENCIALES", req=req)
    c.cerrar()
    a, _ = login(srv.puerto, ADMIN)                  # sesion de administracion inactiva
    error(*a.respuesta(plazo=6.0), 408, "TIEMPO", req=0)
    ok(a.cerrado(), "tras 408 por inactividad el servidor cierra")
    a, _ = login(srv.puerto, ADMIN)                  # con actividad no vence
    for _ in range(4):
        time.sleep(1.2)
        eq(a.consulta("LIST")[0], "RESPONSE")
    a.cerrar()
    n, _ = registrar_nodo(srv.puerto, "nodo-01")     # la conexion de un nodo no tiene plazo
    time.sleep(4.0)
    t, r = n.pedir("EVENT", node_id="nodo-01", msg_id="1791122600-1", ts=1, level="INFO",
                   event="ALARMA")
    eq(t, "ACK")
    n.cerrar()


@prueba
def limites_de_conexiones_y_nodos(ctx):
    srv = ctx.nuevo("capacidad")
    conns = [ClienteTCP(srv.puerto) for _ in range(64)]
    extra = ClienteTCP(srv.puerto)
    error(*extra.respuesta(), 503, "CAPACIDAD", req=0)
    ok(extra.cerrado(), "tras 503 CAPACIDAD el servidor cierra")
    for c in conns:
        c.cerrar()

    def libre():
        c = ClienteTCP(srv.puerto)
        try:
            return c.pedir("LOGIN", user=ADMIN[0], password=ADMIN[1])[0] == "LOGIN_OK"
        finally:
            c.cerrar()
    ok(esperar(libre, 10.0, 0.3), "las conexiones cerradas liberan sus lugares")
    nodos = [registrar_nodo(srv.puerto, "nodo-%02d" % i)[0] for i in range(1, 33)]
    c = ClienteTCP(srv.puerto)
    t, r = c.pedir("REGISTER", node_id="nodo-33", secret=clave_nodo("nodo-33"), kind="IOT", period=5)
    error(t, r, 503, "CAPACIDAD", req=1)
    ok(c.cerrado(), "tras 503 CAPACIDAD el servidor cierra")
    c2, _ = registrar_nodo(srv.puerto, "nodo-01")    # un nodo ya conocido si puede registrarse
    for n in nodos + [c2]:
        n.cerrar()


def _sin_claves(texto, donde):
    """Ninguna clave de laboratorio ni valor secret/password sin enmascarar."""
    claves = [clave_nodo("nodo-%02d" % i) for i in range(1, 35)]
    claves += [ADMIN[1], OPERADOR[1], SINROL[1], CLAVE_INCORRECTA, "clave-nodo-77",
               "clave-cualquiera"]
    for k in claves:
        ok(k not in texto, "%s contiene la clave %s" % (donde, k))
    suelto = re.search("(secret|password)=[^*]", texto, re.I)
    ok(suelto is None, "%s tiene un secret/password sin enmascarar: %s" % (
        donde, suelto and texto[suelto.start():suelto.start() + 40]))


# Debe ser la ultima prueba: revisa lo que dejaron todas las anteriores.
@prueba
def log_tiene_ip_puerto_y_no_contiene_claves(ctx):
    ctx.admin().cerrar()
    ts = "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
    ip = "127[.]0[.]0[.]1:[0-9]+"
    esperados = [
        ts + " TCP " + ip + " <- MCD/1[.]0[|]REGISTER[|]req=1[|]node_id=nodo-01[|]secret=[*]{3}[|]",
        ts + " TCP " + ip + " -> MCD/1[.]0[|]REGISTER_OK[|]req=1[|]node_id=nodo-01[|]session=",
        ts + " TCP " + ip + " <- MCD/1[.]0[|]LOGIN[|]req=1[|]user=admin1[|]password=[*]{3}",
        ts + " TCP " + ip + " -> MCD/1[.]0[|]LOGIN_OK[|]req=1[|]user=admin1[|]role=admin",
        ts + " TCP " + ip + " -> MCD/1[.]0[|]ERROR[|]req=0[|]code=400[|]reason=FORMATO",
        ts + " UDP " + ip + " <- MCD/1[.]0[|]TELEMETRY[|]node_id=nodo-02[|]session=",
        ts + " UDP " + ip + " -> MCD/1[.]0[|]ERROR[|]req=0[|]code=404[|]reason=NODO",
        ts + " SYS - -- nodo-05 estado=SIN_REPORTE anterior=ACTIVO msg_id=srv-",
    ]
    log = ctx.srv.texto_log()
    consola = open(ctx.srv.f_out, errors="replace").read()
    for patron in esperados:
        ok(re.search("^" + patron, log, re.M), "falta en el archivo de log: " + patron)
        ok(re.search("^" + patron, consola, re.M), "falta en la consola: " + patron)
    _sin_claves(log, "el archivo de log")
    _sin_claves(consola, "la consola")
