#!/usr/bin/env python3
"""Nodo 2: equipo de red (router/switch) sin batería (kind RED).

Ejemplo:
  MCD_NODO_SECRET=clave-nodo-02 python3 nodos/nodo_red.py \\
      --servidor servidor.monitoreo.lab --puerto 5050 --id nodo-02 --period 5
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd import nodo, simuladores  # noqa: E402


def agregar_args(p):
    g = p.add_argument_group("simulador del equipo de red")
    g.add_argument("--cpu-base", type=float, default=35.0, help="carga de CPU base (%%)")
    g.add_argument("--umbral-cpu", type=float, default=85.0, help="umbral del evento UMBRAL_CPU")
    g.add_argument("--prob-enlace", type=float, default=0.01, help="probabilidad de caída del enlace por muestra")


def crear(a, rng):
    return simuladores.EquipoRed(rng, a.cpu_base, a.umbral_cpu, a.prob_enlace)


if __name__ == "__main__":
    sys.exit(nodo.principal("Nodo equipo de red MCD/1.0", "RED", agregar_args, crear))
