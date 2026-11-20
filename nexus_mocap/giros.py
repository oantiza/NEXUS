"""Propuesta EXPERIMENTAL del inicio y el final de los giros, a partir de la pelvis.

No está validada con marcadores en la enfermedad de Parkinson. Las definiciones
proceden de la bibliografía y todos los umbrales se pueden cambiar
(``ParametrosGiros``). No se escribe nada en el archivo.

Definición (Mellone, Mancini, King, Horak y Chiari, 2016, J NeuroEng Rehabil):
un giro es un tramo en que la velocidad de giro de la pelvis alrededor del eje
vertical supera 30 °/s durante más de 0,5 s. El rumbo de la pelvis se calcula
con las espinas ilíacas (ASIS y PSIS) y se filtra con un Butterworth de orden 4
sin desfase a 1,5 Hz.

1. Rumbo: dirección horizontal hacia la que mira la pelvis. Se toma el vector
   del punto medio de las PSIS (o del sacro) al punto medio de las ASIS; si solo
   hay ASIS (o solo PSIS), la perpendicular horizontal a la línea que las une.
2. El eje vertical no viene en el archivo: se deduce de los datos (el eje en el
   que la pelvis queda más alta que los pies). Si no hay marcadores del pie, se
   supone Z hacia arriba.
3. Inicio del giro: primer fotograma del tramo por encima de 30 °/s; final:
   el último. El intervalo de duda sigue la histéresis de El-Gohary y cols.
   (2013, Sensors), que sitúan los límites donde la velocidad baja de 5 °/s:
   para el inicio, desde el último fotograma anterior por debajo de 5 °/s hasta
   el cruce de 30 °/s; para el final, desde el cruce de 30 °/s hasta el primer
   fotograma posterior por debajo de 5 °/s.
4. Dos tramos del mismo sentido separados por una pausa corta (0,5 s) son un
   solo giro con una vacilación (Pham y cols., 2017). Se descartan los giros que
   cambian el rumbo menos de 45° (El-Gohary y cols., 2013).

Sentido: visto desde arriba, un giro contrario a las agujas del reloj es a la
izquierda de la persona y uno a favor, a la derecha.

Los huecos de hasta 0,1 s se salvan por interpolación, como en el resto del
programa; los más largos cortan la señal. Un giro que toca un hueco largo o el
principio o el final del registro se marca con confianza baja y el límite que
queda fuera no se inventa: se deja vacío. Si el giro está cortado, basta con que
lo que se ve dure más de 0,5 s o cambie el rumbo 45°: el otro mínimo no se
puede comprobar.

Además, por elección propia y no de la bibliografía: no se usan los fotogramas
en que los marcadores que dan el rumbo quedan a menos de 40 mm en el plano
horizontal, y un pico de más de 720 °/s se marca como dudoso (suele ser un
marcador mal etiquetado).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from nexus_mocap.eventos import _buscar_marcador, _tramos
from nexus_mocap.lectura import Ensayo

EJES = ("X", "Y", "Z")

# Nombres habituales, ya sin prefijo del sujeto ni separadores (véase ``eventos._normalizar``).
NOMBRES_PELVIS = {
    "LASI": ("LASI", "LASIS"),
    "RASI": ("RASI", "RASIS"),
    "LPSI": ("LPSI", "LPSIS"),
    "RPSI": ("RPSI", "RPSIS"),
    "SACR": ("SACR", "SACRUM", "VSACRAL", "SACRAL"),
}
NOMBRES_PIES = ("LHEE", "RHEE", "LTOE", "RTOE", "LANK", "RANK")


@dataclass(frozen=True)
class ParametrosGiros:
    corte_hz: float = 1.5
    """Corte del filtro paso bajo del rumbo. Mellone y cols. (2016): 1,5 Hz."""
    orden_filtro: int = 2
    """Orden del Butterworth en cada sentido. Al aplicarlo hacia delante y hacia atrás (sin desfase),
    el orden efectivo es el doble: 4, como en Mellone y cols. (2016)."""
    umbral_giro_grados_s: float = 30.0
    """Velocidad de giro de la pelvis que define un giro. Mellone y cols. (2016): 30 °/s."""
    duracion_minima_s: float = 0.5
    """Duración mínima por encima del umbral. Mellone y cols. (2016): más de 0,5 s."""
    umbral_reposo_grados_s: float = 5.0
    """Velocidad por debajo de la cual se da el giro por empezado o acabado, para el intervalo de duda.
    El-Gohary y cols. (2013): 5 °/s."""
    pausa_maxima_s: float = 0.5
    """Pausa entre dos tramos del mismo sentido que se toma como vacilación dentro de un solo giro.
    Pham y cols. (2017): vacilaciones de hasta 0,5 s."""
    giro_minimo_grados: float = 45.0
    """Cambio de rumbo mínimo para proponer un giro. El-Gohary y cols. (2013): 45°."""
    hueco_maximo_s: float = 0.1
    """Huecos más cortos que esto se salvan por interpolación; los más largos cortan la señal.
    Es el mismo criterio que usa el programa para la velocidad del pie."""
    separacion_minima_mm: float = 40.0
    """Distancia horizontal mínima entre los puntos de la pelvis que dan el rumbo. Elección propia: si quedan
    más juntos (registro en 2D, etiquetas cambiadas), el rumbo no tiene sentido y ese fotograma no se usa."""
    velocidad_inverosimil_grados_s: float = 720.0
    """Pico de velocidad de giro que no parece de una pelvis real (dos vueltas por segundo). Elección
    propia: el giro se marca con confianza baja porque suele ser un marcador mal etiquetado o cambiado."""


@dataclass(frozen=True)
class Giro:
    """Un giro propuesto. Los fotogramas siguen la numeración original del archivo.

    El intervalo de duda del inicio va de ``inicio_desde`` a ``fotograma_inicio`` y el del final,
    de ``fotograma_fin`` a ``fin_hasta``. ``None`` significa que ese límite queda fuera de lo
    registrado (principio o final del ensayo, o un hueco largo) y no se propone.
    """

    sentido: str  # "izquierda" o "derecha", visto desde arriba
    fotograma_inicio: int | None
    fotograma_fin: int | None
    inicio_desde: int | None
    fin_hasta: int | None
    tiempo_inicio_s: float | None
    tiempo_fin_s: float | None
    cambio_rumbo_grados: float
    """Cambio de rumbo entre los límites a 5 °/s (o lo registrado, si el giro está cortado)."""
    velocidad_pico_grados_s: float
    duracion_s: float
    """Del inicio al final propuestos (por encima de 30 °/s); si está cortado, lo que se ve."""
    confianza: str  # "normal" o "baja"
    nota: str = ""


@dataclass(frozen=True)
class RumboPelvis:
    """Rumbo de la pelvis fotograma a fotograma, en radianes (NaN donde no se puede calcular)."""

    rumbo: np.ndarray
    construccion: str
    marcadores: tuple[str, ...]
    eje_vertical: int
    signo_vertical: float
    horizontales: tuple[int, int]
    nota_eje: str
    fotogramas_juntos: int = 0
    """Fotogramas descartados porque los marcadores quedan demasiado juntos en el plano horizontal."""


@dataclass(frozen=True)
class ResultadoGiros:
    giros: tuple[Giro, ...]
    motivo: str | None
    """Por qué no se propone ningún giro, en una frase. ``None`` si hay propuestas."""
    construccion: str = ""
    eje_vertical: str = ""
    marcadores: tuple[str, ...] = ()
    velocidad_maxima_grados_s: float = float("nan")


def numero(valor: float, decimales: int = 1) -> str:
    """Número con coma decimal para los mensajes."""
    texto = f"{valor:.{decimales}f}".replace(".", ",")
    return texto[:-2] if texto.endswith(",0") else texto


def salvar_huecos(trayectoria: np.ndarray, frecuencia: float, maximo_s: float) -> np.ndarray:
    """Copia de la trayectoria con los huecos cortos interpolados. No toca los extremos ni los largos."""
    posicion = np.array(trayectoria, dtype=float)
    n = posicion.shape[0]
    registrado = np.all(np.isfinite(posicion), axis=1)
    if registrado.sum() < 2:
        return posicion
    maximo = int(round(maximo_s * frecuencia))
    for tramo in _tramos(~registrado):
        if tramo[0] == 0 or tramo[-1] == n - 1 or tramo.size > maximo:
            continue
        antes, despues = tramo[0] - 1, tramo[-1] + 1
        for eje in range(posicion.shape[1]):
            posicion[tramo, eje] = np.interp(tramo, [antes, despues], posicion[[antes, despues], eje])
    return posicion


def buscar(ensayo: Ensayo, clave: str, nombres: dict[str, tuple[str, ...]]) -> tuple[int, str] | None:
    """Índice y nombre del marcador que hace de ``clave`` (``LASI``, ``C7``...), si tiene datos."""
    return _buscar_marcador(ensayo, nombres[clave])


def _media_por_fotograma(bloque: np.ndarray) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(bloque, axis=0)


def eje_vertical(ensayo: Ensayo) -> tuple[int, float, str]:
    """Eje vertical y su sentido hacia arriba, deducidos de los datos.

    Es el eje en el que los marcadores de la pelvis quedan más altos que los del pie. Si no hay
    marcadores de pelvis y pie, o la diferencia no es clara, se supone Z hacia arriba.
    """
    pelvis = [buscar(ensayo, clave, NOMBRES_PELVIS) for clave in NOMBRES_PELVIS]
    pies = [_buscar_marcador(ensayo, (nombre,)) for nombre in NOMBRES_PIES]
    pelvis = [m[0] for m in pelvis if m is not None]
    pies = [m[0] for m in pies if m is not None]
    if pelvis and pies:
        diferencia = _media_por_fotograma(ensayo.posiciones[pelvis]) - _media_por_fotograma(
            ensayo.posiciones[pies]
        )
        validos = np.all(np.isfinite(diferencia), axis=1)
        if validos.any():
            mediana = np.median(diferencia[validos], axis=0)
            eje = int(np.argmax(np.abs(mediana)))
            otros = np.delete(np.abs(mediana), eje)
            if abs(mediana[eje]) >= 300.0 and abs(mediana[eje]) >= 2 * otros.max():
                signo = 1.0 if mediana[eje] > 0 else -1.0
                texto = f"{'' if signo > 0 else '−'}{EJES[eje]} hacia arriba (deducido de pelvis y pies)"
                return eje, signo, texto
    return 2, 1.0, "Z hacia arriba (supuesto: no se ha podido deducir de pelvis y pies)"


def _horizontales(eje: int, signo: float) -> tuple[int, int]:
    """Los dos ejes horizontales en el orden que hace que el ángulo crezca al girar a la izquierda."""
    a, b = (eje + 1) % 3, (eje + 2) % 3
    return (a, b) if signo > 0 else (b, a)


def rumbo_pelvis(
    ensayo: Ensayo, hueco_maximo_s: float = 0.1, separacion_minima_mm: float = 40.0
) -> RumboPelvis | None:
    """Rumbo horizontal de la pelvis, o ``None`` si faltan sus marcadores."""
    encontrados = {clave: buscar(ensayo, clave, NOMBRES_PELVIS) for clave in NOMBRES_PELVIS}
    fs = ensayo.frecuencia
    eje, signo, nota_eje = eje_vertical(ensayo)
    a, b = _horizontales(eje, signo)

    def plano(clave: str) -> np.ndarray:
        return salvar_huecos(ensayo.posiciones[encontrados[clave][0]], fs, hueco_maximo_s)[:, [a, b]]

    def medio(c1: str, c2: str) -> np.ndarray:
        return (plano(c1) + plano(c2)) / 2

    def perpendicular(izquierdo: np.ndarray, derecho: np.ndarray) -> np.ndarray:
        lateral = izquierdo - derecho  # de derecha a izquierda; delante queda a 90° en sentido horario
        return np.stack([lateral[:, 1], -lateral[:, 0]], axis=1)

    candidatas = []
    if all(encontrados[c] for c in ("LASI", "RASI", "LPSI", "RPSI")):
        delante = medio("LASI", "RASI") - medio("LPSI", "RPSI")
        candidatas.append(
            ("del punto medio de las PSIS al de las ASIS", delante, ("LASI", "RASI", "LPSI", "RPSI"))
        )
    if all(encontrados[c] for c in ("LASI", "RASI", "SACR")):
        delante = medio("LASI", "RASI") - plano("SACR")
        candidatas.append(("del sacro al punto medio de las ASIS", delante, ("LASI", "RASI", "SACR")))
    if encontrados["LASI"] and encontrados["RASI"]:
        delante = perpendicular(plano("LASI"), plano("RASI"))
        candidatas.append(("perpendicular a la línea de las ASIS", delante, ("LASI", "RASI")))
    if encontrados["LPSI"] and encontrados["RPSI"]:
        delante = perpendicular(plano("LPSI"), plano("RPSI"))
        candidatas.append(("perpendicular a la línea de las PSIS", delante, ("LPSI", "RPSI")))
    if not candidatas:
        return None

    cobertura, juntos = [], []
    for _, delante, _ in candidatas:
        with np.errstate(invalid="ignore"):
            corto = np.hypot(delante[:, 0], delante[:, 1]) < separacion_minima_mm
        juntos.append(int(corto.sum()))
        delante[corto] = np.nan
        cobertura.append(int(np.sum(np.all(np.isfinite(delante), axis=1))))
    # Se prefiere la primera construcción de la lista salvo que otra tenga claramente más datos.
    mejor = max(cobertura)
    elegida = next(i for i, n in enumerate(cobertura) if n >= 0.95 * mejor)
    construccion, delante, claves = candidatas[elegida]
    rumbo = np.arctan2(delante[:, 1], delante[:, 0])
    return RumboPelvis(
        rumbo=rumbo,
        construccion=construccion,
        marcadores=tuple(ensayo.etiquetas[encontrados[c][0]] for c in claves),
        eje_vertical=eje,
        signo_vertical=signo,
        horizontales=(a, b),
        nota_eje=nota_eje,
        fotogramas_juntos=juntos[elegida],
    )


def velocidad_de_giro(
    rumbo: np.ndarray, frecuencia: float, p: ParametrosGiros
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Rumbo filtrado (grados, continuo dentro de cada tramo), su derivada (°/s) y los tramos usados."""
    from scipy.signal import butter, filtfilt

    n = rumbo.size
    angulo = np.full(n, np.nan)
    velocidad = np.full(n, np.nan)
    minimo = max(13, int(round(p.duracion_minima_s * frecuencia)))
    b, a = butter(p.orden_filtro, min(0.99, p.corte_hz / (frecuencia / 2)))
    usados = []
    for tramo in _tramos(np.isfinite(rumbo)):
        if tramo.size < max(minimo, 3 * max(len(a), len(b)) + 1):
            continue
        suave = np.degrees(filtfilt(b, a, np.unwrap(rumbo[tramo])))
        angulo[tramo] = suave
        velocidad[tramo] = np.gradient(suave) * frecuencia
        usados.append(tramo)
    return angulo, velocidad, usados


def _rachas(signo: np.ndarray) -> list[tuple[int, int, int]]:
    """Tramos seguidos con el mismo signo distinto de cero: (primero, último, signo)."""
    rachas = []
    inicio = None
    for i, s in enumerate(signo):
        if inicio is not None and s != signo[inicio]:
            rachas.append((inicio, i - 1, int(signo[inicio])))
            inicio = None
        if inicio is None and s != 0:
            inicio = i
    if inicio is not None:
        rachas.append((inicio, signo.size - 1, int(signo[inicio])))
    return rachas


def proponer_giros(ensayo: Ensayo, parametros: ParametrosGiros | None = None) -> ResultadoGiros:
    """Propone el inicio y el final de cada giro. EXPERIMENTAL: véase la explicación del módulo."""
    p = parametros or ParametrosGiros()
    fs = ensayo.frecuencia
    n = ensayo.n_fotogramas
    pelvis = rumbo_pelvis(ensayo, p.hueco_maximo_s, p.separacion_minima_mm)
    if pelvis is None:
        return ResultadoGiros(
            (),
            "No se proponen giros: faltan los marcadores de la pelvis (LASI y RASI, o LPSI y RPSI) "
            "o no tienen datos.",
        )
    comun = {
        "construccion": pelvis.construccion,
        "eje_vertical": pelvis.nota_eje,
        "marcadores": pelvis.marcadores,
    }
    angulo, velocidad, tramos = velocidad_de_giro(pelvis.rumbo, fs, p)
    if not tramos and pelvis.fotogramas_juntos:
        return ResultadoGiros(
            (),
            "No se proponen giros: los marcadores de la pelvis quedan a menos de "
            f"{numero(p.separacion_minima_mm, 0)} mm entre sí en el plano horizontal y no dan un rumbo "
            "(¿registro en 2D o etiquetas cambiadas?).",
            **comun,
        )
    if not tramos:
        return ResultadoGiros(
            (),
            f"No se proponen giros: la pelvis no tiene ningún tramo seguido con datos de al menos "
            f"{numero(p.duracion_minima_s)} s.",
            **comun,
        )
    maxima = float(np.nanmax(np.abs(velocidad)))
    umbral = numero(p.umbral_giro_grados_s)
    if maxima <= p.umbral_giro_grados_s:
        return ResultadoGiros(
            (),
            f"No se proponen giros: la velocidad de giro de la pelvis no supera {umbral} °/s "
            f"(máximo: {numero(maxima)} °/s).",
            velocidad_maxima_grados_s=maxima,
            **comun,
        )

    pausa = int(round(p.pausa_maxima_s * fs))
    giros: list[Giro] = []
    candidatos = 0
    for tramo in tramos:
        w = velocidad[tramo]
        signo = np.where(np.abs(w) > p.umbral_giro_grados_s, np.sign(w), 0).astype(int)
        unidas: list[list[int]] = []
        for primero, ultimo, s in _rachas(signo):
            if unidas and unidas[-1][2] == s and primero - unidas[-1][1] - 1 <= pausa:
                unidas[-1][1] = ultimo
            else:
                unidas.append([primero, ultimo, s])
        candidatos += len(unidas)

        quieto = np.abs(w) < p.umbral_reposo_grados_s
        for k, (primero, ultimo, s) in enumerate(unidas):
            # Los límites a 5 °/s se buscan sin pasar de los tramos vecinos por encima de 30 °/s.
            tope_antes = unidas[k - 1][1] + 1 if k > 0 else 0
            tope_despues = unidas[k + 1][0] - 1 if k + 1 < len(unidas) else w.size - 1
            antes = np.flatnonzero(quieto[tope_antes:primero]) + tope_antes
            despues = np.flatnonzero(quieto[ultimo + 1 : tope_despues + 1]) + ultimo + 1
            desde = int(antes[-1]) if antes.size else None
            hasta = int(despues[0]) if despues.size else None
            inicio_conocido = primero > 0
            fin_conocido = ultimo < w.size - 1
            a = desde if desde is not None else primero
            b = hasta if hasta is not None else ultimo
            cambio = float(angulo[tramo[b]] - angulo[tramo[a]])
            duracion = (ultimo - primero) / fs
            larga = duracion > p.duracion_minima_s
            amplia = abs(cambio) >= p.giro_minimo_grados
            if inicio_conocido and fin_conocido:
                if not (larga and amplia):
                    continue
            elif not (larga or amplia):
                # Si el registro corta el giro, basta con que lo que se ve cumpla uno de los dos mínimos:
                # el otro no se puede comprobar.
                continue

            notas = []
            borde_inicio = "el principio del registro" if tramo[0] == 0 else "un hueco largo de la pelvis"
            borde_fin = "el final del registro" if tramo[-1] == n - 1 else "un hueco largo de la pelvis"
            reposo = numero(p.umbral_reposo_grados_s)
            if not inicio_conocido:
                notas.append(
                    f"ya estaba girando al empezar el tramo registrado ({borde_inicio}): inicio desconocido"
                )
            elif desde is None and k > 0:
                notas.append(f"empieza sin bajar de {reposo} °/s desde el tramo de giro anterior")
            elif desde is None:
                notas.append(f"la velocidad no baja de {reposo} °/s antes del inicio, hasta {borde_inicio}")
            if not fin_conocido:
                notas.append(f"seguía girando al acabar el tramo registrado ({borde_fin}): final desconocido")
            elif hasta is None and k + 1 < len(unidas):
                notas.append(f"acaba sin bajar de {reposo} °/s antes del tramo de giro siguiente")
            elif hasta is None:
                notas.append(f"la velocidad no baja de {reposo} °/s tras el final, hasta {borde_fin}")
            pico = float(np.max(np.abs(w[primero : ultimo + 1])))
            if pico > p.velocidad_inverosimil_grados_s:
                notas.append(
                    f"pico de {numero(pico, 0)} °/s, inverosímil para la pelvis: "
                    "revisar el etiquetado de sus marcadores"
                )
            if not (inicio_conocido and fin_conocido):
                notas.append("cambio de rumbo y duración son lo que se ve, como mínimo")
            elif desde is None or hasta is None:
                notas.append("el cambio de rumbo es el que se ve, como mínimo")
            i_inicio, i_fin = int(tramo[primero]), int(tramo[ultimo])
            giros.append(
                Giro(
                    sentido="izquierda" if s > 0 else "derecha",
                    fotograma_inicio=ensayo.fotograma(i_inicio) if inicio_conocido else None,
                    fotograma_fin=ensayo.fotograma(i_fin) if fin_conocido else None,
                    inicio_desde=ensayo.fotograma(tramo[desde]) if desde is not None else None,
                    fin_hasta=ensayo.fotograma(tramo[hasta]) if hasta is not None else None,
                    tiempo_inicio_s=ensayo.tiempo(i_inicio) if inicio_conocido else None,
                    tiempo_fin_s=ensayo.tiempo(i_fin) if fin_conocido else None,
                    cambio_rumbo_grados=abs(cambio),
                    velocidad_pico_grados_s=pico,
                    duracion_s=duracion,
                    confianza="baja" if notas else "normal",
                    nota="; ".join(notas),
                )
            )

    if not giros:
        return ResultadoGiros(
            (),
            f"No se proponen giros: la pelvis supera {umbral} °/s en {candidatos} tramo(s), pero ninguno "
            f"dura más de {numero(p.duracion_minima_s)} s con un cambio de rumbo de al menos "
            f"{numero(p.giro_minimo_grados)}° (máximo: {numero(maxima)} °/s).",
            velocidad_maxima_grados_s=maxima,
            **comun,
        )
    return ResultadoGiros(tuple(giros), None, velocidad_maxima_grados_s=maxima, **comun)
