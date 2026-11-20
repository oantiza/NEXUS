"""La sección experimental de giros y primer movimiento en el informe de ``revisar``."""

import hashlib

import numpy as np
import pytest

from nexus_mocap.cli import main

ezc3d = pytest.importorskip("ezc3d")
import test_giros  # noqa: E402
import test_inicio  # noqa: E402
from test_eventos import _escribir_c3d  # noqa: E402


def _guardar(ensayo, ruta):
    puntos = np.ones((4, len(ensayo.etiquetas), ensayo.n_fotogramas))
    puntos[:3] = np.transpose(ensayo.posiciones, (2, 0, 1))
    c3d = ezc3d.c3d()
    c3d["parameters"]["POINT"]["RATE"]["value"] = [ensayo.frecuencia]
    c3d["parameters"]["POINT"]["UNITS"]["value"] = ["mm"]
    c3d["parameters"]["POINT"]["LABELS"]["value"] = ensayo.etiquetas
    c3d["data"]["points"] = puntos
    c3d.write(str(ruta))
    return ruta


def _filas(ruta):
    return ruta.read_text(encoding="utf-8-sig").splitlines()


def test_revisar_anade_giros_y_primer_movimiento(tmp_path):
    sesion = tmp_path / "sesion"
    sesion.mkdir()
    _, rumbo, _ = test_giros._media_vuelta()
    giro = _guardar(test_giros._ensayo(rumbo), sesion / "giro.c3d")
    inicio = _guardar(test_inicio._iniciacion(), sesion / "inicio.c3d")
    solo_pies, _ = _escribir_c3d(sesion / "pies.c3d")
    huellas = {r: hashlib.sha256(r.read_bytes()).hexdigest() for r in (giro, inicio, solo_pies)}
    salida = tmp_path / "informes"

    assert main(["revisar", str(sesion), "--salida", str(salida)]) == 0

    assert all(hashlib.sha256(r.read_bytes()).hexdigest() == h for r, h in huellas.items())
    for nombre in ("giro", "inicio", "pies"):
        informe = (salida / nombre / "informe.html").read_text(encoding="utf-8")
        assert "Giros y primer movimiento (experimental)" in informe
        assert "no están validadas con marcadores en la enfermedad de Parkinson" in informe
        assert "http://" not in informe and "https://" not in informe

    filas = _filas(salida / "giro" / "giros.csv")
    assert filas[0].startswith("sentido;fotograma_inicio;tiempo_inicio_s;inicio_duda_desde;fotograma_fin")
    assert len(filas) == 2 and filas[1].startswith("izquierda;")
    assert "," in filas[1].split(";")[2]  # coma decimal
    informe = (salida / "giro" / "informe.html").read_text(encoding="utf-8")
    assert "<td>izquierda</td>" in informe
    assert "el registro no empieza con al menos 1 s de pie y quieto" in informe

    filas = _filas(salida / "inicio" / "inicio.csv")
    assert (
        filas[0]
        == "senal;marcador;fotograma;tiempo_s;duda_desde;duda_hasta;orden;criterio;reposo_desde;reposo_hasta"
    )
    assert [f.split(";")[0] for f in filas[1:]] == ["tronco", "pelvis", "talón derecho", "talón izquierdo"]
    informe = (salida / "inicio" / "informe.html").read_text(encoding="utf-8")
    assert "Se mueve antes: <b>tronco</b>" in informe and "el derecho" in informe

    # Sin pelvis: nada propuesto, una línea con el motivo y tablas solo con la cabecera.
    informe = (salida / "pies" / "informe.html").read_text(encoding="utf-8")
    assert "No se proponen giros: faltan los marcadores de la pelvis" in informe
    assert "No se propone el primer movimiento: faltan los marcadores de la pelvis" in informe
    assert len(_filas(salida / "pies" / "giros.csv")) == 1
    assert len(_filas(salida / "pies" / "inicio.csv")) == 1
