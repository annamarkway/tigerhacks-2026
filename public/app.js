/* ============================================
   Memory Vault — Application Logic (PWA)
   ============================================ */

// ── Config ──
const API_BASE = '/api';

// ── State ──
let currentMode = null;          // 'photo' | 'voice'
let mediaStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;
let timerInterval = null;
let timerSeconds = 0;
let capturedBlob = null;
let capturedType = null;         // 'photo' | 'voice'
let pendingMedia = [];           // Array of { type, blob, url, fileName }
let vault = [];
let audioContext = null;
let analyser = null;
let animFrameId = null;

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  loadVault();
});

// ── Navigation ──
function navigateTo(screenId) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const target = document.getElementById(screenId);
  if (target) {
    target.classList.add('active');
    target.style.animation = 'none';
    void target.offsetHeight;
    target.style.animation = '';
  }
  if (screenId === 'vault') renderVault();
  if (screenId === 'add-item') resetAddForm();
}

// ── Toast ──
function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.remove('hidden');
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.classList.add('hidden'), 350);
  }, 2400);
}

// ── Loading Overlay ──
function showLoading(msg) {
  const el = document.getElementById('loading-overlay');
  el.querySelector('p').textContent = msg || 'Saving to vault…';
  el.classList.remove('hidden');
}

function hideLoading() {
  document.getElementById('loading-overlay').classList.add('hidden');
}

// ── Add-Item helpers ──
function resetAddForm() {
  document.getElementById('item-name').value = '';
  document.getElementById('item-story').value = '';
  pendingMedia.forEach(item => URL.revokeObjectURL(item.url));
  pendingMedia = [];
  refreshMediaStrip();
  document.getElementById('photo-upload').value = '';
}

function refreshMediaStrip() {
  const container = document.getElementById('attached-media');
  const list = document.getElementById('media-preview-list');
  list.innerHTML = '';

  if (pendingMedia.length === 0) {
    container.classList.add('hidden');
    return;
  }

  container.classList.remove('hidden');

  pendingMedia.forEach((item, idx) => {
    const thumb = document.createElement('div');
    thumb.className = 'media-thumb';

    if (item.type === 'photo') {
      const img = document.createElement('img');
      img.src = item.url;
      thumb.appendChild(img);
    } else {
      thumb.innerHTML = '<span style="font-size:2rem">🎙️</span>';
    }

    const badge = document.createElement('span');
    badge.className = 'thumb-badge';
    badge.textContent = item.type === 'photo' ? '📷' : '🎙️';
    thumb.appendChild(badge);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'thumb-remove';
    removeBtn.textContent = '✕';
    removeBtn.onclick = (e) => {
      e.stopPropagation();
      URL.revokeObjectURL(item.url);
      pendingMedia.splice(idx, 1);
      refreshMediaStrip();
    };
    thumb.appendChild(removeBtn);

    list.appendChild(thumb);
  });
}

// ───────── File Upload (from gallery — iOS/Android native) ─────────

function triggerFileUpload(inputId) {
  document.getElementById(inputId).click();
}

function handleFileUpload(input, type) {
  const file = input.files[0];
  if (!file) return;

  const blob = file;
  const url = URL.createObjectURL(file);
  pendingMedia.push({ type, blob, url, fileName: file.name });
  refreshMediaStrip();
  showToast('🖼️ Photo added!');

  // Reset input so the same file can be re-picked
  input.value = '';
}

// ───────── Capture Flow (getUserMedia — live camera/mic) ─────────

function openCapture(mode) {
  currentMode = mode;
  capturedBlob = null;
  capturedType = null;
  isRecording = false;
  recordedChunks = [];

  const modal = document.getElementById('capture-modal');
  const title = document.getElementById('capture-modal-title');
  const preview = document.getElementById('camera-preview');
  const visualizer = document.getElementById('voice-visualizer');
  const timer = document.getElementById('capture-timer');
  const fallback = document.getElementById('capture-fallback');
  const live = document.getElementById('capture-live');

  hideAllCaptureButtons();

  clearInterval(timerInterval);
  timerSeconds = 0;
  timer.classList.add('hidden');
  timer.textContent = '00:00';

  modal.classList.remove('hidden');

  // Check if getUserMedia is available
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    live.classList.add('hidden');
    fallback.classList.remove('hidden');
    return;
  }

  live.classList.remove('hidden');
  fallback.classList.add('hidden');

  if (mode === 'photo') {
    title.textContent = '📷 Take a Photo';
    preview.classList.remove('hidden');
    visualizer.classList.add('hidden');
    document.getElementById('btn-snap').classList.remove('hidden');
    startCamera();
  } else if (mode === 'voice') {
    title.textContent = '🎙️ Voice Note';
    preview.classList.add('hidden');
    visualizer.classList.remove('hidden');
    document.getElementById('btn-record-voice').classList.remove('hidden');
    startMic();
  }
}

function hideAllCaptureButtons() {
  ['btn-snap', 'btn-record-voice', 'btn-use-capture', 'btn-retake'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });
}

async function startCamera() {
  try {
    const constraints = {
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1280 },
        height: { ideal: 960 }
      },
      audio: false
    };
    mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
    const preview = document.getElementById('camera-preview');
    preview.srcObject = mediaStream;
    preview.setAttribute('playsinline', '');
    preview.play().catch(() => {});
  } catch (err) {
    console.error('Camera access error:', err);
    showToast('⚠️ Camera access denied. Use the Upload button instead.');
    closeCapture();
  }
}

async function startMic() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    setupVisualizer();
  } catch (err) {
    console.error('Mic access error:', err);
    showToast('⚠️ Microphone access denied.');
    closeCapture();
  }
}

function setupVisualizer() {
  const canvas = document.getElementById('voice-visualizer');
  const ctx = canvas.getContext('2d');
  canvas.width = canvas.offsetWidth * 2;
  canvas.height = canvas.offsetHeight * 2;

  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioContext.createMediaStreamSource(mediaStream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 256;
  source.connect(analyser);

  const bufLen = analyser.frequencyBinCount;
  const dataArray = new Uint8Array(bufLen);

  function draw() {
    animFrameId = requestAnimationFrame(draw);
    analyser.getByteFrequencyData(dataArray);

    ctx.fillStyle = '#1c1c28';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const barW = (canvas.width / bufLen) * 2.5;
    let x = 0;

    for (let i = 0; i < bufLen; i++) {
      const barH = (dataArray[i] / 255) * canvas.height * 0.85;
      const hue = 260 + (i / bufLen) * 40;
      ctx.fillStyle = `hsla(${hue}, 70%, 60%, 0.85)`;
      ctx.fillRect(x, canvas.height - barH, barW - 1, barH);
      x += barW;
    }
  }
  draw();
}

// ── Photo Snap ──
function snapPhoto() {
  const video = document.getElementById('camera-preview');
  const canvas = document.getElementById('snap-canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0);

  canvas.toBlob(blob => {
    capturedBlob = blob;
    capturedType = 'photo';

    const url = URL.createObjectURL(blob);
    video.srcObject = null;
    video.src = url;
    video.muted = true;
    video.loop = false;
    video.pause();
    video.currentTime = 0;

    stopMedia();

    hideAllCaptureButtons();
    document.getElementById('btn-use-capture').classList.remove('hidden');
    document.getElementById('btn-retake').classList.remove('hidden');
  }, 'image/jpeg', 0.92);
}

// ── Voice Recording ──
function toggleVoiceRecording() {
  const btn = document.getElementById('btn-record-voice');

  if (!isRecording) {
    recordedChunks = [];
    const options = getSupportedMimeType('audio');
    try {
      mediaRecorder = new MediaRecorder(mediaStream, options);
    } catch (e) {
      mediaRecorder = new MediaRecorder(mediaStream);
    }

    mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) recordedChunks.push(e.data);
    };

    mediaRecorder.onstop = () => {
      const mimeType = mediaRecorder.mimeType || 'audio/mp4';
      capturedBlob = new Blob(recordedChunks, { type: mimeType });
      capturedType = 'voice';

      stopMedia();
      cancelAnimationFrame(animFrameId);

      hideAllCaptureButtons();
      document.getElementById('btn-use-capture').classList.remove('hidden');
      document.getElementById('btn-retake').classList.remove('hidden');

      const canvas = document.getElementById('voice-visualizer');
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#1c1c28';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#7c5cfc';
      ctx.font = `bold ${canvas.height * 0.12}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText('✅ Voice note recorded!', canvas.width / 2, canvas.height / 2);
    };

    mediaRecorder.start(1000);
    isRecording = true;
    btn.textContent = '⏹ Stop Recording';
    btn.classList.add('recording');
    startTimer();
  } else {
    mediaRecorder.stop();
    isRecording = false;
    btn.textContent = '🎙️ Start Recording';
    btn.classList.remove('recording');
    stopTimer();
  }
}

function getSupportedMimeType(kind) {
  if (typeof MediaRecorder === 'undefined') return {};

  const types = ['audio/mp4', 'audio/aac', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg'];

  for (const type of types) {
    if (MediaRecorder.isTypeSupported(type)) {
      return { mimeType: type };
    }
  }
  return {};
}

// ── Timer ──
function startTimer() {
  timerSeconds = 0;
  const el = document.getElementById('capture-timer');
  el.classList.remove('hidden');
  timerInterval = setInterval(() => {
    timerSeconds++;
    const m = String(Math.floor(timerSeconds / 60)).padStart(2, '0');
    const s = String(timerSeconds % 60).padStart(2, '0');
    el.textContent = `${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  clearInterval(timerInterval);
}

// ── Use / Retake ──
function useCapture() {
  if (!capturedBlob) return;

  const url = URL.createObjectURL(capturedBlob);
  const ext = capturedType === 'photo' ? '.jpg' : '.webm';
  const fileName = `${capturedType}_${Date.now()}${ext}`;
  pendingMedia.push({ type: capturedType, blob: capturedBlob, url, fileName });
  refreshMediaStrip();
  closeCapture();
  showToast(`${capturedType === 'photo' ? '📷' : '🎙️'} Memory captured!`);
}

function retake() {
  capturedBlob = null;
  capturedType = null;
  openCapture(currentMode);
}

function closeCapture() {
  stopMedia();
  clearInterval(timerInterval);
  cancelAnimationFrame(animFrameId);

  if (audioContext) {
    audioContext.close().catch(() => {});
    audioContext = null;
  }

  if (isRecording && mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  isRecording = false;

  document.getElementById('capture-modal').classList.add('hidden');

  const preview = document.getElementById('camera-preview');
  preview.srcObject = null;
  preview.src = '';
}

function stopMedia() {
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop());
    mediaStream = null;
  }
}

// ───────── Save Memory (uploads to server) ─────────

async function saveMemory() {
  const name = document.getElementById('item-name').value.trim();
  if (!name) {
    showToast('⚠️ Give your item a name first.');
    return;
  }
  if (pendingMedia.length === 0) {
    showToast('⚠️ Capture at least one memory (photo or voice note).');
    return;
  }

  const story = document.getElementById('item-story').value.trim();
  const saveBtn = document.getElementById('btn-save');
  saveBtn.disabled = true;
  showLoading('Uploading media…');

  try {
    const uploadedMedia = [];

    for (const item of pendingMedia) {
      const formData = new FormData();
      const ext = getExtension(item.blob.type, item.type);
      const fileName = item.fileName || `${item.type}_${Date.now()}${ext}`;
      formData.append('file', item.blob, fileName);
      formData.append('type', item.type);

      const uploadRes = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!uploadRes.ok) throw new Error('Upload failed');

      const uploadData = await uploadRes.json();
      const mediaEntry = {
        type: item.type,
        filename: uploadData.filename,
        originalName: uploadData.originalName,
        url: uploadData.url,
        size: uploadData.size,
      };
      // Include hash key for photos (used by photo registry)
      if (uploadData.hashKey) {
        mediaEntry.hashKey = uploadData.hashKey;
      }
      uploadedMedia.push(mediaEntry);
    }

    showLoading('Saving memory…');

    const memoryRes = await fetch(`${API_BASE}/memories`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, story, media: uploadedMedia }),
    });

    if (!memoryRes.ok) throw new Error('Save failed');

    showToast('💾 Memory saved to your vault!');
    pendingMedia.forEach(item => URL.revokeObjectURL(item.url));
    pendingMedia = [];

    setTimeout(() => navigateTo('vault'), 600);
  } catch (err) {
    console.error('Save error:', err);
    showToast('⚠️ Failed to save. Please try again.');
  } finally {
    saveBtn.disabled = false;
    hideLoading();
  }
}

function getExtension(mimeType, fallbackType) {
  const map = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/heic': '.heic',
    'audio/mp4': '.m4a',
    'audio/aac': '.aac',
    'audio/webm': '.webm',
    'audio/ogg': '.ogg',
    'audio/mpeg': '.mp3',
    'audio/wav': '.wav',
  };
  if (map[mimeType]) return map[mimeType];
  if (fallbackType === 'photo') return '.jpg';
  return '.webm';
}

// ───────── Load & Render Vault (from server) ─────────

async function loadVault() {
  try {
    const res = await fetch(`${API_BASE}/memories`);
    const data = await res.json();
    vault = data.memories || [];
  } catch (err) {
    console.error('Failed to load vault:', err);
    vault = [];
  }
}

async function renderVault() {
  await loadVault();

  const emptyEl = document.getElementById('vault-empty');
  const gridEl = document.getElementById('vault-grid');

  if (vault.length === 0) {
    emptyEl.classList.remove('hidden');
    gridEl.classList.add('hidden');
    return;
  }

  emptyEl.classList.add('hidden');
  gridEl.classList.remove('hidden');
  gridEl.innerHTML = '';

  [...vault].reverse().forEach(memory => {
    const card = document.createElement('div');
    card.className = 'vault-card';
    card.onclick = () => openDetail(memory.id);

    const thumbDiv = document.createElement('div');
    thumbDiv.className = 'vault-card-thumb';
    const photoMedia = memory.media.find(m => m.type === 'photo');
    if (photoMedia) {
      const img = document.createElement('img');
      img.src = photoMedia.url;
      img.alt = memory.name;
      img.loading = 'lazy';
      thumbDiv.appendChild(img);
    } else {
      thumbDiv.textContent = '🗃️';
    }

    const body = document.createElement('div');
    body.className = 'vault-card-body';
    body.innerHTML = `
      <h4>${escapeHtml(memory.name)}</h4>
      <p>${memory.story ? escapeHtml(memory.story) : '<em>No story written</em>'}</p>
      <div class="vault-card-meta">
        ${memory.media.map(m =>
          `<span class="meta-badge">${m.type === 'photo' ? '📷 Photo' : '🎙️ Voice'}</span>`
        ).join('')}
        <span class="meta-badge">${formatDate(memory.date)}</span>
      </div>
    `;

    card.appendChild(thumbDiv);
    card.appendChild(body);
    gridEl.appendChild(card);
  });
}

// ───────── Detail Modal ─────────

function openDetail(id) {
  const memory = vault.find(m => m.id === id);
  if (!memory) return;

  const body = document.getElementById('detail-body');
  let html = `
    <h3 style="margin-bottom: 6px;">${escapeHtml(memory.name)}</h3>
    <p class="detail-date">${formatDate(memory.date)}</p>
  `;

  if (memory.story) {
    html += `<p class="detail-story">${escapeHtml(memory.story)}</p>`;
  }

  memory.media.forEach(m => {
    if (m.type === 'photo') {
      html += `<div class="detail-media"><img src="${m.url}" alt="${escapeHtml(memory.name)}" /></div>`;
    } else if (m.type === 'voice') {
      html += `<audio class="detail-audio" src="${m.url}" controls></audio>`;
    }
  });

  html += `
    <div class="detail-actions">
      <button class="btn btn-sm btn-danger" onclick="deleteMemory('${memory.id}')">🗑️ Delete</button>
      <button class="btn btn-sm btn-outline" onclick="closeDetail()">Close</button>
    </div>
  `;

  body.innerHTML = html;
  document.getElementById('detail-modal').classList.remove('hidden');
}

function closeDetail() {
  document.getElementById('detail-modal').classList.add('hidden');
}

async function deleteMemory(id) {
  if (!confirm('Are you sure you want to delete this memory forever?')) return;

  try {
    await fetch(`${API_BASE}/memories/${id}`, { method: 'DELETE' });
    showToast('🗑️ Memory deleted.');
  } catch (err) {
    console.error('Delete error:', err);
    showToast('⚠️ Failed to delete.');
  }

  closeDetail();
  renderVault();
}

// ── Helpers ──
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
