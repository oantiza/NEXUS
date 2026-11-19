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

### Propone los fotogramas de contacto y despegue del pie

Para cada paso da el fotograma candidato del contacto del pie y del despegue de
la punta, con la numeración original (la misma que se ve en Nexus), y un
**intervalo de duda**: los fotogramas entre los que cabe situar el evento. La
idea es que quien revisa abra directamente esos pocos fotogramas y confirme o
mueva la marca.

Se basa en la velocidad del marcador del talón (contacto) y de la punta
(despegue): cada paso deja un pico de velocidad durante el balanceo, y el
evento se sitúa donde la velocidad cae a una fracción de ese pico, o la supera.
Al ser relativo a cada paso, no depende de la dirección de la marcha. Si faltan
el talón o la punta, usa el marcador del tobillo. No necesita plataformas de
fuerza.

Si el C3D ya trae eventos marcados, la herramienta calcula sus propuestas sin
mirarlos y después enseña a cuántos fotogramas queda cada una. Sirve para
probarla con un ensayo ya revisado.

Todavía no propone el inicio y el final de los giros ni el primer movimiento.

### Revisa una sesión entera de una vez

Con una sola orden procesa un ensayo, varios o una carpeta completa, y deja un
informe por ensayo en una única página que se abre con doble clic en cualquier
navegador, sin conexión. Cada informe reúne los eventos propuestos con su
figura, la lista de tramos en que se pierde un marcador y los saltos de un
fotograma. Una página de índice resume todos los ensayos y resalta los que
tienen propuestas con intervalo de duda amplio.

La lista de marcadores perdidos solo los enumera, del más largo al más corto;
el programa no rellena ninguno.

### Busca saltos de un solo fotograma

Un marcador que se desplaza durante un fotograma y vuelve a su sitio en el
siguiente sin que el paciente haga ese movimiento. Para cada uno indica el
marcador, el fotograma, cuántos milímetros se aparta y qué posición cabría
esperar por los fotogramas vecinos.

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

Todas las órdenes escriben en `informes/<nombre del ensayo>/` (o en la carpeta
que se indique con `--salida`). Las tablas usan `;` como separador y coma
decimal, para abrirlas directamente con Excel en español.

### Una sesión entera

```bash
python -m nexus_mocap revisar ruta/a/la/carpeta
```

También admite uno o varios archivos sueltos. Al terminar, abre
`informes/indice.html`. Dentro de `informes/<nombre del ensayo>/` quedan
`informe.html` y las tablas `eventos.csv`, `huecos.csv` y `saltos.csv`. Si un
archivo no se puede leer, se indica en el índice y se sigue con los demás.

En Windows se puede arrastrar un C3D, varios o una carpeta encima de
`Revisar ensayos.bat`: ejecuta esa misma orden y abre el índice. Necesita
Python instalado. **Este lanzador no se ha probado en un Windows real.**

### Eventos de marcha

```bash
python -m nexus_mocap eventos ruta/al/ensayo.c3d
```

- `eventos.csv`: pie, tipo de evento, fotograma propuesto, intervalo de duda y,
  si el archivo ya traía eventos, la diferencia con ellos.
- `eventos.png`: la velocidad de cada pie con las propuestas, sus intervalos de
  duda y los eventos que ya estuvieran guardados.

### Saltos de un fotograma

```bash
python -m nexus_mocap saltos ruta/al/ensayo.c3d
```

- `saltos.csv`: la tabla de avisos.
- `figuras/`: una imagen por aviso, con el tramo original y la posición
  propuesta dibujada al lado.

Opciones útiles: `--marcadores LHEE RHEE` para revisar solo algunos marcadores
y `--umbral-mm 6` para pedir saltos mayores (por defecto, 4 mm).

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
python -m nexus_mocap revisar datos/publicos/sample03
```

```bash
python -m nexus_mocap eventos datos/publicos/sample03/gait-pig-nz.c3d
```

```bash
python -m nexus_mocap saltos datos/publicos/sample03/gait-raw.c3d
```

## Qué se ha medido hasta ahora

Todo se ha medido con grabaciones públicas de [C3D.org](https://www.c3d.org/sampledata.html),
de personas sanas. **Nada está validado con grabaciones de Parkinson.**

### Eventos de marcha

Nueve ensayos de marcha de distintos laboratorios (50 a 120 Hz) que traen 92
contactos y despegues ya marcados. Las propuestas se calcularon sin mirarlos.
Se reproduce con `python scripts/descargar_ejemplo.py --todos` y
`python scripts/evaluar_eventos.py`.

| | Contacto | Despegue | Total |
|---|---|---|---|
| Eventos guardados | 48 | 44 | 92 |
| Con propuesta | 46 | 41 | 87 |
| En el mismo fotograma | 9 | 12 | 21 |
| A 1 fotograma | 20 | 17 | 37 |
| A 2 fotogramas | 9 | 4 | 13 |
| A 3 o más | 8 | 8 | 16 |
| Diferencia mediana | 14 ms | 11 ms | 13 ms |
| Diferencia máxima | 69 ms | 88 ms | 88 ms |
| Evento guardado dentro del intervalo de duda | 37 de 46 | 34 de 41 | 71 de 87 |

Los cinco eventos sin propuesta están en los últimos fotogramas de su ensayo,
donde el paso queda cortado.

Cómo leerlo:

- Dos de cada tres propuestas quedan a un fotograma o menos de la marca
  guardada; una de cada seis, a tres o más. Es una ayuda para llegar antes al
  fotograma, no una marca definitiva.
- Las fracciones de velocidad se eligieron con estos mismos ensayos, así que
  las cifras son optimistas. Eligiéndolas con ocho ensayos y midiendo en el
  noveno, la diferencia mediana fue de 18 ms en el contacto y 11 ms en el
  despegue.
- Los eventos guardados tampoco son una verdad exacta: proceden de plataformas
  de fuerza o de marcado manual, según el archivo.
- Con pasos cortos o arrastrados, apoyo plano o bloqueos, el pie no deja un
  pico de velocidad claro y el método puede fallar. Los movimientos del pie por
  debajo de 0,4 m/s no se cuentan como paso.

### Saltos de un fotograma

Tres grabaciones de marcha de un adulto (`sample03`), insertando saltos de
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

Límites: a frecuencias de captura bajas y con registros ruidosos se escapan
más saltos pequeños, y solo se detectan los de un fotograma. Las pruebas con
temblor y con paradas bruscas son sintéticas.

## Desarrollo

```bash
python -m pytest
```

```bash
ruff check .
```

## Siguientes pasos previstos

0. Probar `Revisar ensayos.bat` en Windows y, si hace falta, preparar una
   versión que no necesite instalar Python.
1. Inicio y final de giro y primer movimiento, con la definición que use el
   estudio.
2. Relleno de huecos con marcadores de referencia, con salida «sin estimación
   fiable» cuando también se pierden las referencias.
3. Medir el tiempo total de revisión, incluido el de trasladar la decisión a
   Nexus: si no acorta el trabajo, la ayuda no aporta nada.
