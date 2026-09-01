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
  // Guide character writing animation — authored stroke order (CPP-393)
  //
  // Stroke order and direction come from window.STROKE_ORDER_DATA
  // (stroke_order_data.js), resolved onto the actual glyph's skeleton by
  // window.StrokeOrder (stroke_order.js). This file only plays the result
  // back: one stroke at a time, pen dot + direction arrow, a pause between
  // strokes, and a visible stroke-count badge. A character with no
  // authored entry shows the static glyph with no direction arrow — never
  // a guessed path (see stroke_order.js's module doc for why).
  // ---------------------------------------------------------------------------
  (function () {
    var animCanvas = document.getElementById('guide-anim');
    if (!animCanvas) return;

    // Canvas dimensions — match the ruled proportions of the main canvas
    var AW = 240, AH = 160;
    animCanvas.width  = AW;
    animCanvas.height = AH;
    var ctx      = animCanvas.getContext('2d');

    // Ruled line positions inside the animation canvas
    var A_TOP_PAD = 18;
    var A_LH      = AH - A_TOP_PAD * 2 - 20; // leave room for descender area
    var A_TOP_Y   = A_TOP_PAD;
    var A_MID_Y   = A_TOP_PAD + A_LH * 0.4;
    var A_BASE_Y  = A_TOP_PAD + A_LH;

    var fSize    = Math.floor(A_LH * 0.88);
    var fontSpec = 'bold ' + fSize + 'px ' + fontFamily + ', sans-serif';
    var scriptType = wrapper.dataset.scriptType || 'latin';

    // Draw lined paper background
    function drawBg() {
      ctx.fillStyle = '#fafaf8';
      ctx.fillRect(0, 0, AW, AH);
      // Top line
      ctx.beginPath(); ctx.moveTo(0, A_TOP_Y); ctx.lineTo(AW, A_TOP_Y);
      ctx.strokeStyle = '#b8d4ea'; ctx.lineWidth = 1; ctx.setLineDash([]); ctx.stroke();
      // Mid dashed
      ctx.beginPath(); ctx.moveTo(0, A_MID_Y); ctx.lineTo(AW, A_MID_Y);
      ctx.strokeStyle = '#b8d4ea'; ctx.lineWidth = 1; ctx.setLineDash([4, 6]); ctx.stroke();
      ctx.setLineDash([]);
      // Baseline (blue)
      ctx.beginPath(); ctx.moveTo(0, A_BASE_Y); ctx.lineTo(AW, A_BASE_Y);
      ctx.strokeStyle = '#5b9bd5'; ctx.lineWidth = 2; ctx.stroke();
    }

    // Box-blur smoothing on path coordinates
    function smoothPath(pts, iters) {
      var p = pts.slice();
      for (var k = 0; k < iters; k++) {
        var np = p.slice();
        for (var i = 1; i < p.length - 1; i++)
          np[i] = { x: (p[i-1].x+p[i].x+p[i+1].x)/3, y: (p[i-1].y+p[i].y+p[i+1].y)/3 };
        p = np;
      }
      return p;
    }

    // Renders the full glyph to an offscreen canvas for the faint ghost
    // backdrop (and the no-data fallback). Independent of stroke_order.js's
    // own internal render — this one just needs to look good, not be
    // thresholded for skeleton extraction. Falls back to an SVG render if
    // canvas fillText produced nothing (complex-script font not ready).
    function renderGhost(callback) {
      var off = document.createElement('canvas');
      off.width = AW; off.height = AH;
      var oCtx = off.getContext('2d');
      oCtx.fillStyle = '#ffffff';
      oCtx.fillRect(0, 0, AW, AH);
      oCtx.font = fontSpec;
      oCtx.textAlign    = 'center';
      oCtx.textBaseline = 'alphabetic';
      oCtx.fillStyle    = '#1e3a8a';
      oCtx.fillText(guideChar, AW / 2, A_BASE_Y);

      var imgData = oCtx.getImageData(0, 0, AW, AH);
      var charPx = 0;
      for (var i = 0; i < AW * AH; i++) {
        var lum = 0.299*imgData.data[i*4] + 0.587*imgData.data[i*4+1] + 0.114*imgData.data[i*4+2];
        if (lum < 128) charPx++;
      }

      if (charPx >= 50) { callback(off); return; }

      var esc = guideChar.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      var svgSrc = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="'+AW+'" height="'+AH+'">' +
        '<rect width="100%" height="100%" fill="white"/>' +
        '<text x="'+Math.round(AW/2)+'" y="'+A_BASE_Y+'" ' +
        'font-family="'+fontFamily+', sans-serif" font-size="'+fSize+'" font-weight="bold" ' +
        'fill="#1e3a8a" text-anchor="middle">'+esc+'</text></svg>');
      var svgImg = new Image();
      svgImg.onload = function() {
        oCtx.clearRect(0, 0, AW, AH);
        oCtx.fillStyle = '#ffffff'; oCtx.fillRect(0, 0, AW, AH);
        oCtx.drawImage(svgImg, 0, 0);
        callback(off);
      };
      svgImg.onerror = function() { callback(off); };
      svgImg.src = svgSrc;
    }

    // No authored stroke data (or the glyph failed to render at all) —
    // fade the static ghost in/out. No pen, no direction arrow: a guessed
    // path is exactly the CPP-393 defect, so this is the honest fallback.
    function animateStaticFallback(off) {
      var opacity = 0, rising = true;
      (function fadeFallback() {
        drawBg();
        ctx.globalAlpha = opacity; ctx.drawImage(off, 0, 0); ctx.globalAlpha = 1;
        opacity += rising ? 0.012 : -0.012;
        if (opacity >= 0.85) rising = false;
        if (opacity <= 0) { rising = true; opacity = 0; }
        requestAnimationFrame(fadeFallback);
      })();
    }

    function drawPen(p, angle) {
      // Pencil tip glow
      ctx.beginPath();
      ctx.arc(p.x, p.y, 13, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(239,68,68,0.15)';
      ctx.fill();
      // Core dot
      ctx.beginPath();
      ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
      ctx.fillStyle = '#ef4444';
      ctx.fill();
      // Direction arrow
      if (angle !== null) {
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(angle);
        ctx.beginPath();
        ctx.moveTo(18, 0); ctx.lineTo(9, -6); ctx.lineTo(9, 6);
        ctx.closePath();
        ctx.fillStyle = '#ef4444';
        ctx.fill();
        ctx.restore();
      }
    }

    // Visible "Stroke n / total" badge, top-left — makes the stroke count
    // teachable per CPP-393's acceptance criteria.
    function drawStrokeBadge(n, total) {
      var label = 'Stroke ' + n + ' / ' + total;
      ctx.font = 'bold 11px sans-serif';
      var tw = ctx.measureText(label).width;
      var padX = 8, boxH = 20, boxW = tw + padX * 2;
      ctx.fillStyle = 'rgba(30,58,138,0.85)';
      if (ctx.roundRect) {
        ctx.beginPath(); ctx.roundRect(6, 6, boxW, boxH, 10); ctx.fill();
      } else {
        ctx.fillRect(6, 6, boxW, boxH);
      }
      ctx.fillStyle = '#fff';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, 6 + padX, 6 + boxH / 2 + 1);
    }

    function animateStrokes(resolved, off) {
      var strokes = resolved.strokes
        .map(function (pts) { return pts.length > 1 ? smoothPath(pts, 3) : pts; })
        .filter(function (pts) { return pts.length > 0; });
      if (!strokes.length) { animateStaticFallback(off); return; }

      var inkPx = 0, skelPx = 0;
      for (var i = 0; i < resolved.mask.length; i++) if (resolved.mask[i]) inkPx++;
      for (var j = 0; j < resolved.skeleton.length; j++) if (resolved.skeleton[j]) skelPx++;
      var strokeW = skelPx > 0 ? Math.max(4, Math.round(inkPx / skelPx)) : 10;

      var strokeIdx = 0, pointIdx = 0, pausing = 0;
      var INTRO_FRAMES = 70;   // ~1.1s pulsing "START" before the very first stroke
      var PAUSE_BETWEEN = 45;  // pen-lift pause between strokes
      var PAUSE_END = 130;     // hold the finished character before restart
      var intro = INTRO_FRAMES;

      function drawStrokeTrail(pathArr, upTo) {
        if (pathArr.length === 1) {
          // Single-anchor stroke = a dot (e.g. the tittle on "i"/"j").
          ctx.beginPath();
          ctx.arc(pathArr[0].x, pathArr[0].y, Math.max(3, strokeW / 2), 0, Math.PI * 2);
          ctx.fillStyle = '#1e3a8a';
          ctx.fill();
          return;
        }
        if (upTo < 1) return;
        ctx.beginPath();
        ctx.moveTo(pathArr[0].x, pathArr[0].y);
        for (var i = 1; i <= Math.min(upTo, pathArr.length - 1); i++) {
          var jump = Math.abs(pathArr[i].x-pathArr[i-1].x) > 8 || Math.abs(pathArr[i].y-pathArr[i-1].y) > 8;
          if (jump) {
            ctx.stroke(); ctx.beginPath(); ctx.moveTo(pathArr[i].x, pathArr[i].y);
          } else if (i < pathArr.length - 1) {
            var mx = (pathArr[i].x + pathArr[i+1].x) / 2;
            var my = (pathArr[i].y + pathArr[i+1].y) / 2;
            ctx.quadraticCurveTo(pathArr[i].x, pathArr[i].y, mx, my);
          } else {
            ctx.lineTo(pathArr[i].x, pathArr[i].y);
          }
        }
        ctx.strokeStyle = '#1e3a8a';
        ctx.lineWidth   = strokeW;
        ctx.lineCap     = 'round';
        ctx.lineJoin    = 'round';
        ctx.stroke();
      }

      function frame() {
        drawBg();

        // Faint ghost of full character
        ctx.globalAlpha = 0.10;
        ctx.drawImage(off, 0, 0);
        ctx.globalAlpha = 1;

        // Strokes already completed this pass stay fully visible.
        for (var si = 0; si < strokeIdx; si++) {
          drawStrokeTrail(strokes[si], strokes[si].length - 1);
        }

        var path = strokes[strokeIdx];

        if (intro > 0 && strokeIdx === 0 && pointIdx === 0) {
          var pulse = (Math.sin((INTRO_FRAMES - intro) * 0.12) + 1) / 2;
          var sp = path[0];
          ctx.beginPath();
          ctx.arc(sp.x, sp.y, 14 + pulse * 6, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(239,68,68,' + (0.12 + pulse * 0.22) + ')';
          ctx.fill();
          ctx.beginPath();
          ctx.arc(sp.x, sp.y, 6, 0, Math.PI * 2);
          ctx.fillStyle = '#ef4444'; ctx.fill();
          ctx.font = 'bold 12px sans-serif';
          ctx.fillStyle = '#ef4444';
          ctx.textAlign = 'center';
          ctx.fillText('START HERE', sp.x, sp.y - 18);
          drawStrokeBadge(strokeIdx + 1, strokes.length);
          intro--;

        } else if (!pausing && pointIdx < path.length) {
          drawStrokeTrail(path, pointIdx);

          var cp    = path[pointIdx];
          var prev  = path[Math.max(0, pointIdx - 5)];
          var angle = pointIdx > 5 ? Math.atan2(cp.y - prev.y, cp.x - prev.x) : null;
          drawPen(cp, angle);
          drawStrokeBadge(strokeIdx + 1, strokes.length);

          pointIdx++;

        } else if (!pausing) {
          drawStrokeTrail(path, path.length - 1);
          drawStrokeBadge(strokeIdx + 1, strokes.length);
          pausing = (strokeIdx === strokes.length - 1) ? PAUSE_END : PAUSE_BETWEEN;

        } else {
          drawStrokeTrail(path, path.length - 1);
          drawStrokeBadge(strokeIdx + 1, strokes.length);
          pausing--;
          if (!pausing) {
            if (strokeIdx < strokes.length - 1) {
              strokeIdx++; pointIdx = 0;
            } else {
              strokeIdx = 0; pointIdx = 0; intro = INTRO_FRAMES;
            }
          }
        }

        requestAnimationFrame(frame);
      }
      frame();
    }

    function startAnim() {
      renderGhost(function (off) {
        var strokeData = window.STROKE_ORDER_DATA &&
                          window.STROKE_ORDER_DATA[scriptType] &&
                          window.STROKE_ORDER_DATA[scriptType][guideChar];

        // Reuse the ghost's own render (canvas, with its SVG retry already
        // applied if the complex-script font needed it) instead of having
        // StrokeOrder.resolve() re-render `guideChar` from scratch — avoids
        // a second full fillText + getImageData pass, and means the
        // skeleton engine gets the same fallback robustness the ghost has
        // rather than silently failing where the ghost would have recovered.
        var resolved = (strokeData && window.StrokeOrder) ? window.StrokeOrder.resolve({
          strokes: strokeData,
          canvas:  off,
          w: AW, h: AH,
        }) : null;

        if (!resolved) {
          if (strokeData && window.console && console.warn) {
            console.warn('[stroke-order] authored data exists for ' + JSON.stringify(guideChar) +
              ' (' + scriptType + ') but failed to resolve onto the rendered glyph — showing the static fallback.');
          }
          animateStaticFallback(off);
          return;
        }
        animateStrokes(resolved, off);
      });
    }

    if (document.fonts) {
      document.fonts.load(fontSpec, guideChar).then(startAnim).catch(startAnim);
    } else {
      startAnim();
    }
  })();

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
