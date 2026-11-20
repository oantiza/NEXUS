"""Propuesta EXPERIMENTAL del primer movimiento al iniciar la marcha.

No hay una regla solo con marcadores validada en la enfermedad de Parkinson.
Esto es una adaptación de criterios publicados, con todos los umbrales
configurables (``ParametrosInicio``), y no está validada. No se escribe nada en
el archivo.

Se dan tres propuestas por separado, sin fundirlas en un «primer movimiento»
único, porque la definición la elige quien revisa:

- Pelvis: velocidad horizontal del centro de la pelvis (punto medio de las PSIS
  o sacro; si no, punto medio de las ASIS), suavizada. El movimiento se detecta
  cuando supera la media del reposo + 3 desviaciones típicas (DE) durante al
  menos 0,133 s (Jones y cols., 2019, PLoS One: «>8 frames (>133ms) beyond the
  mean+3SD») y el inicio se retrasa hasta donde superó media + 1 DE
  (Schlenstedt y cols., 2018, Front Aging Neurosci: detección a 3 DE, inicio a
  1 DE). Intervalo de duda: del cruce de 1 DE al de 3 DE.
- Despegue del talón de cada pie: la altura del marcador del talón supera la
  media del reposo + 2 DE (Oliveira y cols., 2023, PLoS One), durante el mismo
  tiempo. Intervalo de duda: del cruce de 1 DE al de 2 DE. Se indica qué pie
  levanta antes.
- Tronco, solo si hay un marcador de tronco (C7; si no, T10, CLAV o STRN): la
  inclinación hacia delante de la línea pelvis-tronco respecto a la vertical,
  con el mismo criterio que la pelvis (3 DE, inicio a 1 DE).

El reposo de referencia: el registro tiene que empezar con la persona de pie y
quieta al menos 1 s. Se usan hasta los últimos 5 s de ese reposo (Schlenstedt y
cols., 2018: «the last 5 s of quiet stance»). Dónde acaba el reposo se decide
primero con umbrales amplios propios de este programa (pelvis a menos de
100 mm/s y talones a menos de 15 mm de su altura inicial) y después se ajusta
para que termine donde empieza el primer movimiento detectado. Si el registro
no empieza en reposo, no se propone nada y se dice por qué.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nexus_mocap.eventos import NOMBRES_TALON, _buscar_marcador, _tramos
from nexus_mocap.giros import (
    NOMBRES_PELVIS,
    _horizontales,
    buscar,
    eje_vertical,
    numero,
    rumbo_pelvis,
    salvar_huecos,
)
from nexus_mocap.lectura import Ensayo

NOMBRES_TRONCO = ("C7", "T10", "CLAV", "STRN")
SENALES = ("pelvis", "talón izquierdo", "talón derecho", "tronco")


@dataclass(frozen=True)
class ParametrosInicio:
    reposo_minimo_s: float = 1.0
    """Reposo inicial mínimo para proponer algo. Elección propia: con menos, la media y la DE no valen."""
    reposo_maximo_s: float = 5.0
    """Duración máxima del reposo de referencia. Schlenstedt y cols. (2018): los últimos 5 s."""
    velocidad_reposo_mm_s: float = 100.0
    """Velocidad horizontal de la pelvis por encima de la cual ya no se considera reposo. Elección propia,
    solo para acotar el reposo; el inicio se decide con la media y la DE."""
    elevacion_reposo_mm: float = 15.0
    """Subida del talón sobre su altura inicial a partir de la cual ya no se considera reposo.
    Elección propia."""
    corte_hz: float = 6.0
    """Suavizado de las trayectorias, el mismo que para los eventos de marcha. Elección propia."""
    de_deteccion: float = 3.0
    """Pelvis y tronco: DE sobre la media del reposo para detectar movimiento. Jones y cols. (2019);
    Schlenstedt y cols. (2018)."""
    de_inicio: float = 1.0
    """DE a la que se retrocede para situar el inicio. Schlenstedt y cols. (2018)."""
    de_talon: float = 2.0
    """Talón: DE sobre la media del reposo. Oliveira y cols. (2023)."""
    persistencia_s: float = 0.133
    """Tiempo seguido por encima del umbral. Jones y cols. (2019): más de 8 fotogramas a 60 Hz (133 ms)."""
    hueco_maximo_s: float = 0.1
    """Huecos más cortos que esto se salvan por interpolación; los más largos cortan la señal."""
    busqueda_maxima_s: float = 5.0
    """Tiempo tras el reposo en el que se busca el primer movimiento de cada señal. Elección propia: un
    talón que no se levanta hasta mucho después no corresponde al inicio de la marcha."""
    iteraciones: int = 3
    """Veces que se ajusta el final del reposo al primer movimiento detectado."""


@dataclass(frozen=True)
class Inicio:
    """Primer movimiento propuesto de una señal. Fotogramas en la numeración original del archivo."""

    senal: str  # "pelvis", "talón izquierdo", "talón derecho" o "tronco"
    marcador: str
    fotograma: int
    tiempo_s: float
    fotograma_desde: int
    fotograma_hasta: int
    criterio: str


@dataclass(frozen=True)
class ResultadoInicio:
    inicios: tuple[Inicio, ...]
    """Ordenados por fotograma."""
    motivo: str | None
    """Por qué no se propone nada, en una frase. ``None`` si hay propuestas."""
    reposo_desde: int | None = None
    reposo_hasta: int | None = None
    """Fotogramas del reposo de referencia que se ha usado."""
    primer_talon: str | None = None
    """``"izquierdo"`` o ``"derecho"``: el pie que levanta antes el talón."""
    primero: str = ""
    """Qué señal se mueve antes: pelvis, talón (el primero de los dos) o tronco."""
    notas: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Senal:
    nombre: str
    marcador: str
    valores: np.ndarray
    de_deteccion: float
    criterio: str
    propuesta_en_deteccion: bool
    """El talón se propone donde supera las 2 DE (Oliveira); pelvis y tronco, donde superan 1 DE."""


def _suavizar(trayectoria: np.ndarray, fs: float, p: ParametrosInicio) -> np.ndarray:
    from scipy.signal import butter, filtfilt

    posicion = salvar_huecos(trayectoria, fs, p.hueco_maximo_s)
    resultado = np.full(posicion.shape, np.nan)
    b, a = butter(2, min(0.99, p.corte_hz / (fs / 2)))
    for tramo in _tramos(np.all(np.isfinite(posicion), axis=1)):
        if tramo.size > 12:
            resultado[tramo] = filtfilt(b, a, posicion[tramo], axis=0)
    return resultado


def _centro_pelvis(ensayo: Ensayo) -> tuple[np.ndarray, str] | None:
    """Punto medio de las PSIS, o el sacro, o el punto medio de las ASIS."""
    m = {clave: buscar(ensayo, clave, NOMBRES_PELVIS) for clave in NOMBRES_PELVIS}
    for claves in (("LPSI", "RPSI"), ("SACR",), ("LASI", "RASI")):
        if all(m[c] for c in claves):
            centro = np.mean([ensayo.posiciones[m[c][0]] for c in claves], axis=0)
            nombre = " y ".join(ensayo.etiquetas[m[c][0]] for c in claves)
            return centro, nombre
    return None


def _primer_mantenido(condicion: np.ndarray, desde: int, n_seguidos: int) -> int | None:
    """Primer índice a partir de ``desde`` en que la condición se cumple ``n_seguidos`` fotogramas."""
    seguidos = 0
    for i in range(desde, condicion.size):
        seguidos = seguidos + 1 if condicion[i] else 0
        if seguidos >= n_seguidos:
            return i - n_seguidos + 1
    return None


def _arranque(
    x: np.ndarray, base: slice, n_seguidos: int, de_deteccion: float, de_inicio: float, limite: int
) -> tuple[int, int] | str:
    """(cruce de 1 DE, detección) o el motivo por el que no hay propuesta."""
    referencia = x[base]
    referencia = referencia[np.isfinite(referencia)]
    if referencia.size < 0.9 * (base.stop - base.start):
        return "le faltan datos durante el reposo"
    media, de = float(np.mean(referencia)), max(float(np.std(referencia)), 1e-9)
    deteccion = None
    seguidos = 0
    for i in range(base.stop, min(x.size, base.stop + limite)):
        if not np.isfinite(x[i]):
            return "se pierde el marcador antes de que se detecte movimiento"
        seguidos = seguidos + 1 if x[i] > media + de_deteccion * de else 0
        if seguidos >= n_seguidos:
            deteccion = i - n_seguidos + 1
            break
    if deteccion is None:
        return f"no supera la media del reposo + {numero(de_deteccion)} DE en el tiempo de búsqueda"
    inicio = deteccion
    while inicio > base.start and x[inicio - 1] > media + de_inicio * de:
        inicio -= 1
    return inicio, deteccion


def proponer_inicio(ensayo: Ensayo, parametros: ParametrosInicio | None = None) -> ResultadoInicio:
    """Propone el primer movimiento de pelvis, talones y tronco. EXPERIMENTAL: véase el módulo."""
    p = parametros or ParametrosInicio()
    fs = ensayo.frecuencia
    n_seguidos = max(1, int(round(p.persistencia_s * fs)))
    minimo = int(round(p.reposo_minimo_s * fs))
    limite = max(1, int(round(p.busqueda_maxima_s * fs)))

    centro = _centro_pelvis(ensayo) if ensayo.n_fotogramas >= 2 else None
    if centro is None:
        return ResultadoInicio(
            (),
            "No se propone el primer movimiento: faltan los marcadores de la pelvis (LPSI y RPSI, SACR, "
            "o LASI y RASI) o no tienen datos.",
        )
    pelvis = rumbo_pelvis(ensayo, p.hueco_maximo_s)
    if pelvis is not None:
        vertical, signo, a, b = pelvis.eje_vertical, pelvis.signo_vertical, *pelvis.horizontales
    else:
        vertical, signo, _ = eje_vertical(ensayo)
        a, b = _horizontales(vertical, signo)
    posicion_pelvis = _suavizar(centro[0], fs, p)
    velocidad_pelvis = np.linalg.norm(np.gradient(posicion_pelvis[:, [a, b]], axis=0) * fs, axis=1)

    validos = np.flatnonzero(np.isfinite(velocidad_pelvis))
    if validos.size == 0:
        return ResultadoInicio(
            (), "No se propone el primer movimiento: la pelvis no tiene datos suficientes."
        )
    comienzo = int(validos[0])
    notas = []
    if comienzo > 0:
        notas.append(f"La pelvis no tiene datos hasta el fotograma {ensayo.fotograma(comienzo)}.")

    senales: list[_Senal] = [
        _Senal(
            "pelvis",
            centro[1],
            velocidad_pelvis,
            p.de_deteccion,
            f"velocidad horizontal > media + {numero(p.de_deteccion)} DE, inicio en {numero(p.de_inicio)} DE",
            False,
        )
    ]
    alturas = {}
    for lado, letra in (("izquierdo", "L"), ("derecho", "R")):
        talon = _buscar_marcador(ensayo, tuple(f"{letra}{nombre}" for nombre in NOMBRES_TALON))
        if talon is None:
            notas.append(f"No hay marcador del talón {lado} con datos.")
            continue
        altura = signo * _suavizar(ensayo.posiciones[talon[0]], fs, p)[:, vertical]
        alturas[lado] = altura
        senales.append(
            _Senal(
                f"talón {lado}",
                ensayo.etiquetas[talon[0]],
                altura,
                p.de_talon,
                f"altura > media + {numero(p.de_talon)} DE",
                True,
            )
        )
    tronco = _buscar_marcador(ensayo, NOMBRES_TRONCO)
    if tronco is None:
        notas.append("No hay marcador de tronco (C7, T10, CLAV o STRN): no se propone la inclinación.")

    # Reposo inicial: pelvis casi quieta y talones en el suelo, con criterios amplios.
    with np.errstate(invalid="ignore"):
        movimiento = ~(velocidad_pelvis < p.velocidad_reposo_mm_s)
        for altura in alturas.values():
            referencia = np.nanmedian(altura[comienzo : comienzo + max(1, int(round(0.25 * fs)))])
            movimiento |= altura - referencia > p.elevacion_reposo_mm
    movimiento[:comienzo] = False
    fin_reposo = _primer_mantenido(movimiento, comienzo, n_seguidos)
    if fin_reposo is None:
        return ResultadoInicio(
            (),
            "No se propone el primer movimiento: no se detecta que la persona empiece a andar "
            f"(la pelvis no pasa de {numero(p.velocidad_reposo_mm_s, 0)} mm/s).",
            notas=tuple(notas),
        )
    if fin_reposo - comienzo < minimo:
        return ResultadoInicio(
            (),
            f"No se propone el primer movimiento: el registro no empieza con al menos "
            f"{numero(p.reposo_minimo_s)} s de pie y quieto "
            f"(a los {numero((fin_reposo - comienzo) / fs, 2)} s ya hay movimiento; "
            "en los ensayos de marcha suele empezar andando).",
            notas=tuple(notas),
        )

    if tronco is not None:
        vector = _suavizar(ensayo.posiciones[tronco[0]], fs, p) - posicion_pelvis
        alto = signo * vector[:, vertical]
        base_inicial = slice(max(comienzo, fin_reposo - int(round(p.reposo_maximo_s * fs))), fin_reposo)
        rumbos = pelvis.rumbo[base_inicial] if pelvis is not None else np.array([])
        rumbos = rumbos[np.isfinite(rumbos)]
        if rumbos.size:
            frente = float(np.arctan2(np.mean(np.sin(rumbos)), np.mean(np.cos(rumbos))))
            delante = vector[:, a] * np.cos(frente) + vector[:, b] * np.sin(frente)
            descripcion = "inclinación hacia delante"
        else:
            delante = np.hypot(vector[:, a], vector[:, b])
            descripcion = (
                "inclinación respecto a la vertical (sin rumbo de la pelvis, en cualquier dirección)"
            )
            notas.append("Sin rumbo de la pelvis, el tronco se mide como inclinación en cualquier dirección.")
        senales.append(
            _Senal(
                "tronco",
                f"{ensayo.etiquetas[tronco[0]]} sobre {centro[1]}",
                np.degrees(np.arctan2(delante, alto)),
                p.de_deteccion,
                f"{descripcion} > media + {numero(p.de_deteccion)} DE, inicio en {numero(p.de_inicio)} DE",
                False,
            )
        )

    # Se ajusta el final del reposo al primer movimiento detectado, para que la media y la DE
    # no incluyan el comienzo del movimiento.
    fin = fin_reposo
    resultados: dict[str, tuple[int, int] | str] = {}
    for _ in range(max(1, p.iteraciones)):
        base = slice(max(comienzo, fin - int(round(p.reposo_maximo_s * fs))), fin)
        if resultados and base.stop - base.start < minimo:
            break
        nuevos = {
            s.nombre: _arranque(s.valores, base, n_seguidos, s.de_deteccion, p.de_inicio, limite)
            for s in senales
        }
        resultados, usada = nuevos, base
        primeros = [r[0] for r in nuevos.values() if not isinstance(r, str)]
        if not primeros or min(primeros) >= fin:
            break
        fin = min(primeros)

    inicios = []
    for s in senales:
        r = resultados[s.nombre]
        if isinstance(r, str):
            notas.append(f"{s.nombre.capitalize()}: {r}.")
            continue
        cruce, deteccion = r
        propuesta = deteccion if s.propuesta_en_deteccion else cruce
        inicios.append(
            Inicio(
                senal=s.nombre,
                marcador=s.marcador,
                fotograma=ensayo.fotograma(propuesta),
                tiempo_s=ensayo.tiempo(propuesta),
                fotograma_desde=ensayo.fotograma(cruce),
                fotograma_hasta=ensayo.fotograma(deteccion),
                criterio=s.criterio,
            )
        )
    inicios.sort(key=lambda i: (i.fotograma, SENALES.index(i.senal)))
    if not inicios:
        return ResultadoInicio(
            (),
            "No se propone el primer movimiento: ninguna señal se aparta lo bastante del reposo.",
            ensayo.fotograma(usada.start),
            ensayo.fotograma(usada.stop - 1),
            notas=tuple(notas),
        )

    talones = [i for i in inicios if i.senal.startswith("talón")]
    primer_talon = talones[0].senal.split()[-1] if talones else None
    candidatos = [i for i in inicios if not i.senal.startswith("talón") or i is talones[0]]
    antes = min(i.fotograma for i in candidatos)
    a_la_vez = [i.senal for i in candidatos if i.fotograma == antes]
    return ResultadoInicio(
        tuple(inicios),
        None,
        ensayo.fotograma(usada.start),
        ensayo.fotograma(usada.stop - 1),
        primer_talon=primer_talon,
        primero=" y ".join(a_la_vez) + (" a la vez" if len(a_la_vez) > 1 else ""),
        notas=tuple(notas),
    )
