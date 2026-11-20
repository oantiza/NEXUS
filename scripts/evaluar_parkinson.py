"""Compara las propuestas con los eventos marcados en un conjunto público de marcha en Parkinson.

Datos: Shida y colaboradores, «A dataset of overground walking full-body kinematics and kinetics
in individuals with Parkinson's disease», figshare, doi:10.6084/m9.figshare.14896881 (CC BY 4.0).
26 personas, con y sin medicación, 150 fotogramas por segundo. Hay que descargar `C3Dfiles.zip`
(1,35 GB) desde esa página y descomprimirlo.

Uso:
    python scripts/evaluar_parkinson.py ruta/a/C3Dfiles

Las propuestas se calculan sin mirar los eventos guardados; después se mide a qué distancia
quedan de ellos. Los ensayos estáticos se saltan.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexus_mocap.eventos import comparar, marcadores_del_pie, proponer_eventos  # noqa: E402
from nexus_mocap.lectura import leer_c3d, leer_eventos  # noqa: E402


def _linea(nombre: str, pares: list) -> str:
    con = [p for p in pares if p[0] is not None]
    ms = np.abs(np.array([p[0] for p in con]))
    sesgo = np.mean([p[0] for p in con])
    dentro = 100 * np.mean([p[1] for p in con])
    return (
        f"{nombre:<24} guardados {len(pares):>5} · "
        f"con propuesta {len(con):>5} ({100 * len(con) / len(pares):.1f} %) · "
        f"mediana {np.median(ms):4.1f} ms · p90 {np.percentile(ms, 90):4.1f} ms · sesgo {sesgo:+5.1f} ms · "
        f"a 20 ms o menos {100 * np.mean(ms <= 20):4.1f} % · dentro del intervalo {dentro:4.1f} %"
    )


def main() -> int:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        print(__doc__)
        return 1
    archivos = sorted(
        p
        for p in Path(sys.argv[1]).rglob("*")
        if p.suffix.lower() == ".c3d" and "static" not in p.name.lower()
    )
    grupos: dict[str, list] = defaultdict(list)
    marcadores: dict[str, set] = defaultdict(set)
    propuestas = sin_marca = 0
    sujetos = set()
    for archivo in archivos:
        encontrado = re.search(r"(SUB\d+)_(on|off)_", archivo.name)
        ensayo = leer_c3d(archivo)
        eventos = proponer_eventos(ensayo)
        emparejados = comparar(eventos, leer_eventos(archivo), ensayo.frecuencia)
        con_marca = {id(p.propuesta) for p in emparejados if p.propuesta is not None}
        propuestas += len(eventos)
        sin_marca += sum(1 for e in eventos if id(e) not in con_marca)
        for lado in ("izquierdo", "derecho"):
            for tipo, usado in marcadores_del_pie(ensayo, lado).items():
                marcadores[tipo].add(usado[1] if usado else "ninguno")
        for par in emparejados:
            dato = (
                None if par.propuesta is None else par.diferencia_fotogramas / ensayo.frecuencia * 1000,
                bool(par.dentro_del_intervalo),
            )
            grupos[par.registrado.tipo].append(dato)
            if encontrado:
                sujetos.add(encontrado.group(1))
                grupos[f"{par.registrado.tipo}, {encontrado.group(2)}"].append(dato)

    print(f"{len(archivos)} ensayos de marcha de {len(sujetos)} personas")
    for tipo in ("contacto", "despegue"):
        print(f"Marcadores usados para el {tipo}: {', '.join(sorted(marcadores[tipo]))}")
    print()
    for nombre in ("contacto", "contacto, on", "contacto, off", "despegue", "despegue, on", "despegue, off"):
        if grupos[nombre]:
            print(_linea(nombre, grupos[nombre]))
    print(f"\nPropuestas en total: {propuestas} · sin un evento guardado a menos de 0,2 s: {sin_marca}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
