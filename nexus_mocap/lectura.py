"""Lectura de grabaciones C3D. Solo lectura: este módulo nunca escribe en el archivo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Grupos de POINT que en los C3D de Vicon contienen resultados del modelo
# (ángulos, fuerzas, centros articulares...) y no posiciones de marcadores. Si el
# archivo trae POINT:TYPE_GROUPS, se añaden los grupos que enumera.
_GRUPOS_NO_MARCADOR = ("ANGLES", "FORCES", "MOMENTS", "POWERS", "SCALARS", "MODELED_MARKERS")

# Un segmento del modelo (Plug-in Gait, CGM) se guarda como cuatro puntos con el
# mismo nombre y un final distinto: origen y tres ejes (PELO, PELA, PELL, PELP).
# Otros programas ponen el eje delante (o_Trunk, x_Trunk, y_Trunk, z_Trunk).
_EJES_DE_SEGMENTO = (("O", "A", "L", "P"), ("O", "X", "Y", "Z"))
_EJES_DELANTE = ("o_", "x_", "y_", "z_")


def _escala_a_milimetros(unidad: str) -> float | None:
    """Factor para pasar a milímetros. Algunos programas recortan o alargan el nombre de la unidad."""
    u = unidad.strip().lower()
    if u in ("mm", "mms") or u.startswith("mil"):
        return 1.0
    if u == "cm" or u.startswith("cent"):
        return 10.0
    if u == "dm" or u.startswith("dec"):
        return 100.0
    if u == "m" or u.startswith("met"):
        return 1000.0
    if u in ("in", "inch", "inches"):
        return 25.4
    return None


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
    avisos: tuple[str, ...] = ()
    """Circunstancias del archivo que conviene que sepa quien lee el informe."""

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

    Se descartan las salidas del modelo (ángulos, fuerzas, momentos, potencias,
    centros articulares y ejes de los segmentos) y, salvo que se pida lo
    contrario, las trayectorias sin etiquetar (``*12``).
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

    no_marcador = _salidas_del_modelo(grupo, etiquetas)

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
        raise ValueError(f"El archivo no contiene trayectorias de marcadores con etiqueta: {ruta.name}")

    avisos: list[str] = []
    unidades = _valores(grupo, "UNITS")
    unidad = unidades[0].strip() if unidades else ""
    if not unidad:
        escala = 1.0
        avisos.append("El archivo no indica la unidad de las posiciones; se han tomado como milímetros.")
    else:
        escala = _escala_a_milimetros(unidad)
        if escala is None:
            raise ValueError(f"Unidades de posición no reconocidas en el archivo: {unidad!r}")

    esperados = _fotogramas_declarados(c3d["parameters"])
    if esperados is not None and esperados > puntos.shape[2]:
        avisos.append(
            f"El archivo declara {esperados} fotogramas, pero solo se han podido leer {puntos.shape[2]}: "
            "el final del ensayo no está revisado."
        )

    posiciones = np.transpose(puntos[:3, indices, :], (1, 2, 0)) * escala
    # Algunos programas guardan el marcador ausente como (0, 0, 0).
    ausente = np.all(posiciones == 0.0, axis=2) | np.any(np.isnan(posiciones), axis=2)
    posiciones[ausente] = np.nan

    return Ensayo(
        ruta=ruta,
        etiquetas=tuple(etiquetas[i] for i in indices),
        posiciones=posiciones,
        frecuencia=float(c3d["header"]["points"]["frame_rate"]),
        primer_fotograma=_primer_fotograma(c3d),
        avisos=tuple(avisos),
    )


def _salidas_del_modelo(grupo: dict, etiquetas: list[str]) -> set[str]:
    """Etiquetas de POINT que el modelo calculó y que no son marcadores colocados en el paciente."""
    nombres = set(_GRUPOS_NO_MARCADOR)
    # TYPE_GROUPS alterna el nombre del grupo y el de su tipo (ANGLES, ANGLE...). Solo
    # cuentan los que existen como parámetro; LABELS y DESCRIPTIONS nunca se descartan.
    for nombre in _valores(grupo, "TYPE_GROUPS"):
        nombre = nombre.upper()
        if nombre in grupo and not nombre.startswith(("LABELS", "DESCRIPTIONS")):
            nombres.add(nombre)
    resultado: set[str] = set()
    for nombre in nombres:
        resultado.update(_valores(grupo, nombre))

    presentes = set(etiquetas)
    for etiqueta in etiquetas:
        raiz = etiqueta[:-1]
        if len(raiz.split(":")[-1]) < 2:  # «RA», «RP»... pueden ser marcadores de verdad
            continue
        for ejes in _EJES_DE_SEGMENTO:
            if etiqueta[-1] != ejes[0]:
                continue
            segmento = {raiz + eje for eje in ejes}
            if segmento <= presentes:
                resultado.update(segmento)
        sujeto, _, corta = etiqueta.rpartition(":")
        prefijo = f"{sujeto}:" if sujeto else ""
        if corta.startswith(_EJES_DELANTE[0]) and len(corta) > 3:
            segmento = {prefijo + eje + corta[2:] for eje in _EJES_DELANTE}
            if segmento <= presentes:
                resultado.update(segmento)
    return resultado


def _dos_palabras(valores) -> int:
    """Valor guardado en dos enteros de 16 bits; algunos lectores los devuelven con signo."""
    return (int(valores[0]) & 0xFFFF) + 65536 * (int(valores[1]) & 0xFFFF)


def _primer_fotograma(c3d) -> int:
    """Número original del primer fotograma.

    La cabecera solo guarda 16 bits; cuando existe, TRIAL:ACTUAL_START_FIELD lo
    guarda completo, en dos palabras.
    """
    try:
        inicio = c3d["parameters"].get("TRIAL", {}).get("ACTUAL_START_FIELD", {}).get("value", [])
        if len(inicio) >= 2:
            return _dos_palabras(inicio)
    except (TypeError, ValueError):
        pass
    return int(c3d["header"]["points"]["first_frame"]) + 1


def _fotogramas_declarados(parametros: dict) -> int | None:
    """Número de fotogramas que el archivo dice tener, cuando lo guarda fuera de la cabecera.

    La cabecera de un C3D solo llega a 65535; los ensayos más largos lo anotan aparte.
    """
    try:
        largo = parametros.get("POINT", {}).get("LONG_FRAMES", {}).get("value", [])
        if len(largo) >= 2:
            return _dos_palabras(largo)
        if len(largo) == 1:
            return int(round(float(largo[0])))
        ensayo = parametros.get("TRIAL", {})
        inicio = ensayo.get("ACTUAL_START_FIELD", {}).get("value", [])
        fin = ensayo.get("ACTUAL_END_FIELD", {}).get("value", [])
        if len(inicio) >= 2 and len(fin) >= 2:
            return _dos_palabras(fin) - _dos_palabras(inicio) + 1
    except (TypeError, ValueError):
        return None
    return None


@dataclass(frozen=True)
class EventoRegistrado:
    """Evento de marcha que ya está guardado en el C3D (marcado en Nexus u otro programa)."""

    lado: str  # "izquierdo" o "derecho"
    tipo: str  # "contacto" o "despegue"
    tiempo_s: float


_CODIGOS = {"LHS": ("izquierdo", "contacto"), "RHS": ("derecho", "contacto")}
_CODIGOS |= {"LTO": ("izquierdo", "despegue"), "RTO": ("derecho", "despegue")}


def leer_eventos(ruta: str | Path) -> list[EventoRegistrado]:
    """Lee los contactos y despegues del pie guardados en el C3D, si los hay."""
    import ezc3d

    grupo = ezc3d.c3d(str(ruta))["parameters"].get("EVENT")
    if not grupo or "TIMES" not in grupo:
        return []
    tiempos = np.atleast_2d(np.asarray(grupo["TIMES"]["value"], dtype=float))
    if tiempos.shape[0] != 2:
        return []
    contextos = [str(v).strip() for v in grupo.get("CONTEXTS", {}).get("value", [])]
    etiquetas = [str(v).strip() for v in grupo.get("LABELS", {}).get("value", [])]

    eventos = []
    for i in range(tiempos.shape[1]):
        contexto = contextos[i] if i < len(contextos) else ""
        etiqueta = etiquetas[i] if i < len(etiquetas) else ""
        clave = _CODIGOS.get(contexto.upper()) or _CODIGOS.get(etiqueta.upper())
        if clave is None:
            lado = {"left": "izquierdo", "right": "derecho"}.get(contexto.lower())
            tipo = {"foot strike": "contacto", "foot off": "despegue"}.get(etiqueta.lower())
            if lado is None or tipo is None:
                continue
            clave = (lado, tipo)
        eventos.append(EventoRegistrado(*clave, tiempo_s=float(tiempos[0, i] * 60 + tiempos[1, i])))
    return sorted(eventos, key=lambda e: e.tiempo_s)
