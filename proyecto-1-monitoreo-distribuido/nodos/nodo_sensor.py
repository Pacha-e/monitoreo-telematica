#!/usr/bin/env python3
"""Nodo 1: sensor de temperatura con batería (kind SENSOR).

Ejemplo:
  MCD_NODO_SECRET=clave-nodo-01 python3 nodos/nodo_sensor.py \\
      --servidor servidor.monitoreo.lab --puerto 5050 --id nodo-01 --period 5
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd import nodo, simuladores  # noqa: E402


def agregar_args(p):
    g = p.add_argument_group("simulador del sensor")
    g.add_argument("--temp-base", type=float, default=45.0, help="temperatura media (°C)")
    g.add_argument("--umbral-temp", type=float, default=70.0, help="umbral del evento UMBRAL_TEMP")
    g.add_argument("--bat-inicial", type=int, default=100, help="batería inicial (%%)")
    g.add_argument("--bat-seg-por-pct", type=float, default=20.0, help="segundos por cada 1%% de batería")
    g.add_argument("--prob-pico", type=float, default=0.02, help="probabilidad de pico de temperatura por muestra")


def crear(a, rng):
    return simuladores.SensorTemperatura(rng, a.temp_base, a.umbral_temp, a.bat_inicial,
                                         a.bat_seg_por_pct, a.prob_pico)


if __name__ == "__main__":
    sys.exit(nodo.principal("Nodo sensor de temperatura MCD/1.0", "SENSOR", agregar_args, crear))
