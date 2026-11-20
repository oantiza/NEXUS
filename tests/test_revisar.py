import hashlib
from pathlib import Path

import numpy as np
import pytest

from nexus_mocap.cli import main
from nexus_mocap.huecos import buscar_huecos
from nexus_mocap.lectura import Ensayo

pytest.importorskip("ezc3d")
from test_eventos import _escribir_c3d  # noqa: E402


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_buscar_huecos_distingue_posicion_y_marcadores_sin_datos():
    posiciones = np.ones((3, 100, 3))
    posiciones[0, :5] = np.nan  # al inicio
    posiciones[0, 40:60] = np.nan  # en medio
    posiciones[0, 97:] = np.nan  # al final
    posiciones[2] = np.nan  # nunca se registró
    ensayo = Ensayo(Path("s.c3d"), ("A", "B", "C"), posiciones, 100.0, 201)

    huecos, sin_datos = buscar_huecos(ensayo)

    assert sin_datos == ["C"]
    assert [(h.fotograma_desde, h.fotograma_hasta, h.fotogramas, h.posicion) for h in huecos] == [
        (241, 260, 20, "medio"),
        (201, 205, 5, "inicio"),
        (298, 300, 3, "final"),
    ]
    assert huecos[0].segundos == pytest.approx(0.2)


def test_revisar_una_carpeta_deja_un_informe_por_ensayo_y_un_indice(tmp_path, capsys):
    sesion = tmp_path / "sesion"
    (sesion / "otra").mkdir(parents=True)
    uno, _ = _escribir_c3d(sesion / "marcha_01.c3d")
    dos, _ = _escribir_c3d(sesion / "otra" / "marcha_01.c3d", con_eventos=False)
    dos = dos.rename(dos.with_suffix(".C3D"))  # la extensión en mayúsculas también vale
    roto = sesion / "roto.c3d"
    roto.write_bytes(b"esto no es un c3d")
    huellas = {ruta: _huella(ruta) for ruta in (uno, dos, roto)}
    salida = tmp_path / "informes"

    assert main(["revisar", str(sesion), "--salida", str(salida)]) == 0

    assert all(_huella(ruta) == huella for ruta, huella in huellas.items())
    indice = (salida / "indice.html").read_text(encoding="utf-8")
    assert "2 de 3 ensayos procesados" in indice
    assert "marcha_01/informe.html" in indice and "marcha_01_2/informe.html" in indice
    assert "No se ha podido leer" in indice
    for carpeta in ("marcha_01", "marcha_01_2"):
        informe = (salida / carpeta / "informe.html").read_text(encoding="utf-8")
        assert "Eventos propuestos" in informe and "data:image/png;base64," in informe
        assert "http://" not in informe and "https://" not in informe  # se abre sin conexión
        for nombre in ("eventos.csv", "saltos.csv", "huecos.csv", "eventos.png"):
            assert (salida / carpeta / nombre).is_file()
    assert "El archivo ya traía 2 eventos marcados" in (salida / "marcha_01" / "informe.html").read_text(
        encoding="utf-8"
    )
    assert "no se han modificado" in capsys.readouterr().out


def test_revisar_sin_archivos_c3d_avisa(tmp_path, capsys):
    (tmp_path / "vacia").mkdir()

    assert main(["revisar", str(tmp_path / "vacia")]) == 1
    assert "ningún archivo C3D" in capsys.readouterr().out
