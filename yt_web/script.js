const API_BASE = 'http://localhost:8000';

const urlInput = document.getElementById('urlInput');
const startBtn = document.getElementById('startBtn');
const cancelBtn = document.getElementById('cancelBtn');
const folderBtn = document.getElementById('folderBtn');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const qualitySelect = document.getElementById('qualitySelect');
const formatSelect = document.getElementById('formatSelect');
const previewCard = document.getElementById('previewCard');
const thumbnailContainer = document.getElementById('thumbnailContainer');
const thumbnailImg = document.getElementById('thumbnailImg');
const thumbnailPlaceholder = document.getElementById('thumbnailPlaceholder');
const youtubePlayer = document.getElementById('youtubePlayer');
const overlayPlayBtn = document.getElementById('overlayPlayBtn');
const previewPlayBtn = document.getElementById('previewPlayBtn');
const previewPauseBtn = document.getElementById('previewPauseBtn');
const videoTitle = document.getElementById('videoTitle');
const channelName = document.getElementById('channelName');
const qualityBadge = document.getElementById('qualityBadge');
const statusMessage = document.getElementById('statusMessage');

let currentJobId = null;
let pollTimer = null;
let infoDebounce = null;
let isDownloading = false;
let currentVideoId = null;
let isPreviewPlaying = false;

const YT_URL_RE = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\//i;

function isYoutubeUrl(url) {
    return YT_URL_RE.test(url.trim());
}

function showStatus(text, type = 'error') {
    if (!text) {
        statusMessage.hidden = true;
        statusMessage.textContent = '';
        statusMessage.classList.remove('success');
        return;
    }
    statusMessage.hidden = false;
    statusMessage.textContent = text;
    statusMessage.classList.toggle('success', type === 'success');
}

async function apiFetch(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
    });
    let data = null;
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
        data = await res.json();
    }
    if (!res.ok) {
        const detail = data?.detail;
        const msg = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : `Erreur ${res.status}`;
        throw new Error(msg);
    }
    return data;
}

function setProgress(value, label) {
    const pct = Math.max(0, Math.min(100, value));
    progressBar.style.width = `${pct}%`;
    progressText.textContent = label ?? `${Math.round(pct)}%`;
    progressText.style.color = pct >= 100 ? 'var(--success)' : 'var(--text-muted)';
}

function setControlsDownloading(active) {
    isDownloading = active;
    startBtn.disabled = active;
    cancelBtn.disabled = !active;
    qualitySelect.disabled = active;
    formatSelect.disabled = active;
    urlInput.disabled = active;
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return ` · ${m}:${String(s).padStart(2, '0')}`;
}

function setPreviewControlsEnabled(enabled) {
    previewPlayBtn.disabled = !enabled || isPreviewPlaying;
    previewPauseBtn.disabled = !enabled || !isPreviewPlaying;
    overlayPlayBtn.hidden = !enabled;
}

function updateOverlayIcon() {
    const icon = overlayPlayBtn.querySelector('i');
    if (icon) {
        icon.className = isPreviewPlaying ? 'fas fa-pause' : 'fas fa-play';
    }
    overlayPlayBtn.title = isPreviewPlaying ? 'Pause' : 'Lecture';
    overlayPlayBtn.setAttribute('aria-label', overlayPlayBtn.title);
}

function stopPreviewPlayback() {
    youtubePlayer.innerHTML = '';
    youtubePlayer.hidden = true;
    isPreviewPlaying = false;
    previewCard.classList.remove('is-playing');

    if (thumbnailImg.src) {
        thumbnailImg.hidden = false;
        thumbnailPlaceholder.hidden = true;
    } else {
        thumbnailImg.hidden = true;
        thumbnailPlaceholder.hidden = false;
    }

    setPreviewControlsEnabled(!!currentVideoId);
    updateOverlayIcon();
}

function startPreviewPlayback() {
    if (!currentVideoId) return;

    const embedUrl = `https://www.youtube.com/embed/${encodeURIComponent(currentVideoId)}?autoplay=1&rel=0&modestbranding=1&playsinline=1`;
    youtubePlayer.innerHTML = `<iframe src="${embedUrl}" title="Aperçu YouTube" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
    youtubePlayer.hidden = false;
    thumbnailImg.hidden = true;
    thumbnailPlaceholder.hidden = true;

    isPreviewPlaying = true;
    previewCard.classList.add('is-playing');
    setPreviewControlsEnabled(true);
    updateOverlayIcon();
}

function togglePreviewPlayback() {
    if (isPreviewPlaying) {
        stopPreviewPlayback();
    } else {
        startPreviewPlayback();
    }
}

function updatePreview(info) {
    stopPreviewPlayback();
    currentVideoId = info.id || null;
    previewCard.classList.toggle('has-video', !!currentVideoId);

    videoTitle.textContent = info.title;
    channelName.textContent = info.channel + formatDuration(info.duration);

    const qLabel = qualitySelect.options[qualitySelect.selectedIndex].text;
    qualityBadge.textContent = qLabel;

    if (info.thumbnail) {
        thumbnailImg.src = info.thumbnail;
        thumbnailImg.alt = info.title;
        thumbnailImg.hidden = false;
        thumbnailPlaceholder.hidden = true;
    } else {
        thumbnailImg.hidden = true;
        thumbnailPlaceholder.hidden = false;
    }

    setPreviewControlsEnabled(!!currentVideoId);
    updateOverlayIcon();
}

function resetPreview() {
    stopPreviewPlayback();
    currentVideoId = null;
    previewCard.classList.remove('has-video');

    videoTitle.textContent = 'Collez un lien YouTube pour afficher l’aperçu';
    channelName.textContent = '—';
    qualityBadge.textContent = '—';
    thumbnailImg.hidden = true;
    thumbnailImg.removeAttribute('src');
    thumbnailPlaceholder.hidden = false;
    setPreviewControlsEnabled(false);
}

async function fetchVideoInfo() {
    const url = urlInput.value.trim();
    if (!isYoutubeUrl(url)) {
        resetPreview();
        return;
    }

    previewCard.classList.add('is-loading');
    showStatus('');

    try {
        const info = await apiFetch('/api/info', {
            method: 'POST',
            body: JSON.stringify({ url }),
        });
        updatePreview(info);
    } catch (err) {
        resetPreview();
        showStatus(err.message);
    } finally {
        previewCard.classList.remove('is-loading');
    }
}

function scheduleInfoFetch() {
    clearTimeout(infoDebounce);
    infoDebounce = setTimeout(fetchVideoInfo, 600);
}

function getDownloadPayload() {
    let quality = qualitySelect.value;
    let format = formatSelect.value;
    if (quality === 'audio') {
        format = 'mp3';
        formatSelect.value = 'mp3';
    }
    return { quality, format };
}

async function pollJob(jobId) {
    try {
        const job = await apiFetch(`/api/download/${jobId}`);
        setProgress(job.progress, job.message || `${Math.round(job.progress)}%`);

        if (job.status === 'completed') {
            stopPolling();
            setControlsDownloading(false);
            setProgress(100, 'Terminé');
            showStatus(job.filename ? `Fichier : ${job.filename}` : 'Téléchargement terminé', 'success');
            currentJobId = null;
            return;
        }

        if (job.status === 'error') {
            stopPolling();
            setControlsDownloading(false);
            showStatus(job.message || 'Erreur de téléchargement');
            currentJobId = null;
            return;
        }

        if (job.status === 'cancelled') {
            stopPolling();
            setControlsDownloading(false);
            setProgress(0, '0%');
            showStatus('Téléchargement annulé');
            currentJobId = null;
        }
    } catch (err) {
        stopPolling();
        setControlsDownloading(false);
        showStatus(err.message);
        currentJobId = null;
    }
}

async function startDownload() {
    const url = urlInput.value.trim();
    if (!isYoutubeUrl(url)) {
        showStatus('Entrez une URL YouTube valide');
        return;
    }

    showStatus('');
    setControlsDownloading(true);
    setProgress(0, 'Démarrage…');

    const { quality, format } = getDownloadPayload();

    try {
        const job = await apiFetch('/api/download', {
            method: 'POST',
            body: JSON.stringify({ url, quality, format }),
        });
        currentJobId = job.job_id;
        stopPolling();
        pollTimer = setInterval(() => pollJob(currentJobId), 500);
        pollJob(currentJobId);
    } catch (err) {
        setControlsDownloading(false);
        setProgress(0, '0%');
        showStatus(err.message);
    }
}

async function cancelDownload() {
    if (!currentJobId) return;
    try {
        await apiFetch(`/api/download/${currentJobId}/cancel`, { method: 'POST' });
        await pollJob(currentJobId);
    } catch (err) {
        showStatus(err.message);
    }
}

async function openLatestDownload() {
    try {
        const files = await apiFetch('/api/downloads');
        if (!files.length) {
            showStatus('Aucun fichier dans le dossier de téléchargements');
            return;
        }
        const name = encodeURIComponent(files[0].name);
        window.open(`${API_BASE}/api/downloads/${name}`, '_blank');
    } catch (err) {
        showStatus(err.message);
    }
}

qualitySelect.addEventListener('change', () => {
    if (qualitySelect.value === 'audio') {
        formatSelect.value = 'mp3';
    }
    const qLabel = qualitySelect.options[qualitySelect.selectedIndex].text;
    if (videoTitle.textContent !== 'Collez un lien YouTube pour afficher l’aperçu') {
        qualityBadge.textContent = qLabel;
    }
});

urlInput.addEventListener('input', scheduleInfoFetch);
urlInput.addEventListener('paste', scheduleInfoFetch);

startBtn.addEventListener('click', () => {
    if (isDownloading) return;
    startDownload();
});

cancelBtn.addEventListener('click', cancelDownload);
folderBtn.addEventListener('click', openLatestDownload);

overlayPlayBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePreviewPlayback();
});
previewPlayBtn.addEventListener('click', startPreviewPlayback);
previewPauseBtn.addEventListener('click', stopPreviewPlayback);
thumbnailContainer.addEventListener('click', (e) => {
    if (e.target.closest('iframe')) return;
    if (!currentVideoId) return;
    if (e.target === overlayPlayBtn || overlayPlayBtn.contains(e.target)) return;
    togglePreviewPlayback();
});

urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !isDownloading) {
        startDownload();
    }
});

if (window.location.protocol === 'file:') {
    showStatus('Utilisez demarrer.bat ou ouvrez http://localhost:8000');
}
