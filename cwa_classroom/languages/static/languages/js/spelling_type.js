(function () {
  'use strict';

  var playBtn       = document.getElementById('play-btn');
  var typeArea      = document.getElementById('type-area');
  var input         = document.getElementById('spelling-input');
  var btnSubmit     = document.getElementById('btn-submit');
  var resultPanel   = document.getElementById('result-panel');
  var resultIcon    = document.getElementById('result-icon');
  var resultMsg     = document.getElementById('result-msg');
  var resultSub     = document.getElementById('result-sub');
  var resultWord    = document.getElementById('result-word');
  var btnTryAgain   = document.getElementById('btn-try-again');
  var audioFallback = document.getElementById('audio-fallback');

  if (!playBtn || !typeArea || !input) return;

  var submitUrl = typeArea.dataset.submitUrl;
  var csrfToken = typeArea.dataset.csrf;
  var ttsLang   = typeArea.dataset.ttsLang || 'en-US';
  var ttsText   = typeArea.dataset.ttsText || '';

  var speaking  = false;
  var submitted = false;

  // ---------------------------------------------------------------------------
  // TTS
  // ---------------------------------------------------------------------------

  if (window.speechSynthesis) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = function () {
      window.speechSynthesis.getVoices();
    };
  }

  function _findVoice(lang) {
    var voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
    var v = voices.find(function (x) { return x.lang === lang; });
    if (v) return v;
    var prefix = lang.split('-')[0];
    return voices.find(function (x) { return x.lang.split('-')[0] === prefix; }) || null;
  }

  function _playAudioFallback() {
    if (!audioFallback) return false;
    audioFallback.currentTime = 0;
    audioFallback.play().catch(function () {});
    return true;
  }

  function _setPlayState(isPlaying) {
    var span = playBtn.querySelector('span');
    if (isPlaying) {
      playBtn.classList.add('playing');
      playBtn.setAttribute('aria-label', 'Stop sound');
      if (span) span.textContent = 'Stop';
    } else {
      playBtn.classList.remove('playing');
      playBtn.setAttribute('aria-label', 'Play word');
      if (span) span.textContent = 'Play';
    }
  }

  function _showNoAudioMsg() {
    var existing = document.getElementById('no-audio-hint');
    if (existing) return;
    var hint = document.createElement('p');
    hint.id = 'no-audio-hint';
    hint.style.cssText = 'font-size:12px;color:#9ca3af;margin-top:8px;text-align:center';
    hint.textContent = 'No audio available for this language on your device.';
    playBtn.parentNode.insertBefore(hint, playBtn.nextSibling);
    speaking = false;
    _setPlayState(false);
  }

  function playSound() {
    if (speaking) {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      if (audioFallback) { audioFallback.pause(); audioFallback.currentTime = 0; }
      speaking = false;
      _setPlayState(false);
      return;
    }
    if (!window.speechSynthesis) {
      if (!_playAudioFallback()) _showNoAudioMsg();
      return;
    }
    speaking = true;
    _setPlayState(true);

    var utter    = new SpeechSynthesisUtterance(ttsText);
    utter.lang   = ttsLang;
    utter.rate   = 0.80;  // slightly slower for spelling dictation
    utter.pitch  = 1;
    utter.volume = 1;
    var voice = _findVoice(ttsLang);
    if (voice) utter.voice = voice;

    utter.onend = function () { speaking = false; _setPlayState(false); };
    utter.onerror = function (e) {
      if (e.error === 'interrupted' || e.error === 'canceled') return;
      speaking = false; _setPlayState(false);
      if (!_playAudioFallback()) _showNoAudioMsg();
    };
    window.speechSynthesis.cancel();
    setTimeout(function () { window.speechSynthesis.speak(utter); }, 100);
  }

  playBtn.addEventListener('click', playSound);

  // Auto-play on load
  setTimeout(playSound, 400);

  // ---------------------------------------------------------------------------
  // Input → enable Submit
  // ---------------------------------------------------------------------------

  input.addEventListener('input', function () {
    btnSubmit.disabled = input.value.trim().length === 0;
  });

  // Submit on Enter key
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !btnSubmit.disabled && !submitted) {
      _submit();
    }
  });

  btnSubmit.addEventListener('click', function () {
    if (!submitted) _submit();
  });

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------

  function _submit() {
    var text = input.value.trim();
    if (!text) return;

    submitted = true;
    btnSubmit.disabled = true;
    input.disabled = true;

    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (audioFallback) { audioFallback.pause(); audioFallback.currentTime = 0; }
    speaking = false;
    _setPlayState(false);

    var fd = new FormData();
    fd.append('answer', text);
    fd.append('csrfmiddlewaretoken', csrfToken);

    fetch(submitUrl, { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (data) { _showFeedback(data); })
      .catch(function () {
        submitted = false;
        btnSubmit.disabled = false;
        input.disabled = false;
      });
  }

  function _stageUnlockedToast() {
    var t = document.createElement('div');
    t.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#059669;color:#fff;padding:14px 28px;border-radius:14px;font-size:14px;font-weight:700;box-shadow:0 6px 24px rgba(0,0,0,.18);z-index:9999;transition:opacity .5s';
    t.textContent = '🎉 Stage Unlocked! The next level is now available.';
    document.body.appendChild(t);
    setTimeout(function () { t.style.opacity = '0'; }, 3500);
    setTimeout(function () { t.remove(); }, 4000);
  }

  function _showFeedback(data) {
    if (data.stage_unlocked) setTimeout(_stageUnlockedToast, 800);
    if (data.is_correct) {
      resultIcon.textContent = '🎉';
      resultMsg.textContent  = 'Correct!';
      resultMsg.style.color  = '#059669';
      resultSub.textContent  = 'Well spelt!';
      if (resultWord) resultWord.textContent = '';
    } else {
      resultIcon.textContent = '✗';
      resultMsg.textContent  = 'Not quite!';
      resultMsg.style.color  = '#dc2626';
      resultSub.textContent  = 'The correct spelling is:';
      if (resultWord) resultWord.textContent = data.correct_spelling || '';
    }
    resultPanel.removeAttribute('hidden');
    resultPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ---------------------------------------------------------------------------
  // Try Again
  // ---------------------------------------------------------------------------

  btnTryAgain.addEventListener('click', function () {
    submitted = false;
    input.value = '';
    input.disabled = false;
    btnSubmit.disabled = true;
    if (resultWord) resultWord.textContent = '';
    resultPanel.setAttribute('hidden', '');
    input.focus();
    playSound();
  });

})();
