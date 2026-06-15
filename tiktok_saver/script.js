const API_BASE = "http://127.0.0.1:8000";

const urlInput = document.getElementById("urlInput");
const startBtn = document.getElementById("startBtn");
const cancelBtn = document.getElementById("cancelBtn");
const folderBtn = document.getElementById("folderBtn");
const qualitySelect = document.getElementById("qualitySelect");
const formatSelect = document.getElementById("formatSelect");
const progressBar = document.getElementById("progressBar");
const progressText = document.getElementById("progressText");
const statusMessage = document.getElementById("statusMessage");
const previewThumb = document.getElementById("previewThumb");
const thumbPlaceholder = document.getElementById("thumbPlaceholder");
const videoTitle = document.getElementById("videoTitle");
const videoAuthor = document.getElementById("videoAuthor");
const authorAvatar = document.getElementById("authorAvatar");
const qualityBadge = document.getElementById("qualityBadge");
const fileDownloadLink = document.getElementById("fileDownloadLink");

let currentTaskId = null;
let pollInterval = null;
let infoDebounce = null;
let isDownloading = false;

function isValidUrl(str) {
    try {
        const u = new URL(str.trim());
        return u.protocol === "http:" || u.protocol === "https:";
    } catch {
        return false;
    }
}

function setStatus(text, type = "") {
    statusMessage.textContent = text || "";
    statusMessage.className = "status-message" + (type ? ` ${type}` : "");
}

function setProgress(value, label) {
    const pct = Math.max(0, Math.min(100, value));
    progressBar.style.width = pct + "%";
    progressText.textContent = label ?? pct + "%";
    if (pct >= 100) {
        progressText.style.color = "var(--success)";
    } else {
        progressText.style.color = "var(--text-muted)";
    }
}

function resetProgress() {
    setProgress(0, "0%");
    fileDownloadLink.classList.add("hidden");
    fileDownloadLink.removeAttribute("href");
}

async function apiFetch(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { "Content-Type": "application/json", ...options.headers },
        ...options,
    });
    let data = null;
    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
        data = await res.json();
    }
    if (!res.ok) {
        const detail = data?.detail;
        const msg = typeof detail === "string" ? detail : JSON.stringify(detail) || res.statusText;
        throw new Error(msg);
    }
    return data;
}

function syncFormatWithQuality() {
    if (qualitySelect.value === "audio") {
        formatSelect.value = "mp3";
        formatSelect.disabled = true;
    } else {
        formatSelect.disabled = false;
    }
    qualityBadge.textContent = qualitySelect.options[qualitySelect.selectedIndex].text.replace(" (HD)", "");
}

function updatePreview(info) {
    videoTitle.textContent = info.title || "Sans titre";
    videoAuthor.textContent = info.author || "—";
    qualityBadge.textContent = qualitySelect.options[qualitySelect.selectedIndex].text.replace(" (HD)", "");

    if (info.thumbnail) {
        previewThumb.src = info.thumbnail;
        previewThumb.alt = info.title || "";
        previewThumb.classList.remove("hidden");
        thumbPlaceholder.classList.add("hidden");
        authorAvatar.style.backgroundImage = `url(${info.thumbnail})`;
        authorAvatar.style.backgroundSize = "cover";
    } else {
        previewThumb.classList.add("hidden");
        thumbPlaceholder.classList.remove("hidden");
        authorAvatar.style.backgroundImage = "";
    }
}

async function fetchVideoInfo() {
    const url = urlInput.value.trim();
    if (!isValidUrl(url)) return;

    setStatus("Analyse du lien…");
    try {
        const info = await apiFetch("/info", {
            method: "POST",
            body: JSON.stringify({ url }),
        });
        updatePreview(info);
        setStatus(`Aperçu chargé (${info.platform})`, "success");
    } catch (err) {
        setStatus(err.message, "error");
    }
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

async function pollTaskStatus(taskId) {
    try {
        const task = await apiFetch(`/download/${taskId}`);
        const label = task.message ? `${Math.round(task.progress)}% — ${task.message}` : `${Math.round(task.progress)}%`;
        setProgress(task.progress, label);

        if (task.status === "completed") {
            stopPolling();
            isDownloading = false;
            startBtn.disabled = false;
            setProgress(100, "Terminé");
            setStatus("Téléchargement terminé.", "success");

            if (task.filename) {
                const href = `${API_BASE}/files/${encodeURIComponent(task.filename)}?download=true`;
                fileDownloadLink.href = href;
                fileDownloadLink.textContent = `Télécharger : ${task.filename}`;
                fileDownloadLink.classList.remove("hidden");
            }
            currentTaskId = null;
        } else if (task.status === "failed") {
            stopPolling();
            isDownloading = false;
            startBtn.disabled = false;
            setStatus(task.message || "Échec du téléchargement.", "error");
            currentTaskId = null;
        } else if (task.status === "cancelled") {
            stopPolling();
            isDownloading = false;
            startBtn.disabled = false;
            resetProgress();
            setStatus("Téléchargement annulé.", "");
            currentTaskId = null;
        }
    } catch (err) {
        stopPolling();
        isDownloading = false;
        startBtn.disabled = false;
        setStatus(err.message, "error");
        currentTaskId = null;
    }
}

async function startDownload() {
    const url = urlInput.value.trim();
    if (!isValidUrl(url)) {
        setStatus("Entrez une URL TikTok ou YouTube valide.", "error");
        return;
    }
    if (isDownloading) return;

    syncFormatWithQuality();
    resetProgress();
    isDownloading = true;
    startBtn.disabled = true;
    setStatus("Démarrage du téléchargement…");

    try {
        const body = {
            url,
            quality: qualitySelect.value,
            format: formatSelect.value,
        };
        const task = await apiFetch("/download", {
            method: "POST",
            body: JSON.stringify(body),
        });
        currentTaskId = task.task_id;
        setProgress(task.progress, "En cours…");
        pollInterval = setInterval(() => pollTaskStatus(currentTaskId), 500);
    } catch (err) {
        isDownloading = false;
        startBtn.disabled = false;
        setStatus(err.message, "error");
    }
}

async function cancelDownload() {
    if (!currentTaskId) {
        resetProgress();
        setStatus("");
        return;
    }
    try {
        await apiFetch(`/download/${currentTaskId}`, { method: "DELETE" });
    } catch (err) {
        setStatus(err.message, "error");
    }
}

async function openDownloadsFolder() {
    try {
        await apiFetch("/open-folder", { method: "POST" });
        setStatus("Dossier ouvert.", "success");
    } catch (err) {
        setStatus(err.message, "error");
    }
}

async function checkApiHealth() {
    try {
        await apiFetch("/health");
    } catch {
        setStatus("API hors ligne — lancez demarrer.bat", "error");
    }
}

urlInput.addEventListener("input", () => {
    clearTimeout(infoDebounce);
    infoDebounce = setTimeout(fetchVideoInfo, 700);
});

urlInput.addEventListener("paste", () => {
    clearTimeout(infoDebounce);
    infoDebounce = setTimeout(fetchVideoInfo, 300);
});

qualitySelect.addEventListener("change", syncFormatWithQuality);
formatSelect.addEventListener("change", () => {
    qualityBadge.textContent = formatSelect.value.toUpperCase();
});

startBtn.addEventListener("click", startDownload);
cancelBtn.addEventListener("click", cancelDownload);
folderBtn.addEventListener("click", openDownloadsFolder);

urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") startDownload();
});

syncFormatWithQuality();
resetProgress();
checkApiHealth();
