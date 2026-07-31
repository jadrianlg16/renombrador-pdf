# Validación realizada

Fecha de validación: 2026-07-30
Version: 1.2.0

## Versión 1.2.0

Servidor de prueba en el puerto 8790 apuntado a una bandeja temporal, para no tocar
`data/inbox` ni `data/state/renamer.db` reales (se comprobó al final que ambos quedaron
idénticos).

### Corrección del salto al siguiente documento

Causa: `approveCurrent()` mantenía `state.busy = true` mientras llamaba a `loadDocuments()`,
y `selectDocument()` empezaba con un `return` temprano cuando `state.busy` era verdadero.
El renombrado se guardaba, pero el visor se quedaba en el archivo ya aprobado. Lo mismo
ocurría al omitir, al sincronizar y al deshacer.

Corrección: `setBusy` ahora lleva un contador anidable y `selectDocument` acepta `force`
para las llamadas internas. Además la aprobación salta explícitamente al **siguiente
pendiente**, dando la vuelta al final del lote.

Prueba en el navegador: se subió una carpeta de 4 PDF y se aprobaron los 4 seguidos con
`Enter`. El contador avanzó `Documento 5 de 8` → `6 de 8` → `7 de 8` → `8 de 8` y, al no
quedar pendientes en ese lote, saltó al pendiente restante mostrando el aviso de que ya
se puede descargar el ZIP.

### Orden estable de la lista

`list_documents()` ordenaba por estado, así que cada aprobación mandaba el archivo al final
y el contador de posición nunca avanzaba. Ahora ordena por `original_relative_path`, que no
cambia al renombrar. Verificado con una prueba automática que compara el orden de los `id`
antes y después de aprobar.

### Teclado

Verificado con eventos de teclado sobre la aplicación en ejecución:

- `←` / `→` movieron entre documentos (índices 1 → 2 → 3 → 2).
- `↑` / `↓` cambiaron de página y se detuvieron en los extremos (1 → 2 → 2 → 1).
- Con el cursor dentro del campo de nombre, `→` **no** cambió de documento y `s` **no** omitió,
  que es lo correcto para un campo de texto.
- `Alt+→`, `Alt+←`, `Alt+S` y `Ctrl+Alt+Z` sí funcionaron con el cursor dentro del campo.
- `Ctrl+Z` dentro del campo ya no deshace el renombrado; antes lo hacía y podía revertir un
  archivo sin querer mientras se corregía un nombre.

### Subida de carpeta

- Subida desde el selector de carpeta: se detectó el nombre del lote a partir de
  `webkitRelativePath`, se conservó la subcarpeta `sub/` y los 4 PDF quedaron en
  `data/inbox/Escrituras Junio`.
- Arrastrar y soltar: la capa de aviso apareció al arrastrar, desapareció al soltar y el
  archivo entró en un lote con nombre automático `lote-AAAAMMDD-HHMMSS`.
- El envío se parte en tandas de 25 archivos o 40 MB; la primera crea el lote y las siguientes
  se le agregan con el identificador devuelto por el servidor.
- Rechazos comprobados con pruebas automáticas: archivos que no son `.pdf`, archivos con
  extensión `.pdf` pero sin la firma `%PDF-`, y rutas con `../` que quedan contenidas dentro
  de la bandeja.

### Descarga en ZIP

- ZIP de un lote: los 4 archivos con sus nombres nuevos, la subcarpeta conservada, CRC íntegro
  y el primer archivo sigue empezando con `%PDF-1.7`.
- ZIP de todo: conserva la carpeta de cada lote para no mezclarlos.
- `Content-Disposition` correcto con el nombre del lote codificado en UTF-8.
- La carpeta temporal `data/state/exports` quedó vacía después de cada descarga.
- Filtro sin resultados responde `404` en vez de entregar un ZIP vacío.

### Estado final

- 30 pruebas automáticas aprobadas (`pytest`).
- Sin errores en la consola del navegador ni en el registro del servidor durante todo el flujo.
- No se pudo tomar una captura de pantalla: el panel del navegador no estaba visible y por eso
  la página no compone imagen. La interfaz se verificó por árbol de accesibilidad, geometría
  calculada de los elementos nuevos y ausencia de desborde horizontal.

## Pruebas automáticas

- Sanitización de caracteres inválidos para nombres de archivo en Windows.
- Conservación de acentos y caracteres Unicode.
- Prevención de nombres reservados de Windows como `CON`.
- Prevención de sobrescritura mediante sufijos `(2)`, `(3)`, etc.
- Conservación de saltos de línea durante la lectura OCR.
- Unión de varias líneas y varias regiones con un solo espacio.
- Eliminación de signos espurios insertados entre letras por OCR.
- Detección visual de separaciones entre palabras.
- Selección automática de puerto libre.
- Rechazo de un puerto solicitado que ya esté ocupado.
- Saneamiento de rutas de subida: `../`, letras de unidad y nombres larguísimos.
- Creación de lotes sin sobrescribir uno existente.
- Subida, agregado a un lote existente y rechazo de archivos que no son PDF.
- Contenido y estructura del ZIP por lote y del ZIP completo.
- Orden estable de la lista de documentos después de aprobar.

Resultado: **30 pruebas aprobadas**.

## Prueba OCR multilínea

Se generó un PDF de prueba con el nombre:

```text
MARIA DEL CARMEN RODRIGUEZ
DE LA GARZA
```

Con una sola caja que cubre ambas líneas, el resultado fue:

```text
MARIA DEL CARMEN RODRIGUEZ DE LA GARZA
```

Confianza orientativa: **95.9 %**. El sistema no marcó discrepancias.

## Prueba de reconstrucción de espacios

Se generó una imagen con:

```text
JORGE ENRIQUE CASTRO GARZA
```

El análisis por huecos visuales detectó cuatro palabras y devolvió exactamente:

```text
JORGE ENRIQUE CASTRO GARZA
```

Esta estrategia no depende de que Tesseract conserve correctamente los espacios.

## Prueba de selección demasiado ajustada

Se desplazó intencionalmente el inicio de la caja para cortar parte de la primera letra.
Los métodos de OCR produjeron lecturas diferentes. Aunque una lectura mostró más de 90 %
de confianza, el sistema marcó `needs_review: true` para impedir que esa cifra se interprete
como garantía de exactitud.

## Cambios de interfaz

- El número de la selección se dibuja fuera de la caja cuando hay espacio, para no tapar el nombre.
- Los resultados dudosos muestran una alerta roja.
- Los archivos estáticos incluyen versión en la URL para evitar que el navegador conserve JavaScript anterior.

## Seguridad del recorte

El backend agrega un margen pequeño y limitado alrededor de la caja. Esto permite recuperar
bordes de letras ligeramente cortados sin ampliar excesivamente la selección hacia texto vecino.

## Verificación del servidor

- `GET /api/health` respondió `200 OK`.
- La respuesta incluyó `app_id: renombrador-pdf` y `version: 1.1.0`.
- `GET /` respondió con el título `Renombrador PDF`.
- `app/static/app.js` pasó la comprobación de sintaxis de Node.

La captura automatizada con Chromium no pudo completarse en el contenedor por errores del
entorno gráfico/DBus. La interfaz se verificó mediante respuesta HTTP, DOM entregado y sintaxis
de JavaScript; no se afirma una nueva prueba visual automatizada para esta revisión.
