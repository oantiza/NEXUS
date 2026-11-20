"""Línea de órdenes: ``python -m nexus_mocap <orden> ensayo.c3d``."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from nexus_mocap.comprobacion import comprobar
from nexus_mocap.eventos import comparar, es_tobillo, marcadores_del_pie, proponer_eventos
from nexus_mocap.huecos import buscar_huecos
from nexus_mocap.informe import (
    dibujar_eventos,
    dibujar_salto,
    escribir_csv,
    escribir_csv_eventos,
    escribir_csv_huecos,
    nombre_figura,
)
from nexus_mocap.informe_html import ResumenEnsayo, escribir, indice, informe_ensayo
from nexus_mocap.lectura import Ensayo, leer_c3d, leer_eventos
from nexus_mocap.saltos import Parametros, detectar_saltos

MAX_FIGURAS = 200


def _argumentos() -> argparse.ArgumentParser:
    archivo = argparse.ArgumentParser(add_help=False)
    archivo.add_argument("archivo", type=Path, help="copia del C3D que se quiere revisar")

    de_saltos = argparse.ArgumentParser(add_help=False)
    de_saltos.add_argument(
        "--marcadores", nargs="+", metavar="ETIQUETA", help="revisar solo estos marcadores"
    )
    de_saltos.add_argument(
        "--umbral-mm",
        type=float,
        default=Parametros.umbral_mm,
        help="desviación mínima para considerar un salto (por defecto, %(default)s mm)",
    )

    salida = argparse.ArgumentParser(add_help=False)
    salida.add_argument(
        "--salida", type=Path, help="carpeta del informe (por defecto, informes/<nombre del ensayo>)"
    )
    salida.add_argument("--sin-figuras", action="store_true", help="no generar las figuras")

    principal = argparse.ArgumentParser(
        prog="python -m nexus_mocap",
        description="Ayudas para revisar grabaciones C3D. El archivo original nunca se modifica.",
    )
    ordenes = principal.add_subparsers(dest="orden", required=True)

    revisar = ordenes.add_parser(
        "revisar",
        help="revisar de una vez uno o varios ensayos, o una carpeta entera, y dejar un informe por ensayo",
    )
    revisar.add_argument("rutas", nargs="+", type=Path, help="archivos C3D o carpetas que los contengan")
    revisar.add_argument("--salida", type=Path, default=Path("informes"), help="carpeta de los informes")
    ordenes.add_parser(
        "eventos",
        parents=[archivo, salida],
        help="proponer los fotogramas de contacto del pie y despegue de la punta",
    )
    ordenes.add_parser(
        "saltos",
        parents=[archivo, de_saltos, salida],
        help="buscar saltos de un solo fotograma y proponer su posición",
    )
    prueba = ordenes.add_parser(
        "comprobar",
        parents=[archivo, de_saltos],
        help="insertar saltos conocidos en memoria y medir cuántos se encuentran",
    )
    prueba.add_argument("--cantidad", type=int, default=50, help="saltos que se insertan")
    prueba.add_argument("--magnitud-mm", type=float, default=15.0, help="tamaño de cada salto")
    prueba.add_argument("--semilla", type=int, default=0, help="para repetir la misma prueba")
    return principal


def _cabecera(args: argparse.Namespace, ensayo: Ensayo) -> None:
    ultimo = ensayo.fotograma(ensayo.n_fotogramas - 1)
    print(f"Ensayo: {args.archivo.name}")
    print(
        f"  {len(ensayo.etiquetas)} marcadores · fotogramas {ensayo.primer_fotograma}-{ultimo} "
        f"· {ensayo.frecuencia:g} Hz"
    )


def _orden_saltos(args: argparse.Namespace) -> int:
    ensayo = leer_c3d(args.archivo, marcadores=args.marcadores)
    saltos = detectar_saltos(ensayo, Parametros(umbral_mm=args.umbral_mm))
    salida = args.salida or Path("informes") / args.archivo.stem
    _cabecera(args, ensayo)

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


def _orden_eventos(args: argparse.Namespace) -> int:
    ensayo = leer_c3d(args.archivo)
    eventos = proponer_eventos(ensayo)
    registrados = leer_eventos(args.archivo)
    emparejados = comparar(eventos, registrados, ensayo.frecuencia)
    salida = args.salida or Path("informes") / args.archivo.stem
    _cabecera(args, ensayo)

    for lado in ("izquierdo", "derecho"):
        usados = marcadores_del_pie(ensayo, lado)
        for tipo, encontrado in usados.items():
            if encontrado is None:
                print(f"  Pie {lado}: no hay marcador con datos para proponer el {tipo}.")
    for tipo in ("contacto", "despegue"):
        del_tipo = [e for e in eventos if e.tipo == tipo]
        dudosos = sum(1 for e in del_tipo if e.confianza == "baja")
        nota = f" ({dudosos} con intervalo de duda amplio)" if dudosos else ""
        print(f"  Propuestas de {tipo}: {len(del_tipo)}{nota}")
    for e in eventos[:30]:
        print(
            f"    fotograma {e.fotograma:>6} · {e.lado:<9} · {e.tipo:<8} · "
            f"duda {e.fotograma_desde}-{e.fotograma_hasta} · confianza {e.confianza}"
        )
    if len(eventos) > 30:
        print(f"    … y {len(eventos) - 30} más en la tabla")

    if registrados:
        diferencias = [abs(round(p.diferencia_fotogramas)) for p in emparejados if p.propuesta]
        sin_propuesta = sum(1 for p in emparejados if p.propuesta is None)
        dentro = sum(1 for p in emparejados if p.dentro_del_intervalo)
        print(
            f"  El archivo ya traía {len(registrados)} eventos. Comparadas con ellos, las propuestas quedan:"
        )
        print(f"    en el mismo fotograma: {sum(1 for d in diferencias if d == 0)}")
        print(f"    a 1 fotograma: {sum(1 for d in diferencias if d == 1)}")
        print(f"    a 2 fotogramas: {sum(1 for d in diferencias if d == 2)}")
        print(f"    a 3 o más: {sum(1 for d in diferencias if d >= 3)}")
        print(f"    sin propuesta: {sin_propuesta}")
        print(f"    evento guardado dentro del intervalo de duda: {dentro} de {len(diferencias)}")

    escribir_csv_eventos(eventos, emparejados, salida / "eventos.csv")
    print(f"  Tabla: {salida / 'eventos.csv'}")
    if not args.sin_figuras:
        dibujar_eventos(ensayo, eventos, registrados, salida / "eventos.png")
        print(f"  Figura: {salida / 'eventos.png'}")
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


def _archivos_c3d(rutas: list[Path]) -> list[Path]:
    """Expande carpetas y devuelve los C3D sin repetir, en orden."""
    encontrados: list[Path] = []
    for ruta in rutas:
        if ruta.is_dir():
            encontrados.extend(
                sorted(p for p in ruta.rglob("*") if p.is_file() and p.suffix.lower() == ".c3d")
            )
        else:
            encontrados.append(ruta)
    return list(dict.fromkeys(encontrados))


def _giros_e_inicio(ensayo: Ensayo, carpeta: Path) -> str:
    """Propuestas experimentales de giros y primer movimiento: escribe sus tablas y devuelve su sección."""
    from html import escape

    from nexus_mocap.giros import proponer_giros
    from nexus_mocap.informe import escribir_csv_giros, escribir_csv_inicio
    from nexus_mocap.informe_html import seccion_giros_inicio
    from nexus_mocap.inicio import proponer_inicio

    try:
        giros, inicio = proponer_giros(ensayo), proponer_inicio(ensayo)
    except Exception as error:  # una función experimental no debe impedir el resto del informe
        return (
            "<h2>Giros y primer movimiento (experimental)</h2>"
            f"<p>No se han podido calcular en este ensayo ({escape(str(error))}).</p>"
        )
    escribir_csv_giros(giros, carpeta / "giros.csv")
    escribir_csv_inicio(inicio, carpeta / "inicio.csv")
    return seccion_giros_inicio(giros, inicio)


def _revisar_ensayo(archivo: Path, carpeta: Path) -> ResumenEnsayo:
    """Calcula todo para un ensayo y escribe su informe. No toca el archivo original."""
    ensayo = leer_c3d(archivo)
    eventos = proponer_eventos(ensayo)
    emparejados = comparar(eventos, leer_eventos(archivo), ensayo.frecuencia)
    saltos = detectar_saltos(ensayo)
    huecos, sin_datos = buscar_huecos(ensayo)

    avisos = list(ensayo.avisos)
    faltan = False
    for lado in ("izquierdo", "derecho"):
        for tipo, encontrado in marcadores_del_pie(ensayo, lado).items():
            if encontrado is None:
                faltan = True
                avisos.append(f"Pie {lado}: no hay marcador con datos para proponer el {tipo}.")
            elif es_tobillo(encontrado[1]):
                avisos.append(f"Pie {lado}: para el {tipo} se usa el marcador del tobillo, a falta de otro.")

    if faltan:
        nombres = ", ".join(e.split(":")[-1] for e in ensayo.etiquetas[:40])
        avisos.append(
            "Se buscan marcadores de talón (HEE, HEEL, CAL), punta (TOE) y tobillo (ANK, ANKLE) "
            f"con L o R delante. Los de este archivo son: {nombres}"
            + ("…" if len(ensayo.etiquetas) > 40 else "")
            + "."
        )

    escribir_csv_eventos(eventos, emparejados, carpeta / "eventos.csv")
    escribir_csv(saltos, carpeta / "saltos.csv")
    escribir_csv_huecos(huecos, carpeta / "huecos.csv")
    figura = None
    if eventos:
        dibujar_eventos(ensayo, eventos, [p.registrado for p in emparejados], carpeta / "eventos.png")
        figura = (carpeta / "eventos.png").read_bytes()
    experimental = _giros_e_inicio(ensayo, carpeta)
    pagina = informe_ensayo(
        ensayo, eventos, emparejados, saltos, huecos, sin_datos, figura, avisos, secciones=(experimental,)
    )
    escribir(carpeta / "informe.html", pagina)
    return ResumenEnsayo(
        nombre=archivo.name,
        enlace=f"{carpeta.name}/informe.html",
        fotogramas=ensayo.n_fotogramas,
        contactos=sum(1 for e in eventos if e.tipo == "contacto"),
        despegues=sum(1 for e in eventos if e.tipo == "despegue"),
        dudosos=sum(1 for e in eventos if e.confianza == "baja"),
        huecos=len(huecos),
        hueco_mas_largo_s=huecos[0].segundos if huecos else 0.0,
        saltos_aislados=sum(1 for s in saltos if s.clasificacion == "aislado"),
    )


def _orden_revisar(args: argparse.Namespace) -> int:
    archivos = _archivos_c3d(args.rutas)
    if not archivos:
        print("No se ha encontrado ningún archivo C3D en lo indicado.")
        return 1
    resumenes = []
    usados: set[str] = set()
    for archivo in archivos:
        nombre = archivo.stem
        numero = 2
        while nombre.lower() in usados:
            nombre = f"{archivo.stem}_{numero}"
            numero += 1
        usados.add(nombre.lower())
        try:
            resumen = _revisar_ensayo(archivo, args.salida / nombre)
            print(
                f"{archivo.name}: {resumen.contactos} contactos y {resumen.despegues} despegues propuestos, "
                f"{resumen.huecos} tramos con marcador perdido"
            )
        except Exception as error:  # un ensayo ilegible no debe detener al resto
            resumen = ResumenEnsayo(nombre=archivo.name, enlace=None, error=f"No se ha podido leer: {error}")
            print(f"{archivo.name}: no se ha podido procesar ({error})")
        resumenes.append(resumen)
    escribir(args.salida / "indice.html", indice(resumenes))
    correctos = sum(1 for r in resumenes if r.error is None)
    print(f"{correctos} de {len(resumenes)} ensayos procesados. Abre: {args.salida / 'indice.html'}")
    print("Los archivos originales no se han modificado.")
    return 0 if correctos else 1


ORDENES = {
    "revisar": _orden_revisar,
    "eventos": _orden_eventos,
    "saltos": _orden_saltos,
    "comprobar": _orden_comprobar,
}


def main(argv: list[str] | None = None) -> int:
    # En algunas consolas de Windows un carácter poco habitual haría fallar la escritura.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = _argumentos().parse_args(argv)
    try:
        return ORDENES[args.orden](args)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}")
        return 1
