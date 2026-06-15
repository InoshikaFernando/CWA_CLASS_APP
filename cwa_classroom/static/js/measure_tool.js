/*
 * measure_tool.js — interactive protractor / ruler overlay for `measure`
 * question types (CPP). Dependency-free (no jQuery / Alpine).
 *
 * A measure question renders a true-scale figure (an angle SVG for degrees, or
 * an author image for length). This script lays a draggable + rotatable
 * instrument over that figure so the student can MEASURE it, then type the
 * reading into the existing numeric input. The instrument is a visual aid only —
 * it never submits anything; grading is unchanged server-side.
 *
 * Markup contract (see templates/maths/partials/_measure_tool.html):
 *   <div class="measure-stage" data-measure-tool="protractor|ruler"> … figure …
 *     <button data-measure-reset>…</button>
 *   </div>
 *
 * Init is idempotent (a data-measure-mounted flag) and runs on DOMContentLoaded
 * AND via a MutationObserver, because the topic quiz swaps the next question in
 * with innerHTML (which does not execute injected <script> tags).
 */
(function () {
  'use strict';

  var SVGNS = 'http://www.w3.org/2000/svg';
  var DEG = 180 / Math.PI;

  // ── Instrument SVG builders ───────────────────────────────────────────────
  // Each returns { html, refX, refY, w, h } where (refX, refY) is the pivot the
  // instrument rotates about (protractor centre / ruler zero), in svg units.

  function protractorSvg() {
    var R = 132, pad = 16;
    var cx = R + pad, cy = R + pad;          // centre, on the baseline
    var w = 2 * (R + pad), h = R + pad + 26;
    var parts = [];
    // Translucent semicircle body (grabbable — has a fill).
    parts.push(
      '<path d="M ' + (cx - R) + ' ' + cy + ' A ' + R + ' ' + R + ' 0 0 1 ' +
      (cx + R) + ' ' + cy + ' Z" fill="#3b82f6" fill-opacity="0.12" ' +
      'stroke="#2563eb" stroke-width="1.5"/>'
    );
    // Degree ticks 0..180 (0 at right, 180 at left — matches the angle figure).
    for (var d = 0; d <= 180; d++) {
      var a = d / DEG;
      var len = (d % 10 === 0) ? 16 : (d % 5 === 0) ? 10 : 6;
      var ox = cx + R * Math.cos(a), oy = cy - R * Math.sin(a);
      var ix = cx + (R - len) * Math.cos(a), iy = cy - (R - len) * Math.sin(a);
      parts.push(
        '<line x1="' + f(ox) + '" y1="' + f(oy) + '" x2="' + f(ix) + '" y2="' +
        f(iy) + '" stroke="#1e3a8a" stroke-width="' + (d % 10 === 0 ? 1.4 : 0.8) +
        '"/>'
      );
      if (d % 10 === 0) {
        var lx = cx + (R - 28) * Math.cos(a), ly = cy - (R - 28) * Math.sin(a);
        parts.push(label(lx, ly, d, 11));            // outer scale 0→180
        var ix2 = cx + (R - 44) * Math.cos(a), iy2 = cy - (R - 44) * Math.sin(a);
        parts.push(label(ix2, iy2, 180 - d, 9, '#64748b'));  // inner scale 180→0
      }
    }
    // Baseline, centre mark, and the rotate knob at the 0° (right) end.
    parts.push('<line x1="' + (cx - R) + '" y1="' + cy + '" x2="' + (cx + R) +
      '" y2="' + cy + '" stroke="#2563eb" stroke-width="1.5"/>');
    parts.push('<circle cx="' + cx + '" cy="' + cy + '" r="3" fill="#2563eb"/>');
    parts.push('<line x1="' + cx + '" y1="' + cy + '" x2="' + cx + '" y2="' +
      (cy - R) + '" stroke="#2563eb" stroke-width="0.8" stroke-dasharray="3 3"/>');
    parts.push(knob(cx + R, cy));
    return { html: svg(w, h, parts), refX: cx, refY: cy };
  }

  function rulerSvg() {
    var L = 384, H = 46, pad = 14;
    var x0 = pad, yTop = pad;                 // zero mark, on the measuring edge
    var w = L + 2 * pad, h = H + 2 * pad;
    var cm = 16, pxCm = L / cm;
    var parts = [];
    parts.push('<rect x="' + x0 + '" y="' + yTop + '" width="' + L + '" height="' +
      H + '" rx="4" fill="#f59e0b" fill-opacity="0.12" stroke="#b45309" ' +
      'stroke-width="1.5"/>');
    // mm ticks down from the top (measuring) edge.
    var mmCount = cm * 10, pxMm = pxCm / 10;
    for (var m = 0; m <= mmCount; m++) {
      var x = x0 + m * pxMm;
      var len = (m % 10 === 0) ? 14 : (m % 5 === 0) ? 9 : 5;
      parts.push('<line x1="' + f(x) + '" y1="' + yTop + '" x2="' + f(x) +
        '" y2="' + f(yTop + len) + '" stroke="#7c2d12" stroke-width="' +
        (m % 10 === 0 ? 1.2 : 0.7) + '"/>');
      if (m % 10 === 0) parts.push(label(x, yTop + 26, m / 10, 10, '#7c2d12'));
    }
    parts.push(knob(x0 + L, yTop));           // rotate knob at the far end
    return { html: svg(w, h, parts), refX: x0, refY: yTop };
  }

  function svg(w, h, parts) {
    return '<svg xmlns="' + SVGNS + '" width="' + w + '" height="' + h +
      '" viewBox="0 0 ' + w + ' ' + h + '" style="pointer-events:none;overflow:visible">' +
      '<g data-measure-body style="pointer-events:auto;cursor:grab">' +
      parts.join('') + '</g></svg>';
  }
  function knob(x, y) {
    return '<circle data-role="rotate" cx="' + x + '" cy="' + y + '" r="9" ' +
      'fill="#fff" stroke="#2563eb" stroke-width="2" ' +
      'style="pointer-events:auto;cursor:alias"/>' +
      '<circle cx="' + x + '" cy="' + y + '" r="2.5" fill="#2563eb" style="pointer-events:none"/>';
  }
  function label(x, y, t, size, fill) {
    return '<text x="' + f(x) + '" y="' + f(y) + '" font-size="' + size +
      '" fill="' + (fill || '#1e3a8a') + '" text-anchor="middle" ' +
      'dominant-baseline="middle" style="pointer-events:none;user-select:none">' +
      t + '</text>';
  }
  function f(n) { return Math.round(n * 100) / 100; }

  // ── Mounting + interaction ────────────────────────────────────────────────

  function mount(stage) {
    if (stage.dataset.measureMounted) return;
    stage.dataset.measureMounted = '1';
    var kind = stage.getAttribute('data-measure-tool');
    var build = kind === 'ruler' ? rulerSvg() : protractorSvg();

    // Anchor div is a zero-size point at the pivot; the svg hangs off it offset
    // so the instrument's reference point sits exactly on the anchor, and a CSS
    // rotate about (0,0) pivots around that reference point.
    var anchor = document.createElement('div');
    anchor.className = 'measure-instrument';
    anchor.style.cssText = 'position:absolute;width:0;height:0;transform-origin:0 0;touch-action:none;z-index:5';
    anchor.innerHTML = build.html;
    var svgEl = anchor.firstChild;
    svgEl.style.position = 'absolute';
    svgEl.style.left = (-build.refX) + 'px';
    svgEl.style.top = (-build.refY) + 'px';
    stage.appendChild(anchor);

    var state = { x: 0, y: 0, rot: 0 };
    function reset() {
      var r = stage.getBoundingClientRect();
      if (kind === 'ruler') { state.x = r.width * 0.18; state.y = r.height * 0.5; }
      else { state.x = r.width * 0.5; state.y = r.height * 0.7; }
      state.rot = 0;
      apply();
    }
    function apply() {
      anchor.style.left = state.x + 'px';
      anchor.style.top = state.y + 'px';
      anchor.style.transform = 'rotate(' + state.rot + 'deg)';
    }

    var mode = null, sx = 0, sy = 0, ox = 0, oy = 0;
    var rot0 = 0, ang0 = 0, pivotX = 0, pivotY = 0;
    function onDown(e) {
      var rotating = e.target.closest('[data-role="rotate"]');
      mode = rotating ? 'rotate' : 'drag';
      sx = e.clientX; sy = e.clientY; ox = state.x; oy = state.y;
      if (mode === 'rotate') {
        // Pivot is fixed for the whole gesture — read it once (avoids a
        // forced layout on every pointermove). Capture the start angle and
        // rotation so we rotate by the DELTA, not snap to the raw bearing.
        var r = stage.getBoundingClientRect();
        pivotX = r.left + state.x; pivotY = r.top + state.y;
        rot0 = state.rot;
        ang0 = Math.atan2(e.clientY - pivotY, e.clientX - pivotX) * DEG;
      }
      try { anchor.setPointerCapture(e.pointerId); } catch (_) { /* stale id */ }
      e.preventDefault();
    }
    function onMove(e) {
      if (!mode) return;
      if (mode === 'drag') {
        state.x = ox + (e.clientX - sx);
        state.y = oy + (e.clientY - sy);
      } else {
        var ang = Math.atan2(e.clientY - pivotY, e.clientX - pivotX) * DEG;
        state.rot = rot0 + (ang - ang0);
      }
      apply();
    }
    function onUp() { mode = null; }

    anchor.addEventListener('pointerdown', onDown);
    anchor.addEventListener('pointermove', onMove);
    anchor.addEventListener('pointerup', onUp);
    anchor.addEventListener('pointercancel', onUp);

    var resetBtn = stage.querySelector('[data-measure-reset]');
    if (resetBtn) resetBtn.addEventListener('click', reset);

    reset();
  }

  function init(root) {
    (root || document).querySelectorAll('.measure-stage[data-measure-tool]')
      .forEach(mount);
  }

  // Mount existing stages now, and any inserted later (quiz innerHTML swaps).
  function boot() {
    init(document);
    // Only the topic quiz swaps questions in via innerHTML; it does so inside
    // #question-container. Homework renders every question up-front, so it
    // needs no observer. Scoping to that node (when present) keeps us off the
    // page-wide mutation firehose (timer ticks, feedback panels, …).
    var root = document.getElementById('question-container');
    if (!root) return;
    new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var added = muts[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var n = added[j];
          if (n.nodeType !== 1) continue;
          if (n.matches && n.matches('.measure-stage[data-measure-tool]')) mount(n);
          else if (n.querySelectorAll) init(n);
        }
      }
    }).observe(root, { childList: true, subtree: true });
  }

  window.CwaMeasureTool = { init: init };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
