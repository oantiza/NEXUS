"""Descarga las grabaciones públicas de marcha ``sample03`` de C3D.org.

Uso: python scripts/descargar_ejemplo.py

Los archivos quedan en ``datos/publicos/sample03``, una carpeta que no se sube
al repositorio.
"""

import io
import urllib.request
import zipfile
from pathlib import Path

URL = "https://www.c3d.org/data/Sample03.zip"
DESTINO = Path("datos") / "publicos" / "sample03"


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=60) as respuesta:
        contenido = respuesta.read()
    with zipfile.ZipFile(io.BytesIO(contenido)) as comprimido:
        for miembro in comprimido.infolist():
            nombre = Path(miembro.filename).name
            if nombre.lower().endswith(".c3d"):
                (DESTINO / nombre).write_bytes(comprimido.read(miembro))
                print(DESTINO / nombre)


if __name__ == "__main__":
    main()
