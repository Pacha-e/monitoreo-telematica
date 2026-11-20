#!/usr/bin/env python3
"""Detiene todo lo que levantó demo/iniciar_demo.py (nodos, servidor y LDAP).

  python3 demo/detener_demo.py            # detiene los procesos y conserva los logs
  python3 demo/detener_demo.py --borrar   # además borra el directorio de estado de la demo

Cada proceso recibe SIGTERM (cierre ordenado: los nodos envían BYE, el servidor libera sus
hilos) y, si no termina en 10 s, SIGKILL. Es seguro ejecutarlo varias veces.
"""
import argparse
import json
import os
import shutil
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iniciar_demo import directorio_estado, vivo  # noqa: E402


def detener(pid, nombre):
    if not vivo(pid):
        print("  %-9s (pid %d) ya no corría" % (nombre, pid))
        return True
    os.kill(pid, signal.SIGTERM)
    fin = time.time() + 10
    while time.time() < fin and vivo(pid):
        time.sleep(0.1)
    if vivo(pid):
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.3)
        print("  %-9s (pid %d) no respondió a SIGTERM: SIGKILL" % (nombre, pid))
    else:
        print("  %-9s (pid %d) detenido" % (nombre, pid))
    return not vivo(pid)


def borrar_directorio(dir_, borrar):
    """Solo borra directorios creados por iniciar_demo.py (tienen la marca .mcd-demo)."""
    if borrar and os.path.exists(os.path.join(dir_, ".mcd-demo")):
        shutil.rmtree(dir_, ignore_errors=True)
        print("Directorio %s borrado." % dir_)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", help="directorio de estado de la demo (def. el mismo de iniciar_demo.py)")
    p.add_argument("--borrar", action="store_true", help="borra también logs y base del LDAP")
    a = p.parse_args()
    dir_ = directorio_estado(a.dir)
    estado_f = os.path.join(dir_, "estado.json")
    if not os.path.exists(estado_f):
        print("No hay una demo registrada en %s (nada que detener)." % dir_)
        borrar_directorio(dir_, a.borrar)
        return 0
    procesos = json.load(open(estado_f))["procesos"]
    print("Deteniendo la demo de %s:" % dir_)
    todo_ok = True
    for x in reversed(procesos):                # nodos primero, LDAP al final
        todo_ok = detener(x["pid"], x["nombre"]) and todo_ok
    if todo_ok:
        os.remove(estado_f)
    if a.borrar and todo_ok:
        borrar_directorio(dir_, True)
    elif todo_ok:
        print("Logs conservados en %s (use --borrar para eliminarlos)." % dir_)
    return 0 if todo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
