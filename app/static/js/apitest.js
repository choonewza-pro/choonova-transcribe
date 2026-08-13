// API Endpoint Self-Test page client.
// Loads config via GET /v1/tests/info, then streams POST /v1/tests/run
// (application/x-ndjson) and renders each result live as it arrives.
document.addEventListener('DOMContentLoaded', () => {
  const API_KEY_STORAGE = 'typhoon_asr_api_key';
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

  let running = false;
  let totalTests = null;
  let completedTests = 0;

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
      `⚙️ ภาษาที่ทดสอบ: <code>th</code> (Typhoon) · compress defaults: crf=<code>${d.crf}</code>, `
      + `preset=<code>${d.preset}</code>, encoder=<code>${d.encoder}</code>`
      + ` · ขีดจำกัด: transcribe <code>${l.transcribe_max_wait_sec}s</code>, `
      + `compress <code>${l.compress_max_wait_sec}s</code>`;
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
    if (progWrap) progWrap.style.display = 'block';
    const pct = Number.isFinite(Number(prog.progress)) ? Math.round(Number(prog.progress)) : 0;
    if (fill) fill.style.width = pct + '%';
    const stage = (prog.status || '') + (prog.stage ? ' — ' + prog.stage : '');
    setStatus(`⏳ poll: ${path.replace(/^.*\/(jobs)/, '/$1')} (${escapeText(stage)} ${pct}%)`);
    renderProgress(`⏳ กำลังประมวลผล... (${fractionText()}) · ${escapeText(stage)}`, completedTests);
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

  // ---------------------------------------------------------------- streaming run

  async function runTest() {
    if (running) return;
    resultsArea.innerHTML = '';
    summaryCard.style.display = 'none';
    resetProgress();
    setRunning(true);
    setStatus('กำลังเริ่มทดสอบ...');
    const doCleanup = !!cleanupToggle.checked;
    try {
      const res = await fetch(`/v1/tests/run?cleanup=${doCleanup}`, {
        method: 'POST',
        headers: headers(),
      });
      if (!res.ok || !res.body) {
        let detail = 'HTTP ' + res.status;
        try { detail = (await res.json()).detail || detail; } catch (e2) {}
        if (res.status === 401 || res.status === 403) {
          detail = 'API Key ไม่ถูกต้อง — ไปที่หน้า <a href="/setting">ตั้งค่า</a> แล้วกรอกใหม่';
        }
        throw new Error(detail);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 1);
          if (!line) continue;
          let ev;
          try { ev = JSON.parse(line); } catch (e3) { continue; }
          handleEvent(ev);
        }
      }
    } catch (e) {
      summaryCard.style.display = 'block';
      summaryCard.innerHTML = '<h3 style="color:#ff6b6b;">❌ ไม่สามารถเริ่มทดสอบได้</h3>'
        + `<p style="color:var(--text-muted);">${escapeText(e.message)}</p>`;
    } finally {
      setRunning(false);
    }
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case 'start':
        totalTests = parseInt(ev.total, 10) || null;
        completedTests = 0;
        renderProgress(`⏳ กำลังเริ่มทดสอบ... (0/${totalTests})`, 0);
        break;
      case 'test':
        completedTests = ev.data.order || completedTests + 1;
        renderProgress(
          `✔ เสร็จแล้ว ${fractionText()} — ${ev.data.passed ? 'ผ่าน' : 'ไม่ผ่าน'}`,
          completedTests);
        setStatus(`✔ รายการ ${ev.data.order} เสร็จ (${ev.data.passed ? 'ผ่าน' : 'ไม่ผ่าน'})`);
        appendTest(ev.data);
        break;
      case 'progress':
        showProgress(ev.data);
        break;
      case 'done':
        if (ev.summary && typeof ev.summary.total === 'number') {
          totalTests = ev.summary.total;
          renderProgress(`เสร็จสิ้น — ${completedTests}/${totalTests}`, completedTests);
        }
        renderSummary(ev.summary);
        setStatus('เสร็จสิ้น');
        break;
      case 'error':
        setStatus('เกิดข้อผิดพลาด: ' + (escapeText(ev.data?.message) || ''));
        break;
    }
  }

  // ---------------------------------------------------------------- wiring

  startBtn.addEventListener('click', runTest);
  window.addEventListener('storage', refreshKeyState);
  window.addEventListener('focus', refreshKeyState);
  refreshKeyState();
  loadInfo();
});