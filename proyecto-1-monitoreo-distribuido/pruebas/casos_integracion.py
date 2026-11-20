"""Pruebas de integración con los programas reales: servidor en C + LDAP + dos
nodos (`nodos/nodo_sensor.py`, `nodos/nodo_red.py`) + cliente (`cliente/cliente_admin.py`).

Cada prueba levanta su propio servidor (`ctx.nuevo`) para no heredar estado de las
demás, y siempre detiene los procesos que lanzó. Los resultados del cliente se leen
de su salida de consola.
"""
import os
import re
import signal
import time

from mcdlib import (ADMIN, OPERADOR, SINROL, Servidor, eq, esperar, login, ok, puerto_libre)
from mcdlib import prueba
from intlib import (CLIENTE, NODOS_DIR, Proc, Proxy, cliente, error_servidor, items, lanzar_nodo,
                    panel_de)

CLAVE_MALA = "clave-incorrecta-xyz"


def espera_estado(adm, nid, cond, plazo=15.0):
    """Espera (nodos y telemetría son asíncronos) a que STATUS de `nid` cumpla `cond`."""
    ultimo = {}

    def f():
        t, _, it = adm.consulta("STATUS", node_id=nid)
        if t != "RESPONSE":
            return False                       # aún no se registra (404)
        ultimo.clear()
        ultimo.update(it[0])
        return cond(ultimo)
    esperar(f, plazo, 0.2)
    ok(ultimo and cond(ultimo), "STATUS de %s no llegó al estado esperado: %s" % (nid, ultimo))
    return ultimo


def con_seq(n):
    return lambda s: s["seq"].isdigit() and int(s["seq"]) >= n


def detener(*procs):
    return [p.terminar() for p in procs]


@prueba
def integ_dos_nodos_telemetria_visible_en_cliente_real(ctx):
    srv = ctx.nuevo("integ-telemetria")
    n1 = lanzar_nodo(srv.puerto, "nodo-21", "nodo_sensor.py")
    n2 = lanzar_nodo(srv.puerto, "nodo-22", "nodo_red.py", extra=["--cpu-base", "50"])
    try:
        adm = login(srv.puerto)[0]
        for nid in ("nodo-21", "nodo-22"):
            espera_estado(adm, nid, con_seq(6))
        lista = items(srv.puerto, ADMIN, "lista")
        eq({i["node_id"]: (i["kind"], i["state"]) for i in lista},
           {"nodo-21": ("SENSOR", "ACTIVO"), "nodo-22": ("RED", "ACTIVO")}, "LIST del cliente real")
        h = items(srv.puerto, ADMIN, "historial nodo-21 5")
        eq(len(h), 5, "al menos 5 datos históricos (requisito 5)")
        seqs = [int(x["seq"]) for x in h]
        eq(seqs, list(range(seqs[0], seqs[0] - 5, -1)), "seq consecutivas, la más reciente primero")
        st21 = items(srv.puerto, ADMIN, "estado nodo-21")[0]
        st22 = items(srv.puerto, ADMIN, "estado nodo-22")[0]
        ok(st21["bat"].isdigit() and 0 <= int(st21["bat"]) <= 100, "el sensor reporta batería: %s" % st21)
        eq(st22["bat"], "NA", "el equipo de red no tiene batería")
        eq((st21["lost"], st21["dups"], st21["ooo"]), ("0", "0", "0"), "sin pérdidas en localhost")
        p = panel_de(cliente(srv.puerto, ADMIN, "panel", extra=["--ciclos", "1"]).stdout)
        eq(sorted(n["estado"]["node_id"] for n in p["nodos"]), ["nodo-21", "nodo-22"], "panel completo")
        ok(all(len(n["historial"]) >= 5 for n in p["nodos"]), "el panel trae 5 muestras por nodo")
        ok(p["eventos"] is not None and p["rol"] == "admin", "el admin ve eventos en el panel")
        po = panel_de(cliente(srv.puerto, OPERADOR, "panel", extra=["--ciclos", "1"]).stdout)
        ok(po["eventos"] is None and po["rol"] == "operador", "el operador no ve eventos")
        eq(detener(n1, n2), [0, 0], "los nodos cierran con BYE y salen con código 0")
        espera_estado(adm, "nodo-21", lambda s: s["state"] == "DESCONECTADO", 5)
        espera_estado(adm, "nodo-22", lambda s: s["state"] == "DESCONECTADO", 5)
        adm.cerrar()
    finally:
        detener(n1, n2)


@prueba
def integ_eventos_de_los_nodos_llegan_una_vez_y_se_confirman(ctx):
    srv = ctx.nuevo("integ-eventos")
    n1 = lanzar_nodo(srv.puerto, "nodo-23", "nodo_sensor.py",
                     extra=["--temp-base", "90", "--forzar-evento", "CRITICO:ALARMA:42"])
    n2 = lanzar_nodo(srv.puerto, "nodo-24", "nodo_red.py",
                     extra=["--forzar-evento", "ADVERTENCIA:UMBRAL_CPU:91.5"])
    try:
        adm = login(srv.puerto)[0]
        esperar(lambda: len(adm.consulta("EVENTS", n=20)[2]) >= 3, 15, 0.2)
        evs = items(srv.puerto, ADMIN, "eventos 20")
        clave = [(e["node_id"], e["event"], e.get("value")) for e in evs]
        eq(clave.count(("nodo-23", "ALARMA", "42")), 1, "ALARMA exactamente una vez: %s" % clave)
        eq(clave.count(("nodo-24", "UMBRAL_CPU", "91.5")), 1, "UMBRAL_CPU una vez")
        ok(any(c[:2] == ("nodo-23", "UMBRAL_TEMP") for c in clave), "el simulador generó UMBRAL_TEMP: %s" % clave)
        ok(all(re.fullmatch(r"\d+-\d+", e["msg_id"]) for e in evs), "msg_id <arranque>-<contador>")
        solo = items(srv.puerto, ADMIN, "eventos 20 nodo-24")
        ok(solo and all(e["node_id"] == "nodo-24" for e in solo), "el filtro por nodo funciona")
        ok(n1.err().count("ACK de ") >= 2, "el nodo registró los ACK: %s" % n1.err()[-400:])
        r = cliente(srv.puerto, OPERADOR, "eventos 5")
        eq(r.rc, 3, "el operador no puede consultar eventos")
        eq(error_servidor(r)[:2], ("403", "ROL"), "403 ROL mostrado por el cliente")
        adm.cerrar()
    finally:
        detener(n1, n2)


@prueba
def integ_ack_perdido_el_nodo_reenvia_y_el_servidor_no_duplica(ctx):
    srv = ctx.nuevo("integ-idempotencia")
    rele = Proxy(srv.puerto, perder_primer_ack=True)
    nodo = lanzar_nodo(rele.puerto, "nodo-26", "nodo_red.py",
                       extra=["--forzar-evento", "CRITICO:ALARMA:99", "--prob-enlace", "0", "--cpu-base", "10"])
    try:
        ok(esperar(lambda: "dup=1" in srv.texto_log(), 25, 0.2), "el servidor nunca vio el reenvío (dup=1)")
        eq(rele.acks_perdidos, 1, "el relé perdió exactamente un ACK")
        log = srv.texto_log()
        ids = re.findall(r"-> MCD/1.0\|ACK\|req=\d+\|node_id=nodo-26\|msg_id=(\S+)\|dup=(\d)", log)
        eq([d for _, d in ids][:2], ["0", "1"], "primero dup=0 y luego dup=1: %s" % ids)
        eq(ids[0][0], ids[1][0], "el reenvío conserva el msg_id")
        evs = [e for e in items(srv.puerto, ADMIN, "eventos 20") if e["event"] == "ALARMA"]
        eq(len(evs), 1, "el evento está guardado una sola vez")
        ok(nodo.err().count("|REGISTER|") == 2, "el nodo se registró de nuevo tras cortarse TCP")
        ok("sesión terminada" in nodo.err(), "el nodo anotó la caída")
    finally:
        nodo.terminar()
        rele.cerrar()


@prueba
def integ_nodo_congelado_sin_reporte_y_recuperacion(ctx):
    srv = ctx.nuevo("integ-sinreporte")
    nodo = lanzar_nodo(srv.puerto, "nodo-27", "nodo_sensor.py", period=1)
    try:
        adm = login(srv.puerto)[0]
        espera_estado(adm, "nodo-27", con_seq(3))
        nodo.senal(signal.SIGSTOP)                       # el proceso deja de enviar, TCP sigue abierto
        espera_estado(adm, "nodo-27", lambda s: s["state"] == "SIN_REPORTE", 12)
        nodo.senal(signal.SIGCONT)
        espera_estado(adm, "nodo-27", lambda s: s["state"] == "ACTIVO", 12)
        evs = items(srv.puerto, ADMIN, "eventos 20 nodo-27")
        conect = [(e["level"], e.get("value")) for e in evs if e["event"] == "CONECTIVIDAD"]
        ok(("ADVERTENCIA", "SIN_REPORTE") in conect and ("INFO", "RECUPERADO") in conect,
           "eventos internos CONECTIVIDAD: %s" % conect)
        ok(all(e["msg_id"].startswith("srv-") for e in evs if e["event"] == "CONECTIVIDAD"), "msg_id srv-<n>")
        adm.cerrar()
    finally:
        nodo.senal(signal.SIGCONT)
        nodo.terminar()


@prueba
def integ_nodo_muere_queda_desconectado_y_al_volver_conserva_historial(ctx):
    srv = ctx.nuevo("integ-caida-nodo")
    n = lanzar_nodo(srv.puerto, "nodo-28", "nodo_red.py")
    n2 = None
    try:
        adm = login(srv.puerto)[0]
        espera_estado(adm, "nodo-28", con_seq(4))
        n.matar()                                        # caída abrupta, sin BYE
        espera_estado(adm, "nodo-28", lambda s: s["state"] == "DESCONECTADO", 8)
        n2 = lanzar_nodo(srv.puerto, "nodo-28", "nodo_red.py")
        espera_estado(adm, "nodo-28", lambda s: s["state"] == "ACTIVO" and con_seq(1)(s), 12)
        h = items(srv.puerto, ADMIN, "historial nodo-28 10")
        ok(len(h) >= 5, "el historial anterior se conservó: %d muestras" % len(h))
        adm.cerrar()
    finally:
        n.matar()
        if n2:
            n2.terminar()


@prueba
def integ_cliente_real_login_malo_permisos_y_errores(ctx):
    srv = ctx.nuevo("integ-cliente-errores")
    for cred, code, reason in [((ADMIN[0], CLAVE_MALA), "401", "CREDENCIALES"),
                               (("noexiste", "clave-lo-que-sea1"), "401", "CREDENCIALES"),
                               (SINROL, "403", "ROL")]:
        r = cliente(srv.puerto, cred, "lista")
        eq(r.rc, 2, "login rechazado -> código 2 (%s)" % (cred,))
        eq(error_servidor(r)[:2], (code, reason), "motivo del rechazo")
        ok("Traceback" not in r.stderr, "sin traza de Python: %s" % r.stderr[-300:])
    r = cliente(srv.puerto, (ADMIN[0], "clave con espacios"), "lista")
    eq(r.rc, 2, "clave con caracteres no permitidos se rechaza en el cliente")
    for cmd, code, reason, field in [("estado nodo-99", "404", "NODO", None),
                                     ("historial nodo-01 50", "422", "VALOR", "n"),
                                     ("eventos 5 nodo-99", "404", "NODO", None)]:
        r = cliente(srv.puerto, ADMIN, cmd)
        eq(r.rc, 3, "ERROR del servidor -> código 3 (%s)" % cmd)
        eq(error_servidor(r), (code, reason, field), cmd)
    r = cliente(srv.puerto, ADMIN, "historial nodo-01 abc")
    eq(r.rc, 2, "n no numérico se rechaza antes de enviar")
    r = cliente(srv.puerto, ADMIN, "bailar")
    eq(r.rc, 2, "comando desconocido")
    for secreto in (CLAVE_MALA, ADMIN[1]):
        ok(secreto not in srv.texto_log(), "el log del servidor no contiene claves")
    ok("password=***" in srv.texto_log(), "el LOGIN aparece con la clave enmascarada")


@prueba
def integ_resolucion_fallida_y_servidor_ausente_no_matan_a_los_programas(ctx):
    puerto = puerto_libre()                               # nadie escucha aquí
    for host, esperado in (("no-existe.invalid", "DNS"), ("localhost", "conexión")):
        t0 = time.time()
        r = cliente(puerto, ADMIN, "lista", host=host, extra=["--reintentos", "1", "--backoff-max", "1"])
        eq(r.rc, 4, "cliente sin servidor -> código 4 (%s)" % host)
        ok(esperado in r.stderr and "Traceback" not in r.stderr, "mensaje claro (%s): %s" % (host, r.stderr[-300:]))
        ok(time.time() - t0 < 30, "el cliente se rindió en tiempo razonable")
        n = lanzar_nodo(puerto, "nodo-29", "nodo_sensor.py", host=host, backoff_max=1)
        try:
            ok(esperar(lambda: n.err().count("estado=RESOLVIENDO") >= 3, 15, 0.2),
               "el nodo reintenta sin parar (%s): %s" % (host, n.err()[-400:]))
            ok(n.vivo(), "el nodo sigue vivo con %s" % host)
            ok(esperado.upper()[:3] in n.err().upper(), "el nodo registra el motivo (%s)" % host)
        finally:
            eq(n.terminar(), 0, "el nodo termina limpio con SIGTERM aun sin servidor")
        ok("Traceback" not in n.err(), "el nodo no lanza excepciones: %s" % n.err()[-300:])
    n = Proc(["python3", os.path.join(NODOS_DIR, "nodo_sensor.py"),
              "--servidor", "localhost", "--puerto", str(puerto), "--id", "nodo-29", "--period", "99"],
             dict(os.environ, MCD_NODO_SECRET="clave-nodo-29"), "nodo-args")
    n.p.wait(10)
    eq(n.p.returncode, 2, "argumentos inválidos -> código 2")
    ok("Traceback" not in n.err(), "error de uso sin traza")


@prueba
def integ_servidor_cae_y_vuelve_nodo_y_cliente_se_recuperan(ctx):
    srv = ctx.nuevo("integ-caida-servidor")
    nodo = lanzar_nodo(srv.puerto, "nodo-25", "nodo_sensor.py", period=1)
    panel = Proc(["python3", CLIENTE, "--servidor", "localhost", "--puerto", str(srv.puerto),
                  "--usuario", "admin1", "--ciclos", "60", "--intervalo", "1",
                  "--backoff-max", "2", "--comando", "panel"],
                 dict(os.environ, MCD_PASSWORD=ADMIN[1]), "panel")

    def activo(desde=0):
        return re.search(r"^nodo-25\s+ACTIVO\b", panel.out()[desde:], re.M) is not None
    try:
        ok(esperar(activo, 20, 0.3), "el panel mostró al nodo activo")
        eq(srv.detener(), 0, "el servidor termina con SIGTERM")
        ok(esperar(lambda: "sin conexión" in panel.err(), 15, 0.3),
           "el cliente avisó que perdió el servidor: %s" % panel.err()[-300:])
        ok(esperar(lambda: nodo.err().count("estado=RESOLVIENDO") >= 3, 15, 0.3), "el nodo reintenta")
        ok(nodo.vivo() and panel.vivo(), "ni el nodo ni el cliente terminaron")
        corte = len(panel.out())
        s2 = Servidor(ctx.binario, ctx.ldap.puerto, None, "integ-reinicio")
        s2.puerto = srv.puerto                           # vuelve en el mismo puerto
        ctx.servidores.append(s2)
        s2.iniciar()
        ok(esperar(lambda: activo(corte), 30, 0.3),
           "tras volver el servidor, el cliente y el nodo se reconectaron: %s | %s"
           % (panel.err()[-200:], nodo.err()[-300:]))
        ok("Traceback" not in nodo.err() + panel.err(), "sin excepciones sin manejar")
    finally:
        nodo.terminar()
        eq(panel.terminar(), 0, "el cliente cierra limpio con SIGTERM")
