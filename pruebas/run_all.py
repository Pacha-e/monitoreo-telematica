#!/usr/bin/env python3
"""Suite completa del servidor MCD/1.0: compila, levanta un LDAP de laboratorio
y corre todas las pruebas contra `servidor`. Con --asan repite la suite contra
`servidor_asan` (AddressSanitizer y UBSan).

Cada prueba imprime 'PASA nombre' o 'FALLA nombre: detalle'; al final
'TOTAL: n pasan, m fallan'. Sale con codigo 0 solo si no falla nada.
Los procesos hijos (servidor, slapd) se matan siempre, incluso ante excepcion.

  python3 pruebas/run_all.py           # binario normal
  python3 pruebas/run_all.py --asan    # ademas, el binario con ASan y UBSan
"""
import argparse
import atexit
import os
import signal
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mcdlib                                       # noqa: E402
from mcdlib import Ctx, LdapLab, PRUEBAS, SERVIDOR_DIR, limpiar_todo  # noqa: E402
import casos_nodos, casos_clientes, casos_robustez  # noqa: E402,F401  (registran pruebas)
import casos_integracion, casos_fakes                 # noqa: E402,F401  (nodos y cliente reales)

RESULTADOS = {"pasan": 0, "fallan": 0}
MARCAS_SANITIZER = ("AddressSanitizer", "runtime error", "LeakSanitizer",
                    "UndefinedBehaviorSanitizer", "ThreadSanitizer")


def pasa(nombre):
    RESULTADOS["pasan"] += 1
    print("PASA " + nombre, flush=True)


def falla(nombre, detalle):
    RESULTADOS["fallan"] += 1
    detalle = " ".join(str(detalle).split())
    print("FALLA %s: %s" % (nombre, detalle[:600]), flush=True)


def ejecutar(nombre, f, *args):
    try:
        f(*args)
        pasa(nombre)
    except AssertionError as e:
        falla(nombre, e)
    except Exception as e:                      # error de la prueba o del entorno
        falla(nombre, "%s: %s | %s" % (type(e).__name__, e,
                                       traceback.format_exc().strip().splitlines()[-3]))


def make(*objetivos):
    r = subprocess.run(["make", "-C", SERVIDOR_DIR] + list(objetivos),
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def compilar(asan):
    def sin_warnings(objetivos, binario):
        def f():
            rc, salida = make(*objetivos)
            if rc != 0:
                raise AssertionError("make fallo:\n" + salida[-800:])
            if "warning" in salida.lower():
                raise AssertionError("hay warnings:\n" + salida[-800:])
            if not os.path.exists(os.path.join(SERVIDOR_DIR, binario)):
                raise AssertionError("no se genero " + binario)
        return f
    ejecutar("compilacion_make_clean_all_sin_warnings", sin_warnings(["clean", "all"], "servidor"))
    if asan:
        ejecutar("compilacion_make_asan_sin_warnings", sin_warnings(["asan"], "servidor_asan"))


def revisar_sanitizers(ctx):
    """Tras detener los servidores: salida 0 y nada de ASan/UBSan/LSan en stderr."""
    for s, rc in ctx.detener_todo():
        err = s.stderr()
        marcas = [m for m in MARCAS_SANITIZER if m in err]
        if marcas:
            raise AssertionError("%s reporto %s: %s" % (os.path.basename(s.dir), marcas, err[:500]))
        if rc != 0:
            raise AssertionError("%s termino con codigo %s: %s" % (os.path.basename(s.dir), rc, err[:300]))


def variante(etiqueta, binario, ldap):
    sufijo = "" if etiqueta == "normal" else "@" + etiqueta
    try:
        ctx = Ctx(binario, ldap, etiqueta)
    except Exception as e:
        falla("arranque_servidor" + sufijo, e)
        return
    try:
        for f in PRUEBAS:
            ejecutar(f.__name__ + sufijo, f, ctx)
    finally:
        ejecutar("salida_limpia_sin_errores_de_sanitizers" + sufijo, revisar_sanitizers, ctx)


def principal(asan):
    atexit.register(limpiar_todo)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(143))
    ldap = None
    try:
        compilar(asan)
        ldap = LdapLab()
        ldap.iniciar()
        print("# LDAP de laboratorio en el puerto %d" % ldap.puerto, flush=True)
        variante("normal", os.path.join(SERVIDOR_DIR, "servidor"), ldap)
        if asan:
            variante("asan", os.path.join(SERVIDOR_DIR, "servidor_asan"), ldap)
    except Exception:
        falla("suite", traceback.format_exc())
    finally:
        if ldap is not None:
            ldap.detener()
        limpiar_todo()
    print("TOTAL: %d pasan, %d fallan" % (RESULTADOS["pasan"], RESULTADOS["fallan"]), flush=True)
    return 0 if RESULTADOS["fallan"] == 0 and RESULTADOS["pasan"] > 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Suite de pruebas del servidor MCD/1.0")
    ap.add_argument("--asan", action="store_true", help="ademas, compila y prueba servidor_asan")
    sys.exit(principal(ap.parse_args().asan))
