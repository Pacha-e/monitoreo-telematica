"""Cliente de administración MCD/1.0: sesión, consultas y reconexión.

Máquina de estados de la sección 9.4 sin interfaz: resolver -> conectar ->
LOGIN -> consultas. La consola solo la usa y muestra los resultados;
los permisos los decide el servidor.

Errores que distingue quien llama:
  ErrorCredenciales  401 CREDENCIALES o 403 ROL en LOGIN: no se reintenta solo,
                     la interfaz debe pedir las credenciales de nuevo.
  ErrorServidor      ERROR de una consulta que se muestra al usuario (403, 404,
                     422...) y deja la sesión abierta.
  ErrorRed           DNS, conexión, plazo T_resp, caída de TCP, respuesta
                     inválida, 408/500/503: se cierra y se reintenta con espera.
  ErrorEntrada       el usuario escribió algo que MCD/1.0 no puede representar.
"""
import select
import threading
import time
from collections import deque, namedtuple

from . import proto
from .proto import ErrorConexion, ErrorFormato, ErrorResolucion, LectorLineas, construir

Resultado = namedtuple("Resultado", "op items")

# Códigos que dejan la conexión útil (se muestran) frente a los que obligan a reconectar.
_MOSTRAR = ("400", "403", "404", "409", "413", "422")


class ErrorServidor(Exception):
    def __init__(self, code, reason, field=None):
        self.code, self.reason, self.field = code, reason, field
        extra = " (campo %s)" % field if field else ""
        Exception.__init__(self, "ERROR %s %s%s" % (code, reason, extra))


class ErrorCredenciales(ErrorServidor):
    pass


class ErrorRed(Exception):
    pass


class ErrorEntrada(ValueError):
    pass


class ClienteAdmin:
    def __init__(self, host, puerto, usuario, password, log, t_resp=5.0, backoff_max=30, avisar=None):
        self.host, self.puerto = host, puerto
        self.usuario, self.password = usuario, password
        self.log, self.t_resp, self.backoff_max = log, t_resp, backoff_max
        self.avisar = avisar or (lambda texto: None)
        self.parar = threading.Event()
        self.rol = None
        self.sock = None
        self._req = 0
        self._lector = LectorLineas()
        self._lineas = deque()

    # ------------------------------------------------------------ sesión

    def conectar(self):
        """RESOLVIENDO -> CONECTANDO -> AUTENTICANDO. Devuelve el perfil (`role`)."""
        login = construir_login(self.usuario, self.password, 1)   # ErrorEntrada antes de abrir el socket
        self._cerrar_socket()
        try:
            self.sock = proto.conectar_tcp(self.host, self.puerto, self.t_resp)
        except ErrorResolucion as e:
            raise ErrorRed("DNS: %s" % e)
        except ErrorConexion as e:
            raise ErrorRed("conexión: %s" % e)
        self._lector, self._lineas, self._req = LectorLineas(), deque(), 1
        m = self._intercambio(login)
        c = m.campos
        if m.tipo == "LOGIN_OK":
            if c.get("user") != self.usuario or c.get("role") not in ("admin", "operador"):
                self._cerrar_socket()
                raise ErrorRed("LOGIN_OK inválido: %s" % c)
            self.rol = c["role"]
            self.log.info("sesión iniciada: usuario=%s perfil=%s", self.usuario, self.rol)
            return self.rol
        if m.tipo != "ERROR":
            self._cerrar_socket()
            raise ErrorRed("respuesta inesperada al LOGIN: %s" % m.tipo)
        code, reason = c.get("code"), c.get("reason")
        self._cerrar_socket()
        if (code, reason) in (("401", "CREDENCIALES"), ("403", "ROL")):
            raise ErrorCredenciales(code, reason)
        if code in ("503", "408", "500"):
            raise ErrorRed("el servidor no pudo atender el LOGIN: ERROR %s %s" % (code, reason))
        raise ErrorServidor(code, reason, c.get("field"))

    def cerrar(self):
        """CERRANDO: BYE y espera de su respuesta (breve); siempre libera el socket."""
        if self.sock is not None:
            try:
                self._enviar(construir("BYE", req=self._nuevo_req()))
                self._leer_mensaje(min(self.t_resp, 2.0))
            except (ErrorRed, OSError):
                pass
        self._cerrar_socket()

    # --------------------------------------------------------- consultas

    def consultar(self, tipo, **campos):
        """Una consulta y su respuesta completa (7.6). Devuelve Resultado."""
        if self.sock is None:
            raise ErrorRed("sin conexión")
        req = self._nuevo_req()
        try:
            linea = construir(tipo, req=req, **campos)
        except ValueError as e:
            raise ErrorEntrada(str(e))
        m = self._intercambio(linea)
        c = m.campos
        if m.tipo == "ERROR":
            code, reason = c.get("code"), c.get("reason")
            if code in _MOSTRAR:
                if code == "413":
                    self._cerrar_socket()
                raise ErrorServidor(code, reason, c.get("field"))
            self._cerrar_socket()
            raise ErrorRed("ERROR %s %s del servidor" % (code, reason))
        try:
            if m.tipo != "RESPONSE" or c.get("req") != str(req) or c.get("op") != tipo:
                raise ErrorFormato("se esperaba RESPONSE req=%d op=%s y llegó %s %s" % (req, tipo, m.tipo, c))
            n = proto.entero(c, "items")
            items = []
            for i in range(1, n + 1):
                it = self._leer_mensaje(self.t_resp)
                if it.tipo != "ITEM" or it.campos.get("req") != str(req) or it.campos.get("idx") != str(i):
                    raise ErrorFormato("se esperaba ITEM idx=%d y llegó %s %s" % (i, it.tipo, it.campos))
                items.append(it.campos)
        except ErrorFormato as e:
            self._cerrar_socket()
            raise ErrorRed("respuesta inválida: %s" % e)
        return Resultado(tipo, items)

    def consultar_resiliente(self, tipo, reintentos=None, **campos):
        """Como `consultar`, pero reconecta (resolviendo el nombre otra vez) y repite el
        LOGIN con las credenciales en memoria si la red falla (7.9, 9.4).
        `reintentos=None` reintenta sin fin; un número limita los reintentos."""
        espera = proto.Backoff(self.backoff_max)
        fallos = 0
        while True:
            if self.parar.is_set():
                raise ErrorRed("cancelado")
            try:
                if self.sock is None:
                    self.conectar()
                    espera.reiniciar()
                return self.consultar(tipo, **campos)
            except ErrorRed as e:
                fallos += 1
                if reintentos is not None and fallos > reintentos:
                    raise
                s = espera.siguiente()
                self.log.warning("%s; reintento en %ds", e, s)
                self.avisar("%s; reintento en %ds" % (e, s))
                if self.parar.wait(s):
                    raise ErrorRed("cancelado")

    def panel(self, historial=5, eventos=10, reintentos=None):
        """Estado instantáneo de todos los nodos + sus últimas `historial` muestras (+ los
        últimos eventos si el perfil es admin). Es lo que muestran las interfaces."""
        q = lambda tipo, **c: self.consultar_resiliente(tipo, reintentos, **c)  # noqa: E731
        nodos = []
        for it in q("LIST").items:
            nid = it["node_id"]
            try:
                estado = q("STATUS", node_id=nid).items[0]
                hist = q("HISTORY", node_id=nid, n=historial).items
            except ErrorCredenciales:
                raise
            except ErrorServidor as e:          # el nodo desapareció entre consultas
                self.log.warning("%s: %s", nid, e)
                continue
            nodos.append(dict(lista=it, estado=estado, historial=hist))
        evs = None
        if self.rol == "admin":
            evs = q("EVENTS", n=eventos).items
        return dict(ts=int(time.time()), usuario=self.usuario, rol=self.rol, nodos=nodos, eventos=evs)

    # ------------------------------------------------------------- bajo nivel

    def _nuevo_req(self):
        self._req += 1
        return self._req

    def _enviar(self, linea):
        self.log.info("-> %s", proto.ocultar(linea.strip()))
        try:
            self.sock.sendall(linea.encode("ascii"))
        except OSError as e:
            self._cerrar_socket()
            raise ErrorRed("fallo al enviar: %s" % e)

    def _intercambio(self, linea):
        self._enviar(linea)
        return self._leer_mensaje(self.t_resp)

    def _leer_mensaje(self, plazo):
        fin = time.monotonic() + plazo
        while not self._lineas:
            if self.sock is None:
                raise ErrorRed("sin conexión")
            resto = fin - time.monotonic()
            if resto <= 0:
                self._cerrar_socket()
                raise ErrorRed("vence T_resp (%gs) sin respuesta" % plazo)
            try:
                if not select.select([self.sock], [], [], resto)[0]:
                    continue
                datos = self.sock.recv(4096)
                if not datos:
                    raise ErrorRed("el servidor cerró la conexión")
                self._lineas.extend(self._lector.alimentar(datos))
            except ErrorFormato as e:
                self._cerrar_socket()
                raise ErrorRed("mensaje inválido del servidor: %s" % e)
            except OSError as e:
                self._cerrar_socket()
                raise ErrorRed("fallo de red: %s" % e)
            except ErrorRed:
                self._cerrar_socket()
                raise
        linea = self._lineas.popleft()
        self.log.info("<- %s", proto.ocultar(linea))
        try:
            return proto.parsear(linea)
        except ErrorFormato as e:
            self._cerrar_socket()
            raise ErrorRed("mensaje inválido del servidor: %s" % e)

    def _cerrar_socket(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None


def construir_login(usuario, password, req):
    """LOGIN validado localmente (ErrorEntrada si usa caracteres no permitidos)."""
    if not proto.RE_USER.fullmatch(usuario):
        raise ErrorEntrada("usuario inválido: use [a-z][a-z0-9._-]{2,31}")
    if not 8 <= len(password) <= 64 or not proto.RE_VALOR.fullmatch(password):
        raise ErrorEntrada("la clave debe tener 8 a 64 caracteres entre letras, dígitos y . - _ :")
    return construir("LOGIN", req=req, user=usuario, password=password)
