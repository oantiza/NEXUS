"""Entrada del programa para Windows que no necesita instalar Python.

Se arrastran encima uno o varios C3D, o una carpeta. Los informes se guardan en
la carpeta «informes», junto al programa, y al terminar se abre el índice en el
navegador. Los C3D no se modifican.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from nexus_mocap.cli import main as ordenes

AYUDA = "Arrastra encima de este programa uno o varios archivos C3D, o una carpeta que los contenga."


def carpeta_del_programa() -> Path:
    """Carpeta donde está el ejecutable; al ejecutar desde el código, la carpeta actual."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    interactivo = "--no-abrir" not in argumentos
    rutas = [a for a in argumentos if a != "--no-abrir"]

    if not rutas:
        print(AYUDA)
        codigo = 1
    else:
        salida = carpeta_del_programa() / "informes"
        try:
            codigo = ordenes(["revisar", *rutas, "--salida", str(salida)])
        except Exception as error:  # que la ventana no se cierre sin explicar qué ha pasado
            print(f"Ha ocurrido un error inesperado: {error}")
            codigo = 1
        if codigo == 0 and interactivo:
            webbrowser.open((salida / "indice.html").resolve().as_uri())

    if interactivo and codigo != 0:
        try:
            input("Pulsa Intro para cerrar esta ventana.")
        except EOFError:
            pass
    return codigo


if __name__ == "__main__":
    sys.exit(main())
