"""Detección de saltos de un solo fotograma en trayectorias de marcadores.

El caso que se busca es el que describe la revisión manual: un marcador que se
desplaza durante un fotograma y vuelve a su sitio en el siguiente, sin que el
paciente haga ese movimiento.

Cómo se decide, para cada marcador y fotograma:

1. Se compara el punto con la posición que cabría esperar por sus vecinos (dos a
   cada lado cuando están registrados). Esa diferencia (la *desviación*) tiene
   que superar un umbral en milímetros y, además, varias veces la variación
   habitual de ese marcador en ese tramo. Así un registro más ruidoso o un gesto
   brusco suben el umbral en lugar de disparar avisos.
2. Tiene que «salir y volver»: los fotogramas vecinos deben quedar desplazados
   en sentido contrario, que es la huella de un punto aislado fuera de sitio. Un
   cambio brusco de velocidad (un apoyo de talón, un bloqueo) no deja esa huella
   y no se señala.
3. Se mira si los marcadores que se mueven solidarios con él hacen lo mismo en
   ese fotograma. Si le acompañan, puede ser movimiento real: se señala para
   revisarlo tal como se registró y no se propone ninguna corrección.

Nada de esto modifica los datos: el resultado es una lista de propuestas.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from nexus_mocap.lectura import Ensayo

EJES = ("X", "Y", "Z")


@dataclass(frozen=True)
class Parametros:
    umbral_mm: float = 4.0
    """Desviación mínima, en milímetros, para considerar un salto."""
    factor_ruido: float = 6.0
    """Veces que la desviación debe superar la variación habitual del tramo."""
    ventana_s: float = 0.5
    """Duración del tramo con el que se mide la variación habitual."""
    max_referencias: int = 3
    """Marcadores solidarios que se consultan para cada salto."""
    rigidez_mm: float = 10.0
    """Variación máxima de la distancia entre dos marcadores para tomarlos como solidarios."""


@dataclass(frozen=True)
class Salto:
    marcador: str
    indice: int
    fotograma: int
    tiempo_s: float
    eje: str
    desviacion_mm: float
    original: tuple[float, float, float]
    propuesta: tuple[float, float, float] | None
    clasificacion: str  # "aislado" o "acompañado"
    confianza: str  # "alta", "media" o "baja"
    referencias: tuple[str, ...]
    acompanan: tuple[str, ...]
    simultaneos: int


def _mediana_movil(valores: np.ndarray, ventana: int) -> np.ndarray:
    """Mediana móvil por filas que ignora los NaN."""
    medio = ventana // 2
    relleno = np.pad(valores, ((0, 0), (medio, medio)), constant_values=np.nan)
    vistas = np.lib.stride_tricks.sliding_window_view(relleno, ventana, axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(vistas, axis=2)


def _residuos(posiciones: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Diferencia de cada punto con el punto medio de sus dos vecinos."""
    vector = np.full_like(posiciones, np.nan)
    vector[:, 1:-1] = posiciones[:, 1:-1] - (posiciones[:, :-2] + posiciones[:, 2:]) / 2
    return vector, np.linalg.norm(vector, axis=2)


def _desviaciones(posiciones: np.ndarray, modulo_lineal: np.ndarray) -> np.ndarray:
    """Distancia de cada punto a la curva que pasa por dos vecinos a cada lado.

    Sigue mejor el movimiento real que el punto medio, sobre todo a frecuencias
    de captura bajas. Donde falta algún vecino lejano se usa el punto medio.
    """
    desviacion = modulo_lineal.copy()
    if posiciones.shape[1] >= 5:
        cerca = posiciones[:, 1:-3] + posiciones[:, 3:-1]
        lejos = posiciones[:, :-4] + posiciones[:, 4:]
        cubica = np.linalg.norm(posiciones[:, 2:-2] - (4 * cerca - lejos) / 6, axis=2)
        centro = desviacion[:, 2:-2]
        centro[np.isfinite(cubica)] = cubica[np.isfinite(cubica)]
    return desviacion


def _umbrales(modulo: np.ndarray, frecuencia: float, p: Parametros) -> np.ndarray:
    ventana = max(21, int(round(p.ventana_s * frecuencia)))
    ventana += 1 - ventana % 2
    local = _mediana_movil(modulo, ventana)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        general = np.nanmedian(modulo, axis=1, keepdims=True)
    variacion = np.fmax(local, np.nan_to_num(general))
    return np.maximum(p.umbral_mm, p.factor_ruido * np.nan_to_num(variacion))


def _sale_y_vuelve(vector: np.ndarray, modulo: np.ndarray, m: int, t: int) -> tuple[bool, int]:
    """Comprueba la huella de un punto aislado y devuelve cuántos lados la confirman."""
    direccion = vector[m, t] / modulo[m, t]
    pruebas = []
    for vecino in (t - 1, t + 1):
        if 0 <= vecino < modulo.shape[1] and np.isfinite(modulo[m, vecino]):
            pruebas.append(-2.0 * float(vector[m, vecino] @ direccion) / modulo[m, t])
    return (bool(pruebas) and float(np.mean(pruebas)) >= 0.5), len(pruebas)


def _propuesta(trayectoria: np.ndarray, t: int) -> np.ndarray:
    """Posición estimada con los vecinos: cúbica si hay dos a cada lado, si no lineal."""
    n = trayectoria.shape[0]
    if t - 2 >= 0 and t + 2 < n:
        lejos = trayectoria[t - 2] + trayectoria[t + 2]
        if np.all(np.isfinite(lejos)):
            return (4 * (trayectoria[t - 1] + trayectoria[t + 1]) - lejos) / 6
    return (trayectoria[t - 1] + trayectoria[t + 1]) / 2


def _referencias(posiciones: np.ndarray, m: int, p: Parametros) -> list[int]:
    """Marcadores cuya distancia a ``m`` apenas cambia: se mueven solidarios con él."""
    distancias = np.linalg.norm(posiciones - posiciones[m], axis=2)
    comunes = np.sum(np.isfinite(distancias), axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mediana = np.nanmedian(distancias, axis=1, keepdims=True)
        variacion = np.nanmedian(np.abs(distancias - mediana), axis=1)
    variacion[m] = np.inf
    variacion[(comunes < 20) | ~np.isfinite(variacion)] = np.inf
    orden = np.argsort(variacion)[: p.max_referencias]
    return [int(i) for i in orden if variacion[i] <= p.rigidez_mm]


def detectar_saltos(ensayo: Ensayo, parametros: Parametros | None = None) -> list[Salto]:
    """Devuelve los saltos de un fotograma del ensayo, ordenados por fotograma."""
    p = parametros or Parametros()
    posiciones = ensayo.posiciones
    n_marcadores, n_fotogramas, _ = posiciones.shape
    if n_fotogramas < 3:
        return []

    vector, modulo_lineal = _residuos(posiciones)
    modulo = _desviaciones(posiciones, modulo_lineal)
    umbral = _umbrales(modulo, ensayo.frecuencia, p)
    supera = np.nan_to_num(modulo, nan=-np.inf) >= umbral
    simultaneos = supera.sum(axis=0)

    previo = np.nan_to_num(np.roll(modulo, 1, axis=1), nan=-np.inf)
    siguiente = np.nan_to_num(np.roll(modulo, -1, axis=1), nan=-np.inf)
    candidatos = supera & (modulo > previo) & (modulo >= siguiente)

    saltos: list[Salto] = []
    referencias_de: dict[int, list[int]] = {}
    for m, t in zip(*np.nonzero(candidatos), strict=True):
        m, t = int(m), int(t)
        confirmado, lados = _sale_y_vuelve(vector, modulo_lineal, m, t)
        if not confirmado:
            continue

        if m not in referencias_de:
            referencias_de[m] = _referencias(posiciones, m, p)
        visibles = [r for r in referencias_de[m] if np.isfinite(modulo[r, t])]
        acompanan = [r for r in visibles if modulo[r, t] >= 0.5 * umbral[r, t]]
        otros = int(simultaneos[t]) - 1
        generalizado = otros >= max(2, round(0.25 * (n_marcadores - 1)))

        estimada = _propuesta(posiciones[m], t)
        diferencia = posiciones[m, t] - estimada
        if acompanan or generalizado:
            clasificacion, confianza, propuesta = "acompañado", "baja", None
        else:
            clasificacion = "aislado"
            confianza = "alta" if (lados == 2 and visibles) else "media"
            propuesta = tuple(float(v) for v in estimada)

        saltos.append(
            Salto(
                marcador=ensayo.etiquetas[m],
                indice=t,
                fotograma=ensayo.fotograma(t),
                tiempo_s=ensayo.tiempo(t),
                eje=EJES[int(np.argmax(np.abs(diferencia)))],
                desviacion_mm=float(np.linalg.norm(diferencia)),
                original=tuple(float(v) for v in posiciones[m, t]),
                propuesta=propuesta,
                clasificacion=clasificacion,
                confianza=confianza,
                referencias=tuple(ensayo.etiquetas[r] for r in visibles),
                acompanan=tuple(ensayo.etiquetas[r] for r in acompanan),
                simultaneos=otros,
            )
        )

    saltos.sort(key=lambda s: (s.fotograma, s.marcador))
    return saltos
