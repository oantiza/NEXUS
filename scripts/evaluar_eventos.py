"""Compara las propuestas de eventos con los eventos ya marcados en grabaciones públicas.

Uso:
    python scripts/descargar_ejemplo.py --todos
    python scripts/evaluar_eventos.py

Las propuestas se calculan sin mirar los eventos guardados; después se mide a
qué distancia quedan de ellos. Son grabaciones de personas sanas.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexus_mocap.eventos import comparar, proponer_eventos  # noqa: E402
from nexus_mocap.lectura import leer_c3d, leer_eventos  # noqa: E402

BASE = Path("datos") / "publicos"
ENSAYOS = (
    "sample00/Motion Analysis Corporation/Walk1.c3d",
    "sample00/Vicon Motion Systems/pyCGM2 lower limb CGM24 Walking01.c3d",
    "sample03/gait-pig-nz.c3d",
    "sample03/gait-pig.c3d",
    "sample04/sub_labels.c3d",
    "sample09/PlugInC3D.c3d",
    "sample11/2198928.c3d",
    "sample23/Vicon_analysis.c3d",
    "sample32/vicon_zerowire.c3d",
)


def main() -> int:
    filas = []
    for relativa in ENSAYOS:
        ruta = BASE / relativa
        if not ruta.is_file():
            print(f"Falta {ruta}. Ejecuta antes: python scripts/descargar_ejemplo.py --todos")
            return 1
        ensayo = leer_c3d(ruta)
        emparejados = comparar(proponer_eventos(ensayo), leer_eventos(ruta), ensayo.frecuencia)
        for par in emparejados:
            filas.append((ruta.name, ensayo.frecuencia, par))
        con = [p for p in emparejados if p.propuesta]
        print(
            f"{ruta.name[:40]:<40} {ensayo.frecuencia:>4g} Hz · "
            f"guardados {len(emparejados):>2} · con propuesta {len(con):>2}"
        )

    print()
    for tipo in ("contacto", "despegue", None):
        del_tipo = [f for f in filas if tipo is None or f[2].registrado.tipo == tipo]
        con = [f for f in del_tipo if f[2].propuesta]
        ms = np.array([f[2].diferencia_fotogramas / f[1] * 1000 for f in con])
        fotogramas = np.array([abs(round(f[2].diferencia_fotogramas)) for f in con])
        dentro = sum(1 for f in con if f[2].dentro_del_intervalo)
        print(
            f"{(tipo or 'total').capitalize()}: {len(del_tipo)} eventos guardados, {len(con)} con propuesta"
        )
        print(
            f"  diferencia: mediana {np.median(np.abs(ms)):.0f} ms, "
            f"percentil 90 {np.percentile(np.abs(ms), 90):.0f} ms, "
            f"máxima {np.abs(ms).max():.0f} ms, sesgo {ms.mean():+.0f} ms"
        )
        print(
            f"  mismo fotograma {np.sum(fotogramas == 0)} · a 1: {np.sum(fotogramas == 1)} · "
            f"a 2: {np.sum(fotogramas == 2)} · a 3 o más: {np.sum(fotogramas >= 3)}"
        )
        print(f"  evento guardado dentro del intervalo de duda: {dentro} de {len(con)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
