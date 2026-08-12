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

  let selectedFile = null;
  let activeJobId = null;
  let pollInterval = null;

  // --- API Key Management ---
  function getApiKey() {
    return localStorage.getItem(API_KEY_STORAGE) || '';
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
          if (window.ModelLoadingDialog) window.ModelLoadingDialog.hide();
          stopPolling();
          handleJobCompleted(job);
        } else if (job.status === 'failed') {
          if (window.ModelLoadingDialog) window.ModelLoadingDialog.hide();
          stopPolling();
          alert(`กระบวนการถอดความล้มเหลว: ${job.error_message || 'Unknown error'}`);
          currentStageText.textContent = `❌ เกิดข้อผิดพลาด: ${job.error_message || 'Failed'}`;
          startJobBtn.disabled = false;
          mediaDropzone.style.display = '';
        }
      } catch (err) {
        console.error('Error polling job status:', err);
      }
    }, 2000);
  }

  let activeJobFilename = '';

  async function downloadFileWithAuth(url, defaultFilename) {
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch(url, { headers });
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
      if (disposition && disposition.includes('filename=')) {
        const match = disposition.match(/filename=["']?([^"';]+)["']?/);
        if (match && match[1]) filename = match[1];
      }

      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
    } catch (err) {
      alert(`❌ ดาวน์โหลดล้มเหลว: ${err.message || err}`);
    }
  }

  function handleJobCompleted(job) {
    resultSection.style.display = 'block';
    resultText.textContent = job.result_text || '(ไม่มีข้อความที่ถอดได้)';

    statJobId.textContent = `🆔 Job ID: ${job.job_id.substring(0, 8)}...`;
    statDuration.textContent = `⏱️ ความยาววิดีโอ: ${formatSeconds(job.duration_seconds)}`;
    statElapsed.textContent = `⚡ เวลาประมวลผลรวม: ${formatSeconds(job.elapsed_seconds)}`;

    activeJobId = job.job_id;
    activeJobFilename = (job.filename || job.job_id).replace(/\.[^/.]+$/, '');

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
