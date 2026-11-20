#!/usr/bin/env python3
"""Levanta la demostración completa: LDAP de laboratorio + servidor en C + dos nodos
(sensor y equipo de red) y deja listo el cliente. Se detiene con demo/detener_demo.py.

  python3 demo/iniciar_demo.py                  # arranca todo y muestra cómo usar el cliente
  python3 demo/iniciar_demo.py --abrir-cliente  # además abre el cliente de consola (admin1)
  python3 demo/iniciar_demo.py --puerto 6000 --period 3

Todo corre como usuario normal (sin root), en puertos altos. El estado (pids, logs, base del
LDAP) vive en un directorio temporal (por defecto <tmp>/mcd-demo, o MCD_DEMO_DIR); el proyecto
no se ensucia. Las claves son las ficticias de infra/ldap/base.ldif.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "localhost"            # nombre, resuelto con getaddrinfo por cada programa
ADMIN = ("admin1", "clave-admin-lab1")
OPERADOR = ("operador1", "clave-operador-lab1")


def directorio_estado(arg=None):
    return arg or os.environ.get("MCD_DEMO_DIR") or os.path.join(tempfile.gettempdir(), "mcd-demo")


def vivo(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def esperar(cond, plazo, que):
    fin = time.time() + plazo
    while time.time() < fin:
        if cond():
            return
        time.sleep(0.2)
    sys.exit("ERROR: no se logró %s en %d s; revise los logs en el directorio de la demo." % (que, plazo))


def tcp_abierto(puerto):
    try:
        socket.create_connection((HOST, puerto), 0.5).close()
        return True
    except OSError:
        return False


def lanzar(args, log, env=None):
    """Proceso independiente de esta terminal (sigue vivo al terminar el script)."""
    f = open(log, "ab")
    p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=f, stderr=f, start_new_session=True,
                         env=env or dict(os.environ))
    return p.pid


def compilar_servidor():
    binario = os.path.join(RAIZ, "servidor", "servidor")
    fuentes = [os.path.join(RAIZ, "servidor", d, n) for d in ("src", "include")
               for n in os.listdir(os.path.join(RAIZ, "servidor", d))]
    if not os.path.exists(binario) or os.path.getmtime(binario) < max(os.path.getmtime(f) for f in fuentes):
        print("Compilando el servidor (make -C servidor)...")
        r = subprocess.run(["make", "-C", os.path.join(RAIZ, "servidor")], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("ERROR: falló la compilación:\n" + r.stdout[-1500:] + r.stderr[-1500:])
    return binario


def preparar_ldap(dir_, puerto):
    slapd = shutil.which("slapd") or "/usr/sbin/slapd"
    slapadd = shutil.which("slapadd") or "/usr/sbin/slapadd"
    for herramienta in (slapd, slapadd):
        if not os.path.exists(herramienta):
            sys.exit("ERROR: falta %s. Instale OpenLDAP: sudo apt install slapd ldap-utils" % herramienta)
    base = os.path.join(dir_, "ldap")
    os.makedirs(os.path.join(base, "db"), exist_ok=True)
    conf = os.path.join(base, "slapd.conf")
    with open(os.path.join(RAIZ, "infra", "ldap", "slapd.conf.plantilla")) as f:
        texto = f.read().replace("@DIR@", base)
    with open(conf, "w") as f:
        f.write(texto)
    if not os.path.exists(os.path.join(base, "db", "data.mdb")):
        subprocess.run([slapadd, "-f", conf, "-l", os.path.join(RAIZ, "infra", "ldap", "base.ldif")],
                       check=True, capture_output=True)
    pidfile = os.path.join(base, "slapd.pid")
    if os.path.exists(pidfile):
        os.remove(pidfile)
    # slapd se pone en segundo plano por sí solo; el pid válido queda en slapd.pid.
    subprocess.run([slapd, "-f", conf, "-h", "ldap://%s:%d/" % (HOST, puerto)], check=True,
                   stdout=open(os.path.join(dir_, "slapd.log"), "ab"), stderr=subprocess.STDOUT)
    esperar(lambda: tcp_abierto(puerto) and os.path.exists(pidfile), 10, "arrancar slapd")
    return int(open(pidfile).read().strip())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--puerto", type=int, default=5050, help="puerto TCP/UDP del servidor (def. 5050)")
    p.add_argument("--ldap-puerto", type=int, default=3899)
    p.add_argument("--period", type=int, default=2, help="segundos entre telemetrías de los nodos")
    p.add_argument("--dir", help="directorio de estado de la demo")
    p.add_argument("--abrir-cliente", action="store_true", help="abre el cliente de consola como admin1")
    a = p.parse_args()
    dir_ = directorio_estado(a.dir)
    os.makedirs(dir_, exist_ok=True)
    open(os.path.join(dir_, ".mcd-demo"), "w").close()      # marca: solo así --borrar elimina el directorio
    estado_f = os.path.join(dir_, "estado.json")
    if os.path.exists(estado_f):
        previo = json.load(open(estado_f))
        if any(vivo(x["pid"]) for x in previo["procesos"]):
            sys.exit("La demo ya está levantada (%s). Deténgala con: python3 demo/detener_demo.py" % dir_)
    if tcp_abierto(a.puerto) or tcp_abierto(a.ldap_puerto):
        sys.exit("ERROR: el puerto %d o el %d ya está en uso; use --puerto / --ldap-puerto." % (a.puerto, a.ldap_puerto))

    servidor = compilar_servidor()
    procesos = []

    def registrar(nombre, pid):
        procesos.append({"nombre": nombre, "pid": pid})
        json.dump({"dir": dir_, "puerto": a.puerto, "ldap_puerto": a.ldap_puerto, "procesos": procesos},
                  open(estado_f, "w"), indent=1)

    try:
        print("1/4 LDAP de laboratorio en %s:%d ..." % (HOST, a.ldap_puerto))
        registrar("slapd", preparar_ldap(dir_, a.ldap_puerto))

        print("2/4 Servidor MCD/1.0 en el puerto %d (TCP y UDP) ..." % a.puerto)
        env = dict(os.environ, MCD_LDAP_HOST=HOST, MCD_LDAP_PORT=str(a.ldap_puerto))
        registrar("servidor", lanzar([servidor, str(a.puerto), os.path.join(dir_, "servidor.log")],
                                     os.path.join(dir_, "servidor.stdout"), env))
        esperar(lambda: tcp_abierto(a.puerto), 10, "arrancar el servidor")

        print("3/4 Nodos: nodo-01 (sensor) y nodo-02 (equipo de red) ...")
        for nid, prog, extra in (("nodo-01", "nodo_sensor.py", ["--temp-base", "62", "--umbral-temp", "66",
                                                                "--forzar-evento", "INFO:CAMBIO_ESTADO:OK"]),
                                 ("nodo-02", "nodo_red.py", ["--prob-enlace", "0.05"])):
            registrar(nid, lanzar(
                [sys.executable, os.path.join(RAIZ, "nodos", prog), "--servidor", HOST, "--puerto", str(a.puerto),
                 "--id", nid, "--period", str(a.period), "--log", os.path.join(dir_, nid + ".log")] + extra,
                os.path.join(dir_, nid + ".stdout"), dict(os.environ, MCD_NODO_SECRET="clave-" + nid)))
        time.sleep(a.period * 3 + 1)      # que haya varias muestras que mostrar
    except BaseException:
        print("Algo falló: se detiene lo que ya se había levantado.", file=sys.stderr)
        for x in reversed(procesos):
            try:
                os.kill(x["pid"], 15)
            except ProcessLookupError:
                pass
        raise

    cmd = "python3 cliente/cliente_admin.py --servidor %s --puerto %d" % (HOST, a.puerto)
    print("4/4 Listo. Archivos de log en %s" % dir_)
    print("""
Cliente (en otra terminal, desde la raíz del proyecto):
  MCD_PASSWORD=%s %s --usuario %s          # administrador: ve eventos
  MCD_PASSWORD=%s %s --usuario %s       # operador: no puede pedir eventos (403)
  ... --comando "historial nodo-01 5"                          # un solo comando

Para ver al servidor registrar peticiones y respuestas:  tail -f %s
Para detener todo:                                       python3 demo/detener_demo.py
""" % (ADMIN[1], cmd, ADMIN[0], OPERADOR[1], cmd, OPERADOR[0], os.path.join(dir_, "servidor.log")))
    if a.abrir_cliente:
        os.chdir(RAIZ)
        os.environ["MCD_PASSWORD"] = ADMIN[1]
        os.execv(sys.executable, [sys.executable, "cliente/cliente_admin.py", "--servidor", HOST,
                                  "--puerto", str(a.puerto), "--usuario", ADMIN[0]])


if __name__ == "__main__":
    main()
