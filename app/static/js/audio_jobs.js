document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';
  const common = window.TranscribeCommon;

  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('audioFileInput');
  const fileNameDisplay = document.getElementById('fileName');
  const startJobBtn = document.getElementById('startJobBtn');
  const audioJobsForm = document.getElementById('audioJobsForm');
  const cancelJobBtn = document.getElementById('cancelJobBtn');
  const newJobBtn = document.getElementById('newJobBtn');

  const jobProgressSection = document.getElementById('jobProgressSection');
  const currentStageText = document.getElementById('currentStageText');
  const progressPctText = document.getElementById('progressPctText');
  const progressBarFill = document.getElementById('progressBarFill');

  const statusMessage = document.getElementById('statusMessage');
  const resultText = document.getElementById('resultText');
  const copyResultBtn = document.getElementById('copyResultBtn');
  const copyJsonBtn = document.getElementById('copyJsonBtn');
  const jsonBox = document.getElementById('jsonBox');
  const resultJson = document.getElementById('resultJson');
  const statsBar = document.getElementById('statsBar');
  const statElapsed = document.getElementById('statElapsed');
  const statDuration = document.getElementById('statDuration');
  const statRtf = document.getElementById('statRtf');
  const timestampsCheck = document.getElementById('timestampsCheck');
  const timestampsBox = document.getElementById('timestampsBox');
  const timestampsJson = document.getElementById('timestampsJson');
  const audioPreview = document.getElementById('audioPreview');
  const playerStatus = document.getElementById('playerStatus');
  const languageSelect = document.getElementById('languageSelect');
  const modelSelect = document.getElementById('modelSelect');
  const diarizationCheck = document.getElementById('diarizationCheck');
  const diarizationOptions = document.getElementById('diarizationOptions');

  let selectedFile = null;
  let activeJobId = null;
  let pollInterval = null;
  let fileDialogActive = false;
  let isProcessing = false;

  function getApiKey() {
    return localStorage.getItem(API_KEY_STORAGE) || '';
  }

  function updateBtnState() {
    const hasKey = !!getApiKey();
    const hasFile = !!selectedFile;
    startJobBtn.disabled = !hasKey || !hasFile || isProcessing;
    startJobBtn.title = !hasKey
      ? 'กรุณาตั้งค่า API Key ในหน้า Settings ก่อนใช้งาน'
      : (!hasFile
        ? 'กรุณาเลือกไฟล์เสียงก่อน'
        : (isProcessing ? 'กำลังประมวลผล... (ยกเลิกได้ด้วยปุ่ม Cancel)' : ''));
  }

  // --- Model matrix (shared) ---
  if (common) {
    common.applyDiarizationAvailability(diarizationCheck);
    common.bindModelSelect(modelSelect, languageSelect, diarizationCheck);
  }
  if (diarizationCheck && diarizationOptions) {
    diarizationCheck.addEventListener('change', () => {
      diarizationOptions.style.display = diarizationCheck.checked ? 'block' : 'none';
    });
  }

  if (common) {
    common.bindSpeakerMode();
    common.bindTimestampHint();
  }

  // --- Dropzone & file selection ---
  dropzone.addEventListener('click', () => {
    fileDialogActive = true;
    fileInput.value = '';
    fileInput.click();
  });

  window.addEventListener('focus', () => {
    if (fileDialogActive) {
      fileDialogActive = false;
      setTimeout(() => {
        if (!fileInput.files || fileInput.files.length === 0) {
          clearFilePreview();
        }
      }, 0);
    }
  });

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dragover');
  });

  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener('change', (e) => {
    fileDialogActive = false;
    if (e.target.files.length > 0) {
      handleFileSelect(e.target.files[0]);
    }
  });

  function handleFileSelect(file) {
    const maxAudioMb = parseFloat(audioJobsForm.dataset.maxAudioUploadMb) || 50;
    if (file.size > maxAudioMb * 1024 * 1024) {
      alert(`ไฟล์ใหญ่เกินไป! ขนาดสูงสุดที่อนุญาตคือ ${maxAudioMb} MB`);
      selectedFile = null;
      fileNameDisplay.textContent = `📁 ไม่มีไฟล์ (ขนาดเกิน ${maxAudioMb} MB)`;
      updateBtnState();
      document.getElementById('audioPlayerContainer').style.display = 'none';
      return;
    }
    selectedFile = file;
    fileNameDisplay.textContent = `📁 ไฟล์ที่เลือก: ${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)`;
    updateBtnState();

    const fileURL = URL.createObjectURL(file);
    audioPreview.src = fileURL;
    document.getElementById('audioPlayerContainer').style.display = 'block';
    playerStatus.textContent = 'พร้อมเล่นไฟล์';
  }

  function clearFilePreview() {
    selectedFile = null;
    fileInput.value = '';
    fileNameDisplay.textContent = '📁 ลากไฟล์เสียงมาวางที่นี่ หรือ คลิกเพื่อเลือกไฟล์';
    updateBtnState();
    document.getElementById('audioPlayerContainer').style.display = 'none';
    audioPreview.src = '';
    playerStatus.textContent = '';
  }

  // API key state management
  updateBtnState();
  window.addEventListener('storage', (e) => {
    if (e.key === API_KEY_STORAGE) updateBtnState();
  });
  window.addEventListener('focus', updateBtnState);

  // --- Progress helpers ---
  function updateProgress(pct, stageText) {
    const rounded = Math.min(100, Math.max(0, Math.round(pct)));
    progressPctText.textContent = `${rounded}%`;
    progressBarFill.style.width = `${rounded}%`;
    if (stageText) {
      currentStageText.textContent = `⚙️ ${stageText}`;
    }
  }

  function isProcessingStatus(status) {
    return ['queued', 'processing'].includes(status);
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  function resetToIdle(message) {
    stopPolling();
    cancelJobBtn.style.display = 'none';
    currentStageText.textContent = message;
    isProcessing = false;
    updateBtnState();
    dropzone.style.display = '';
  }

  function resetUI() {
    stopPolling();
    resultText.textContent = 'ผลลัพธ์ข้อความภาษาไทยจะแสดงตรงนี้...';
    statsBar.style.display = 'none';
    timestampsBox.style.display = 'none';
    jsonBox.style.display = 'none';
    resultJson.textContent = '';
    jobProgressSection.style.display = 'none';
    statusMessage.textContent = '';
    statusMessage.style.color = '';
    cancelJobBtn.style.display = 'none';
    isProcessing = false;

    selectedFile = null;
    activeJobId = null;
    fileInput.value = '';
    fileNameDisplay.textContent = '📁 ลากไฟล์เสียงมาวางที่นี่ หรือ คลิกเพื่อเลือกไฟล์';
    dropzone.style.display = '';
    document.getElementById('audioPlayerContainer').style.display = 'none';
    audioPreview.src = '';
    playerStatus.textContent = '';
    newJobBtn.style.display = 'none';
    updateBtnState();
  }

  if (newJobBtn) newJobBtn.addEventListener('click', resetUI);

  async function cancelActiveJob() {
    if (!activeJobId) return;
    const ok = await appConfirm('❌ ยกเลิกงานนี้?\n\nข้อมูลการถอดความทั้งหมด และไฟล์ชั่วคราวจะถูกลบถาวร ไม่สามารถกู้คืนได้');
    if (!ok) return;
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

  if (cancelJobBtn) cancelJobBtn.addEventListener('click', cancelActiveJob);

  // --- Submit: create audio job ---
  audioJobsForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!selectedFile) return;
    if (!getApiKey()) {
      alert('กรุณาตั้งค่า API Key ในหน้า Settings ก่อนทำรายการ');
      return;
    }

    isProcessing = true;
    startJobBtn.disabled = true;
    dropzone.style.display = 'none';
    jobProgressSection.style.display = 'block';
    resultText.textContent = 'กำลังแปลงเสียงพูดเป็นข้อความ...';
    statsBar.style.display = 'none';
    timestampsBox.style.display = 'none';
    jsonBox.style.display = 'none';
    resultJson.textContent = '';
    statusMessage.textContent = '⏳ กำลังอัปโหลดไฟล์...';
    statusMessage.style.color = 'var(--accent-cyan)';
    updateProgress(0, 'อัปโหลดไฟล์ขึ้นเซิร์ฟเวอร์...');
    cancelJobBtn.style.display = 'none';

    const formData = new FormData();
    formData.append('file', selectedFile);
    const selectedLang = (languageSelect && languageSelect.value) || 'th';
    formData.append('language', selectedLang);
    if (modelSelect) {
      formData.append('model', modelSelect.value);
    }
    if (timestampsCheck.checked) {
      formData.append('with_timestamps', 'true');
    }
if (diarizationCheck && diarizationCheck.checked) {
        formData.append('enable_diarization', 'true');
        if (common) {
          common.collectSpeakerParams(formData);
        }
      }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/v1/audio/transcribe/jobs', true);

    const apiKey = getApiKey();
    if (apiKey) {
      xhr.setRequestHeader('x-api-key', apiKey);
    }

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const pct = Math.round((event.loaded / event.total) * 10.0);
        updateProgress(pct, `อัปโหลดไฟล์แล้ว (${(event.loaded / (1024 * 1024)).toFixed(2)} MB / ${(event.total / (1024 * 1024)).toFixed(2)} MB)...`);
      }
    };

    xhr.onload = () => {
      if (xhr.status === 202) {
        const data = JSON.parse(xhr.responseText);
        activeJobId = data.id;
        statusMessage.textContent = '✅ ไฟล์ถูกเข้ารับแล้ว กำลังรอคิวประมวลผล...';
        updateProgress(10, 'เริ่มการประมวลผลเบื้องหลัง (รอคิว)...');
        cancelJobBtn.style.display = 'inline-flex';
        startPolling(activeJobId);
      } else {
        let detail = `HTTP ${xhr.status}`;
        try {
          const errData = JSON.parse(xhr.responseText);
          detail = errData.detail || detail;
        } catch (ex) {}
        resetToIdle('❌ ไม่สามารถสร้างงานได้');
        alert(`เกิดข้อผิดพลาดในการสร้างงาน: ${detail}`);
      }
    };

    xhr.onerror = () => {
      resetToIdle('❌ เกิดข้อผิดพลาดในการเชื่อมต่อ');
      alert('การเชื่อมต่อเครือข่ายล้มเหลวขณะอัปโหลดไฟล์');
    };

    xhr.send(formData);
  });

  // --- Poll job status (throttled; skips work while the tab is hidden to
  // reduce continuous GPU compositing on the display adapter) ---
  async function pollJob(jobId) {
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch(`/v1/media/transcribe/jobs/${jobId}`, { headers });
      if (!res.ok) return;

      const job = await res.json();
      updateProgress(job.progress, job.stage || job.status);
      cancelJobBtn.style.display = isProcessingStatus(job.status) ? 'inline-flex' : 'none';

      if (job.status === 'completed') {
        stopPolling();
        handleJobCompleted(job);
      } else if (job.status === 'failed') {
        stopPolling();
        const errMsg = job.error ? (job.error.message || job.error.detail || 'Unknown error') : 'Unknown error';
        currentStageText.textContent = `❌ เกิดข้อผิดพลาด: ${errMsg}`;
        statusMessage.textContent = `❌ งานล้มเหลว: ${errMsg}`;
        statusMessage.style.color = 'var(--danger)';
        cancelJobBtn.style.display = 'none';
        isProcessing = false;
        dropzone.style.display = '';
        updateBtnState();
      } else if (job.status === 'cancelled') {
        stopPolling();
        resetToIdle('❌ ยกเลิกงานเรียบร้อยแล้ว (Cancelled)');
      }
    } catch (err) {
      console.error('Error polling job status:', err);
    }
  }

  function startPolling(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollJob(jobId);
    pollInterval = setInterval(() => {
      if (!document.hidden) pollJob(jobId);
    }, 5000);
  }

  // --- Render completed result ---
  function handleJobCompleted(job) {
    const result = job.result || {};
    const text = result.text || '(ไม่พบข้อความเสียงพูด)';
    const duration = job.duration || 0;
    const elapsed = job.processing_time || 0;
    const rtf = duration > 0 ? elapsed / duration : 0;
    const timestamps = result.segments || [];

    statusMessage.textContent = '✅ แปลงไฟล์เสียงสำเร็จ!';
    statusMessage.style.color = 'var(--success)';
    resultText.textContent = text;
    currentStageText.textContent = '✅ เสร็จสมบูรณ์ (Completed)';
    updateProgress(100, 'เสร็จสมบูรณ์');
    cancelJobBtn.style.display = 'none';

    statsBar.style.display = 'flex';
    statElapsed.textContent = `⏱️ เวลาประมวลผล: ${elapsed.toFixed(3)}s`;
    statDuration.textContent = `🎵 ความยาวไฟล์เสียง: ${duration.toFixed(2)}s`;
    if (rtf > 0) {
      const speedFactor = (1 / rtf).toFixed(1);
      statRtf.textContent = `⚡ ความเร็ว RTF: ${speedFactor}x (${rtf.toFixed(4)} RTF)`;
    } else {
      statRtf.textContent = `⚡ ความเร็ว RTF: ∞`;
    }

    if (timestamps.length > 0 && (timestampsCheck.checked || (diarizationCheck && diarizationCheck.checked))) {
      timestampsBox.style.display = 'block';
      timestampsJson.textContent = JSON.stringify(timestamps, null, 2);
    }

    const displayJson = {
      status: 'success',
      id: job.id,
      filename: job.filename,
      language: job.language,
      model: job.model || result.model || null,
      text: text,
      duration_seconds: duration,
      elapsed_seconds: elapsed,
      rtf: Number(rtf.toFixed(5)),
      timestamps: timestamps,
    };
    jsonBox.style.display = 'block';
    resultJson.textContent = JSON.stringify(displayJson, null, 2);

    isProcessing = false;
    newJobBtn.style.display = 'inline-flex';
    updateBtnState();
  }

  // --- Copy handlers ---
  copyResultBtn.addEventListener('click', () => {
    const textToCopy = resultText.textContent;
    if (!textToCopy || textToCopy.includes('ผลลัพธ์ข้อความภาษาไทยจะแสดงตรงนี้') || textToCopy.includes('กำลังแปลงเสียง')) {
      alert('ไม่มีข้อความให้คัดลอก');
      return;
    }
    if (common) {
      common.copyText(textToCopy, copyResultBtn);
    }
  });

  copyJsonBtn.addEventListener('click', () => {
    if (common) {
      common.copyText(resultJson.textContent, copyJsonBtn, { emptyMsg: 'ไม่มี JSON ให้คัดลอก' });
    }
  });
});