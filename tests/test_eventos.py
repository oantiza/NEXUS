from pathlib import Path

import numpy as np
import pytest

from nexus_mocap.cli import main
from nexus_mocap.eventos import comparar, proponer_eventos
from nexus_mocap.lectura import Ensayo, EventoRegistrado, leer_eventos

ezc3d = pytest.importorskip("ezc3d")

FRECUENCIA = 100.0
BALANCEO_S = 0.4
CICLO_S = 1.1
ETIQUETAS = ("LHEE", "LTOE", "LANK", "RHEE", "RTOE", "RANK")


def _avance(t, inicio, longitud=1200.0):
    """Avance suave del pie durante un balanceo que empieza en ``inicio`` (perfil de mínima sacudida)."""
    u = np.clip((t - inicio) / BALANCEO_S, 0.0, 1.0)
    return longitud * (10 * u**3 - 15 * u**4 + 6 * u**5)


def _marcha(n_ciclos=4, frecuencia=FRECUENCIA, ruido_mm=0.3, semilla=5):
    """Dos pies que alternan apoyo y balanceo. Devuelve posiciones e inicios de balanceo por pie."""
    generador = np.random.default_rng(semilla)
    t = np.arange(int((n_ciclos * CICLO_S + 1.0) * frecuencia)) / frecuencia
    inicios = {
        "izquierdo": [0.4 + CICLO_S * i for i in range(n_ciclos)],
        "derecho": [0.4 + CICLO_S / 2 + CICLO_S * i for i in range(n_ciclos)],
    }
    posiciones = []
    for lado, lateral in (("izquierdo", 100.0), ("derecho", -100.0)):
        x = sum(_avance(t, inicio) for inicio in inicios[lado])
        for delante, alto in ((0.0, 40.0), (180.0, 30.0), (60.0, 90.0)):  # talón, punta, tobillo
            posiciones.append(
                np.stack([x + delante, np.full_like(t, lateral), np.full_like(t, alto)], axis=1)
            )
    posiciones = np.array(posiciones) + generador.normal(scale=ruido_mm, size=(6, t.size, 3))
    return posiciones, inicios


def _ensayo(posiciones, primer_fotograma=1, frecuencia=FRECUENCIA):
    return Ensayo(
        Path("sintetico.c3d"), ETIQUETAS, np.asarray(posiciones, dtype=float), frecuencia, primer_fotograma
    )


def _tiempos(eventos, lado, tipo):
    return [e.tiempo_s for e in eventos if e.lado == lado and e.tipo == tipo]


@pytest.mark.parametrize("frecuencia", [50.0, 100.0, 200.0])
def test_propone_un_contacto_y_un_despegue_por_paso(frecuencia):
    posiciones, inicios = _marcha(frecuencia=frecuencia)

    eventos = proponer_eventos(_ensayo(posiciones, frecuencia=frecuencia))

    for lado in ("izquierdo", "derecho"):
        despegues = _tiempos(eventos, lado, "despegue")
        contactos = _tiempos(eventos, lado, "contacto")
        assert len(despegues) == len(contactos) == len(inicios[lado])
        for inicio, despegue, contacto in zip(inicios[lado], despegues, contactos, strict=True):
            # El despegue cae poco después de que el pie empiece a moverse y el
            # contacto poco antes de que se detenga.
            assert 0.0 <= despegue - inicio <= 0.12
            assert 0.0 <= (inicio + BALANCEO_S) - contacto <= 0.12
    assert all(e.fotograma_desde <= e.fotograma <= e.fotograma_hasta for e in eventos)
    assert all(e.confianza == "normal" for e in eventos)


def test_usa_talon_para_el_contacto_y_punta_para_el_despegue():
    eventos = proponer_eventos(_ensayo(_marcha()[0]))

    assert {e.marcador for e in eventos if e.tipo == "contacto"} == {"LHEE", "RHEE"}
    assert {e.marcador for e in eventos if e.tipo == "despegue"} == {"LTOE", "RTOE"}


def test_si_el_talon_no_tiene_datos_usa_el_tobillo():
    posiciones, _ = _marcha()
    posiciones[0] = np.nan  # LHEE existe como etiqueta pero no se registró

    eventos = proponer_eventos(_ensayo(posiciones))

    assert {e.marcador for e in eventos if e.lado == "izquierdo" and e.tipo == "contacto"} == {"LANK"}
    assert len(_tiempos(eventos, "izquierdo", "contacto")) == 4


def test_respeta_la_numeracion_original_de_fotogramas():
    posiciones, _ = _marcha()

    desde_uno = proponer_eventos(_ensayo(posiciones, primer_fotograma=1))
    desde_300 = proponer_eventos(_ensayo(posiciones, primer_fotograma=300))

    assert [e.fotograma + 299 for e in desde_uno] == [e.fotograma for e in desde_300]
    assert desde_300[0].tiempo_s == pytest.approx(desde_uno[0].tiempo_s + 299 / FRECUENCIA)


def test_un_temblor_del_pie_no_se_cuenta_como_paso():
    t = np.arange(600) / FRECUENCIA
    quieto = np.zeros((6, t.size, 3))
    quieto[:, :, 0] += 10 * np.sin(2 * np.pi * 5.0 * t)  # 5 Hz, 10 mm: unos 0,3 m/s de pico
    quieto += np.arange(6)[:, None, None] * 50.0

    assert proponer_eventos(_ensayo(quieto)) == []


def test_un_hueco_largo_no_inventa_eventos():
    posiciones, inicios = _marcha()
    final_balanceo = int((inicios["izquierdo"][1] + BALANCEO_S) * FRECUENCIA)
    posiciones[0, final_balanceo - 15 : final_balanceo + 25] = np.nan  # el talón se pierde al apoyar

    eventos = proponer_eventos(_ensayo(posiciones))

    assert len(_tiempos(eventos, "izquierdo", "contacto")) == 3
    assert len(_tiempos(eventos, "derecho", "contacto")) == 4


def test_no_modifica_los_datos_de_entrada():
    posiciones, _ = _marcha()
    posiciones[2, 100:104] = np.nan
    copia = posiciones.copy()

    proponer_eventos(_ensayo(posiciones))

    np.testing.assert_array_equal(posiciones, copia)


def test_comparar_empareja_por_pie_y_tipo():
    eventos = proponer_eventos(_ensayo(_marcha()[0]))
    primero = next(e for e in eventos if e.lado == "derecho" and e.tipo == "contacto")
    guardados = [
        EventoRegistrado("derecho", "contacto", primero.tiempo_s + 0.02),
        EventoRegistrado("izquierdo", "despegue", 99.0),
    ]

    cercano, lejano = comparar(eventos, guardados, FRECUENCIA)

    assert cercano.propuesta is primero
    assert cercano.diferencia_fotogramas == pytest.approx(-2.0)
    assert cercano.dentro_del_intervalo
    assert lejano.propuesta is None and lejano.diferencia_fotogramas is None


def _escribir_c3d(ruta, con_eventos=True):
    posiciones, inicios = _marcha()
    puntos = np.ones((4, 6, posiciones.shape[1]))
    puntos[:3] = np.transpose(posiciones, (2, 0, 1))
    c3d = ezc3d.c3d()
    c3d["parameters"]["POINT"]["RATE"]["value"] = [FRECUENCIA]
    c3d["parameters"]["POINT"]["UNITS"]["value"] = ["mm"]
    c3d["parameters"]["POINT"]["LABELS"]["value"] = tuple(f"Sujeto:{e}" for e in ETIQUETAS)
    c3d["data"]["points"] = puntos
    if con_eventos:
        c3d.add_event([0, inicios["izquierdo"][0] + BALANCEO_S], context="Left", label="Foot Strike")
        c3d.add_event([0, inicios["derecho"][0]], context="Right", label="Foot Off")
        c3d.add_event([0, 1.0], context="General", label="Otro")
    c3d.write(str(ruta))
    return ruta, inicios


def test_lee_los_eventos_guardados_en_el_c3d(tmp_path):
    ruta, inicios = _escribir_c3d(tmp_path / "ensayo.c3d")

    guardados = leer_eventos(ruta)

    assert [(e.lado, e.tipo) for e in guardados] == [("izquierdo", "contacto"), ("derecho", "despegue")]
    assert guardados[0].tiempo_s == pytest.approx(inicios["izquierdo"][0] + BALANCEO_S, abs=1e-4)
    assert leer_eventos(_escribir_c3d(tmp_path / "sin.c3d", con_eventos=False)[0]) == []


def test_orden_eventos_genera_tabla_y_figura(tmp_path, capsys):
    ruta, _ = _escribir_c3d(tmp_path / "ensayo.c3d")
    contenido = ruta.read_bytes()
    salida = tmp_path / "informe"

    assert main(["eventos", str(ruta), "--salida", str(salida)]) == 0

    assert ruta.read_bytes() == contenido
    filas = (salida / "eventos.csv").read_text(encoding="utf-8-sig").splitlines()
    assert filas[0].startswith("lado;tipo;fotograma;tiempo_s;duda_desde;duda_hasta")
    assert len(filas) == 1 + 16  # cuatro pasos por pie, contacto y despegue
    assert sum(1 for fila in filas[1:] if fila.split(";")[8]) == 2  # los dos eventos guardados
    assert (salida / "eventos.png").is_file()
    texto = capsys.readouterr().out
    assert "El archivo ya traía 2 eventos" in texto
    assert "no se ha modificado" in texto
