from pathlib import Path

import numpy as np
import pytest

from nexus_mocap.comprobacion import comprobar
from nexus_mocap.lectura import Ensayo
from nexus_mocap.saltos import detectar_saltos

FRECUENCIA = 100.0


def _ensayo(posiciones, etiquetas=None, primer_fotograma=1, frecuencia=FRECUENCIA):
    posiciones = np.asarray(posiciones, dtype=float)
    etiquetas = etiquetas or [f"M{i + 1}" for i in range(posiciones.shape[0])]
    return Ensayo(Path("sintetico.c3d"), tuple(etiquetas), posiciones, frecuencia, primer_fotograma)


def _segmento(n_fotogramas=400, ruido_mm=0.2, semilla=1, frecuencia=FRECUENCIA):
    """Cuatro marcadores solidarios que avanzan y oscilan como un segmento al caminar."""
    generador = np.random.default_rng(semilla)
    t = np.arange(n_fotogramas) / frecuencia
    centro = np.stack(
        [1200 * t, 40 * np.sin(2 * np.pi * 1.0 * t), 900 + 25 * np.sin(2 * np.pi * 2.0 * t)], axis=1
    )
    separacion = np.array([[0, 0, 0], [80, 0, 0], [0, 60, 0], [0, 0, 120]], dtype=float)
    posiciones = centro[None, :, :] + separacion[:, None, :]
    return posiciones + generador.normal(scale=ruido_mm, size=posiciones.shape)


def test_encuentra_un_salto_lateral_y_propone_la_posicion_real():
    posiciones = _segmento()
    real = posiciones[1, 150].copy()
    posiciones[1, 150, 1] += 14.0

    saltos = detectar_saltos(_ensayo(posiciones))

    assert [(s.marcador, s.indice) for s in saltos] == [("M2", 150)]
    salto = saltos[0]
    assert salto.clasificacion == "aislado"
    assert salto.confianza == "alta"
    assert salto.eje == "Y"
    assert salto.desviacion_mm == pytest.approx(14.0, abs=1.0)
    assert np.linalg.norm(np.asarray(salto.propuesta) - real) < 1.0


def test_un_registro_limpio_no_da_avisos():
    assert detectar_saltos(_ensayo(_segmento())) == []


@pytest.mark.parametrize("frecuencia", [50.0, 100.0, 200.0])
def test_el_temblor_no_se_marca_como_salto(frecuencia):
    posiciones = _segmento(frecuencia=frecuencia)
    t = np.arange(posiciones.shape[1]) / frecuencia
    # Temblor de 5 Hz y 12 mm de amplitud en un marcador, como en una mano.
    posiciones[2, :, 1] += 12 * np.sin(2 * np.pi * 5.0 * t)

    assert detectar_saltos(_ensayo(posiciones, frecuencia=frecuencia)) == []


def test_una_parada_brusca_no_se_marca_como_salto():
    posiciones = _segmento(ruido_mm=0.1)
    # El segmento entero se detiene de golpe, como en un bloqueo de la marcha.
    posiciones[:, 200:, :] = posiciones[:, 200:201, :]

    assert detectar_saltos(_ensayo(posiciones)) == []


def test_si_el_segmento_acompana_no_se_propone_correccion():
    posiciones = _segmento()
    posiciones[:, 220, 1] += 12.0  # todos los marcadores se desplazan a la vez

    saltos = detectar_saltos(_ensayo(posiciones))

    assert saltos, "el movimiento conjunto debe señalarse para revisión"
    assert {s.indice for s in saltos} == {220}
    assert all(s.clasificacion == "acompañado" for s in saltos)
    assert all(s.propuesta is None and s.confianza == "baja" for s in saltos)


def test_respeta_la_numeracion_original_de_fotogramas():
    posiciones = _segmento()
    posiciones[0, 99, 2] += 20.0

    (salto,) = detectar_saltos(_ensayo(posiciones, primer_fotograma=300))

    assert salto.fotograma == 399
    assert salto.tiempo_s == pytest.approx(398 / FRECUENCIA)


def test_junto_a_un_hueco_baja_la_confianza():
    posiciones = _segmento()
    posiciones[3, 180, 0] += 18.0
    posiciones[3, 182:190] = np.nan  # el marcador se pierde justo después

    (salto,) = detectar_saltos(_ensayo(posiciones))

    assert (salto.marcador, salto.indice) == ("M4", 180)
    assert salto.clasificacion == "aislado"
    assert salto.confianza == "media"


def test_los_huecos_no_provocan_avisos():
    posiciones = _segmento()
    posiciones[0, 50:70] = np.nan
    posiciones[2, 300:] = np.nan

    assert detectar_saltos(_ensayo(posiciones)) == []


def test_no_modifica_los_datos_de_entrada():
    posiciones = _segmento()
    posiciones[1, 150, 1] += 14.0
    copia = posiciones.copy()

    detectar_saltos(_ensayo(posiciones))

    np.testing.assert_array_equal(posiciones, copia)


def test_comprobacion_con_valor_conocido():
    ensayo = _ensayo(_segmento(n_fotogramas=1000))
    original = ensayo.posiciones.copy()

    resultado = comprobar(ensayo, n=30, magnitud_mm=15.0, semilla=3)

    assert resultado.insertados == 30
    assert resultado.detectados == 30
    assert resultado.error_mediano_mm < 1.0
    assert resultado.avisos_nuevos_falsos == 0
    np.testing.assert_array_equal(ensayo.posiciones, original)
