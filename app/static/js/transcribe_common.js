// Shared helpers for the audio transcription pages (upload page + audio jobs page).
// Load this BEFORE the page-specific script.
window.TranscribeCommon = (function () {
  function modelOptionsFor(lang, diarization) {
    if (lang === 'th') {
      if (diarization) {
        return [
          { value: 'thai-whisper', label: 'Thai Whisper — คำต่อคำ + PyAnnote' },
          { value: 'whisperx', label: 'WhisperX — ASR + Diarization' },
        ];
      }
      return [
        { value: 'typhoon', label: 'Typhoon ASR — เร็วที่สุด, รันบน CPU ได้' },
        { value: 'thai-whisper', label: 'Thai Whisper — แม่นยำที่สุด แต่ช้าที่สุด' },
        { value: 'whisper', label: 'Faster-Whisper — กลาง ๆ' },
      ];
    }
    return diarization
      ? [{ value: 'whisperx', label: 'WhisperX — ASR + Diarization' }]
      : [{ value: 'whisper', label: 'Faster-Whisper' }];
  }

  function populateModelOptions(modelSelect, languageSelect, diarizationCheck) {
    if (!modelSelect) return;
    const lang = (languageSelect && languageSelect.value) || 'th';
    const diar = !!(diarizationCheck && diarizationCheck.checked);
    const opts = modelOptionsFor(lang, diar);
    const previous = modelSelect.value;
    modelSelect.innerHTML = '';
    opts.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o.value;
      opt.textContent = o.label;
      modelSelect.appendChild(opt);
    });
    if (opts.some(o => o.value === previous)) {
      modelSelect.value = previous;
    }
  }

  function bindModelSelect(modelSelect, languageSelect, diarizationCheck) {
    if (!modelSelect) return;
    if (languageSelect) {
      languageSelect.addEventListener('change', () => populateModelOptions(modelSelect, languageSelect, diarizationCheck));
    }
    if (diarizationCheck) {
      diarizationCheck.addEventListener('change', () => populateModelOptions(modelSelect, languageSelect, diarizationCheck));
    }
    populateModelOptions(modelSelect, languageSelect, diarizationCheck);
  }

  async function copyText(text, btn, opts) {
    if (!text) {
      alert(opts && opts.emptyMsg ? opts.emptyMsg : 'ไม่มีข้อความให้คัดลอก');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      const originalText = btn.textContent;
      btn.textContent = (opts && opts.successLabel) || '✅ คัดลอกแล้ว!';
      btn.style.color = 'var(--success)';
      setTimeout(() => {
        btn.textContent = originalText;
        btn.style.color = '';
      }, 2000);
    } catch (err) {
      alert('ไม่สามารถคัดลอกได้: ' + err.message);
    }
  }

  function bindSpeakerMode() {
    const radios = document.querySelectorAll('input[name="speakerMode"]');
    const exactRow = document.getElementById('exactSpeakersRow');
    const rangeRow = document.getElementById('rangeSpeakersRow');
    function sync() {
      const checked = document.querySelector('input[name="speakerMode"]:checked');
      const mode = (checked && checked.value) || 'auto';
      if (exactRow) exactRow.style.display = mode === 'exact' ? 'flex' : 'none';
      if (rangeRow) rangeRow.style.display = mode === 'range' ? 'flex' : 'none';
    }
    radios.forEach(r => r.addEventListener('change', sync));
    sync();
  }

  function collectSpeakerParams(formData) {
    const checked = document.querySelector('input[name="speakerMode"]:checked');
    const mode = (checked && checked.value) || 'auto';
    const num = document.getElementById('numSpeakersInput');
    const min = document.getElementById('minSpeakersInput');
    const max = document.getElementById('maxSpeakersInput');
    if (mode === 'exact') {
      if (num && num.value && parseInt(num.value, 10) > 0) {
        formData.append('num_speakers', num.value);
      }
    } else if (mode === 'range') {
      if (min && min.value && parseInt(min.value, 10) > 0) {
        formData.append('min_speakers', min.value);
      }
      if (max && max.value && parseInt(max.value, 10) > 0) {
        formData.append('max_speakers', max.value);
      }
    }
  }

  function bindTimestampHint() {
    const check = document.getElementById('timestampsCheck');
    const modelSelect = document.getElementById('modelSelect');
    const hint = document.getElementById('timestampHint');
    if (!check || !modelSelect || !hint) return;

    function update() {
      const model = (modelSelect && modelSelect.value) || '';
      const isTyphoon = model === 'typhoon';
      check.disabled = isTyphoon;
      if (isTyphoon) {
        check.checked = false;
        hint.style.display = 'block';
        hint.textContent = '⚠️ Word-level Timestamps ใช้ไม่ได้กับ Typhoon (ถูกปิดอัตโนมัติ) — รองรับเฉพาะ Thai Whisper / Whisper / WhisperX';
        hint.style.background = 'rgba(251,191,36,0.12)';
        hint.style.color = '#fbbf24';
        hint.style.border = '1px solid rgba(251,191,36,0.4)';
        return;
      }
      if (!check.checked) {
        hint.style.display = 'none';
        return;
      }
      hint.style.display = 'block';
      hint.textContent = '✅ ได้ Word-level Timestamps ระดับคำจริง';
      hint.style.background = 'rgba(34,197,94,0.12)';
      hint.style.color = '#4ade80';
      hint.style.border = '1px solid rgba(34,197,94,0.4)';
    }

    check.addEventListener('change', update);
    modelSelect.addEventListener('change', update);
    const languageSelect = document.getElementById('languageSelect');
    const diarizationCheck = document.getElementById('diarizationCheck');
    if (languageSelect) languageSelect.addEventListener('change', update);
    if (diarizationCheck) diarizationCheck.addEventListener('change', update);
    update();
  }

  return {
    modelOptionsFor: modelOptionsFor,
    populateModelOptions: populateModelOptions,
    bindModelSelect: bindModelSelect,
    bindSpeakerMode: bindSpeakerMode,
    collectSpeakerParams: collectSpeakerParams,
    bindTimestampHint: bindTimestampHint,
    copyText: copyText,
  };
})();