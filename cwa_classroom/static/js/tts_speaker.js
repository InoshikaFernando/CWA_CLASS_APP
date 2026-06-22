/*
 * tts_speaker.js — read-aloud (text-to-speech) for questions and answers.
 *
 * Lets young / pre-reading students hear a question or a multiple-choice
 * option instead of reading it, so they can work independently.
 *
 * Uses the browser's built-in Web Speech API (window.speechSynthesis) — no
 * backend, no network, no API key. Degrades gracefully: if the browser has no
 * speech support, every speaker button is hidden so nothing looks broken.
 *
 * Two ways to trigger speech:
 *   1. Markup:  <button class="tts-btn" data-speak="Two plus two">🔊</button>
 *      Any element with [data-speak] is wired automatically via a single
 *      delegated listener — this keeps working even when question HTML is
 *      swapped in dynamically (htmx / innerHTML) without re-binding.
 *   2. Code:    speakText("some text", optionalButtonEl)
 *      Kept for inline onclick="speakText(...)" callers in older templates.
 */
(function () {
  'use strict';

  var synth = window.speechSynthesis;
  var supported = typeof synth !== 'undefined' &&
                  typeof window.SpeechSynthesisUtterance !== 'undefined';

  // No speech support → hide every speaker control so the UI stays clean.
  if (!supported) {
    document.documentElement.classList.add('tts-unsupported');
    window.speakText = function () {};
    return;
  }

  var activeBtn = null; // the button whose utterance is currently playing

  function _clearActive() {
    if (activeBtn) {
      activeBtn.classList.remove('tts-playing');
      activeBtn = null;
    }
  }

  // Make maths read naturally: "3 × 4 = ?" → "3 times 4 equals ?".
  // Only symbols are swapped; words and numbers are left untouched.
  function _humanizeMaths(text) {
    return text
      .replace(/×/g, ' times ')
      .replace(/÷/g, ' divided by ')
      .replace(/≠/g, ' not equal to ')
      .replace(/≤/g, ' less than or equal to ')
      .replace(/≥/g, ' greater than or equal to ')
      .replace(/=/g, ' equals ')
      .replace(/%/g, ' percent ')
      // "x^2" / "5^3" → "x to the power of 2"
      .replace(/\^/g, ' to the power of ')
      // minus sign / hyphen sitting between two numbers → "minus"
      .replace(/(\d)\s*[−-]\s*(\d)/g, '$1 minus $2')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /**
   * Speak `text`. If `btn` is supplied it gets a "playing" highlight, and
   * clicking the same button again while it is talking stops it (toggle).
   */
  function speakText(text, btn) {
    if (!text) return;

    // Toggle: tapping the active button again just stops the speech.
    var wasActive = btn && btn === activeBtn;
    synth.cancel();      // stop anything already talking
    _clearActive();
    if (wasActive) return;

    var utter = new window.SpeechSynthesisUtterance(_humanizeMaths(String(text)));
    utter.rate = 0.9;    // a touch slower — easier for young listeners
    utter.pitch = 1.0;
    utter.lang = document.documentElement.lang || 'en-US';

    if (btn) {
      btn.classList.add('tts-playing');
      activeBtn = btn;
      utter.onend = utter.onerror = function () {
        if (activeBtn === btn) _clearActive();
      };
    }

    synth.speak(utter);
  }

  // Expose for inline onclick="speakText(...)" callers.
  window.speakText = speakText;

  // Delegated click handler: any [data-speak] element reads its own text.
  // stopPropagation keeps a per-answer speaker icon from also triggering the
  // surrounding answer button (which would submit the answer).
  document.addEventListener('click', function (e) {
    var el = e.target.closest && e.target.closest('[data-speak]');
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    speakText(el.getAttribute('data-speak'), el);
  });

  // Stop talking when leaving the page or switching questions.
  window.addEventListener('beforeunload', function () { synth.cancel(); });
})();
