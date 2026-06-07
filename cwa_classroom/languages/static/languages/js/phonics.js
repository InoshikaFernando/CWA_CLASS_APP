(function () {
  'use strict';

  var playBtn      = document.getElementById('play-btn');
  var grid         = document.getElementById('answer-grid');
  var resultPanel  = document.getElementById('result-panel');
  var resultIcon   = document.getElementById('result-icon');
  var resultMsg    = document.getElementById('result-msg');
  var resultSub    = document.getElementById('result-sub');
  var btnTryAgain  = document.getElementById('btn-try-again');
  var audioFallback = document.getElementById('audio-fallback');

  if (!playBtn || !grid) return;

  var submitUrl = grid.dataset.submitUrl;
  var csrfToken = grid.dataset.csrf;
  var ttsLang   = grid.dataset.ttsLang || 'en-US';
  var ttsText   = grid.dataset.ttsText || '';

  var speaking = false;
  var answered = false;

  // ---------------------------------------------------------------------------
  // Voice helpers
  // ---------------------------------------------------------------------------

  // Prime Chrome's async voice cache; show warning early if language unsupported.
  // Do NOT auto-play — Chrome blocks speechSynthesis.speak() without a user gesture.
  function _onVoicesReady() {
    if (!_findVoice(ttsLang) && !audioFallback) {
      _showNoAudioMsg();
    }
  }

  if (window.speechSynthesis) {
    var _voices = window.speechSynthesis.getVoices();
    if (_voices.length > 0) {
      _onVoicesReady();
    } else {
      window.speechSynthesis.onvoiceschanged = function () {
        window.speechSynthesis.onvoiceschanged = null;
        _onVoicesReady();
      };
    }
  }

  function _findVoice(lang) {
    var voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
    // 1. exact match
    var v = voices.find(function (x) { return x.lang === lang; });
    if (v) return v;
    // 2. same language prefix (en-NZ → any en-*)
    var prefix = lang.split('-')[0];
    v = voices.find(function (x) { return x.lang.split('-')[0] === prefix; });
    return v || null;
  }

  function _playAudioFallback() {
    if (!audioFallback) return false;
    audioFallback.currentTime = 0;
    audioFallback.play().catch(function () {});
    return true;
  }

  // ---------------------------------------------------------------------------
  // Play sound — no async waiting, immediate response
  // ---------------------------------------------------------------------------

  function playSound() {
    // Toggle off if already playing
    if (speaking) {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      if (audioFallback) { audioFallback.pause(); audioFallback.currentTime = 0; }
      speaking = false;
      _setPlayState(false);
      return;
    }

    // No TTS API → audio file only
    if (!window.speechSynthesis) {
      if (!_playAudioFallback()) {
        _showNoAudioMsg();
      }
      return;
    }

    var voice = _findVoice(ttsLang);

    // No matching voice → use audio file if available, else bail with message.
    // Do NOT call speak() without a matching voice — browsers silently skip
    // non-Latin text (Sinhala, Tamil) with a default English voice.
    if (!voice) {
      if (!_playAudioFallback()) _showNoAudioMsg();
      return;
    }

    speaking = true;
    _setPlayState(true);

    var utter = new SpeechSynthesisUtterance(ttsText);
    utter.lang   = ttsLang;
    utter.rate   = 0.85;
    utter.pitch  = 1;
    utter.volume = 1;

    utter.voice = voice;

    utter.onend = function () {
      speaking = false;
      _setPlayState(false);
    };
    utter.onerror = function (e) {
      // 'interrupted' is not an error — it fires when we call cancel()
      if (e.error === 'interrupted' || e.error === 'canceled') return;
      speaking = false;
      _setPlayState(false);
      // TTS failed — try audio file then show message
      if (!_playAudioFallback()) _showNoAudioMsg();
    };

    // cancel() + 100 ms gap avoids Chrome silent-drop bug
    window.speechSynthesis.cancel();
    setTimeout(function () {
      window.speechSynthesis.speak(utter);
    }, 100);
  }

  function _setPlayState(isPlaying) {
    var span = playBtn.querySelector('span');
    if (isPlaying) {
      playBtn.classList.add('playing');
      playBtn.setAttribute('aria-label', 'Stop sound');
      if (span) span.textContent = 'Stop';
    } else {
      playBtn.classList.remove('playing');
      playBtn.setAttribute('aria-label', 'Play sound');
      if (span) span.textContent = 'Play';
    }
  }

  function _showNoAudioMsg() {
    var existing = document.getElementById('no-audio-hint');
    if (existing) return;
    var hint = document.createElement('div');
    hint.id = 'no-audio-hint';
    hint.style.cssText = 'font-size:12px;color:#6b7280;margin-top:10px;text-align:center;background:#fef9c3;border:1px solid #fde68a;border-radius:8px;padding:8px 12px;max-width:260px';
    hint.innerHTML = '⚠️ Your device does not have a <strong>' + ttsLang + '</strong> voice installed.<br>' +
      '<span style="font-size:11px;color:#9ca3af">Install the language pack in your OS settings to hear the audio.</span>';
    playBtn.parentNode.insertBefore(hint, playBtn.nextSibling);
    speaking = false;
    _setPlayState(false);
  }

  playBtn.addEventListener('click', playSound);

  // ---------------------------------------------------------------------------
  // MCQ answer selection + POST
  // ---------------------------------------------------------------------------

  var answerBtns = grid.querySelectorAll('.answer-btn');

  answerBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (answered) return;
      answered = true;

      if (window.speechSynthesis) window.speechSynthesis.cancel();
      if (audioFallback) { audioFallback.pause(); audioFallback.currentTime = 0; }
      speaking = false;
      _setPlayState(false);

      answerBtns.forEach(function (b) { b.disabled = true; });

      var selectedId = btn.dataset.answerId;
      var fd = new FormData();
      fd.append('selected_answer_id', selectedId);
      fd.append('csrfmiddlewaretoken', csrfToken);

      fetch(submitUrl, { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) { _showFeedback(data, btn, selectedId); })
        .catch(function () {
          answered = false;
          answerBtns.forEach(function (b) { b.disabled = false; });
        });
    });
  });

  function _showFeedback(data, selectedBtn, selectedId) {
    var correctId = String(data.correct_answer_id);
    answerBtns.forEach(function (b) {
      var bid = String(b.dataset.answerId);
      if (bid === correctId) {
        b.classList.add('correct');
      } else if (bid === String(selectedId) && !data.is_correct) {
        b.classList.add('incorrect');
      }
    });

    if (data.is_correct) {
      resultIcon.textContent = '🎉';
      resultMsg.textContent  = 'Correct!';
      resultMsg.style.color  = '#059669';
      resultSub.textContent  = 'Great job — you recognised that sound!';
    } else {
      resultIcon.textContent = '✗';
      resultMsg.textContent  = 'Not quite!';
      resultMsg.style.color  = '#dc2626';
      resultSub.textContent  = 'The correct answer is highlighted in blue.';
    }

    resultPanel.removeAttribute('hidden');
  }

  // ---------------------------------------------------------------------------
  // Try Again
  // ---------------------------------------------------------------------------

  btnTryAgain.addEventListener('click', function () {
    answered = false;
    answerBtns.forEach(function (b) {
      b.disabled = false;
      b.classList.remove('correct', 'incorrect', 'reveal');
    });
    resultPanel.setAttribute('hidden', '');
    playSound();
  });

})();
