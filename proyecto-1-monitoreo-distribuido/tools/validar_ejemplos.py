#!/usr/bin/env python3
"""Valida el formato general y el tamaño de los ejemplos MCD/1.0."""

from __future__ import annotations

import re
import sys
from pathlib import Path

TIPOS = {
    "REGISTER",
    "REGISTER_OK",
    "TELEMETRY",
    "EVENT",
    "ACK",
    "LOGIN",
    "LOGIN_OK",
    "LIST",
    "STATUS",
    "HISTORY",
    "EVENTS",
    "RESPONSE",
    "ITEM",
    "ERROR",
    "BYE",
}
CLAVE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
VALOR = re.compile(r"^[A-Za-z0-9._:@/\-]{1,64}$")


def validar_linea(mensaje: str) -> list[str]:
    errores: list[str] = []
    if len(mensaje.encode("utf-8")) > 512:
        errores.append("supera 512 bytes")

    linea = mensaje.removesuffix("\n")
    partes = linea.split("|")
    if len(partes) < 2 or partes[0] != "MCD/1.0":
        return errores + ["encabezado inválido"]
    if partes[1] not in TIPOS:
        return errores + [f"tipo desconocido: {partes[1]}"]

    vistas: set[str] = set()
    for campo in partes[2:]:
        if "=" not in campo:
            errores.append(f"campo sin '=': {campo}")
            continue
        clave, valor = campo.split("=", 1)
        if not CLAVE.fullmatch(clave):
            errores.append(f"clave inválida: {clave}")
        if clave in vistas:
            errores.append(f"clave repetida: {clave}")
        vistas.add(clave)
        if not VALOR.fullmatch(valor):
            errores.append(f"valor inválido en {clave}")
    return errores


def limpiar_ejemplo(texto: str) -> str:
    mensaje = re.split(r"\s{2,}\(", texto, maxsplit=1)[0].strip("` ")
    return mensaje + "\n"


def extraer_ejemplos(ruta: Path):
    for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        inicio = linea.find("MCD/1.0|")
        if inicio < 0:
            continue
        mensaje = limpiar_ejemplo(linea[inicio:])
        if "secret=***" in mensaje or "password=***" in mensaje:
            continue
        tipo = mensaje.split("|", 2)[1] if "|" in mensaje else ""
        if tipo in TIPOS:
            yield numero, mensaje


def main() -> int:
    raiz = Path(__file__).resolve().parents[1]
    archivos = [
        raiz / "docs/protocolo/MCD-1.0.md",
        raiz / "docs/entrega1/propuesta.md",
    ]
    total = 0
    fallos: list[str] = []
    for archivo in archivos:
        for numero, mensaje in extraer_ejemplos(archivo):
            total += 1
            for error in validar_linea(mensaje):
                fallos.append(f"{archivo.relative_to(raiz)}:{numero}: {error}")

    print(f"Ejemplos MCD/1.0 revisados: {total}")
    if fallos:
        print("Errores:")
        print("\n".join(fallos))
        return 1
    print("Resultado: OK (formato general, claves únicas y máximo de 512 bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
