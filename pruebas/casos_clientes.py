"""Pruebas de clientes de administracion y de formato de mensajes: login,
perfiles, consultas, errores de gramatica y encuadre TCP (4.3, 5, 6, 7.5)."""
import time

from mcdlib import (ADMIN, CLAVE_INCORRECTA, OPERADOR, SINROL, ClienteTCP, eq,
                    error, login, msg, ok, parsear, prueba, registrar_nodo, status)


@prueba
def login_correcto_con_perfiles(ctx):
    c = ClienteTCP(ctx.puerto)
    t, r = c.pedir("LOGIN", user=ADMIN[0], password=ADMIN[1])
    eq((t, r["req"], r["user"], r["role"]), ("LOGIN_OK", "1", "admin1", "admin"))
    c.cerrar()
    c, role = login(ctx.puerto, OPERADOR)
    eq(role, "operador")
    c.cerrar()


@prueba
def login_incorrecto(ctx):
    c = ClienteTCP(ctx.puerto)
    t, r = c.pedir("LOGIN", user="admin1", password=CLAVE_INCORRECTA)
    error(t, r, 401, "CREDENCIALES", req=1)
    t, r = c.pedir("LOGIN", user="usuario-inexistente", password="clave-cualquiera")
    error(t, r, 401, "CREDENCIALES", req=2)
    t, r = c.pedir("LOGIN", user="admin1", password=CLAVE_INCORRECTA)   # tercer intento
    error(t, r, 401, "CREDENCIALES", req=3)
    ok(c.cerrado(), "al tercer intento fallido el servidor cierra")
    c = ClienteTCP(ctx.puerto)
    t, r = c.pedir("LOGIN", user=SINROL[0], password=SINROL[1])   # clave buena, sin grupo
    error(t, r, 403, "ROL", req=1)
    t, r = c.pedir("LOGIN", user="admin1", password=ADMIN[1])      # y aun puede reintentar
    eq(t, "LOGIN_OK")
    c.cerrar()


@prueba
def consulta_sin_login(ctx):
    c = ClienteTCP(ctx.puerto)
    t, r = c.pedir("LIST")
    error(t, r, 401, "SIN_SESION", req=1)
    t, r = c.pedir("STATUS", node_id="nodo-01")
    error(t, r, 401, "SIN_SESION", req=2)
    t, r = c.pedir("EVENT", node_id="nodo-01", msg_id="1791122400-1", ts=1, level="INFO",
                   event="ALARMA")
    error(t, r, 401, "SIN_SESION", req=3)
    c.enviar(msg("TELEMETRY", node_id="nodo-01", session="0123456789abcdef", seq=1, ts=1,
                 cpu="1.0", temp="1.0", bat="1", opstate="OK", uptime=1))
    t, r = c.respuesta()
    error(t, r, 409, "TRANSPORTE", req=0)
    c.cerrar()


@prueba
def permiso_segun_perfil_y_estado(ctx):
    op, _ = login(ctx.puerto, OPERADOR)
    t, r, items = op.consulta("LIST")
    eq(t, "RESPONSE")
    t, r, items = op.consulta("EVENTS", n=5)
    error(t, r, 403, "ROL", req=3)
    t, r = op.pedir("LOGIN", user=ADMIN[0], password=ADMIN[1])
    error(t, r, 409, "ESTADO")
    op.cerrar()
    adm = ctx.admin()
    t, r, items = adm.consulta("EVENTS", n=5)
    eq(t, "RESPONSE")
    t, r = adm.pedir("EVENT", node_id="nodo-01", msg_id="1791122400-1", ts=1, level="INFO",
                     event="ALARMA")
    error(t, r, 403, "ROL")
    t, r = adm.pedir("REGISTER", node_id="nodo-01", secret="clave-nodo-01", kind="IOT", period=5)
    error(t, r, 409, "ESTADO")
    adm.cerrar()
    n, _ = registrar_nodo(ctx.puerto, "nodo-25")
    t, r = n.pedir("LIST")
    error(t, r, 403, "ROL", req=2)
    t, r = n.pedir("EVENTS", n=5)
    error(t, r, 403, "ROL", req=3)
    t, r = n.pedir("REGISTER", node_id="nodo-25", secret="clave-nodo-25", kind="IOT", period=5)
    error(t, r, 409, "ESTADO")
    n.cerrar()


@prueba
def consultas_list_status_history_events(ctx):
    a, _ = registrar_nodo(ctx.puerto, "nodo-26", kind="RED", period=7)
    b, _ = registrar_nodo(ctx.puerto, "nodo-27", kind="IOT")
    adm = ctx.admin()
    t, r, items = adm.consulta("LIST")
    ids = [i["node_id"] for i in items]
    eq(ids, sorted(ids), "LIST ordenado por node_id")
    eq(r["items"], str(len(items)))
    eq([i["idx"] for i in items], [str(k) for k in range(1, len(items) + 1)], "idx 1..items")
    por = {i["node_id"]: i for i in items}
    eq((por["nodo-26"]["kind"], por["nodo-26"]["state"]), ("RED", "ACTIVO"))
    eq(por["nodo-27"]["kind"], "IOT")
    s = status(adm, "nodo-26")
    eq((s["state"], s["seq"], s["lost"], s["dups"], s["ooo"]), ("ACTIVO", "NA", "0", "0", "0"))
    t, r, items = adm.consulta("HISTORY", node_id="nodo-26", n=3)
    eq((t, r["items"], items), ("RESPONSE", "0", []), "sin muestras: items=0 y ningun ITEM")
    for k in range(1, 4):
        a.pedir("EVENT", node_id="nodo-26", msg_id="1791122401-%d" % k, ts=k, level="INFO",
                event="CAMBIO_ESTADO", value="OK")
    t, r, items = adm.consulta("EVENTS", n=2, node_id="nodo-26")
    eq([i["msg_id"] for i in items], ["1791122401-3", "1791122401-2"], "n=2, mas reciente primero")
    t, r, items = adm.consulta("EVENTS", n=20)
    ok(len(items) >= 3, "EVENTS sin filtro incluye eventos de varios nodos")
    a.cerrar()
    b.cerrar()
    adm.cerrar()


@prueba
def nodo_inexistente(ctx):
    adm = ctx.admin()
    for tipo, campos in [("STATUS", {}), ("HISTORY", {"n": 5}), ("EVENTS", {"n": 5})]:
        t, r, _ = adm.consulta(tipo, node_id="nodo-98", **campos)
        error(t, r, 404, "NODO")
    adm.cerrar()


@prueba
def linea_malformada_version_y_tipo(ctx):
    c = ClienteTCP(ctx.puerto)
    for linea, code, reason in [
            ("MCD/1.0 LIST req=2\n", 400, "FORMATO"),          # separador equivocado
            ("MCD/1.0|LIST|req=\n", 400, "FORMATO"),           # valor vacio
            ("MCD/1.0|list|req=2\n", 400, "FORMATO"),          # tipo en minusculas
            ("hola\n", 400, "FORMATO")]:
        c.enviar(linea)
        t, r = c.respuesta()
        error(t, r, code, reason, req=0)
    t, r = c.pedir("LIST")                                     # la conexion sigue viva
    error(t, r, 401, "SIN_SESION")
    c.cerrar()
    c = ClienteTCP(ctx.puerto)
    for linea, code, reason in [
            ("MCD/2.0|LIST|req=2\n", 400, "VERSION"),
            ("MCD/1.0|PING|req=2\n", 400, "TIPO"),
            ("MCD/1.0|ACK|req=2|node_id=nodo-01|msg_id=1-1|dup=0\n", 400, "TIPO"),
            ("MCD/1.0|ERROR|req=2|code=400|reason=FORMATO\n", 400, "TIPO")]:
        c.enviar(linea)
        t, r = c.respuesta()
        error(t, r, code, reason, req=0)
    c.enviar(b"MCD/1.0|LIST|req=1|caf\xc3\xa9=1\n")            # byte no ASCII
    t, r = c.respuesta()
    error(t, r, 400, "FORMATO")
    c.cerrar()
    c = ClienteTCP(ctx.puerto)
    c.enviar("MCD/1.0|LIST|" + "|".join("k%d=1" % i for i in range(17)) + "\n")   # 17 campos
    error(*c.respuesta(), 400, "FORMATO")
    c.cerrar()


@prueba
def errores_422_y_clave_repetida(ctx):
    c, _ = login(ctx.puerto, ADMIN)
    c.enviar("MCD/1.0|STATUS|req=5|node_id=nodo-01|node_id=nodo-02\n")
    error(*c.respuesta(), 422, "CAMPO_REPETIDO", req=5, field="node_id")
    c.enviar("MCD/1.0|STATUS|req=6\n")
    error(*c.respuesta(), 422, "FALTA_CAMPO", req=6, field="node_id")
    c.enviar("MCD/1.0|STATUS|req=7|node_id=nodo-01|color=rojo\n")
    error(*c.respuesta(), 422, "CAMPO_DESCONOCIDO", req=7, field="color")
    c.enviar("MCD/1.0|HISTORY|req=8|node_id=nodo-01|n=50\n")
    error(*c.respuesta(), 422, "VALOR", req=8, field="n")
    c.enviar("MCD/1.0|LIST|req=0\n")                  # req invalido: el ERROR lleva req=0
    error(*c.respuesta(), 422, "VALOR", req=0, field="req")
    c.cerrar()


@prueba
def cinco_errores_de_formato_seguidos_cierran(ctx):
    c = ClienteTCP(ctx.puerto)
    for _ in range(5):
        c.enviar("basura\n")
        error(*c.respuesta(), 400, "FORMATO")
    ok(c.cerrado(), "tras 5 errores seguidos el servidor cierra")
    c = ClienteTCP(ctx.puerto)         # un acierto en medio reinicia la cuenta
    for _ in range(4):
        c.enviar("basura\n")
        c.respuesta()
    c.pedir("LIST")
    for _ in range(4):
        c.enviar("basura\n")
        error(*c.respuesta(), 400, "FORMATO")
    t, r = c.pedir("LIST")
    error(t, r, 401, "SIN_SESION")
    c.cerrar()


@prueba
def linea_mayor_de_512_bytes(ctx):
    c = ClienteTCP(ctx.puerto)
    c.enviar(b"A" * 600)                       # 600 bytes sin LF
    error(*c.respuesta(), 413, "TAMANO", req=0)
    ok(c.cerrado(), "tras 413 el servidor cierra")
    c = ClienteTCP(ctx.puerto)
    c.enviar(b"A" * 599 + b"\n")               # 600 bytes con LF
    error(*c.respuesta(), 413, "TAMANO", req=0)
    ok(c.cerrado(), "tras 413 el servidor cierra")
    c = ClienteTCP(ctx.puerto)
    c.enviar(b"A" * 511 + b"\n")               # 512 bytes con LF: cabe, pero no es un mensaje
    error(*c.respuesta(), 400, "FORMATO", req=0)
    c.enviar(b"A" * 512 + b"\n")               # 513 bytes con LF: no cabe
    error(*c.respuesta(), 413, "TAMANO", req=0)
    ok(c.cerrado(), "tras 413 el servidor cierra")


@prueba
def linea_partida_en_varios_send(ctx):
    c = ClienteTCP(ctx.puerto)
    c.s.setsockopt(6, 1, 1)   # TCP_NODELAY: cada send sale como segmento propio
    partes = ["MCD/1.0|REG", "ISTER|req=1|node_id=nod", "o-28|secret=clave-nodo-28|kind=I",
              "OT|period=5", "\n"]
    for p in partes:
        c.enviar(p)
        time.sleep(0.15)
    t, r = c.respuesta()
    eq((t, r["req"], r["node_id"]), ("REGISTER_OK", "1", "nodo-28"))
    c.cerrar()


@prueba
def varias_lineas_en_un_send(ctx):
    c = ClienteTCP(ctx.puerto)
    c.enviar(msg("LOGIN", req=1, user=ADMIN[0], password=ADMIN[1]) + msg("LIST", req=2) +
             msg("STATUS", req=3, node_id="nodo-98") + msg("BYE", req=4))
    t, r = c.respuesta()
    eq((t, r["role"]), ("LOGIN_OK", "admin"))
    t, r = c.respuesta()
    eq((t, r["req"], r["op"]), ("RESPONSE", "2", "LIST"))
    for _ in range(int(r["items"])):
        eq(c.respuesta()[0], "ITEM")
    error(*c.respuesta(), 404, "NODO", req=3)
    t, r = c.respuesta()
    eq((t, r["req"]), ("BYE", "4"))
    ok(c.cerrado())


@prueba
def lineas_vacias_y_crlf_se_toleran(ctx):
    c, _ = login(ctx.puerto, OPERADOR)
    c.enviar("\n\r\n\n")                                  # lineas vacias: sin respuesta
    c.enviar("MCD/1.0|LIST|req=9\r\n")                   # CRLF solo para pruebas manuales
    t, r = c.respuesta()
    eq((t, r["req"], r["op"]), ("RESPONSE", "9", "LIST"))
    for _ in range(int(r["items"])):
        c.respuesta()
    c.enviar("\n")
    ok(c.linea(0.5) is None, "una linea vacia no produce respuesta")
    c.cerrar()


@prueba
def cliente_lento_no_bloquea_a_los_demas(ctx):
    lento = ClienteTCP(ctx.puerto)
    lento.enviar("MCD/1.0|LOGIN|req=1|user=admin1|pass")   # media linea y se queda callado
    mudo = ClienteTCP(ctx.puerto)                           # conexion que nunca envia nada
    t0 = time.time()
    adm, role = login(ctx.puerto, ADMIN)
    eq(adm.consulta("LIST")[0], "RESPONSE")
    ok(time.time() - t0 < 2.0, "el servidor atiende a otros mientras hay clientes lentos")
    lento.enviar("word=%s\n" % ADMIN[1])                    # el cliente lento termina su linea
    t, r = lento.respuesta()
    eq((t, r["role"]), ("LOGIN_OK", "admin"))
    for c in (lento, mudo, adm):
        c.cerrar()
