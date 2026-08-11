// Model VRAM residency settings card (homepage).
document.addEventListener('DOMContentLoaded', () => {
  const modeSelect = document.getElementById('settingsLoadMode');
  const timeoutInput = document.getElementById('settingsIdleTimeout');
  const timeoutWrap = document.getElementById('settingsTimeoutWrap');
  const saveBtn = document.getElementById('saveModelSettingsBtn');
  const statusEl = document.getElementById('settingsStatus');

  if (!modeSelect || !saveBtn || !statusEl) return;

  // --- API Key Management (homepage has no other JS to wire these) ---
  const API_KEY_STORAGE = 'typhoon_asr_api_key';
  const apiKeyInput = document.getElementById('apiKeyInput');
  const toggleApiKeyBtn = document.getElementById('toggleApiKeyBtn');
  const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
  const clearApiKeyLink = document.getElementById('clearApiKeyLink');

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
        const isPassword = apiKeyInput.type === 'password';
        apiKeyInput.type = isPassword ? 'text' : 'password';
        toggleApiKeyBtn.textContent = isPassword ? '🙈' : '👁️';
        toggleApiKeyBtn.title = isPassword ? 'ซ่อน API Key' : 'แสดง API Key';
      }
    });
  }

  initApiKeyUI();

  function getApiKey() {
    try {
      return localStorage.getItem(API_KEY_STORAGE) || '';
    } catch (e) {
      return '';
    }
  }

  function headers() {
    const h = { 'Content-Type': 'application/json' };
    const key = getApiKey();
    if (key) h['x-api-key'] = key;
    return h;
  }

  function stateLabel(s) {
    return { loaded: '🟢 พร้อมใช้งาน', loading: '🟡 กำลังโหลด', idle: '⚪ idle (ไม่โหลด)' }[s] || s;
  }

  function updateTimeoutEnabled() {
    const isIdle = modeSelect.value === 'idle';
    timeoutInput.disabled = !isIdle;
    timeoutInput.style.opacity = isIdle ? '1' : '0.45';
  }

  async function load() {
    try {
      const res = await fetch('/v1/settings/model', { headers: headers() });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      modeSelect.value = data.mode;
      timeoutInput.value = Math.round(data.idle_timeout_sec);
      updateTimeoutEnabled();
      statusEl.textContent =
        `สถานะปัจจุบัน: Typhoon ${stateLabel(data.typhoon_model_state)} · ` +
        `Whisper ${stateLabel(data.whisper_model_state)}`;
    } catch (e) {
      statusEl.textContent = `ไม่สามารถโหลดการตั้งค่าได้: ${e.message} — กรุณากรอก API Key ด้านบน`;
    }
  }

  let activeSettingsController = null;

  saveBtn.addEventListener('click', async () => {
    const mode = modeSelect.value;
    const payload = {
      mode: mode,
      idle_timeout_sec: Math.max(30, parseFloat(timeoutInput.value) || 900),
    };
    saveBtn.disabled = true;
    statusEl.textContent = '⏳ กำลังบันทึกการตั้งค่าโมเดล...';

    activeSettingsController = new AbortController();

    if (mode === 'always' && window.ModelLoadingDialog) {
      window.ModelLoadingDialog.show({
        engine: 'all',
        title: 'กำลังพรีโหลดโมเดลทั้งหมดเข้า VRAM / RAM...',
        onCancel: () => {
          if (activeSettingsController) {
            activeSettingsController.abort();
          }
        }
      });
    }

    try {
      const res = await fetch('/v1/settings/model', {
        method: 'PUT',
        headers: headers(),
        body: JSON.stringify(payload),
        signal: activeSettingsController.signal,
      });

      if (window.ModelLoadingDialog) window.ModelLoadingDialog.hide();

      if (!res.ok) {
        let detail = 'HTTP ' + res.status;
        try {
          detail = (await res.json()).detail || detail;
        } catch (e2) {}
        throw new Error(detail);
      }
      const data = await res.json();
      statusEl.textContent =
        `✅ บันทึกแล้ว: โหมด ${data.mode} (idle timeout ${Math.round(data.idle_timeout_sec)}s) · ` +
        `Typhoon ${stateLabel(data.typhoon_model_state)} · ` +
        `Whisper ${stateLabel(data.whisper_model_state)}`;
      if (window.ModelStatus) window.ModelStatus.refresh();
    } catch (e) {
      if (window.ModelLoadingDialog) window.ModelLoadingDialog.hide();
      if (e.name === 'AbortError') {
        statusEl.textContent = '❌ ยกเลิกการบันทึกการตั้งค่าเรียบร้อยแล้ว';
      } else {
        statusEl.textContent = `❌ บันทึกไม่สำเร็จ: ${e.message}`;
      }
    } finally {
      saveBtn.disabled = false;
    }
  });

  modeSelect.addEventListener('change', updateTimeoutEnabled);
  load();
});
