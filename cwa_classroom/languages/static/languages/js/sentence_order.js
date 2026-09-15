(function () {
  'use strict';

  var submitBtn   = document.getElementById('btn-submit');
  var wordBank    = document.getElementById('word-bank');
  var answerZone  = document.getElementById('answer-zone');
  var resultPanel = document.getElementById('result-panel');
  var resultIcon  = document.getElementById('result-icon');
  var resultMsg   = document.getElementById('result-msg');
  var resultScore = document.getElementById('result-score');
  var resultSentenceWrap = document.getElementById('result-sentence-wrap');
  var resultSentence     = document.getElementById('result-sentence');
  var btnTryAgain = document.getElementById('btn-try-again');

  if (!submitBtn || !wordBank || !answerZone) return;

  var submitUrl   = submitBtn.dataset.submitUrl;
  var csrfToken   = submitBtn.dataset.csrf;
  var wordOrder   = JSON.parse(submitBtn.dataset.wordOrder || '[]');
  var submitted   = false;

  // ---------------------------------------------------------------------------
  // Build shuffled tiles into word bank
  // ---------------------------------------------------------------------------

  var shuffled = wordOrder.slice().sort(function () { return Math.random() - 0.5; });

  shuffled.forEach(function (word, idx) {
    var tile = document.createElement('div');
    tile.className = 'word-tile';
    tile.dataset.word = word;
    tile.dataset.idx  = String(idx);
    tile.textContent  = word;
    tile.setAttribute('role', 'button');
    tile.setAttribute('tabindex', '0');
    tile.setAttribute('aria-label', 'Word tile: ' + word);
    wordBank.appendChild(tile);
  });

  // ---------------------------------------------------------------------------
  // SortableJS — cross-list drag between bank and answer zone
  // ---------------------------------------------------------------------------

  var sortableOpts = {
    group:              'words',
    animation:          150,
    delay:              100,        // helps distinguish tap-scroll on mobile
    delayOnTouchOnly:   true,
    ghostClass:         'sortable-ghost',
    chosenClass:        'sortable-chosen',
    dragClass:          'sortable-drag',
    onAdd:    _onAnswerChange,
    onRemove: _onAnswerChange,
    onSort:   _onAnswerChange,
  };

  Sortable.create(wordBank, Object.assign({}, sortableOpts));
  Sortable.create(answerZone, Object.assign({}, sortableOpts, {
    onAdd:    _onAnswerChange,
    onRemove: _onAnswerChange,
    onSort:   _onAnswerChange,
  }));

  // ---------------------------------------------------------------------------
  // Tap-to-move fallback — tap in bank moves to answer zone; tap in answer zone
  // moves back to bank. Prevents zero-word stuck state on devices with poor
  // drag support.
  // ---------------------------------------------------------------------------

  wordBank.addEventListener('click', function (e) {
    var tile = e.target.closest('.word-tile');
    if (!tile || submitted) return;
    answerZone.appendChild(tile);
    _onAnswerChange();
  });

  answerZone.addEventListener('click', function (e) {
    var tile = e.target.closest('.word-tile');
    if (!tile || submitted) return;
    wordBank.appendChild(tile);
    _onAnswerChange();
  });

  // Keyboard: Enter/Space on tile → move to other container
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var tile = e.target.closest('.word-tile');
    if (!tile || submitted) return;
    e.preventDefault();
    if (tile.parentElement === wordBank) {
      answerZone.appendChild(tile);
    } else {
      wordBank.appendChild(tile);
    }
    tile.focus();
    _onAnswerChange();
  });

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------

  submitBtn.addEventListener('click', function () {
    if (submitted) return;
    submitted = true;
    submitBtn.disabled = true;

    var tiles = answerZone.querySelectorAll('.word-tile');
    var words = Array.from(tiles).map(function (t) { return t.dataset.word; });

    var fd = new FormData();
    fd.append('submitted_order', JSON.stringify(words));
    fd.append('csrfmiddlewaretoken', csrfToken);

    fetch(submitUrl, { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (data) { _showFeedback(data); })
      .catch(function () {
        submitted = false;
        submitBtn.disabled = answerZone.children.length === 0;
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

  function _showFeedback(data) {
    if (data.stage_unlocked) setTimeout(_stageUnlockedToast, 800);
    if (data.is_correct) {
      resultIcon.textContent = '🎉';
      resultMsg.textContent  = 'Correct!';
      resultMsg.style.color  = '#7c3aed';
      resultScore.textContent = 'Perfect sentence!';
    } else {
      resultIcon.textContent = '✗';
      resultMsg.textContent  = 'Almost!';
      resultMsg.style.color  = '#dc2626';
      resultScore.textContent =
        data.correct_count + ' of ' + data.total + ' words in the right position (' +
        data.score + '%)';
      resultSentence.textContent = data.correct_sentence;
      resultSentenceWrap.removeAttribute('hidden');
    }
    resultPanel.removeAttribute('hidden');
    submitBtn.setAttribute('hidden', '');
  }

  // ---------------------------------------------------------------------------
  // Try Again
  // ---------------------------------------------------------------------------

  btnTryAgain.addEventListener('click', function () {
    submitted = false;

    // Return all tiles from answer zone back to word bank
    var tiles = answerZone.querySelectorAll('.word-tile');
    tiles.forEach(function (t) { wordBank.appendChild(t); });

    resultPanel.setAttribute('hidden', '');
    if (resultSentenceWrap) resultSentenceWrap.setAttribute('hidden', '');
    submitBtn.removeAttribute('hidden');
    submitBtn.disabled = true;
    _onAnswerChange();
  });

  // ---------------------------------------------------------------------------
  // Enable submit once at least one tile is in the answer zone
  // ---------------------------------------------------------------------------

  function _onAnswerChange() {
    submitBtn.disabled = answerZone.querySelectorAll('.word-tile').length === 0;
    // Drag-over hint
    if (answerZone.children.length > 0) {
      answerZone.classList.remove('drag-over');
    }
  }

})();
