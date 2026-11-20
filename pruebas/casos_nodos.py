"""Pruebas del lado de los nodos: registro, telemetria, eventos, watchdog y
desconexiones (secciones 7.2 a 7.8 de MCD-1.0)."""
import re
import socket
import struct
import time

from mcdlib import (CLAVE_INCORRECTA, ClienteTCP, ClienteUDP, clave_nodo, eq,
                    error, esperar_status, ok, parsear, prueba, registrar_nodo,
                    resolver, status, telemetria, msg)


@prueba
def registro_valido(ctx):
    c = ClienteTCP(ctx.puerto)
    t, r = c.pedir("REGISTER", node_id="nodo-01", secret=clave_nodo("nodo-01"),
                   kind="SENSOR", period=5)
    eq(t, "REGISTER_OK")
    eq((r["req"], r["node_id"], r["period"]), ("1", "nodo-01", "5"))
    ok(re.fullmatch("[0-9a-f]{16}", r["session"]), "session de 16 hex: %r" % r["session"])
    adm = ctx.admin()
    eq(status(adm, "nodo-01")["state"], "ACTIVO")
    c.cerrar()
    adm.cerrar()


@prueba
def registro_invalido(ctx):
    c = ClienteTCP(ctx.puerto)
    t, r = c.pedir("REGISTER", node_id="nodo-02", secret=CLAVE_INCORRECTA, kind="IOT", period=5)
    error(t, r, 401, "CREDENCIALES", req=1)
    ok(c.cerrado(), "tras 401 CREDENCIALES el servidor debe cerrar")
    c = ClienteTCP(ctx.puerto)
    t, r = c.pedir("REGISTER", node_id="nodo-77", secret="clave-nodo-77", kind="IOT", period=5)
    error(t, r, 401, "CREDENCIALES")   # el nodo no existe en LDAP
    c.cerrar()
    c = ClienteTCP(ctx.puerto)
    sec = clave_nodo("nodo-02")
    for campos, field, reason in [
            (dict(node_id="nodo-02", secret="corta", kind="IOT", period=5), "secret", "VALOR"),
            (dict(node_id="nodo-02", secret=sec, kind="XX", period=5), "kind", "VALOR"),
            (dict(node_id="nodo-02", secret=sec, kind="IOT", period=61), "period", "VALOR"),
            (dict(node_id="Nodo-02", secret=sec, kind="IOT", period=5), "node_id", "VALOR"),
            (dict(node_id="nodo-02", secret=sec, kind="IOT"), "period", "FALTA_CAMPO")]:
        t, r = c.pedir("REGISTER", **campos)
        error(t, r, 422, reason, field=field)
    c.cerrar()


@prueba
def telemetria_y_reflejo_en_status_history(ctx):
    n, sess = registrar_nodo(ctx.puerto, "nodo-02")
    adm = ctx.admin()
    s = status(adm, "nodo-02")   # antes de la primera telemetria
    eq((s["seq"], s["cpu"], s["temp"], s["bat"], s["opstate"], s["uptime"]),
       ("NA",) * 6, "campos NA sin telemetria")
    u = ClienteUDP(ctx.puerto)
    for i in range(1, 7):
        u.enviar(telemetria("nodo-02", sess, i, cpu="%d.5" % (10 + i), uptime=100 + i))
    s = esperar_status(adm, "nodo-02", lambda x: x["seq"] == "6")
    eq((s["state"], s["cpu"], s["uptime"], s["lost"], s["dups"], s["ooo"]),
       ("ACTIVO", "16.5", "106", "0", "0", "0"))
    t, r, items = adm.consulta("HISTORY", node_id="nodo-02", n=5)
    eq([i["seq"] for i in items], ["6", "5", "4", "3", "2"], "HISTORY n=5 mas reciente primero")
    eq(items[0]["cpu"], "16.5")
    t, r, items = adm.consulta("HISTORY", node_id="nodo-02", n=10)
    eq(len(items), 6, "HISTORY n=10 devuelve las 6 muestras que hay")
    u.cerrar()
    n.cerrar()
    adm.cerrar()


@prueba
def historial_circular_maximo_10(ctx):
    n, sess = registrar_nodo(ctx.puerto, "nodo-17")
    u = ClienteUDP(ctx.puerto)
    for i in range(1, 13):
        u.enviar(telemetria("nodo-17", sess, i))
    adm = ctx.admin()
    esperar_status(adm, "nodo-17", lambda x: x["seq"] == "12")
    t, r, items = adm.consulta("HISTORY", node_id="nodo-17", n=10)
    eq([i["seq"] for i in items], [str(k) for k in range(12, 2, -1)], "solo las 10 ultimas")
    u.cerrar()
    n.cerrar()
    adm.cerrar()


@prueba
def seq_duplicado_y_atrasado(ctx):
    n, sess = registrar_nodo(ctx.puerto, "nodo-03")
    u = ClienteUDP(ctx.puerto)
    for seq in (1, 2, 3, 3, 2, 5):    # 3 duplicado, 2 atrasado, salto 4 -> 1 perdido
        u.enviar(telemetria("nodo-03", sess, seq))
        time.sleep(0.05)
    adm = ctx.admin()
    s = esperar_status(adm, "nodo-03", lambda x: x["seq"] == "5" and x["dups"] == "1")
    eq((s["dups"], s["ooo"], s["lost"]), ("1", "1", "1"), "dups/ooo/lost")
    t, r, items = adm.consulta("HISTORY", node_id="nodo-03", n=10)
    eq([i["seq"] for i in items], ["5", "3", "2", "1"], "descartados no entran al historial")
    u.cerrar()
    n.cerrar()
    adm.cerrar()


@prueba
def telemetria_con_sesion_desconocida(ctx):
    u = ClienteUDP(ctx.puerto)
    u.enviar(telemetria("nodo-99", "0123456789abcdef", 1))
    t, r = parsear(u.recibir(2.0) + "\n")
    error(t, r, 404, "NODO", req=0)
    u.enviar(telemetria("nodo-99", "0123456789abcdef", 2))   # mismo origen: limite 1 cada 5 s
    eq(u.recibir(1.0), None, "segundo ERROR UDP del mismo origen debe omitirse")
    n, sess = registrar_nodo(ctx.puerto, "nodo-19")
    u2 = ClienteUDP(ctx.puerto)
    u2.enviar(telemetria("nodo-19", "ffffffffffffffff", 1))
    t, r = parsear(u2.recibir(2.0) + "\n")
    error(t, r, 404, "SESION", req=0)
    adm = ctx.admin()
    eq(status(adm, "nodo-19")["seq"], "NA", "la telemetria rechazada no actualiza el nodo")
    u.cerrar()
    u2.cerrar()
    n.cerrar()
    adm.cerrar()


@prueba
def udp_invalido_se_descarta_sin_respuesta(ctx):
    n, sess = registrar_nodo(ctx.puerto, "nodo-18")
    adm = ctx.admin()
    bueno = telemetria("nodo-18", sess, 1).encode()
    malos = [b"A" * 600 + b"\n",                          # mas de 512 bytes
             b"basura sin formato\n",
             bueno.rstrip(b"\n"),                          # sin LF final
             bueno * 2,                                    # dos mensajes
             msg("LIST", req=1).encode(),                  # tipo no permitido por UDP
             telemetria("nodo-18", sess, 1, cpu="150.0").encode(),   # fuera de rango
             telemetria("nodo-18", sess, 0).encode()]      # seq invalido
    u = ClienteUDP(ctx.puerto)
    for d in malos:
        u.enviar(d)
        eq(u.recibir(0.3), None, "no se responde a un datagrama invalido")
    time.sleep(0.3)
    eq(status(adm, "nodo-18")["seq"], "NA", "ningun datagrama invalido se acepto")
    u.enviar(bueno)
    esperar_status(adm, "nodo-18", lambda x: x["seq"] == "1")
    u.cerrar()
    n.cerrar()
    adm.cerrar()


@prueba
def evento_y_ack(ctx):
    n, sess = registrar_nodo(ctx.puerto, "nodo-04")
    t, r = n.pedir("EVENT", node_id="nodo-04", msg_id="1791122400-1", ts=1791126138,
                   level="CRITICO", event="UMBRAL_TEMP", value="85.2")
    eq(t, "ACK")
    eq((r["req"], r["node_id"], r["msg_id"], r["dup"]), ("2", "nodo-04", "1791122400-1", "0"))
    adm = ctx.admin()
    t, r, items = adm.consulta("EVENTS", n=20, node_id="nodo-04")
    eq(len(items), 1)
    eq((items[0]["msg_id"], items[0]["level"], items[0]["event"], items[0]["value"],
        items[0]["ts"]), ("1791122400-1", "CRITICO", "UMBRAL_TEMP", "85.2", "1791126138"))
    t, r = n.pedir("EVENT", node_id="nodo-04", msg_id="1791122400-2", ts=1791126139,
                   level="INFO", event="ALARMA")   # sin value
    eq(t, "ACK")
    t, r, items = adm.consulta("EVENTS", n=20, node_id="nodo-04")
    eq([i["msg_id"] for i in items], ["1791122400-2", "1791122400-1"], "mas reciente primero")
    ok("value" not in items[0], "evento sin value no lleva value")
    n.cerrar()
    adm.cerrar()


@prueba
def evento_reenvio_mismo_msg_id_no_duplica(ctx):
    n, _ = registrar_nodo(ctx.puerto, "nodo-20")
    ev = dict(node_id="nodo-20", msg_id="1791122400-7", ts=1791126146, level="CRITICO",
              event="FALLA", value="FALLA")
    eq(n.pedir("EVENT", **ev)[1]["dup"], "0")
    t, r = n.pedir("EVENT", **ev)
    eq((t, r["dup"], r["msg_id"]), ("ACK", "1", "1791122400-7"), "reenvio -> ACK dup=1")
    n.pedir("BYE")
    n.cerrar()
    n2, _ = registrar_nodo(ctx.puerto, "nodo-20")   # reconexion y reenvio del mismo msg_id
    eq(n2.pedir("EVENT", **ev)[1]["dup"], "1", "tras reconectar sigue sin duplicarse")
    adm = ctx.admin()
    t, r, items = adm.consulta("EVENTS", n=20, node_id="nodo-20")
    eq(len(items), 1, "el evento se guardo una sola vez")
    n2.cerrar()
    adm.cerrar()


@prueba
def evento_de_nodo_ajeno(ctx):
    n, _ = registrar_nodo(ctx.puerto, "nodo-21")
    t, r = n.pedir("EVENT", node_id="nodo-04", msg_id="1791122400-9", ts=1, level="INFO",
                   event="ALARMA")
    error(t, r, 403, "NODO_AJENO", req=2)
    t, r = n.pedir("EVENT", node_id="nodo-21", msg_id="srv-9", ts=1, level="INFO", event="ALARMA")
    error(t, r, 422, "VALOR", field="msg_id")
    n.cerrar()


@prueba
def watchdog_sin_reporte_y_recuperacion(ctx):
    n, sess = registrar_nodo(ctx.puerto, "nodo-05", period=1)
    u = ClienteUDP(ctx.puerto)
    u.enviar(telemetria("nodo-05", sess, 1))
    adm = ctx.admin()
    esperar_status(adm, "nodo-05", lambda x: x["seq"] == "1")
    eq(status(adm, "nodo-05")["state"], "ACTIVO")
    esperar_status(adm, "nodo-05", lambda x: x["state"] == "SIN_REPORTE", plazo=9.0)
    t, r, items = adm.consulta("EVENTS", n=5, node_id="nodo-05")
    e = items[0]
    eq((e["event"], e["value"], e["level"]), ("CONECTIVIDAD", "SIN_REPORTE", "ADVERTENCIA"))
    ok(re.fullmatch("srv-[0-9]+", e["msg_id"]), "msg_id de evento interno: %s" % e["msg_id"])
    u.enviar(telemetria("nodo-05", sess, 2))
    esperar_status(adm, "nodo-05", lambda x: x["state"] == "ACTIVO")
    t, r, items = adm.consulta("EVENTS", n=5, node_id="nodo-05")
    eq((items[0]["event"], items[0]["value"], items[0]["level"]),
       ("CONECTIVIDAD", "RECUPERADO", "INFO"))
    u.cerrar()
    n.cerrar()
    adm.cerrar()


@prueba
def bye_desconecta_e_invalida_sesion(ctx):
    n, sess = registrar_nodo(ctx.puerto, "nodo-22")
    t, r = n.pedir("BYE")
    eq((t, r["req"]), ("BYE", "2"))
    ok(n.cerrado(), "el servidor cierra tras BYE")
    adm = ctx.admin()
    eq(status(adm, "nodo-22")["state"], "DESCONECTADO")
    u = ClienteUDP(ctx.puerto)
    u.enviar(telemetria("nodo-22", sess, 1))
    t, r = parsear(u.recibir(2.0) + "\n")
    error(t, r, 404, "SESION")
    n2, sess2 = registrar_nodo(ctx.puerto, "nodo-22")
    ok(sess2 != sess, "sesion nueva tras volver a registrarse")
    eq(status(adm, "nodo-22")["state"], "ACTIVO")
    u.cerrar()
    n2.cerrar()
    adm.cerrar()


@prueba
def nuevo_registro_reemplaza_la_conexion_anterior(ctx):
    a, sess_a = registrar_nodo(ctx.puerto, "nodo-23")
    b, sess_b = registrar_nodo(ctx.puerto, "nodo-23")
    ok(sess_a != sess_b, "sesion nueva")
    ok(a.cerrado(), "la conexion anterior del nodo debe cerrarse")
    adm = ctx.admin()
    time.sleep(0.3)
    eq(status(adm, "nodo-23")["state"], "ACTIVO", "cerrar la conexion reemplazada no desconecta")
    u = ClienteUDP(ctx.puerto)
    u.enviar(telemetria("nodo-23", sess_a, 1))   # sesion vieja: ya no vale
    t, r = parsear(u.recibir(2.0) + "\n")
    error(t, r, 404, "SESION")
    u.cerrar()
    b.cerrar()
    adm.cerrar()


@prueba
def desconexion_abrupta_en_mitad_de_linea(ctx):
    s = socket.create_connection(resolver("localhost", ctx.puerto, socket.SOCK_STREAM), 5)
    s.sendall(b"MCD/1.0|REGISTER|req=1|node_id=nodo-24|secret=cla")
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()   # RST en mitad de la linea
    time.sleep(0.3)
    ok(ctx.srv.vivo(), "el servidor debe seguir vivo")
    n, _ = registrar_nodo(ctx.puerto, "nodo-24")      # y sigue atendiendo
    n.s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    n.cerrar()   # nodo registrado que se cae sin BYE
    adm = ctx.admin()
    esperar_status(adm, "nodo-24", lambda x: x["state"] == "DESCONECTADO")
    adm.cerrar()
