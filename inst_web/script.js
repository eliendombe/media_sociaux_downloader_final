const API_BASE = window.location.protocol === 'file:'
    ? 'http://localhost:8000'
    : window.location.origin;


const urlInput = document.getElementById('urlInput');
const startBtn = document.getElementById('startBtn');
const pauseBtn = document.getElementById('pauseBtn');
const cancelBtn = document.getElementById('cancelBtn');
const folderBtn = document.getElementById('folderBtn');
const qualitySelect = document.getElementById('qualitySelect');
const formatSelect = document.getElementById('formatSelect');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const videoTitle = document.getElementById('videoTitle');
const authorName = document.getElementById('authorName');
const qualityBadge = document.getElementById('qualityBadge');
const previewThumbnail = document.getElementById('previewThumbnail');
const thumbnailPlaceholder = document.getElementById('thumbnailPlaceholder');
const authorAvatar = document.getElementById('authorAvatar');
const authorAvatarPlaceholder = document.getElementById('authorAvatarPlaceholder');

let currentTaskId = null;
let pollInterval = null;
let isPaused = false;
let lastFilename = null;
let infoDebounce = null;

async function api(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        throw new Error(data.detail || `Erreur ${res.status}`);
    }
    return data;
}

function setProgress(value, label) {
    progressBar.style.width = `${value}%`;
    progressText.textContent = label ?? `${Math.round(value)}%`;
}

function resetProgressStyle() {
    progressText.style.color = 'var(--text-muted)';
}

function setControlsDownloading(active) {
    pauseBtn.disabled = !active;
    cancelBtn.disabled = !active;
    startBtn.disabled = active;
    urlInput.disabled = active;
    qualitySelect.disabled = active;
    formatSelect.disabled = active;
}

function resetPauseButton() {
    isPaused = false;
    pauseBtn.style.borderColor = 'var(--border-color)';
    pauseBtn.style.color = 'var(--text-muted)';
    pauseBtn.title = 'Pause';
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

function updatePreview(info) {
    videoTitle.textContent = info.title || 'Sans titre';

    const username = info.uploader_id || info.uploader || 'username';
    authorName.textContent = username.startsWith('@') ? username : `@${username}`;

    qualityBadge.textContent = info.is_video ? 'HD' : 'IMG';

    if (info.thumbnail) {
        previewThumbnail.src = info.thumbnail;
        previewThumbnail.hidden = false;
        thumbnailPlaceholder.hidden = true;
    } else {
        previewThumbnail.hidden = true;
        thumbnailPlaceholder.hidden = false;
    }

    if (info.thumbnail) {
        authorAvatar.src = info.thumbnail;
        authorAvatar.hidden = false;
        authorAvatarPlaceholder.hidden = true;
    } else {
        authorAvatar.hidden = true;
        authorAvatarPlaceholder.hidden = false;
    }
}

function clearPreview() {
    videoTitle.textContent = "Collez un lien pour voir l'aperçu";
    authorName.textContent = '@username';
    qualityBadge.textContent = '—';
    previewThumbnail.hidden = true;
    thumbnailPlaceholder.hidden = false;
    authorAvatar.hidden = true;
    authorAvatarPlaceholder.hidden = false;
}

async function fetchPreview() {
    const url = urlInput.value.trim();
    if (!url || !url.includes('instagram.com')) {
        clearPreview();
        return;
    }

    try {
        const info = await api('/api/info', {
            method: 'POST',
            body: JSON.stringify({ url }),
        });
        updatePreview(info);
    } catch (err) {
        clearPreview();
        videoTitle.textContent = err.message;
    }
}

async function startDownload() {
    const url = urlInput.value.trim();
    if (!url) {
        progressText.textContent = 'URL requise';
        progressText.style.color = 'var(--danger)';
        return;
    }

    stopPolling();
    resetPauseButton();
    setControlsDownloading(true);
    setProgress(0);
    resetProgressStyle();

    let quality = qualitySelect.value;
    let format = formatSelect.value;
    if (format === 'mp3') quality = 'audio';

    try {
        const task = await api('/api/download', {
            method: 'POST',
            body: JSON.stringify({ url, quality, format }),
        });

        currentTaskId = task.task_id;
        pollInterval = setInterval(pollStatus, 500);
        await pollStatus();
    } catch (err) {
        setControlsDownloading(false);
        setProgress(0, 'Erreur');
        progressText.style.color = 'var(--danger)';
        progressText.textContent = err.message;
    }
}

async function pollStatus() {
    if (!currentTaskId) return;

    try {
        const task = await api(`/api/download/${currentTaskId}`);

        if (task.status === 'paused') {
            setProgress(task.progress, 'Pause');
            progressText.style.color = 'var(--primary)';
            return;
        }

        if (task.status === 'downloading' || task.status === 'pending') {
            setProgress(task.progress);
            resetProgressStyle();
            return;
        }

        stopPolling();
        setControlsDownloading(false);
        currentTaskId = null;

        if (task.status === 'completed') {
            lastFilename = task.filename;
            setProgress(100, 'Fini');
            progressText.style.color = 'var(--success)';
            if (task.filename) {
                videoTitle.textContent = task.filename;
            }
            return;
        }

        if (task.status === 'cancelled') {
            setProgress(0, 'Annulé');
            resetProgressStyle();
            return;
        }

        if (task.status === 'error') {
            setProgress(task.progress, 'Erreur');
            progressText.style.color = 'var(--danger)';
            progressText.textContent = task.error || 'Erreur inconnue';
        }
    } catch (err) {
        stopPolling();
        setControlsDownloading(false);
        currentTaskId = null;
        progressText.style.color = 'var(--danger)';
        progressText.textContent = err.message;
    }
}

async function togglePause() {
    if (!currentTaskId) return;

    try {
        if (isPaused) {
            await api(`/api/download/${currentTaskId}/resume`, { method: 'POST' });
            isPaused = false;
            pauseBtn.style.borderColor = 'var(--border-color)';
            pauseBtn.style.color = 'var(--text-muted)';
            pauseBtn.title = 'Pause';
        } else {
            await api(`/api/download/${currentTaskId}/pause`, { method: 'POST' });
            isPaused = true;
            pauseBtn.style.borderColor = 'var(--primary)';
            pauseBtn.style.color = 'var(--primary)';
            pauseBtn.title = 'Reprendre';
        }
    } catch (err) {
        progressText.style.color = 'var(--danger)';
        progressText.textContent = err.message;
    }
}

async function cancelDownload() {
    if (!currentTaskId) return;

    try {
        await api(`/api/download/${currentTaskId}/cancel`, { method: 'POST' });
        stopPolling();
        setControlsDownloading(false);
        resetPauseButton();
        currentTaskId = null;
        setProgress(0, 'Annulé');
        resetProgressStyle();
    } catch (err) {
        progressText.style.color = 'var(--danger)';
        progressText.textContent = err.message;
    }
}

async function openFolder() {
    try {
        const { path } = await api('/api/downloads/folder');
        await navigator.clipboard.writeText(path);
        alert(`Chemin du dossier copié :\n${path}`);
    } catch {
        alert('Impossible de récupérer le chemin du dossier.');
    }

    if (lastFilename) {
        window.open(`${API_BASE}/api/downloads/file/${encodeURIComponent(lastFilename)}`, '_blank');
    }
}

urlInput.addEventListener('input', () => {
    clearTimeout(infoDebounce);
    infoDebounce = setTimeout(fetchPreview, 800);
});

urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') startDownload();
});

formatSelect.addEventListener('change', () => {
    if (formatSelect.value === 'mp3') qualitySelect.value = 'audio';
});

startBtn.addEventListener('click', startDownload);
pauseBtn.addEventListener('click', togglePause);
cancelBtn.addEventListener('click', cancelDownload);
folderBtn.addEventListener('click', openFolder);

setProgress(0);
