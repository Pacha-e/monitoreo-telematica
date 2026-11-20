"""Biblioteca de apoyo de las pruebas del servidor MCD/1.0.

Solo usa la biblioteca estandar de Python: sockets crudos, procesos y archivos.
"""
import os
import random
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
INFRA = os.path.join(RAIZ, "infra", "ldap")
SERVIDOR_DIR = os.path.join(RAIZ, "servidor")
HOST = "localhost"
BASE_DN = "dc=monitoreo,dc=lab"

# Claves ficticias de laboratorio (las mismas de infra/ldap/base.ldif).
ADMIN = ("admin1", "clave-admin-lab1")
OPERADOR = ("operador1", "clave-operador-lab1")
SINROL = ("sinrol1", "clave-sinrol-lab1")
CLAVE_INCORRECTA = "clave-incorrecta-xyz"


def clave_nodo(node_id):
    return "clave-" + node_id


def resolver(host, puerto, tipo):
    """getaddrinfo IPv4 (el servidor escucha en IPv4)."""
    info = socket.getaddrinfo(host, puerto, socket.AF_INET, tipo)
    return info[0][4]


def puerto_libre():
    """Un puerto alto libre tanto en TCP como en UDP."""
    for _ in range(200):
        t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        t.bind(("", 0))
        p = t.getsockname()[1]
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            u.bind(("", p))
            return p
        except OSError:
            continue
        finally:
            t.close()
            u.close()
    raise RuntimeError("no hay puerto libre")


def msg(tipo, **campos):
    """Construye una linea MCD/1.0 terminada en LF."""
    partes = ["MCD/1.0", tipo] + ["%s=%s" % (k, v) for k, v in campos.items()]
    return "|".join(partes) + "\n"


def parsear(linea):
    """'MCD/1.0|TIPO|a=b' -> ('TIPO', {'a': 'b'})."""
    partes = linea.rstrip("\n").split("|")
    campos = {}
    for p in partes[2:]:
        k, _, v = p.partition("=")
        campos[k] = v
    return partes[1], campos


class ClienteTCP:
    """Cliente TCP con lectura por lineas y plazos."""

    def __init__(self, puerto, host=HOST):
        self.s = socket.create_connection(resolver(host, puerto, socket.SOCK_STREAM), 5)
        self.buf = b""
        self.req = 0

    def siguiente_req(self):
        self.req += 1
        return self.req

    def enviar(self, texto):
        self.s.sendall(texto.encode() if isinstance(texto, str) else texto)

    def linea(self, plazo=5.0):
        """Siguiente linea sin LF; None si venció el plazo; '' si cerró el servidor."""
        fin = time.time() + plazo
        while b"\n" not in self.buf:
            resto = fin - time.time()
            if resto <= 0:
                return None
            self.s.settimeout(resto)
            try:
                d = self.s.recv(4096)
            except socket.timeout:
                return None
            except OSError:
                return ""
            if not d:
                return ""
            self.buf += d
        l, _, self.buf = self.buf.partition(b"\n")
        return l.decode()

    def pedir(self, tipo, **campos):
        """Envía un mensaje con req nuevo y devuelve (tipo, campos) de la respuesta."""
        campos = dict(req=self.siguiente_req(), **campos)
        self.enviar(msg(tipo, **campos))
        return self.respuesta()

    def respuesta(self, plazo=5.0):
        l = self.linea(plazo)
        if not l:
            return None, {}
        return parsear(l)

    def consulta(self, tipo, **campos):
        """Consulta: devuelve (RESPONSE|ERROR, campos, [items])."""
        t, c = self.pedir(tipo, **campos)
        items = []
        if t == "RESPONSE":
            for _ in range(int(c["items"])):
                ti, ci = self.respuesta()
                assert ti == "ITEM", "se esperaba ITEM y llego %r" % ti
                items.append(ci)
        return t, c, items

    def cerrado(self, plazo=3.0):
        """True si el servidor cerró la conexión dentro del plazo."""
        fin = time.time() + plazo
        while time.time() < fin:
            self.s.settimeout(max(0.05, fin - time.time()))
            try:
                d = self.s.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return True
            if not d:
                return True
        return False

    def cerrar(self):
        try:
            self.s.close()
        except OSError:
            pass


class ClienteUDP:
    def __init__(self, puerto, host=HOST):
        self.dest = resolver(host, puerto, socket.SOCK_DGRAM)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def enviar(self, texto):
        self.s.sendto(texto.encode() if isinstance(texto, str) else texto, self.dest)

    def recibir(self, plazo=1.0):
        self.s.settimeout(plazo)
        try:
            return self.s.recvfrom(2048)[0].decode().rstrip("\n")
        except socket.timeout:
            return None

    def cerrar(self):
        self.s.close()


def telemetria(node_id, session, seq, cpu="37.5", temp="48.1", bat="91",
               opstate="OK", uptime="3731", ts="1791126131"):
    return msg("TELEMETRY", node_id=node_id, session=session, seq=seq, ts=ts,
               cpu=cpu, temp=temp, bat=bat, opstate=opstate, uptime=uptime)


def registrar_nodo(puerto, node_id, period=5, kind="SENSOR", secret=None):
    """Abre TCP y registra el nodo. Devuelve (cliente, session)."""
    c = ClienteTCP(puerto)
    t, r = c.pedir("REGISTER", node_id=node_id, secret=secret or clave_nodo(node_id),
                   kind=kind, period=period)
    if t != "REGISTER_OK":
        c.cerrar()
        raise AssertionError("REGISTER fallo: %s %s" % (t, r))
    return c, r["session"]


def login(puerto, cred=ADMIN):
    c = ClienteTCP(puerto)
    t, r = c.pedir("LOGIN", user=cred[0], password=cred[1])
    if t != "LOGIN_OK":
        c.cerrar()
        raise AssertionError("LOGIN fallo: %s %s" % (t, r))
    return c, r["role"]


def esperar(cond, plazo=5.0, paso=0.1):
    """Repite cond() hasta que sea verdadera o venza el plazo."""
    fin = time.time() + plazo
    while time.time() < fin:
        v = cond()
        if v:
            return v
        time.sleep(paso)
    return cond()


# ---- Procesos hijos: se registran para poder matarlos siempre ----

_PROCESOS = []
_DIRS = []


def limpiar_todo():
    """Mata los procesos registrados (servidor, slapd) y borra los temporales."""
    for p in _PROCESOS:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                pass
    del _PROCESOS[:]
    for d in _DIRS:
        shutil.rmtree(d, ignore_errors=True)
    del _DIRS[:]


def directorio_temporal(prefijo):
    # Los temporales (slapd, logs, salidas de procesos) van a /tmp, no al disco del proyecto.
    base = os.environ.get("MCD_TMP") or os.path.join(tempfile.gettempdir(), "mcd-pruebas")
    os.makedirs(base, exist_ok=True)
    d = tempfile.mkdtemp(prefix=prefijo, dir=base)
    _DIRS.append(d)
    return d


class LdapLab:
    """slapd de laboratorio como usuario normal, en un puerto alto y un
    directorio temporal propio (mismo procedimiento que infra/ldap/README.md)."""

    def __init__(self):
        self.dir = directorio_temporal("ldap-")
        self.puerto = puerto_libre()
        self.conf = os.path.join(self.dir, "slapd.conf")
        self.pidfile = os.path.join(self.dir, "slapd.pid")
        self.proc = None

    def _preparar(self):
        os.makedirs(os.path.join(self.dir, "db"), exist_ok=True)
        with open(os.path.join(INFRA, "slapd.conf.plantilla")) as f:
            txt = f.read().replace("@DIR@", self.dir)
        with open(self.conf, "w") as f:
            f.write(txt)
        if not os.path.exists(os.path.join(self.dir, "db", "data.mdb")):
            subprocess.run(["/usr/sbin/slapadd", "-f", self.conf, "-l",
                            os.path.join(INFRA, "base.ldif")],
                           check=True, capture_output=True)

    def iniciar(self):
        self._preparar()
        if os.path.exists(self.pidfile):
            os.remove(self.pidfile)
        log = open(os.path.join(self.dir, "slapd.log"), "ab")
        self.proc = subprocess.Popen(
            ["/usr/sbin/slapd", "-f", self.conf, "-h", "ldap://%s:%d/" % (HOST, self.puerto),
             "-d", "0"],
            stdout=log, stderr=log, start_new_session=True)
        _PROCESOS.append(self.proc)
        if not esperar(self.responde, 10.0):
            raise RuntimeError("slapd no respondio; revise %s/slapd.log" % self.dir)

    def responde(self):
        r = subprocess.run(["ldapsearch", "-x", "-H", "ldap://%s:%d/" % (HOST, self.puerto),
                            "-b", "", "-s", "base"], capture_output=True)
        return r.returncode == 0

    def detener(self):
        pids = []
        if os.path.exists(self.pidfile):
            try:
                pids.append(int(open(self.pidfile).read().strip()))
            except ValueError:
                pass
        if self.proc is not None:
            pids.append(self.proc.pid)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        def terminado():
            for pid in pids:
                try:
                    os.kill(pid, 0)
                    return False
                except ProcessLookupError:
                    pass
            return True
        if not esperar(terminado, 5.0):
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.proc is not None:
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
        if os.path.exists(self.pidfile):
            os.remove(self.pidfile)


class Servidor:
    """El binario del servidor como proceso hijo, con su log y su salida."""

    def __init__(self, binario, ldap_puerto, env=None, nombre="srv"):
        self.binario = os.path.abspath(binario)
        self.puerto = puerto_libre()
        self.dir = directorio_temporal("srv-%s-" % nombre)
        self.log = os.path.join(self.dir, "servidor.log")
        self.f_out = os.path.join(self.dir, "stdout.txt")
        self.f_err = os.path.join(self.dir, "stderr.txt")
        self.env = dict(os.environ)
        self.env.update({
            "MCD_LDAP_HOST": HOST, "MCD_LDAP_PORT": str(ldap_puerto),
            "MCD_LDAP_BASE": BASE_DN,
            "ASAN_OPTIONS": "detect_leaks=1:exitcode=99",
            "UBSAN_OPTIONS": "print_stacktrace=1",
        })
        self.env.update(env or {})
        self.proc = None

    def iniciar(self):
        self.proc = subprocess.Popen(
            [self.binario, str(self.puerto), self.log], cwd=self.dir, env=self.env,
            stdout=open(self.f_out, "wb"), stderr=open(self.f_err, "wb"),
            start_new_session=True)
        _PROCESOS.append(self.proc)
        fin = time.time() + 10
        while time.time() < fin:
            if self.proc.poll() is not None:
                raise RuntimeError("el servidor termino al arrancar: " + self.stderr())
            try:
                socket.create_connection(resolver(HOST, self.puerto, socket.SOCK_STREAM), 0.5).close()
                return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("el servidor no acepto conexiones")

    def vivo(self):
        return self.proc is not None and self.proc.poll() is None

    def detener(self):
        """SIGTERM y espera; devuelve el codigo de salida."""
        if self.proc is None:
            return None
        if self.proc.poll() is None:
            os.kill(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(5)
        return self.proc.returncode

    def stderr(self):
        with open(self.f_err, errors="replace") as f:
            return f.read()

    def texto_log(self):
        with open(self.log, errors="replace") as f:
            return f.read()


# ---- Registro de pruebas y contexto de ejecucion ----

PRUEBAS = []


def prueba(f):
    """Decorador: registra la funcion como prueba (en orden de definicion)."""
    PRUEBAS.append(f)
    return f


def ok(cond, detalle="condicion falsa"):
    if not cond:
        raise AssertionError(detalle)


def eq(obtenido, esperado, detalle=""):
    if obtenido != esperado:
        raise AssertionError("%s esperado=%r obtenido=%r" % (detalle, esperado, obtenido))


def error(t, campos, code, reason, req=None, field=None):
    """Comprueba que la respuesta es el ERROR indicado."""
    eq(t, "ERROR", "tipo de respuesta (campos=%s)" % campos)
    eq((campos.get("code"), campos.get("reason")), (str(code), reason), "codigo/motivo")
    if req is not None:
        eq(campos.get("req"), str(req), "req del ERROR")
    if field is not None:
        eq(campos.get("field"), field, "field del ERROR")


class Ctx:
    """Servidor principal de una variante (normal o ASan) y servidores extra."""

    def __init__(self, binario, ldap, etiqueta):
        self.binario = binario
        self.ldap = ldap
        self.etiqueta = etiqueta
        self.servidores = []
        self.srv = self.nuevo("principal")

    @property
    def puerto(self):
        return self.srv.puerto

    def nuevo(self, nombre, env=None):
        s = Servidor(self.binario, self.ldap.puerto, env, nombre).iniciar()
        self.servidores.append(s)
        return s

    def admin(self, cred=ADMIN, puerto=None):
        return login(puerto or self.puerto, cred)[0]

    def detener_todo(self):
        """Detiene todos los servidores y devuelve [(servidor, codigo de salida)]."""
        return [(s, s.detener()) for s in self.servidores]


def status(c, node_id):
    """Item de STATUS del nodo (o falla la prueba)."""
    t, r, items = c.consulta("STATUS", node_id=node_id)
    eq(t, "RESPONSE", "STATUS de %s: %s" % (node_id, r))
    eq(len(items), 1, "items de STATUS")
    return items[0]


def esperar_status(c, node_id, cond, plazo=5.0):
    """Espera (la telemetria UDP es asincrona) a que cond(item) sea cierta."""
    ultimo = {}

    def f():
        ultimo.update(status(c, node_id))
        return cond(ultimo)
    esperar(f, plazo)
    ok(cond(ultimo), "STATUS de %s no llego al estado esperado: %s" % (node_id, ultimo))
    return ultimo
