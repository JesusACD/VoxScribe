const CLOUD_MODELS = {
  groq: [
    { value: "whisper-large-v3-turbo", label: "Whisper Large v3 Turbo (Rápido)" },
    { value: "whisper-large-v3", label: "Whisper Large v3 (Máxima precisión)" },
  ],
  openai: [
    { value: "whisper-1", label: "Whisper-1 (Oficial)" },
  ],
  custom: [
    { value: "whisper-1", label: "whisper-1" },
    { value: "whisper-large-v3-turbo", label: "whisper-large-v3-turbo" },
  ],
};

const state = {
  sourceTab: "youtube",
  selectedFile: null,
  engine: "local",
  viewMode: "segments",
  searchQuery: "",
  activeJobId: null,
  currentJob: null,
  eventSource: null,
  systemInfo: null,
};

// Elementos DOM
const hwBadge = document.getElementById("hwBadge");
const hwText = document.getElementById("hwText");
const urlInput = document.getElementById("urlInput");
const clearUrlBtn = document.getElementById("clearUrlBtn");
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const dropzoneTitle = document.getElementById("dropzoneTitle");
const dropzoneSub = document.getElementById("dropzoneSub");

const localOptions = document.getElementById("localOptions");
const cloudOptions = document.getElementById("cloudOptions");
const localModel = document.getElementById("localModel");
const deviceSelect = document.getElementById("deviceSelect");
const vadCheckbox = document.getElementById("vadCheckbox");

const cloudProvider = document.getElementById("cloudProvider");
const cloudModel = document.getElementById("cloudModel");
const customBaseUrlWrap = document.getElementById("customBaseUrlWrap");
const customBaseUrl = document.getElementById("customBaseUrl");
const apiKeyInput = document.getElementById("apiKeyInput");
const toggleKeyBtn = document.getElementById("toggleKeyBtn");
const envKeyHint = document.getElementById("envKeyHint");

const languageSelect = document.getElementById("languageSelect");
const taskSelect = document.getElementById("taskSelect");
const startBtn = document.getElementById("startBtn");
const cancelBtn = document.getElementById("cancelBtn");

const historyList = document.getElementById("historyList");
const historyCount = document.getElementById("historyCount");

const emptyState = document.getElementById("emptyState");
const jobView = document.getElementById("jobView");
const progressBanner = document.getElementById("progressBanner");
const stageMessage = document.getElementById("stageMessage");
const progressPct = document.getElementById("progressPct");
const progressFill = document.getElementById("progressFill");
const firstModelTip = document.getElementById("firstModelTip");

const errorBanner = document.getElementById("errorBanner");
const errorText = document.getElementById("errorText");
const retryErrorBtn = document.getElementById("retryErrorBtn");
const retryToolbarBtn = document.getElementById("retryToolbarBtn");

const jobThumb = document.getElementById("jobThumb");
const jobTitle = document.getElementById("jobTitle");
const metaPills = document.getElementById("metaPills");
const notesBox = document.getElementById("notesBox");
const playerWrap = document.getElementById("playerWrap");
const audioPlayer = document.getElementById("audioPlayer");
const autoScrollAudio = document.getElementById("autoScrollAudio");

const searchInput = document.getElementById("searchInput");
const copyBtn = document.getElementById("copyBtn");
const copyBtnText = document.getElementById("copyBtnText");
const segmentsContainer = document.getElementById("segmentsContainer");
const proseContainer = document.getElementById("proseContainer");

// Utilidades de formato
function formatTime(secs) {
  const s = Math.max(0, Math.floor(secs || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rem = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(rem)}` : `${pad(m)}:${pad(rem)}`;
}

function formatBytes(bytes) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(0)} KB`;
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function highlightText(text, query) {
  const safe = escapeHtml(text);
  if (!query) return safe;
  const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(`(${escapedQuery})`, "gi");
  return safe.replace(regex, '<mark class="hl">$1</mark>');
}

// Inicialización de Hardware y Preferencias
async function initSystemInfo() {
  try {
    const res = await fetch("/api/system-info");
    const info = await res.json();
    state.systemInfo = info;

    if (info.cuda_available) {
      hwBadge.classList.add("gpu-ready");
      hwText.textContent = `GPU Activa: ${info.gpu_name || "NVIDIA CUDA"}`;
    } else if (info.gpu_name) {
      hwText.textContent = `${info.gpu_name} · Modo CPU`;
    } else {
      hwText.textContent = "Modo CPU Local";
      localModel.value = "small";
    }
    updateEnvKeyHint();
  } catch {
    hwText.textContent = "Servidor conectado";
  }
}

function populateCloudModels() {
  const prov = cloudProvider.value;
  const models = CLOUD_MODELS[prov] || CLOUD_MODELS.groq;
  cloudModel.innerHTML = models
    .map((m) => `<option value="${m.value}">${m.label}</option>`)
    .join("");

  customBaseUrlWrap.classList.toggle("hidden", prov !== "custom");

  // Cargar API key guardada en navegador para ese proveedor
  const savedKey = localStorage.getItem(`voxscribe_key_${prov}`) || "";
  apiKeyInput.value = savedKey;
  updateEnvKeyHint();
}

function updateEnvKeyHint() {
  if (!state.systemInfo) return;
  const prov = cloudProvider.value;
  const hasEnv =
    (prov === "groq" && state.systemInfo.has_env_groq_key) ||
    (prov === "openai" && state.systemInfo.has_env_openai_key);
  envKeyHint.classList.toggle("hidden", !hasEnv);
}

// Eventos de Pestañas y Controles
document.querySelectorAll("[data-source-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.sourceTab = btn.dataset.sourceTab;
    document.querySelectorAll("[data-source-tab]").forEach((b) =>
      b.classList.toggle("active", b === btn)
    );
    document
      .getElementById("paneYoutube")
      .classList.toggle("hidden", state.sourceTab !== "youtube");
    document
      .getElementById("paneFile")
      .classList.toggle("hidden", state.sourceTab !== "file");
  });
});

urlInput.addEventListener("input", () => {
  clearUrlBtn.classList.toggle("hidden", !urlInput.value);
});

clearUrlBtn.addEventListener("click", () => {
  urlInput.value = "";
  clearUrlBtn.classList.add("hidden");
  urlInput.focus();
});

// Drag & Drop Archivo
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});

["dragenter", "dragover"].forEach((ev) => {
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
});

["dragleave", "drop"].forEach((ev) => {
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  });
});

dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer?.files?.[0];
  if (file) selectFile(file);
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (file) selectFile(file);
});

function selectFile(file) {
  state.selectedFile = file;
  dropzone.classList.add("has-file");
  dropzoneTitle.textContent = file.name;
  dropzoneSub.textContent = `${formatBytes(file.size)} · Haz clic para cambiar archivo`;
}

// Motor Local vs Cloud
document.querySelectorAll("#engineSelector .seg-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.engine = btn.dataset.engine;
    document
      .querySelectorAll("#engineSelector .seg-btn")
      .forEach((b) => b.classList.toggle("active", b === btn));
    localOptions.classList.toggle("hidden", state.engine !== "local");
    cloudOptions.classList.toggle("hidden", state.engine !== "cloud");
  });
});

cloudProvider.addEventListener("change", populateCloudModels);

apiKeyInput.addEventListener("input", () => {
  const prov = cloudProvider.value;
  localStorage.setItem(`voxscribe_key_${prov}`, apiKeyInput.value.trim());
});

toggleKeyBtn.addEventListener("click", () => {
  const isPass = apiKeyInput.type === "password";
  apiKeyInput.type = isPass ? "text" : "password";
  toggleKeyBtn.textContent = isPass ? "Ocultar" : "Mostrar";
});

// Iniciar Transcripción
startBtn.addEventListener("click", startTranscription);

async function startTranscription() {
  const isLocal = state.engine === "local";
  const model = isLocal ? localModel.value : cloudModel.value;
  const provider = cloudProvider.value;
  const language = languageSelect.value;
  const device = deviceSelect.value;
  const vadFilter = vadCheckbox.checked;
  const task = taskSelect.value;
  const apiKey = apiKeyInput.value.trim();
  const baseUrl = customBaseUrl.value.trim();

  if (state.sourceTab === "youtube") {
    const url = urlInput.value.trim();
    if (!url) {
      urlInput.focus();
      alert("Por favor pega el enlace del video de YouTube o audio.");
      return;
    }

    setBusyUI(true);
    try {
      const res = await fetch("/api/transcribe/url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          engine: state.engine,
          provider,
          model,
          language,
          device,
          vad_filter: vadFilter,
          task,
          api_key: apiKey || null,
          base_url: provider === "custom" ? baseUrl || null : null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "No se pudo iniciar el trabajo.");
      }
      const job = await res.json();
      openJob(job, true);
      loadHistory();
    } catch (err) {
      setBusyUI(false);
      alert(err.message);
    }
  } else {
    if (!state.selectedFile) {
      alert("Por favor selecciona o arrastra un archivo de audio o video.");
      return;
    }

    setBusyUI(true);
    const form = new FormData();
    form.append("file", state.selectedFile);
    form.append("engine", state.engine);
    form.append("provider", provider);
    form.append("model", model);
    form.append("language", language);
    form.append("device", device);
    form.append("vad_filter", String(vadFilter));
    form.append("task", task);
    if (apiKey) form.append("api_key", apiKey);
    if (provider === "custom" && baseUrl) form.append("base_url", baseUrl);

    try {
      emptyState.classList.add("hidden");
      jobView.classList.remove("hidden");
      progressBanner.classList.remove("hidden");
      stageMessage.textContent = "Subiendo archivo al servidor local...";
      progressPct.textContent = "";
      progressFill.style.width = "4%";

      const res = await fetch("/api/transcribe/file", {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error al subir el archivo.");
      }
      const job = await res.json();
      openJob(job, true);
      loadHistory();
    } catch (err) {
      setBusyUI(false);
      alert(err.message);
    }
  }
}

cancelBtn.addEventListener("click", async () => {
  if (!state.activeJobId) return;
  await fetch(`/api/jobs/${state.activeJobId}/cancel`, { method: "POST" });
});

async function retryActiveJob() {
  if (!state.activeJobId) return;
  const isLocal = state.engine === "local";
  const model = isLocal ? localModel.value : cloudModel.value;
  const provider = cloudProvider.value;
  const language = languageSelect.value;
  const device = deviceSelect.value;
  const vadFilter = vadCheckbox.checked;
  const task = taskSelect.value;
  const apiKey = apiKeyInput.value.trim();
  const baseUrl = customBaseUrl.value.trim();

  setBusyUI(true);
  try {
    const res = await fetch(`/api/jobs/${state.activeJobId}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        engine: state.engine,
        provider,
        model,
        language,
        device,
        vad_filter: vadFilter,
        task,
        api_key: apiKey || null,
        base_url: provider === "custom" ? baseUrl || null : null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "No se pudo reintentar.");
    }
    const updated = await res.json();
    openJob(updated, true);
    loadHistory();
  } catch (err) {
    setBusyUI(false);
    alert(err.message);
  }
}

retryErrorBtn?.addEventListener("click", retryActiveJob);
retryToolbarBtn?.addEventListener("click", retryActiveJob);

function setBusyUI(isBusy) {
  startBtn.disabled = isBusy;
  cancelBtn.classList.toggle("hidden", !isBusy);
}

// Gestión de Vista de Trabajo y SSE
function closeEventSource() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function openJob(job, subscribeLive = false) {
  closeEventSource();
  state.activeJobId = job.id;
  state.currentJob = { ...job, segments: job.segments ? [...job.segments] : [] };

  emptyState.classList.add("hidden");
  jobView.classList.remove("hidden");

  // Reset reproductor hasta que haya archivo listo
  audioPlayer.pause();
  audioPlayer.removeAttribute("src");
  playerWrap.classList.add("hidden");

  renderJobHeader();
  renderTranscriptFull();
  updateJobStatusBanner();
  highlightActiveHistoryItem();

  const isActive = ["queued", "downloading", "preparing", "transcribing"].includes(
    job.status
  );
  setBusyUI(isActive);

  if (subscribeLive || isActive) {
    subscribeToJobEvents(job.id);
  }
}

function subscribeToJobEvents(jobId) {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  state.eventSource = es;

  es.addEventListener("snapshot", (ev) => {
    const snap = JSON.parse(ev.data);
    state.currentJob = snap;
    renderJobHeader();
    renderTranscriptFull();
    updateJobStatusBanner();
  });

  es.addEventListener("status", (ev) => {
    const data = JSON.parse(ev.data);
    if (!state.currentJob) return;
    Object.assign(state.currentJob, data);
    renderJobHeader();
    updateJobStatusBanner();

    if (["completed", "error", "cancelled"].includes(data.status)) {
      setBusyUI(false);
      closeEventSource();
      loadHistory();
      renderTranscriptFull();
    }
  });

  es.addEventListener("segment", (ev) => {
    const { segment, progress, stage_message } = JSON.parse(ev.data);
    if (!state.currentJob) return;

    // Evitar duplicados si ya llegó en snapshot
    const exists = state.currentJob.segments.some((s) => s.id === segment.id);
    if (!exists) {
      state.currentJob.segments.push(segment);
      appendSegmentDOM(segment);
      if (state.viewMode === "prose") {
        renderProseView();
      }
    }
    if (typeof progress === "number") state.currentJob.progress = progress;
    if (stage_message) state.currentJob.stage_message = stage_message;
    updateJobStatusBanner();
  });

  es.addEventListener("note", (ev) => {
    const { note } = JSON.parse(ev.data);
    if (!state.currentJob) return;
    state.currentJob.notes = state.currentJob.notes || [];
    state.currentJob.notes.push(note);
    renderJobHeader();
  });

  es.onerror = () => {
    // Verificar estado final por HTTP si SSE se cierra
    fetch(`/api/jobs/${jobId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (j && ["completed", "error", "cancelled"].includes(j.status)) {
          state.currentJob = j;
          setBusyUI(false);
          closeEventSource();
          renderJobHeader();
          renderTranscriptFull();
          updateJobStatusBanner();
          loadHistory();
        }
      })
      .catch(() => {});
  };
}

function updateJobStatusBanner() {
  const job = state.currentJob;
  if (!job) return;

  const isRunning = ["queued", "downloading", "preparing", "transcribing"].includes(
    job.status
  );
  progressBanner.classList.toggle("hidden", !isRunning);
  firstModelTip.classList.toggle(
    "hidden",
    !(job.engine === "local" && job.status === "preparing")
  );

  if (isRunning) {
    stageMessage.textContent = job.stage_message || "Procesando...";
    const pct = job.progress ?? 0;
    progressPct.textContent = `${pct}%`;
    progressFill.style.width = `${pct}%`;
  }

  const hasError = job.status === "error";
  errorBanner.classList.toggle("hidden", !hasError);
  if (hasError) {
    errorText.textContent = job.error || "Ocurrió un error inesperado.";
  }
}

function renderJobHeader() {
  const job = state.currentJob;
  if (!job) return;

  jobTitle.textContent = job.title || "Transcripción";

  if (job.thumbnail) {
    jobThumb.src = job.thumbnail;
    jobThumb.classList.remove("hidden");
  } else {
    jobThumb.classList.add("hidden");
  }

  const pills = [];
  if (job.channel) pills.push(`<span class="pill">${escapeHtml(job.channel)}</span>`);
  if (job.duration) pills.push(`<span class="pill">Duración: ${formatTime(job.duration)}</span>`);
  const lang = job.detected_language || (job.language !== "auto" ? job.language : null);
  if (lang) pills.push(`<span class="pill accent">Idioma: ${escapeHtml(lang.toUpperCase())}</span>`);
  if (job.model) pills.push(`<span class="pill">Modelo: ${escapeHtml(job.model)}</span>`);
  if (job.device_used) pills.push(`<span class="pill">${escapeHtml(job.device_used)}</span>`);
  if (job.elapsed_seconds) pills.push(`<span class="pill">Listo en ${job.elapsed_seconds}s</span>`);
  metaPills.innerHTML = pills.join("");

  if (job.notes && job.notes.length > 0) {
    notesBox.textContent = job.notes.join(" · ");
    notesBox.classList.remove("hidden");
  } else {
    notesBox.classList.add("hidden");
  }

  // Configurar reproductor cuando el archivo de audio ya esté disponible
  if (job.audio_filename) {
    const expectedSrc = `/api/jobs/${job.id}/audio`;
    if (!audioPlayer.getAttribute("src") || !audioPlayer.getAttribute("src").includes(job.id)) {
      audioPlayer.src = expectedSrc;
    }
    playerWrap.classList.remove("hidden");
  }
}

function renderTranscriptFull() {
  segmentsContainer.innerHTML = "";
  const job = state.currentJob;
  if (!job) return;

  const q = state.searchQuery.trim().toLowerCase();
  const segs = job.segments || [];

  const filtered = q
    ? segs.filter((s) => s.text.toLowerCase().includes(q))
    : segs;

  if (filtered.length === 0) {
    if (segs.length === 0 && ["queued", "downloading", "preparing", "transcribing"].includes(job.status)) {
      segmentsContainer.innerHTML = `<p class="empty-small">Los segmentos aparecerán aquí en tiempo real apenas comience la voz...</p>`;
    } else if (q) {
      segmentsContainer.innerHTML = `<p class="empty-small">No se encontraron coincidencias para "${escapeHtml(state.searchQuery)}".</p>`;
    } else if (job.status === "completed") {
      segmentsContainer.innerHTML = `<p class="empty-small">No se detectó voz en el audio.</p>`;
    }
  } else {
    for (const seg of filtered) {
      appendSegmentDOM(seg);
    }
  }

  renderProseView();
}

function appendSegmentDOM(seg) {
  const q = state.searchQuery.trim();
  if (q && !seg.text.toLowerCase().includes(q.toLowerCase())) {
    return;
  }

  // Quitar placeholder si existía
  const placeholder = segmentsContainer.querySelector(".empty-small");
  if (placeholder) placeholder.remove();

  const row = document.createElement("div");
  row.className = "segment-row";
  row.dataset.segId = seg.id;
  row.dataset.start = seg.start;
  row.dataset.end = seg.end;
  row.title = "Haz clic para escuchar desde este instante";

  row.innerHTML = `
    <div class="seg-time">[${formatTime(seg.start)}]</div>
    <div class="seg-text">${highlightText(seg.text, q)}</div>
  `;

  row.addEventListener("click", () => {
    if (!audioPlayer.src) return;
    audioPlayer.currentTime = seg.start;
    audioPlayer.play().catch(() => {});
  });

  segmentsContainer.appendChild(row);
}

function renderProseView() {
  const job = state.currentJob;
  if (!job) return;
  const fullText = (job.segments || []).map((s) => s.text.trim()).join(" ");
  proseContainer.innerHTML = fullText
    ? highlightText(fullText, state.searchQuery.trim())
    : `<span class="empty-small">Sin texto disponible aún.</span>`;
}

// Sincronización en vivo Reproductor -> Segmento Activo
audioPlayer.addEventListener("timeupdate", () => {
  const t = audioPlayer.currentTime;
  const rows = segmentsContainer.querySelectorAll(".segment-row");
  let activeRow = null;

  rows.forEach((row) => {
    const start = parseFloat(row.dataset.start);
    const end = parseFloat(row.dataset.end);
    const isPlaying = t >= start && t <= end + 0.25;
    row.classList.toggle("playing", isPlaying);
    if (isPlaying) activeRow = row;
  });

  if (activeRow && autoScrollAudio.checked && !audioPlayer.paused && state.viewMode === "segments") {
    activeRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});

// Cambio de vista Segmentos / Texto continuo y Búsqueda
document.querySelectorAll("#viewModeSelector .seg-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.viewMode = btn.dataset.view;
    document
      .querySelectorAll("#viewModeSelector .seg-btn")
      .forEach((b) => b.classList.toggle("active", b === btn));
    segmentsContainer.classList.toggle("hidden", state.viewMode !== "segments");
    proseContainer.classList.toggle("hidden", state.viewMode !== "prose");
  });
});

searchInput.addEventListener("input", () => {
  state.searchQuery = searchInput.value;
  renderTranscriptFull();
});

// Copiar al portapapeles
copyBtn.addEventListener("click", async () => {
  const job = state.currentJob;
  if (!job || !job.segments?.length) return;

  const text =
    state.viewMode === "segments"
      ? job.segments
          .map((s) => `[${formatTime(s.start)} - ${formatTime(s.end)}] ${s.text}`)
          .join("\n")
      : job.segments.map((s) => s.text.trim()).join(" ");

  await navigator.clipboard.writeText(text);
  copyBtnText.textContent = "¡Copiado!";
  setTimeout(() => {
    copyBtnText.textContent = "Copiar";
  }, 1800);
});

// Botones de Exportación (TXT, TXT+Tiempo, SRT, VTT, JSON)
document.querySelectorAll(".export-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (!state.activeJobId) return;
    const fmt = btn.dataset.fmt;
    window.location.href = `/api/jobs/${state.activeJobId}/export?fmt=${fmt}`;
  });
});

// Historial
async function loadHistory() {
  try {
    const res = await fetch("/api/jobs");
    const data = await res.json();
    const jobs = data.jobs || [];
    historyCount.textContent = String(jobs.length);

    if (jobs.length === 0) {
      historyList.innerHTML = `<p class="empty-small">Tus transcripciones aparecerán aquí.</p>`;
      return;
    }

    historyList.innerHTML = "";
    for (const item of jobs) {
      const div = document.createElement("div");
      div.className = `history-item ${item.id === state.activeJobId ? "active" : ""}`;
      div.dataset.jobId = item.id;

      const statusMap = {
        completed: "Completado",
        transcribing: "Transcribiendo...",
        downloading: "Descargando...",
        preparing: "Preparando...",
        error: "Error",
        cancelled: "Cancelado",
      };
      const statusLabel = statusMap[item.status] || item.status;
      const durStr = item.duration ? ` · ${formatTime(item.duration)}` : "";

      div.innerHTML = `
        <div class="history-main">
          <div class="history-title">${escapeHtml(item.title)}</div>
          <div class="history-sub">
            <span>${statusLabel}${durStr}</span>
          </div>
        </div>
        <button type="button" class="del-job-btn" title="Eliminar">&times;</button>
      `;

      div.addEventListener("click", async (e) => {
        if (e.target.closest(".del-job-btn")) return;
        const r = await fetch(`/api/jobs/${item.id}`);
        if (r.ok) {
          const fullJob = await r.json();
          openJob(fullJob, false);
        }
      });

      div.querySelector(".del-job-btn").addEventListener("click", async (e) => {
        e.stopPropagation();
        await fetch(`/api/jobs/${item.id}`, { method: "DELETE" });
        if (state.activeJobId === item.id) {
          closeEventSource();
          state.activeJobId = null;
          state.currentJob = null;
          jobView.classList.add("hidden");
          emptyState.classList.remove("hidden");
        }
        loadHistory();
      });

      historyList.appendChild(div);
    }
  } catch {
    // Silencioso
  }
}

function highlightActiveHistoryItem() {
  document.querySelectorAll(".history-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.jobId === state.activeJobId);
  });
}

// Arranque inicial
populateCloudModels();
initSystemInfo();
loadHistory();
