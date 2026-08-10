document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';

  const apiKeyInput = document.getElementById('apiKeyInput');
  const toggleApiKeyBtn = document.getElementById('toggleApiKeyBtn');
  const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
  const clearApiKeyLink = document.getElementById('clearApiKeyLink');

  const micBtn = document.getElementById('micBtn');
  const micIcon = document.getElementById('micIcon');
  const micStatus = document.getElementById('micStatus');
  const liveTranscript = document.getElementById('liveTranscript');
  const clearBtn = document.getElementById('clearBtn');
  const copyLiveBtn = document.getElementById('copyLiveBtn');
  const wsConnectionBadge = document.getElementById('wsConnectionBadge');
  const micSelect = document.getElementById('micSelect');
  const refreshMicsBtn = document.getElementById('refreshMicsBtn');
  const permissionNotice = document.getElementById('permissionNotice');
  const permissionText = document.getElementById('permissionText');
  const grantPermBtn = document.getElementById('grantPermBtn');
  const canvas = document.getElementById('visualizer');
  const canvasCtx = canvas.getContext('2d');

  let isRecording = false;
  let socket = null;
  let mediaRecorder = null;
  let audioStream = null;
  let audioContext = null;
  let analyser = null;
  let animFrameId = null;

  const MIC_STORAGE_KEY = 'typhoonAsrSelectedMic';

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

  function saveSelectedMic(deviceId) {
    try {
      if (deviceId) {
        localStorage.setItem(MIC_STORAGE_KEY, deviceId);
      } else {
        localStorage.removeItem(MIC_STORAGE_KEY);
      }
    } catch (e) {
      console.warn('ไม่สามารถบันทึกการเลือกไมโครโฟนได้:', e);
    }
  }

  micSelect.addEventListener('change', () => {
    saveSelectedMic(micSelect.value);
  });

  // Copy live transcript to clipboard
  copyLiveBtn.addEventListener('click', async () => {
    const textToCopy = liveTranscript.textContent;
    if (!textToCopy || textToCopy.includes('ข้อความจะปรากฏขึ้นที่นี่เมื่อคุณเริ่มพูด')) {
      alert('ไม่มีข้อความให้คัดลอก');
      return;
    }
    try {
      await navigator.clipboard.writeText(textToCopy);
      const originalText = copyLiveBtn.textContent;
      copyLiveBtn.textContent = '✅ คัดลอกแล้ว!';
      copyLiveBtn.style.color = 'var(--success)';
      setTimeout(() => {
        copyLiveBtn.textContent = originalText;
        copyLiveBtn.style.color = '';
      }, 2000);
    } catch (err) {
      alert('ไม่สามารถคัดลอกข้อความได้: ' + err.message);
    }
  });

  // Initialize permission check & microphones
  checkMicrophonePermission();

  grantPermBtn.addEventListener('click', () => {
    populateMicrophones(true);
  });

  refreshMicsBtn.addEventListener('click', () => {
    populateMicrophones(true);
  });

  // Automatically request/refresh device list when user interacts with mic dropdown
  micSelect.addEventListener('focus', () => {
    if (micSelect.options.length <= 1 || micSelect.options[0].textContent.includes('Default')) {
      populateMicrophones(true);
    }
  });

  async function checkMicrophonePermission() {
    if (navigator.permissions && navigator.permissions.query) {
      try {
        const status = await navigator.permissions.query({ name: 'microphone' });
        updatePermissionUI(status.state);
        
        if (status.state === 'granted') {
          populateMicrophones(true);
        } else {
          populateMicrophones(false);
        }

        status.onchange = () => {
          updatePermissionUI(status.state);
          if (status.state === 'granted') {
            populateMicrophones(true);
          }
        };
      } catch (e) {
        populateMicrophones(false);
      }
    } else {
      populateMicrophones(false);
    }
  }

  function updatePermissionUI(state) {
    if (state === 'granted') {
      permissionNotice.style.display = 'none';
    } else if (state === 'denied') {
      permissionNotice.style.display = 'block';
      permissionNotice.style.background = 'rgba(218, 54, 51, 0.15)';
      permissionNotice.style.border = '1px solid rgba(218, 54, 51, 0.4)';
      permissionText.innerHTML = '🚫 <strong>การเข้าถึงไมโครโฟนถูกปฏิเสธ:</strong> กรุณาเปิดอนุญาตให้เว็บไซต์ใช้งานไมโครโฟนในการตั้งค่าความเป็นส่วนตัวของเบราว์เซอร์ (Browser Privacy Settings)';
      grantPermBtn.style.display = 'none';
    } else { // 'prompt'
      permissionNotice.style.display = 'block';
      permissionNotice.style.background = 'rgba(255, 193, 7, 0.12)';
      permissionNotice.style.border = '1px solid rgba(255, 193, 7, 0.3)';
      permissionText.innerHTML = '⚠️ <strong>พบไมโครโฟนหลายรายการ:</strong> กดยินยอมสิทธิ์ใช้ไมค์เพื่อค้นหาและปลดล็อกชื่อไมโครโฟนทั้งหมดในเครื่อง';
      grantPermBtn.style.display = 'inline-flex';
    }
  }

  // Listen for hardware device changes (plugin/unplug)
  if (navigator.mediaDevices && navigator.mediaDevices.ondevicechange !== undefined) {
    navigator.mediaDevices.ondevicechange = () => populateMicrophones(true);
  }

  async function populateMicrophones(requestPermission = false) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      console.warn('MediaDevices API not supported in this browser.');
      return;
    }

    try {
      if (requestPermission) {
        // Trigger browser native permission prompt to reveal all physical devices & labels
        const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        tempStream.getTracks().forEach(track => track.stop());
        updatePermissionUI('granted');
      }

      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter(device => device.kind === 'audioinput');

      const hasLabels = audioInputs.some(d => d.label && d.label.length > 0);
      if (!hasLabels && !requestPermission) {
        updatePermissionUI('prompt');
      } else if (hasLabels) {
        updatePermissionUI('granted');
      }

      if (audioInputs.length > 0) {
        micSelect.innerHTML = '';
        let savedMicId = '';
        try {
          savedMicId = localStorage.getItem(MIC_STORAGE_KEY) || '';
        } catch (e) {
          savedMicId = '';
        }
        let matchedSaved = false;

        audioInputs.forEach((device, index) => {
          const option = document.createElement('option');
          option.value = device.deviceId;
          
          let labelName = device.label;
          if (!labelName || labelName.trim() === '') {
            labelName = `🎤 ไมโครโฟน ${index + 1} (${device.deviceId ? device.deviceId.slice(0, 8) + '...' : 'Default'})`;
          } else {
            labelName = `🎤 ${labelName}`;
          }
          
          option.textContent = labelName;
          if (savedMicId && device.deviceId === savedMicId) {
            option.selected = true;
            matchedSaved = true;
          }
          micSelect.appendChild(option);
        });

        if (!matchedSaved && savedMicId) {
          saveSelectedMic('');
        }
      } else {
        micSelect.innerHTML = '<option value="">🎙️ ไมโครโฟนเริ่มต้น (System Default Mic)</option>';
      }
    } catch (err) {
      console.warn('Could not enumerate audio devices:', err);
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        updatePermissionUI('denied');
      }
    }
  }

  let interimTimer = null;
  let confirmedText = '';
  let silenceStart = null;
  let lastCommitTime = Date.now();
  let hasSpeechSinceLastCommit = false; // Track active speech in current window

  const SILENCE_THRESHOLD = 0.015; // Energy RMS silence threshold
  const SILENCE_DURATION_MS = 600; // 600ms pause triggers boundary commit
  const MAX_SEGMENT_DURATION = 10000; // Force commit every 10s if continuously speaking

  // Web Audio API Frequency Waveform Visualizer & Smart VAD Silence Monitor
  function startVisualizer(stream) {
    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;

      const source = audioContext.createMediaStreamSource(stream);
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      const floatData = new Float32Array(analyser.fftSize);

      function draw() {
        animFrameId = requestAnimationFrame(draw);
        analyser.getByteFrequencyData(dataArray);

        // VAD Silence & Active Speech Monitor
        analyser.getFloatTimeDomainData(floatData);
        let sum = 0;
        for (let i = 0; i < floatData.length; i++) {
          sum += floatData[i] * floatData[i];
        }
        const rms = Math.sqrt(sum / floatData.length);
        const now = Date.now();

        if (rms >= SILENCE_THRESHOLD) {
          // User is actively speaking
          hasSpeechSinceLastCommit = true;
          silenceStart = null;

          if (now - lastCommitTime > MAX_SEGMENT_DURATION) {
            commitSegment();
            lastCommitTime = now;
            hasSpeechSinceLastCommit = false;
          }
        } else {
          // User is silent
          if (!silenceStart) silenceStart = now;
          else if (now - silenceStart > SILENCE_DURATION_MS) {
            // Commit only if there was active speech prior to this silence
            if (hasSpeechSinceLastCommit && (now - lastCommitTime > 1500)) {
              commitSegment();
              lastCommitTime = now;
              hasSpeechSinceLastCommit = false;
            }
          }
        }

        // Render Waveform Canvas
        canvasCtx.clearRect(0, 0, canvas.width, canvas.height);

        const barWidth = (canvas.width / bufferLength) * 1.8;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
          const barHeight = (dataArray[i] / 255) * (canvas.height - 10);

          const gradient = canvasCtx.createLinearGradient(0, canvas.height, 0, 0);
          gradient.addColorStop(0, '#00f2fe');
          gradient.addColorStop(0.5, '#4facfe');
          gradient.addColorStop(1, '#7f00ff');

          canvasCtx.fillStyle = gradient;
          canvasCtx.shadowColor = '#00f2fe';
          canvasCtx.shadowBlur = 8;
          canvasCtx.fillRect(x + 2, canvas.height - barHeight - 2, barWidth - 4, barHeight + 2);

          x += barWidth;
        }
      }

      draw();
    } catch (e) {
      console.warn('AudioContext visualizer error:', e);
    }
  }

  function commitSegment() {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send('COMMIT_SEGMENT');
    }
  }

  function stopVisualizer() {
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
    if (audioContext && audioContext.state !== 'closed') {
      audioContext.close();
      audioContext = null;
    }
    canvasCtx.clearRect(0, 0, canvas.width, canvas.height);
  }

  clearBtn.addEventListener('click', () => {
    confirmedText = '';
    liveTranscript.innerHTML = '<span style="color: var(--text-muted); font-style: italic;">ข้อความจะปรากฏขึ้นที่นี่เมื่อคุณเริ่มพูด...</span>';
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send('CLEAR');
    }
  });

  micBtn.addEventListener('click', () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  async function startRecording() {
    const selectedDeviceId = micSelect.value;
    const audioConstraints = selectedDeviceId
      ? { deviceId: { exact: selectedDeviceId } }
      : true;

    try {
      audioStream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
      updatePermissionUI('granted');
      populateMicrophones(true);
      startVisualizer(audioStream);
    } catch (err) {
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        updatePermissionUI('denied');
        alert('การเข้าถึงไมโครโฟนถูกปฏิเสธ กรุณายินยอมให้สิทธิ์ไมค์ในตั้งค่าเบราว์เซอร์');
      } else {
        alert('ไม่สามารถเข้าถึงไมโครโฟนได้: ' + err.message);
      }
      return;
    }

    // Connect WebSocket
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const apiKey = getApiKey();
    const keyParam = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : '';
    const wsUrl = `${wsProtocol}//${window.location.host}/v1/stream${keyParam}`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      wsConnectionBadge.textContent = '🔌 สถานะการเชื่อมต่อ: Connected';
      wsConnectionBadge.style.color = 'var(--accent-cyan)';
      wsConnectionBadge.style.borderColor = 'var(--accent-cyan)';

      confirmedText = '';
      lastCommitTime = Date.now();

      // Clear any previous session text on server
      socket.send('CLEAR');

      // Setup Continuous MediaRecorder
      mediaRecorder = new MediaRecorder(audioStream, { mimeType: getSupportedMimeType() });

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
          socket.send(event.data);
        }
      };

      // Stream continuous audio chunks every 250ms
      mediaRecorder.start(250);

      // Trigger interim partial transcription every 1000ms ONLY when user is actively speaking
      interimTimer = setInterval(() => {
        if (hasSpeechSinceLastCommit && socket && socket.readyState === WebSocket.OPEN) {
          socket.send('INTERIM');
        }
      }, 1000);

      isRecording = true;
      micBtn.classList.add('recording');
      micIcon.textContent = '⏹️';
      micStatus.textContent = '🔴 กำลังฟังและถอดความสด... (พูดได้เลย)';
      micStatus.style.color = '#ff416c';

      if (liveTranscript.querySelector('span')) {
        liveTranscript.textContent = '';
      }
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'final') {
          confirmedText = data.fullText || '';
          liveTranscript.innerHTML = confirmedText ||
            '<span style="color: var(--text-muted); font-style: italic;">กำลังฟัง...</span>';
        } else if (data.type === 'partial') {
          const partialWord = data.text ? `<span class="partial-text">${data.text}</span>` : '';
          liveTranscript.innerHTML = confirmedText
            ? (confirmedText + (partialWord ? ' ' + partialWord : ''))
            : (partialWord || '<span style="color: var(--text-muted); font-style: italic;">กำลังฟัง...</span>');
        }
      } catch (e) {
        console.error('Error parsing WS frame:', e);
      }
    };

    socket.onerror = (error) => {
      console.error('WebSocket Error:', error);
      wsConnectionBadge.textContent = '❌ สถานะการเชื่อมต่อ: Error';
      wsConnectionBadge.style.color = 'var(--danger)';
    };

    socket.onclose = () => {
      wsConnectionBadge.textContent = '🔌 สถานะการเชื่อมต่อ: Disconnected';
      wsConnectionBadge.style.color = 'var(--text-muted)';
      if (isRecording) {
        stopRecording();
      }
    };
  }

  function stopRecording() {
    isRecording = false;

    if (interimTimer) {
      clearInterval(interimTimer);
      interimTimer = null;
    }

    stopVisualizer();

    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }

    if (audioStream) {
      audioStream.getTracks().forEach(track => track.stop());
    }

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send('COMMIT_SEGMENT');
      socket.close();
    }

    micBtn.classList.remove('recording');
    micIcon.textContent = '🎙️';
    micStatus.textContent = 'คลิกปุ่มด้านบนเพื่อเริ่มฟังเสียงพูด';
    micStatus.style.color = 'var(--text-muted)';
  }

  function getSupportedMimeType() {
    const types = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/wav'
    ];
    for (const type of types) {
      if (MediaRecorder.isTypeSupported(type)) {
        return type;
      }
    }
    return '';
  }
});
