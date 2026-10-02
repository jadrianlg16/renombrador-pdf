const state = {
  documents: [],
  counts: {},
  currentIndex: -1,
  currentDocument: null,
  currentPage: 1,
  pageCount: 0,
  zoom: 1,
  selections: [],
  draftSelection: null,
  ocrResult: null,
  busy: false,
  uploading: false,
  batches: [],
  latestUpload: null,
  modalOpen: false,
  maxUploadBytes: null,
};

const ALL_BATCHES = '__all__';
const UPLOAD_MAX_BYTES_PER_REQUEST = 40 * 1024 * 1024;
const UPLOAD_MAX_FILES_PER_REQUEST = 25;

const elements = {
  toast: document.querySelector('#toast'),
  progressSummary: document.querySelector('#progress-summary'),
  syncButton: document.querySelector('#sync-button'),
  undoButton: document.querySelector('#undo-button'),
  positionLabel: document.querySelector('#position-label'),
  fileName: document.querySelector('#file-name'),
  previousDocument: document.querySelector('#previous-document'),
  nextDocument: document.querySelector('#next-document'),
  openPdf: document.querySelector('#open-pdf'),
  previousPage: document.querySelector('#previous-page'),
  nextPage: document.querySelector('#next-page'),
  pageIndicator: document.querySelector('#page-indicator'),
  zoomRange: document.querySelector('#zoom-range'),
  zoomOutput: document.querySelector('#zoom-output'),
  removeSelection: document.querySelector('#remove-selection'),
  clearSelections: document.querySelector('#clear-selections'),
  emptyState: document.querySelector('#empty-state'),
  pageStage: document.querySelector('#page-stage'),
  pageImage: document.querySelector('#page-image'),
  canvas: document.querySelector('#selection-canvas'),
  pageLoading: document.querySelector('#page-loading'),
  statusBadge: document.querySelector('#status-badge'),
  selectionCount: document.querySelector('#selection-count'),
  selectionPages: document.querySelector('#selection-pages'),
  ocrButton: document.querySelector('#ocr-button'),
  confidenceCard: document.querySelector('#confidence-card'),
  confidenceValue: document.querySelector('#confidence-value'),
  confidenceMessage: document.querySelector('#confidence-message'),
  nameInput: document.querySelector('#name-input'),
  filenamePreview: document.querySelector('#filename-preview'),
  candidateSection: document.querySelector('#candidate-section'),
  candidateList: document.querySelector('#candidate-list'),
  cropSection: document.querySelector('#crop-section'),
  cropList: document.querySelector('#crop-list'),
  approveButton: document.querySelector('#approve-button'),
  skipButton: document.querySelector('#skip-button'),
  documentQueue: document.querySelector('#document-queue'),
  uploadFolderButton: document.querySelector('#upload-folder-button'),
  uploadFilesButton: document.querySelector('#upload-files-button'),
  folderInput: document.querySelector('#folder-input'),
  filesInput: document.querySelector('#files-input'),
  uploadHint: document.querySelector('#upload-hint'),
  uploadProgress: document.querySelector('#upload-progress'),
  uploadProgressFill: document.querySelector('#upload-progress-fill'),
  uploadProgressLabel: document.querySelector('#upload-progress-label'),
  exportFolder: document.querySelector('#export-folder'),
  exportScope: document.querySelector('#export-scope'),
  exportButton: document.querySelector('#export-button'),
  dropOverlay: document.querySelector('#drop-overlay'),
  clearBatchButton: document.querySelector('#clear-batch-button'),
  clearModal: document.querySelector('#clear-modal'),
  clearModalTarget: document.querySelector('#clear-modal-target'),
  clearModalWarning: document.querySelector('#clear-modal-warning'),
  clearCancel: document.querySelector('#clear-cancel'),
  clearConfirm: document.querySelector('#clear-confirm'),
};

const canvasContext = elements.canvas.getContext('2d');
let toastTimer = null;
let pointerStart = null;
let busyDepth = 0;
let dragDepth = 0;

function showToast(message, type = '') {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast visible ${type}`;
  toastTimer = setTimeout(() => {
    elements.toast.className = 'toast';
  }, 3500);
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

// Contador en vez de booleano: aprobar llama a loadDocuments() mientras sigue ocupado
// y antes eso dejaba la interfaz habilitada a medias.
function setBusy(value, message = '') {
  busyDepth = Math.max(0, busyDepth + (value ? 1 : -1));
  state.busy = busyDepth > 0;
  if (message) showToast(message);
  updateControls();
}

function documentBatch(item) {
  const parts = (item.current_relative_path || '').split('/');
  return parts.length > 1 ? parts[0] : '';
}

function nextPendingIndex(fromIndex) {
  const total = state.documents.length;
  if (!total) return -1;
  for (let step = 1; step <= total; step += 1) {
    const index = (fromIndex + step + total) % total;
    if (state.documents[index].status === 'pending') return index;
  }
  return -1;
}

async function loadDocuments(options = {}) {
  const { preferredId = null, preferBatch = null, advanceFrom = null } = options;
  const [payload, batchPayload] = await Promise.all([
    request('/api/documents'),
    request('/api/batches').catch(() => ({ batches: [], latest_upload: null })),
  ]);
  state.documents = payload.documents;
  state.counts = payload.counts;
  state.batches = batchPayload.batches || [];
  state.latestUpload = batchPayload.latest_upload || null;
  renderProgress();
  renderExportFolders(preferBatch);
  renderQueue();

  if (!state.documents.length) {
    clearDocument();
    return;
  }

  let index = -1;
  if (advanceFrom) {
    const origin = state.documents.findIndex((document) => document.id === advanceFrom);
    index = nextPendingIndex(origin);
    if (index < 0) index = origin;
  }
  if (index < 0 && preferredId) index = state.documents.findIndex((document) => document.id === preferredId);
  if (index < 0 && preferBatch !== null) {
    index = state.documents.findIndex(
      (document) => document.status === 'pending' && documentBatch(document) === preferBatch,
    );
  }
  if (index < 0 && state.currentDocument) {
    index = state.documents.findIndex((document) => document.id === state.currentDocument.id);
  }
  if (index < 0) index = state.documents.findIndex((document) => document.status === 'pending');
  if (index < 0) index = 0;
  await selectDocument(index, { force: true });
}

function renderProgress() {
  const pending = state.counts.pending || 0;
  const approved = state.counts.approved || 0;
  const skipped = state.counts.skipped || 0;
  const total = state.documents.length;
  elements.progressSummary.textContent = `${approved} aprobados · ${pending} pendientes · ${skipped} omitidos · ${total} total`;
}

function renderQueue() {
  elements.documentQueue.innerHTML = '';
  let activeButton = null;
  state.documents.forEach((item, index) => {
    const button = window.document.createElement('button');
    button.type = 'button';
    const isActive = state.currentDocument?.id === item.id;
    button.className = `queue-item ${item.status} ${isActive ? 'active' : ''}`;
    button.textContent = `${index + 1}. ${item.current_name}`;
    button.title = `${item.status}: ${item.current_relative_path}`;
    button.addEventListener('click', () => selectDocument(index));
    elements.documentQueue.appendChild(button);
    if (isActive) activeButton = button;
  });
  if (activeButton && elements.documentQueue.offsetParent) {
    activeButton.scrollIntoView({ block: 'nearest' });
  }
}

function clearDocument() {
  state.currentIndex = -1;
  state.currentDocument = null;
  state.currentPage = 1;
  state.pageCount = 0;
  state.selections = [];
  state.ocrResult = null;
  elements.emptyState.hidden = false;
  elements.pageStage.hidden = true;
  elements.fileName.textContent = 'Sin documentos';
  elements.positionLabel.textContent = 'Documento';
  elements.pageIndicator.textContent = 'Página 0 de 0';
  elements.nameInput.value = '';
  elements.filenamePreview.textContent = '—.pdf';
  resetOcrPanels();
  updateControls();
}

async function selectDocument(index, { force = false } = {}) {
  if (index < 0 || index >= state.documents.length) return;
  if (state.busy && !force) return;
  state.currentIndex = index;
  state.currentDocument = state.documents[index];
  state.currentPage = 1;
  state.selections = Array.isArray(state.currentDocument.selections) ? state.currentDocument.selections : [];
  state.ocrResult = null;
  resetOcrPanels();
  elements.nameInput.value = state.currentDocument.proposed_name || '';
  updateFilenamePreview();
  renderQueue();
  updateDocumentHeader();

  try {
    setBusy(true);
    const detail = await request(`/api/documents/${state.currentDocument.id}`);
    state.currentDocument = { ...state.currentDocument, ...detail };
    state.pageCount = detail.page_count || 1;
    await loadPage();
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    setBusy(false);
    updateControls();
  }
}

function updateDocumentHeader() {
  const document = state.currentDocument;
  if (!document) return;
  elements.emptyState.hidden = true;
  elements.pageStage.hidden = false;
  elements.fileName.textContent = document.current_name;
  elements.positionLabel.textContent = `Documento ${state.currentIndex + 1} de ${state.documents.length}`;
  elements.openPdf.href = `/api/documents/${document.id}/file`;
  elements.statusBadge.textContent = ({ pending: 'Pendiente', approved: 'Aprobado', skipped: 'Omitido', missing: 'No encontrado' })[document.status] || document.status;
  elements.statusBadge.className = `status-badge ${document.status}`;
}

async function loadPage() {
  if (!state.currentDocument) return;
  elements.pageLoading.hidden = false;
  elements.pageImage.onload = () => {
    applyZoom();
    elements.pageLoading.hidden = true;
    redrawCanvas();
  };
  elements.pageImage.onerror = () => {
    elements.pageLoading.hidden = true;
    showToast('No se pudo cargar la página', 'error');
  };
  // No dpi parameter: the server renders at PDF_RENDER_DPI.
  elements.pageImage.src = `/api/documents/${state.currentDocument.id}/page/${state.currentPage}?t=${Date.now()}`;
  elements.pageIndicator.textContent = `Página ${state.currentPage} de ${state.pageCount}`;
  updateControls();
}

function applyZoom() {
  if (!elements.pageImage.naturalWidth) return;
  const width = Math.round(elements.pageImage.naturalWidth * state.zoom);
  const height = Math.round(elements.pageImage.naturalHeight * state.zoom);
  elements.pageImage.style.width = `${width}px`;
  elements.pageImage.style.height = `${height}px`;
  elements.pageStage.style.width = `${width}px`;
  elements.pageStage.style.height = `${height}px`;
  const deviceScale = window.devicePixelRatio || 1;
  elements.canvas.width = Math.round(width * deviceScale);
  elements.canvas.height = Math.round(height * deviceScale);
  elements.canvas.style.width = `${width}px`;
  elements.canvas.style.height = `${height}px`;
  canvasContext.setTransform(deviceScale, 0, 0, deviceScale, 0, 0);
  redrawCanvas();
}

function redrawCanvas() {
  const width = parseFloat(elements.canvas.style.width) || 0;
  const height = parseFloat(elements.canvas.style.height) || 0;
  canvasContext.clearRect(0, 0, width, height);

  state.selections.forEach((selection, index) => {
    if (selection.page !== state.currentPage) return;
    drawSelection(selection, index + 1, '#2f80ed', 'rgba(47,128,237,.16)');
  });
  if (state.draftSelection) {
    drawSelection(state.draftSelection, state.selections.length + 1, '#31c48d', 'rgba(49,196,141,.16)');
  }
}

function drawSelection(selection, number, stroke, fill) {
  const width = parseFloat(elements.canvas.style.width) || 0;
  const height = parseFloat(elements.canvas.style.height) || 0;
  const x = selection.x * width;
  const y = selection.y * height;
  const boxWidth = selection.width * width;
  const boxHeight = selection.height * height;
  canvasContext.fillStyle = fill;
  canvasContext.strokeStyle = stroke;
  canvasContext.lineWidth = 2;
  canvasContext.fillRect(x, y, boxWidth, boxHeight);
  canvasContext.strokeRect(x, y, boxWidth, boxHeight);
  let markerX = x + 12;
  let markerY = y - 12;
  if (markerY < 12) {
    markerX = x + boxWidth + 12;
    markerY = y + 12;
  }
  if (markerX > width - 12) markerX = Math.max(12, x - 12);
  canvasContext.fillStyle = stroke;
  canvasContext.beginPath();
  canvasContext.arc(markerX, markerY, 10, 0, Math.PI * 2);
  canvasContext.fill();
  canvasContext.fillStyle = '#fff';
  canvasContext.font = '700 11px system-ui';
  canvasContext.textAlign = 'center';
  canvasContext.textBaseline = 'middle';
  canvasContext.fillText(String(number), markerX, markerY);
}

function canvasPoint(event) {
  const rect = elements.canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(rect.width, event.clientX - rect.left)),
    y: Math.max(0, Math.min(rect.height, event.clientY - rect.top)),
    width: rect.width,
    height: rect.height,
  };
}

function pointerDown(event) {
  if (!state.currentDocument || state.busy) return;
  elements.canvas.setPointerCapture(event.pointerId);
  pointerStart = canvasPoint(event);
  state.draftSelection = null;
}

function pointerMove(event) {
  if (!pointerStart) return;
  const point = canvasPoint(event);
  const x1 = Math.min(pointerStart.x, point.x);
  const y1 = Math.min(pointerStart.y, point.y);
  const x2 = Math.max(pointerStart.x, point.x);
  const y2 = Math.max(pointerStart.y, point.y);
  state.draftSelection = {
    page: state.currentPage,
    x: x1 / point.width,
    y: y1 / point.height,
    width: (x2 - x1) / point.width,
    height: (y2 - y1) / point.height,
  };
  redrawCanvas();
}

function pointerUp(event) {
  if (!pointerStart) return;
  const point = canvasPoint(event);
  const draft = state.draftSelection;
  pointerStart = null;
  state.draftSelection = null;
  try { elements.canvas.releasePointerCapture(event.pointerId); } catch (_) {}
  if (draft && draft.width * point.width >= 8 && draft.height * point.height >= 8) {
    state.selections.push(draft);
    resetOcrPanels();
    state.ocrResult = null;
  }
  redrawCanvas();
  updateControls();
}

function updateSelectionSummary() {
  const count = state.selections.length;
  elements.selectionCount.textContent = `${count} ${count === 1 ? 'selección' : 'selecciones'}`;
  const pages = [...new Set(state.selections.map((selection) => selection.page))].sort((a, b) => a - b);
  elements.selectionPages.textContent = pages.length ? `Páginas: ${pages.join(', ')}` : 'Ninguna página seleccionada';
}

function updateFilenamePreview() {
  const value = elements.nameInput.value.trim().replace(/[<>:"/\\|?*\u0000-\u001F]/g, ' ').replace(/\s+/g, ' ').replace(/[. ]+$/g, '');
  elements.filenamePreview.textContent = value ? `${value.replace(/\.pdf$/i, '')}.pdf` : '—.pdf';
  const editable = state.currentDocument && ['pending', 'skipped'].includes(state.currentDocument.status);
  elements.approveButton.disabled = state.busy || !editable || !value;
}

function updateControls() {
  const hasDocument = Boolean(state.currentDocument);
  elements.previousDocument.disabled = !hasDocument || state.currentIndex <= 0 || state.busy;
  elements.nextDocument.disabled = !hasDocument || state.currentIndex >= state.documents.length - 1 || state.busy;
  elements.previousPage.disabled = !hasDocument || state.currentPage <= 1 || state.busy;
  elements.nextPage.disabled = !hasDocument || state.currentPage >= state.pageCount || state.busy;
  elements.removeSelection.disabled = !state.selections.length || state.busy;
  elements.clearSelections.disabled = !state.selections.length || state.busy;
  const editable = hasDocument && ['pending', 'skipped'].includes(state.currentDocument.status);
  elements.ocrButton.disabled = !editable || !state.selections.length || state.busy;
  elements.skipButton.disabled = !editable || state.busy;
  elements.syncButton.disabled = state.busy;
  elements.undoButton.disabled = state.busy;
  elements.uploadFolderButton.disabled = state.busy;
  elements.uploadFilesButton.disabled = state.busy;
  updateSelectionSummary();
  updateFilenamePreview();
  updateExportControls();
}

function renderExportFolders(preferBatch = null) {
  const counts = new Map();
  state.documents.forEach((document) => {
    if (document.status === 'missing') return;
    const batch = documentBatch(document);
    counts.set(batch, (counts.get(batch) || 0) + 1);
  });

  const previous = elements.exportFolder.value;
  const options = [[ALL_BATCHES, `Todos (${state.documents.length})`]];
  [...counts.keys()].sort().forEach((batch) => {
    options.push([batch, `${batch || '(raíz)'} (${counts.get(batch)})`]);
  });

  elements.exportFolder.innerHTML = '';
  options.forEach(([value, label]) => {
    const option = window.document.createElement('option');
    option.value = value;
    option.textContent = label;
    elements.exportFolder.appendChild(option);
  });

  const wanted = [preferBatch, previous, ALL_BATCHES].find(
    (value) => value !== null && value !== undefined && options.some(([option]) => option === value),
  );
  elements.exportFolder.value = wanted ?? ALL_BATCHES;
}

function exportSelection() {
  // selectedIndex distingue "sin opciones" de la opción de la raíz, cuyo valor es "".
  const folder = elements.exportFolder.selectedIndex >= 0 ? elements.exportFolder.value : ALL_BATCHES;
  const scope = elements.exportScope.value;
  const matches = state.documents.filter((document) => {
    if (document.status === 'missing') return false;
    if (scope === 'approved' && document.status !== 'approved') return false;
    return folder === ALL_BATCHES || documentBatch(document) === folder;
  });
  return { folder, scope, count: matches.length };
}

function updateExportControls() {
  const { count } = exportSelection();
  const hasDocuments = state.documents.length > 0;
  elements.exportButton.textContent = count ? `Descargar ZIP (${count})` : 'Descargar ZIP';
  elements.exportButton.disabled = state.busy || !count;
  elements.exportFolder.disabled = state.busy || !hasDocuments;
  elements.exportScope.disabled = state.busy || !hasDocuments;
  updateClearBatchControls();
}

// El botón actúa sobre el lote elegido arriba, que tras subir una carpeta ya viene
// seleccionado en la nueva: así "limpiar el último lote" es un solo clic.
function selectedBatch() {
  const { folder } = exportSelection();
  if (folder === ALL_BATCHES) return null;
  return state.batches.find((batch) => batch.name === folder) || null;
}

function updateClearBatchControls() {
  const batch = selectedBatch();
  const { folder } = exportSelection();
  elements.clearBatchButton.disabled = state.busy || !batch?.deletable;
  if (!batch?.deletable) {
    elements.clearBatchButton.textContent = 'Limpiar lote';
    if (folder === ALL_BATCHES) {
      elements.clearBatchButton.title = 'Elige un lote concreto arriba; no se borran todos a la vez.';
    } else if (folder === '') {
      elements.clearBatchButton.title = 'Los PDF sueltos en la raíz de la bandeja no forman lote y no se borran desde aquí.';
    } else {
      elements.clearBatchButton.title = 'Este lote no se puede borrar desde aquí.';
    }
    return;
  }
  elements.clearBatchButton.textContent = `Limpiar “${batch.name}” (${batch.documents})`;
  elements.clearBatchButton.title = `Borra del disco los ${batch.documents} archivos de “${batch.name}”.`;
}

function openClearModal() {
  const batch = selectedBatch();
  if (!batch?.deletable || state.busy) return;
  const sinDescargar = batch.approved > 0 && !batch.exported_at;
  const unico = batch.approved === 1;
  const renombrados = unico ? '1 ya tiene su nombre nuevo' : `${batch.approved} ya tienen su nombre nuevo`;
  const cuantos = batch.documents === 1 ? 'Se borrará 1 archivo' : `Se borrarán ${batch.documents} archivos`;
  elements.clearModalTarget.textContent =
    `${cuantos} del lote “${batch.name}”${batch.approved ? `, de los cuales ${renombrados}` : ''}.`;
  const avisos = [];
  if (sinDescargar) {
    avisos.push(
      'Todavía no has descargado el ZIP de este lote. Si lo borras, pierdes '
      + (unico ? 'el nombre que ya corregiste.' : `los ${batch.approved} nombres que ya corregiste.`),
    );
  }
  if (batch.source === 'adopted') {
    avisos.push('Este lote ya estaba en la bandeja, no lo subiste en esta sesión. Confirma que no son tus originales.');
  }
  elements.clearModalWarning.hidden = avisos.length === 0;
  elements.clearModalWarning.textContent = avisos.join(' ');
  elements.clearModal.hidden = false;
  state.modalOpen = true;
  elements.clearCancel.focus();
}

function closeClearModal() {
  elements.clearModal.hidden = true;
  state.modalOpen = false;
}

async function confirmClearBatch() {
  const batch = selectedBatch();
  closeClearModal();
  if (!batch?.deletable) return;
  try {
    setBusy(true);
    const result = await request(`/api/batches/${encodeURIComponent(batch.name)}/delete`, { method: 'POST' });
    await loadDocuments();
    showToast(
      `Lote “${result.batch}” borrado: ${result.files} ${result.files === 1 ? 'archivo' : 'archivos'}. Ya puedes subir otra carpeta.`,
      'success',
    );
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    setBusy(false);
  }
}

function downloadExport() {
  const { folder, scope, count } = exportSelection();
  if (!count) return;
  const params = new URLSearchParams({ scope });
  if (folder !== ALL_BATCHES) params.set('folder', folder);
  showToast(`Preparando el ZIP con ${count} ${count === 1 ? 'archivo' : 'archivos'}…`);
  window.location.assign(`/api/export?${params.toString()}`);
}

function resetOcrPanels() {
  elements.confidenceCard.hidden = true;
  elements.candidateSection.hidden = true;
  elements.cropSection.hidden = true;
  elements.candidateList.innerHTML = '';
  elements.cropList.innerHTML = '';
}

function renderOcrResult(result) {
  elements.confidenceCard.hidden = false;
  elements.confidenceValue.textContent = `${Math.round(result.confidence || 0)}%`;
  elements.confidenceCard.classList.toggle('danger', Boolean(result.needs_review));
  elements.confidenceMessage.textContent = result.needs_review
    ? 'OCR dudoso: corrige el texto comparandolo letra por letra antes de aprobar.'
    : 'La lectura parece consistente, pero confirma siempre contra la imagen.';
  elements.nameInput.value = result.joined_text || '';
  updateFilenamePreview();

  const candidates = new Map();
  if (result.joined_text) candidates.set(result.joined_text, { text: result.joined_text, confidence: result.confidence, variant: 'Resultado unido' });
  if (result.regions.length === 1) {
    result.regions[0].alternatives.forEach((candidate) => {
      const flattened = candidate.text.replace(/\s+/g, ' ').trim();
      if (flattened && !candidates.has(flattened)) {
        candidates.set(flattened, { ...candidate, text: flattened });
      }
    });
  }

  elements.candidateList.innerHTML = '';
  [...candidates.values()].slice(0, 8).forEach((candidate) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'candidate';
    const text = document.createElement('span');
    text.className = 'candidate-text';
    text.textContent = candidate.text;
    const meta = document.createElement('span');
    meta.className = 'candidate-meta';
    meta.textContent = `${Math.round(candidate.confidence || 0)}% · ${candidate.variant || 'OCR'}`;
    button.append(text, meta);
    button.addEventListener('click', () => {
      elements.nameInput.value = candidate.text.replace(/\s+/g, ' ').trim();
      updateFilenamePreview();
    });
    elements.candidateList.appendChild(button);
  });
  elements.candidateSection.hidden = candidates.size === 0;

  elements.cropList.innerHTML = '';
  result.regions.forEach((region, index) => {
    const card = document.createElement('div');
    card.className = 'crop-card';
    const label = document.createElement('div');
    label.className = 'crop-label';
    label.textContent = `Selección ${index + 1} · página ${region.page}`;
    const originalBlock = document.createElement('div');
    originalBlock.className = 'crop-image-block';
    const originalCaption = document.createElement('span');
    originalCaption.textContent = 'Original';
    const originalImage = document.createElement('img');
    originalImage.src = `data:image/png;base64,${region.preview_original}`;
    originalImage.alt = `Recorte original ${index + 1}`;
    originalBlock.append(originalCaption, originalImage);

    const enhancedBlock = document.createElement('div');
    enhancedBlock.className = 'crop-image-block';
    const enhancedCaption = document.createElement('span');
    enhancedCaption.textContent = 'Contraste mejorado';
    const enhancedImage = document.createElement('img');
    enhancedImage.src = `data:image/png;base64,${region.preview_enhanced}`;
    enhancedImage.alt = `Recorte mejorado ${index + 1}`;
    enhancedBlock.append(enhancedCaption, enhancedImage);

    const reading = document.createElement('div');
    reading.className = 'crop-reading';
    reading.textContent = `OCR: ${region.best.text.replace(/\s+/g, ' ').trim()} · ${Math.round(region.best.confidence || 0)}%`;
    card.append(label, originalBlock, enhancedBlock, reading);
    elements.cropList.appendChild(card);
  });
  elements.cropSection.hidden = result.regions.length === 0;
}

async function runOcr() {
  if (!state.currentDocument || !state.selections.length || state.busy) return;
  try {
    setBusy(true, 'Procesando únicamente las zonas seleccionadas…');
    const result = await request(`/api/documents/${state.currentDocument.id}/ocr`, {
      method: 'POST',
      body: JSON.stringify({ selections: state.selections }),
    });
    state.ocrResult = result;
    renderOcrResult(result);
    showToast('OCR terminado. Revisa el recorte y corrige lo necesario.', 'success');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    setBusy(false);
  }
}

async function approveCurrent() {
  const name = elements.nameInput.value.trim();
  if (!state.currentDocument || !name || state.busy) return;
  const currentId = state.currentDocument.id;
  try {
    setBusy(true);
    const result = await request(`/api/documents/${currentId}/approve`, {
      method: 'POST',
      body: JSON.stringify({
        name,
        ocr_text: state.ocrResult?.joined_text || state.currentDocument.ocr_text || null,
        selections: state.selections,
      }),
    });
    await loadDocuments({ advanceFrom: currentId });
    if (state.counts.pending) {
      showToast(`Renombrado: ${result.filename}. Siguiente pendiente listo.`, 'success');
    } else {
      showToast(`Renombrado: ${result.filename}. No quedan pendientes: ya puedes descargar el ZIP.`, 'success');
    }
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    setBusy(false);
  }
}

async function skipCurrent() {
  if (!state.currentDocument || state.busy) return;
  const currentId = state.currentDocument.id;
  try {
    setBusy(true);
    await request(`/api/documents/${currentId}/skip`, { method: 'POST' });
    await loadDocuments({ advanceFrom: currentId });
    showToast('Documento omitido. Puedes volver a él desde la cola.', 'success');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    setBusy(false);
  }
}

async function syncFolder() {
  try {
    setBusy(true);
    const result = await request('/api/sync', { method: 'POST' });
    await loadDocuments();
    showToast(`Carpeta actualizada: ${result.added} nuevos, ${result.missing} faltantes.`, 'success');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    setBusy(false);
  }
}

async function undoLast() {
  try {
    setBusy(true);
    const result = await request('/api/undo-last', { method: 'POST' });
    await loadDocuments({ preferredId: result.document_id });
    showToast(`Restaurado: ${result.restored}`, 'success');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    setBusy(false);
  }
}

function showUploadProgress(ratio, label) {
  elements.uploadProgress.hidden = false;
  elements.uploadProgressFill.style.width = `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`;
  elements.uploadProgressLabel.textContent = label;
}

function hideUploadProgress() {
  elements.uploadProgress.hidden = true;
  elements.uploadProgressFill.style.width = '0%';
}

function groupUploads(items) {
  const groups = [];
  let current = [];
  let currentBytes = 0;
  items.forEach((item) => {
    const size = item.file.size || 0;
    const full = current.length >= UPLOAD_MAX_FILES_PER_REQUEST
      || (current.length && currentBytes + size > UPLOAD_MAX_BYTES_PER_REQUEST);
    if (full) {
      groups.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(item);
    currentBytes += size;
  });
  if (current.length) groups.push(current);
  return groups;
}

function sendUpload(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress(event.loaded);
    });
    xhr.addEventListener('load', () => {
      let payload = null;
      try { payload = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(payload || {});
      else reject(new Error(payload?.detail || `Error ${xhr.status} al subir`));
    });
    xhr.addEventListener('error', () => reject(new Error('Se interrumpió la conexión durante la subida')));
    xhr.addEventListener('abort', () => reject(new Error('Subida cancelada')));
    xhr.send(form);
  });
}

function collectFromInput(fileList) {
  const items = [];
  let folder = null;
  [...fileList].forEach((file) => {
    const relativePath = file.webkitRelativePath || '';
    if (!relativePath) {
      items.push({ file, relative: file.name });
      return;
    }
    const parts = relativePath.split('/');
    if (folder === null) folder = parts[0];
    items.push({ file, relative: parts.slice(1).join('/') || file.name });
  });
  return { items, folder };
}

function readEntries(reader) {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
}

async function walkDirectory(entry, prefix, items) {
  const reader = entry.createReader();
  for (;;) {
    const batch = await readEntries(reader);
    if (!batch.length) return;
    for (const child of batch) await walkEntry(child, prefix, items);
  }
}

async function walkEntry(entry, prefix, items) {
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    items.push({ file, relative: `${prefix}${file.name}` });
    return;
  }
  if (entry.isDirectory) await walkDirectory(entry, `${prefix}${entry.name}/`, items);
}

// Las entradas del DataTransfer se invalidan al terminar el manejador, así que
// se leen de forma síncrona antes del primer await.
async function collectFromDrop(dataTransfer) {
  const entries = [...(dataTransfer.items || [])]
    .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
    .filter(Boolean);
  const looseFiles = [...(dataTransfer.files || [])];
  if (!entries.length) {
    return { items: looseFiles.map((file) => ({ file, relative: file.name })), folder: null };
  }
  const items = [];
  let folder = null;
  for (const entry of entries) {
    if (entry.isDirectory && folder === null) {
      folder = entry.name;
      await walkDirectory(entry, '', items);
    } else {
      await walkEntry(entry, '', items);
    }
  }
  return { items, folder };
}

async function uploadItems(items, folderName) {
  if (state.uploading) return;
  const pdfItems = items.filter((item) => /\.pdf$/i.test(item.relative));
  const ignored = items.length - pdfItems.length;
  if (!pdfItems.length) {
    showToast('No encontré archivos .pdf en lo que seleccionaste.', 'error');
    return;
  }

  // The server refuses an oversized request before reading it, so files over the limit
  // are left out here instead of aborting the rest of the folder halfway through.
  const limit = state.maxUploadBytes;
  const limitLabel = limit ? `${Math.floor(limit / (1024 * 1024))} MB` : '';
  const oversized = limit ? pdfItems.filter((item) => item.file.size > limit) : [];
  const sendable = pdfItems.filter((item) => !oversized.includes(item));
  if (!sendable.length) {
    showToast(`Ningún PDF entra en el límite de ${limitLabel} por archivo.`, 'error');
    return;
  }

  const groups = groupUploads(sendable);
  const totalBytes = sendable.reduce((sum, item) => sum + (item.file.size || 0), 0);
  let uploadedBytes = 0;
  let batch = null;
  let saved = 0;
  const rejected = oversized.map((item) => ({ name: item.relative, reason: `Supera el límite de ${limitLabel}` }));
  let completed = false;

  state.uploading = true;
  setBusy(true);
  showUploadProgress(0, `Subiendo ${sendable.length} archivos…`);
  try {
    for (const group of groups) {
      const form = new FormData();
      if (batch) form.append('batch', batch);
      else if (folderName) form.append('folder', folderName);
      group.forEach((item) => form.append('files', item.file, item.relative));

      const groupBytes = group.reduce((sum, item) => sum + (item.file.size || 0), 0);
      const result = await sendUpload(form, (loaded) => {
        const ratio = totalBytes ? (uploadedBytes + Math.min(loaded, groupBytes)) / totalBytes : 0;
        showUploadProgress(ratio, `Subiendo ${Math.round(Math.min(1, ratio) * 100)}% de ${sendable.length} archivos`);
      });
      uploadedBytes += groupBytes;
      batch = result.batch || batch;
      saved += result.saved || 0;
      if (Array.isArray(result.rejected)) rejected.push(...result.rejected);
    }
    completed = true;
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    state.uploading = false;
    hideUploadProgress();
    setBusy(false);
  }

  if (!completed && !saved) return;
  await loadDocuments({ preferBatch: batch });
  const notes = [];
  if (rejected.length) notes.push(`${rejected.length} rechazados`);
  if (ignored) notes.push(`${ignored} no eran PDF`);
  showToast(
    `Se agregaron ${saved} PDF a “${batch}”${notes.length ? ` · ${notes.join(' · ')}` : ''}.`,
    rejected.length || ignored ? '' : 'success',
  );
  if (rejected.length) console.warn('Archivos rechazados por el servidor:', rejected);
}

function clearSelections() {
  state.selections = [];
  state.ocrResult = null;
  resetOcrPanels();
  redrawCanvas();
  updateControls();
}

function changePage(delta) {
  const next = Math.max(1, Math.min(state.pageCount, state.currentPage + delta));
  if (next === state.currentPage) return;
  state.currentPage = next;
  loadPage();
}

function changeDocument(delta) {
  const next = Math.max(0, Math.min(state.documents.length - 1, state.currentIndex + delta));
  if (next !== state.currentIndex) selectDocument(next);
}

elements.canvas.addEventListener('pointerdown', pointerDown);
elements.canvas.addEventListener('pointermove', pointerMove);
elements.canvas.addEventListener('pointerup', pointerUp);
elements.canvas.addEventListener('pointercancel', pointerUp);
elements.nameInput.addEventListener('input', updateFilenamePreview);
elements.zoomRange.addEventListener('input', () => {
  state.zoom = Number(elements.zoomRange.value) / 100;
  elements.zoomOutput.value = `${elements.zoomRange.value}%`;
  applyZoom();
});
elements.previousPage.addEventListener('click', () => changePage(-1));
elements.nextPage.addEventListener('click', () => changePage(1));
elements.previousDocument.addEventListener('click', () => changeDocument(-1));
elements.nextDocument.addEventListener('click', () => changeDocument(1));
elements.removeSelection.addEventListener('click', () => {
  state.selections.pop();
  state.ocrResult = null;
  resetOcrPanels();
  redrawCanvas();
  updateControls();
});
elements.clearSelections.addEventListener('click', clearSelections);
elements.ocrButton.addEventListener('click', runOcr);
elements.approveButton.addEventListener('click', approveCurrent);
elements.skipButton.addEventListener('click', skipCurrent);
elements.syncButton.addEventListener('click', syncFolder);
elements.undoButton.addEventListener('click', undoLast);

elements.uploadFolderButton.addEventListener('click', () => elements.folderInput.click());
elements.uploadFilesButton.addEventListener('click', () => elements.filesInput.click());
elements.folderInput.addEventListener('change', async () => {
  const { items, folder } = collectFromInput(elements.folderInput.files);
  elements.folderInput.value = '';
  await uploadItems(items, folder);
});
elements.filesInput.addEventListener('change', async () => {
  const { items, folder } = collectFromInput(elements.filesInput.files);
  elements.filesInput.value = '';
  await uploadItems(items, folder);
});
elements.exportFolder.addEventListener('change', updateExportControls);
elements.exportScope.addEventListener('change', updateExportControls);
elements.exportButton.addEventListener('click', downloadExport);
elements.clearBatchButton.addEventListener('click', openClearModal);
elements.clearCancel.addEventListener('click', closeClearModal);
elements.clearConfirm.addEventListener('click', confirmClearBatch);
elements.clearModal.addEventListener('click', (event) => {
  if (event.target === elements.clearModal) closeClearModal();
});

function dragCarriesFiles(dataTransfer) {
  return [...(dataTransfer?.types || [])].includes('Files');
}

window.addEventListener('dragenter', (event) => {
  if (!dragCarriesFiles(event.dataTransfer)) return;
  event.preventDefault();
  dragDepth += 1;
  elements.dropOverlay.hidden = false;
});
window.addEventListener('dragover', (event) => {
  if (dragCarriesFiles(event.dataTransfer)) event.preventDefault();
});
window.addEventListener('dragleave', (event) => {
  if (!dragCarriesFiles(event.dataTransfer)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) elements.dropOverlay.hidden = true;
});
window.addEventListener('drop', async (event) => {
  if (!dragCarriesFiles(event.dataTransfer)) return;
  event.preventDefault();
  dragDepth = 0;
  elements.dropOverlay.hidden = true;
  if (state.uploading) return;
  try {
    const { items, folder } = await collectFromDrop(event.dataTransfer);
    await uploadItems(items, folder);
  } catch (error) {
    showToast(`No pude leer la carpeta soltada: ${error.message}`, 'error');
  }
});

window.addEventListener('resize', redrawCanvas);
window.addEventListener('keydown', (event) => {
  if (state.uploading) return;
  // Con el diálogo de borrado abierto no debe dispararse ningún atajo detrás de él.
  if (state.modalOpen) {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeClearModal();
    }
    return;
  }
  const activeTag = window.document.activeElement?.tagName;
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(activeTag)
    || Boolean(window.document.activeElement?.isContentEditable);
  // Enter sobre un botón enfocado debe activar ese botón, no aprobar el documento.
  const activatable = ['BUTTON', 'A', 'SELECT', 'SUMMARY'].includes(activeTag);
  // Con Alt los atajos de navegación siguen funcionando sin salir del campo de nombre.
  const navigable = !typing || event.altKey;

  if (navigable && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
    event.preventDefault();
    changeDocument(event.key === 'ArrowLeft' ? -1 : 1);
    return;
  }
  if (navigable && ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown'].includes(event.key)) {
    event.preventDefault();
    changePage(['ArrowUp', 'PageUp'].includes(event.key) ? -1 : 1);
    return;
  }
  if (event.altKey && !event.ctrlKey && !event.metaKey) {
    // Alt + R/S para no tener que salir del campo de nombre, donde "r" y "s" son letras.
    if (event.key.toLowerCase() === 'r') {
      event.preventDefault();
      clearSelections();
      return;
    }
    if (event.key.toLowerCase() === 's') {
      event.preventDefault();
      skipCurrent();
      return;
    }
  }
  if (event.ctrlKey || event.metaKey) {
    // Dentro del campo de nombre, Ctrl+Z deshace el texto; Ctrl+Alt+Z deshace el renombrado.
    if (navigable && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      undoLast();
    }
    return;
  }
  if (event.key === 'Enter' && !event.shiftKey && !activatable) {
    event.preventDefault();
    approveCurrent();
    return;
  }
  if (typing) return;
  if (event.key.toLowerCase() === 'r') {
    clearSelections();
  } else if (event.key.toLowerCase() === 's') {
    skipCurrent();
  }
});

async function loadConfig() {
  try {
    const config = await request('/api/config');
    state.maxUploadBytes = config.max_upload_bytes || null;
  } catch (_) {
    // Without the limit the server still refuses oversized uploads; they just aren't filtered here.
  }
}

loadConfig();
loadDocuments().catch((error) => showToast(error.message, 'error'));
