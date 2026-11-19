"""Localiza los tramos en que un marcador no se registró. No rellena nada: solo los enumera."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nexus_mocap.lectura import Ensayo


@dataclass(frozen=True)
class Hueco:
    marcador: str
    fotograma_desde: int
    fotograma_hasta: int
    fotogramas: int
    segundos: float
    posicion: str  # "inicio", "medio" o "final" del ensayo


def buscar_huecos(ensayo: Ensayo) -> tuple[list[Hueco], list[str]]:
    """Devuelve los huecos, del más largo al más corto, y los marcadores sin ningún dato."""
    huecos: list[Hueco] = []
    sin_datos: list[str] = []
    n = ensayo.n_fotogramas
    for etiqueta, trayectoria in zip(ensayo.etiquetas, ensayo.posiciones, strict=True):
        ausente = ~np.all(np.isfinite(trayectoria), axis=1)
        if ausente.all():
            sin_datos.append(etiqueta)
            continue
        indices = np.flatnonzero(ausente)
        if indices.size == 0:
            continue
        for tramo in np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1):
            inicio, fin = int(tramo[0]), int(tramo[-1])
            posicion = "inicio" if inicio == 0 else "final" if fin == n - 1 else "medio"
            huecos.append(
                Hueco(
                    marcador=etiqueta,
                    fotograma_desde=ensayo.fotograma(inicio),
                    fotograma_hasta=ensayo.fotograma(fin),
                    fotogramas=tramo.size,
                    segundos=tramo.size / ensayo.frecuencia,
                    posicion=posicion,
                )
            )
    huecos.sort(key=lambda h: (-h.fotogramas, h.fotograma_desde, h.marcador))
    return huecos, sin_datos
