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
  // Scoring — IoU on full canvas width
  // ---------------------------------------------------------------------------

  function _threshold(imageData, count) {
    var d = imageData.data, px = new Uint8Array(count);
    for (var i = 0; i < count; i++) {
      var lum = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2];
      px[i] = lum < 128 ? 1 : 0;
    }
    return px;
  }

  function _dilate(px, w, h, r) {
    var out = new Uint8Array(px.length);
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        if (!px[y * w + x]) continue;
        for (var dy = -r; dy <= r; dy++) {
          for (var dx = -r; dx <= r; dx++) {
            var ny = y + dy, nx = x + dx;
            if (ny >= 0 && ny < h && nx >= 0 && nx < w) out[ny * w + nx] = 1;
          }
        }
      }
    }
    return out;
  }

  function _autoCenter(px, w, h) {
    var sx = 0, sy = 0, n = 0;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        if (px[y * w + x]) { sx += x; sy += y; n++; }
      }
    }
    if (!n) return px;
    var dx = Math.round(w / 2 - sx / n);
    var dy = Math.round(h / 2 - sy / n);
    if (!dx && !dy) return px;
    var out = new Uint8Array(px.length);
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        if (!px[y * w + x]) continue;
        var nx = x + dx, ny = y + dy;
        if (nx >= 0 && nx < w && ny >= 0 && ny < h) out[ny * w + nx] = 1;
      }
    }
    return out;
  }

  function _normalizeScale(px, w, h) {
    var minX = w, maxX = -1, minY = h, maxY = -1;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        if (!px[y * w + x]) continue;
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
    }
    if (maxX < 0) return px;
    var bboxW = maxX - minX + 1, bboxH = maxY - minY + 1;
    var PAD = 4, tgtW = w - PAD * 2, tgtH = h - PAD * 2;
    var out = new Uint8Array(px.length);
    for (var sy = 0; sy < bboxH; sy++) {
      for (var sx = 0; sx < bboxW; sx++) {
        if (!px[(minY + sy) * w + (minX + sx)]) continue;
        var nx = Math.round(sx / (bboxW - 1 || 1) * tgtW) + PAD;
        var ny = Math.round(sy / (bboxH - 1 || 1) * tgtH) + PAD;
        if (nx >= 0 && nx < w && ny >= 0 && ny < h) out[ny * w + nx] = 1;
      }
    }
    return out;
  }

  function _iou(a, b) {
    var inter = 0, union = 0;
    for (var i = 0; i < a.length; i++) {
      if (a[i] || b[i]) union++;
      if (a[i] && b[i]) inter++;
    }
    return union === 0 ? 0 : Math.round(inter / union * 100);
  }

  function computeScore() {
    try {
      // Student pixels — full canvas
      var scratch = document.createElement('canvas');
      scratch.width = W; scratch.height = H;
      scratch.getContext('2d').drawImage(fc.lowerCanvasEl, 0, 0);
      var studentData = scratch.getContext('2d').getImageData(0, 0, W, H);
      var studentPx   = _threshold(studentData, W * H);

      // Template — render guide char on same-size offscreen canvas
      var tmpl = document.createElement('canvas');
      tmpl.width = W; tmpl.height = H;
      var tCtx = tmpl.getContext('2d');
      tCtx.fillStyle = '#fafaf8';
      tCtx.fillRect(0, 0, W, H);
      tCtx.fillStyle    = '#1a1a1a';
      tCtx.font         = 'bold ' + FONT_SIZE + 'px ' + fontFamily + ', sans-serif';
      tCtx.textAlign    = 'center';
      tCtx.textBaseline = 'alphabetic';
      tCtx.fillText(guideChar, W / 2, BASE_Y);
      var templateData = tCtx.getImageData(0, 0, W, H);
      var templatePx   = _threshold(templateData, W * H);

      // If template failed to render (complex script font issue), give generous
      // credit — student gets 72 for drawing anything meaningful
      var tmplCount = 0;
      for (var k = 0; k < templatePx.length; k++) if (templatePx[k]) tmplCount++;
      if (tmplCount < 80) {
        var stuCount = 0;
        for (var k = 0; k < studentPx.length; k++) if (studentPx[k]) stuCount++;
        return stuCount > 80 ? 72 : 0;
      }

      // normalize scale → center → dilate (r=12) → IoU
      // Larger dilation gives fair credit for rough/complex-script strokes
      studentPx  = _dilate(_autoCenter(_normalizeScale(studentPx,  W, H), W, H), W, H, 12);
      templatePx = _dilate(_autoCenter(_normalizeScale(templatePx, W, H), W, H), W, H, 12);

      return _iou(studentPx, templatePx);
    } catch (e) {
      return history.length > 0 ? 60 : 0;
    }
  }

  function starsFromScore(s) {
    if (s >= 85) return 3;
    if (s >= 70) return 2;
    if (s >= 50) return 1;
    return 0;
  }

  // ---------------------------------------------------------------------------
  // Score panel
  // ---------------------------------------------------------------------------
  var STAR_MSGS   = ['Keep practising!', 'Good effort!', 'Well done!', 'Excellent!'];
  var STAR_TIPS   = [
    'Look at the guide card above and try to match every stroke.',
    'Nearly there — try to fill the canvas height like the guide shows.',
    'Great shape! Push for full marks by matching all the curves.',
    'Perfect match — you nailed it!',
  ];
  var STAR_COLORS = ['#d97706', '#2563eb', '#059669', '#047857'];

  function showScorePanel(score, stars, bestScore) {
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
    if (tipEl)  tipEl.textContent  = STAR_TIPS[stars];
    if (bestEl) bestEl.textContent = 'Your best: ' + Math.max(score, bestScore) + '%';

    scorePanel.removeAttribute('hidden');
  }

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------
  btnSubmit.addEventListener('click', function () {
    var score      = computeScore();
    var stars      = starsFromScore(score);
    var strokeData = JSON.stringify(fc.toJSON());

    btnSubmit.disabled    = true;
    btnSubmit.textContent = 'Saving…';
    fc.isDrawingMode      = false;
    showScorePanel(score, stars, score);

    var fd = new FormData();
    fd.append('stroke_data', strokeData);
    fd.append('score', score);
    fd.append('csrfmiddlewaretoken', csrfToken);

    fetch(submitUrl, { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success) {
          var bestEl = document.getElementById('best-badge');
          if (bestEl) bestEl.textContent = 'Your best: ' + data.best_score + '%';
          btnSubmit.textContent = 'Submit';
        }
      })
      .catch(function () {
        btnSubmit.disabled    = false;
        btnSubmit.textContent = 'Submit';
        fc.isDrawingMode      = true;
        scorePanel.setAttribute('hidden', '');
      });
  });

  // ---------------------------------------------------------------------------
  // Guide character writing animation  (skeleton trace + smooth bezier)
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
    var A_DESC    = 20;
    var A_TOP_Y   = A_TOP_PAD;
    var A_MID_Y   = A_TOP_PAD + A_LH * 0.4;
    var A_BASE_Y  = A_TOP_PAD + A_LH;

    var fSize    = Math.floor(A_LH * 0.88);
    var fontSpec = 'bold ' + fSize + 'px ' + fontFamily + ', sans-serif';

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

    // Zhang-Suen iterative thinning
    function thin(src, w, h) {
      var px = new Uint8Array(src);
      var changed = true;
      while (changed) {
        changed = false;
        for (var pass = 0; pass < 2; pass++) {
          var rem = [];
          for (var y = 1; y < h - 1; y++) {
            for (var x = 1; x < w - 1; x++) {
              if (!px[y * w + x]) continue;
              var p2 = px[(y-1)*w+x],   p3 = px[(y-1)*w+x+1];
              var p4 = px[ y   *w+x+1], p5 = px[(y+1)*w+x+1];
              var p6 = px[(y+1)*w+x],   p7 = px[(y+1)*w+x-1];
              var p8 = px[ y   *w+x-1], p9 = px[(y-1)*w+x-1];
              var B  = p2+p3+p4+p5+p6+p7+p8+p9;
              if (B < 2 || B > 6) continue;
              var A = (!p2&&p3?1:0)+(!p3&&p4?1:0)+(!p4&&p5?1:0)+(!p5&&p6?1:0)+
                      (!p6&&p7?1:0)+(!p7&&p8?1:0)+(!p8&&p9?1:0)+(!p9&&p2?1:0);
              if (A !== 1) continue;
              if (pass === 0 && (p2*p4*p6 || p4*p6*p8)) continue;
              if (pass === 1 && (p2*p4*p8 || p2*p6*p8)) continue;
              rem.push(y * w + x);
            }
          }
          rem.forEach(function (i) { px[i] = 0; changed = true; });
        }
      }
      return px;
    }

    // DFS skeleton trace from topmost endpoint
    function traceSkeleton(skel, w, h) {
      var ptMap = {}, pts = [];
      for (var y = 0; y < h; y++)
        for (var x = 0; x < w; x++)
          if (skel[y*w+x]) { ptMap[y+'_'+x] = 1; pts.push({x:x, y:y}); }
      if (!pts.length) return [];

      function nbrs(p) {
        var n = [];
        for (var dy = -1; dy <= 1; dy++)
          for (var dx = -1; dx <= 1; dx++)
            if ((dx||dy) && ptMap[(p.y+dy)+'_'+(p.x+dx)]) n.push({x:p.x+dx, y:p.y+dy});
        return n;
      }

      var endpoints = pts.filter(function(p){ return nbrs(p).length === 1; });
      var start = (endpoints.length ? endpoints : pts).reduce(function(a,b){
        return a.y < b.y || (a.y===b.y && a.x < b.x) ? a : b;
      });

      var visited = {}, path = [];
      function dfs(p) {
        var k = p.y+'_'+p.x;
        if (visited[k]) return;
        visited[k] = 1; path.push(p);
        var ns = nbrs(p).filter(function(n){ return !visited[n.y+'_'+n.x]; });
        if (ns.length) dfs(ns[0]);
      }
      dfs(start);
      pts.forEach(function(p){ if (!visited[p.y+'_'+p.x]) dfs(p); });
      return path;
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

    function startAnim() {
      // Offscreen: render char at animation canvas size (white bg required —
      // transparent pixels have lum=0 and would corrupt the mask)
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
      var mask = new Uint8Array(AW * AH);
      var charPx = 0;
      for (var i = 0; i < AW * AH; i++) {
        var lum = 0.299*imgData.data[i*4] + 0.587*imgData.data[i*4+1] + 0.114*imgData.data[i*4+2];
        if (lum < 128) { mask[i] = 1; charPx++; }
      }

      // If canvas fillText rendered nothing (complex script font not ready),
      // retry via SVG — SVG text uses browser shaping engine same as HTML
      if (charPx < 50) {
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
          var d2 = oCtx.getImageData(0, 0, AW, AH);
          var m2 = new Uint8Array(AW * AH); var cp2 = 0;
          for (var ii = 0; ii < AW * AH; ii++) {
            var l2 = 0.299*d2.data[ii*4]+0.587*d2.data[ii*4+1]+0.114*d2.data[ii*4+2];
            if (l2 < 128) { m2[ii] = 1; cp2++; }
          }
          buildAndAnimate(off, m2, cp2);
        };
        svgImg.onerror = function() { buildAndAnimate(off, mask, charPx); };
        svgImg.src = svgSrc;
        return;
      }

      buildAndAnimate(off, mask, charPx);
    }

    function buildAndAnimate(off, mask, charPx) {
      var skel = thin(mask, AW, AH);
      var skelPx = 0;
      for (var j = 0; j < skel.length; j++) if (skel[j]) skelPx++;
      var strokeW = skelPx > 0 ? Math.max(4, Math.round(charPx / skelPx)) : 10;

      var rawPath = traceSkeleton(skel, AW, AH);
      if (!rawPath.length) {
        // Fallback: fade the ghost in/out when skeleton fails
        var opacity = 0, rising = true;
        (function fadeFallback() {
          drawBg();
          ctx.globalAlpha = opacity; ctx.drawImage(off, 0, 0); ctx.globalAlpha = 1;
          opacity += rising ? 0.012 : -0.012;
          if (opacity >= 0.85) rising = false;
          if (opacity <= 0) { rising = true; opacity = 0; }
          requestAnimationFrame(fadeFallback);
        })();
        return;
      }

      // Smooth the path for natural-looking strokes
      var path = smoothPath(rawPath, 5);

      var pathIdx = 0;
      var pausing = 0;
      var intro   = 100; // ~1.6s pulsing "START" intro
      var PAUSE   = 130; // hold complete char before restart

      function drawSmoothTrail(upTo) {
        if (upTo < 1) return;
        ctx.beginPath();
        ctx.moveTo(path[0].x, path[0].y);
        var inStroke = true;
        for (var i = 1; i <= Math.min(upTo, path.length - 1); i++) {
          var jump = Math.abs(path[i].x-path[i-1].x) > 8 || Math.abs(path[i].y-path[i-1].y) > 8;
          if (jump) {
            ctx.stroke(); ctx.beginPath(); ctx.moveTo(path[i].x, path[i].y);
          } else if (i < path.length - 1) {
            // Quadratic bezier through midpoints → smooth curve
            var mx = (path[i].x + path[i+1].x) / 2;
            var my = (path[i].y + path[i+1].y) / 2;
            ctx.quadraticCurveTo(path[i].x, path[i].y, mx, my);
          } else {
            ctx.lineTo(path[i].x, path[i].y);
          }
        }
        ctx.strokeStyle = '#1e3a8a';
        ctx.lineWidth   = strokeW;
        ctx.lineCap     = 'round';
        ctx.lineJoin    = 'round';
        ctx.stroke();
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

      function frame() {
        drawBg();

        // Faint ghost of full character
        ctx.globalAlpha = 0.10;
        ctx.drawImage(off, 0, 0);
        ctx.globalAlpha = 1;

        if (intro > 0) {
          // Pulse "START HERE" at the first stroke position
          var pulse = (Math.sin((100 - intro) * 0.12) + 1) / 2;
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
          intro--;

        } else if (!pausing && pathIdx < path.length) {
          drawSmoothTrail(pathIdx);

          var cp    = path[pathIdx];
          var prev  = path[Math.max(0, pathIdx - 5)];
          var angle = pathIdx > 5 ? Math.atan2(cp.y - prev.y, cp.x - prev.x) : null;
          drawPen(cp, angle);

          // Persistent small start dot
          ctx.beginPath();
          ctx.arc(path[0].x, path[0].y, 5, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(239,68,68,0.6)'; ctx.fill();

          pathIdx++;

        } else if (!pausing) {
          drawSmoothTrail(path.length - 1);
          pausing = PAUSE;
        } else {
          drawSmoothTrail(path.length - 1);
          pausing--;
          if (!pausing) { pathIdx = 0; intro = 70; }
        }

        requestAnimationFrame(frame);
      }
      frame();
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
