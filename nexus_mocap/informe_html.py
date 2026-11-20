"""Informe de un ensayo en una sola página, que se abre con doble clic en cualquier navegador.

La página no necesita conexión: la figura va incrustada y no carga nada de fuera.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from html import escape
from pathlib import Path

from nexus_mocap.eventos import Emparejado, Evento
from nexus_mocap.huecos import Hueco
from nexus_mocap.lectura import Ensayo
from nexus_mocap.saltos import Salto

MAX_FILAS = 40

_ESTILO = """
:root { color-scheme: light; }
body { font-family: "Segoe UI", Inter, Arial, sans-serif; color: #1f2328; background: #fff;
  max-width: 1040px; margin: 0 auto; padding: 22px 18px 40px; line-height: 1.45; }
h1 { font-size: 1.5rem; margin: 0 0 2px; }
h2 { font-size: 1.12rem; margin: 26px 0 8px; padding-top: 12px; border-top: 1px solid #d5dade; }
p { margin: 0 0 8px; }
.sub, .nota { color: #4a5560; font-size: 0.9rem; }
.resumen { display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 4px; }
.dato { border: 1px solid #d5dade; border-radius: 6px; padding: 8px 12px; min-width: 128px; }
.dato b { display: block; font-size: 1.3rem; }
.dato span { color: #4a5560; font-size: 0.82rem; }
.aviso b { color: #a4521a; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; margin: 6px 0 10px; }
th, td { border: 1px solid #d5dade; padding: 4px 8px; text-align: left; }
th { background: #f3f4f5; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
tr.duda td { background: #fff4e5; }
img { max-width: 100%; border: 1px solid #d5dade; border-radius: 4px; }
.tabla { overflow-x: auto; }
a { color: #0b5cad; }
.error { color: #a4261a; }
"""


def _numero(valor: float, decimales: int = 1) -> str:
    return f"{valor:.{decimales}f}".replace(".", ",")


def _pagina(titulo: str, cuerpo: str) -> str:
    return (
        '<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(titulo)}</title>\n<style>{_ESTILO}</style>\n</head>\n<body>\n{cuerpo}\n"
        '<p class="nota" style="margin-top:26px">Son propuestas para revisar, no marcas definitivas. '
        "El archivo original no se ha modificado. El método se ha comprobado con grabaciones públicas de "
        "personas sanas y de personas con Parkinson, no con las de este estudio.</p>\n</body>\n</html>\n"
    )


def _dato(valor, texto: str, aviso: bool = False) -> str:
    clase = "dato aviso" if aviso else "dato"
    return f'<div class="{clase}"><b>{escape(str(valor))}</b><span>{escape(texto)}</span></div>'


def _tabla_eventos(eventos: list[Evento], emparejados: list[Emparejado]) -> str:
    por_propuesta = {id(p.propuesta): p for p in emparejados if p.propuesta is not None}
    comparar = bool(por_propuesta)
    cabecera = "<th>Pie</th><th>Evento</th><th class='n'>Fotograma propuesto</th><th class='n'>Intervalo de duda</th>"
    if comparar:
        cabecera += "<th class='n'>Marca que ya traía</th><th class='n'>Diferencia (fotogramas)</th>"
    cabecera += "<th>Aviso</th>"
    filas = []
    for e in eventos:
        par = por_propuesta.get(id(e))
        fila = (
            f"<td>{e.lado}</td><td>{e.tipo}</td><td class='n'><b>{e.fotograma}</b></td>"
            f"<td class='n'>{e.fotograma_desde} a {e.fotograma_hasta}</td>"
        )
        if comparar:
            if par:
                signo = "+" if par.diferencia_fotogramas > 0 else "−" if par.diferencia_fotogramas < 0 else ""
                fila += (
                    f"<td class='n'>{_numero(par.fotograma_registrado)}</td>"
                    f"<td class='n'>{signo}{_numero(abs(par.diferencia_fotogramas))}</td>"
                )
            else:
                fila += "<td class='n'>—</td><td class='n'>—</td>"
        dudoso = e.confianza == "baja"
        fila += f"<td>{'intervalo de duda amplio' if dudoso else ''}</td>"
        filas.append(f"<tr class='{'duda' if dudoso else ''}'>{fila}</tr>")
    return f"<div class='tabla'><table><thead><tr>{cabecera}</tr></thead><tbody>{''.join(filas)}</tbody></table></div>"


def informe_ensayo(
    ensayo: Ensayo,
    eventos: list[Evento],
    emparejados: list[Emparejado],
    saltos: list[Salto],
    huecos: list[Hueco],
    sin_datos: list[str],
    figura_png: bytes | None,
    avisos: list[str],
) -> str:
    """Compone la página de un ensayo."""
    ultimo = ensayo.fotograma(ensayo.n_fotogramas - 1)
    dudosos = sum(1 for e in eventos if e.confianza == "baja")
    aislados = [s for s in saltos if s.clasificacion == "aislado"]
    acompanados = [s for s in saltos if s.clasificacion == "acompañado"]
    partes = [
        f"<h1>{escape(ensayo.ruta.name)}</h1>",
        f"<p class='sub'>{len(ensayo.etiquetas)} marcadores · fotogramas {ensayo.primer_fotograma} a {ultimo} · "
        f"{ensayo.frecuencia:g} fotogramas por segundo</p>",
        "<div class='resumen'>",
        _dato(sum(1 for e in eventos if e.tipo == "contacto"), "contactos propuestos"),
        _dato(sum(1 for e in eventos if e.tipo == "despegue"), "despegues propuestos"),
        _dato(dudosos, "con intervalo de duda amplio", aviso=dudosos > 0),
        _dato(len(huecos), "tramos con un marcador perdido", aviso=bool(huecos)),
        _dato(len(aislados), "saltos aislados de un fotograma", aviso=bool(aislados)),
        "</div>",
    ]
    for aviso in avisos:
        partes.append(f"<p class='nota'>{escape(aviso)}</p>")

    partes.append("<h2>Eventos propuestos</h2>")
    if eventos:
        con_marca = [p for p in emparejados if p.propuesta is not None]
        if emparejados:
            cerca = sum(1 for p in con_marca if abs(round(p.diferencia_fotogramas)) <= 1)
            sin_propuesta = len(emparejados) - len(con_marca)
            partes.append(
                f"<p>El archivo ya traía {len(emparejados)} eventos marcados. Las propuestas se calcularon sin mirarlos: "
                f"{cerca} de {len(con_marca)} quedan a un fotograma o menos"
                + (f", y {sin_propuesta} no tienen propuesta." if sin_propuesta else ".")
                + "</p>"
            )
        partes.append(
            "<p class='nota'>Los números de fotograma son los del archivo original, los mismos que en Nexus. "
            "Las filas resaltadas tienen un intervalo de duda amplio: ahí la propuesta vale poco.</p>"
        )
        partes.append(_tabla_eventos(eventos, emparejados))
        if figura_png:
            imagen = base64.b64encode(figura_png).decode("ascii")
            partes.append(
                f"<img alt='Velocidad de los marcadores del pie con los eventos propuestos' src='data:image/png;base64,{imagen}'>"
            )
    else:
        partes.append("<p>No se ha podido proponer ningún evento en este ensayo.</p>")

    partes.append("<h2>Marcadores perdidos</h2>")
    if sin_datos:
        partes.append(f"<p>Sin ningún dato en todo el ensayo: {escape(', '.join(sin_datos))}.</p>")
    if huecos:
        total = sum(h.fotogramas for h in huecos)
        partes.append(
            f"<p>{len(huecos)} tramos, {total} fotogramas en total. Se enumeran del más largo al más corto; "
            "el programa no rellena ninguno.</p>"
        )
        filas = "".join(
            f"<tr><td>{escape(h.marcador)}</td><td class='n'>{h.fotograma_desde}</td><td class='n'>{h.fotograma_hasta}</td>"
            f"<td class='n'>{h.fotogramas}</td><td class='n'>{_numero(h.segundos, 2)}</td><td>{h.posicion} del ensayo</td></tr>"
            for h in huecos[:MAX_FILAS]
        )
        partes.append(
            "<div class='tabla'><table><thead><tr><th>Marcador</th><th class='n'>Desde</th><th class='n'>Hasta</th>"
            f"<th class='n'>Fotogramas</th><th class='n'>Segundos</th><th>Dónde</th></tr></thead><tbody>{filas}</tbody></table></div>"
        )
        if len(huecos) > MAX_FILAS:
            partes.append(
                f"<p class='nota'>Se muestran los {MAX_FILAS} más largos; el resto está en huecos.csv.</p>"
            )
    elif not sin_datos:
        partes.append("<p>Ningún marcador etiquetado se pierde en este ensayo.</p>")

    partes.append("<h2>Saltos de un solo fotograma</h2>")
    if saltos:
        partes.append(
            f"<p>{len(aislados)} aislados, con posición propuesta, y {len(acompanados)} en los que otros marcadores del "
            "segmento se desplazan a la vez: esos pueden ser movimiento real y no se propone corregirlos.</p>"
        )
        filas = "".join(
            f"<tr><td class='n'>{s.fotograma}</td><td>{escape(s.marcador)}</td><td class='n'>{_numero(s.desviacion_mm)}</td>"
            f"<td>{s.eje}</td><td>{s.clasificacion}</td><td>{s.confianza}</td></tr>"
            for s in saltos[:MAX_FILAS]
        )
        partes.append(
            "<div class='tabla'><table><thead><tr><th class='n'>Fotograma</th><th>Marcador</th><th class='n'>Desviación (mm)</th>"
            f"<th>Eje</th><th>Tipo</th><th>Confianza</th></tr></thead><tbody>{filas}</tbody></table></div>"
        )
        if len(saltos) > MAX_FILAS:
            partes.append(
                f"<p class='nota'>Se muestran los primeros {MAX_FILAS}; el resto está en saltos.csv.</p>"
            )
    else:
        partes.append("<p>No se ha encontrado ninguno.</p>")
    return _pagina(ensayo.ruta.name, "\n".join(partes))


@dataclass(frozen=True)
class ResumenEnsayo:
    nombre: str
    enlace: str | None
    fotogramas: int = 0
    contactos: int = 0
    despegues: int = 0
    dudosos: int = 0
    huecos: int = 0
    hueco_mas_largo_s: float = 0.0
    saltos_aislados: int = 0
    error: str | None = None


def indice(resumenes: list[ResumenEnsayo]) -> str:
    """Compone la página de entrada cuando se revisan varios ensayos a la vez."""
    correctos = [r for r in resumenes if r.error is None]
    partes = [
        "<h1>Ensayos revisados</h1>",
        f"<p class='sub'>{len(correctos)} de {len(resumenes)} ensayos procesados. Pulsa en un ensayo para ver su informe.</p>",
    ]
    filas = []
    for r in resumenes:
        if r.error is not None:
            filas.append(
                f"<tr><td>{escape(r.nombre)}</td><td colspan='7' class='error'>{escape(r.error)}</td></tr>"
            )
            continue
        clase = "duda" if r.dudosos else ""
        filas.append(
            f"<tr class='{clase}'><td><a href='{escape(r.enlace or '')}'>{escape(r.nombre)}</a></td>"
            f"<td class='n'>{r.fotogramas}</td><td class='n'>{r.contactos}</td><td class='n'>{r.despegues}</td>"
            f"<td class='n'>{r.dudosos}</td><td class='n'>{r.huecos}</td>"
            f"<td class='n'>{_numero(r.hueco_mas_largo_s, 2) if r.huecos else '—'}</td><td class='n'>{r.saltos_aislados}</td></tr>"
        )
    partes.append(
        "<div class='tabla'><table><thead><tr><th>Ensayo</th><th class='n'>Fotogramas</th><th class='n'>Contactos</th>"
        "<th class='n'>Despegues</th><th class='n'>Con duda amplia</th><th class='n'>Marcadores perdidos (tramos)</th>"
        "<th class='n'>Hueco más largo (s)</th><th class='n'>Saltos aislados</th></tr></thead>"
        f"<tbody>{''.join(filas)}</tbody></table></div>"
    )
    return _pagina("Ensayos revisados", "\n".join(partes))


def escribir(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
