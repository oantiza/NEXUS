"""Giros propuestos con la velocidad de giro de la pelvis (experimental), con datos sintéticos."""

from pathlib import Path

import numpy as np
import pytest

from nexus_mocap.giros import ParametrosGiros, eje_vertical, proponer_giros
from nexus_mocap.lectura import Ensayo

FRECUENCIA = 100.0
ETIQUETAS = ("Sujeto:LASI", "Sujeto:RASI", "Sujeto:LPSI", "Sujeto:RPSI", "LHEE", "RHEE", "LTOE", "RTOE")
# Tolerancia frente a los cruces exactos de 30 °/s del perfil simulado: el filtro de 1,5 Hz los
# desplaza unos fotogramas.
TOLERANCIA_S = 0.1


def _perfil_giro(t, inicio, duracion, grados):
    """Rumbo (grados) de un giro cuya velocidad es ``2·grados/duración · sen²(π·u)``."""
    u = np.clip((t - inicio) / duracion, 0.0, 1.0)
    return grados * (u - np.sin(2 * np.pi * u) / (2 * np.pi))


def _velocidad_giro(t, inicio, duracion, grados):
    u = (t - inicio) / duracion
    return np.where((u > 0) & (u < 1), 2 * grados / duracion * np.sin(np.pi * u) ** 2, 0.0)


def _oscilacion(t, amplitud=4.0, hz=0.9):
    """Rotación de la pelvis con cada zancada al andar recto."""
    return amplitud * np.sin(2 * np.pi * hz * t)


def _ensayo(rumbo_grados, frecuencia=FRECUENCIA, ruido_mm=0.5, semilla=3, y_arriba=False):
    """Pelvis y pies que avanzan hacia donde mira la pelvis, con Z hacia arriba (o Y, si se pide)."""
    r = np.radians(rumbo_grados)
    delante = np.stack([np.cos(r), np.sin(r), np.zeros_like(r)], axis=1)
    izquierda = np.stack([-np.sin(r), np.cos(r), np.zeros_like(r)], axis=1)
    arriba = np.array([0.0, 0.0, 1.0])
    centro = np.cumsum(delante * 1000.0 / frecuencia, axis=0)

    def marcador(adelante, lateral, alto):
        return centro + adelante * delante + lateral * izquierda + alto * arriba

    posiciones = np.array(
        [
            marcador(60, 120, 950),
            marcador(60, -120, 950),
            marcador(-90, 45, 980),
            marcador(-90, -45, 980),
            marcador(0, 100, 50),
            marcador(0, -100, 50),
            marcador(180, 100, 30),
            marcador(180, -100, 30),
        ]
    )
    posiciones += np.random.default_rng(semilla).normal(scale=ruido_mm, size=posiciones.shape)
    if y_arriba:  # mismo movimiento con Y vertical: (x, y, z) pasa a (y, z, x), también dextrógiro
        posiciones = posiciones[:, :, [1, 2, 0]]
    return Ensayo(Path("giro.c3d"), ETIQUETAS, posiciones, frecuencia, 1)


def _media_vuelta(total_s=8.0, inicio=3.0, duracion=2.0, grados=180.0, oscilacion=True):
    t = np.arange(int(total_s * FRECUENCIA)) / FRECUENCIA
    rumbo = _perfil_giro(t, inicio, duracion, grados)
    velocidad = _velocidad_giro(t, inicio, duracion, grados)
    if oscilacion:
        rumbo = rumbo + _oscilacion(t)
        velocidad = velocidad + np.gradient(_oscilacion(t)) * FRECUENCIA
    return t, rumbo, velocidad


def _cruces_30(t, velocidad):
    """Tiempos del primer y el último fotograma por encima de 30 °/s en el perfil simulado."""
    encima = np.flatnonzero(np.abs(velocidad) > 30.0)
    return t[encima[0]], t[encima[-1]]


@pytest.mark.parametrize("oscilacion", [False, True])
def test_media_vuelta_inicio_final_sentido_y_angulo(oscilacion):
    t, rumbo, velocidad = _media_vuelta(oscilacion=oscilacion)
    verdad_inicio, verdad_fin = _cruces_30(t, velocidad)

    resultado = proponer_giros(_ensayo(rumbo))

    assert resultado.motivo is None
    (giro,) = resultado.giros
    assert giro.sentido == "izquierda"  # rumbo creciente: contrario a las agujas del reloj visto desde arriba
    assert abs(giro.tiempo_inicio_s - verdad_inicio) <= TOLERANCIA_S
    assert abs(giro.tiempo_fin_s - verdad_fin) <= TOLERANCIA_S
    assert giro.cambio_rumbo_grados == pytest.approx(180.0, abs=12.0)
    assert giro.velocidad_pico_grados_s == pytest.approx(180.0, rel=0.15)
    assert giro.inicio_desde < giro.fotograma_inicio < giro.fotograma_fin < giro.fin_hasta
    assert giro.duracion_s == pytest.approx((giro.fotograma_fin - giro.fotograma_inicio) / FRECUENCIA)
    assert giro.confianza == "normal" and giro.nota == ""
    assert "PSIS" in resultado.construccion and resultado.eje_vertical.startswith("Z")


def test_giro_a_la_derecha_y_numeracion_original():
    t, rumbo, _ = _media_vuelta(grados=-180.0)
    ensayo = _ensayo(rumbo)
    desplazado = Ensayo(ensayo.ruta, ensayo.etiquetas, ensayo.posiciones, FRECUENCIA, 501)

    (giro,) = proponer_giros(ensayo).giros
    (otro,) = proponer_giros(desplazado).giros

    assert giro.sentido == "derecha"
    assert otro.fotograma_inicio == giro.fotograma_inicio + 500
    assert otro.fin_hasta == giro.fin_hasta + 500


def test_giro_lento_por_debajo_de_30_no_se_propone():
    t = np.arange(int(20 * FRECUENCIA)) / FRECUENCIA
    rumbo = _perfil_giro(t, 2.0, 15.0, 180.0)  # pico de 24 °/s

    resultado = proponer_giros(_ensayo(rumbo))

    assert resultado.giros == ()
    assert "no supera 30 °/s" in resultado.motivo
    assert resultado.velocidad_maxima_grados_s == pytest.approx(24.0, abs=1.5)


def test_vacilacion_breve_dentro_del_giro_se_une():
    t = np.arange(int(9 * FRECUENCIA)) / FRECUENCIA
    rumbo = _perfil_giro(t, 3.0, 1.0, 90.0) + _perfil_giro(t, 4.3, 1.0, 90.0)  # 0,3 s parado a mitad

    (giro,) = proponer_giros(_ensayo(rumbo)).giros

    assert giro.cambio_rumbo_grados == pytest.approx(180.0, abs=10.0)
    assert giro.tiempo_inicio_s < 3.3 and giro.tiempo_fin_s > 5.0


def test_dos_giros_separados_por_una_pausa_larga_no_se_unen():
    t = np.arange(int(10 * FRECUENCIA)) / FRECUENCIA
    rumbo = _perfil_giro(t, 3.0, 1.0, 90.0) + _perfil_giro(t, 5.5, 1.0, 90.0)  # 1,5 s parado

    giros = proponer_giros(_ensayo(rumbo)).giros

    assert len(giros) == 2
    assert all(g.cambio_rumbo_grados == pytest.approx(90.0, abs=10.0) for g in giros)


def test_andar_recto_no_propone_giros():
    t = np.arange(int(10 * FRECUENCIA)) / FRECUENCIA

    resultado = proponer_giros(_ensayo(_oscilacion(t, amplitud=5.0)))

    assert resultado.giros == ()
    assert resultado.motivo.startswith("No se proponen giros")


def test_un_giro_pequeno_no_se_propone():
    t = np.arange(int(8 * FRECUENCIA)) / FRECUENCIA

    resultado = proponer_giros(_ensayo(_perfil_giro(t, 3.0, 0.8, 30.0)))  # 30° con pico de 75 °/s

    assert resultado.giros == ()
    assert "45°" in resultado.motivo


def test_sin_marcadores_de_pelvis_no_propone_y_explica():
    t, rumbo, _ = _media_vuelta()
    ensayo = _ensayo(rumbo)
    sin_pelvis = Ensayo(ensayo.ruta, ETIQUETAS[4:], ensayo.posiciones[4:], FRECUENCIA, 1)
    vacios = ensayo.posiciones.copy()
    vacios[:4] = np.nan  # las etiquetas existen pero no hay datos

    for caso in (sin_pelvis, Ensayo(ensayo.ruta, ETIQUETAS, vacios, FRECUENCIA, 1)):
        resultado = proponer_giros(caso)
        assert resultado.giros == ()
        assert "faltan los marcadores de la pelvis" in resultado.motivo


def test_solo_con_las_asis_tambien_funciona():
    t, rumbo, velocidad = _media_vuelta()
    ensayo = _ensayo(rumbo)
    solo_asis = Ensayo(
        ensayo.ruta, ETIQUETAS[:2] + ETIQUETAS[4:], ensayo.posiciones[[0, 1, 4, 5, 6, 7]], 100.0, 1
    )

    resultado = proponer_giros(solo_asis)

    (giro,) = resultado.giros
    assert "ASIS" in resultado.construccion and "PSIS" not in resultado.construccion
    assert giro.sentido == "izquierda"
    assert abs(giro.tiempo_inicio_s - _cruces_30(t, velocidad)[0]) <= TOLERANCIA_S


def test_con_y_hacia_arriba():
    t, rumbo, velocidad = _media_vuelta()
    ensayo = _ensayo(rumbo, y_arriba=True)

    resultado = proponer_giros(ensayo)

    assert eje_vertical(ensayo)[:2] == (1, 1.0)
    assert resultado.eje_vertical.startswith("Y")
    (giro,) = resultado.giros
    assert giro.sentido == "izquierda"
    verdad_inicio, verdad_fin = _cruces_30(t, velocidad)
    assert abs(giro.tiempo_inicio_s - verdad_inicio) <= TOLERANCIA_S
    assert abs(giro.tiempo_fin_s - verdad_fin) <= TOLERANCIA_S


def test_giro_cortado_por_el_final_del_registro_tiene_confianza_baja():
    t, rumbo, velocidad = _media_vuelta()
    ensayo = _ensayo(rumbo)
    corte = int(4.5 * FRECUENCIA)  # a tres cuartos del giro, todavía a más de 30 °/s
    cortado = Ensayo(ensayo.ruta, ETIQUETAS, ensayo.posiciones[:, :corte], FRECUENCIA, 1)

    (giro,) = proponer_giros(cortado).giros

    assert giro.confianza == "baja"
    assert giro.fotograma_fin is None and giro.fin_hasta is None and giro.tiempo_fin_s is None
    assert "final del registro" in giro.nota
    assert abs(giro.tiempo_inicio_s - _cruces_30(t, velocidad)[0]) <= TOLERANCIA_S


def test_un_hueco_largo_no_inventa_limites():
    t, rumbo, _ = _media_vuelta(oscilacion=False)
    posiciones = _ensayo(rumbo).posiciones.copy()
    posiciones[:4, 380:440] = np.nan  # la pelvis se pierde 0,6 s en mitad del giro

    giros = proponer_giros(Ensayo(Path("g.c3d"), ETIQUETAS, posiciones, FRECUENCIA, 1)).giros

    # Lo registrado antes del hueco ya dura más de 0,5 s: se propone el inicio y el final queda vacío.
    # Lo que se ve después del hueco no llega a ninguno de los dos mínimos y no se propone.
    (giro,) = giros
    assert giro.confianza == "baja" and "hueco largo" in giro.nota
    assert giro.fotograma_inicio is not None and giro.fotograma_fin is None and giro.fin_hasta is None


def test_un_hueco_corto_se_salva():
    t, rumbo, _ = _media_vuelta(oscilacion=False)
    posiciones = _ensayo(rumbo).posiciones.copy()
    posiciones[:4, 380:388] = np.nan  # 0,08 s

    (giro,) = proponer_giros(Ensayo(Path("g.c3d"), ETIQUETAS, posiciones, FRECUENCIA, 1)).giros

    assert giro.confianza == "normal"


def test_los_umbrales_se_pueden_cambiar():
    t = np.arange(int(20 * FRECUENCIA)) / FRECUENCIA
    rumbo = _perfil_giro(t, 2.0, 15.0, 180.0)  # pico de 24 °/s

    giros = proponer_giros(_ensayo(rumbo), ParametrosGiros(umbral_giro_grados_s=20.0)).giros

    assert len(giros) == 1


def test_no_modifica_los_datos_de_entrada():
    t, rumbo, _ = _media_vuelta()
    posiciones = _ensayo(rumbo).posiciones.copy()
    posiciones[0, 100:105] = np.nan
    copia = posiciones.copy()

    proponer_giros(Ensayo(Path("g.c3d"), ETIQUETAS, posiciones, FRECUENCIA, 1))

    np.testing.assert_array_equal(posiciones, copia)
