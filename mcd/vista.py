"""Presentación en texto de las respuestas del servidor (consola).
No hace red: solo da formato a diccionarios de campos."""
import time


def hora(epoch):
    """HH:MM:SS UTC de un campo epoch, o '-' si es NA o inválido."""
    try:
        return time.strftime("%H:%M:%S", time.gmtime(int(epoch)))
    except (TypeError, ValueError, OverflowError):
        return "-"


def tabla(columnas, filas):
    """Tabla de texto alineada. `columnas` = [(título, clave)]; `filas` = [dict]."""
    celdas = [[str(f.get(k, "-")) for _, k in columnas] for f in filas]
    anchos = [max([len(t)] + [len(r[i]) for r in celdas]) for i, (t, _) in enumerate(columnas)]
    linea = lambda vals: "  ".join(v.ljust(a) for v, a in zip(vals, anchos)).rstrip()  # noqa: E731
    return "\n".join([linea([t for t, _ in columnas]), linea(["-" * a for a in anchos])]
                     + [linea(r) for r in celdas])


def _con_horas(items, *claves):
    salida = []
    for it in items:
        f = dict(it)
        for k in claves:
            if k in f:
                f[k] = hora(f[k])
        salida.append(f)
    return salida


COLUMNAS_LISTA = [("NODO", "node_id"), ("TIPO", "kind"), ("ESTADO", "state"), ("ULTIMA MUESTRA (UTC)", "last_seen")]
COLUMNAS_ESTADO = [("NODO", "node_id"), ("ESTADO", "state"), ("ULT.(UTC)", "last_seen"), ("SEQ", "seq"),
                   ("CPU%", "cpu"), ("TEMP", "temp"), ("BAT%", "bat"), ("OPERATIVO", "opstate"),
                   ("UPTIME", "uptime"), ("PERDIDAS", "lost"), ("DUPL", "dups"), ("DESORD", "ooo")]
COLUMNAS_HISTORIAL = [("SEQ", "seq"), ("HORA NODO (UTC)", "ts"), ("CPU%", "cpu"), ("TEMP", "temp"),
                      ("BAT%", "bat"), ("OPERATIVO", "opstate")]
COLUMNAS_EVENTOS = [("HORA (UTC)", "ts"), ("NODO", "node_id"), ("MSG_ID", "msg_id"), ("NIVEL", "level"),
                    ("EVENTO", "event"), ("VALOR", "value")]


def texto_resultado(op, items):
    """Texto de la respuesta a LIST, STATUS, HISTORY o EVENTS."""
    if not items:
        return "(sin resultados)"
    if op == "LIST":
        return tabla(COLUMNAS_LISTA, _con_horas(items, "last_seen"))
    if op == "STATUS":
        return tabla(COLUMNAS_ESTADO, _con_horas(items, "last_seen"))
    if op == "HISTORY":
        return tabla(COLUMNAS_HISTORIAL, _con_horas(items, "ts"))
    return tabla(COLUMNAS_EVENTOS, _con_horas(items, "ts"))


def texto_panel(p):
    """Pantalla completa: estado de cada nodo, sus últimas muestras y los eventos."""
    partes = ["MONITOREO MCD/1.0 · usuario %s (%s) · %s UTC" % (p["usuario"], p["rol"], hora(p["ts"])), ""]
    if not p["nodos"]:
        partes.append("(no hay nodos registrados)")
    else:
        partes.append("Estado instantáneo")
        partes.append(tabla(COLUMNAS_ESTADO, _con_horas([n["estado"] for n in p["nodos"]], "last_seen")))
        for n in p["nodos"]:
            partes += ["", "Historial de %s (últimas %d muestras, la más reciente primero)"
                       % (n["estado"]["node_id"], len(n["historial"])),
                       texto_resultado("HISTORY", n["historial"])]
    if p["eventos"] is not None:
        partes += ["", "Últimos eventos", texto_resultado("EVENTS", p["eventos"])]
    return "\n".join(partes)
