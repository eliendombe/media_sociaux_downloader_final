const API_BASE = window.location.origin;

const urlInput = document.getElementById('urlInput');
const qualitySelect = document.getElementById('qualitySelect');
const formatSelect = document.getElementById('formatSelect');
const startBtn = document.getElementById('startBtn');
const pauseBtn = document.getElementById('pauseBtn');
const cancelBtn = document.getElementById('cancelBtn');
const folderBtn = document.getElementById('folderBtn');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const statusMessage = document.getElementById('statusMessage');
const apiStatus = document.getElementById('apiStatus');
const videoTitle = document.getElementById('videoTitle');
const videoMeta = document.getElementById('videoMeta');
const authorName = document.getElementById('authorName');
const authorAvatar = document.getElementById('authorAvatar');
const thumbnailImg = document.getElementById('thumbnailImg');
const thumbnailPlaceholder = document.getElementById('thumbnailPlaceholder');
const watermarkBadge = document.getElementById('watermarkBadge');

let currentJobId = null;
let pollTimer = null;
let isPaused = false;
let analyzedUrl = null;

async function apiFetch(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
    });
    let data = null;
    const text = await res.text();
    if (text) {
        try {
            data = JSON.parse(text);
        } catch {
            data = { detail: text };
        }
    }
    if (!res.ok) {
        const detail = data?.detail;
        const msg = typeof detail === 'string' ? detail : JSON.stringify(detail) || res.statusText;
        throw new Error(msg);
    }
    return data;
}

function setStatus(msg, isError = false) {
    if (!msg) {
        statusMessage.hidden = true;
        return;
    }
    statusMessage.hidden = false;
    statusMessage.textContent = msg;
    statusMessage.classList.toggle('error', isError);
}

function setProgress(value, label) {
    const pct = Math.max(0, Math.min(100, value));
    progressBar.style.width = `${pct}%`;
    progressText.textContent = label ?? `${pct}%`;
    if (pct >= 100) {
        progressText.style.color = 'var(--success)';
    } else {
        progressText.style.color = 'var(--text-muted)';
    }
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
}

function updatePreview(info) {
    videoTitle.textContent = info.title || 'Sans titre';
    const parts = [];
    if (info.extractor) parts.push(info.extractor);
    if (info.duration) parts.push(formatDuration(info.duration));
    videoMeta.textContent = parts.length ? parts.join(' · ') : 'Vidéo détectée';
    authorName.textContent = info.uploader || '—';
    if (info.thumbnail) {
        thumbnailImg.src = info.thumbnail;
        thumbnailImg.hidden = false;
        thumbnailPlaceholder.hidden = true;
        authorAvatar.style.backgroundImage = `url(${info.thumbnail})`;
        authorAvatar.style.backgroundSize = 'cover';
    } else {
        thumbnailImg.hidden = true;
        thumbnailPlaceholder.hidden = false;
    }
    const q = qualitySelect.value;
    watermarkBadge.hidden = false;
    watermarkBadge.textContent = q === 'audio' ? 'Audio' : q.toUpperCase();
}

async function checkApi() {
    try {
        await apiFetch('/health');
        apiStatus.textContent = '● API';
        apiStatus.className = 'api-status online';
        apiStatus.title = 'API connectée';
        return true;
    } catch {
        apiStatus.textContent = '○ API';
        apiStatus.className = 'api-status offline';
        apiStatus.title = 'Lancez uvicorn sur le port 8000 et ouvrez http://127.0.0.1:8000';
        setStatus('API hors ligne — démarrez le serveur (voir console).', true);
        return false;
    }
}

async function analyzeUrl() {
    const url = urlInput.value.trim();
    if (!url) {
        setStatus('Collez une URL Facebook valide.', true);
        return null;
    }
    setStatus('Analyse en cours…');
    startBtn.disabled = true;
    try {
        const info = await apiFetch('/api/analyze', {
            method: 'POST',
            body: JSON.stringify({ url }),
        });
        analyzedUrl = url;
        updatePreview(info);
        setStatus('');
        return info;
    } catch (err) {
        setStatus(err.message, true);
        return null;
    } finally {
        startBtn.disabled = false;
    }
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

async function pollJob(jobId) {
    try {
        const job = await apiFetch(`/api/jobs/${jobId}`);
        setProgress(job.progress, job.message ? `${Math.round(job.progress)}% — ${job.message}` : undefined);

        if (job.status === 'completed') {
            stopPolling();
            setProgress(100, 'Fini');
            setStatus(job.filename ? `Enregistré : ${job.filename}` : 'Téléchargement terminé');
            currentJobId = null;
            startBtn.disabled = false;
            return;
        }
        if (job.status === 'error') {
            stopPolling();
            setStatus(job.error || 'Erreur', true);
            currentJobId = null;
            startBtn.disabled = false;
            return;
        }
        if (job.status === 'cancelled') {
            stopPolling();
            setProgress(0, '0%');
            setStatus('Annulé');
            currentJobId = null;
            startBtn.disabled = false;
        }
    } catch (err) {
        stopPolling();
        setStatus(err.message, true);
        startBtn.disabled = false;
    }
}

async function startDownload() {
    if (!(await checkApi())) return;

    const url = urlInput.value.trim();
    if (!url) {
        setStatus('URL requise.', true);
        return;
    }

    if (analyzedUrl !== url) {
        const info = await analyzeUrl();
        if (!info) return;
    }

    if (currentJobId) {
        setStatus('Un téléchargement est déjà en cours.', true);
        return;
    }

    const quality = qualitySelect.value;
    let format = formatSelect.value;
    if (quality === 'audio') format = 'mp3';

    setStatus('Démarrage du téléchargement…');
    startBtn.disabled = true;
    isPaused = false;

    try {
        const job = await apiFetch('/api/download', {
            method: 'POST',
            body: JSON.stringify({ url, quality, format }),
        });
        currentJobId = job.id;
        setProgress(job.progress || 0);
        stopPolling();
        pollTimer = setInterval(() => pollJob(currentJobId), 500);
    } catch (err) {
        setStatus(err.message, true);
        startBtn.disabled = false;
    }
}

qualitySelect.addEventListener('change', () => {
    if (qualitySelect.value === 'audio') formatSelect.value = 'mp3';
    if (!watermarkBadge.hidden) {
        watermarkBadge.textContent =
            qualitySelect.value === 'audio' ? 'Audio' : qualitySelect.value.toUpperCase();
    }
});

urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') analyzeUrl();
});

urlInput.addEventListener('blur', () => {
    const url = urlInput.value.trim();
    if (url && url !== analyzedUrl) analyzeUrl();
});

startBtn.addEventListener('click', startDownload);

pauseBtn.addEventListener('click', async () => {
    if (!currentJobId) return;
    try {
        if (!isPaused) {
            await apiFetch(`/api/jobs/${currentJobId}/pause`, { method: 'POST' });
            isPaused = true;
        } else {
            await apiFetch(`/api/jobs/${currentJobId}/resume`, { method: 'POST' });
            isPaused = false;
        }
        pauseBtn.style.borderColor = isPaused ? 'var(--primary)' : 'var(--border-color)';
        pauseBtn.style.color = isPaused ? 'var(--primary)' : 'var(--text-muted)';
    } catch (err) {
        setStatus(err.message, true);
    }
});

cancelBtn.addEventListener('click', async () => {
    stopPolling();
    if (currentJobId) {
        try {
            await apiFetch(`/api/jobs/${currentJobId}/cancel`, { method: 'POST' });
        } catch {
            /* ignore */
        }
        currentJobId = null;
    }
    isPaused = false;
    setProgress(0, '0%');
    setStatus('Annulé');
    startBtn.disabled = false;
    pauseBtn.style.borderColor = 'var(--border-color)';
    pauseBtn.style.color = 'var(--text-muted)';
});

folderBtn.addEventListener('click', async () => {
    if (!(await checkApi())) return;
    try {
        const [{ path }, files] = await Promise.all([
            apiFetch('/api/open-downloads-folder'),
            apiFetch('/api/downloads'),
        ]);
        if (files.length > 0) {
            window.open(`${API_BASE}${files[0].path}`, '_blank');
        }
        setStatus(`Dossier serveur : ${path}`);
    } catch (err) {
        setStatus(err.message, true);
    }
});

checkApi();
setProgress(0);
