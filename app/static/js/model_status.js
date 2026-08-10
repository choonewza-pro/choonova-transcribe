// Model VRAM residency status badge (header, all pages) + shared helpers for
// page-level "model loading..." progress UI.
(function () {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';

  const badgeEl = document.getElementById('modelStatusBadge');
  let last = { mode: 'always', typhoon: 'idle', whisper: 'idle' };
  let pollTimer = null;

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
    if (!badgeEl) return;
    const dot = (s) => `${STATE_DOT[s] || '⚪'} ${STATE_LABEL[s] || s}`;
    const modeLabel = MODE_LABEL[data.model_load_mode] || data.model_load_mode;
    badgeEl.innerHTML =
      `<span class="badge-dot" title="โหมด: ${modeLabel}">` +
      `🌀 Typhoon: ${dot(data.typhoon_model_state)} · ` +
      `🕊️ Whisper: ${dot(data.whisper_model_state)} · ` +
      `โหมด: ${data.model_load_mode}</span>`;
  }

  async function refresh() {
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

  if (badgeEl) {
    startPolling(3000);
  }
})();
