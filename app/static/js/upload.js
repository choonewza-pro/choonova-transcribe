document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';


  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('audioFileInput');
  const fileNameDisplay = document.getElementById('fileName');
  const transcribeBtn = document.getElementById('transcribeBtn');
  const uploadForm = document.getElementById('uploadForm');
  const statusMessage = document.getElementById('statusMessage');
  const resultText = document.getElementById('resultText');
  const copyResultBtn = document.getElementById('copyResultBtn');
  const statsBar = document.getElementById('statsBar');
  const statElapsed = document.getElementById('statElapsed');
  const statDuration = document.getElementById('statDuration');
  const statRtf = document.getElementById('statRtf');
  const timestampsCheck = document.getElementById('timestampsCheck');
  const timestampsBox = document.getElementById('timestampsBox');
  const timestampsJson = document.getElementById('timestampsJson');
  const audioPreview = document.getElementById('audioPreview');
  const playerStatus = document.getElementById('playerStatus');
  const cancelBtn = document.getElementById('cancelBtn');
  const newTranscribeBtn = document.getElementById('newTranscribeBtn');
  const diarizationCheck = document.getElementById('diarizationCheck');
  const diarizationOptions = document.getElementById('diarizationOptions');

  if (diarizationCheck && diarizationOptions) {
    diarizationCheck.addEventListener('change', () => {
      diarizationOptions.style.display = diarizationCheck.checked ? 'block' : 'none';
    });
  }

  let selectedFile = null;
  let activeController = null;
  let fileDialogActive = false;

  // --- API Key Management ---
  function getApiKey() {
    return localStorage.getItem(API_KEY_STORAGE) || '';
  }

  function updateTranscribeBtnState() {
    const hasKey = !!getApiKey();
    transcribeBtn.disabled = !hasKey;
    transcribeBtn.title = hasKey ? '' : 'กรุณาตั้งค่า API Key ในหน้า Settings ก่อนใช้งาน';
  }

  // Copy text to clipboard handler
  copyResultBtn.addEventListener('click', async () => {
    const textToCopy = resultText.textContent;
    if (!textToCopy || textToCopy.includes('ผลลัพธ์ข้อความภาษาไทยจะแสดงตรงนี้') || textToCopy.includes('กำลังแปลงเสียง')) {
      alert('ไม่มีข้อความให้คัดลอก');
      return;
    }
    try {
      await navigator.clipboard.writeText(textToCopy);
      const originalText = copyResultBtn.textContent;
      copyResultBtn.textContent = '✅ คัดลอกแล้ว!';
      copyResultBtn.style.color = 'var(--success)';
      setTimeout(() => {
        copyResultBtn.textContent = originalText;
        copyResultBtn.style.color = '';
      }, 2000);
    } catch (err) {
      alert('ไม่สามารถคัดลอกข้อความได้: ' + err.message);
    }
  });

  // Dropzone click triggers file input with cancel detection
  dropzone.addEventListener('click', () => {
    fileDialogActive = true;
    fileInput.value = '';
    fileInput.click();
  });

  // Detect file dialog cancel when focus returns but no file was selected
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

  // Drag & Drop handlers
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
    const maxAudioMb = parseFloat(uploadForm.dataset.maxAudioUploadMb) || 50;
    if (file.size > maxAudioMb * 1024 * 1024) {
      alert(`ไฟล์ใหญ่เกินไป! ขนาดสูงสุดที่อนุญาตคือ ${maxAudioMb} MB`);
      selectedFile = null;
      fileNameDisplay.textContent = `📁 ไม่มีไฟล์ (ขนาดเกิน ${maxAudioMb} MB)`;
      transcribeBtn.disabled = true;
      document.getElementById('audioPlayerContainer').style.display = 'none';
      return;
    }
    selectedFile = file;
    fileNameDisplay.textContent = `📁 ไฟล์ที่เลือก: ${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)`;
    transcribeBtn.disabled = false;

    // Load Audio Preview
    const fileURL = URL.createObjectURL(file);
    audioPreview.src = fileURL;
    document.getElementById('audioPlayerContainer').style.display = 'block';
    playerStatus.textContent = 'พร้อมเล่นไฟล์';
  }

  function clearFilePreview() {
    selectedFile = null;
    fileInput.value = '';
    fileNameDisplay.textContent = '📁 ลากไฟล์เสียงมาวางที่นี่ หรือ คลิกเพื่อเลือกไฟล์';
    transcribeBtn.disabled = true;
    document.getElementById('audioPlayerContainer').style.display = 'none';
    audioPreview.src = '';
    playerStatus.textContent = '';
  }

  // API Key state management
  updateTranscribeBtnState();
  window.addEventListener('storage', (e) => {
    if (e.key === API_KEY_STORAGE) updateTranscribeBtnState();
  });
  window.addEventListener('focus', updateTranscribeBtnState);

  // Submit form handler
  uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!selectedFile) return;
    if (!getApiKey()) {
      alert('กรุณาตั้งค่า API Key ในหน้า Settings ก่อนทำรายการ');
      return;
    }

    transcribeBtn.disabled = true;
    dropzone.style.display = 'none';
    cancelBtn.style.display = 'inline-flex';
    statusMessage.textContent = '⏳ กำลังส่งไฟล์และประมวลผลบน GPU...';
    statusMessage.style.color = 'var(--accent-cyan)';
    resultText.textContent = 'กำลังแปลงเสียงพูดเป็นข้อความ...';
    statsBar.style.display = 'none';
    timestampsBox.style.display = 'none';
    newTranscribeBtn.style.display = 'none';

    const formData = new FormData();
    formData.append('file', selectedFile);
    const languageSelect = document.getElementById('languageSelect');
    const selectedLang = languageSelect ? languageSelect.value : 'th';
    if (selectedLang === 'translate_en') {
      formData.append('language', 'auto');
      formData.append('task', 'translate');
      resultText.textContent = 'กำลังแปลเสียงพูดเป็นภาษาอังกฤษ...';
    } else {
      formData.append('language', selectedLang);
      formData.append('task', 'transcribe');
    }
    if (timestampsCheck.checked) {
      formData.append('with_timestamps', 'true');
    }
    if (diarizationCheck && diarizationCheck.checked) {
      formData.append('enable_diarization', 'true');
      const numSpeakersInput = document.getElementById('numSpeakersInput');
      if (numSpeakersInput && numSpeakersInput.value && parseInt(numSpeakersInput.value, 10) > 0) {
        formData.append('num_speakers', numSpeakersInput.value);
      }
      const minSpeakersInput = document.getElementById('minSpeakersInput');
      if (minSpeakersInput && minSpeakersInput.value && parseInt(minSpeakersInput.value, 10) > 0) {
        formData.append('min_speakers', minSpeakersInput.value);
      }
      const maxSpeakersInput = document.getElementById('maxSpeakersInput');
      if (maxSpeakersInput && maxSpeakersInput.value && parseInt(maxSpeakersInput.value, 10) > 0) {
        formData.append('max_speakers', maxSpeakersInput.value);
      }
    }

    const headers = {};
    const apiKey = getApiKey();
    if (apiKey) {
      headers['x-api-key'] = apiKey;
    }

    // If the target engine is not resident on VRAM yet, surface the cold-start
    // load progress so the user knows why the first request takes longer.
    activeController = new AbortController();
    const signal = activeController.signal;

    // Check if model loading dialog is needed
    const lang = (languageSelect && languageSelect.value) || 'th';
    const targetEngine = lang === 'th' ? 'typhoon' : 'whisper';
    let dialogShown = false;

    if (window.ModelStatus && window.ModelLoadingDialog) {
      const st = window.ModelStatus.getLast();
      if (st && st[targetEngine + '_model_state'] !== 'loaded') {
        dialogShown = true;
        window.ModelLoadingDialog.show({
          engine: targetEngine,
          title: `กำลังโหลดโมเดล ${targetEngine === 'typhoon' ? 'Typhoon ASR' : 'Whisper'} เข้า VRAM / RAM...`,
          onCancel: () => {
            if (activeController) {
              activeController.abort();
            }
          }
        });
      }
    }

    try {
      const response = await fetch('/v1/audio/transcribe', {
        method: 'POST',
        headers: headers,
        body: formData,
        signal: signal
      });

      if (window.ModelLoadingDialog) {
        window.ModelLoadingDialog.hide();
      }

      const data = await response.json();

      if (response.ok && data.status === 'success') {
        statusMessage.textContent = '✅ แปลงไฟล์เสียงสำเร็จ!';
        statusMessage.style.color = 'var(--success)';
        resultText.textContent = data.text || '(ไม่พบข้อความเสียงพูด)';
        newTranscribeBtn.style.display = 'inline-flex';

        // Update stats
        statsBar.style.display = 'flex';

        const elapsedVal = data.elapsed_seconds !== undefined ? data.elapsed_seconds : 0;
        const durationVal = data.duration_seconds !== undefined ? data.duration_seconds : 0;

        statElapsed.textContent = `⏱️ เวลาประมวลผล: ${elapsedVal.toFixed(3)}s`;
        statDuration.textContent = `🎵 ความยาวไฟล์เสียง: ${durationVal.toFixed(2)}s`;
        
        if (data.rtf !== null && data.rtf !== undefined) {
          const speedFactor = data.rtf > 0 ? (1 / data.rtf).toFixed(1) : '∞';
          statRtf.textContent = `⚡ ความเร็ว RTF: ${speedFactor}x (${data.rtf.toFixed(4)} RTF)`;
        }

        if (data.timestamps && data.timestamps.length > 0) {
          timestampsBox.style.display = 'block';
          timestampsJson.textContent = JSON.stringify(data.timestamps, null, 2);
        }
      } else {
        statusMessage.textContent = `❌ เกิดข้อผิดพลาด: ${data.detail || 'ไม่สามารถแปลงไฟล์เสียงได้'}`;
        statusMessage.style.color = 'var(--danger)';
        resultText.textContent = 'เกิดข้อผิดพลาดในการประมวลผล';
        dropzone.style.display = '';
      }
    } catch (err) {
      if (window.ModelLoadingDialog) {
        window.ModelLoadingDialog.hide();
      }
      dropzone.style.display = '';
      if (err.name === 'AbortError') {
        statusMessage.textContent = '❌ ยกเลิกการแปลงเรียบร้อยแล้ว (Cancelled)';
        statusMessage.style.color = 'var(--danger)';
        resultText.textContent = 'ยกเลิกการแปลงไฟล์เสียง';
      } else {
        statusMessage.textContent = '❌ ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้: ' + err.message;
        statusMessage.style.color = 'var(--danger)';
        resultText.textContent = 'เกิดข้อผิดพลาดในการเชื่อมต่อ';
      }
    } finally {
      activeController = null;
      cancelBtn.style.display = 'none';
      transcribeBtn.disabled = false;
    }
  });

  // Cancel button handler: abort the in-flight transcription request
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      if (activeController) {
        activeController.abort();
      }
    });
  }

  function resetUploadUI() {
    selectedFile = null;
    activeController = null;

    fileInput.value = '';
    fileNameDisplay.textContent = '📁 ลากไฟล์เสียงมาวางที่นี่ หรือ คลิกเพื่อเลือกไฟล์';
    dropzone.style.display = '';
    transcribeBtn.disabled = true;
    transcribeBtn.innerHTML = '<span>🚀 เริ่มแปลงไฟล์เสียง (Transcribe)</span>';
    cancelBtn.style.display = 'none';

    document.getElementById('audioPlayerContainer').style.display = 'none';
    audioPreview.src = '';
    playerStatus.textContent = '';

    statusMessage.textContent = '';
    statusMessage.style.color = '';
    resultText.textContent = '📁 ผลลัพธ์ข้อความภาษาไทยจะแสดงตรงนี้...';
    statsBar.style.display = 'none';
    timestampsBox.style.display = 'none';
  }

  if (newTranscribeBtn) newTranscribeBtn.addEventListener('click', resetUploadUI);
});
