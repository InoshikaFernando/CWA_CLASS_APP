(function () {
  'use strict';

  var wrapper    = document.getElementById('whiteboard-wrapper');
  if (!wrapper) return;

  var lineHeight = parseInt(wrapper.dataset.lineHeight, 10);
  var descender  = parseInt(wrapper.dataset.descender,  10);
  var numLines   = parseInt(wrapper.dataset.lines,      10);
  var guideChar  = wrapper.dataset.guideChar  || '?';
  var fontFamily = wrapper.dataset.fontFamily || 'sans-serif';
  var submitUrl  = wrapper.dataset.submitUrl;
  var csrfToken  = wrapper.dataset.csrf;

  var TOP_PAD   = 24;
  var W         = wrapper.offsetWidth || 600;
  var H         = TOP_PAD + lineHeight + descender + TOP_PAD;
  var FONT_SIZE = Math.floor(lineHeight * 0.9);
  var BASE_Y    = TOP_PAD + lineHeight;

  // ---------------------------------------------------------------------------
  // Fabric canvas — full width, student draws anywhere
  // ---------------------------------------------------------------------------
  var fc = new fabric.Canvas('drawing-layer', {
    width:           W,
    height:          H,
    isDrawingMode:   false,
    selection:       false,
    backgroundColor: '#fafaf8',
  });
  if (window.__E2E_TEST__) { window._fabricCanvas = fc; }

  // ---------------------------------------------------------------------------
  // Ruled lines (full width — no left/right split)
  // ---------------------------------------------------------------------------
  var BG_OPTS = {
    selectable: false, evented: false,
    hasControls: false, hasBorders: false,
    lockMovementX: true, lockMovementY: true,
    excludeFromExport: true,
  };

  var bgHLines = [];

  function drawRuledLines() {
    var topY  = TOP_PAD;
    var midY  = TOP_PAD + lineHeight * 0.4;
    var baseY = TOP_PAD + lineHeight;
    var descY = TOP_PAD + lineHeight + descender;

    var ruleY = [topY, midY, baseY];
    if (numLines >= 4 && descender > 0) ruleY.push(descY);

    ruleY.forEach(function (y, i) {
      var isBase = (i === 2);
      var line = new fabric.Line([0, y, W, y], Object.assign({}, BG_OPTS, {
        stroke:          isBase ? '#5b9bd5' : '#b8d4ea',
        strokeWidth:     isBase ? 2 : 1,
        strokeDashArray: (i === 1) ? [4, 6] : [],
      }));
      bgHLines.push(line);
      fc.add(line);
    });

    // "Write here" watermark text centered on canvas
    fc.add(new fabric.Text('Write here', Object.assign({}, BG_OPTS, {
      left: W / 2, top: H / 2,
      fontSize: 14, fontFamily: 'sans-serif', fontWeight: '600',
      fill: 'rgba(5,150,105,0.20)', originX: 'center', originY: 'center',
    })));
  }

  drawRuledLines();

  // ---------------------------------------------------------------------------
  // Faint guide character on drawing canvas (trace-over helper)
  // ---------------------------------------------------------------------------
  (function () {
    var fSpec = 'bold ' + FONT_SIZE + 'px ' + fontFamily + ', sans-serif';

    function placeGuide() {
      var gOff = document.createElement('canvas');
      gOff.width = W; gOff.height = H;
      var gCtx = gOff.getContext('2d');
      gCtx.font          = fSpec;
      gCtx.textAlign     = 'center';
      gCtx.textBaseline  = 'alphabetic';
      gCtx.fillStyle     = '#3b82f6';
      gCtx.fillText(guideChar, W / 2, BASE_Y);

      fabric.Image.fromURL(gOff.toDataURL(), function (img) {
        img.set(Object.assign({}, BG_OPTS, { left: 0, top: 0, opacity: 0.18 }));
        fc.add(img);
        fc.renderAll();
      });
    }

    if (document.fonts) {
      document.fonts.load(fSpec, guideChar).then(placeGuide).catch(placeGuide);
    } else {
      placeGuide();
    }
  })();

  fc.renderAll();

  // ---------------------------------------------------------------------------
  // Freehand drawing
  // ---------------------------------------------------------------------------
  fc.isDrawingMode = true;
  fc.freeDrawingBrush = new fabric.PencilBrush(fc);
  fc.freeDrawingBrush.color = '#1a1a1a';
  fc.freeDrawingBrush.width = 3;

  // ---------------------------------------------------------------------------
  // Stroke history (undo)
  // ---------------------------------------------------------------------------
  var history = [];

  fc.on('path:created', function (e) {
    history.push(e.path);
    syncUI();
  });

  // ---------------------------------------------------------------------------
  // UI elements
  // ---------------------------------------------------------------------------
  var btnSubmit  = document.getElementById('btn-submit');
  var btnClear   = document.getElementById('btn-clear');
  var btnUndo    = document.getElementById('btn-undo');
  var btnRetry   = document.getElementById('btn-retry');
  var scorePanel = document.getElementById('score-panel');

  function syncUI() {
    var count = history.length;
    btnSubmit.disabled = (count === 0);
    btnUndo.disabled   = (count === 0);
  }
  syncUI();

  function clearCanvas() {
    history.forEach(function (p) { fc.remove(p); });
    history = [];
    fc.renderAll();
    syncUI();
  }

  btnClear.addEventListener('click', clearCanvas);

  btnUndo.addEventListener('click', function () {
    if (!history.length) return;
    fc.remove(history.pop());
    fc.renderAll();
    syncUI();
  });

  btnRetry.addEventListener('click', function () {
    clearCanvas();
    scorePanel.setAttribute('hidden', '');
    fc.isDrawingMode = true;
    btnSubmit.textContent = 'Submit';
  });

  // ---------------------------------------------------------------------------
  // Scoring — the server is authoritative (languages/scoring.py). It
  // recomputes the score from the ink snapshot below rather than trusting a
  // client-submitted number, and uses a skeleton-corridor metric instead of
  // raw pixel IoU so pen-stroke width vs. font-glyph fill width no longer
  // caps a correctly-formed character's score (CPP-392). This file only
  // captures the ink and renders whatever the server returns.
  // ---------------------------------------------------------------------------

  function captureInkPng() {
    var scratch = document.createElement('canvas');
    scratch.width = W; scratch.height = H;
    scratch.getContext('2d').drawImage(fc.lowerCanvasEl, 0, 0);
    return scratch.toDataURL('image/png').replace(/^data:image\/png;base64,/, '');
  }

  // ---------------------------------------------------------------------------
  // Score panel
  // ---------------------------------------------------------------------------
  var STAR_MSGS   = ['Keep practising!', 'Good effort!', 'Well done!', 'Excellent!'];
  var STAR_COLORS = ['#d97706', '#2563eb', '#059669', '#047857'];
  var REASON_TIPS = {
    excellent_match:       'Perfect match — you nailed it!',
    close_match:           'Great shape! Push for full marks by matching all the curves.',
    shape_incomplete:      'Parts of the letter are missing — make sure every stroke is drawn.',
    strokes_outside_shape: "Some strokes go outside the letter's shape — try to stay closer to the outline.",
    shape_mismatch:        "That doesn't look like the target letter — check the guide and try again.",
    needs_practice:        'Keep practising — compare your shape closely with the guide.',
    no_ink:                'Draw the character before submitting.',
    too_little_ink:        'That looks like a single mark rather than the letter — try drawing the full shape.',
    unscored_fallback:     'Saved your attempt — this character can’t be auto-scored yet.',
  };

  function showScorePanel(score, stars, reason, bestScore) {
    var starEls = scorePanel.querySelectorAll('.wb-star');
    var pctEl   = document.getElementById('score-pct');
    var msgEl   = document.getElementById('score-msg');
    var tipEl   = document.getElementById('score-tip');
    var bestEl  = document.getElementById('best-badge');

    starEls.forEach(function (s) { s.style.color = '#d1d5db'; });
    for (var i = 0; i < stars; i++) {
      (function (idx) {
        setTimeout(function () { starEls[idx].style.color = '#f59e0b'; }, idx * 250);
      })(i);
    }

    pctEl.textContent  = score + '%';
    msgEl.textContent  = STAR_MSGS[stars];
    msgEl.style.color  = STAR_COLORS[stars];
    if (tipEl)  tipEl.textContent  = REASON_TIPS[reason] || REASON_TIPS.needs_practice;
    if (bestEl) bestEl.textContent = 'Your best: ' + Math.max(score, bestScore) + '%';

    scorePanel.removeAttribute('hidden');
  }

  function showScoringError(message) {
    var msgEl = document.getElementById('score-msg');
    var tipEl = document.getElementById('score-tip');
    var pctEl = document.getElementById('score-pct');
    scorePanel.querySelectorAll('.wb-star').forEach(function (s) { s.style.color = '#d1d5db'; });
    if (pctEl) pctEl.textContent = '';
    msgEl.textContent = 'Could not score this attempt';
    msgEl.style.color = '#dc2626';
    if (tipEl) tipEl.textContent = message;
    scorePanel.removeAttribute('hidden');
  }

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------
  btnSubmit.addEventListener('click', function () {
    var strokeData = JSON.stringify(fc.toJSON());
    var inkImage   = captureInkPng();

    btnSubmit.disabled    = true;
    btnSubmit.textContent = 'Scoring…';
    fc.isDrawingMode      = false;

    var fd = new FormData();
    fd.append('stroke_data', strokeData);
    fd.append('ink_image', inkImage);
    fd.append('csrfmiddlewaretoken', csrfToken);

    fetch(submitUrl, { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success) {
          showScorePanel(data.score, data.stars, data.reason, data.best_score);
          btnSubmit.textContent = 'Submit';
          if (data.stage_unlocked) setTimeout(function () {
            var t = document.createElement('div');
            t.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#059669;color:#fff;padding:14px 28px;border-radius:14px;font-size:14px;font-weight:700;box-shadow:0 6px 24px rgba(0,0,0,.18);z-index:9999;transition:opacity .5s';
            t.textContent = '🎉 Stage Unlocked! The next level is now available.';
            document.body.appendChild(t);
            setTimeout(function () { t.style.opacity = '0'; }, 3500);
            setTimeout(function () { t.remove(); }, 4000);
          }, 800);
        } else {
          showScoringError(data.error || 'Please try again.');
          btnSubmit.disabled    = false;
          btnSubmit.textContent = 'Submit';
          fc.isDrawingMode      = true;
        }
      })
      .catch(function () {
        showScoringError('Network error — check your connection and try again.');
        btnSubmit.disabled    = false;
        btnSubmit.textContent = 'Submit';
        fc.isDrawingMode      = true;
      });
  });

  // ---------------------------------------------------------------------------
  // Responsive resize
  // ---------------------------------------------------------------------------
  var lastW = W;
  function onResize() {
    var newW = wrapper.offsetWidth;
    if (!newW || Math.abs(newW - lastW) < 2) return;
    lastW = newW;
    fc.setWidth(newW);
    bgHLines.forEach(function (line) { line.set({ x2: newW }); });
    fc.renderAll();
  }
  window.addEventListener('resize', onResize);

})();
