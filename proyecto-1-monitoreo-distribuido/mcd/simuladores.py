"""Simuladores de dos nodos distintos (requisito 1: al menos dos nodos).

Cada simulador entrega una muestra por periodo y, si corresponde, los eventos
que esa muestra provoca. Los eventos se disparan al *cruzar* un umbral (no en
cada muestra por encima de él), para no inundar la cola de pendientes.
"""
import math
import random


def _limitar(x, minimo, maximo):
    return max(minimo, min(maximo, x))


class Simulador:
    """Interfaz: muestra(t) -> dict; eventos(muestra) -> [(nivel, evento, valor)]."""

    kind = "OTRO"

    def muestra(self, t):
        raise NotImplementedError

    def eventos(self, m):
        return []


class SensorTemperatura(Simulador):
    """Sensor de ambiente alimentado por batería (kind SENSOR).

    Temperatura ondulante alrededor de `temp_base`, batería que baja un 1 % cada
    `seg_por_pct` segundos y un estado operativo que degrada al pasar el umbral.
    Eventos: UMBRAL_TEMP (CRITICO), BATERIA_BAJA (ADVERTENCIA) y CAMBIO_ESTADO.
    """

    kind = "SENSOR"

    def __init__(self, rng, temp_base=45.0, umbral_temp=70.0, bat_inicial=100,
                 seg_por_pct=20.0, prob_pico=0.02):
        self.rng = rng
        self.temp_base = temp_base
        self.umbral = umbral_temp
        self.bat_inicial = bat_inicial
        self.seg_por_pct = seg_por_pct
        self.prob_pico = prob_pico
        self._pico = 0
        self._sobre_umbral = False
        self._bateria_avisada = False
        self._opstate_previo = None

    def muestra(self, t):
        if self._pico == 0 and self.rng.random() < self.prob_pico:
            self._pico = 3                       # tres muestras calientes
        temp = self.temp_base + 6.0 * math.sin(t / 30.0) + self.rng.gauss(0, 0.7)
        if self._pico:
            temp += 30.0
            self._pico -= 1
        temp = _limitar(temp, -40.0, 150.0)
        bat = int(_limitar(self.bat_inicial - t / self.seg_por_pct, 0, 100))
        cpu = _limitar(12.0 + self.rng.gauss(0, 4.0), 0.0, 100.0)
        if temp > self.umbral + 15:
            opstate = "FALLA"
        elif temp > self.umbral or bat <= 5:
            opstate = "DEGRADADO"
        else:
            opstate = "OK"
        return dict(cpu=cpu, temp=temp, bat=bat, opstate=opstate)

    def eventos(self, m):
        salida = []
        if m["temp"] > self.umbral and not self._sobre_umbral:
            self._sobre_umbral = True
            salida.append(("CRITICO", "UMBRAL_TEMP", "%.1f" % m["temp"]))
        elif m["temp"] < self.umbral - 3:
            self._sobre_umbral = False
        if m["bat"] <= 20 and not self._bateria_avisada:
            self._bateria_avisada = True
            salida.append(("ADVERTENCIA", "BATERIA_BAJA", str(m["bat"])))
        if self._opstate_previo not in (None, m["opstate"]):
            salida.append(("INFO", "CAMBIO_ESTADO", m["opstate"]))
        self._opstate_previo = m["opstate"]
        return salida


class EquipoRed(Simulador):
    """Router/switch alimentado por red eléctrica (kind RED, sin batería: `bat=NA`).

    Carga de CPU que sube y baja, temperatura estable y un enlace que puede
    caerse unos periodos (con probabilidad `prob_enlace` por muestra).
    Eventos: UMBRAL_CPU (ADVERTENCIA) y CONECTIVIDAD (CRITICO al caer el enlace,
    INFO al restaurarse).
    """

    kind = "RED"

    def __init__(self, rng, cpu_base=35.0, umbral_cpu=85.0, prob_enlace=0.01):
        self.rng = rng
        self.cpu_base = cpu_base
        self.umbral = umbral_cpu
        self.prob_enlace = prob_enlace
        self._enlace_caido = 0
        self._sobre_umbral = False
        self._aviso_enlace = None

    def muestra(self, t):
        cpu = self.cpu_base + 30.0 * abs(math.sin(t / 25.0)) + self.rng.gauss(0, 2.0)
        cpu = _limitar(cpu, 0.0, 100.0)
        temp = _limitar(38.0 + cpu / 10.0 + self.rng.gauss(0, 0.5), -40.0, 150.0)
        if self._enlace_caido == 0 and self.rng.random() < self.prob_enlace:
            self._enlace_caido = 3
            self._aviso_enlace = "ENLACE_CAIDO"
        opstate = "OK"
        if self._enlace_caido:
            opstate = "DEGRADADO"
            self._enlace_caido -= 1
            if self._enlace_caido == 0:
                self._aviso_enlace = "ENLACE_RESTAURADO"
        return dict(cpu=cpu, temp=temp, bat="NA", opstate=opstate)

    def eventos(self, m):
        salida = []
        if m["cpu"] > self.umbral and not self._sobre_umbral:
            self._sobre_umbral = True
            salida.append(("ADVERTENCIA", "UMBRAL_CPU", "%.1f" % m["cpu"]))
        elif m["cpu"] < self.umbral - 5:
            self._sobre_umbral = False
        if self._aviso_enlace:
            nivel = "CRITICO" if self._aviso_enlace == "ENLACE_CAIDO" else "INFO"
            salida.append((nivel, "CONECTIVIDAD", self._aviso_enlace))
            self._aviso_enlace = None
        return salida


def generador(semilla=None):
    return random.Random(semilla)
