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

  window.ModelStatus = {
    refresh: refresh,
    waitForReady: waitForReady,
    getLast: () => ({ ...last }),
    getApiKey: getApiKey,
    startPolling: startPolling,
  };

  if (getBadgeEl()) {
    startPolling(3000);
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      if (getBadgeEl()) startPolling(3000);
    });
  }
})();
