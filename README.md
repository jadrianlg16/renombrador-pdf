# Renombrador PDF local

Aplicación local para revisar una carpeta de PDF, seleccionar visualmente una o varias regiones, ejecutar OCR únicamente sobre esas regiones y renombrar cada archivo sólo después de aprobación humana.

## Funciones incluidas

- Subida de una carpeta completa desde el navegador, con barra de progreso y arrastrar y soltar.
- Descarga de un ZIP con los archivos ya renombrados, por lote o de todo.
- Al aprobar un nombre salta solo al siguiente documento pendiente.
- Recorrido del lote con las flechas del teclado.
- Visor de PDF dentro del navegador, renderizado por el servidor local.
- Selección rectangular de una o varias zonas.
- Una caja puede contener nombres partidos en varias líneas.
- Varias cajas se unen en el orden 1, 2, 3… incluso si están en páginas distintas.
- OCR local con Tesseract en español e inglés.
- Cinco preprocesamientos de imagen y varias estrategias de lectura.
- Reconstrucción de espacios a partir de los huecos visuales entre palabras.
- Margen de seguridad para no cortar la primera o última letra por pocos píxeles.
- Alerta de revisión cuando distintas lecturas no coinciden, aunque la confianza sea alta.
- Campo editable y recorte visible para comparar letra por letra.
- Renombrado seguro para Windows; conserva acentos y evita caracteres inválidos.
- No sobrescribe archivos: agrega `(2)`, `(3)`, etc. si existe un duplicado.
- Botón para omitir documentos difíciles.
- Historial en SQLite y opción para deshacer el último cambio de nombre.
- Atajos: `Enter`, flechas, `R`, `S` y `Ctrl+Z`.
- Los PDF y recortes nunca se envían a internet.

## Atajos de teclado

| Tecla | Acción |
|---|---|
| `Enter` | Aprobar el nombre y saltar al siguiente pendiente |
| `←` `→` | Documento anterior / siguiente |
| `↑` `↓` | Página anterior / siguiente |
| `R` | Limpiar las cajas de selección |
| `S` | Omitir el documento actual |
| `Ctrl+Z` | Deshacer el último renombrado |
| `Alt` + la tecla | Los atajos anteriores también funcionan mientras escribes el nombre |

Mientras el cursor está dentro del campo de nombre, las flechas mueven el cursor y `R`/`S`
escriben letras, como en cualquier campo de texto. Agrega `Alt` para usarlos como atajo sin
salir del campo: `Alt+→`, `Alt+S`, `Ctrl+Alt+Z`.

## Uso rápido con Windows

1. Instala Python 3.11 o 3.12.
2. Instala Tesseract OCR para Windows y asegúrate de incluir el idioma español.
3. Ejecuta `setup_windows.bat` una sola vez.
4. Copia tus PDF a `data\inbox`.
5. Ejecuta `run_windows.bat`.
6. El navegador se abre automáticamente. Normalmente usará `http://127.0.0.1:8765`; si ese puerto está ocupado elegirá otro entre 8765 y 8799.

### Cómo cerrar la aplicación

- Lo normal: presiona `Ctrl+C` en la ventana negra que se abrió al iniciar, o simplemente ciérrala.
- Si perdiste la ventana o hay varias instancias abiertas: ejecuta `stop_windows.bat`. Revisa
  los puertos 8765 a 8799, confirma con `/api/health` que cada uno sea el Renombrador (no toca
  otros programas) y cierra todas las instancias que encuentre.

La aplicación busca automáticamente Tesseract en:

- el `PATH` del sistema;
- `C:\Program Files\Tesseract-OCR\tesseract.exe`;
- la ruta definida en `TESSERACT_CMD`.

## Uso desde el Project Dashboard

Registrado como `renombrador-pdf` en el puerto **5027**. En la tarjeta: **Rebuild** para
construir la imagen, el interruptor para encenderlo y **Open ↗** para abrirlo.

Los archivos viven en el volumen de Docker `renombrador_pdf_data` (montado en `/app/data`),
no en la carpeta `data/` del proyecto. Es decir: por aquí **se sube la carpeta desde el
navegador y se descarga el ZIP** — no puedes copiar PDF a mano a `data/inbox`. Los datos
sobreviven a reinicios y a apagar y prender el contenedor.

Desde **Env** puedes ajustar `OCR_LANGUAGES`, `PDF_OCR_DPI` y `PDF_RENDER_DPI` sin reconstruir.

Para empezar de cero y borrar todo lo subido:

```bash
docker volume rm renombrador_pdf_data
```

## Uso con Docker Desktop (compose)

```bash
docker compose up --build
```

Después abre `http://127.0.0.1:8765`. A diferencia del dashboard, aquí la carpeta local
`data/inbox` sí queda montada dentro del contenedor, así que puedes copiar los PDF a mano.

## Uso manual en macOS o Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

También puedes ejecutar `./run_linux.sh`; el lanzador escogerá automáticamente un puerto libre.

## Subir una carpeta y descargar el ZIP

1. Presiona **Subir carpeta** y elige la carpeta con los PDF. También puedes arrastrarla
   sobre la ventana o usar **Subir PDF sueltos** para archivos individuales.
2. Los archivos se copian a `data/inbox/<nombre de la carpeta>`; si ese lote ya existe se crea
   `<nombre> (2)`. Se conservan las subcarpetas. Los originales en tu disco no se tocan.
3. Renombra los documentos uno por uno. Al aprobar, la aplicación salta sola al siguiente
   pendiente del lote.
4. Cuando termines, elige el **Lote** y si quieres **Sólo aprobados** o **Todos los archivos**,
   y presiona **Descargar ZIP**.

El ZIP de un lote trae los archivos ya renombrados en la raíz. El ZIP de *Todos* conserva la
carpeta de cada lote para no mezclarlos. Sólo se aceptan archivos `.pdf` reales: la extensión
no basta, el servidor verifica la firma del archivo y descarta el resto.

## Flujo recomendado para los 400 PDF

1. Sube primero una muestra de 10 a 20 PDF.
2. Abre el primer documento.
3. Arrastra una caja que incluya las dos líneas cuando el nombre esté partido.
4. Si hay texto no deseado entre partes del nombre, crea varias cajas pequeñas en el orden correcto.
5. Presiona **Leer selecciones con OCR**.
6. Compara el recorte con el texto propuesto y corrige manualmente.
7. Presiona **Aprobar y siguiente**.
8. Cuando confirmes que el flujo funciona bien con tu formato, sube el resto del lote.
9. Descarga el ZIP del lote terminado.

## Configuración opcional

Variables de entorno:

| Variable | Valor predeterminado | Uso |
|---|---|---|
| `PDF_INPUT_DIR` | `data/inbox` | Carpeta que contiene los PDF |
| `PDF_STATE_DIR` | `data/state` | Base SQLite e historial |
| `PDF_RENDER_DPI` | `150` | Calidad del visor |
| `PDF_OCR_DPI` | `450` | Calidad del recorte para OCR |
| `OCR_LANGUAGES` | `spa+eng` | Idiomas de Tesseract |
| `TESSERACT_CMD` | autodetección | Ruta al ejecutable de Tesseract |

El límite por archivo subido es de 300 MB. El navegador envía la carpeta en tandas de hasta
25 archivos o 40 MB para que un lote grande no dependa de una sola petición.

## Seguridad y recuperación

El sistema cambia únicamente el nombre del archivo. No modifica el contenido del PDF. Cada aprobación crea un registro en `data/state/renamer.db`. El botón **Deshacer último** restaura el nombre anterior siempre que no exista otro archivo con ese nombre.

Para una copia adicional de seguridad, duplica la carpeta original antes de comenzar el lote completo.


## Si aparece una página de otro sistema

Eso significa que otro programa ya usa el puerto que intentaste abrir. El lanzador incluido evita el conflicto: busca un puerto libre entre `8765` y `8799`, espera a que el Renombrador PDF esté listo y sólo entonces abre el navegador. La dirección exacta también aparece en la ventana negra.

Para fijar manualmente un puerto libre:

```bash
python launcher.py --port 8770
```


## Actualizar desde una versión anterior

1. Cierra la ventana del Renombrador PDF.
2. Descomprime la versión nueva sobre la carpeta existente y acepta reemplazar archivos.
3. No borres `data\inbox` ni `data\state`.
4. Ejecuta de nuevo `run_windows.bat`.
5. Si el navegador estaba abierto, presiona `Ctrl+F5` una vez.

La versión 1.1 corrige nombres pegados, signos espurios y selecciones que cortan ligeramente una letra.

La versión 1.2 agrega la subida de carpetas y la descarga en ZIP, corrige que al aprobar un
nombre la aplicación se quedara en el mismo documento y agrega el recorrido con flechas.
La lista de documentos ya no se reordena al aprobar: conserva el orden original de la carpeta,
así que el contador «Documento 5 de 400» avanza como esperas.
