import hashlib

import numpy as np
import pytest

from nexus_mocap.cli import main
from nexus_mocap.lectura import leer_c3d

ezc3d = pytest.importorskip("ezc3d")


def _escribir_c3d(ruta, unidades="mm", primer_fotograma=300):
    """C3D sintético: tres marcadores, una salida de modelo y una trayectoria sin etiquetar."""
    n = 300
    t = np.arange(n) / 100.0
    generador = np.random.default_rng(7)
    base = np.stack([1000 * t, 30 * np.sin(2 * np.pi * t), 800 + 0 * t])
    puntos = np.ones((4, 5, n))
    for i in range(5):
        puntos[:3, i, :] = base + np.array([[60.0 * i], [0.0], [0.0]])
    puntos[:3] += generador.normal(scale=0.2, size=(3, 5, n))
    puntos[1, 1, 120] += 16.0  # salto lateral en RHEE, índice 120
    puntos[:3, 2, 40:55] = np.nan  # hueco en SACR
    if unidades == "m":
        puntos[:3] /= 1000.0

    c3d = ezc3d.c3d()
    c3d["parameters"]["POINT"]["RATE"]["value"] = [100]
    c3d["parameters"]["POINT"]["UNITS"]["value"] = [unidades]
    c3d["parameters"]["POINT"]["LABELS"]["value"] = (
        "Sujeto:LHEE",
        "Sujeto:RHEE",
        "Sujeto:SACR",
        "Sujeto:LKneeAngles",
        "*4",
    )
    c3d.add_parameter("POINT", "ANGLES", ["Sujeto:LKneeAngles"])
    c3d["data"]["points"] = puntos
    c3d["header"]["points"]["first_frame"] = primer_fotograma - 1
    c3d.write(str(ruta))
    return ruta


def test_lee_solo_marcadores_y_conserva_la_numeracion(tmp_path):
    ensayo = leer_c3d(_escribir_c3d(tmp_path / "ensayo.c3d"))

    assert ensayo.etiquetas == ("Sujeto:LHEE", "Sujeto:RHEE", "Sujeto:SACR")
    assert ensayo.frecuencia == 100.0
    assert ensayo.primer_fotograma == 300
    assert ensayo.posiciones.shape == (3, 300, 3)
    assert np.isnan(ensayo.posiciones[2, 40:55]).all()


def test_convierte_metros_a_milimetros(tmp_path):
    ensayo = leer_c3d(_escribir_c3d(tmp_path / "metros.c3d", unidades="m"))

    assert np.nanmedian(ensayo.posiciones[0, :, 2]) == pytest.approx(800.0, abs=1.0)


def test_seleccion_de_marcadores_sin_prefijo(tmp_path):
    ruta = _escribir_c3d(tmp_path / "ensayo.c3d")

    assert leer_c3d(ruta, marcadores=["RHEE"]).etiquetas == ("Sujeto:RHEE",)
    with pytest.raises(ValueError, match="NOEXISTE"):
        leer_c3d(ruta, marcadores=["NOEXISTE"])


def test_orden_saltos_genera_el_informe_sin_tocar_el_original(tmp_path, capsys):
    ruta = _escribir_c3d(tmp_path / "ensayo.c3d")
    huella = hashlib.sha256(ruta.read_bytes()).hexdigest()
    salida = tmp_path / "informe"

    assert main(["saltos", str(ruta), "--salida", str(salida)]) == 0

    assert hashlib.sha256(ruta.read_bytes()).hexdigest() == huella
    filas = (salida / "saltos.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(filas) == 2
    campos = filas[1].split(";")
    assert campos[0] == "Sujeto:RHEE"
    assert campos[1] == "420"  # índice 120 con primer fotograma 300
    assert campos[5] == "aislado"
    assert (salida / "figuras" / "000420_Sujeto_RHEE.png").is_file()
    assert "no se ha modificado" in capsys.readouterr().out


def test_orden_comprobar(tmp_path, capsys):
    ruta = _escribir_c3d(tmp_path / "ensayo.c3d")

    assert main(["comprobar", str(ruta), "--cantidad", "10"]) == 0
    assert "Encontrados: 10 de 10" in capsys.readouterr().out


def test_archivo_inexistente_da_un_error_claro(tmp_path, capsys):
    assert main(["saltos", str(tmp_path / "no_esta.c3d")]) == 1
    assert "No existe el archivo" in capsys.readouterr().out
