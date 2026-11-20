"""Crea un C3D de marcha simulada, para probar el programa sin ninguna grabación real.

Uso: python scripts/ensayo_sintetico.py datos/sintetico/marcha_sintetica.c3d
"""

import sys
from pathlib import Path

import ezc3d
import numpy as np

FRECUENCIA = 100.0
BALANCEO_S = 0.4
CICLO_S = 1.1
ETIQUETAS = ("LHEE", "LTOE", "LANK", "RHEE", "RTOE", "RANK")


def _avance(t: np.ndarray, inicio: float, longitud: float = 1200.0) -> np.ndarray:
    u = np.clip((t - inicio) / BALANCEO_S, 0.0, 1.0)
    return longitud * (10 * u**3 - 15 * u**4 + 6 * u**5)


def crear(ruta: Path, ciclos: int = 5) -> Path:
    generador = np.random.default_rng(11)
    t = np.arange(int((ciclos * CICLO_S + 1.0) * FRECUENCIA)) / FRECUENCIA
    puntos = np.ones((4, len(ETIQUETAS), t.size))
    indice = 0
    for desfase, lateral in ((0.0, 100.0), (CICLO_S / 2, -100.0)):
        x = sum(_avance(t, 0.4 + desfase + CICLO_S * i) for i in range(ciclos))
        for delante, alto in ((0.0, 40.0), (180.0, 30.0), (60.0, 90.0)):  # talón, punta, tobillo
            puntos[0, indice] = x + delante
            puntos[1, indice] = lateral
            puntos[2, indice] = alto
            indice += 1
    puntos[:3] += generador.normal(scale=0.3, size=puntos[:3].shape)
    puntos[:3, 1, 250:262] = np.nan  # un tramo con la punta izquierda perdida

    c3d = ezc3d.c3d()
    c3d["parameters"]["POINT"]["RATE"]["value"] = [FRECUENCIA]
    c3d["parameters"]["POINT"]["UNITS"]["value"] = ["mm"]
    c3d["parameters"]["POINT"]["LABELS"]["value"] = ETIQUETAS
    c3d["data"]["points"] = puntos
    ruta.parent.mkdir(parents=True, exist_ok=True)
    c3d.write(str(ruta))
    return ruta


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("datos") / "sintetico" / "marcha_sintetica.c3d"
    print(crear(destino))
