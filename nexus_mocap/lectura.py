"""Lectura de grabaciones C3D. Solo lectura: este módulo nunca escribe en el archivo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Grupos de POINT que en los C3D de Vicon contienen resultados del modelo
# (ángulos, fuerzas...) y no posiciones de marcadores.
_GRUPOS_NO_MARCADOR = ("ANGLES", "FORCES", "MOMENTS", "POWERS", "SCALARS")

_A_MILIMETROS = {"mm": 1.0, "cm": 10.0, "dm": 100.0, "m": 1000.0}


@dataclass(frozen=True)
class Ensayo:
    """Trayectorias de los marcadores de una grabación.

    ``posiciones`` tiene forma (marcadores, fotogramas, 3), en milímetros, con
    NaN donde el marcador no se registró. ``primer_fotograma`` conserva la
    numeración original del archivo, que es la que se ve en Nexus.
    """

    ruta: Path
    etiquetas: tuple[str, ...]
    posiciones: np.ndarray
    frecuencia: float
    primer_fotograma: int

    @property
    def n_fotogramas(self) -> int:
        return self.posiciones.shape[1]

    def fotograma(self, indice: int) -> int:
        """Número de fotograma original que corresponde a una posición del array."""
        return self.primer_fotograma + int(indice)

    def tiempo(self, indice: int) -> float:
        """Tiempo en segundos, con el mismo origen que los eventos del C3D."""
        return (self.fotograma(indice) - 1) / self.frecuencia


def _valores(grupo: dict, prefijo: str) -> list[str]:
    """Une LABELS, LABELS2, LABELS3... (los C3D parten las listas largas)."""
    claves = sorted(
        (c for c in grupo if c == prefijo or (c.startswith(prefijo) and c[len(prefijo) :].isdigit())),
        key=lambda c: int(c[len(prefijo) :] or 1),
    )
    valores: list[str] = []
    for clave in claves:
        valores.extend(str(v).strip() for v in grupo[clave]["value"])
    return valores


def leer_c3d(
    ruta: str | Path,
    marcadores: list[str] | None = None,
    incluir_sin_etiquetar: bool = False,
) -> Ensayo:
    """Lee un C3D y devuelve las trayectorias de sus marcadores.

    Se descartan las salidas del modelo (ángulos, fuerzas, momentos, potencias)
    y, salvo que se pida lo contrario, las trayectorias sin etiquetar (``*12``).
    ``marcadores`` limita la lectura a esas etiquetas; se acepta el nombre con o
    sin el prefijo del sujeto (``LHEE`` o ``Paciente:LHEE``).
    """
    import ezc3d

    ruta = Path(ruta)
    if not ruta.is_file():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")

    c3d = ezc3d.c3d(str(ruta))
    grupo = c3d["parameters"]["POINT"]
    puntos = np.asarray(c3d["data"]["points"], dtype=float)  # (4, puntos, fotogramas)
    n_puntos = puntos.shape[1]

    etiquetas = _valores(grupo, "LABELS")[:n_puntos]
    etiquetas += [f"*{i + 1}" for i in range(len(etiquetas), n_puntos)]

    no_marcador: set[str] = set()
    for nombre in _GRUPOS_NO_MARCADOR:
        no_marcador.update(_valores(grupo, nombre))

    pedidos = {m.split(":")[-1] for m in marcadores} if marcadores else None
    indices = []
    for i, etiqueta in enumerate(etiquetas):
        corta = etiqueta.split(":")[-1]
        if etiqueta in no_marcador:
            continue
        if pedidos is not None:
            if corta in pedidos:
                indices.append(i)
            continue
        if not incluir_sin_etiquetar and (corta.startswith("*") or not corta):
            continue
        indices.append(i)

    if pedidos is not None:
        encontrados = {etiquetas[i].split(":")[-1] for i in indices}
        faltan = sorted(pedidos - encontrados)
        if faltan:
            raise ValueError(f"Marcadores que no están en el archivo: {', '.join(faltan)}")
    if not indices:
        raise ValueError(f"El archivo no contiene trayectorias de marcadores: {ruta}")

    unidades = _valores(grupo, "UNITS")
    unidad = unidades[0].lower() if unidades else "mm"
    escala = _A_MILIMETROS.get(unidad)
    if escala is None:
        raise ValueError(f"Unidades de posición no reconocidas en el archivo: {unidad!r}")

    posiciones = np.transpose(puntos[:3, indices, :], (1, 2, 0)) * escala
    # Algunos programas guardan el marcador ausente como (0, 0, 0).
    ausente = np.all(posiciones == 0.0, axis=2) | np.any(np.isnan(posiciones), axis=2)
    posiciones[ausente] = np.nan

    return Ensayo(
        ruta=ruta,
        etiquetas=tuple(etiquetas[i] for i in indices),
        posiciones=posiciones,
        frecuencia=float(c3d["header"]["points"]["frame_rate"]),
        primer_fotograma=int(c3d["header"]["points"]["first_frame"]) + 1,
    )
