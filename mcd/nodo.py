"""Nodo MCD/1.0: registro, telemetría UDP, eventos con reintento y reconexión.

Implementa la máquina de estados de la sección 9.1 con un solo hilo y
`select`: el mismo ciclo envía la telemetría cada `period`, manda un evento a
la vez, espera su ACK y vigila los datagramas de error que el servidor
pueda devolver por UDP.

  INICIO -> RESOLVIENDO -> CONECTANDO -> REGISTRANDO -> OPERANDO <-> ESPERANDO_ACK
                 ^______________ ESPERA_REINTENTO (1,2,4,8,16,30 s) ____|
"""
import argparse
import os
import random
import select
import signal
import socket
import sys
import time
from collections import deque, namedtuple

from . import proto
from .proto import ErrorConexion, ErrorFormato, ErrorResolucion, LectorLineas, construir

Evento = namedtuple("Evento", "msg_id ts level event value")

# Resultados de una sesión (conexión TCP completa) del nodo.
FIN, REINTENTO, INMEDIATO = "fin", "reintento", "inmediato"


class FalloSesion(Exception):
    """Termina la sesión actual. `inmediato` salta la espera de reintento
    (caso del ERROR 404 por UDP, 7.9)."""

    def __init__(self, motivo, inmediato=False):
        Exception.__init__(self, motivo)
        self.inmediato = inmediato


class Nodo:
    def __init__(self, host, puerto, node_id, secret, kind, period, simulador, log,
                 backoff_max=30, t_resp=5.0, t_ack=5.0, cola_max=32):
        self.host, self.puerto = host, puerto
        self.node_id, self.secret, self.kind, self.period = node_id, secret, kind, period
        self.sim, self.log = simulador, log
        self.backoff_max, self.t_resp, self.t_ack, self.cola_max = backoff_max, t_resp, t_ack, cola_max
        self.detener = _Parada()
        self.arranque = int(time.time())        # primera parte de cada msg_id (7.4)
        self.contador = 0
        self.pendientes = deque()               # eventos sin ACK, el más viejo primero
        self.en_vuelo = None                    # msg_id del EVENT esperando ACK
        self._req_vuelo = 0                     # req con que se envió ese EVENT
        self.t0 = time.monotonic()
        self._req = 0
        self._lector = LectorLineas()
        self._lineas = deque()
        self._inmediatos = []                   # instantes de los últimos reregistros sin espera

    # ------------------------------------------------------------ eventos

    def encolar_evento(self, level, event, value=None):
        """Asigna `msg_id` y guarda el evento hasta recibir su ACK (7.4, pasos 1-2)."""
        self.contador += 1
        ev = Evento("%d-%d" % (self.arranque, self.contador), int(time.time()),
                    level, event, value)
        if len(self.pendientes) >= self.cola_max:
            # Se descarta el más antiguo; el que está en vuelo no, porque ya se está entregando.
            i = 1 if self.en_vuelo == self.pendientes[0].msg_id else 0
            viejo = self.pendientes[i]
            del self.pendientes[i]
            self.log.warning("cola de eventos llena (%d): se descarta %s %s",
                             self.cola_max, viejo.msg_id, viejo.event)
        self.pendientes.append(ev)
        self.log.info("evento en cola: msg_id=%s %s %s %s", ev.msg_id, level, event, value or "-")

    # ----------------------------------------------------- ciclo de vida

    def ejecutar(self):
        """Ciclo principal: nunca termina por fallas de DNS, red, LDAP o servidor."""
        espera = proto.Backoff(self.backoff_max)
        while not self.detener.is_set():
            resultado = self._una_sesion(espera)
            if resultado == FIN:
                break
            if resultado == INMEDIATO:
                # Dos reregistros seguidos sin espera son normales; si el servidor sigue sin
                # reconocer la sesión (p. ej. dos procesos con el mismo node_id), se frena la ráfaga.
                ahora = time.monotonic()
                self._inmediatos = [t for t in self._inmediatos if ahora - t < 5.0] + [ahora]
                if len(self._inmediatos) >= 3:
                    resultado = REINTENTO
            if resultado == REINTENTO:
                s = espera.siguiente()
                self.log.info("estado=ESPERA_REINTENTO: reintento en %ds", s)
                self.detener.wait(s)
        self.log.info("nodo terminado")

    def _una_sesion(self, espera):
        self.log.info("estado=RESOLVIENDO: %s:%s", self.host, self.puerto)
        try:
            tcp = proto.conectar_tcp(self.host, self.puerto, self.t_resp)
        except ErrorResolucion as e:
            self.log.error("DNS: %s", e)
            return REINTENTO
        except ErrorConexion as e:
            self.log.error("TCP: %s", e)
            return REINTENTO
        udp = socket.socket(tcp.family, socket.SOCK_DGRAM)
        self._lector, self._lineas, self._req, self.en_vuelo = LectorLineas(), deque(), 0, None
        try:
            self.log.info("estado=REGISTRANDO: conectado a %s", tcp.getpeername()[:2])
            session = self._registrar(tcp)
            espera.reiniciar()
            return self._operar(tcp, udp, session)
        except FalloSesion as f:
            self.log.warning("sesión terminada: %s", f)
            return INMEDIATO if f.inmediato else REINTENTO
        except OSError as e:
            self.log.warning("error de red: %s", e)
            return REINTENTO
        finally:
            tcp.close()
            udp.close()

    # ---------------------------------------------------------- registro

    def _registrar(self, tcp):
        req = self._nuevo_req()
        self._enviar_tcp(tcp, construir("REGISTER", req=req, node_id=self.node_id,
                                        secret=self.secret, kind=self.kind, period=self.period))
        m = self._leer_mensaje(tcp, self.t_resp)
        c = m.campos
        if m.tipo == "REGISTER_OK":
            if (c.get("req") != str(req) or c.get("node_id") != self.node_id
                    or c.get("period") != str(self.period)
                    or not proto.RE_SESSION.fullmatch(c.get("session", ""))):
                raise FalloSesion("REGISTER_OK inválido: %s" % c)
            self.log.info("registrado: node_id=%s period=%s sesión %s…",
                          self.node_id, self.period, c["session"][:4])
            return c["session"]
        if m.tipo == "ERROR":
            raise FalloSesion("registro rechazado: ERROR %s %s" % (c.get("code"), c.get("reason")))
        raise FalloSesion("respuesta inesperada al registro: %s" % m.tipo)

    # ----------------------------------------------------------- operación

    def _operar(self, tcp, udp, session):
        self.log.info("estado=OPERANDO")
        destino = tcp.getpeername()
        seq = 0
        siguiente_tel = time.monotonic()
        vence_ack = None
        while True:
            if self.detener.is_set():
                self._despedir(tcp)
                return FIN
            ahora = time.monotonic()
            if ahora >= siguiente_tel:
                seq += 1
                self._enviar_telemetria(udp, destino, session, seq)
                siguiente_tel += self.period
                if siguiente_tel <= ahora:      # se atrasó (p. ej. proceso detenido): sin ráfagas
                    siguiente_tel = ahora + self.period
            if self.en_vuelo is None and self.pendientes:
                ev = self.pendientes[0]
                req = self._nuevo_req()
                campos = dict(req=req, node_id=self.node_id, msg_id=ev.msg_id, ts=ev.ts,
                              level=ev.level, event=ev.event)
                if ev.value:
                    campos["value"] = ev.value
                self._enviar_tcp(tcp, construir("EVENT", **campos))
                self.en_vuelo, self._req_vuelo = ev.msg_id, req
                vence_ack = ahora + self.t_ack
            if self.en_vuelo is not None and time.monotonic() >= vence_ack:
                raise FalloSesion("vence T_ack (%gs) sin ACK de %s; se reenviará con el mismo "
                                  "msg_id tras reconectar" % (self.t_ack, self.en_vuelo))
            limite = siguiente_tel if self.en_vuelo is None else min(siguiente_tel, vence_ack)
            espera = max(0.0, min(limite - time.monotonic(), 0.5))
            listos, _, _ = select.select([tcp, udp], [], [], espera)
            if udp in listos:
                self._recibir_udp(udp, destino)
            if tcp in listos:
                self._recibir(tcp)
            while self._lineas:
                self._manejar_tcp(self._tomar())

    def _enviar_telemetria(self, udp, destino, session, seq):
        m = self.sim.muestra(time.monotonic() - self.t0)
        bat = m["bat"] if m["bat"] == "NA" else int(m["bat"])
        linea = construir("TELEMETRY", node_id=self.node_id, session=session, seq=seq,
                          ts=int(time.time()), cpu="%.1f" % m["cpu"], temp="%.1f" % m["temp"],
                          bat=bat, opstate=m["opstate"], uptime=int(time.monotonic() - self.t0))
        try:
            udp.sendto(linea.encode("ascii"), destino)
            self.log.info("UDP -> %s", linea.strip())
        except OSError as e:           # UDP no avisa de pérdidas; un error local solo se anota
            self.log.warning("no se pudo enviar la telemetría seq=%d: %s", seq, e)
        for nivel, evento, valor in self.sim.eventos(m):
            self.encolar_evento(nivel, evento, valor)

    def _manejar_tcp(self, m):
        c = m.campos
        if m.tipo == "ACK" and self.en_vuelo is not None:
            if c.get("req") == str(self._req_vuelo) and c.get("msg_id") == self.en_vuelo:
                self.pendientes.popleft()
                self.log.info("ACK de %s (dup=%s)", self.en_vuelo, c.get("dup"))
                self.en_vuelo = None
                return
            raise FalloSesion("ACK que no corresponde al EVENT en vuelo: %s" % c)
        if (m.tipo == "ERROR" and self.en_vuelo is not None
                and c.get("req") == str(self._req_vuelo) and c.get("code") in ("400", "403", "422")):
            # Reenviarlo produciría el mismo error: se descarta (7.4, paso 8).
            ev = self.pendientes.popleft()
            self.log.error("evento %s descartado: ERROR %s %s field=%s",
                           ev.msg_id, c.get("code"), c.get("reason"), c.get("field", "-"))
            self.en_vuelo = None
            return
        if m.tipo == "ERROR":
            raise FalloSesion("ERROR %s %s del servidor" % (c.get("code"), c.get("reason")))
        raise FalloSesion("mensaje inesperado del servidor: %s" % m.tipo)

    def _recibir_udp(self, udp, destino):
        datos, origen = udp.recvfrom(2048)
        if origen[:2] != destino[:2]:
            self.log.warning("datagrama ignorado de %s (no es el servidor)", origen[:2])
            return
        texto = datos.decode("ascii", "replace").strip()
        self.log.info("UDP <- %s", texto)
        try:
            m = proto.parsear(texto)
        except ErrorFormato as e:
            self.log.warning("datagrama del servidor mal formado: %s", e)
            return
        if m.tipo == "ERROR" and m.campos.get("code") == "404":
            raise FalloSesion("ERROR 404 %s por UDP: el servidor no reconoce la sesión; "
                              "se registra de nuevo" % m.campos.get("reason"), inmediato=True)

    def _despedir(self, tcp):
        """CERRANDO: BYE y espera del BYE del servidor (hasta T_resp)."""
        self.log.info("estado=CERRANDO")
        try:
            self._enviar_tcp(tcp, construir("BYE", req=self._nuevo_req()))
            fin = time.monotonic() + self.t_resp
            while True:
                if self._leer_mensaje(tcp, max(0.1, fin - time.monotonic())).tipo == "BYE":
                    break
        except (FalloSesion, OSError) as e:
            self.log.warning("cierre sin BYE del servidor: %s", e)

    # ------------------------------------------------------------ TCP

    def _nuevo_req(self):
        self._req += 1
        return self._req

    def _enviar_tcp(self, tcp, linea):
        self.log.info("TCP -> %s", proto.ocultar(linea.strip()))
        tcp.sendall(linea.encode("ascii"))     # sendall repite send() hasta enviar todo (4.3)

    def _recibir(self, tcp):
        datos = tcp.recv(4096)
        if not datos:
            raise FalloSesion("el servidor cerró la conexión TCP")
        try:
            self._lineas.extend(self._lector.alimentar(datos))
        except ErrorFormato as e:
            raise FalloSesion("mensaje inválido del servidor: %s" % e)

    def _tomar(self):
        linea = self._lineas.popleft()
        self.log.info("TCP <- %s", proto.ocultar(linea))
        try:
            return proto.parsear(linea)
        except ErrorFormato as e:
            raise FalloSesion("mensaje inválido del servidor: %s" % e)

    def _leer_mensaje(self, tcp, plazo):
        fin = time.monotonic() + plazo
        while not self._lineas:
            resto = fin - time.monotonic()
            if resto <= 0:
                raise FalloSesion("vence T_resp (%gs) sin respuesta" % plazo)
            if select.select([tcp], [], [], resto)[0]:
                self._recibir(tcp)
        return self._tomar()


class _Parada:
    """Bandera de apagado compatible con `wait(segundos)` (como threading.Event
    pero segura para usar desde un manejador de señales)."""

    def __init__(self):
        self._v = False

    def set(self):
        self._v = True

    def is_set(self):
        return self._v

    def wait(self, segundos):
        fin = time.monotonic() + segundos
        while not self._v and time.monotonic() < fin:
            time.sleep(min(0.1, max(0.0, fin - time.monotonic())))


# -------------------------------------------------------- línea de comandos

def _parser(descripcion, kind_defecto):
    p = argparse.ArgumentParser(description=descripcion)
    p.add_argument("--servidor", default=os.environ.get("MCD_SERVIDOR"),
                   help="nombre del servidor (o variable MCD_SERVIDOR)")
    p.add_argument("--puerto", type=int, default=_entero_env("MCD_PUERTO"), help="puerto TCP/UDP del servidor")
    p.add_argument("--id", dest="node_id", required=True, help="node_id (existe en ou=devices del LDAP)")
    p.add_argument("--kind", default=kind_defecto, choices=proto.KINDS)
    p.add_argument("--period", type=int, default=5, help="segundos entre telemetrías (1 a 60)")
    p.add_argument("--secret-env", default="MCD_NODO_SECRET",
                   help="variable de entorno con la clave del nodo (nunca se pasa por argumento)")
    p.add_argument("--log", help="archivo de log del nodo (además de la consola)")
    p.add_argument("--detallado", action="store_true")
    p.add_argument("--backoff-max", type=int, default=30, help="tope de la espera de reintento (7.9)")
    p.add_argument("--t-resp", type=float, default=5.0)
    p.add_argument("--t-ack", type=float, default=5.0)
    p.add_argument("--semilla", type=int, default=None, help="semilla del simulador (repetible)")
    p.add_argument("--forzar-evento", action="append", default=[], metavar="NIVEL:EVENTO[:VALOR]",
                   help="encola un evento al arrancar (para demostraciones y pruebas)")
    return p


def _entero_env(nombre):
    v = os.environ.get(nombre)
    return int(v) if v and v.isdigit() else None


def principal(descripcion, kind_defecto, agregar_args, crear_simulador, argv=None):
    """Punto de entrada común de los programas de nodo."""
    p = _parser(descripcion, kind_defecto)
    agregar_args(p)
    a = p.parse_args(argv)
    secret = os.environ.get(a.secret_env, "")
    errores = []
    if not a.servidor:
        errores.append("falta --servidor (o MCD_SERVIDOR)")
    if not a.puerto or not 1 <= a.puerto <= 65535:
        errores.append("falta --puerto válido (1 a 65535)")
    if not proto.RE_NODE_ID.fullmatch(a.node_id):
        errores.append("--id debe cumplir [a-z][a-z0-9-]{2,31}")
    if not 1 <= a.period <= 60:
        errores.append("--period debe estar entre 1 y 60")
    if not 8 <= len(secret) <= 64 or any(not (c.isalnum() or c in "._:-") for c in secret):
        errores.append("la variable %s debe tener la clave del nodo (8 a 64 caracteres seguros)" % a.secret_env)
    forzados = []
    for texto in a.forzar_evento:
        partes = texto.split(":", 2)
        valor = partes[2] if len(partes) == 3 else None
        if (len(partes) < 2 or partes[0] not in proto.LEVELS or partes[1] not in proto.EVENTOS
                or (valor is not None and not (proto.RE_VALOR.fullmatch(valor) and len(valor) <= 32))):
            errores.append("--forzar-evento inválido: %r" % texto)
        else:
            forzados.append((partes[0], partes[1], valor))
    if errores:
        p.error("; ".join(errores))
    log = proto.configurar_log("nodo." + a.node_id, a.log, a.detallado)
    nodo = Nodo(a.servidor, a.puerto, a.node_id, secret, a.kind, a.period,
                crear_simulador(a, random.Random(a.semilla)), log,
                a.backoff_max, a.t_resp, a.t_ack)
    for nivel, evento, valor in forzados:
        nodo.encolar_evento(nivel, evento, valor)
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, lambda *_: nodo.detener.set())
    nodo.ejecutar()
    return 0
