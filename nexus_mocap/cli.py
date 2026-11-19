"""Línea de órdenes: ``python -m nexus_mocap saltos ensayo.c3d``."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from nexus_mocap.comprobacion import comprobar
from nexus_mocap.informe import dibujar_salto, escribir_csv, nombre_figura
from nexus_mocap.lectura import leer_c3d
from nexus_mocap.saltos import Parametros, detectar_saltos

MAX_FIGURAS = 200


def _argumentos() -> argparse.ArgumentParser:
    comunes = argparse.ArgumentParser(add_help=False)
    comunes.add_argument("archivo", type=Path, help="copia del C3D que se quiere revisar")
    comunes.add_argument("--marcadores", nargs="+", metavar="ETIQUETA", help="revisar solo estos marcadores")
    comunes.add_argument(
        "--umbral-mm",
        type=float,
        default=Parametros.umbral_mm,
        help="desviación mínima para considerar un salto (por defecto, %(default)s mm)",
    )

    principal = argparse.ArgumentParser(
        prog="python -m nexus_mocap",
        description="Ayudas para revisar grabaciones C3D. El archivo original nunca se modifica.",
    )
    ordenes = principal.add_subparsers(dest="orden", required=True)

    saltos = ordenes.add_parser(
        "saltos",
        parents=[comunes],
        help="buscar saltos de un solo fotograma y proponer su posición",
    )
    saltos.add_argument(
        "--salida",
        type=Path,
        help="carpeta del informe (por defecto, informes/<nombre del ensayo>)",
    )
    saltos.add_argument("--sin-figuras", action="store_true", help="no generar las figuras")

    prueba = ordenes.add_parser(
        "comprobar",
        parents=[comunes],
        help="insertar saltos conocidos en memoria y medir cuántos se encuentran",
    )
    prueba.add_argument("--cantidad", type=int, default=50, help="saltos que se insertan")
    prueba.add_argument("--magnitud-mm", type=float, default=15.0, help="tamaño de cada salto")
    prueba.add_argument("--semilla", type=int, default=0, help="para repetir la misma prueba")
    return principal


def _orden_saltos(args: argparse.Namespace) -> int:
    ensayo = leer_c3d(args.archivo, marcadores=args.marcadores)
    saltos = detectar_saltos(ensayo, Parametros(umbral_mm=args.umbral_mm))
    salida = args.salida or Path("informes") / args.archivo.stem

    ultimo = ensayo.fotograma(ensayo.n_fotogramas - 1)
    print(f"Ensayo: {args.archivo.name}")
    print(
        f"  {len(ensayo.etiquetas)} marcadores · fotogramas {ensayo.primer_fotograma}-{ultimo} "
        f"· {ensayo.frecuencia:g} Hz"
    )

    aislados = [s for s in saltos if s.clasificacion == "aislado"]
    acompanados = [s for s in saltos if s.clasificacion == "acompañado"]
    print(f"  Saltos aislados, con posición propuesta: {len(aislados)}")
    print(f"  Para revisar tal como se registraron (otros marcadores acompañan): {len(acompanados)}")
    for s in saltos[:20]:
        print(
            f"    fotograma {s.fotograma:>6} · {s.marcador:<12} · {s.desviacion_mm:6.1f} mm en {s.eje}"
            f" · {s.clasificacion}, confianza {s.confianza}"
        )
    if len(saltos) > 20:
        print(f"    … y {len(saltos) - 20} más en la tabla")

    escribir_csv(saltos, salida / "saltos.csv")
    print(f"  Tabla: {salida / 'saltos.csv'}")
    if saltos and not args.sin_figuras:
        for s in saltos[:MAX_FIGURAS]:
            dibujar_salto(ensayo, s, salida / "figuras" / nombre_figura(s))
        print(f"  Figuras: {salida / 'figuras'} ({min(len(saltos), MAX_FIGURAS)})")
        if len(saltos) > MAX_FIGURAS:
            print(f"  Solo se dibujan los primeros {MAX_FIGURAS} saltos; la tabla los tiene todos.")
    print("El archivo original no se ha modificado.")
    return 0


def _orden_comprobar(args: argparse.Namespace) -> int:
    ensayo = leer_c3d(args.archivo, marcadores=args.marcadores)
    r = comprobar(
        ensayo,
        n=args.cantidad,
        magnitud_mm=args.magnitud_mm,
        semilla=args.semilla,
        parametros=Parametros(umbral_mm=args.umbral_mm),
    )
    print(f"Ensayo: {args.archivo.name} (la prueba se hace en memoria; el archivo no se toca)")
    print(f"  Avisos en el registro tal como está: {r.avisos_previos}")
    print(f"  Saltos de {args.magnitud_mm:g} mm insertados: {r.insertados}")
    if r.insertados:
        print(f"  Encontrados: {r.detectados} de {r.insertados}")
        print(f"  Con posición propuesta: {r.propuestos}")
    if not math.isnan(r.error_mediano_mm):
        print(
            f"  Distancia entre la propuesta y lo que se midió: mediana {r.error_mediano_mm:.2f} mm, "
            f"máxima {r.error_maximo_mm:.2f} mm"
        )
    print(f"  Avisos nuevos que no corresponden a un salto insertado: {r.avisos_nuevos_falsos}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _argumentos().parse_args(argv)
    try:
        return _orden_saltos(args) if args.orden == "saltos" else _orden_comprobar(args)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}")
        return 1
