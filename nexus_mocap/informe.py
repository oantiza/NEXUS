"""Salida para la revisión: una tabla y una figura por cada salto propuesto."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np

from nexus_mocap.lectura import Ensayo
from nexus_mocap.saltos import EJES, Salto

COLUMNAS = (
    "marcador",
    "fotograma",
    "tiempo_s",
    "eje",
    "desviacion_mm",
    "clasificacion",
    "confianza",
    "original_x",
    "original_y",
    "original_z",
    "propuesta_x",
    "propuesta_y",
    "propuesta_z",
    "referencias",
    "acompanan",
    "otros_marcadores_a_la_vez",
)


def _numero(valor: float, decimales: int = 2) -> str:
    """Número con coma decimal, que es como lo abre Excel en español."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def escribir_csv(saltos: list[Salto], ruta: Path) -> None:
    """Escribe la tabla de saltos (separador ``;`` y coma decimal)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        tabla = csv.writer(archivo, delimiter=";")
        tabla.writerow(COLUMNAS)
        for s in saltos:
            propuesta = [_numero(v) for v in s.propuesta] if s.propuesta else ["", "", ""]
            tabla.writerow(
                [
                    s.marcador,
                    s.fotograma,
                    _numero(s.tiempo_s, 3),
                    s.eje,
                    _numero(s.desviacion_mm),
                    s.clasificacion,
                    s.confianza,
                    *[_numero(v) for v in s.original],
                    *propuesta,
                    " ".join(s.referencias),
                    " ".join(s.acompanan),
                    s.simultaneos,
                ]
            )


def dibujar_salto(ensayo: Ensayo, salto: Salto, ruta: Path, margen: int = 6) -> None:
    """Dibuja el tramo original y, si la hay, la posición propuesta al lado."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    m = ensayo.etiquetas.index(salto.marcador)
    eje = EJES.index(salto.eje)
    inicio = max(0, salto.indice - margen)
    fin = min(ensayo.n_fotogramas, salto.indice + margen + 1)
    fotogramas = np.arange(inicio, fin) + ensayo.primer_fotograma
    valores = ensayo.posiciones[m, inicio:fin, eje]

    # Se resta el avance medio del tramo para que un salto de pocos milímetros
    # se vea aunque el marcador se esté desplazando decenas de centímetros.
    apoyo = np.isfinite(valores) & (fotogramas != salto.fotograma)
    if apoyo.sum() >= 2:
        pendiente, corte = np.polyfit(fotogramas[apoyo], valores[apoyo], 1)
    else:
        pendiente, corte = 0.0, float(np.nanmean(valores))

    def relativo(fotograma, valor):
        return valor - (pendiente * fotograma + corte)

    figura, ax = plt.subplots(figsize=(7, 3.2))
    ax.plot(
        fotogramas,
        relativo(fotogramas, valores),
        "-o",
        color="#34495e",
        markersize=4,
        label="Registro original",
    )
    if salto.propuesta is not None:
        vecinos = np.array([salto.fotograma - 1, salto.fotograma, salto.fotograma + 1])
        tramo = np.array(
            [
                ensayo.posiciones[m, salto.indice - 1, eje],
                salto.propuesta[eje],
                ensayo.posiciones[m, salto.indice + 1, eje],
            ]
        )
        ax.plot(vecinos, relativo(vecinos, tramo), "--", color="#0b7a6b")
        ax.plot(
            [salto.fotograma],
            [relativo(salto.fotograma, salto.propuesta[eje])],
            "D",
            color="#0b7a6b",
            markerfacecolor="white",
            markersize=7,
            label="Posición propuesta",
        )
    ax.set_xlabel("Fotograma")
    ax.set_ylabel(f"{salto.eje} respecto al avance del tramo (mm)")
    ax.set_title(
        f"{salto.marcador} · fotograma {salto.fotograma} · "
        f"{salto.desviacion_mm:.1f} mm · {salto.clasificacion}, confianza {salto.confianza}",
        fontsize=9,
    )
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    figura.tight_layout()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    figura.savefig(ruta, dpi=130)
    plt.close(figura)


def nombre_figura(salto: Salto) -> str:
    marcador = re.sub(r"[^A-Za-z0-9_-]", "_", salto.marcador)
    return f"{salto.fotograma:06d}_{marcador}.png"
