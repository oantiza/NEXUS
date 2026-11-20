"""Propuesta de eventos de marcha: contacto del pie y despegue de la punta.

La idea es dar a quien revisa un fotograma candidato y el tramo en el que cabe
la duda, para que solo tenga que confirmarlo o moverlo. No se escribe nada en
el archivo.

Cómo se calcula, para cada pie:

1. Se toma la velocidad del marcador del talón (para el contacto) y del de la
   punta (para el despegue), suavizada. Cada paso deja un pico de velocidad
   durante el balanceo.
2. El contacto se sitúa donde, tras el pico, la velocidad del talón baja a una
   fracción pequeña de ese pico. El despegue, donde la de la punta la supera
   antes del pico. Al ser relativo al propio paso, el criterio no depende de la
   dirección de la marcha ni de lo largo o rápido que sea el paso.
3. El intervalo de duda son los fotogramas entre los que la velocidad cruza una
   fracción algo menor y otra algo mayor. Si el pie frena o arranca de forma
   brusca, el intervalo es estrecho; si lo hace poco a poco (apoyo plano,
   pasos arrastrados), es ancho y la confianza se marca como baja.

Las fracciones se eligieron con grabaciones públicas de marcha de personas
sanas. No están validadas con marcha parkinsoniana.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from nexus_mocap.lectura import Ensayo, EventoRegistrado

LADOS = {"izquierdo": "L", "derecho": "R"}


@dataclass(frozen=True)
class ParametrosEventos:
    corte_hz: float = 6.0
    """Frecuencia de corte del suavizado de las trayectorias."""
    velocidad_minima_mm_s: float = 400.0
    """Velocidad de pico por debajo de la cual un movimiento del pie no se cuenta como paso."""
    fraccion_contacto: float = 0.15
    fraccion_despegue: float = 0.30
    duda_contacto: tuple[float, float] = (0.25, 0.10)
    duda_despegue: tuple[float, float] = (0.20, 0.40)
    hueco_maximo_s: float = 0.1
    """Huecos más cortos que esto se salvan al calcular la velocidad; los más largos, no."""
    separacion_minima_s: float = 0.15
    """Dos propuestas iguales del mismo pie más juntas que esto se toman como una sola."""
    duda_amplia_s: float = 0.08
    """Anchura del intervalo de duda a partir de la cual la confianza se marca como baja."""


@dataclass(frozen=True)
class Evento:
    lado: str  # "izquierdo" o "derecho"
    tipo: str  # "contacto" o "despegue"
    fotograma: int
    tiempo_s: float
    fotograma_desde: int
    fotograma_hasta: int
    confianza: str  # "normal" o "baja"
    marcador: str
    velocidad_pico_mm_s: float


def _tramos(validos: np.ndarray) -> list[np.ndarray]:
    indices = np.flatnonzero(validos)
    if indices.size == 0:
        return []
    return np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)


def velocidad(trayectoria: np.ndarray, frecuencia: float, p: ParametrosEventos) -> np.ndarray:
    """Módulo de la velocidad (mm/s) de un marcador, con la trayectoria suavizada.

    Los huecos cortos se salvan por interpolación solo para este cálculo; en los
    largos la velocidad queda sin definir y no se proponen eventos.
    """
    from scipy.signal import butter, filtfilt

    posicion = np.array(trayectoria, dtype=float)
    n = posicion.shape[0]
    registrado = np.all(np.isfinite(posicion), axis=1)
    if registrado.sum() < 2:
        return np.full(n, np.nan)

    hueco_maximo = int(round(p.hueco_maximo_s * frecuencia))
    for tramo in _tramos(~registrado):
        if tramo[0] == 0 or tramo[-1] == n - 1 or tramo.size > hueco_maximo:
            continue
        antes, despues = tramo[0] - 1, tramo[-1] + 1
        for eje in range(3):
            posicion[tramo, eje] = np.interp(tramo, [antes, despues], posicion[[antes, despues], eje])
    disponible = np.all(np.isfinite(posicion), axis=1)

    b, a = butter(2, min(0.99, p.corte_hz / (frecuencia / 2)))
    resultado = np.full(n, np.nan)
    for tramo in _tramos(disponible):
        if tramo.size <= 12:
            continue
        suave = filtfilt(b, a, posicion[tramo], axis=0)
        resultado[tramo] = np.linalg.norm(np.gradient(suave, axis=0) * frecuencia, axis=1)
    return resultado


def _cruce(v: np.ndarray, pico: int, umbral: float, hacia_delante: bool, limite: int) -> float | None:
    """Posición (con decimales) del primer cruce del umbral a partir del pico."""
    if hacia_delante:
        for i in range(pico, min(v.size - 1, pico + limite)):
            if not np.isfinite(v[i + 1]):
                return None
            if v[i] >= umbral > v[i + 1]:
                return i + (v[i] - umbral) / (v[i] - v[i + 1])
    else:
        for i in range(pico, max(0, pico - limite), -1):
            if not np.isfinite(v[i - 1]):
                return None
            if v[i - 1] < umbral <= v[i]:
                return i - (v[i] - umbral) / (v[i] - v[i - 1])
    return None


# Nombres habituales de cada marcador según el laboratorio o el fabricante, sin la letra del lado.
NOMBRES_TALON = ("HEE", "HEEL", "CAL")
NOMBRES_PUNTA = ("TOE",)
NOMBRES_TOBILLO = ("ANK", "ANKLE")


def _normalizar(etiqueta: str) -> str:
    """Quita el prefijo del sujeto y los separadores: ``Sujeto:L.Heel`` pasa a ``LHEEL``."""
    return re.sub(r"[^A-Z0-9]", "", etiqueta.split(":")[-1].upper())


def _buscar_marcador(ensayo: Ensayo, nombres: tuple[str, ...]) -> tuple[int, str] | None:
    """Primer marcador de la lista que existe y tiene trayectoria registrada."""
    cortas = [_normalizar(e) for e in ensayo.etiquetas]
    minimo = max(13, int(round(0.5 * ensayo.frecuencia)))
    for nombre in nombres:
        if nombre not in cortas:
            continue
        indice = cortas.index(nombre)
        if np.sum(np.all(np.isfinite(ensayo.posiciones[indice]), axis=1)) >= minimo:
            return indice, nombre
    return None


def es_tobillo(nombre: str) -> bool:
    """Indica si el marcador elegido es el del tobillo, que sustituye peor al talón o a la punta."""
    return any(nombre.endswith(n) for n in NOMBRES_TOBILLO)


def marcadores_del_pie(ensayo: Ensayo, lado: str) -> dict[str, tuple[int, str] | None]:
    """Marcador que se usa para cada tipo de evento: talón y punta, o tobillo si faltan."""
    letra = LADOS[lado]
    tobillo = tuple(f"{letra}{n}" for n in NOMBRES_TOBILLO)
    return {
        "contacto": _buscar_marcador(ensayo, tuple(f"{letra}{n}" for n in NOMBRES_TALON) + tobillo),
        "despegue": _buscar_marcador(ensayo, tuple(f"{letra}{n}" for n in NOMBRES_PUNTA) + tobillo),
    }


def _sin_repetidos(eventos: list[Evento], separacion_s: float) -> list[Evento]:
    """Si un mismo balanceo deja dos picos de velocidad, se queda con la propuesta del pico mayor."""
    conservados: list[Evento] = []
    for evento in sorted(eventos, key=lambda e: (e.lado, e.tipo, e.tiempo_s)):
        anterior = conservados[-1] if conservados else None
        if (
            anterior is not None
            and (anterior.lado, anterior.tipo) == (evento.lado, evento.tipo)
            and evento.tiempo_s - anterior.tiempo_s < separacion_s
        ):
            if evento.velocidad_pico_mm_s > anterior.velocidad_pico_mm_s:
                conservados[-1] = evento
            continue
        conservados.append(evento)
    return conservados


def proponer_eventos(ensayo: Ensayo, parametros: ParametrosEventos | None = None) -> list[Evento]:
    """Devuelve los contactos y despegues propuestos, ordenados por fotograma."""
    from scipy.signal import find_peaks

    p = parametros or ParametrosEventos()
    fs = ensayo.frecuencia
    limite = int(round(0.6 * fs))
    eventos: list[Evento] = []

    for lado in LADOS:
        for tipo, encontrado in marcadores_del_pie(ensayo, lado).items():
            if encontrado is None:
                continue
            indice_marcador, _ = encontrado
            es_contacto = tipo == "contacto"
            fraccion = p.fraccion_contacto if es_contacto else p.fraccion_despegue
            duda = p.duda_contacto if es_contacto else p.duda_despegue

            v = velocidad(ensayo.posiciones[indice_marcador], fs, p)
            picos, _ = find_peaks(
                np.nan_to_num(v, nan=0.0),
                height=p.velocidad_minima_mm_s,
                prominence=p.velocidad_minima_mm_s / 2,
                distance=max(1, int(round(0.3 * fs))),
            )
            for pico in picos:
                centro = _cruce(v, pico, fraccion * v[pico], es_contacto, limite)
                if centro is None:
                    continue
                extremos = [_cruce(v, pico, f * v[pico], es_contacto, limite) for f in duda]
                if None in extremos:
                    desde = hasta = centro
                    confianza = "baja"
                else:
                    desde, hasta = min(extremos), max(extremos)
                    confianza = "normal" if (hasta - desde) / fs <= p.duda_amplia_s else "baja"
                eventos.append(
                    Evento(
                        lado=lado,
                        tipo=tipo,
                        fotograma=ensayo.primer_fotograma + int(round(centro)),
                        tiempo_s=(ensayo.primer_fotograma + centro - 1) / fs,
                        fotograma_desde=ensayo.primer_fotograma + int(np.floor(desde)),
                        fotograma_hasta=ensayo.primer_fotograma + int(np.ceil(hasta)),
                        confianza=confianza,
                        marcador=ensayo.etiquetas[indice_marcador],
                        velocidad_pico_mm_s=float(v[pico]),
                    )
                )

    eventos = _sin_repetidos(eventos, p.separacion_minima_s)
    eventos.sort(key=lambda e: (e.tiempo_s, e.lado, e.tipo))
    return eventos


@dataclass(frozen=True)
class Emparejado:
    """Un evento ya guardado en el archivo y la propuesta más cercana, si la hay."""

    registrado: EventoRegistrado
    fotograma_registrado: float
    propuesta: Evento | None
    diferencia_fotogramas: float | None  # propuesta menos registrado
    dentro_del_intervalo: bool | None


def comparar(
    eventos: list[Evento],
    registrados: list[EventoRegistrado],
    frecuencia: float,
    ventana_s: float = 0.2,
) -> list[Emparejado]:
    """Empareja cada evento guardado con la propuesta del mismo pie y tipo más próxima."""
    resultado = []
    for registrado in registrados:
        candidatos = [
            e
            for e in eventos
            if e.lado == registrado.lado
            and e.tipo == registrado.tipo
            and abs(e.tiempo_s - registrado.tiempo_s) <= ventana_s
        ]
        fotograma = registrado.tiempo_s * frecuencia + 1
        if not candidatos:
            resultado.append(Emparejado(registrado, fotograma, None, None, None))
            continue
        propuesta = min(candidatos, key=lambda e: abs(e.tiempo_s - registrado.tiempo_s))
        resultado.append(
            Emparejado(
                registrado=registrado,
                fotograma_registrado=fotograma,
                propuesta=propuesta,
                diferencia_fotogramas=(propuesta.tiempo_s - registrado.tiempo_s) * frecuencia,
                dentro_del_intervalo=propuesta.fotograma_desde - 0.5
                <= fotograma
                <= propuesta.fotograma_hasta + 0.5,
            )
        )
    return resultado
