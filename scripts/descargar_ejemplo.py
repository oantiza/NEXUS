"""Descarga grabaciones públicas de C3D.org para probar sin datos de pacientes.

Uso:
    python scripts/descargar_ejemplo.py            # solo sample03 (marcha de un adulto)
    python scripts/descargar_ejemplo.py --todos    # las que usa scripts/evaluar_eventos.py

Los archivos quedan en ``datos/publicos/``, una carpeta que no se sube al repositorio.
"""

import argparse
import io
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

URL = "https://www.c3d.org/data/Sample{:02d}.zip"
DESTINO = Path("datos") / "publicos"
CON_EVENTOS = (0, 3, 4, 9, 11, 23, 32)


def descargar(numero: int) -> None:
    carpeta = DESTINO / f"sample{numero:02d}"
    with urllib.request.urlopen(URL.format(numero), timeout=120) as respuesta:
        contenido = respuesta.read()
    with zipfile.ZipFile(io.BytesIO(contenido)) as comprimido:
        for miembro in comprimido.infolist():
            ruta = PurePosixPath(miembro.filename.replace("\\", "/"))
            if miembro.is_dir() or ruta.suffix.lower() != ".c3d":
                continue
            if ruta.is_absolute() or ".." in ruta.parts:
                continue
            destino = carpeta.joinpath(*ruta.parts)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(comprimido.read(miembro))
            print(destino)


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument(
        "--todos", action="store_true", help="descargar todas las grabaciones con eventos"
    )
    for numero in CON_EVENTOS if argumentos.parse_args().todos else (3,):
        descargar(numero)


if __name__ == "__main__":
    main()
