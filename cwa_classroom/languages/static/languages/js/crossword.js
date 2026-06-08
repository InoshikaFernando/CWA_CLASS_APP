(function () {
  'use strict';

  var container  = document.getElementById('cw-container');
  if (!container) return;

  var submitUrl  = container.dataset.submitUrl;
  var csrfToken  = container.dataset.csrf;
  var langCode   = container.dataset.lang   || 'en';
  var scriptType = container.dataset.script || 'latin';
  var puzzle;
  try { puzzle = JSON.parse(container.dataset.puzzle || '{}'); } catch (e) { puzzle = {}; }
  var words      = puzzle.words || [];

  var btnCheck   = document.getElementById('btn-check');
  var btnReveal  = document.getElementById('btn-reveal');
  var btnReset   = document.getElementById('btn-reset');
  var resultDiv  = document.getElementById('cw-result');
  var resultIcon = document.getElementById('cw-result-icon');
  var resultMsg  = document.getElementById('cw-result-msg');
  var resultSub  = document.getElementById('cw-result-sub');
  var mobileBar  = document.getElementById('cw-mobile-bar');
  var mcNum      = document.getElementById('mc-num');
  var mcText     = document.getElementById('mc-text');
  var modal      = document.getElementById('cw-modal');

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var activeWordIndex = null;   // index into words[]
  var activeDirection = 'across';
  var hintsUsed       = [];     // word indices revealed
  var checked         = false;

  // ---------------------------------------------------------------------------
  // Cell map — keyed by "row,col"
  // ---------------------------------------------------------------------------

  var cellMap = {};   // "r,c" → <td>
  var inputMap = {};  // "r,c" → <input>

  var tds = document.querySelectorAll('.cw-table td.cw-cell');
  tds.forEach(function (td) {
    var r = td.dataset.row;
    var c = td.dataset.col;
    var key = r + ',' + c;
    cellMap[key]  = td;
    inputMap[key] = td.querySelector('.cw-input');
  });

  // ---------------------------------------------------------------------------
  // Word → cells mapping
  // ---------------------------------------------------------------------------

  function wordCells(word) {
    var cells = [];
    for (var i = 0; i < word.answer.length; i++) {
      var r = word.row + (word.direction === 'down'   ? i : 0);
      var c = word.col + (word.direction === 'across' ? i : 0);
      var key = r + ',' + c;
      if (cellMap[key]) cells.push(key);
    }
    return cells;
  }

  // Pre-build cells list per word
  var wordCellsCache = {};
  words.forEach(function (w) { wordCellsCache[w.index] = wordCells(w); });

  // For each cell, which words own it?
  var cellWordMap = {};  // "r,c" → [wordIndex, ...]
  words.forEach(function (w) {
    wordCellsCache[w.index].forEach(function (key) {
      cellWordMap[key] = cellWordMap[key] || [];
      cellWordMap[key].push(w.index);
    });
  });

  // ---------------------------------------------------------------------------
  // Selection helpers
  // ---------------------------------------------------------------------------

  function clearHighlight() {
    tds.forEach(function (td) {
      td.classList.remove('active-word', 'active-cell');
    });
    document.querySelectorAll('.cw-clue-item').forEach(function (el) {
      el.classList.remove('active-clue');
    });
  }

  function highlightWord(wordIndex, focusKey) {
    clearHighlight();
    if (wordIndex === null) {
      activeWordIndex = null;
      btnReveal.disabled = true;
      _updateMobileBar(null);
      return;
    }
    activeWordIndex = wordIndex;
    btnReveal.disabled = checked;

    var cells = wordCellsCache[wordIndex];
    cells.forEach(function (key) {
      if (cellMap[key]) cellMap[key].classList.add('active-word');
    });
    if (focusKey && cellMap[focusKey]) {
      cellMap[focusKey].classList.add('active-cell');
      cellMap[focusKey].classList.remove('active-word');
    }

    // Highlight clue items
    document.querySelectorAll('.cw-clue-item[data-word-index="' + wordIndex + '"]').forEach(function (el) {
      el.classList.add('active-clue');
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });

    _updateMobileBar(wordIndex);
  }

  function _updateMobileBar(wordIndex) {
    if (!mcNum || !mcText) return;
    if (wordIndex === null) {
      mcNum.textContent  = '';
      mcText.textContent = 'Select a cell to see its clue';
      return;
    }
    var word = words.find(function (w) { return w.index === wordIndex; });
    if (!word) return;
    mcNum.textContent  = word.number + (word.direction === 'across' ? 'A' : 'D');
    mcText.textContent = word.clue;
  }

  // ---------------------------------------------------------------------------
  // Click on cell → select word
  // ---------------------------------------------------------------------------

  function cellKey(td) { return td.dataset.row + ',' + td.dataset.col; }

  tds.forEach(function (td) {
    td.addEventListener('click', function () {
      var key  = cellKey(td);
      var owns = cellWordMap[key] || [];
      if (!owns.length) return;

      if (owns.length === 1) {
        activeDirection = words.find(function(w){ return w.index === owns[0]; }).direction;
        highlightWord(owns[0], key);
      } else {
        // Toggle across ↔ down
        var currentOwner = owns.find(function (i) { return i === activeWordIndex; });
        var next;
        if (currentOwner !== undefined) {
          // Cycle to the other word
          next = owns.find(function (i) { return i !== activeWordIndex; });
        } else {
          // Default: prefer across
          var acrossWord = owns.find(function (i) {
            return words.find(function(w){ return w.index===i; }).direction === 'across';
          });
          next = acrossWord !== undefined ? acrossWord : owns[0];
        }
        activeDirection = words.find(function(w){ return w.index === next; }).direction;
        highlightWord(next, key);
      }

      if (inputMap[key]) inputMap[key].focus();
    });
  });

  // ---------------------------------------------------------------------------
  // Clue panel click → jump to word
  // ---------------------------------------------------------------------------

  document.querySelectorAll('.cw-clue-item').forEach(function (el) {
    el.addEventListener('click', function () {
      var idx = parseInt(el.dataset.wordIndex, 10);
      if (isNaN(idx)) return;
      var word = words.find(function (w) { return w.index === idx; });
      if (!word) return;
      var firstKey = word.row + ',' + word.col;
      activeDirection = word.direction;
      highlightWord(idx, firstKey);
      if (inputMap[firstKey]) inputMap[firstKey].focus();
      if (modal) modal.classList.remove('open');
    });
  });

  // ---------------------------------------------------------------------------
  // Keyboard handling
  // ---------------------------------------------------------------------------

  function nextKey(key, direction) {
    var parts = key.split(',');
    var r = parseInt(parts[0], 10);
    var c = parseInt(parts[1], 10);
    if (direction === 'across') c++;
    else r++;
    return r + ',' + c;
  }

  function prevKey(key, direction) {
    var parts = key.split(',');
    var r = parseInt(parts[0], 10);
    var c = parseInt(parts[1], 10);
    if (direction === 'across') c--;
    else r--;
    return r + ',' + c;
  }

  function arrowKey(key, arrow) {
    var parts = key.split(',');
    var r = parseInt(parts[0], 10);
    var c = parseInt(parts[1], 10);
    if (arrow === 'ArrowRight') c++;
    else if (arrow === 'ArrowLeft')  c--;
    else if (arrow === 'ArrowDown')  r++;
    else if (arrow === 'ArrowUp')    r--;
    return r + ',' + c;
  }

  function currentKeyOf(inp) {
    var td = inp.closest('td');
    return td ? cellKey(td) : null;
  }

  Object.keys(inputMap).forEach(function (key) {
    var inp = inputMap[key];

    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Tab') {
        e.preventDefault();
        _jumpNextWord(e.shiftKey);
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        _jumpNextWord(false);
        return;
      }
      if (['ArrowRight','ArrowLeft','ArrowDown','ArrowUp'].indexOf(e.key) !== -1) {
        e.preventDefault();
        var dest = arrowKey(key, e.key);
        if (inputMap[dest]) {
          inputMap[dest].focus();
          var owns = cellWordMap[dest] || [];
          if (owns.length) highlightWord(owns[0], dest);
        }
        return;
      }
      if (e.key === 'Backspace') {
        if (inp.value === '') {
          e.preventDefault();
          var prev = prevKey(key, activeDirection);
          if (inputMap[prev]) {
            inputMap[prev].value = '';
            inputMap[prev].focus();
          }
        }
      }
    });

    inp.addEventListener('input', function () {
      // Clamp to first grapheme cluster
      var val = inp.value;
      if (val.length > 1) {
        var segs = [];
        if (typeof Intl !== 'undefined' && Intl.Segmenter) {
          var seg = new Intl.Segmenter();
          for (var s of seg.segment(val)) { segs.push(s.segment); }
        } else {
          segs = Array.from(val);
        }
        inp.value = segs[0] || '';
      }
      // Auto-advance
      if (inp.value.length > 0 && activeWordIndex !== null) {
        var nk = nextKey(key, activeDirection);
        if (inputMap[nk] && (wordCellsCache[activeWordIndex] || []).indexOf(nk) !== -1) {
          inputMap[nk].focus();
          highlightWord(activeWordIndex, nk);
        }
      }
    });

    inp.addEventListener('focus', function () {
      var owns = cellWordMap[key] || [];
      if (!owns.length) return;

      // Keep current word if this cell belongs to it
      if (activeWordIndex !== null && owns.indexOf(activeWordIndex) !== -1) {
        highlightWord(activeWordIndex, key);
      } else {
        var preferred = owns.find(function (i) {
          return words.find(function(w){ return w.index===i; }).direction === activeDirection;
        });
        highlightWord(preferred !== undefined ? preferred : owns[0], key);
      }
    });
  });

  function _jumpNextWord(reverse) {
    if (!words.length) return;
    var idx = words.findIndex(function (w) { return w.index === activeWordIndex; });
    var next = reverse ? (idx - 1 + words.length) % words.length : (idx + 1) % words.length;
    var word = words[next];
    var firstKey = word.row + ',' + word.col;
    activeDirection = word.direction;
    highlightWord(word.index, firstKey);
    if (inputMap[firstKey]) inputMap[firstKey].focus();
  }

  // ---------------------------------------------------------------------------
  // Check
  // ---------------------------------------------------------------------------

  btnCheck.addEventListener('click', function () {
    if (checked) return;
    checked = true;
    btnReveal.disabled = true;

    var wordAnswers = {};
    words.forEach(function (word) {
      var cells = wordCellsCache[word.index];
      var typed = cells.map(function (k) { return (inputMap[k] || {value:''}).value || ''; }).join('');
      wordAnswers[String(word.index)] = typed;
    });

    var fd = new FormData();
    fd.append('word_answers',     JSON.stringify(wordAnswers));
    fd.append('hints_used',       JSON.stringify(hintsUsed));
    fd.append('csrfmiddlewaretoken', csrfToken);

    fetch(submitUrl, { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (data) { _applyResults(data); })
      .catch(function () {
        checked = false;
        btnReveal.disabled = (activeWordIndex === null);
      });
  });

  function _stageUnlockedToast() {
    var t = document.createElement('div');
    t.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#059669;color:#fff;padding:14px 28px;border-radius:14px;font-size:14px;font-weight:700;box-shadow:0 6px 24px rgba(0,0,0,.18);z-index:9999;transition:opacity .5s';
    t.textContent = '🎉 Stage Unlocked! The next level is now available.';
    document.body.appendChild(t);
    setTimeout(function () { t.style.opacity = '0'; }, 3500);
    setTimeout(function () { t.remove(); }, 4000);
  }

  function _applyResults(data) {
    if (data.stage_unlocked) setTimeout(_stageUnlockedToast, 800);
    clearHighlight();
    activeWordIndex = null;

    (data.results || []).forEach(function (r) {
      var cells = wordCellsCache[r.index] || [];
      cells.forEach(function (key) {
        if (cellMap[key]) {
          cellMap[key].classList.remove('cell-correct', 'cell-incorrect');
          cellMap[key].classList.add(r.correct ? 'cell-correct' : 'cell-incorrect');
        }
        if (inputMap[key]) inputMap[key].disabled = true;
      });
    });

    var pct    = Math.round(data.score || 0);
    var total  = data.total  || words.length;
    var correct = data.correct_count || 0;

    if (pct >= 80) {
      resultIcon.textContent = '🎉';
      resultMsg.textContent  = 'Excellent! ' + correct + '/' + total + ' words correct';
      resultMsg.style.color  = '#059669';
    } else if (pct >= 50) {
      resultIcon.textContent = '👍';
      resultMsg.textContent  = correct + '/' + total + ' words correct';
      resultMsg.style.color  = '#d97706';
    } else {
      resultIcon.textContent = '✗';
      resultMsg.textContent  = correct + '/' + total + ' words correct';
      resultMsg.style.color  = '#dc2626';
    }
    resultSub.textContent = 'Score: ' + pct + '%  ·  ' + data.points_earned + ' point' + (data.points_earned !== '1' ? 's' : '') + ' earned';

    if (resultDiv) {
      resultDiv.classList.add('show');
      if (pct >= 80) {
        resultDiv.style.borderColor = '#059669';
        resultDiv.style.background  = '#f0fdf4';
      } else if (pct >= 50) {
        resultDiv.style.borderColor = '#d97706';
        resultDiv.style.background  = '#fffbeb';
      } else {
        resultDiv.style.borderColor = '#dc2626';
        resultDiv.style.background  = '#fef2f2';
      }
      resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  // ---------------------------------------------------------------------------
  // Reveal Word
  // ---------------------------------------------------------------------------

  btnReveal.addEventListener('click', function () {
    if (activeWordIndex === null || checked) return;
    var word = words.find(function (w) { return w.index === activeWordIndex; });
    if (!word) return;

    var cells = wordCellsCache[word.index];
    var answer = word.answer;
    cells.forEach(function (key, i) {
      if (inputMap[key]) {
        inputMap[key].value = Array.from(answer)[i] || '';
      }
    });

    if (hintsUsed.indexOf(word.index) === -1) hintsUsed.push(word.index);
    btnReveal.disabled = true;
  });

  // ---------------------------------------------------------------------------
  // Try Again
  // ---------------------------------------------------------------------------

  btnReset.addEventListener('click', function () {
    checked   = false;
    hintsUsed = [];
    activeWordIndex = null;

    Object.keys(inputMap).forEach(function (key) {
      inputMap[key].value    = '';
      inputMap[key].disabled = false;
    });
    tds.forEach(function (td) {
      td.classList.remove('active-word', 'active-cell', 'cell-correct', 'cell-incorrect');
    });
    document.querySelectorAll('.cw-clue-item').forEach(function (el) {
      el.classList.remove('active-clue');
    });
    btnReveal.disabled = true;
    if (resultDiv) resultDiv.classList.remove('show');
    if (mcNum)   mcNum.textContent  = '';
    if (mcText)  mcText.textContent = 'Select a cell to see its clue';
  });

  // ---------------------------------------------------------------------------
  // Mobile modal
  // ---------------------------------------------------------------------------

  if (mobileBar) {
    mobileBar.addEventListener('click', function () { if (modal) modal.classList.add('open'); });
    mobileBar.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (modal) modal.classList.add('open'); }
    });
  }
  if (modal) {
    modal.addEventListener('click', function (e) {
      if (e.target === modal) modal.classList.remove('open');
    });
  }

})();
