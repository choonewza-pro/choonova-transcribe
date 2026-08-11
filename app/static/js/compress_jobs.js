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
  const storageStats = document.getElementById('storageStats');

  let jobs = [];
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
    saveApiKeyBtn.addEventListener('click', async () => {
      const key = apiKeyInput ? apiKeyInput.value.trim() : '';
      if (!key) {
        alert('Please enter an API key before saving.');
        return;
      }
      localStorage.setItem(API_KEY_STORAGE, key);
      if (apiKeyInput) apiKeyInput.value = '';
      initApiKeyUI();
      await loadJobs();
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
    if (bytes == null || !bytes) return '-';
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  function formatSeconds(seconds) {
    if (!seconds || seconds <= 0) return '-';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
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
    processing: { cls: 'status-processing', label: 'กำลังบีบอัด' },
    completed: { cls: 'status-completed', label: 'เสร็จสมบูรณ์' },
    failed: { cls: 'status-failed', label: 'ล้มเหลว' }
  };

  function statusBadge(status) {
    const info = STATUS_MAP[status] || { cls: 'status-queued', label: status || '-' };
    return `<span class="status-badge ${info.cls}">${info.label}</span>`;
  }

  // --- Retention banner (last automatic cleanup by COMPRESS_RETENTION_HOURS) ---
  function escapeText(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (m) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[m]));
  }

  async function loadRetentionInfo() {
    const banner = document.getElementById('retentionBanner');
    if (!banner) return;
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;
      const res = await fetch('/v1/media/compress/retention', { headers });
      if (!res.ok) return;
      const info = await res.json();
      const hours = info.retention_hours || 0;
      const lastAt = info.last_cleanup_at ? formatDate(info.last_cleanup_at) : '';
      const count = info.last_cleanup_count || 0;
      const lastCleanup = lastAt
        ? `🕐 ล่าสุด: <strong>${escapeText(lastAt)}</strong>${count ? ` (${count} งาน)` : ''}`
        : '🕐 ยังไม่มีประวัติล้างไฟล์';
      banner.innerHTML = `
        <span class="retention-icon">🧹</span>
        <div class="retention-text">
          <div><strong>Retention Policy:</strong>
          ลบไฟล์บีบอัดอัตโนมัติหลัง
          <strong>${hours} ชม.</strong> — เก็บเฉพาะประวัติ</div>
          <div>${lastCleanup}</div>
        </div>`;
    } catch (e) {
      const el = document.getElementById('retentionLastCleanup');
      if (el && !el.textContent.trim()) el.textContent = 'ยังไม่มีประวัติล้างไฟล์';
    }
  }

  function isProcessing(status) {
    return ['queued', 'processing'].includes(status);
  }

  // --- List Loading ---
  async function loadJobs() {
    listMeta.textContent = 'กำลังโหลดรายการ...';
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch('/v1/media/compress/jobs?limit=50', { headers });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (e) {}
        throw new Error(detail);
      }

      jobs = await res.json();
      renderStorageStats();
      renderJobs();
      loadRetentionInfo();
    } catch (err) {
      listMeta.textContent = `❌ โหลดรายการไม่สำเร็จ: ${err.message || err}`;
      jobsCards.style.display = 'none';
      emptyState.style.display = 'block';
      emptyState.querySelector('p').textContent = `เกิดข้อผิดพลาด: ${err.message || err}`;
    }
  }

  function renderStorageStats() {
    if (!storageStats) return;
    let totalInput = 0, totalOutput = 0;
    jobs.forEach(j => {
      totalInput += j.file_size_bytes || 0;
      totalOutput += (j.status === 'completed' ? (j.output_size_bytes || 0) : 0);
    });
    const saved = Math.max(0, totalInput - totalOutput);
    const pct = totalInput > 0 ? Math.round((saved / totalInput) * 100) : 0;
    storageStats.innerHTML = `
      <span class="storage-stat">🗃️ พื้นที่ต้นฉบับรวม: ${formatBytes(totalInput)}</span>
      <span class="storage-stat">📦 ผลลัพธ์รวม: ${formatBytes(totalOutput)}</span>
      <span class="storage-stat">💾 ประหยัดไปแล้ว: ${formatBytes(saved)} (${pct}%)</span>
    `;
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
      emptyState.querySelector('p').textContent = 'ยังไม่มีงานบีบอัด — เริ่มจากหน้าบีบอัดวิดีโอได้เลย';
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
      const completed = job.status === 'completed';
      const outputExists = !!job.output_exists;
      const processing = isProcessing(job.status);

      const outputBadge = completed
        ? (outputExists
            ? '<span class="media-badge media-exists">✅ มีไฟล์ผลลัพธ์</span>'
            : '<span class="media-badge media-gone">🗑 ไฟล์ถูกลบแล้ว</span>')
        : '';

      let savingsBadge = '';
      if (completed && job.file_size_bytes && job.output_size_bytes) {
        const inSize = job.file_size_bytes;
        const outSize = job.output_size_bytes;
        const reduced = inSize - outSize;
        const pct = Math.round((reduced / inSize) * 100);
        savingsBadge = reduced > 0
          ? `<span class="savings-badge savings-good">💾 ลดลง ${pct}%</span>`
          : (pct === 0
              ? `<span class="savings-badge savings-none">➖ ขนาดเท่าเดิม</span>`
              : `<span class="savings-badge savings-none">⚠️ ใหญ่ขึ้น ${Math.abs(pct)}%</span>`);
      }

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

      const shortId = escapeHtml((job.job_id || '').substring(0, 8));
      const fileName = escapeHtml(job.filename || '-');
      const dims = job.input_width && job.input_height
        ? `${job.input_width}×${job.input_height}`
        : '-';
      const outDims = job.output_width && job.output_height
        ? `${job.output_width}×${job.output_height}`
        : '-';
      const encLabel = job.encoder === 'nvenc' ? '⚡ NVENC' : '💻 libx264';

      const downloadBtn = `<button type="button" class="btn-row" data-action="download" data-id="${job.job_id}" ${completed && outputExists ? '' : 'disabled title="ไม่มีไฟล์ผลลัพธ์"'} title="${completed && outputExists ? 'ดาวน์โหลดไฟล์ MP4 ที่บีบอัดแล้ว' : 'ไม่มีไฟล์ผลลัพธ์'}">📥 ดาวน์โหลด</button>`;
      const delOutputBtn = `<button type="button" class="btn-row btn-danger" data-action="del-output" data-id="${job.job_id}" ${completed && outputExists ? '' : 'disabled title="ไม่มีไฟล์ผลลัพธ์ให้ลบ"'} title="${completed && outputExists ? 'ลบเฉพาะไฟล์ผลลัพธ์ เพื่อประหยัดพื้นที่ (เก็บประวัติไว้)' : 'ไม่มีไฟล์ผลลัพธ์ให้ลบ'}">🗑 ลบไฟล์ผลลัพธ์</button>`;
      const delRowBtn = `<button type="button" class="btn-row btn-danger" data-action="del-row" data-id="${job.job_id}" title="ลบทั้งแถว (ประวัติ + ไฟล์ทั้งหมด)">❌ ลบรายการ</button>`;

      card.innerHTML = `
        <div class="job-card-header">
          <div class="job-card-title" title="${fileName}">${fileName}</div>
          ${statusBadge(job.status)}
        </div>
        <div class="job-card-id">🆔 ${shortId}…</div>
        ${extra}
        <div class="job-card-meta">
          <span class="job-card-meta-item">🎞️ ${dims}${completed ? ` → ${outDims}` : ''}</span>
          <span class="job-card-meta-item">⏱️ ${formatSeconds(job.duration_seconds)}</span>
          <span class="job-card-meta-item">📦 ${formatBytes(job.file_size_bytes)}${completed ? ` → ${formatBytes(job.output_size_bytes)}` : ''}</span>
          <span class="job-card-meta-item">${encLabel} · ${escapeHtml(job.preset || 'medium')}</span>
          ${job.bitrate_kbps ? `<span class="job-card-meta-item">🎛️ ${job.bitrate_kbps}kbps</span>` : ''}
          <span class="job-card-meta-item">⚡ ${formatSeconds(job.elapsed_seconds)}</span>
          <span class="job-card-meta-item">📅 ${formatDate(job.created_at)}</span>
        </div>
        <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">${outputBadge}${savingsBadge}</div>
        <div class="job-card-actions">
          ${downloadBtn}
          ${delOutputBtn}
          ${delRowBtn}
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
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.getAttribute('data-action');
    const jobId = btn.getAttribute('data-id');

    if (action === 'download') {
      await downloadOutput(jobId);
    } else if (action === 'del-output') {
      await deleteOutputOnly(jobId);
    } else if (action === 'del-row') {
      await deleteRow(jobId);
    }
  });

  async function downloadOutput(jobId) {
    try {
      const headers = {};
      const apiKey = getApiKey();
      if (apiKey) headers['x-api-key'] = apiKey;

      const res = await fetch(`/v1/media/compress/jobs/${jobId}/download`, { headers });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (e2) {}
        throw new Error(detail);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const job = jobs.find(j => j.job_id === jobId);
      const base = (job && job.filename) ? String(job.filename).replace(/\.[^/.]+$/, '') : jobId;
      const a = document.createElement('a');
      a.href = url;
      a.download = `${base}.mp4`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`❌ ดาวน์โหลดล้มเหลว: ${err.message || err}`);
    }
  }

  async function deleteOutputOnly(jobId) {
    const job = jobs.find(j => j.job_id === jobId);
    const filename = job ? job.filename : jobId;
    if (!confirm(`🗑 ลบไฟล์ผลลัพธ์ของ "${filename}" ?\n\nจะลบเฉพาะไฟล์ MP4 ที่บีบอัดแล้วเพื่อประหยัดพื้นที่\nประวัติการบีบอัด (ขนาด/ความละเอียด/อัตราการลด) จะถูกเก็บไว้`)) {
      return;
    }
    await doDelete(`/v1/media/compress/jobs/${jobId}/output`, jobId, 'ลบไฟล์ผลลัพธ์');
  }

  async function deleteRow(jobId) {
    const job = jobs.find(j => j.job_id === jobId);
    const filename = job ? job.filename : jobId;
    if (!confirm(`❌ ลบรายการ "${filename}" ?\n\nประวัติทั้งหมด และไฟล์ที่เกี่ยวข้องจะถูกลบถาวร ไม่สามารถกู้คืนได้`)) {
      return;
    }
    await doDelete(`/v1/media/compress/jobs/${jobId}`, jobId, 'ลบรายการ');
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
  if (btnRefresh) btnRefresh.addEventListener('click', loadJobs);

  loadRetentionInfo();
  loadJobs();
});
