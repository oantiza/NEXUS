# NEXUS

Ayuda para revisar grabaciones de captura de movimiento (C3D) en un estudio
neurofisiológico sobre Parkinson, antes y después de la estimulación cerebral
profunda.

No sustituye a Vicon Nexus ni a la revisión de la neurofisióloga. Es una
herramienta aparte que mira una **copia** del C3D y deja preparadas propuestas
para que quien revisa decida.

## Principios

- **Independiente.** No se instala en el equipo de captura, no usa el SDK de
  Vicon y no necesita que Nexus esté abierto. Solo lee un archivo C3D.
- **No invasiva.** El archivo original nunca se modifica. Los resultados se
  escriben en una carpeta distinta (`informes/`).
- **El movimiento real no es un error.** Temblor, discinesias y bloqueos son lo
  que el estudio quiere medir. Si hay duda, se señala para revisar y no se
  propone corrección.
- **Datos en local.** Nada se envía a servicios externos. Las grabaciones de
  pacientes no se suben a este repositorio (`.gitignore` excluye los C3D).

## Qué hace hoy

Busca **saltos de un solo fotograma**: un marcador que se desplaza durante un
fotograma y vuelve a su sitio en el siguiente sin que el paciente haga ese
movimiento. Para cada uno indica el marcador, el fotograma (con la numeración
original, la misma que se ve en Nexus), cuántos milímetros se aparta y qué
posición cabría esperar por los fotogramas vecinos.

Cada aviso se clasifica así:

| Clasificación | Qué significa | Propuesta |
|---|---|---|
| aislado, confianza alta | Solo se mueve ese marcador; los marcadores solidarios con él no acompañan | Sí |
| aislado, confianza media | Igual, pero falta contexto: está junto a un hueco o no hay marcadores solidarios visibles | Sí |
| acompañado, confianza baja | Otros marcadores del segmento se desplazan en el mismo fotograma: puede ser movimiento real (por ejemplo, el impacto del talón) | No: revisar tal como se registró |

## Instalación

Hace falta Python 3.10 o posterior, en cualquier ordenador (no tiene que ser el
de captura).

```bash
pip install -r requirements.txt
```

## Uso

Revisar un ensayo:

```bash
python -m nexus_mocap saltos ruta/al/ensayo.c3d
```

Se crea `informes/<nombre del ensayo>/` con:

- `saltos.csv`: la tabla de avisos. Usa `;` como separador y coma decimal, para
  abrirla directamente con Excel en español.
- `figuras/`: una imagen por aviso, con el tramo original y la posición
  propuesta dibujada al lado.

Opciones útiles: `--marcadores LHEE RHEE` para revisar solo algunos marcadores,
`--umbral-mm 6` para pedir saltos mayores (por defecto, 4 mm), `--salida` para
elegir la carpeta del informe.

### Comprobarlo con un valor conocido

Para saber si la estimación sirve con un ensayo concreto, esta orden desplaza
en memoria puntos bien registrados y mide si se encuentran y a cuántos
milímetros queda la propuesta de lo que la cámara sí midió. El archivo no se
toca.

```bash
python -m nexus_mocap comprobar ruta/al/ensayo.c3d --magnitud-mm 8
```

### Probar con una grabación pública

```bash
python scripts/descargar_ejemplo.py
```

```bash
python -m nexus_mocap saltos datos/publicos/sample03/gait-raw.c3d
```

## Qué se ha medido hasta ahora

Con las tres grabaciones públicas de marcha de un adulto sano
([C3D.org, sample03](https://www.c3d.org/sampledata.html)), insertando saltos de
dirección aleatoria en tres repeticiones:

| Grabación | 15 mm | 8 mm | 5 mm | Avisos falsos |
|---|---|---|---|---|
| `gait-pig-nz` (120 Hz) | 119 de 119 | 119 de 119 | 117 de 119 | 0 |
| `gait-pig` (50 Hz) | 50 de 55 | 45 de 55 | 39 de 55 | 0 |
| `gait-raw` (50 Hz, sin procesar) | 49 de 53 | 38 de 53 | 20 de 53 | 1 |

La propuesta quedó, de mediana, a menos de 0,6 mm de la posición realmente
medida en todos los casos; la mayor diferencia fue de 3,2 mm.

En `gait-raw` tal como está, la herramienta da 14 avisos. Once coinciden con
los apoyos del pie, donde tobillo, antepié y tibia se desplazan a la vez: los
clasifica como *acompañados* y no propone corregirlos. Los otros tres son
saltos aislados de 5 a 6 mm que quedarían para revisar.

Límites conocidos:

- Son datos de una persona sana. **No está validado con grabaciones de
  Parkinson**; las pruebas con temblor y con paradas bruscas son sintéticas.
- A frecuencias de captura bajas (50 Hz) y con registros ruidosos se escapan
  más saltos pequeños.
- Solo detecta saltos de un fotograma. Los de dos o más fotogramas seguidos, el
  relleno de huecos y los eventos de marcha no están hechos todavía.

## Desarrollo

```bash
python -m pytest
```

```bash
ruff check .
```

## Siguientes pasos previstos

1. Relleno de huecos con marcadores de referencia, con salida «sin estimación
   fiable» cuando también se pierden las referencias.
2. Propuesta de eventos: contacto de talón, despegue de la punta, inicio y
   final de giro, primer movimiento.
3. Medir el tiempo total de revisión, incluido el de trasladar la decisión a
   Nexus: si no acorta el trabajo, la ayuda no aporta nada.
