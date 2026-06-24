/*
 * Rough-work whiteboard — a lightweight scratchpad for maths questions.
 *
 * One floating pad per page, summoned by a pill button. Pure <canvas> +
 * Pointer Events so finger / stylus / mouse all work and tablet scrolling
 * never fights the drawing surface. Working is ephemeral — never submitted
 * or graded.
 *
 * Markup lives in templates/partials/_rough_work_whiteboard.html. This script
 * wires the behaviour and exposes window.RoughWork.clear() so one-question-at
 * -a-time quizzes can wipe the pad when the student advances.
 */
(function () {
  'use strict';

  function init() {
    var fab    = document.getElementById('rw-fab');
    var panel  = document.getElementById('rw-panel');
    var canvas = document.getElementById('rw-canvas');
    if (!fab || !panel || !canvas) return;

    var ctx     = canvas.getContext('2d');
    var color   = '#1e293b';
    var erasing = false;
    var drawing = false;
    var undo    = [];
    var UNDO_MAX = 25;

    // ── High-DPI backing store ───────────────────────────────────────────
    // Size the canvas to its displayed box × devicePixelRatio so strokes stay
    // crisp. Resizing clears the bitmap, so we preserve work across re-fits.
    function fit() {
      var rect = canvas.getBoundingClientRect();
      var w = rect.width || canvas.clientWidth || canvas.offsetWidth;
      var h = rect.height || canvas.clientHeight || 300;
      if (!w || !h) return;
      rect = { width: w, height: h };
      var dpr = window.devicePixelRatio || 1;
      var prev = canvas.width ? canvas.toDataURL() : null;
      canvas.width  = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      if (prev) {
        var img = new Image();
        img.onload = function () { ctx.drawImage(img, 0, 0, rect.width, rect.height); };
        img.src = prev;
      }
    }

    function point(e) {
      var rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    function snapshot() {
      try {
        if (undo.length >= UNDO_MAX) undo.shift();
        undo.push(canvas.toDataURL());
      } catch (err) { /* tainted canvas — undo simply unavailable */ }
    }

    function clearAll(takeSnapshot) {
      if (takeSnapshot) snapshot();
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    // ── Open / close ─────────────────────────────────────────────────────
    function open() {
      panel.classList.remove('hidden');
      fab.classList.add('hidden');
      fit();
    }
    function close() {
      panel.classList.add('hidden');
      fab.classList.remove('hidden');
    }
    fab.addEventListener('click', open);
    var closeBtn = document.getElementById('rw-close');
    if (closeBtn) closeBtn.addEventListener('click', close);

    // ── Tool selection ───────────────────────────────────────────────────
    var pens = panel.querySelectorAll('[data-rw-color]');
    var eraseBtn = document.getElementById('rw-erase');
    function selectPen(btn) {
      color = btn.getAttribute('data-rw-color');
      erasing = false;
      pens.forEach(function (b) { b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
      if (eraseBtn) eraseBtn.setAttribute('aria-pressed', 'false');
    }
    pens.forEach(function (btn) {
      btn.addEventListener('click', function () { selectPen(btn); });
    });
    if (eraseBtn) {
      eraseBtn.addEventListener('click', function () {
        erasing = true;
        pens.forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
        eraseBtn.setAttribute('aria-pressed', 'true');
      });
    }

    var undoBtn = document.getElementById('rw-undo');
    if (undoBtn) {
      undoBtn.addEventListener('click', function () {
        if (!undo.length) return;
        var data = undo.pop();
        var img = new Image();
        img.onload = function () {
          var rect = canvas.getBoundingClientRect();
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(img, 0, 0, rect.width, rect.height);
        };
        img.src = data;
      });
    }

    var clearBtn = document.getElementById('rw-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () { clearAll(true); });

    // ── Drawing ──────────────────────────────────────────────────────────
    canvas.addEventListener('pointerdown', function (e) {
      drawing = true;
      snapshot();
      var p = point(e);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
      e.preventDefault();
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!drawing) return;
      var p = point(e);
      if (erasing) {
        ctx.globalCompositeOperation = 'destination-out';
        ctx.lineWidth = 22;
      } else {
        ctx.globalCompositeOperation = 'source-over';
        ctx.strokeStyle = color;
        ctx.lineWidth = 3;
      }
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      e.preventDefault();
    });
    function endStroke() { drawing = false; }
    canvas.addEventListener('pointerup', endStroke);
    canvas.addEventListener('pointercancel', endStroke);
    canvas.addEventListener('pointerleave', endStroke);

    var resizeTimer;
    window.addEventListener('resize', function () {
      if (panel.classList.contains('hidden')) return;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(fit, 150);
    });

    // Public hook: quizzes that swap one question at a time call this on
    // advance for a clean slate per problem. Undo history is reset too.
    window.RoughWork = {
      clear: function () { clearAll(false); undo = []; },
      open: open,
      close: close,
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
