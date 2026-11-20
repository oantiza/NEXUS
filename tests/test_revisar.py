import hashlib
import os
import re
from html import unescape
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pytest

from nexus_mocap.cli import _carpeta_dentro, _nombre_de_carpeta, main
from nexus_mocap.huecos import buscar_huecos
from nexus_mocap.lectura import Ensayo

ezc3d = pytest.importorskip("ezc3d")
from test_eventos import ETIQUETAS, FRECUENCIA, _escribir_c3d, _marcha  # noqa: E402


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


def test_los_enlaces_del_indice_abren_el_informe_aunque_el_nombre_lleve_simbolos(tmp_path):
    sesion = tmp_path / "sesion"
    sesion.mkdir()
    nombres = ["Paciente #3 pre.c3d", "marcha 50%25.c3d", "con espacios.c3d"]
    if os.name != "nt":  # Windows no admite «?» en un nombre de archivo
        nombres.append("prueba?.c3d")
    for nombre in nombres:
        _escribir_c3d(sesion / nombre)
    salida = tmp_path / "informes"

    assert main(["revisar", str(sesion), "--salida", str(salida)]) == 0

    enlaces = re.findall(r"href='([^']*)'", (salida / "indice.html").read_text(encoding="utf-8"))
    assert len(enlaces) == len(nombres)
    for enlace in enlaces:
        enlace = unescape(enlace)
        assert not set("#? ") & set(enlace)  # el navegador cortaría ahí el enlace
        assert (salida / unquote(enlace)).is_file()


def test_un_nombre_de_archivo_con_solo_puntos_no_escribe_fuera(tmp_path, monkeypatch, capsys):
    sesion = tmp_path / "trabajo" / "sesion"
    sesion.mkdir(parents=True)
    _escribir_c3d(sesion / "..c3d")  # su nombre sin extensión es «.»
    _escribir_c3d(sesion / "...c3d")  # y este, «..»
    salida = tmp_path / "trabajo" / "informes"

    assert main(["revisar", str(sesion), "--salida", str(salida)]) == 0

    escritos = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert all(e.startswith(("trabajo/sesion/", "trabajo/informes/")) for e in escritos), escritos
    assert (salida / "ensayo" / "informe.html").is_file() and (salida / "ensayo_2" / "informe.html").is_file()

    monkeypatch.chdir(tmp_path)  # «eventos» y «saltos» escriben en informes/ por defecto
    assert main(["eventos", str(sesion / "...c3d"), "--sin-figuras"]) == 0
    assert main(["saltos", str(sesion / "..c3d"), "--sin-figuras"]) == 0
    assert (tmp_path / "informes" / "ensayo" / "eventos.csv").is_file()
    assert (tmp_path / "informes" / "ensayo" / "saltos.csv").is_file()
    assert not (tmp_path / "eventos.csv").exists() and not (tmp_path / "saltos.csv").exists()
    capsys.readouterr()


def test_nombre_de_la_carpeta_del_informe(tmp_path):
    assert _nombre_de_carpeta(Path("..c3d")) == "ensayo"
    assert _nombre_de_carpeta(Path("...c3d")) == "ensayo"
    assert _nombre_de_carpeta(Path(" . .c3d")) == "ensayo"
    assert _nombre_de_carpeta(Path("marcha 01.c3d")) == "marcha 01"
    assert _carpeta_dentro(tmp_path, "marcha 01") == tmp_path / "marcha 01"
    for nombre in ("..", ".", "../otra"):
        with pytest.raises(ValueError):
            _carpeta_dentro(tmp_path / "informes", nombre)


def test_los_marcadores_sin_ningun_dato_se_cuentan_en_el_indice(tmp_path, capsys):
    posiciones, _ = _marcha()
    puntos = np.ones((4, 8, posiciones.shape[1]))
    puntos[:3, :6] = np.transpose(posiciones, (2, 0, 1))
    puntos[:3, 6:] = 0.0  # dos marcadores etiquetados que nunca se registraron
    c3d = ezc3d.c3d()
    c3d["parameters"]["POINT"]["RATE"]["value"] = [FRECUENCIA]
    c3d["parameters"]["POINT"]["UNITS"]["value"] = ["mm"]
    c3d["parameters"]["POINT"]["LABELS"]["value"] = (*ETIQUETAS, "LKNE", "RKNE")
    c3d["data"]["points"] = puntos
    ruta = tmp_path / "sesion" / "sin_rodillas.c3d"
    ruta.parent.mkdir()
    c3d.write(str(ruta))
    salida = tmp_path / "informes"

    assert main(["revisar", str(ruta), "--salida", str(salida)]) == 0

    assert "0 tramos con marcador perdido, 2 marcadores sin ningún dato" in capsys.readouterr().out
    indice = (salida / "indice.html").read_text(encoding="utf-8")
    assert "Marcadores sin ningún dato" in indice
    fila = re.search(r"<tr class='[^']*'><td><a href='sin_rodillas/informe.html'>.*?</tr>", indice).group(0)
    celdas = re.findall(r"<td class='n'>([^<]*)</td>", fila)
    assert celdas[6] == "2"  # fotogramas, contactos, despegues, duda, tramos, hueco, sin datos
