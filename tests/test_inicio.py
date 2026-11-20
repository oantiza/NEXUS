"""Primer movimiento al iniciar la marcha (experimental), con datos sintéticos."""

from pathlib import Path

import numpy as np
import pytest

from nexus_mocap.inicio import ParametrosInicio, proponer_inicio
from nexus_mocap.lectura import Ensayo

FRECUENCIA = 100.0
ETIQUETAS = ("Sujeto:LASI", "Sujeto:RASI", "Sujeto:LPSI", "Sujeto:RPSI", "Sujeto:C7", "LHEE", "RHEE")
# Momentos en que empieza a moverse cada parte en el ensayo simulado (s).
TRONCO_S, PELVIS_S, TALON_DERECHO_S, TALON_IZQUIERDO_S = 2.00, 2.15, 2.35, 2.90
# Un inicio detectado puede quedar algo después del verdadero (hace falta apartarse del ruido),
# nunca antes de más de un par de fotogramas.
TOLERANCIA_S = 0.15


def _minimo_tiron(t, inicio, duracion):
    u = np.clip((t - inicio) / duracion, 0.0, 1.0)
    return 10 * u**3 - 15 * u**4 + 6 * u**5


def _iniciacion(total_s=5.0, ruido_mm=0.3, balanceo_mm=1.5, semilla=7, quieto_s=None, y_arriba=False):
    """De pie y quieto, luego inclina el tronco, adelanta la pelvis y levanta el talón derecho y el izquierdo.

    El reposo tiene ruido de medida y un balanceo lento de la pelvis, como en bipedestación real.
    """
    g = np.random.default_rng(semilla)
    t = np.arange(int(total_s * FRECUENCIA)) / FRECUENCIA
    desplazamiento = {
        "tronco": TRONCO_S,
        "pelvis": PELVIS_S,
        "dcho": TALON_DERECHO_S,
        "izdo": TALON_IZQUIERDO_S,
    }
    if quieto_s is not None:  # adelanta todo para que el reposo dure ``quieto_s``
        desplazamiento = {k: v - (TRONCO_S - quieto_s) for k, v in desplazamiento.items()}
    # Pelvis: arranca con un perfil suave y sigue a 1 m/s.
    avance = 400.0 * _minimo_tiron(t, desplazamiento["pelvis"], 0.8)
    avance += np.clip(t - desplazamiento["pelvis"] - 0.8, 0, None) * 1000.0
    balanceo = balanceo_mm * np.sin(2 * np.pi * 0.3 * t + 0.4)
    x = avance + balanceo
    flexion = np.radians(15.0) * _minimo_tiron(t, desplazamiento["tronco"], 0.6)

    def punto(dx, dy, z):
        return np.stack([x + dx, np.full_like(t, dy), np.full_like(t, z)], axis=1)

    c7 = np.stack([x - 90 + 520 * np.sin(flexion), np.zeros_like(t), 980 + 520 * np.cos(flexion)], axis=1)
    talon = {}
    for lado in ("izdo", "dcho"):
        subida = 70.0 * _minimo_tiron(t, desplazamiento[lado], 0.25)
        talon[lado] = punto(-60, 100 if lado == "izdo" else -100, 0) + np.stack(
            [np.zeros_like(t), np.zeros_like(t), 45 + subida], axis=1
        )
    posiciones = np.array(
        [
            punto(60, 120, 950),
            punto(60, -120, 950),
            punto(-90, 45, 980),
            punto(-90, -45, 980),
            c7,
            talon["izdo"],
            talon["dcho"],
        ]
    )
    posiciones = posiciones + g.normal(scale=ruido_mm, size=posiciones.shape)
    if y_arriba:
        posiciones = posiciones[:, :, [1, 2, 0]]
    return Ensayo(Path("inicio.c3d"), ETIQUETAS, posiciones, FRECUENCIA, 1)


def _por_senal(resultado):
    return {i.senal: i for i in resultado.inicios}


def _comprobar_cerca(inicio, verdad):
    assert verdad - 0.02 <= inicio.tiempo_s <= verdad + TOLERANCIA_S, (inicio.senal, inicio.tiempo_s, verdad)


@pytest.mark.parametrize("y_arriba", [False, True])
def test_reposo_y_despues_movimiento_inicios_y_orden(y_arriba):
    resultado = proponer_inicio(_iniciacion(y_arriba=y_arriba))

    assert resultado.motivo is None
    inicios = _por_senal(resultado)
    assert set(inicios) == {"pelvis", "tronco", "talón izquierdo", "talón derecho"}
    _comprobar_cerca(inicios["tronco"], TRONCO_S)
    _comprobar_cerca(inicios["pelvis"], PELVIS_S)
    _comprobar_cerca(inicios["talón derecho"], TALON_DERECHO_S)
    _comprobar_cerca(inicios["talón izquierdo"], TALON_IZQUIERDO_S)
    assert [i.senal for i in resultado.inicios] == ["tronco", "pelvis", "talón derecho", "talón izquierdo"]
    assert resultado.primero == "tronco"
    assert resultado.primer_talon == "derecho"
    for i in resultado.inicios:
        assert i.fotograma_desde <= i.fotograma <= i.fotograma_hasta
    # El reposo de referencia acaba donde empieza el primer movimiento (el inicio a 1 DE puede
    # quedar uno o dos fotogramas dentro) y dura al menos 1 s.
    assert abs(resultado.reposo_hasta - inicios["tronco"].fotograma) <= 2
    assert resultado.reposo_hasta - resultado.reposo_desde + 1 >= FRECUENCIA


def test_respeta_la_numeracion_original_de_fotogramas():
    ensayo = _iniciacion()
    desplazado = Ensayo(ensayo.ruta, ensayo.etiquetas, ensayo.posiciones, FRECUENCIA, 1001)

    uno, otro = proponer_inicio(ensayo), proponer_inicio(desplazado)

    assert [i.fotograma + 1000 for i in uno.inicios] == [i.fotograma for i in otro.inicios]
    assert otro.reposo_desde == 1001


def test_sin_tronco_propone_pelvis_y_talones():
    ensayo = _iniciacion()
    sin_c7 = Ensayo(
        ensayo.ruta, ETIQUETAS[:4] + ETIQUETAS[5:], ensayo.posiciones[[0, 1, 2, 3, 5, 6]], 100.0, 1
    )

    resultado = proponer_inicio(sin_c7)

    assert {i.senal for i in resultado.inicios} == {"pelvis", "talón izquierdo", "talón derecho"}
    assert resultado.primero == "pelvis"
    assert any("tronco" in nota for nota in resultado.notas)


def test_si_empieza_andando_no_propone_y_explica():
    ensayo = _iniciacion(quieto_s=0.3)

    resultado = proponer_inicio(ensayo)

    assert resultado.inicios == ()
    assert "no empieza con al menos 1 s de pie y quieto" in resultado.motivo


def test_un_reposo_mas_ruidoso_retrasa_pero_no_rompe_la_deteccion():
    limpio = _por_senal(proponer_inicio(_iniciacion()))
    ruidoso_resultado = proponer_inicio(_iniciacion(ruido_mm=1.0, balanceo_mm=4.0))

    assert ruidoso_resultado.motivo is None
    ruidoso = _por_senal(ruidoso_resultado)
    assert set(ruidoso) == set(limpio)
    for senal, verdad in (
        ("tronco", TRONCO_S),
        ("pelvis", PELVIS_S),
        ("talón derecho", TALON_DERECHO_S),
        ("talón izquierdo", TALON_IZQUIERDO_S),
    ):
        assert ruidoso[senal].fotograma >= limpio[senal].fotograma - 2
        assert verdad - 0.02 <= ruidoso[senal].tiempo_s <= verdad + 0.3
    assert ruidoso_resultado.primer_talon == "derecho"


def test_sin_pelvis_no_propone_y_explica():
    ensayo = _iniciacion()
    solo_pies = Ensayo(ensayo.ruta, ETIQUETAS[5:], ensayo.posiciones[5:], FRECUENCIA, 1)

    resultado = proponer_inicio(solo_pies)

    assert resultado.inicios == ()
    assert "faltan los marcadores de la pelvis" in resultado.motivo


def test_quieto_todo_el_ensayo_no_propone():
    ensayo = _iniciacion()
    quieto = Ensayo(ensayo.ruta, ETIQUETAS, ensayo.posiciones[:, :180], FRECUENCIA, 1)

    resultado = proponer_inicio(quieto)

    assert resultado.inicios == ()
    assert "no se detecta" in resultado.motivo


def test_los_umbrales_se_pueden_cambiar():
    ensayo = _iniciacion()

    estricto = _por_senal(proponer_inicio(ensayo, ParametrosInicio(de_deteccion=30.0, de_inicio=20.0)))
    normal = _por_senal(proponer_inicio(ensayo))

    assert estricto["pelvis"].fotograma > normal["pelvis"].fotograma


def test_no_modifica_los_datos_de_entrada():
    ensayo = _iniciacion()
    posiciones = ensayo.posiciones.copy()
    posiciones[2, 50:55] = np.nan
    copia = posiciones.copy()

    proponer_inicio(Ensayo(ensayo.ruta, ETIQUETAS, posiciones, FRECUENCIA, 1))

    np.testing.assert_array_equal(posiciones, copia)
