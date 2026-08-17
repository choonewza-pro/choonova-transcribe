// API Endpoint Self-Test page client.
// Loads config via GET /v1/tests/info. Runs are owned by the server: POST
// /v1/tests/run returns a run_id immediately and the run executes in the
// background. This page watches the run by polling GET /v1/tests/runs/{id},
// reconnects to any active run on page load (survives refresh/disconnect),
// and lets you re-open past results from the recent-history bar.
document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';
  const POLL_MS = 5000;
  const startBtn = document.getElementById('startTestBtn');
  const cleanupToggle = document.getElementById('cleanupToggle');
  const testStatus = document.getElementById('testStatus');
  const assetPanel = document.getElementById('assetPanel');
  const limitPanel = document.getElementById('limitPanel');
  const progressPanel = document.getElementById('progressPanel');
  const progressLabel = document.getElementById('progressLabel');
  const progressPct = document.getElementById('progressPct');
  const progressFill = document.getElementById('progressFill');
  const resultsArea = document.getElementById('resultsArea');
  const summaryCard = document.getElementById('summaryCard');
  const watchBanner = document.getElementById('watchBanner');
  const historyPanel = document.getElementById('historyPanel');

  const SUITE_NAMES = {
    'word-diar': 'Word-level + ผู้พูด',
    'word-only': 'Word-level เท่านั้น',
    'no-word': 'ไม่มี Word-level',
    'sync': 'Sync /v1/audio/transcribe',
  };

  let running = false;
  let totalTests = null;
  let completedTests = 0;
  let selectedSuite = 'no-word';
  let activeRunId = null;
  let watchTimer = null;
  let renderedOrders = new Set();
  let suiteTestStatus = {};
  let diarizationEnabled = true;

  // Suite Card Click Handling
  const suiteCards = document.querySelectorAll('.suite-card');
  suiteCards.forEach(card => {
    card.addEventListener('click', () => {
      if (running) return;
      if (card.dataset.disabled) return;
      selectedSuite = card.dataset.suite || 'no-word';
      suiteCards.forEach(c => {
        c.classList.remove('active');
        c.style.borderColor = 'var(--card-border)';
      });
      card.classList.add('active');
      card.style.borderColor = 'var(--accent-cyan)';
    });
  });

  function getApiKey() {
    try { return localStorage.getItem(API_KEY_STORAGE) || ''; } catch (e) { return ''; }
  }

  function escapeText(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, m => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]
    ));
  }

  function formatBytes(b) {
    if (!b || b <= 0) return '-';
    const k = 1024, sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.min(sizes.length - 1, Math.floor(Math.log(b) / Math.log(k)));
    return parseFloat((b / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  function setStatus(msg) { if (testStatus) testStatus.textContent = msg; }

  function showBanner(msg, isError) {
    if (!watchBanner) return;
    watchBanner.style.display = msg ? 'block' : 'none';
    watchBanner.style.color = isError ? '#ff6b6b' : 'var(--accent-cyan)';
    watchBanner.textContent = msg || '';
  }

  function fractionText() {
    return totalTests ? `${completedTests}/${totalTests}` : String(completedTests);
  }

  function renderProgress(label, done) {
    if (!progressPanel) return;
    progressPanel.style.display = 'flex';
    progressPanel.style.flexDirection = 'column';
    const total = totalTests;
    const pct = total ? Math.round((done / total) * 100) : 0;
    progressLabel.textContent = label;
    progressPct.textContent = total ? `${pct}%` : '';
    progressFill.style.width = pct + '%';
  }

  function resetProgress() {
    totalTests = null;
    completedTests = 0;
    if (progressPanel) progressPanel.style.display = 'none';
    progressFill.style.width = '0%';
    progressPct.textContent = '';
  }

  function setRunning(state) {
    running = state;
    startBtn.disabled = state || !getApiKey();
    startBtn.textContent = state ? '⏳ กำลังทดสอบ...' : '▶ เริ่มทดสอบอัตโนมัติ';
  }

  function headers(extra) {
    const h = extra || {};
    const key = getApiKey();
    if (key) h['x-api-key'] = key;
    return h;
  }

  function refreshKeyState() {
    startBtn.disabled = running || !getApiKey();
    startBtn.title = getApiKey() ? '' : 'กรุณาตั้งค่า API Key ในหน้า Settings ก่อน';
  }

  async function loadInfo() {
    try {
      const res = await fetch('/v1/tests/info', { headers: headers() });
      if (res.status === 401 || res.status === 403) {
        assetPanel.innerHTML = '<div style="color:#ff6b6b;">❌ ยังไม่ได้ตั้งค่า API Key — ไปที่หน้า '
          + '<a href="/setting" style="color:var(--accent-cyan);">ตั้งค่า</a> แล้วกรอก GATEWAY_API_KEY ก่อน</div>';
        refreshKeyState();
        return;
      }
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const info = await res.json();
      renderInfo(info);
    } catch (e) {
      assetPanel.innerHTML = '<div style="color:#ff6b6b;">ไม่สามารถโหลดข้อมูลการทดสอบ: ' + escapeText(e.message) + '</div>';
    }
  }

  function renderInfo(info) {
    const a = info.assets || {};
    const parts = Object.values(a).map(f => (
      `<span class="stats-badge" style="color:#00f2fe; border-color:rgba(0,242,254,0.3);">`
      + `${escapeText(f.filename)} — ${f.exists ? formatBytes(f.size_bytes) : '❌ ไม่พบ'}</span>`
    )).join(' ');
    assetPanel.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; margin-bottom:0.35rem;">
      📁 ไฟล์ทดสอบ (${escapeText((info.assets_dir || '').replace(/\\\\/g, '/'))}):</div>
      <div style="display:flex; flex-wrap:wrap; gap:0.5rem;">${parts}</div>`;
    const d = info.defaults || {}, l = info.limits || {};
    limitPanel.innerHTML =
      `⚙️ ภาษาที่ทดสอบ: <code>${escapeText(d.language || 'th')}</code>`
      + ` · ขีดจำกัด: transcribe <code>${l.transcribe_max_wait_sec}s</code>`
      + (info.diarization_enabled === false ? ' · สถานะ Diarization: <code>ปิดอยู่</code>' : '');
    diarizationEnabled = info.diarization_enabled !== false;
    applyDiarizationAvailability();
    renderSuiteStatuses(info);
  }

  function applyDiarizationAvailability() {
    const card = document.querySelector('.suite-card[data-suite="word-diar"]');
    if (!card) return;
    if (diarizationEnabled) {
      card.dataset.disabled = '';
      card.style.opacity = '';
      card.style.cursor = '';
      const note = card.querySelector('.diar-disabled-note');
      if (note) note.remove();
      return;
    }
    card.dataset.disabled = 'true';
    card.style.opacity = '0.55';
    card.style.cursor = 'not-allowed';
    if (card.querySelector('.diar-disabled-note')) return;
    const note = document.createElement('div');
    note.className = 'diar-disabled-note';
    note.style.cssText = 'font-size:0.78rem; color:#ff9d2e; border:1px solid rgba(255,157,46,0.4);'
      + ' border-radius:6px; padding:0.35rem 0.5rem; margin-top:0.6rem; line-height:1.4;';
    note.textContent = '⛔ ปิดอยู่ — Diarization ต้องมี HF_TOKEN (หรือวาง PyAnnote models ใน models/) และเปิด DIARIZATION_ENABLED=true';
    card.appendChild(note);
  }

  function renderSuiteStatuses(info) {
    suiteTestStatus = info.test_status || {};
    const statusMap = info.status || {};
    document.querySelectorAll('.suite-status').forEach(el => {
      const suite = el.dataset.suite;
      const st = statusMap[suite] || 'not_tested';
      const rows = Object.values(suiteTestStatus[suite] || {});
      const passed = rows.filter(r => r.status === 'passed').length;
      const total = rows.length;
      const times = rows.map(r => r.updated_at).filter(Boolean).sort();
      const lastTime = times[times.length - 1] || '';
      let txt, color;
      if (st === 'passed') {
        txt = `✅ ผ่านการตรวจสอบแล้ว (${passed}/${total})`;
        color = '#34d399';
      } else if (st === 'failed') {
        txt = `❌ ยังไม่ผ่าน (${passed}/${total})`;
        color = '#ff6b6b';
      } else {
        txt = '⚪ ยังไม่ได้ทดสอบ';
        color = 'var(--text-muted)';
      }
      el.textContent = txt;
      el.style.color = color;
      el.title = lastTime ? `ทดสอบล่าสุด: ${lastTime}` : '';
    });
  }

  // ---------------------------------------------------------------- rendering

  function newTestCard(test) {
    const card = document.createElement('div');
    card.className = 'api-group-card';
    card.dataset.path = test.path;
    card.style.marginBottom = '1rem';
    const ok = test.passed;
    const badgeClass = ok ? 'badge-loaded' : 'badge-delete';
    const ball = ok ? '✅' : '❌';
    card.innerHTML = `
      <div class="api-group-header">
        <span class="api-group-icon">${test.method === 'POST' ? '📮' : test.method === 'DELETE' ? '🗑️' : '🔎'}</span>
        <div style="flex:1; min-width:0;">
          <div class="api-group-title" style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
            <span class="status-badge ${badgeClass}" style="padding:0.15rem 0.5rem;">${ball} ${ok ? 'PASS' : 'FAIL'}</span>
            <span class="endpoint-badge badge-${test.method.toLowerCase()}">${test.method}</span>
            <code style="font-size:0.85rem; word-break:break-all;">${escapeText(test.path)}</code>
          </div>
          <p class="api-group-desc" style="margin:0.2rem 0 0 0;">${test.order}. ${escapeText(test.name_th)}
            <span style="color:var(--text-muted);">· HTTP ${test.status_code} · ${test.elapsed_sec}s</span>
            ${test.error_msg ? ' <span style="color:#ff6b6b;">· ' + escapeText(test.error_msg) + '</span>' : ''}
          </p>
          <div class="prog" style="display:none; margin-top:0.4rem;">
            <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.25rem; color:var(--accent-cyan); font-size:0.78rem; font-weight:600;">
              <span class="prog-label">⏳ กำลังประมวลผลอยู่...</span>
              <span class="prog-stage" style="color:var(--text-muted); font-weight:400;"></span>
            </div>
            <div style="height:6px; border-radius:3px; background:rgba(255,255,255,0.08); overflow:hidden;">
              <div class="prog-fill" style="width:0%; height:100%; background:#00f2fe; transition:width .4s;"></div>
            </div>
          </div>
        </div>
      </div>
      <details class="api-endpoint" style="margin-top:0.5rem;">
        <summary><span style="font-size:0.85rem;">รายละเอียดผลตรวจ (fields)</span><span class="api-chevron">▾</span></summary>
        <div class="api-endpoint-body">
          <table id="checkTable" style="width:100%; border-collapse:collapse; font-size:0.85rem;"></table>
        </div>
      </details>`;
    return card;
  }

  function renderFieldChecks(card, field_checks) {
    const table = card.querySelector('#checkTable');
    const rows = field_checks.map(c => {
      const ball = c.passed ? '✅' : '❌';
      let val = c.value;
      if (Array.isArray(val)) val = `[array ×${val.length}]`;
      else if (val && typeof val === 'object') val = '{…}';
      else if (val != null) val = String(val);
      else val = c.present ? 'null' : '(ไม่มี)';
      if (String(val).length > 140) val = String(val).slice(0, 140) + '…';
      return `<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
        <td style="padding:0.35rem 0.6rem;"><code>${escapeText(c.name)}</code></td>
        <td style="padding:0.35rem 0.6rem; color:var(--text-muted);">${escapeText(c.type)}</td>
        <td style="padding:0.35rem 0.6rem; text-align:center;">${ball}</td>
        <td style="padding:0.35rem 0.6rem; color:var(--text-main); word-break:break-all;">${escapeText(val)}</td>
        <td style="padding:0.35rem 0.6rem; color:${c.passed ? 'var(--text-muted)' : '#ff6b6b'};">${escapeText(c.note)}</td>
      </tr>`;
    }).join('');
    const header = `<thead><tr style="text-align:left; color:var(--text-muted);">
      <th style="padding:0.35rem 0.6rem;">Field</th><th style="padding:0.35rem 0.6rem;">Type</th>
      <th style="padding:0.35rem 0.6rem;">ผ่าน</th><th style="padding:0.35rem 0.6rem;">ค่าที่ได้</th>
      <th style="padding:0.35rem 0.6rem;">หมายเหตุ</th></tr></thead>`;
    table.innerHTML = header + `<tbody>${rows}</tbody>`;
  }

  function appendTest(test) {
    const card = newTestCard(test);
    renderFieldChecks(card, test.field_checks);
    resultsArea.appendChild(card);
    if (test.inputs && test.inputs.length) {
      const details = card.querySelector('details');
      const pre = document.createElement('div');
      pre.className = 'code-container';
      pre.style.marginTop = '0.5rem';
      const lines = test.inputs.map(i =>
        `<span style="color:var(--text-muted);">· ${escapeText(i.name)}</span> <code>${escapeText(describeInput(i))}</code>`);
      pre.innerHTML = `<div class="code-header">Input ที่ส่ง (โดยประมาณ)</div><div style="padding:0.6rem 0.9rem;">${lines.join('<br>')}</div>`;
      details.querySelector('.api-endpoint-body').prepend(pre);
    }
    return card;
  }

  function describeInput(i) {
    if (i.kind === 'file') return i.value;
    if (i.name === 'x-api-key' || /key/i.test(i.name)) return '••••';
    return i.value == null ? '' : String(i.value);
  }

  function showProgress(prog) {
    const path = prog.path || '';
    const card = resultsArea.querySelector(`[data-path="${CSS.escape(path)}"]`);
    if (!card) return;
    const progWrap = card.querySelector('.prog');
    const fill = card.querySelector('.prog-fill');
    const label = card.querySelector('.prog-label');
    const stage = card.querySelector('.prog-stage');
    if (progWrap) {
      progWrap.style.display = 'block';
      progWrap.classList.add('processing');
    }
    const pct = Number.isFinite(Number(prog.progress)) ? Math.round(Number(prog.progress)) : 0;
    if (fill) fill.style.width = (pct > 0 ? pct : 6) + '%';
    if (label) label.textContent = '⏳ กำลังประมวลผลอยู่...';
    if (stage) {
      const s = prog.stage || prog.status || '';
      stage.textContent = s ? `(${escapeText(s)})` : '';
    }
    const stageTxt = (prog.status || '') + (prog.stage ? ' — ' + prog.stage : '');
    setStatus(`⏳ poll: ${path.replace(/^.*\/(jobs)/, '/$1')} (${escapeText(stageTxt)} ${pct}%)`);
    renderProgress(`⏳ กำลังประมวลผล... (${fractionText()}) · ${escapeText(stageTxt)}`, completedTests);
  }

  function addPriorPassedTag(card) {
    // Small persistent marker: this card's test passed in a previous run
    // (status persisted in SQLite, survives server restart).
    if (!card) return;
    const title = card.querySelector('.api-group-desc');
    if (!title || title.querySelector('.prior-passed')) return;
    const tag = document.createElement('span');
    tag.className = 'prior-passed';
    tag.textContent = '✅ เคยผ่านการตรวจสอบแล้ว';
    tag.style.cssText = 'font-size:0.72rem; color:#34d399; border:1px solid rgba(52,211,153,0.4);'
      + ' border-radius:6px; padding:0.05rem 0.4rem; margin-left:0.5rem; white-space:nowrap;';
    title.appendChild(tag);
  }

  function setProcessingIndicator(snapshot) {
    // Show/hide an animated "กำลังประมวลผลอยู่" bar under the last completed
    // test card while the run is actively polling a job.
    const cards = resultsArea.querySelectorAll('.api-group-card');
    const last = cards[cards.length - 1];
    if (!last) return;
    const progWrap = last.querySelector('.prog');
    if (!progWrap) return;
    if (snapshot.status === 'running') {
      const p = snapshot.latest_progress || {};
      const pct = Number.isFinite(Number(p.progress)) ? Math.round(Number(p.progress)) : 0;
      progWrap.style.display = 'block';
      progWrap.classList.add('processing');
      const fill = last.querySelector('.prog-fill');
      if (fill) fill.style.width = (pct > 0 ? pct : 6) + '%';
      const label = last.querySelector('.prog-label');
      if (label) label.textContent = '⏳ กำลังประมวลผลอยู่...';
      const stage = last.querySelector('.prog-stage');
      if (stage) {
        const s = p.stage || p.status || '';
        stage.textContent = s ? `(${escapeText(s)})` : '';
      }
    } else {
      progWrap.style.display = 'none';
      progWrap.classList.remove('processing');
    }
  }

  function renderSummary(summary) {
    if (!summary || summary.error) {
      summaryCard.style.display = 'block';
      summaryCard.innerHTML = '<h3 style="color:#ff6b6b;">❌ เกิดข้อผิดพลาดระหว่างทดสอบ</h3>'
        + `<p style="color:var(--text-muted);">${escapeText(summary?.error || '')}</p>`;
      return;
    }
    const ok = summary.overall_passed;
    summaryCard.style.display = 'block';
    summaryCard.innerHTML = `
      <div style="display:flex; align-items:center; gap:1rem; flex-wrap:wrap;">
        <span style="font-size:2rem;">${ok ? '🎉' : '⚠️'}</span>
        <div>
          <h3 style="margin:0;">${ok ? 'ผ่านครบทุกรายการ!' : 'มีบางรายการไม่ผ่าน'}</h3>
          <p style="margin:0.3rem 0 0 0; color:var(--text-muted);">
            ผ่าน <strong style="color:var(--success);">${summary.passed_count}/${summary.total}</strong> รายการ
            · ล้มเหลว <strong style="color:#ff6b6b;">${summary.failed_count}</strong> ·
            เริ่ม ${escapeText(summary.started_at)} · จบ ${escapeText(summary.finished_at)}
          </p>
        </div>
      </div>`;
  }

  // ---------------------------------------------------------------- run snapshot

  function renderRunSnapshot(snapshot) {
    if (!snapshot) return;
    if (snapshot.expected_total) totalTests = snapshot.expected_total;
    if (snapshot.status === 'running' && snapshot.latest_progress) {
      showProgress(snapshot.latest_progress);
    }
    (snapshot.tests || []).forEach(t => {
      if (!t || renderedOrders.has(t.order)) return;
      renderedOrders.add(t.order);
      completedTests = Math.max(completedTests, t.order || 0);
      appendTest(t);
      const prior = (suiteTestStatus[snapshot.suite] || {})[String(t.order)];
      if (prior && prior.status === 'passed') addPriorPassedTag(resultsArea.lastElementChild);
      setStatus(`✔ รายการ ${t.order} เสร็จ (${t.passed ? 'ผ่าน' : 'ไม่ผ่าน'})`);
      renderProgress(`✔ เสร็จแล้ว ${fractionText()} — ${t.passed ? 'ผ่าน' : 'ไม่ผ่าน'}`, completedTests);
    });
    setProcessingIndicator(snapshot);
    if (snapshot.status === 'running') return;
    if (snapshot.summary) {
      if (typeof snapshot.summary.total === 'number') {
        totalTests = snapshot.summary.total;
        renderProgress(`เสร็จสิ้น — ${completedTests}/${totalTests}`, completedTests);
      }
      renderSummary(snapshot.summary);
      setStatus('เสร็จสิ้น');
    } else if (snapshot.error) {
      summaryCard.style.display = 'block';
      summaryCard.innerHTML = '<h3 style="color:#ff6b6b;">❌ งานทดสอบล้มเหลว</h3>'
        + `<p style="color:var(--text-muted);">${escapeText(snapshot.error)}</p>`;
      setStatus('ล้มเหลว');
    }
  }

  // ---------------------------------------------------------------- watch (polling)

  function stopWatch() {
    if (watchTimer) { clearTimeout(watchTimer); watchTimer = null; }
    activeRunId = null;
  }

  function highlightSuite(suiteKey) {
    if (!suiteKey) return;
    selectedSuite = suiteKey;
    suiteCards.forEach(c => {
      const on = c.dataset.suite === suiteKey;
      c.classList.toggle('active', on);
      c.style.borderColor = on ? 'var(--accent-cyan)' : 'var(--card-border)';
    });
  }

  function startWatch(runId, opts) {
    opts = opts || {};
    stopWatch();
    activeRunId = runId;
    renderedOrders.clear();
    resultsArea.innerHTML = '';
    summaryCard.style.display = 'none';
    resetProgress();
    setRunning(true);
    setStatus('กำลังเชื่อมต่อกับงานทดสอบ...');
    renderProgress('⏳ กำลังเริ่มทดสอบ...', 0);
    const suiteName = SUITE_NAMES[opts.suiteKey] || opts.suiteKey || '';
    showBanner(`⏳ กำลังทดสอบอยู่${suiteName ? ' (' + escapeText(suiteName) + ')' : ''} — ระบบแสดงผลแบบสด (poll ทุก ${Math.round(POLL_MS / 1000)} วิ) จนเสร็จ`);
    highlightSuite(opts.suiteKey);
    pollRun();
  }

  async function pollRun() {
    if (!activeRunId) return;
    try {
      const res = await fetch(`/v1/tests/runs/${encodeURIComponent(activeRunId)}`, { headers: headers() });
      if (res.status === 401 || res.status === 403) {
        showBanner('❌ API Key ไม่ถูกต้อง — ไปที่หน้า ตั้งค่า แล้วกรอกใหม่', true);
        stopWatch();
        setRunning(false);
        return;
      }
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const snapshot = await res.json();
      renderRunSnapshot(snapshot);
      if (snapshot.status === 'running') {
        watchTimer = setTimeout(pollRun, POLL_MS);
      } else {
        showBanner('');
        stopWatch();
        setRunning(false);
        loadHistory();
        loadInfo();
      }
    } catch (e) {
      // transient network error → keep retrying
      watchTimer = setTimeout(pollRun, POLL_MS);
    }
  }

  async function checkActiveRun() {
    if (activeRunId) return;
    try {
      const res = await fetch('/v1/tests/runs/active', { headers: headers() });
      if (!res.ok) return;
      const data = await res.json();
      if (data.active && data.run) {
        startWatch(data.run.run_id, { suiteKey: data.run.suite });
      } else {
        loadHistory();
      }
    } catch (e) { /* ignore */ }
  }

  // ---------------------------------------------------------------- run start

  async function runTest() {
    if (running) return;
    if (selectedSuite === 'word-diar' && !diarizationEnabled) {
      summaryCard.style.display = 'block';
      summaryCard.innerHTML = '<h3 style="color:#ff9d2e;">⚠️ ไม่สามารถรันชุด Word-level + ผู้พูด ได้</h3>'
        + '<p style="color:var(--text-muted);">Speaker Diarization ถูกปิดบนเซิร์ฟเวอร์นี้ — ต้องตั้งค่า HF_TOKEN และเปิด DIARIZATION_ENABLED=true ก่อน</p>';
      return;
    }
    const doCleanup = !!cleanupToggle.checked;
    try {
      const res = await fetch(`/v1/tests/run?suite=${selectedSuite}&cleanup=${doCleanup}`, {
        method: 'POST',
        headers: headers(),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 401 || res.status === 403) {
        summaryCard.style.display = 'block';
        summaryCard.innerHTML = '<h3 style="color:#ff6b6b;">❌ API Key ไม่ถูกต้อง</h3>'
          + '<p style="color:var(--text-muted);">ไปที่หน้า <a href="/setting">ตั้งค่า</a> แล้วกรอกใหม่</p>';
        return;
      }
      if (res.status === 409) {
        const det = (body.detail && typeof body.detail === 'object') ? body.detail : {};
        const rid = det.active_run_id;
        if (rid) {
          startWatch(rid, { suiteKey: det.active_suite });
        } else {
          summaryCard.style.display = 'block';
          summaryCard.innerHTML = '<h3 style="color:#ff9d2e;">⚠️ มีงานทดสอบกำลังทำงานอยู่</h3>'
            + `<p style="color:var(--text-muted);">${escapeText(typeof body.detail === 'string' ? body.detail : (det.message || 'HTTP 409'))}</p>`;
        }
        return;
      }
      if (!res.ok) {
        throw new Error(typeof body.detail === 'string' ? body.detail : ('HTTP ' + res.status));
      }
      if (body.run_id) {
        startWatch(body.run_id, { suiteKey: body.suite });
      }
    } catch (e) {
      summaryCard.style.display = 'block';
      summaryCard.innerHTML = '<h3 style="color:#ff6b6b;">❌ ไม่สามารถเริ่มทดสอบได้</h3>'
        + `<p style="color:var(--text-muted);">${escapeText(e.message)}</p>`;
    }
  }

  // ---------------------------------------------------------------- history bar

  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' });
  }

  function historyChip(run) {
    const name = SUITE_NAMES[run.suite] || run.suite;
    const done = run.status !== 'running';
    const label = !done ? '⏳' : (run.status === 'completed' ? '✅' : '❌');
    const detail = !done ? 'กำลังทำงาน...'
      : (run.summary ? `ผ่าน ${run.summary.passed_count}/${run.summary.total}` : 'ล้มเหลว');
    return `<button type="button" data-run="${escapeText(run.run_id)}"
      style="flex:1 1 190px; min-width:190px; text-align:left; cursor:pointer; background:rgba(255,255,255,0.04);
             border:1px solid var(--card-border); border-radius:10px; padding:0.6rem 0.8rem; color:var(--text-main);
             font-size:0.82rem; transition:border-color .15s;">
      <span style="display:block; font-weight:600;">${label} ${escapeText(name)}</span>
      <span style="color:var(--text-muted);">${escapeText(detail)} · ${fmtTime(run.started_at)}</span>
    </button>`;
  }

  function renderHistory(runs) {
    if (!historyPanel) return;
    if (!runs || !runs.length) {
      historyPanel.style.display = 'none';
      historyPanel.innerHTML = '';
      return;
    }
    historyPanel.style.display = 'block';
    historyPanel.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.5rem;">
        <span style="font-weight:600; color:var(--text-main);">🕘 ประวัติการทดสอบล่าสุด</span>
        <span style="font-size:0.8rem; color:var(--text-muted);">คลิกเพื่อดูผลลัพธ์</span>
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:0.5rem;">${runs.map(historyChip).join('')}</div>`;
  }

  async function loadHistory() {
    if (!historyPanel) return;
    try {
      const res = await fetch('/v1/tests/runs', { headers: headers() });
      if (!res.ok) return;
      const data = await res.json();
      renderHistory(data.runs || []);
    } catch (e) { /* ignore */ }
  }

  async function openRun(runId) {
    stopWatch();
    setRunning(false);
    showBanner('');
    renderedOrders.clear();
    resultsArea.innerHTML = '';
    summaryCard.style.display = 'none';
    resetProgress();
    try {
      const res = await fetch(`/v1/tests/runs/${encodeURIComponent(runId)}`, { headers: headers() });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const snapshot = await res.json();
      if (snapshot.status === 'running') {
        startWatch(runId, { suiteKey: snapshot.suite });
        return;
      }
      renderRunSnapshot(snapshot);
    } catch (e) {
      summaryCard.style.display = 'block';
      summaryCard.innerHTML = '<h3 style="color:#ff6b6b;">❌ ไม่สามารถโหลดผลลัพธ์ได้</h3>'
        + `<p style="color:var(--text-muted);">${escapeText(e.message)}</p>`;
    }
  }

  // ---------------------------------------------------------------- wiring

  startBtn.addEventListener('click', runTest);
  historyPanel.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-run]');
    if (btn) openRun(btn.dataset.run);
  });
  window.addEventListener('storage', refreshKeyState);
  window.addEventListener('focus', () => { refreshKeyState(); checkActiveRun(); });
  refreshKeyState();
  loadInfo();
  checkActiveRun();
});