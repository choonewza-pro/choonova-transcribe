document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';

  const apiKeyInput = document.getElementById('apiKeyInput');
  const toggleApiKeyBtn = document.getElementById('toggleApiKeyBtn');
  const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
  const clearApiKeyLink = document.getElementById('clearApiKeyLink');

  const listMeta = document.getElementById('listMeta');
  const btnRefresh = document.getElementById('btnRefresh');
  const jobsCards = document.getElementById('jobsCards');
  const emptyState = document.getElementById('emptyState');
  const searchInput = document.getElementById('searchInput');
  const statusFilter = document.getElementById('statusFilter');
  const sortSelect = document.getElementById('sortSelect');

  const viewModal = document.getElementById('viewModal');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const modalTitle = document.getElementById('modalTitle');
  const modalResultText = document.getElementById('modalResultText');
  const modalErrorBox = document.getElementById('modalErrorBox');
  const btnCopy = document.getElementById('btnCopy');
  const btnDownloadTxt = document.getElementById('btnDownloadTxt');
  const btnDownloadSrt = document.getElementById('btnDownloadSrt');
  const btnDownloadJson = document.getElementById('btnDownloadJson');
  const statJobId = document.getElementById('statJobId');
  const statStatus = document.getElementById('statStatus');
  const statDuration = document.getElementById('statDuration');
  const statElapsed = document.getElementById('statElapsed');

  let jobs = [];
  let activeJobId = null;
  const state = { search: '', statusFilter: 'all', sortKey: 'created_at', sortDir: 'desc' };

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

  // --- Formatting Helpers ---
  function formatBytes(bytes) {
    if (!bytes) return '-';
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

  function formatDate(dateStr) {
    if (!dateStr) return '-';
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return dateStr;
      return d.toLocaleString('th-TH', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
      });
    } catch (e) {
      return dateStr;
    }
  }

  const STATUS_MAP = {
    queued: { cls: 'status-queued', label: 'รอคิว' },
    extracting: { cls: 'status-processing', label: 'กำลังสกัดเสียง' },
    chunking: { cls: 'status-processing', label: 'กำลังตัดแบ่ง' },
    transcribing: { cls: 'status-processing', label: 'กำลังถอดความ' },
    completed: { cls: 'status-completed', label: 'เสร็จสมบูรณ์' },
    failed: { cls: 'status-failed', label: 'ล้มเหลว' }
  };

  function statusBadge(status) {
    const info = STATUS_MAP[status] || { cls: 'status-queued', label: status || '-' };
    return `<span class="status-badge ${info.cls}">${info.label}</span>`;
  }

  function isProcessing(status) {
    return ['queued', 'extracting', 'chunking', 'transcribing'].includes(status);
  }

  // --- List Loading ---
  async function loadJobs() {
    listMeta.textContent = 'กำลังโหลดรายการ...';
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch('/v1/media/transcribe/jobs?limit=50&include_text=false', { headers });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (e) {}
        throw new Error(detail);
      }

      jobs = await res.json();
      renderJobs();
    } catch (err) {
      listMeta.textContent = `❌ โหลดรายการไม่สำเร็จ: ${err.message || err}`;
      jobsCards.style.display = 'none';
      emptyState.style.display = 'block';
      emptyState.querySelector('p').textContent = `เกิดข้อผิดพลาด: ${err.message || err}`;
    }
  }

  function applyFiltersAndSort() {
    const q = state.search.trim().toLowerCase();
    let list = jobs.filter(job => {
      if (q && !String(job.filename || '').toLowerCase().includes(q)) return false;
      if (state.statusFilter === 'completed' && job.status !== 'completed') return false;
      if (state.statusFilter === 'failed' && job.status !== 'failed') return false;
      if (state.statusFilter === 'processing' && !isProcessing(job.status)) return false;
      return true;
    });

    const key = state.sortKey;
    const dir = state.sortDir === 'asc' ? 1 : -1;
    list.sort((a, b) => {
      let va = a[key];
      let vb = b[key];
      if (key === 'status') {
        va = (STATUS_MAP[va] || {}).label || va || '';
        vb = (STATUS_MAP[vb] || {}).label || vb || '';
      }
      if (va == null) va = '';
      if (vb == null) vb = '';
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
      return String(va).localeCompare(String(vb), 'th') * dir;
    });
    return list;
  }

  function updateListMeta(count) {
    if (count === jobs.length) {
      listMeta.textContent = `แสดง ${count} รายการล่าสุด (กด 🔄 เพื่อรีเฟรช)`;
    } else {
      listMeta.textContent = `แสดง ${count} จาก ${jobs.length} รายการ (กรองแล้ว)`;
    }
  }

  function renderJobs() {
    const list = applyFiltersAndSort();
    jobsCards.innerHTML = '';

    if (!jobs || jobs.length === 0) {
      jobsCards.style.display = 'none';
      emptyState.style.display = 'block';
      emptyState.querySelector('p').textContent = 'ยังไม่มีรายการถอดความ — เริ่มจากหน้าถอดไฟล์เสียงและวีดีโอก่อนได้เลย';
      return;
    }
    if (list.length === 0) {
      jobsCards.style.display = 'none';
      emptyState.style.display = 'block';
      emptyState.querySelector('p').textContent = '🔍 ไม่พบรายการที่ตรงกับเงื่อนไขการค้นหา/กรอง';
      return;
    }

    jobsCards.style.display = 'grid';
    emptyState.style.display = 'none';

    list.forEach(job => {
      const card = document.createElement('div');
      card.className = 'job-card';
      const mediaExists = !!job.media_files_exist;
      const canView = job.status === 'completed';
      const processing = isProcessing(job.status);

      const mediaBadge = mediaExists
        ? '<span class="media-badge media-exists">✅ มีไฟล์</span>'
        : '<span class="media-badge media-gone">🗑 ถูกลบ</span>';

      const deleteMediaBtn = `<button type="button" class="btn-row btn-danger" data-action="del-media" data-id="${job.job_id}" ${mediaExists ? '' : 'disabled title="ไม่มีไฟล์ media บนเครื่อง"'} title="${mediaExists ? 'ลบเฉพาะไฟล์ media (เก็บข้อมูลถอดความ)' : 'ไม่มีไฟล์ media บนเครื่อง'}">🗑 ลบเฉพาะ media</button>`;
      const deleteRowBtn = `<button type="button" class="btn-row btn-danger" data-action="del-row" data-id="${job.job_id}" title="ลบทั้งแถว (ข้อมูลถอดความ + media)">❌ ลบทั้งแถว</button>`;
      const viewBtn = `<button type="button" class="btn-row" data-action="view" data-id="${job.job_id}" ${canView ? '' : 'disabled title="งานยังไม่เสร็จหรือล้มเหลว"'} title="${canView ? 'ดูข้อความถอดความ + export' : 'ดูได้เฉพาะงานที่เสร็จสมบูรณ์'}">👁 ดูถอดความ</button>`;

      const shortId = escapeHtml((job.job_id || '').substring(0, 8));
      const fileName = escapeHtml(job.filename || '-');
      const langMap = { th: '🇹🇭 ไทย', en: '🇬🇧 EN', auto: '🌐 อัตโนมัติ' };
      const langBadge = langMap[job.language] || '🇹🇭 ไทย';

      let extra = '';
      if (processing) {
        const pct = Math.min(100, Math.max(0, Math.round(job.progress_pct || 0)));
        extra = `
          <div class="job-progress">
            <div class="job-progress-label">
              <span>⏳ ${escapeHtml(job.current_stage || job.status)}</span>
              <span class="pct">${pct}%</span>
            </div>
            <div class="job-progress-track"><div class="job-progress-fill" style="width:${pct}%"></div></div>
          </div>`;
      } else if (job.status === 'failed' && job.error_message) {
        extra = `<div class="job-error">❌ ${escapeHtml(job.error_message)}</div>`;
      }

      card.innerHTML = `
        <div class="job-card-header">
          <div class="job-card-title" title="${fileName}">${fileName}</div>
          ${statusBadge(job.status)}
        </div>
        <div class="job-card-id">🆔 ${shortId}…</div>
        ${extra}
        <div class="job-card-meta">
          <span class="job-card-meta-item">🌐 ${langBadge}</span>
          <span class="job-card-meta-item">⏱️ ${formatSeconds(job.duration_seconds)}</span>
          <span class="job-card-meta-item">📦 ${formatBytes(job.file_size_bytes)}</span>
          <span class="job-card-meta-item">📅 ${formatDate(job.created_at)}</span>
        </div>
        <div class="job-card-media">${mediaBadge}</div>
        <div class="job-card-actions">
          ${viewBtn}
          ${deleteMediaBtn}
          ${deleteRowBtn}
        </div>
      `;

      jobsCards.appendChild(card);
    });

    updateListMeta(list.length);
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (m) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[m]));
  }

  // --- Card Actions (event delegation) ---
  jobsCards.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const action = btn.getAttribute('data-action');
    const jobId = btn.getAttribute('data-id');

    if (action === 'view') {
      await openViewModal(jobId);
    } else if (action === 'del-media') {
      await deleteMediaOnly(jobId);
    } else if (action === 'del-row') {
      await deleteRow(jobId);
    }
  });

  // --- View Transcript Modal ---
  async function openViewModal(jobId) {
    activeJobId = jobId;
    modalResultText.textContent = 'กำลังโหลดข้อความถอดความ...';
    modalResultText.style.display = 'block';
    modalErrorBox.style.display = 'none';
    statJobId.textContent = `🆔 Job ID: -`;
    statStatus.textContent = `📌 สถานะ: -`;
    statDuration.textContent = `⏱️ ความยาว: -`;
    statElapsed.textContent = `⚡ เวลาประมวลผลรวม: -`;
    viewModal.classList.add('open');

    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch(`/v1/media/transcribe/jobs/${jobId}`, { headers });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (err2) {}
        throw new Error(detail);
      }

      const job = await res.json();
      modalTitle.textContent = `📄 ดูข้อมูลการถอดความ — ${job.filename || jobId}`;
      modalResultText.textContent = job.result_text || '(ไม่มีข้อความที่ถอดได้)';
      statJobId.textContent = `🆔 Job ID: ${job.job_id.substring(0, 8)}...`;
      statStatus.textContent = `📌 สถานะ: ${(STATUS_MAP[job.status] || {}).label || job.status}`;
      statDuration.textContent = `⏱️ ความยาว: ${formatSeconds(job.duration_seconds)}`;
      statElapsed.textContent = `⚡ เวลาประมวลผลรวม: ${formatSeconds(job.elapsed_seconds)}`;

      // Export URLs
      btnDownloadTxt.href = `/v1/media/transcribe/jobs/${job.job_id}/export/txt`;
      btnDownloadSrt.href = `/v1/media/transcribe/jobs/${job.job_id}/export/srt`;
      btnDownloadJson.href = `/v1/media/transcribe/jobs/${job.job_id}/export/json`;
    } catch (err) {
      modalResultText.style.display = 'none';
      modalErrorBox.style.display = 'block';
      modalErrorBox.textContent = `❌ โหลดข้อมูลไม่สำเร็จ: ${err.message || err}`;
    }
  }

  function closeViewModal() {
    viewModal.classList.remove('open');
    activeJobId = null;
  }

  if (modalCloseBtn) modalCloseBtn.addEventListener('click', closeViewModal);
  viewModal.addEventListener('click', (e) => {
    if (e.target === viewModal) closeViewModal();
  });

  btnCopy.addEventListener('click', () => {
    if (modalResultText.textContent) {
      navigator.clipboard.writeText(modalResultText.textContent);
      btnCopy.textContent = '✅ คัดลอกแล้ว!';
      setTimeout(() => btnCopy.textContent = '📋 คัดลอก', 2000);
    }
  });

  // --- Delete: media only (keep transcription record) ---
  async function deleteMediaOnly(jobId) {
    const job = jobs.find(j => j.job_id === jobId);
    const filename = job ? job.filename : jobId;
    if (!confirm(`🗑 ลบเฉพาะไฟล์ media ของ "${filename}" ?\n\nข้อมูลการถอดความ (ข้อความ/SRT/timestamps) จะถูกเก็บไว้\nหมายเหตุ: งานที่เสร็จแล้ว media ถูกลบไปแล้วโดยอัตโนมัติ`)) {
      return;
    }
    await doDelete(`/v1/media/transcribe/jobs/${jobId}/media`, jobId, 'ลบเฉพาะ media');
  }

  // --- Delete: entire row (record + media) ---
  async function deleteRow(jobId) {
    const job = jobs.find(j => j.job_id === jobId);
    const filename = job ? job.filename : jobId;
    if (!confirm(`❌ ลบทั้งแถว "${filename}" ?\n\nข้อมูลการถอดความทั้งหมด และไฟล์ media ที่เกี่ยวข้องจะถูกลบถาวร ไม่สามารถกู้คืนได้`)) {
      return;
    }
    await doDelete(`/v1/media/transcribe/jobs/${jobId}`, jobId, 'ลบทั้งแถว');
  }

  async function doDelete(url, jobId, label) {
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch(url, { method: 'DELETE', headers });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (e2) {}
        throw new Error(detail);
      }

      alert(`✅ ${label} สำเร็จ`);
      if (activeJobId === jobId) closeViewModal();
      await loadJobs();
    } catch (err) {
      alert(`❌ ${label} ล้มเหลว: ${err.message || err}`);
    }
  }

  // --- Search / Filter / Sort ---
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      state.search = searchInput.value;
      renderJobs();
    });
  }
  if (statusFilter) {
    statusFilter.addEventListener('change', () => {
      state.statusFilter = statusFilter.value;
      renderJobs();
    });
  }
  if (sortSelect) {
    sortSelect.addEventListener('change', () => {
      const parts = sortSelect.value.split(':');
      state.sortKey = parts[0] || 'created_at';
      state.sortDir = parts[1] || 'desc';
      renderJobs();
    });
  }
  // --- Refresh ---
  if (btnRefresh) btnRefresh.addEventListener('click', loadJobs);

  // Initial load
  loadJobs();
});
