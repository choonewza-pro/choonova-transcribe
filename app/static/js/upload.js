document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';

  const apiKeyInput = document.getElementById('apiKeyInput');
  const toggleApiKeyBtn = document.getElementById('toggleApiKeyBtn');
  const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
  const clearApiKeyLink = document.getElementById('clearApiKeyLink');
  const keySavedBadge = document.getElementById('keySavedBadge');

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

  let selectedFile = null;

  // --- API Key Management ---
  function getApiKey() {
    return (apiKeyInput && apiKeyInput.value.trim()) || localStorage.getItem(API_KEY_STORAGE) || '';
  }

  function initApiKeyUI() {
    const saved = localStorage.getItem(API_KEY_STORAGE);
    if (saved) {
      if (keySavedBadge) {
        keySavedBadge.className = 'key-badge';
        keySavedBadge.textContent = '✓ Key active in browser';
      }
    } else {
      if (keySavedBadge) {
        keySavedBadge.className = 'key-badge required';
        keySavedBadge.textContent = '⚠️ API Key required';
      }
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

  // Dropzone click triggers file input
  dropzone.addEventListener('click', () => fileInput.click());

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
    if (e.target.files.length > 0) {
      handleFileSelect(e.target.files[0]);
    }
  });

  function handleFileSelect(file) {
    selectedFile = file;
    fileNameDisplay.textContent = `📁 ไฟล์ที่เลือก: ${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)`;
    transcribeBtn.disabled = false;

    // Load Audio Preview
    const fileURL = URL.createObjectURL(file);
    audioPreview.src = fileURL;
    document.getElementById('audioPlayerContainer').style.display = 'block';
    playerStatus.textContent = 'พร้อมเล่นไฟล์';
  }

  // Submit form handler
  uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!selectedFile) return;

    transcribeBtn.disabled = true;
    statusMessage.textContent = '⏳ กำลังส่งไฟล์และประมวลผลบน GPU...';
    statusMessage.style.color = 'var(--accent-cyan)';
    resultText.textContent = 'กำลังแปลงเสียงพูดเป็นข้อความ...';
    statsBar.style.display = 'none';
    timestampsBox.style.display = 'none';

    const formData = new FormData();
    formData.append('file', selectedFile);
    if (timestampsCheck.checked) {
      formData.append('with_timestamps', 'true');
    }

    const headers = {};
    const apiKey = getApiKey();
    if (apiKey) {
      headers['x-api-key'] = apiKey;
    }

    try {
      const response = await fetch('/v1/transcribe', {
        method: 'POST',
        headers: headers,
        body: formData
      });

      const data = await response.json();

      if (response.ok && data.status === 'success') {
        statusMessage.textContent = '✅ แปลงไฟล์เสียงสำเร็จ!';
        statusMessage.style.color = 'var(--success)';
        resultText.textContent = data.text || '(ไม่พบข้อความเสียงพูด)';

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
      }
    } catch (err) {
      statusMessage.textContent = '❌ ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้: ' + err.message;
      statusMessage.style.color = 'var(--danger)';
      resultText.textContent = 'เกิดข้อผิดพลาดในการเชื่อมต่อ';
    } finally {
      transcribeBtn.disabled = false;
    }
  });
});
