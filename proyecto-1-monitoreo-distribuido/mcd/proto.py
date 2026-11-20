"""Núcleo de MCD/1.0 del lado de nodos y clientes (secciones 4, 7.9 y 12).

Contiene lo que comparten el nodo y el cliente: construcción y análisis de
mensajes (gramática 4.2), encuadre de líneas sobre TCP (4.3), espera
creciente (7.9), conexión resolviendo por nombre (12) y registro de
actividad sin secretos (11).
"""
import logging
import re
import socket
import sys
import time
from collections import namedtuple

VERSION = "MCD/1.0"
MAX_MSG = 512          # bytes con el LF (4.1)
MAX_CAMPOS = 16

_RE_TIPO = re.compile(r"[A-Z_]{1,16}")
_RE_CLAVE = re.compile(r"[a-z][a-z0-9_]{0,15}")
RE_VALOR = re.compile(r"[A-Za-z0-9._:\-]{1,64}")
_RE_SECRETO = re.compile(r"\b(secret|password)=[^|\s]*")

# Formatos de los campos que los programas validan antes de enviar (4.5).
RE_NODE_ID = re.compile(r"[a-z][a-z0-9\-]{2,31}")
RE_USER = re.compile(r"[a-z][a-z0-9._\-]{2,31}")
RE_SESSION = re.compile(r"[0-9a-f]{16}")

KINDS = ("SENSOR", "RED", "IOT", "OTRO")
LEVELS = ("INFO", "ADVERTENCIA", "CRITICO")
EVENTOS = ("FALLA", "UMBRAL_TEMP", "UMBRAL_CPU", "BATERIA_BAJA",
           "CAMBIO_ESTADO", "ALARMA", "CONECTIVIDAD")

Mensaje = namedtuple("Mensaje", "tipo campos")


class ErrorFormato(ValueError):
    """Una línea recibida no cumple la gramática de 4.2 o el límite de 4.3."""


class ErrorResolucion(OSError):
    """getaddrinfo no pudo resolver el nombre (EAI_*)."""


class ErrorConexion(OSError):
    """Ninguna de las direcciones resueltas aceptó la conexión TCP."""


# ---------------------------------------------------------------- mensajes

def construir(tipo, **campos):
    """Arma una línea MCD/1.0 terminada en LF; ValueError si incumple 4.2."""
    if not _RE_TIPO.fullmatch(tipo):
        raise ValueError("tipo inválido: %r" % tipo)
    if len(campos) > MAX_CAMPOS:
        raise ValueError("más de %d campos" % MAX_CAMPOS)
    partes = [VERSION, tipo]
    for clave, valor in campos.items():
        valor = str(valor)
        if not _RE_CLAVE.fullmatch(clave) or not RE_VALOR.fullmatch(valor):
            raise ValueError("campo inválido: %s=%r" % (clave, valor))
        partes.append("%s=%s" % (clave, valor))
    linea = "|".join(partes) + "\n"
    if len(linea) > MAX_MSG:
        raise ValueError("el mensaje excede %d bytes" % MAX_MSG)
    return linea


def parsear(linea):
    """Analiza una línea (sin LF) recibida del servidor. ErrorFormato si no
    cumple la gramática, repite claves o la versión no es MCD/1.0."""
    if len(linea) + 1 > MAX_MSG:
        raise ErrorFormato("línea de más de %d bytes" % MAX_MSG)
    partes = linea.split("|")
    if len(partes) < 2:
        raise ErrorFormato("faltan elementos")
    if partes[0] != VERSION:
        raise ErrorFormato("versión %r" % partes[0][:20])
    if not _RE_TIPO.fullmatch(partes[1]):
        raise ErrorFormato("tipo inválido")
    if len(partes) - 2 > MAX_CAMPOS:
        raise ErrorFormato("demasiados campos")
    campos = {}
    for p in partes[2:]:
        clave, igual, valor = p.partition("=")
        if not igual or not _RE_CLAVE.fullmatch(clave) or not RE_VALOR.fullmatch(valor):
            raise ErrorFormato("campo mal formado: %r" % p[:40])
        if clave in campos:
            raise ErrorFormato("clave repetida: %s" % clave)
        campos[clave] = valor
    return Mensaje(partes[1], campos)


def entero(campos, clave):
    """Entero decimal sin ceros a la izquierda de un campo, o ErrorFormato."""
    v = campos.get(clave, "")
    if not re.fullmatch(r"0|[1-9][0-9]*", v):
        raise ErrorFormato("%s=%r no es un entero" % (clave, v[:20]))
    return int(v)


def ocultar(linea):
    """Reemplaza secret y password por *** (regla de 11: nunca en un log)."""
    return _RE_SECRETO.sub(lambda m: m.group(1) + "=***", linea)


class LectorLineas:
    """Encuadre por LF de un flujo TCP (4.3): acepta líneas partidas y varias
    líneas por lectura, tolera \\r\\n y descarta líneas vacías."""

    def __init__(self):
        self.buf = b""

    def alimentar(self, datos):
        """Agrega bytes y devuelve las líneas completas (str, sin LF)."""
        self.buf += datos
        salida = []
        while True:
            fin = self.buf.find(b"\n")
            if fin < 0:
                break
            if fin + 1 > MAX_MSG:
                raise ErrorFormato("línea de más de %d bytes" % MAX_MSG)
            linea, self.buf = self.buf[:fin], self.buf[fin + 1:]
            if linea.endswith(b"\r"):
                linea = linea[:-1]
            if not linea:
                continue
            try:
                salida.append(linea.decode("ascii"))
            except UnicodeDecodeError:
                raise ErrorFormato("bytes fuera de ASCII")
        if len(self.buf) >= MAX_MSG:
            raise ErrorFormato("%d bytes sin LF" % len(self.buf))
        return salida


# ------------------------------------------------------------------ red

class Backoff:
    """Espera creciente de 7.9: 1, 2, 4, 8, 16, 30, 30... (con tope opcional
    menor para pruebas)."""

    PASOS = (1, 2, 4, 8, 16, 30)

    def __init__(self, maximo=30):
        self.maximo = maximo
        self.i = 0

    def siguiente(self):
        espera = min(self.PASOS[min(self.i, len(self.PASOS) - 1)], self.maximo)
        self.i += 1
        return espera

    def reiniciar(self):
        self.i = 0


def conectar_tcp(host, puerto, plazo):
    """Resuelve `host` con getaddrinfo y abre TCP (nunca una IP escrita en el
    código, requisito 4). Cada intento vuelve a resolver el nombre, así un
    cambio de DNS se aplica en la siguiente reconexión (12)."""
    try:
        infos = socket.getaddrinfo(host, puerto, 0, socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as e:
        raise ErrorResolucion("no se pudo resolver %r: %s" % (host, e))
    ultimo = None
    for familia, tipo, proto, _, direccion in infos:
        s = socket.socket(familia, tipo, proto)
        s.settimeout(plazo)
        try:
            s.connect(direccion)
        except OSError as e:
            ultimo = e
            s.close()
            continue
        s.settimeout(None)
        return s
    raise ErrorConexion("no se pudo conectar a %s:%s (%s)" % (host, puerto, ultimo))


# ------------------------------------------------------------------ log

def configurar_log(nombre, archivo=None, detallado=False, nivel_consola=logging.INFO):
    """Logger propio: consola (stderr) y, si se pide, archivo. Hora UTC."""
    log = logging.getLogger(nombre)
    log.setLevel(logging.DEBUG if detallado else logging.INFO)
    log.propagate = False
    log.handlers = []
    formato = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    formato.converter = time.gmtime
    consola = logging.StreamHandler(sys.stderr)
    consola.setLevel(nivel_consola)
    destinos = [consola]
    if archivo:
        destinos.append(logging.FileHandler(archivo, encoding="utf-8"))
    for d in destinos:
        d.setFormatter(formato)
        log.addHandler(d)
    return log


def log_cliente(nombre, archivo=None, detallado=False):
    """Log del cliente: la consola solo muestra errores salvo con --detallado (que enseña
    cada mensaje enviado y recibido); el archivo, si se pide, lo registra todo."""
    return configurar_log(nombre, archivo, detallado, logging.INFO if detallado else logging.ERROR)
