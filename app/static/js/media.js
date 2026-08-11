document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';

  const apiKeyInput = document.getElementById('apiKeyInput');
  const toggleApiKeyBtn = document.getElementById('toggleApiKeyBtn');
  const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
  const clearApiKeyLink = document.getElementById('clearApiKeyLink');

  const mediaDropzone = document.getElementById('mediaDropzone');
  const mediaFileInput = document.getElementById('mediaFileInput');
  const mediaFileName = document.getElementById('mediaFileName');
  const mediaFileSize = document.getElementById('mediaFileSize');
  const startJobBtn = document.getElementById('startJobBtn');
  const mediaUploadForm = document.getElementById('mediaUploadForm');

  const mediaPreviewContainer = document.getElementById('mediaPreviewContainer');
  const videoPreview = document.getElementById('videoPreview');
  const audioPreview = document.getElementById('audioPreview');

  const jobProgressSection = document.getElementById('jobProgressSection');
  const currentStageText = document.getElementById('currentStageText');
  const progressPctText = document.getElementById('progressPctText');
  const progressBarFill = document.getElementById('progressBarFill');

  const step1 = document.getElementById('step1');
  const step2 = document.getElementById('step2');
  const step3 = document.getElementById('step3');
  const step4 = document.getElementById('step4');
  const step5 = document.getElementById('step5');

  const resultSection = document.getElementById('resultSection');
  const resultText = document.getElementById('resultText');
  const btnCopy = document.getElementById('btnCopy');
  const btnDownloadTxt = document.getElementById('btnDownloadTxt');
  const btnDownloadSrt = document.getElementById('btnDownloadSrt');
  const btnDownloadJson = document.getElementById('btnDownloadJson');

  const statJobId = document.getElementById('statJobId');
  const statDuration = document.getElementById('statDuration');
  const statElapsed = document.getElementById('statElapsed');

  const cancelJobBtn = document.getElementById('cancelJobBtn');
  const btnNewJob = document.getElementById('btnNewJob');

  let selectedFile = null;
  let activeJobId = null;
  let pollInterval = null;

  // --- API Key Management ---
  function getApiKey() {
    return (apiKeyInput && apiKeyInput.value.trim()) || localStorage.getItem(API_KEY_STORAGE) || '';
  }

  function maskApiKey(key) {
    if (!key) return '••••••••';
    if (key.length <= 8) return '•'.repeat(key.length);
    return `${key.slice(0, 4)}••••${key.slice(-4)}`;
  }

  function initApiKeyUI() {
    const apiKeyInputGroup = document.getElementById('apiKeyInputGroup');
    const apiKeySavedState = document.getElementById('apiKeySavedState');
    const apiKeyMask = document.getElementById('apiKeyMask');
    const saved = localStorage.getItem(API_KEY_STORAGE);
    if (saved) {
      if (apiKeyInputGroup) apiKeyInputGroup.style.display = 'none';
      if (apiKeySavedState) {
        apiKeySavedState.style.display = 'flex';
        if (apiKeyMask) apiKeyMask.textContent = maskApiKey(saved);
      }
    } else {
      if (apiKeyInputGroup) apiKeyInputGroup.style.display = 'block';
      if (apiKeySavedState) apiKeySavedState.style.display = 'none';
    }
  }

  if (saveApiKeyBtn) {
    saveApiKeyBtn.addEventListener('click', () => {
      const key = apiKeyInput ? apiKeyInput.value.trim() : '';
      if (!key) {
        alert('Please enter an API key before saving.');
        return;
      }
      localStorage.setItem(API_KEY_STORAGE, key);
      if (apiKeyInput) apiKeyInput.value = '';
      initApiKeyUI();
    });
  }

  if (clearApiKeyLink) {
    clearApiKeyLink.addEventListener('click', (e) => {
      e.preventDefault();
      localStorage.removeItem(API_KEY_STORAGE);
      if (apiKeyInput) apiKeyInput.value = '';
      initApiKeyUI();
    });
  }

  if (toggleApiKeyBtn) {
    toggleApiKeyBtn.addEventListener('click', () => {
      if (apiKeyInput) {
        apiKeyInput.type = apiKeyInput.type === 'password' ? 'text' : 'password';
      }
    });
  }

  initApiKeyUI();

  // --- Formatting Helpers ---
  function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  function formatSeconds(seconds) {
    if (!seconds || seconds <= 0) return '-';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hrs > 0) return `${hrs}ชม. ${mins}นาที ${secs}วิ`;
    if (mins > 0) return `${mins}นาที ${secs}วิ`;
    return `${secs}วินาที`;
  }

  // --- Drag & Drop Handlers ---
  mediaDropzone.addEventListener('click', () => mediaFileInput.click());

  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    mediaDropzone.addEventListener(eventName, preventDefaults, false);
  });

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  ['dragenter', 'dragover'].forEach(eventName => {
    mediaDropzone.addEventListener(eventName, () => mediaDropzone.classList.add('dragover'), false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    mediaDropzone.addEventListener(eventName, () => mediaDropzone.classList.remove('dragover'), false);
  });

  mediaDropzone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
      handleFileSelected(files[0]);
    }
  });

  mediaFileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFileSelected(e.target.files[0]);
    }
  });

  function handleFileSelected(file) {
    const maxUploadMb = parseFloat(mediaUploadForm.dataset.maxUploadMb) || 0;
    if (maxUploadMb > 0 && file.size > maxUploadMb * 1024 * 1024) {
      alert(`ไฟล์ใหญ่เกินไป! ขนาดสูงสุดที่อนุญาตคือ ${maxUploadMb} MB`);
      selectedFile = null;
      mediaFileName.textContent = '📁 ไม่มีไฟล์ (ขนาดเกินกำหนด)';
      mediaFileSize.textContent = `ไฟล์นี้มีขนาด ${formatBytes(file.size)} — เกิน ${maxUploadMb} MB`;
      startJobBtn.disabled = true;
      mediaPreviewContainer.style.display = 'none';
      return;
    }
    selectedFile = file;
    mediaFileName.textContent = `📁 ไฟล์ที่เลือก: ${file.name}`;
    mediaFileSize.textContent = formatBytes(file.size);
    startJobBtn.disabled = false;

    // Show Preview
    const fileURL = URL.createObjectURL(file);
    mediaPreviewContainer.style.display = 'block';

    if (file.type.startsWith('video/')) {
      videoPreview.src = fileURL;
      videoPreview.style.display = 'block';
      audioPreview.style.display = 'none';
    } else {
      audioPreview.src = fileURL;
      audioPreview.style.display = 'block';
      videoPreview.style.display = 'none';
    }
  }

  // --- Stepper UI Update ---
  function updateStepper(stage, status) {
    [step1, step2, step3, step4, step5].forEach(s => s.className = 'step-item');

    if (status === 'queued') {
      step1.classList.add('active');
    } else if (status === 'extracting') {
      step1.classList.add('completed');
      step2.classList.add('active');
    } else if (status === 'chunking') {
      step1.classList.add('completed');
      step2.classList.add('completed');
      step3.classList.add('active');
    } else if (status === 'transcribing') {
      step1.classList.add('completed');
      step2.classList.add('completed');
      step3.classList.add('completed');
      step4.classList.add('active');
    } else if (status === 'completed') {
      [step1, step2, step3, step4, step5].forEach(s => s.classList.add('completed'));
    }
  }

  function isProcessingStatus(status) {
    return ['queued', 'extracting', 'chunking', 'transcribing'].includes(status);
  }

  function updateCancelBtn(status) {
    if (!cancelJobBtn) return;
    cancelJobBtn.style.display = isProcessingStatus(status) ? 'inline-flex' : 'none';
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  function resetToIdle(message) {
    stopPolling();
    updateCancelBtn('failed');
    currentStageText.textContent = message;
    startJobBtn.disabled = false;
  }

  function resetMediaUI() {
    stopPolling();
    resultSection.style.display = 'none';
    jobProgressSection.style.display = 'none';
    updateCancelBtn('failed');
    currentStageText.textContent = '⚙️ กำลังประมวลผล...';
    updateProgress(0, '');
    updateStepper(1, '');

    selectedFile = null;
    activeJobId = null;

    mediaFileInput.value = '';
    mediaFileName.textContent = '📹 ลากไฟล์วิดีโอ/ไฟล์เสียงมาวางที่นี่ หรือ คลิกเพื่อเลือกไฟล์';
    mediaFileSize.textContent = '';
    mediaPreviewContainer.style.display = 'none';
    videoPreview.src = '';
    audioPreview.src = '';
    startJobBtn.disabled = true;
    startJobBtn.innerHTML = '<span>🚀 เริ่มการถอดความ</span>';
  }

  if (btnNewJob) btnNewJob.addEventListener('click', resetMediaUI);

  async function cancelActiveJob() {
    if (!activeJobId) return;
    if (!confirm('❌ ยกเลิกงานนี้?\n\nข้อมูลการถอดความทั้งหมด และไฟล์ชั่วคราวจะถูกลบถาวร ไม่สามารถกู้คืนได้')) {
      return;
    }
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch(`/v1/media/transcribe/jobs/${activeJobId}`, { method: 'DELETE', headers });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (e2) {}
        throw new Error(detail);
      }
      resetToIdle('❌ ยกเลิกงานเรียบร้อยแล้ว (Cancelled)');
      alert('✅ ยกเลิกงานเรียบร้อยแล้ว');
    } catch (err) {
      alert(`❌ ยกเลิกงานล้มเหลว: ${err.message || err}`);
    }
  }

  if (cancelJobBtn) {
    cancelJobBtn.addEventListener('click', cancelActiveJob);
  }

  // --- Upload Form Handler ---
  mediaUploadForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!selectedFile) return;

    startJobBtn.disabled = true;
    jobProgressSection.style.display = 'block';
    resultSection.style.display = 'none';
    updateProgress(0, 'อัปโหลดไฟล์ขึ้นเซิร์ฟเวอร์...');
    updateStepper(1, 'queued');

    const formData = new FormData();
    formData.append('file', selectedFile);
    const languageSelect = document.getElementById('languageSelect');
    if (languageSelect) {
      formData.append('language', languageSelect.value);
    }

    const targetChunkInput = document.getElementById('targetChunkSec');
    if (targetChunkInput && targetChunkInput.value && parseFloat(targetChunkInput.value) > 0) {
      formData.append('target_chunk_sec', targetChunkInput.value);
    }
    const maxChunkInput = document.getElementById('maxChunkSec');
    if (maxChunkInput && maxChunkInput.value && parseFloat(maxChunkInput.value) > 0) {
      formData.append('max_chunk_sec', maxChunkInput.value);
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/v1/media/transcribe/jobs', true);

    const apiKey = getApiKey();
    if (apiKey) {
      xhr.setRequestHeader('x-api-key', apiKey);
    }

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percentComplete = Math.round((event.loaded / event.total) * 10.0);
        const speed = formatBytes(event.loaded);
        const total = formatBytes(event.total);
        updateProgress(percentComplete, `อัปโหลดไฟล์แล้ว (${speed} / ${total})...`);
      }
    };

    xhr.onload = () => {
      if (xhr.status === 202) {
        const data = JSON.parse(xhr.responseText);
        activeJobId = data.job_id;
        updateProgress(10, 'เริ่มการประมวลผลเบื้องหลัง...');
        startPollingJobStatus(activeJobId);
      } else {
        try {
          const errData = JSON.parse(xhr.responseText);
          alert(`เกิดข้อผิดพลาดในการสร้างงาน: ${errData.detail || 'Unknown error'}`);
        } catch (ex) {
          alert(`เกิดข้อผิดพลาดในการอัปโหลด (${xhr.status})`);
        }
    startJobBtn.disabled = false;
    selectedFile = null;
  }
    };

    xhr.onerror = () => {
      alert('การเชื่อมต่อเครือข่ายล้มเหลวขณะอัปโหลดไฟล์');
      startJobBtn.disabled = false;
    };

    xhr.send(formData);
  });

  function updateProgress(pct, stageText) {
    const rounded = Math.min(100, Math.max(0, Math.round(pct)));
    progressPctText.textContent = `${rounded}%`;
    progressBarFill.style.width = `${rounded}%`;
    if (stageText) {
      currentStageText.textContent = `⚙️ ${stageText}`;
    }
  }

  // --- Poll Job Status every 2 seconds ---
  function startPollingJobStatus(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
      try {
        const apiKey = getApiKey();
        const headers = {};
        if (apiKey) {
          headers['x-api-key'] = apiKey;
        }

        const res = await fetch(`/v1/media/transcribe/jobs/${jobId}`, { headers });
        if (!res.ok) return;

        const job = await res.json();
        updateProgress(job.progress_pct, job.current_stage || job.status);
        updateStepper(job.current_stage, job.status);
        updateCancelBtn(job.status);

        if (job.status === 'completed') {
          stopPolling();
          handleJobCompleted(job);
        } else if (job.status === 'failed') {
          stopPolling();
          alert(`กระบวนการถอดความล้มเหลว: ${job.error_message || 'Unknown error'}`);
          currentStageText.textContent = `❌ เกิดข้อผิดพลาด: ${job.error_message || 'Failed'}`;
          startJobBtn.disabled = false;
        }
      } catch (err) {
        console.error('Error polling job status:', err);
      }
    }, 2000);
  }

  function handleJobCompleted(job) {
    resultSection.style.display = 'block';
    resultText.textContent = job.result_text || '(ไม่มีข้อความที่ถอดได้)';

    statJobId.textContent = `🆔 Job ID: ${job.job_id.substring(0, 8)}...`;
    statDuration.textContent = `⏱️ ความยาววิดีโอ: ${formatSeconds(job.duration_seconds)}`;
    statElapsed.textContent = `⚡ เวลาประมวลผลรวม: ${formatSeconds(job.elapsed_seconds)}`;

    // Set export URLs with API key query param
    const apiKey = getApiKey();
    const keyParam = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : '';

    btnDownloadTxt.href = `/v1/media/transcribe/jobs/${job.job_id}/export/txt${keyParam}`;
    btnDownloadSrt.href = `/v1/media/transcribe/jobs/${job.job_id}/export/srt${keyParam}`;
    btnDownloadJson.href = `/v1/media/transcribe/jobs/${job.job_id}/export/json${keyParam}`;

    startJobBtn.disabled = false;
  }

  // Copy Result Text
  btnCopy.addEventListener('click', () => {
    if (resultText.textContent) {
      navigator.clipboard.writeText(resultText.textContent);
      btnCopy.textContent = '✅ คัดลอกแล้ว!';
      setTimeout(() => btnCopy.textContent = '📋 คัดลอก', 2000);
    }
  });
});
