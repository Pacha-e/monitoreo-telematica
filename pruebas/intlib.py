"""Apoyo de las pruebas de integración: lanzar los programas reales (nodos y
cliente), un relé TCP+UDP que puede perder un ACK y un servidor MCD falso para
provocar situaciones que el servidor real no produce (404 por UDP, respuestas
inválidas, 503 repetidos).

Los programas bajo prueba se ejecutan como procesos de verdad (`python3 nodos/...`,
`python3 cliente/...`); aquí solo se les da entorno, se leen sus logs y se les
envían señales.
"""
import os
import re
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import namedtuple

import mcdlib
from mcdlib import (ADMIN, HOST, RAIZ, clave_nodo, directorio_temporal, msg, parsear,
                    puerto_libre)

sys.path.insert(0, RAIZ)
from mcd import vista  # noqa: E402

NODOS_DIR = os.path.join(RAIZ, "nodos")
CLIENTE = os.path.join(RAIZ, "cliente", "cliente_admin.py")


class Proc:
    """Proceso hijo con su salida en archivos y control de señales."""

    def __init__(self, args, env=None, nombre="proc"):
        self.dir = directorio_temporal("proc-%s-" % nombre)
        self.f_out = os.path.join(self.dir, "stdout.txt")
        self.f_err = os.path.join(self.dir, "stderr.txt")
        self.p = subprocess.Popen(args, env=env or dict(os.environ), stdin=subprocess.DEVNULL,
                                  stdout=open(self.f_out, "wb"), stderr=open(self.f_err, "wb"),
                                  start_new_session=True)
        mcdlib._PROCESOS.append(self.p)

    def vivo(self):
        return self.p.poll() is None

    def err(self):
        with open(self.f_err, errors="replace") as f:
            return f.read()

    def out(self):
        with open(self.f_out, errors="replace") as f:
            return f.read()

    def senal(self, sig):
        os.kill(self.p.pid, sig)

    def terminar(self, plazo=10):
        """SIGTERM (cierre ordenado) y código de salida."""
        if self.vivo():
            self.senal(signal.SIGTERM)
            try:
                self.p.wait(plazo)
            except subprocess.TimeoutExpired:
                os.killpg(self.p.pid, signal.SIGKILL)
                self.p.wait(5)
        return self.p.returncode

    def matar(self):
        if self.vivo():
            os.killpg(self.p.pid, signal.SIGKILL)
            self.p.wait(5)


def lanzar_nodo(puerto, node_id, programa="nodo_sensor.py", period=1, host=HOST, extra=(),
                backoff_max=2, secret=None, env=None):
    e = dict(os.environ, MCD_NODO_SECRET=secret or clave_nodo(node_id))
    e.update(env or {})
    args = ["python3", os.path.join(NODOS_DIR, programa), "--servidor", host, "--puerto", str(puerto),
            "--id", node_id, "--period", str(period), "--backoff-max", str(backoff_max)] + list(extra)
    return Proc(args, e, "nodo-" + node_id)


Resultado = namedtuple("Resultado", "rc stdout stderr")

# Título de columna de la consola -> clave del campo del protocolo.
_CLAVE_DE_TITULO = {t: k for cols in (vista.COLUMNAS_LISTA, vista.COLUMNAS_ESTADO,
                                      vista.COLUMNAS_HISTORIAL, vista.COLUMNAS_EVENTOS)
                    for t, k in cols}


def cliente(puerto, cred, *comandos, host=HOST, extra=(), timeout=45):
    """Ejecuta el cliente real una vez con uno o más --comando y devuelve código de
    salida, stdout y stderr."""
    args = ["python3", CLIENTE, "--servidor", host, "--puerto", str(puerto), "--usuario", cred[0]]
    for c in comandos:
        args += ["--comando", c]
    r = subprocess.run(args + list(extra), env=dict(os.environ, MCD_PASSWORD=cred[1]),
                       capture_output=True, text=True, timeout=timeout)
    return Resultado(r.returncode, r.stdout, r.stderr)


def filas(lineas):
    """Filas de una tabla de la consola (encabezado, raya y filas) como dicts con las
    claves del protocolo. Las columnas se localizan por la raya `---`."""
    lineas = [l for l in lineas if l.strip()]
    if len(lineas) < 2 or not set(lineas[1].replace(" ", "")) <= {"-"}:
        return []
    tramos = [m.span() for m in re.finditer(r"-+", lineas[1])]
    claves = [_CLAVE_DE_TITULO[lineas[0][a:b].strip()] for a, b in tramos]
    return [{k: l[a:b].strip() for k, (a, b) in zip(claves, tramos)} for l in lineas[2:]]


def tabla_de(texto):
    return filas(texto.splitlines())


def panel_de(texto):
    """Último panel de la salida de consola: rol, nodos (estado + historial) y eventos
    (None si el rol no los ve)."""
    p = {"rol": re.search(r"usuario \S+ \((\w+)\)", texto).group(1), "nodos": [], "eventos": None}
    historiales = {}
    for bloque in texto.strip().split("\n\n")[1:]:
        titulo, *resto = bloque.splitlines()
        if titulo == "Estado instantáneo":
            p["nodos"] = [{"estado": e, "historial": []} for e in filas(resto)]
        elif titulo.startswith("Historial de "):
            historiales[titulo.split()[2]] = filas(resto)
        elif titulo == "Últimos eventos":
            p["eventos"] = filas(resto)
    for n in p["nodos"]:
        n["historial"] = historiales.get(n["estado"]["node_id"], [])
    return p


def error_servidor(r):
    """(code, reason, field) del ERROR que el cliente mostró en stderr."""
    m = re.search(r"ERROR (\d{3}) ([A-Z_]+)(?: \(campo (\w+)\))?", r.stderr)
    if not m:
        raise AssertionError("stderr sin ERROR del servidor: %r" % r.stderr[-300:])
    return m.groups()


def items(puerto, cred, comando, **kw):
    """Filas de una consulta hecha con el cliente real (falla si no salió con 0)."""
    r = cliente(puerto, cred, comando, **kw)
    if r.rc != 0:
        raise AssertionError("cliente '%s' rc=%s stdout=%r stderr=%r" % (comando, r.rc, r.stdout[-300:], r.stderr[-300:]))
    return tabla_de(r.stdout)


# ------------------------------------------------------------------ relé

class Proxy:
    """Relé TCP + UDP entre un nodo y el servidor. Con `perder_primer_ack`, descarta el
    primer ACK del servidor y corta la conexión: el servidor ya guardó el evento pero el
    nodo no lo sabe (el caso que cubre `msg_id`, 7.4)."""

    def __init__(self, puerto_servidor, perder_primer_ack=True):
        self.destino = ("localhost", puerto_servidor)
        self.puerto = puerto_libre()
        self.perder = perder_primer_ack
        self.acks_perdidos = 0
        self.activo = True
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(("localhost", self.puerto))
        self.tcp.listen(8)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("localhost", self.puerto))
        for f in (self._aceptar, self._relevo_udp):
            threading.Thread(target=f, daemon=True).start()

    def _aceptar(self):
        while self.activo:
            try:
                cli, _ = self.tcp.accept()
                srv = socket.create_connection(self.destino, 5)
            except OSError:
                return
            threading.Thread(target=self._copiar, args=(cli, srv, False), daemon=True).start()
            threading.Thread(target=self._copiar, args=(srv, cli, True), daemon=True).start()

    def _copiar(self, origen, destino, desde_servidor):
        try:
            while True:
                datos = origen.recv(4096)
                if not datos:
                    break
                if desde_servidor and self.perder and b"|ACK|" in datos:
                    self.perder = False
                    self.acks_perdidos += 1
                    break                    # el ACK no llega al nodo y se corta la conexión
                destino.sendall(datos)
        except OSError:
            pass
        finally:
            for s in (origen, destino):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                s.close()

    def _relevo_udp(self):
        arriba = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ultimo = None
        while self.activo:
            r, _, _ = select.select([self.udp, arriba], [], [], 0.3)
            try:
                if self.udp in r:
                    datos, ultimo = self.udp.recvfrom(2048)
                    arriba.sendto(datos, self.destino)
                if arriba in r and ultimo:
                    self.udp.sendto(arriba.recvfrom(2048)[0], ultimo)
            except OSError:
                return

    def cerrar(self):
        self.activo = False
        for s in (self.tcp, self.udp):
            try:
                s.close()
            except OSError:
                pass


# ----------------------------------------------------------- servidor falso

class ServidorFalso:
    """Servidor MCD mínimo con comportamientos defectuosos a propósito.

    modo:  udp404       tras la primera TELEMETRY responde ERROR 404 SESION por UDP
           siempre404   responde 404 SESION a cada TELEMETRY (dos nodos que se pisan la sesión)
           sin_ack      acepta registros pero nunca confirma un EVENT
           basura       el primer REGISTER recibe una línea que no es MCD/1.0
           503          los dos primeros REGISTER reciben ERROR 503 LDAP
           lista_corta  LOGIN_OK y a LIST responde items=2 con un solo ITEM y cierra
    """

    def __init__(self, modo):
        self.modo = modo
        self.puerto = puerto_libre()
        self.activo = True
        self.conexiones = 0
        self.registros = []        # (instante, número de conexión)
        self.eventos = []          # (número de conexión, req, msg_id)
        self.logins = 0
        self.enviado_404 = False
        self.telemetrias = 0
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(("localhost", self.puerto))
        self.tcp.listen(8)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("localhost", self.puerto))
        for f in (self._aceptar, self._bucle_udp):
            threading.Thread(target=f, daemon=True).start()

    def _aceptar(self):
        while self.activo:
            try:
                c, _ = self.tcp.accept()
            except OSError:
                return
            self.conexiones += 1
            threading.Thread(target=self._atender, args=(c, self.conexiones), daemon=True).start()

    def _bucle_udp(self):
        while self.activo:
            try:
                datos, origen = self.udp.recvfrom(2048)
            except OSError:
                return
            self.telemetrias += 1
            if (self.modo == "udp404" and not self.enviado_404) or self.modo == "siempre404":
                self.enviado_404 = True
                self.udp.sendto(msg("ERROR", req=0, code=404, reason="SESION").encode(), origen)

    def _atender(self, c, n):
        buf = b""
        try:
            while self.activo:
                d = c.recv(4096)
                if not d:
                    return
                buf += d
                while b"\n" in buf:
                    linea, _, buf = buf.partition(b"\n")
                    if not self._responder(c, n, linea.decode(errors="replace")):
                        return
        except OSError:
            pass
        finally:
            c.close()

    def _responder(self, c, n, linea):
        """Devuelve False si hay que cerrar la conexión."""
        try:
            tipo, f = parsear(linea)
        except IndexError:
            return True
        enviar = lambda texto: c.sendall(texto.encode())  # noqa: E731
        req = f.get("req", "0")
        if tipo == "REGISTER":
            self.registros.append((time.monotonic(), n))
            if self.modo == "basura" and len(self.registros) == 1:
                enviar("HOLA MUNDO esto no es MCD\n")
            elif self.modo == "503" and len(self.registros) <= 2:
                enviar(msg("ERROR", req=req, code=503, reason="LDAP"))
            else:
                enviar(msg("REGISTER_OK", req=req, node_id=f["node_id"],
                           session="%016x" % (0xABC000 + len(self.registros)), period=f["period"]))
        elif tipo == "EVENT":
            self.eventos.append((n, req, f["msg_id"]))
            if self.modo != "sin_ack":
                enviar(msg("ACK", req=req, node_id=f["node_id"], msg_id=f["msg_id"], dup=0))
        elif tipo == "LOGIN":
            self.logins += 1
            enviar(msg("LOGIN_OK", req=req, user=f["user"], role="admin"))
        elif tipo == "LIST" and self.modo == "lista_corta":
            enviar(msg("RESPONSE", req=req, op="LIST", items=2))
            enviar(msg("ITEM", req=req, idx=1, node_id="nodo-01", kind="SENSOR", state="ACTIVO",
                       last_seen=1))
            return False
        elif tipo == "BYE":
            enviar(msg("BYE", req=req))
            return False
        return True

    def cerrar(self):
        self.activo = False
        for s in (self.tcp, self.udp):
            try:
                s.close()
            except OSError:
                pass
