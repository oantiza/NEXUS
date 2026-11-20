import pytest

from nexus_mocap import lanzador

pytest.importorskip("ezc3d")
from test_eventos import _escribir_c3d  # noqa: E402


def test_lanzador_deja_los_informes_junto_al_programa(tmp_path, monkeypatch, capsys):
    (tmp_path / "datos").mkdir()
    ensayo, _ = _escribir_c3d(tmp_path / "datos" / "marcha.c3d")
    programa = tmp_path / "programa"
    programa.mkdir()
    monkeypatch.setattr(lanzador, "carpeta_del_programa", lambda: programa)
    abiertos = []
    monkeypatch.setattr(lanzador.webbrowser, "open", abiertos.append)

    assert lanzador.main([str(ensayo)]) == 0

    assert (programa / "informes" / "marcha" / "informe.html").is_file()
    assert abiertos == [(programa / "informes" / "indice.html").resolve().as_uri()]
    assert "no se han modificado" in capsys.readouterr().out


def test_lanzador_sin_abrir_no_lanza_el_navegador_ni_espera(tmp_path, monkeypatch):
    ensayo, _ = _escribir_c3d(tmp_path / "marcha.c3d")
    monkeypatch.setattr(lanzador, "carpeta_del_programa", lambda: tmp_path)
    monkeypatch.setattr(lanzador.webbrowser, "open", lambda _: pytest.fail("no debía abrir el navegador"))
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("no debía esperar una tecla"))

    assert lanzador.main(["--no-abrir", str(ensayo)]) == 0
    assert lanzador.main(["--no-abrir"]) == 1


def test_lanzador_sin_archivos_explica_que_hacer(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "")

    assert lanzador.main([]) == 1
    assert "Arrastra encima" in capsys.readouterr().out
