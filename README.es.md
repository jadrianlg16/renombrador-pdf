# Renombrador PDF: guía de uso

[English version](README.md)

Aplicación local para renombrar un lote de PDF escaneados. Marcas con el mouse dónde está el nombre, el sistema lo lee con OCR sólo en esa zona y propone el nombre del archivo. El archivo se renombra únicamente cuando una persona revisa la propuesta y la aprueba.

Todo corre en tu equipo: los PDF y los recortes no se envían a ningún servicio externo. Al aprobar, el sistema sólo cambia el nombre del archivo; nunca modifica su contenido.

![Pantalla de revisión con una caja sobre el nombre, el nombre propuesto por el OCR y los recortes para comparar](docs/review.png)

## Contenido

- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Cómo cerrar la aplicación](#cómo-cerrar-la-aplicación)
- [Flujo de trabajo](#flujo-de-trabajo)
- [Atajos de teclado](#atajos-de-teclado)
- [Limpiar un lote](#limpiar-un-lote)
- [Configuración opcional](#configuración-opcional)
- [Seguridad y recuperación](#seguridad-y-recuperación)
- [Problemas frecuentes](#problemas-frecuentes)

## Requisitos

- **Python 3.12.**
- **Tesseract OCR 5** con los idiomas español (`spa`) e inglés (`eng`):
  - **Windows:** usa el [instalador de UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki). En la lista de componentes, abre *Additional language data* y marca *Spanish*.
  - **macOS (Homebrew):** `brew install tesseract tesseract-lang`
  - **Debian / Ubuntu:** `sudo apt-get install tesseract-ocr tesseract-ocr-spa`

Para comprobar la instalación, ejecuta `tesseract --list-langs`; deben aparecer `eng` y `spa`.

La aplicación busca Tesseract en este orden:

1. la variable de entorno `TESSERACT_CMD`;
2. el `PATH` del sistema;
3. `C:\Program Files\Tesseract-OCR\tesseract.exe`;
4. `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`.

## Instalación

### Windows

1. Ejecuta `setup_windows.bat` una sola vez. Crea el entorno `.venv`, instala las dependencias y avisa si no encuentra Tesseract.
2. Ejecuta `run_windows.bat` cada vez que quieras usar la aplicación.
3. El navegador se abre solo. Normalmente la dirección será `http://127.0.0.1:8765`; si ese puerto está ocupado, se elige otro libre entre 8765 y 8799. La dirección exacta también aparece en la ventana negra.

### macOS o Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python launcher.py
```

El lanzador elige un puerto libre entre 8765 y 8799 y abre el navegador cuando la aplicación está lista. Una vez creado `.venv`, también puedes iniciarla con `sh run_linux.sh`.

### Docker

```bash
docker build -t renombrador-pdf .
docker run --rm -p 127.0.0.1:8765:8000 -v "$PWD/data:/app/data" renombrador-pdf
```

Después abre `http://127.0.0.1:8765`. La carpeta `data` del proyecto queda montada dentro del contenedor, así que también puedes copiar PDF a mano a `data/inbox`. La imagen ya incluye Tesseract con español e inglés.

> El archivo `docker-compose.yml` publica el puerto en todas las interfaces de red. Si lo usas, cambia `"8765:8000"` por `"127.0.0.1:8765:8000"` para que sólo tu equipo pueda abrir la aplicación.

### Probar con un PDF de ejemplo

```bash
.venv/bin/python generate_demo_pdf.py
```

En Windows usa `.venv\Scripts\python generate_demo_pdf.py`. Esto crea `data/inbox/demo_nombre_dos_lineas.pdf`, una página con un nombre inventado partido en dos líneas. Si la aplicación ya estaba abierta, presiona **Actualizar carpeta**.

## Cómo cerrar la aplicación

- Lo normal: presiona `Ctrl+C` en la ventana negra que se abrió al iniciar, o simplemente ciérrala.
- En Windows, si perdiste la ventana o hay varias instancias abiertas, ejecuta `stop_windows.bat`. Revisa los puertos 8765 a 8799, confirma con `/api/health` que cada uno sea el Renombrador y cierra todas las instancias que encuentre.
- No uses `stop_windows.bat` mientras corre el contenedor de Docker: en ese caso el puerto lo ocupa Docker Desktop y el script lo cerraría a la fuerza. Detén el contenedor con `Ctrl+C` o `docker stop`.

## Flujo de trabajo

1. **Sube los PDF.** Presiona **Subir carpeta** y elige la carpeta. También puedes arrastrarla sobre la ventana, o usar **Subir PDF sueltos** para archivos individuales. Los archivos se copian a `data/inbox/<nombre de la carpeta>`; si ese lote ya existe, se crea `<nombre> (2)`. Se conservan las subcarpetas y los originales en tu disco no se tocan.
2. **Marca el nombre.** Arrastra una caja sobre el nombre en la página. Una sola caja puede incluir un nombre partido en dos o más líneas. Si entre las partes del nombre hay texto que no quieres, crea varias cajas pequeñas en el orden correcto: se unen en el orden 1, 2, 3…, aunque estén en páginas distintas.
3. **Lee con OCR.** Presiona **Leer selecciones con OCR**. La caja se lee de varias formas y se propone la mejor lectura.
4. **Revisa.** Compara el recorte con el texto propuesto y corrige el nombre si hace falta. En **Lecturas propuestas** puedes hacer clic en otra lectura para usarla. Si las lecturas no coinciden entre sí, el sistema pide revisión aunque la confianza sea alta.
5. **Aprueba.** Presiona **Aprobar y siguiente** (o `Enter`). El archivo se renombra y la aplicación salta sola al siguiente documento pendiente del lote. Si un documento es difícil, usa **Omitir por ahora**.
6. **Descarga el ZIP.** Elige el **Lote** y si quieres **Sólo aprobados** o **Todos los archivos**, y presiona **Descargar ZIP**. El ZIP de un lote trae los archivos renombrados en la raíz; el ZIP de todos los lotes conserva la carpeta de cada uno para no mezclarlos.
7. **Limpia el lote.** Con el ZIP ya guardado, presiona **Limpiar lote** para dejar la bandeja lista para la siguiente carpeta.

Sólo se aceptan archivos `.pdf` reales: la extensión no basta, el servidor verifica la firma del archivo y descarta el resto. La lista conserva el orden original de la carpeta, así que el contador «Documento 5 de N» avanza como esperas.

**Para un lote grande**, sube primero una muestra de 10 a 20 PDF. Cuando confirmes que el flujo funciona bien con el formato de tus documentos, sube el resto.

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

Mientras el cursor está dentro del campo de nombre, las flechas mueven el cursor y `R`/`S` escriben letras, como en cualquier campo de texto. Agrega `Alt` para usarlos como atajo sin salir del campo: `Alt+→`, `Alt+S`, `Ctrl+Alt+Z`.

## Limpiar un lote

**Limpiar lote** borra del disco la carpeta del lote elegido arriba. Es definitivo: no hay papelera ni forma de deshacerlo. Por eso tiene estos límites:

- Sólo borra **carpetas de lote**. Nunca borra archivos sueltos en la raíz de `data/inbox`, ni la bandeja entera, ni todos los lotes de un golpe.
- Pide confirmación y muestra cuántos archivos se van y cuántos ya tenían nombre nuevo.
- Si todavía no descargaste el ZIP de ese lote y ya hay nombres corregidos, la confirmación lo advierte.
- Una carpeta que ya estaba en la bandeja (no subida desde el navegador) también se puede limpiar, pero la confirmación avisa que no la subiste en esta sesión y te pide confirmar que no son tus originales. **Si montaste tu carpeta real en Docker, lee ese aviso con cuidado: ahí sí serían tus originales.**

Después de limpiar un lote, su nombre queda libre: si vuelves a subir una carpeta «Lote marzo», se crea `Lote marzo` y no `Lote marzo (2)`.

## Configuración opcional

Variables de entorno:

| Variable | Valor predeterminado | Uso |
|---|---|---|
| `PDF_INPUT_DIR` | `data/inbox` | Carpeta con los PDF; ahí se guardan las subidas y se renombran los archivos |
| `PDF_STATE_DIR` | `data/state` | Base SQLite (`renamer.db`) y ZIP temporales |
| `PDF_OCR_DPI` | `450` | Resolución del recorte que se lee con OCR |
| `PDF_RENDER_DPI` | `150` | Resolución predeterminada de la imagen de página cuando la petición no indica otra; la interfaz siempre pide 150 |
| `OCR_LANGUAGES` | `spa+eng` | Idiomas de Tesseract |
| `TESSERACT_CMD` | autodetección | Ruta al ejecutable de Tesseract |

El límite por archivo subido es de 300 MB. El navegador envía la carpeta en tandas de hasta 25 archivos o 40 MB, para que un lote grande no dependa de una sola petición.

## Seguridad y recuperación

- Cada aprobación queda registrada en `data/state/renamer.db`. El botón **Deshacer último** restaura el nombre anterior, siempre que no exista ya otro archivo con ese nombre. Puedes presionarlo varias veces para deshacer, uno por uno, los renombrados más recientes.
- Los archivos nunca se sobrescriben: si el nombre ya existe, se agrega `(2)`, `(3)`, etc. Se conservan los acentos y se reemplazan los caracteres que Windows no acepta.
- Si copias tus PDF directamente a `data/inbox` (en lugar de subirlos), se renombran esos mismos archivos. Para tener un respaldo, duplica la carpeta original antes de empezar.
- La aplicación no tiene usuarios ni contraseñas: cualquiera que pueda abrir su dirección puede ver, renombrar y borrar archivos. Úsala sólo en `127.0.0.1` y no la expongas en una red.

## Problemas frecuentes

**Aparece una página de otro sistema.** Otro programa ya usa el puerto que intentaste abrir. El lanzador evita el conflicto: busca un puerto libre entre 8765 y 8799, espera a que el Renombrador esté listo y sólo entonces abre el navegador. La dirección exacta aparece en la ventana negra. Para fijar un puerto libre a mano:

```bash
.venv/bin/python launcher.py --port 8770
```

En Windows: `.venv\Scripts\python launcher.py --port 8770`.

**El OCR responde que no encuentra Tesseract.** Instálalo con el idioma español (ver [Requisitos](#requisitos)) o define `TESSERACT_CMD` con la ruta completa al ejecutable. La dirección `/api/health` de la aplicación muestra si Tesseract está listo (`tesseract_ready`) y qué idiomas tiene instalados.

**Después de actualizar el código, la página se ve rara.** Presiona `Ctrl+F5` una vez para que el navegador cargue la versión nueva.
