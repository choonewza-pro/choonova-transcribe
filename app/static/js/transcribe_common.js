// Shared helpers for the audio transcription pages (upload page + audio jobs page).
// Load this BEFORE the page-specific script.
window.TranscribeCommon = (function () {
  function modelOptionsFor(lang, diarization) {
    if (lang === 'translate_en') {
      return [{ value: 'whisper', label: 'Faster-Whisper (large-v3-turbo)' }];
    }
    if (lang === 'th') {
      if (diarization) {
        return [
          { value: 'thai-whisper', label: 'Thai Whisper (คำต่อคำ + PyAnnote)' },
          { value: 'whisperx', label: 'WhisperX (ASR + Diarization)' },
        ];
      }
      return [
        { value: 'thai-whisper', label: 'Thai Whisper (faster-whisper CT2)' },
        { value: 'typhoon', label: 'Typhoon ASR (NeMo)' },
        { value: 'whisper', label: 'Faster-Whisper (large-v3-turbo)' },
      ];
    }
    return diarization
      ? [{ value: 'whisperx', label: 'WhisperX (ASR + Diarization)' }]
      : [{ value: 'whisper', label: 'Faster-Whisper (large-v3-turbo)' }];
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
    modelSelect.disabled = lang === 'translate_en';
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

  return {
    modelOptionsFor: modelOptionsFor,
    populateModelOptions: populateModelOptions,
    bindModelSelect: bindModelSelect,
    copyText: copyText,
  };
})();