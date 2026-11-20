"""Casos encontrados al pasar el programa por los 106 archivos de ejemplo de C3D.org."""

from pathlib import Path

import numpy as np
import pytest

from nexus_mocap.eventos import Evento, _sin_repetidos, marcadores_del_pie, proponer_eventos
from nexus_mocap.lectura import Ensayo, _escala_a_milimetros, _fotogramas_declarados, leer_c3d

ezc3d = pytest.importorskip("ezc3d")
from test_eventos import ETIQUETAS, FRECUENCIA, _marcha  # noqa: E402


@pytest.mark.parametrize(
    "etiquetas",
    [
        ("L.Heel", "L.Toe", "L.Ankle", "R.Heel", "R.Toe", "R.Ankle"),
        ("l_heel", "l_toe", "l_ankle", "r_heel", "r_toe", "r_ankle"),
        (
            "Sujeto:l heel",
            "Sujeto:l toe",
            "Sujeto:l ankle",
            "Sujeto:r heel",
            "Sujeto:r toe",
            "Sujeto:r ankle",
        ),
        ("LCAL", "LTOE", "LANK", "RCAL", "RTOE", "RANK"),
    ],
)
def test_reconoce_otras_formas_de_nombrar_los_marcadores_del_pie(etiquetas):
    posiciones, _ = _marcha()
    ensayo = Ensayo(Path("otro.c3d"), etiquetas, posiciones, FRECUENCIA, 1)

    usados = marcadores_del_pie(ensayo, "izquierdo")
    eventos = proponer_eventos(ensayo)

    assert usados["contacto"][0] == 0 and usados["despegue"][0] == 1
    assert sum(1 for e in eventos if e.tipo == "contacto") == 8
    assert sum(1 for e in eventos if e.tipo == "despegue") == 8


def test_no_confunde_marcadores_que_solo_se_parecen():
    posiciones, _ = _marcha()
    etiquetas = ("LHEEX", "LTOES", "LANKLEM", "RHEE2", "RTO", "RANKL")
    ensayo = Ensayo(Path("otro.c3d"), etiquetas, posiciones, FRECUENCIA, 1)

    assert marcadores_del_pie(ensayo, "izquierdo") == {"contacto": None, "despegue": None}
    assert proponer_eventos(ensayo) == []


@pytest.mark.parametrize(
    ("unidad", "factor"),
    [
        ("mm", 1.0),
        ("MM", 1.0),
        ("millimeters", 1.0),
        ("cm", 10.0),
        ("m", 1000.0),
        ("mete", 1000.0),
        ("in", 25.4),
    ],
)
def test_unidades_de_posicion(unidad, factor):
    assert _escala_a_milimetros(unidad) == factor


def test_unidad_desconocida_no_se_adivina():
    assert _escala_a_milimetros("codos") is None


def _c3d(ruta, unidades):
    puntos = np.ones((4, 2, 60))
    puntos[:3] = 0.5
    c3d = ezc3d.c3d()
    c3d["parameters"]["POINT"]["RATE"]["value"] = [100.0]
    c3d["parameters"]["POINT"]["UNITS"]["value"] = [unidades]
    c3d["parameters"]["POINT"]["LABELS"]["value"] = ("A", "B")
    c3d["data"]["points"] = puntos
    c3d.write(str(ruta))
    return ruta


def test_unidad_recortada_se_lee_como_metros(tmp_path):
    ensayo = leer_c3d(_c3d(tmp_path / "metros.c3d", "mete"))

    assert np.nanmax(ensayo.posiciones) == pytest.approx(500.0)
    assert ensayo.avisos == ()


def test_sin_unidad_se_avisa(tmp_path):
    ensayo = leer_c3d(_c3d(tmp_path / "sin_unidad.c3d", ""))

    assert any("unidad" in aviso for aviso in ensayo.avisos)


def test_el_error_no_muestra_la_ruta_completa(tmp_path):
    ruta = tmp_path / "solo_sin_etiquetar.c3d"
    puntos = np.ones((4, 1, 30))
    c3d = ezc3d.c3d()
    c3d["parameters"]["POINT"]["RATE"]["value"] = [100.0]
    c3d["parameters"]["POINT"]["LABELS"]["value"] = ("*1",)
    c3d["data"]["points"] = puntos
    c3d.write(str(ruta))

    with pytest.raises(ValueError) as error:
        leer_c3d(ruta)
    assert ruta.name in str(error.value) and str(tmp_path) not in str(error.value)


def test_fotogramas_declarados_fuera_de_la_cabecera():
    assert _fotogramas_declarados({"POINT": {"LONG_FRAMES": {"value": [72610.0]}}}) == 72610
    campos = {"ACTUAL_START_FIELD": {"value": [1, 0]}, "ACTUAL_END_FIELD": {"value": [7074, 1]}}
    assert _fotogramas_declarados({"TRIAL": campos}) == 72610
    assert _fotogramas_declarados({"POINT": {"LONG_FRAMES": {"value": [-1, 0]}}}) == 65535
    assert _fotogramas_declarados({"POINT": {}}) is None


def _evento(tiempo, pico, lado="izquierdo", tipo="despegue"):
    fotograma = int(round(tiempo * 100)) + 1
    return Evento(lado, tipo, fotograma, tiempo, fotograma - 1, fotograma + 1, "normal", "LTOE", pico)


def test_dos_propuestas_del_mismo_balanceo_se_quedan_en_una():
    eventos = [
        _evento(1.00, 3000.0),
        _evento(1.02, 4200.0),
        _evento(2.10, 4000.0),
        _evento(1.01, 3900.0, "derecho"),
    ]

    conservados = _sin_repetidos(eventos, 0.15)

    assert [(e.lado, e.tiempo_s) for e in sorted(conservados, key=lambda e: e.tiempo_s)] == [
        ("derecho", 1.01),
        ("izquierdo", 1.02),
        ("izquierdo", 2.10),
    ]


def test_las_etiquetas_de_prueba_siguen_siendo_las_habituales():
    assert ETIQUETAS[0] == "LHEE"
