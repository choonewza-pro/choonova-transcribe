// Model VRAM residency status card (page top, all pages) + shared helpers for
// page-level "model loading..." progress UI.
(function () {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';

  let last = { mode: 'always', typhoon: 'idle', whisper: 'idle' };
  let pollTimer = null;

  function getBadgeEl() {
    return document.getElementById('modelStatusBadge');
  }

  const STATE_LABEL = { loaded: 'พร้อม', loading: 'กำลังโหลด', idle: 'idle' };
  const STATE_DOT = { loaded: '🟢', loading: '🟡', idle: '⚪' };
  const MODE_LABEL = {
    always: 'always (จองถาวร)',
    idle: 'idle (ปล่อย VRAM เมื่อว่าง)',
  };

  function getApiKey() {
    try {
      return localStorage.getItem(API_KEY_STORAGE) || '';
    } catch (e) {
      return '';
    }
  }

  async function fetchStatus() {
    try {
      const res = await fetch('/healthz', { cache: 'no-store' });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  function render(data) {
    last = data;
    const badgeEl = getBadgeEl();
    if (!badgeEl) return;
    const dot = (s) => `${STATE_DOT[s] || '⚪'} ${STATE_LABEL[s] || s}`;
    const modeLabel = MODE_LABEL[data.model_load_mode] || data.model_load_mode;
    badgeEl.innerHTML =
      `<div class="model-status-title">🌀 สถานะโมเดลบน VRAM</div>` +
      `<div class="model-status-body">` +
      `<span class="model-status-item">🌀 Typhoon: ${dot(data.typhoon_model_state)}</span>` +
      `<span class="model-status-item">🕊️ Whisper: ${dot(data.whisper_model_state)}</span>` +
      `<span class="model-status-item">⚙️ โหมด: ${modeLabel}</span>` +
      `</div>`;
  }

  function renderNoApiKey() {
    const badgeEl = getBadgeEl();
    if (!badgeEl) return;
    badgeEl.innerHTML =
      `<div class="model-status-title" style="color: #ff6b6b;">⚠️ ยังไม่ได้ตั้งค่า API Key</div>` +
      `<div class="model-status-body" style="text-align: center;">` +
      `<p style="margin: 0.25rem 0; color: var(--text-muted); font-size: 0.88rem;">กรุณาตั้งค่า API Key ก่อนใช้งานระบบ</p>` +
      `<a href="/setting" class="btn-primary" style="display: inline-block; padding: 0.45rem 1.2rem; text-decoration: none; font-size: 0.9rem; margin-top: 0.15rem;">⚙️ ไปที่หน้าตั้งค่า</a>` +
      `</div>`;
  }

  async function refresh() {
    if (!getApiKey()) {
      renderNoApiKey();
      return null;
    }
    const data = await fetchStatus();
    if (data) render(data);
    return data;
  }

  // Poll until the given engine ('typhoon' | 'whisper') reports 'loaded', then
  // fire cb. Returns the interval id (or null if already ready) so the caller
  // can clear it if the in-flight request is cancelled.
  function waitForReady(engine, cb) {
    const isReady = (d) => d && d[`${engine}_model_state`] === 'loaded';
    if (isReady(last)) {
      cb();
      return null;
    }
    return setInterval(async () => {
      const data = await fetchStatus();
      if (data) {
        render(data);
        if (isReady(data)) {
          clearInterval(intervalId);
          cb();
        }
      }
    }, 2000);
  }

  function startPolling(intervalMs) {
    refresh();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      if (document.hidden) return;
      refresh();
    }, intervalMs || 3000);
  }

  // ============================================================
  // Model Loading Dialog Modal Controller (Global)
  // ============================================================
  let dialogState = {
    active: false,
    timerId: null,
    pollId: null,
    startTime: 0,
    onCancel: null,
    targetEngine: 'auto',
  };

  const BADGE_CLASS = {
    loaded: 'badge-loaded',
    loading: 'badge-loading',
    idle: 'badge-idle',
  };

  const BADGE_LABEL = {
    loaded: '🟢 พร้อมใช้งาน',
    loading: '🟡 กำลังโหลดเข้า VRAM...',
    idle: '⚪ Idle (รอการโหลด)',
  };

  function updateModalBadges(data) {
    const typhoonBadge = document.getElementById('modelLoadingTyphoonBadge');
    const whisperBadge = document.getElementById('modelLoadingWhisperBadge');

    if (typhoonBadge && data.typhoon_model_state) {
      const state = data.typhoon_model_state;
      typhoonBadge.className = `status-badge ${BADGE_CLASS[state] || 'badge-idle'}`;
      typhoonBadge.textContent = BADGE_LABEL[state] || state;
    }

    if (whisperBadge && data.whisper_model_state) {
      const state = data.whisper_model_state;
      whisperBadge.className = `status-badge ${BADGE_CLASS[state] || 'badge-idle'}`;
      whisperBadge.textContent = BADGE_LABEL[state] || state;
    }
  }

  function formatTimer(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    const mm = String(mins).padStart(2, '0');
    const ss = String(secs).padStart(2, '0');
    return `${mm}:${ss}s`;
  }

  function showLoadingDialog(opts = {}) {
    const backdrop = document.getElementById('modelLoadingBackdrop');
    if (!backdrop) return;

    dialogState.active = true;
    dialogState.onCancel = typeof opts.onCancel === 'function' ? opts.onCancel : null;
    dialogState.targetEngine = opts.engine || 'auto';
    dialogState.startTime = Date.now();

    const titleEl = document.getElementById('modelLoadingTitle');
    const subtitleEl = document.getElementById('modelLoadingSubtitle');
    const timerEl = document.getElementById('modelLoadingTimer');

    if (titleEl && opts.title) titleEl.textContent = opts.title;
    if (subtitleEl && opts.subtitle) subtitleEl.textContent = opts.subtitle;
    if (timerEl) timerEl.textContent = '00:00s';

    // Show backdrop
    backdrop.style.display = 'flex';
    backdrop.setAttribute('aria-hidden', 'false');

    // Update initial status badges from last cached status
    updateModalBadges(last);

    // Timer tick
    if (dialogState.timerId) clearInterval(dialogState.timerId);
    dialogState.timerId = setInterval(() => {
      if (!dialogState.active) return;
      const elapsedSec = Math.floor((Date.now() - dialogState.startTime) / 1000);
      if (timerEl) timerEl.textContent = formatTimer(elapsedSec);
    }, 1000);

    // Poll /healthz frequently (every 1s) while modal is open
    if (dialogState.pollId) clearInterval(dialogState.pollId);
    dialogState.pollId = setInterval(async () => {
      if (!dialogState.active) return;
      const data = await fetchStatus();
      if (!data) return;

      render(data);
      updateModalBadges(data);

      // Check if target engine is loaded
      const target = dialogState.targetEngine;
      let ready = false;
      if (target === 'typhoon' && data.typhoon_model_state === 'loaded') ready = true;
      else if (target === 'whisper' && data.whisper_model_state === 'loaded') ready = true;
      else if (
        (target === 'auto' || target === 'all') &&
        (data.typhoon_model_state === 'loaded' || data.whisper_model_state === 'loaded')
      ) {
        ready = true;
      }

      if (ready && opts.autoClose !== false) {
        // Automatically hide modal once model is loaded
        hideLoadingDialog();
      }
    }, 1000);
  }

  function hideLoadingDialog() {
    dialogState.active = false;
    if (dialogState.timerId) {
      clearInterval(dialogState.timerId);
      dialogState.timerId = null;
    }
    if (dialogState.pollId) {
      clearInterval(dialogState.pollId);
      dialogState.pollId = null;
    }

    const backdrop = document.getElementById('modelLoadingBackdrop');
    if (backdrop) {
      backdrop.style.display = 'none';
      backdrop.setAttribute('aria-hidden', 'true');
    }
  }

  function cancelLoadingDialog() {
    const cancelCb = dialogState.onCancel;
    hideLoadingDialog();
    if (cancelCb) {
      try {
        cancelCb();
      } catch (e) {
        console.error('Error during ModelLoadingDialog cancel callback:', e);
      }
    }
  }

  // Setup DOM listener for Cancel button
  function initModalEvents() {
    const cancelBtn = document.getElementById('modelLoadingCancelBtn');
    if (cancelBtn) {
      cancelBtn.removeEventListener('click', cancelLoadingDialog);
      cancelBtn.addEventListener('click', cancelLoadingDialog);
    }
  }

  window.ModelLoadingDialog = {
    show: showLoadingDialog,
    hide: hideLoadingDialog,
    cancel: cancelLoadingDialog,
    isActive: () => dialogState.active,
  };

  window.ModelStatus = {
    refresh: refresh,
    waitForReady: waitForReady,
    getLast: () => ({ ...last }),
    getApiKey: getApiKey,
    startPolling: startPolling,
  };

  if (getBadgeEl()) {
    startPolling(3000);
    initModalEvents();
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      if (getBadgeEl()) startPolling(3000);
      initModalEvents();
    });
  }
})();

