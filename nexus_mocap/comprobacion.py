"""Comprobación con un valor conocido.

Se toma un ensayo, se desplaza en memoria un punto bien registrado y se mira si
el detector lo encuentra y cuánto se aleja su propuesta de lo que la cámara sí
midió. La diferencia en milímetros permite juzgar la estimación con datos
propios. El archivo en disco no se toca.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from nexus_mocap.lectura import Ensayo
from nexus_mocap.saltos import Parametros, detectar_saltos

SEPARACION = 5
"""Fotogramas que se dejan entre dos saltos insertados."""


@dataclass(frozen=True)
class ResultadoComprobacion:
    insertados: int
    detectados: int
    propuestos: int
    error_mediano_mm: float
    error_maximo_mm: float
    avisos_previos: int
    avisos_nuevos_falsos: int


def comprobar(
    ensayo: Ensayo,
    n: int = 50,
    magnitud_mm: float = 15.0,
    semilla: int = 0,
    parametros: Parametros | None = None,
) -> ResultadoComprobacion:
    """Inserta ``n`` saltos de ``magnitud_mm`` en una copia en memoria y mide el resultado."""
    generador = np.random.default_rng(semilla)
    previos = {(s.marcador, s.indice) for s in detectar_saltos(ensayo, parametros)}

    posiciones = ensayo.posiciones.copy()
    valido = np.all(np.isfinite(posiciones), axis=2)
    # Puntos con dos vecinos registrados a cada lado, para poder comparar.
    apto = valido.copy()
    for desplazamiento in (-2, -1, 1, 2):
        apto &= np.roll(valido, desplazamiento, axis=1)
    apto[:, :2] = False
    apto[:, -2:] = False

    elegidos: list[tuple[int, int]] = []
    fotogramas_usados: set[int] = set()
    disponibles = np.argwhere(apto)
    generador.shuffle(disponibles)
    for m, t in disponibles:
        m, t = int(m), int(t)
        # Se separan en el tiempo, también entre marcadores distintos, para que
        # cada salto sea realmente aislado. En ensayos cortos caben menos de ``n``.
        if any(t + d in fotogramas_usados for d in range(-SEPARACION, SEPARACION + 1)):
            continue
        if any((ensayo.etiquetas[m], t + d) in previos for d in range(-3, 4)):
            continue
        elegidos.append((m, t))
        fotogramas_usados.add(t)
        if len(elegidos) == n:
            break

    reales = {}
    for m, t in elegidos:
        direccion = generador.normal(size=3)
        direccion /= np.linalg.norm(direccion)
        reales[(ensayo.etiquetas[m], t)] = posiciones[m, t].copy()
        posiciones[m, t] += magnitud_mm * direccion

    alterado = replace(ensayo, posiciones=posiciones)
    encontrados = {(s.marcador, s.indice): s for s in detectar_saltos(alterado, parametros)}

    errores = []
    detectados = 0
    for clave, real in reales.items():
        salto = encontrados.get(clave)
        if salto is None:
            continue
        detectados += 1
        if salto.propuesta is not None:
            errores.append(float(np.linalg.norm(np.asarray(salto.propuesta) - real)))

    nuevos_falsos = sum(1 for clave in encontrados if clave not in reales and clave not in previos)
    return ResultadoComprobacion(
        insertados=len(elegidos),
        detectados=detectados,
        propuestos=len(errores),
        error_mediano_mm=float(np.median(errores)) if errores else float("nan"),
        error_maximo_mm=float(np.max(errores)) if errores else float("nan"),
        avisos_previos=len(previos),
        avisos_nuevos_falsos=nuevos_falsos,
    )
