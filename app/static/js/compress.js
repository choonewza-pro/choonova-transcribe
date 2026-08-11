document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';

  const apiKeyInput = document.getElementById('apiKeyInput');
  const toggleApiKeyBtn = document.getElementById('toggleApiKeyBtn');
  const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
  const clearApiKeyLink = document.getElementById('clearApiKeyLink');

  const compressDropzone = document.getElementById('compressDropzone');
  const compressFileInput = document.getElementById('compressFileInput');
  const compressFileName = document.getElementById('compressFileName');
  const compressFileSize = document.getElementById('compressFileSize');
  const startCompressBtn = document.getElementById('startCompressBtn');
  const compressForm = document.getElementById('compressForm');

  const previewContainer = document.getElementById('compressPreviewContainer');
  const videoPreview = document.getElementById('compressVideoPreview');
  const sourceResInfo = document.getElementById('sourceResInfo');
  const targetWidthInput = document.getElementById('targetWidth');
  const widthHint = document.getElementById('widthHint');
  const bitrateInput = document.getElementById('bitrateKbps');
  const crfSlider = document.getElementById('crfSlider');
  const crfValue = document.getElementById('crfValue');
  const presetSelect = document.getElementById('presetSelect');

  const progressSection = document.getElementById('compressProgressSection');
  const queueBanner = document.getElementById('queueBanner');
  const queueBannerText = document.getElementById('queueBannerText');
  const stageText = document.getElementById('compressStageText');
  const pctText = document.getElementById('compressPctText');
  const progressFill = document.getElementById('compressProgressFill');
  const cancelCompressBtn = document.getElementById('cancelCompressBtn');

  const resultSection = document.getElementById('compressResultSection');
  const btnDownload = document.getElementById('btnDownloadCompressed');
  const resOriginalSize = document.getElementById('resOriginalSize');
  const resCompressedSize = document.getElementById('resCompressedSize');
  const resSavedPct = document.getElementById('resSavedPct');
  const resResolution = document.getElementById('resResolution');
  const resDuration = document.getElementById('resDuration');
  const statJobId = document.getElementById('compressStatJobId');
  const statElapsed = document.getElementById('compressStatElapsed');

  let selectedFile = null;
  let activeJobId = null;
  let pollInterval = null;
  let sourceWidth = 0;
  let sourceHeight = 0;

  // --- API Key Management (same UX as the other pages) ---
  function getApiKey() {
    return (apiKeyInput && apiKeyInput.value.trim()) || localStorage.getItem(API_KEY_STORAGE) || '';
  }
  function maskApiKey(key) {
    if (!key) return '••••••••';
    if (key.length <= 8) return '•'.repeat(key.length);
    return `${key.slice(0, 4)}••••${key.slice(-4)}`;
  }
  function initApiKeyUI() {
    const inputGroup = document.getElementById('apiKeyInputGroup');
    const savedState = document.getElementById('apiKeySavedState');
    const mask = document.getElementById('apiKeyMask');
    const saved = localStorage.getItem(API_KEY_STORAGE);
    if (saved) {
      if (inputGroup) inputGroup.style.display = 'none';
      if (savedState) {
        savedState.style.display = 'flex';
        if (mask) mask.textContent = maskApiKey(saved);
      }
    } else {
      if (inputGroup) inputGroup.style.display = 'block';
      if (savedState) savedState.style.display = 'none';
    }
  }
  if (saveApiKeyBtn) saveApiKeyBtn.addEventListener('click', () => {
    const key = apiKeyInput ? apiKeyInput.value.trim() : '';
    if (!key) { alert('Please enter an API key before saving.'); return; }
    localStorage.setItem(API_KEY_STORAGE, key);
    if (apiKeyInput) apiKeyInput.value = '';
    initApiKeyUI();
  });
  if (clearApiKeyLink) clearApiKeyLink.addEventListener('click', (e) => {
    e.preventDefault();
    localStorage.removeItem(API_KEY_STORAGE);
    if (apiKeyInput) apiKeyInput.value = '';
    initApiKeyUI();
  });
  if (toggleApiKeyBtn) toggleApiKeyBtn.addEventListener('click', () => {
    if (apiKeyInput) apiKeyInput.type = apiKeyInput.type === 'password' ? 'text' : 'password';
  });
  initApiKeyUI();

  // --- Formatting helpers ---
  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '-';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }
  function formatSeconds(seconds) {
    if (!seconds || seconds <= 0) return '-';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hrs > 0) return `${hrs}ชม. ${mins}นาที`;
    if (mins > 0) return `${mins}นาที ${secs}วิ`;
    return `${secs}วินาที`;
  }
  function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }

  // --- Drag & drop ---
  compressDropzone.addEventListener('click', () => compressFileInput.click());
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(n => compressDropzone.addEventListener(n, preventDefaults, false));
  ['dragenter', 'dragover'].forEach(n => compressDropzone.addEventListener(n, () => compressDropzone.classList.add('dragover'), false));
  ['dragleave', 'drop'].forEach(n => compressDropzone.addEventListener(n, () => compressDropzone.classList.remove('dragover'), false));
  compressDropzone.addEventListener('drop', (e) => { if (e.dataTransfer.files.length > 0) handleFileSelected(e.dataTransfer.files[0]); });
  compressFileInput.addEventListener('change', (e) => { if (e.target.files.length > 0) handleFileSelected(e.target.files[0]); });

  function handleFileSelected(file) {
    const maxUploadMb = parseFloat(compressForm.dataset.maxUploadMb) || 0;
    if (maxUploadMb > 0 && file.size > maxUploadMb * 1024 * 1024) {
      alert(`ไฟล์ใหญ่เกินไป! ขนาดสูงสุดที่อนุญาตคือ ${maxUploadMb} MB`);
      selectedFile = null;
      compressFileName.textContent = '📁 ไม่มีไฟล์ (ขนาดเกินกำหนด)';
      startCompressBtn.disabled = true;
      previewContainer.style.display = 'none';
      return;
    }
    selectedFile = file;
    compressFileName.textContent = `📁 ไฟล์ที่เลือก: ${file.name}`;
    compressFileSize.textContent = formatBytes(file.size);
    startCompressBtn.disabled = false;

    const fileURL = URL.createObjectURL(file);
    previewContainer.style.display = 'block';
    videoPreview.src = fileURL;
    videoPreview.style.display = 'block';

    videoPreview.onloadedmetadata = () => {
      sourceWidth = videoPreview.videoWidth || 0;
      sourceHeight = videoPreview.videoHeight || 0;
      if (sourceWidth && sourceHeight) {
        sourceResInfo.textContent = `ความละเอียดต้นฉบับ: ${sourceWidth} × ${sourceHeight}`;
      }
      updateWidthHint();
    };
  }

  // --- Live width preview (keeps aspect ratio, even height) ---
  function updateWidthHint() {
    const w = parseInt(targetWidthInput.value, 10) || 0;
    if (!w || !sourceWidth || !sourceHeight) {
      widthHint.textContent = 'เว้นว่างหรือ 0 = ไม่ปรับขนาด • ระบบห้ามขยายเกินไฟล์ต้นฉบับ';
      return;
    }
    const clamped = Math.min(w, sourceWidth);
    let h = Math.round((sourceHeight * clamped) / sourceWidth);
    if (h % 2 !== 0) h += 1;
    const suffix = clamped < w ? ' (จำกัดไม่เกินขนาดต้นฉบับ)' : '';
    widthHint.textContent = `→ ไฟล์จะถูกลดเหลือ ${clamped} × ${h} (คงอัตราส่วน)${suffix}`;
  }
  targetWidthInput.addEventListener('input', updateWidthHint);

  crfSlider.addEventListener('input', () => { crfValue.textContent = crfSlider.value; });

  // --- Progress helpers ---
  function updateProgress(pct, stageTextMsg) {
    const rounded = Math.min(100, Math.max(0, Math.round(pct)));
    pctText.textContent = `${rounded}%`;
    progressFill.style.width = `${rounded}%`;
    if (stageTextMsg) stageText.textContent = `⚙️ ${stageTextMsg}`;
  }
  function showQueueBanner(position, length) {
    if (position > 0) {
      queueBanner.classList.add('visible');
      queueBannerText.textContent = `รอคิวอยู่ที่ตำแหน่ง ${position} จาก ${length} งาน — มีวิดีโออื่นกำลังบีบอัดอยู่ (ระบบทำทีละไฟล์)`;
    } else {
      queueBanner.classList.remove('visible');
    }
  }
  function isProcessingStatus(status) {
    return ['queued', 'processing'].includes(status);
  }
  function stopPolling() {
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  }
  function resetToIdle(message) {
    stopPolling();
    cancelCompressBtn.style.display = 'none';
    stageText.textContent = message;
    startCompressBtn.disabled = false;
  }

  async function cancelActiveJob() {
    if (!activeJobId) return;
    if (!confirm('❌ ยกเลิกงานนี้?\n\nไฟล์ต้นฉบับและไฟล์ที่บีบอัดแล้วจะถูกลบถาวร ไม่สามารถกู้คืนได้')) return;
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;
      const res = await fetch(`/v1/media/compress/jobs/${activeJobId}`, { method: 'DELETE', headers });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { detail = (await res.json()).detail || detail; } catch (e2) {}
        throw new Error(detail);
      }
      resetToIdle('❌ ยกเลิกงานเรียบร้อยแล้ว (Cancelled)');
      alert('✅ ยกเลิกงานเรียบร้อยแล้ว — ไฟล์ต้นฉบับถูกลบแล้ว');
    } catch (err) {
      alert(`❌ ยกเลิกงานล้มเหลว: ${err.message || err}`);
    }
  }
  if (cancelCompressBtn) cancelCompressBtn.addEventListener('click', cancelActiveJob);

  // --- Upload + create job ---
  compressForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!selectedFile) return;

    const widthVal = parseInt(targetWidthInput.value, 10) || 0;
    const bitrateVal = parseInt(bitrateInput.value, 10) || 0;
    if (!widthVal && !bitrateVal) {
      alert('กรุณากรอกอย่างใดอย่างหนึ่ง: ความกว้างที่ต้องการ (px) หรือบิตเรต (kbps)');
      return;
    }

    startCompressBtn.disabled = true;
    progressSection.style.display = 'block';
    resultSection.style.display = 'none';
    showQueueBanner(1, 1);
    updateProgress(0, 'อัปโหลดไฟล์ขึ้นเซิร์ฟเวอร์...');

    const formData = new FormData();
    formData.append('file', selectedFile);
    if (widthVal) formData.append('target_width', widthVal);
    if (bitrateVal) formData.append('bitrate_kbps', bitrateVal);
    formData.append('crf', crfSlider.value);
    formData.append('preset', presetSelect.value);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/v1/media/compress/jobs', true);
    const apiKey = getApiKey();
    if (apiKey) xhr.setRequestHeader('x-api-key', apiKey);

    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) {
        updateProgress((ev.loaded / ev.total) * 5, `อัปโหลดไฟล์แล้ว (${formatBytes(ev.loaded)} / ${formatBytes(ev.total)})...`);
      }
    };
    xhr.onload = () => {
      if (xhr.status === 202) {
        const data = JSON.parse(xhr.responseText);
        activeJobId = data.job_id;
        showQueueBanner(data.queue_position || 1, data.queue_length || 0);
        updateProgress(5, 'เพิ่มเข้าคิวแล้ว — รอคิวบีบอัด...');
        startPollingJobStatus(activeJobId);
      } else {
        try {
          const errData = JSON.parse(xhr.responseText);
          alert(`เกิดข้อผิดพลาดในการสร้างงาน: ${errData.detail || 'Unknown error'}`);
        } catch (ex) {
          alert(`เกิดข้อผิดพลาดในการอัปโหลด (${xhr.status})`);
        }
        startCompressBtn.disabled = false;
        showQueueBanner(0, 0);
      }
    };
    xhr.onerror = () => {
      alert('การเชื่อมต่อเครือข่ายล้มเหลวขณะอัปโหลดไฟล์');
      startCompressBtn.disabled = false;
    };
    xhr.send(formData);
  });

  // --- Poll status every 2s ---
  function startPollingJobStatus(jobId) {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(async () => {
      try {
        const headers = {};
        const apiKey = getApiKey();
        if (apiKey) headers['x-api-key'] = apiKey;
        const res = await fetch(`/v1/media/compress/jobs/${jobId}`, { headers });
        if (!res.ok) return;
        const job = await res.json();

        showQueueBanner(job.queue_position || 0, job.queue_length || 0);
        updateProgress(job.progress_pct, job.current_stage || job.status);
        cancelCompressBtn.style.display = isProcessingStatus(job.status) ? 'inline-flex' : 'none';

        if (job.status === 'completed') {
          stopPolling();
          handleJobCompleted(job);
        } else if (job.status === 'failed') {
          stopPolling();
          alert(`การบีบอัดล้มเหลว: ${job.error_message || 'Unknown error'}`);
          stageText.textContent = `❌ เกิดข้อผิดพลาด: ${job.error_message || 'Failed'}`;
          startCompressBtn.disabled = false;
          cancelCompressBtn.style.display = 'none';
        }
      } catch (err) {
        console.error('Error polling compress job status:', err);
      }
    }, 2000);
  }

  function handleJobCompleted(job) {
    resultSection.style.display = 'block';
    cancelCompressBtn.style.display = 'none';

    resOriginalSize.textContent = formatBytes(job.file_size_bytes);
    resCompressedSize.textContent = formatBytes(job.output_size_bytes);
    const reduction = job.file_size_bytes > 0
      ? ((1 - job.output_size_bytes / job.file_size_bytes) * 100).toFixed(1)
      : 0;
    resSavedPct.textContent = `${reduction}%`;
    if (reduction < 0) resSavedPct.textContent = 'ขยายขึ้น!';

    resResolution.textContent = (job.output_width && job.output_height)
      ? `${job.output_width} × ${job.output_height}`
      : '-';
    resDuration.textContent = formatSeconds(job.duration_seconds);
    statJobId.textContent = `🆔 Job ID: ${job.job_id.substring(0, 8)}...`;
    statElapsed.textContent = `⚡ เวลาประมวลผล: ${formatSeconds(job.elapsed_seconds)}`;

    const apiKey = getApiKey();
    const keyParam = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : '';
    btnDownload.href = `/v1/media/compress/jobs/${job.job_id}/download${keyParam}`;

    startCompressBtn.disabled = false;
    selectedFile = null;
  }
});
