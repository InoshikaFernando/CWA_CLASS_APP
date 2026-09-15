(function () {
  'use strict';

  var grid        = document.getElementById('answer-grid');
  var resultPanel = document.getElementById('result-panel');
  var resultIcon  = document.getElementById('result-icon');
  var resultMsg   = document.getElementById('result-msg');
  var resultWord  = document.getElementById('result-word');
  var resultExpl  = document.getElementById('result-explanation');
  var resultExplText = document.getElementById('result-explanation-text');
  var btnTryAgain = document.getElementById('btn-try-again');

  if (!grid) return;

  var submitUrl = grid.dataset.submitUrl;
  var csrfToken = grid.dataset.csrf;
  var answered  = false;

  var answerBtns = grid.querySelectorAll('.answer-btn');

  // ---------------------------------------------------------------------------
  // Answer selection
  // ---------------------------------------------------------------------------

  answerBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (answered) return;
      answered = true;

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

  // ---------------------------------------------------------------------------
  // Feedback
  // ---------------------------------------------------------------------------

  function _stageUnlockedToast() {
    var t = document.createElement('div');
    t.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#059669;color:#fff;padding:14px 28px;border-radius:14px;font-size:14px;font-weight:700;box-shadow:0 6px 24px rgba(0,0,0,.18);z-index:9999;transition:opacity .5s';
    t.textContent = '🎉 Stage Unlocked! The next level is now available.';
    document.body.appendChild(t);
    setTimeout(function () { t.style.opacity = '0'; }, 3500);
    setTimeout(function () { t.remove(); }, 4000);
  }

  function _showFeedback(data, selectedBtn, selectedId) {
    if (data.stage_unlocked) setTimeout(_stageUnlockedToast, 800);
    var correctId = data.correct_answer_id != null ? String(data.correct_answer_id) : null;

    answerBtns.forEach(function (b) {
      var bid = String(b.dataset.answerId);
      if (correctId !== null && bid === correctId) {
        b.classList.add('correct');
      } else if (bid === String(selectedId) && !data.is_correct) {
        b.classList.add('incorrect');
      }
    });

    if (data.is_correct) {
      resultIcon.textContent = '🎉';
      resultMsg.textContent  = 'Correct!';
      resultMsg.style.color  = '#059669';
      resultWord.textContent = '';
    } else {
      resultIcon.textContent = '✗';
      resultMsg.textContent  = 'Not quite!';
      resultMsg.style.color  = '#dc2626';
      resultWord.textContent = data.correct_answer_text;
    }

    if (data.grammar_explanation) {
      resultExplText.textContent = data.grammar_explanation;
      resultExpl.removeAttribute('hidden');
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
      b.classList.remove('correct', 'incorrect');
    });
    resultPanel.setAttribute('hidden', '');
    if (resultExpl) resultExpl.setAttribute('hidden', '');
  });

})();
