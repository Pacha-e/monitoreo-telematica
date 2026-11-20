#!/usr/bin/env python3
"""Cliente de administración MCD/1.0 (consola).

Interactivo:
  MCD_PASSWORD=... python3 cliente/cliente_admin.py --servidor servidor.monitoreo.lab \\
      --puerto 5050 --usuario operador1
  mcd> panel          (estado de todos los nodos + 5 muestras + eventos, se refresca solo)

Un solo comando (para guiones y pruebas):
  ... --comando "historial nodo-01 5"

Códigos de salida: 0 bien, 2 credenciales o entrada inválida, 3 ERROR del servidor
(403, 404, 422...), 4 red (DNS, conexión o servidor caído tras los reintentos).
"""
import argparse
import getpass
import os
import shlex
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd import proto, vista  # noqa: E402
from mcd.cliente import (ClienteAdmin, ErrorCredenciales, ErrorEntrada, ErrorRed,  # noqa: E402
                         ErrorServidor)

AYUDA = """Comandos:
  lista                       nodos conocidos y su estado          (admin, operador)
  estado <nodo>               último estado y contadores           (admin, operador)
  historial <nodo> [n]        últimas n muestras, 1 a 10 (def. 5)  (admin, operador)
  eventos [n] [nodo]          últimos n eventos, 1 a 20 (def. 10)  (solo admin)
  panel                       vista completa que se refresca; Ctrl+C vuelve
  ayuda | salir"""


def _entero_env(nombre):
    v = os.environ.get(nombre)
    return int(v) if v and v.isdigit() else None


def leer_argumentos(argv=None):
    p = argparse.ArgumentParser(description="Cliente de administración MCD/1.0",
                                epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--servidor", default=os.environ.get("MCD_SERVIDOR"), help="nombre del servidor (o MCD_SERVIDOR)")
    p.add_argument("--puerto", type=int, default=_entero_env("MCD_PUERTO"))
    p.add_argument("--usuario", default=os.environ.get("MCD_USUARIO"))
    p.add_argument("--password-env", default="MCD_PASSWORD",
                   help="variable de entorno con la clave; si falta se pregunta sin eco")
    p.add_argument("--comando", action="append", help="ejecuta el comando y termina (repetible)")
    p.add_argument("--intervalo", type=float, default=5.0, help="segundos entre refrescos del panel (def. 5)")
    p.add_argument("--ciclos", type=int, default=None, help="el panel se detiene tras N refrescos")
    p.add_argument("--reintentos", type=int, default=2, help="con --comando: reintentos de red antes de rendirse")
    p.add_argument("--backoff-max", type=int, default=30)
    p.add_argument("--t-resp", type=float, default=5.0)
    p.add_argument("--log", help="archivo de log del cliente (además de stderr con --detallado)")
    p.add_argument("--detallado", action="store_true", help="muestra el intercambio de mensajes")
    a = p.parse_args(argv)
    if not a.servidor or not a.puerto or not 1 <= a.puerto <= 65535:
        p.error("faltan --servidor y --puerto (o MCD_SERVIDOR y MCD_PUERTO)")
    return a


def crear_log(a):
    return proto.log_cliente("cliente", a.log, a.detallado)


def _n(valor, defecto):
    try:
        return int(valor) if valor is not None else defecto
    except ValueError:
        raise ErrorEntrada("n debe ser un entero: %r" % valor)


def ejecutar_comando(cli, a, linea, reintentos):
    """Ejecuta un comando; devuelve False si es `salir`. Propaga los Error*."""
    partes = shlex.split(linea)
    if not partes:
        return True
    orden, args = partes[0].lower(), partes[1:]
    if orden in ("salir", "exit", "quit"):
        return False
    if orden in ("ayuda", "help", "?"):
        print(AYUDA)
        return True
    q = lambda tipo, **c: cli.consultar_resiliente(tipo, reintentos, **c)  # noqa: E731
    if orden == "lista":
        r = q("LIST")
    elif orden == "estado" and len(args) == 1:
        r = q("STATUS", node_id=args[0])
    elif orden == "historial" and 1 <= len(args) <= 2:
        r = q("HISTORY", node_id=args[0], n=_n(args[1] if len(args) > 1 else None, 5))
    elif orden == "eventos" and len(args) <= 2:
        campos = dict(n=_n(args[0] if args else None, 10))
        if len(args) == 2:
            campos["node_id"] = args[1]
        r = q("EVENTS", **campos)
    elif orden == "panel" and not args:
        panel(cli, a, reintentos)
        return True
    else:
        raise ErrorEntrada("comando no reconocido: %r (escriba ayuda)" % linea)
    print(vista.texto_resultado(r.op, r.items), flush=True)
    return True


def panel(cli, a, reintentos):
    """Refresca la vista completa cada `--intervalo` s. Si el servidor cae, avisa y
    reconecta solo (1, 2, 4... 30 s) y vuelve a pedir el LOGIN con la clave en memoria."""
    def avisar(texto):
        print("[sin conexión] " + texto, file=sys.stderr, flush=True)
    cli.avisar = avisar
    ciclo = 0
    try:
        while a.ciclos is None or ciclo < a.ciclos:
            p = cli.panel(reintentos=reintentos)
            ciclo += 1
            if sys.stdout.isatty():
                sys.stdout.write("\x1b[2J\x1b[H")
            print(vista.texto_panel(p), flush=True)
            if a.ciclos is None or ciclo < a.ciclos:
                time.sleep(a.intervalo)
    except KeyboardInterrupt:
        print()
    finally:
        cli.avisar = lambda texto: None


def mostrar_error(a, e):
    """Imprime el error al usuario y devuelve el código de salida."""
    if isinstance(e, ErrorCredenciales):
        texto, codigo = "credenciales rechazadas por el servidor (%s)" % e, 2
    elif isinstance(e, ErrorServidor):
        texto, codigo = "el servidor respondió: %s" % e, 3
    elif isinstance(e, ErrorEntrada):
        texto, codigo = "entrada inválida: %s" % e, 2
    else:
        texto, codigo = "error de red: %s" % e, 4
    print("ERROR: " + texto, file=sys.stderr, flush=True)
    return codigo


def pedir_credenciales(a):
    usuario = a.usuario or (input("Usuario: ") if sys.stdin.isatty() else "")
    password = os.environ.get(a.password_env, "")
    if not password and sys.stdin.isatty():
        password = getpass.getpass("Clave: ")
    return usuario, password


def principal(argv=None):
    a = leer_argumentos(argv)
    usuario, password = pedir_credenciales(a)
    if not usuario or not password:
        print("ERROR: faltan usuario y clave (--usuario y la variable %s)" % a.password_env, file=sys.stderr)
        return 2
    cli = ClienteAdmin(a.servidor, a.puerto, usuario, password, crear_log(a), a.t_resp, a.backoff_max)
    signal.signal(signal.SIGTERM, lambda *_: cli.parar.set())
    una_vez = a.comando is not None
    reintentos = a.reintentos if una_vez else None
    try:
        # En un solo comando el LOGIN lo hace la primera consulta; en modo interactivo se
        # hace ya, para decirle al usuario enseguida si sus credenciales sirven.
        if not una_vez:
            cli.consultar_resiliente("LIST", reintentos)   # LOGIN + prueba de la sesión
            print("Sesión iniciada como %s (%s). Escriba ayuda." % (usuario, cli.rol))
        if una_vez:
            for linea in a.comando:
                if not ejecutar_comando(cli, a, linea, reintentos):
                    break
            return 0
        while True:
            try:
                linea = input("mcd> ")
            except EOFError:
                break
            try:
                if not ejecutar_comando(cli, a, linea, reintentos):
                    break
            except (ErrorServidor, ErrorEntrada) as e:
                if isinstance(e, ErrorCredenciales):
                    raise
                mostrar_error(a, e)
        return 0
    except (ErrorServidor, ErrorEntrada, ErrorRed) as e:
        if cli.parar.is_set():                  # SIGTERM: el usuario pidió terminar, no es una falla
            return 0
        return mostrar_error(a, e)
    except KeyboardInterrupt:
        return 0
    finally:
        cli.cerrar()


if __name__ == "__main__":
    sys.exit(principal())
