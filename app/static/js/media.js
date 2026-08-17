document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';


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
  const enableDiarizationCheck = document.getElementById('enableDiarization');
  const diarizationOptions = document.getElementById('diarizationOptions');

  // Speaker Diarization master switch (DIARIZATION_ENABLED / HF_TOKEN) from the page.
  const diarizationAvailable = !document.body || document.body.dataset.diarizationEnabled !== 'false';
  if (!diarizationAvailable && enableDiarizationCheck) {
    enableDiarizationCheck.checked = false;
    enableDiarizationCheck.disabled = true;
  }
  if (!diarizationAvailable && diarizationOptions) {
    diarizationOptions.style.display = 'none';
  }

  if (enableDiarizationCheck && diarizationOptions) {
    enableDiarizationCheck.addEventListener('change', () => {
      diarizationOptions.style.display = enableDiarizationCheck.checked ? 'flex' : 'none';
    });
  }

  function bindSpeakerMode() {
    const radios = document.querySelectorAll('input[name="speakerMode"]');
    const exactRow = document.getElementById('exactSpeakersRow');
    const rangeRow = document.getElementById('rangeSpeakersRow');
    function sync() {
      const checked = document.querySelector('input[name="speakerMode"]:checked');
      const mode = (checked && checked.value) || 'auto';
      if (exactRow) exactRow.style.display = mode === 'exact' ? 'flex' : 'none';
      if (rangeRow) rangeRow.style.display = mode === 'range' ? 'flex' : 'none';
    }
    radios.forEach(r => r.addEventListener('change', sync));
    sync();
  }

  function collectSpeakerParams(formData) {
    const checked = document.querySelector('input[name="speakerMode"]:checked');
    const mode = (checked && checked.value) || 'auto';
    const num = document.getElementById('numSpeakersInput');
    const min = document.getElementById('minSpeakersInput');
    const max = document.getElementById('maxSpeakersInput');
    if (mode === 'exact') {
      if (num && num.value && parseInt(num.value, 10) > 0) {
        formData.append('num_speakers', num.value);
      }
    } else if (mode === 'range') {
      if (min && min.value && parseInt(min.value, 10) > 0) {
        formData.append('min_speakers', min.value);
      }
      if (max && max.value && parseInt(max.value, 10) > 0) {
        formData.append('max_speakers', max.value);
      }
    }
  }

  bindSpeakerMode();

  let selectedFile = null;
  let activeJobId = null;
  let pollInterval = null;
  let fileDialogActive = false;

  // --- API Key Management ---
  function getApiKey() {
    return localStorage.getItem(API_KEY_STORAGE) || '';
  }

  function updateMediaBtnState() {
    const hasKey = !!getApiKey();
    startJobBtn.disabled = !hasKey;
    startJobBtn.title = hasKey ? '' : 'กรุณาตั้งค่า API Key ในหน้า Settings ก่อนใช้งาน';
  }

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
  mediaDropzone.addEventListener('click', () => {
    fileDialogActive = true;
    mediaFileInput.value = '';
    mediaFileInput.click();
  });

  // Detect file dialog cancel when focus returns but no file was selected
  window.addEventListener('focus', () => {
    if (fileDialogActive) {
      fileDialogActive = false;
      setTimeout(() => {
        if (!mediaFileInput.files || mediaFileInput.files.length === 0) {
          clearMediaPreview();
        }
      }, 0);
    }
  });

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
    fileDialogActive = false;
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

  function clearMediaPreview() {
    selectedFile = null;
    mediaFileInput.value = '';
    mediaFileName.textContent = '📹 ลากไฟล์วิดีโอ/ไฟล์เสียงมาวางที่นี่ หรือ คลิกเพื่อเลือกไฟล์';
    mediaFileSize.textContent = '';
    startJobBtn.disabled = true;
    mediaPreviewContainer.style.display = 'none';
    videoPreview.src = '';
    audioPreview.src = '';
  }

  // API Key state management
  updateMediaBtnState();
  window.addEventListener('storage', (e) => {
    if (e.key === API_KEY_STORAGE) updateMediaBtnState();
  });
  window.addEventListener('focus', updateMediaBtnState);

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
    } else if (status === 'transcribing' || stage === 'transcribing' || stage === 'diarizing') {
      step1.classList.add('completed');
      step2.classList.add('completed');
      step3.classList.add('completed');
      step4.classList.add('active');
    } else if (status === 'completed' || stage === 'completed') {
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
    mediaDropzone.style.display = '';
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
    mediaDropzone.style.display = '';
    mediaPreviewContainer.style.display = 'none';
    videoPreview.src = '';
    audioPreview.src = '';
    startJobBtn.disabled = true;
    startJobBtn.innerHTML = '<span>🚀 เริ่มการถอดความ</span>';
  }

  if (btnNewJob) btnNewJob.addEventListener('click', resetMediaUI);

  async function cancelActiveJob() {
    if (!activeJobId) return;
    const ok = await appConfirm('❌ ยกเลิกงานนี้?\n\nข้อมูลการถอดความทั้งหมด และไฟล์ชั่วคราวจะถูกลบถาวร ไม่สามารถกู้คืนได้');
    if (!ok) {
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
    if (!getApiKey()) {
      alert('กรุณาตั้งค่า API Key ในหน้า Settings ก่อนทำรายการ');
      return;
    }

    startJobBtn.disabled = true;
    mediaDropzone.style.display = 'none';
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
    const enableDiarizationCheck = document.getElementById('enableDiarization');
    if (enableDiarizationCheck && enableDiarizationCheck.checked) {
      formData.append('enable_diarization', 'true');
      collectSpeakerParams(formData);
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
        activeJobId = data.id;
        updateProgress(10, 'เริ่มการประมวลผลเบื้องหลัง...');


        startPollingJobStatus(activeJobId);
      } else {
        if (window.ModelLoadingDialog) window.ModelLoadingDialog.hide();
        try {
          const errData = JSON.parse(xhr.responseText);
          alert(`เกิดข้อผิดพลาดในการสร้างงาน: ${errData.detail || 'Unknown error'}`);
        } catch (ex) {
          alert(`เกิดข้อผิดพลาดในการอัปโหลด (${xhr.status})`);
        }
        startJobBtn.disabled = false;
        mediaDropzone.style.display = '';
        selectedFile = null;
      }
    };

    xhr.onerror = () => {
      if (window.ModelLoadingDialog) window.ModelLoadingDialog.hide();
      alert('การเชื่อมต่อเครือข่ายล้มเหลวขณะอัปโหลดไฟล์');
      startJobBtn.disabled = false;
      mediaDropzone.style.display = '';
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

  // --- Poll Job Status (throttled; skips work while tab is hidden) ---
  async function pollJobStatus(jobId) {
    try {
      const apiKey = getApiKey();
      const headers = {};
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      const res = await fetch(`/v1/media/transcribe/jobs/${jobId}`, { headers });
      if (!res.ok) return;

      const job = await res.json();
      updateProgress(job.progress, job.stage || job.status);
      updateStepper(job.stage, job.status);
      updateCancelBtn(job.status);


      if (job.status === 'completed') {
        if (window.ModelLoadingDialog) window.ModelLoadingDialog.hide();
        stopPolling();
        handleJobCompleted(job);
      } else if (job.status === 'failed') {
        if (window.ModelLoadingDialog) window.ModelLoadingDialog.hide();
        stopPolling();
        const errMsg = job.error ? job.error.message : 'Unknown error';
        alert(`กระบวนการถอดความล้มเหลว: ${errMsg}`);
        currentStageText.textContent = `❌ เกิดข้อผิดพลาด: ${errMsg}`;
        startJobBtn.disabled = false;
        mediaDropzone.style.display = '';
      }
    } catch (err) {
      console.error('Error polling job status:', err);
    }
  }

  function startPollingJobStatus(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollJobStatus(jobId);
    pollInterval = setInterval(() => {
      if (!document.hidden) pollJobStatus(jobId);
    }, 5000);
  }

  let activeJobFilename = '';

  async function downloadFileWithAuth(url, defaultFilename) {
    let cancelled = false;
    const controller = new AbortController();
    const overlay = _createDownloadOverlay(defaultFilename, () => {
      cancelled = true;
      controller.abort();
    });
    document.body.appendChild(overlay);
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch(url, { headers, signal: controller.signal });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (e2) {}
        throw new Error(detail);
      }

      let filename = defaultFilename;
      const disposition = res.headers.get('Content-Disposition');
      if (disposition) {
        const utf8Match = disposition.match(/filename\*=UTF-8''([^;\s]+)/);
        if (utf8Match && utf8Match[1]) {
          filename = decodeURIComponent(utf8Match[1]);
        } else if (disposition.includes('filename=')) {
          const asciiMatch = disposition.match(/filename=["']?([^"';]+)["']?/);
          if (asciiMatch && asciiMatch[1]) filename = asciiMatch[1];
        }
      }

      const fnEl = overlay.querySelector('.download-filename');
      if (fnEl) fnEl.textContent = filename;

      const total = parseInt(res.headers.get('Content-Length') || '0', 10);
      const reader = res.body.getReader();
      const chunks = [];
      let received = 0;
      const indeterminate = total === 0;
      const fill = overlay.querySelector('.progress-bar-fill');
      const pctText = overlay.querySelector('.download-progress-text');
      const container = overlay.querySelector('.progress-bar-container');

      if (indeterminate && container) {
        container.classList.add('download-progress-indeterminate');
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        if (!indeterminate && fill && pctText) {
          const pct = Math.round((received / total) * 100);
          fill.style.width = pct + '%';
          pctText.textContent = pct + '%';
        }
      }

      const blob = new Blob(chunks);
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
    } catch (err) {
      if (cancelled) return;
      alert(`❌ ดาวน์โหลดล้มเหลว: ${err.message || err}`);
    } finally {
      overlay.remove();
    }
  }

  function _createDownloadOverlay(filename, onCancel) {
    const dlg = document.createElement('div');
    dlg.className = 'model-loading-backdrop';
    dlg.innerHTML = [
      '<div class="download-progress-dialog">',
      '  <div class="download-progress-title">กำลังดาวน์โหลด...</div>',
      '  <div class="download-filename">' + filename.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') + '</div>',
      '  <div class="progress-bar-container">',
      '    <div class="progress-bar-fill" style="width:0%"></div>',
      '  </div>',
      '  <div class="download-progress-text">0%</div>',
      '  <button class="download-cancel-btn">ยกเลิก</button>',
      '</div>',
    ].join('');
    dlg.querySelector('.download-cancel-btn').addEventListener('click', function(e) {
      onCancel();
      dlg.remove();
    });
    return dlg;
  }

  function handleJobCompleted(job) {
    resultSection.style.display = 'block';
    resultText.textContent = job.result ? job.result.text : '(ไม่มีข้อความที่ถอดได้)';

    statJobId.textContent = `🆔 Job ID: ${job.id.substring(0, 8)}...`;
    statDuration.textContent = `⏱️ ความยาววิดีโอ: ${formatSeconds(job.duration)}`;
    statElapsed.textContent = `⚡ เวลาประมวลผลรวม: ${formatSeconds(job.processing_time)}`;

    activeJobId = job.id;
    activeJobFilename = (job.filename || job.id).replace(/\.[^/.]+$/, '');

    startJobBtn.disabled = false;
  }

  if (btnDownloadTxt) {
    btnDownloadTxt.addEventListener('click', () => {
      if (!activeJobId) return;
      const baseName = activeJobFilename || activeJobId;
      downloadFileWithAuth(`/v1/media/transcribe/jobs/${activeJobId}/export/txt`, `${baseName}.txt`);
    });
  }
  if (btnDownloadSrt) {
    btnDownloadSrt.addEventListener('click', () => {
      if (!activeJobId) return;
      const baseName = activeJobFilename || activeJobId;
      downloadFileWithAuth(`/v1/media/transcribe/jobs/${activeJobId}/export/srt`, `${baseName}.srt`);
    });
  }
  if (btnDownloadJson) {
    btnDownloadJson.addEventListener('click', () => {
      if (!activeJobId) return;
      const baseName = activeJobFilename || activeJobId;
      downloadFileWithAuth(`/v1/media/transcribe/jobs/${activeJobId}/export/json`, `${baseName}.json`);
    });
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
