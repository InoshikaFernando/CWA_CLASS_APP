/**
 * StrokeOrder — resolves an authored stroke order (window.STROKE_ORDER_DATA,
 * from stroke_order_data.js) into an actual pixel path along a rendered
 * glyph's skeleton (CPP-393).
 *
 * Previously (CPP-310/311's guide animation) the path was *guessed*: the
 * glyph was skeletonised and walked in raster-scan order, which has nothing
 * to do with how any script is actually handwritten and was wrong for every
 * letter in every language. This module keeps the skeleton (so the traced
 * path still follows the real glyph shape) but takes stroke order and
 * direction entirely from authored data: each stroke is a short list of
 * normalised anchor points; each anchor is snapped to the nearest skeleton
 * pixel, and consecutive anchors within a stroke are joined by the shortest
 * path *along the skeleton* (BFS), falling back to a straight line only
 * when the skeleton is disconnected between them (e.g. a dotted "i").
 *
 * A character with no authored entry resolves to null — callers must show
 * the static glyph with no direction arrow, never a guessed path. This is
 * deliberate (see CPP-393): a plausible-but-wrong stroke order is worse
 * than no animation, and it's what keeps a newly added script (or an
 * unreviewed one — see stroke_order_data.js's header) honest.
 */
(function (global) {
  'use strict';

  // ---------------------------------------------------------------------
  // Zhang-Suen thinning — identical algorithm to the one whiteboard.js
  // used for the old guess-based animation; CPP-393 keeps it for shape
  // extraction, only the path *through* the skeleton is no longer guessed.
  // ---------------------------------------------------------------------
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

  // ---------------------------------------------------------------------
  // Threshold an already-rendered canvas (white bg, dark glyph ink) into
  // a skeleton. Shared by renderSkeleton() below (which renders the glyph
  // itself) and by resolve()'s opts.canvas path (which reuses a canvas
  // the caller already rendered — see resolve()'s doc comment for why).
  // ---------------------------------------------------------------------
  function skeletonFromCanvas(canvas, w, h) {
    var data = canvas.getContext('2d').getImageData(0, 0, w, h).data;
    var mask = new Uint8Array(w * h);
    var inkCount = 0;
    for (var i = 0; i < w * h; i++) {
      var lum = 0.299*data[i*4] + 0.587*data[i*4+1] + 0.114*data[i*4+2];
      if (lum < 128) { mask[i] = 1; inkCount++; }
    }
    if (inkCount < 8) return null; // glyph didn't render (font not ready / unmapped codepoint)
    return { skeleton: thin(mask, w, h), mask: mask, w: w, h: h };
  }

  // ---------------------------------------------------------------------
  // Render `char` to a fresh offscreen canvas and return its skeleton.
  // No SVG-shaping fallback of its own — callers that already have a
  // validated render (e.g. whiteboard.js's renderGhost(), which retries
  // via SVG when canvas fillText produces nothing for a complex-script
  // font) should pass that canvas to resolve() via opts.canvas instead of
  // going through this path, so the skeleton benefits from the same
  // fallback rather than silently failing where the ghost would recover.
  // ---------------------------------------------------------------------
  function renderSkeleton(char, fontSpec, w, h, baseX, baseY) {
    var off = document.createElement('canvas');
    off.width = w; off.height = h;
    var ctx = off.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);
    ctx.font          = fontSpec;
    ctx.textAlign     = 'center';
    ctx.textBaseline  = 'alphabetic';
    ctx.fillStyle     = '#000000';
    ctx.fillText(char, baseX, baseY);
    return skeletonFromCanvas(off, w, h);
  }

  function inkBBox(mask, w, h) {
    var minX = w, maxX = -1, minY = h, maxY = -1;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        if (!mask[y * w + x]) continue;
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
    }
    if (maxX < 0) return null;
    return { minX: minX, maxX: maxX, minY: minY, maxY: maxY };
  }

  // Nearest skeleton pixel to (x, y), searching outward ring by ring —
  // skeleton pixels are sparse (1px wide), so an expanding-radius search
  // is the simplest reliable way to "snap" an approximate anchor onto it.
  function nearestSkeletonPixel(skeleton, w, h, x, y) {
    var cx = Math.round(x), cy = Math.round(y);
    if (cx >= 0 && cx < w && cy >= 0 && cy < h && skeleton[cy * w + cx]) {
      return { x: cx, y: cy };
    }
    var maxR = Math.max(w, h);
    for (var r = 1; r <= maxR; r++) {
      for (var dy = -r; dy <= r; dy++) {
        var ny = cy + dy;
        if (ny < 0 || ny >= h) continue;
        var edge = (Math.abs(dy) === r);
        var dxStep = edge ? 1 : (2 * r);
        for (var dx = -r; dx <= r; dx += (dxStep || 1)) {
          if (!edge && dx !== -r && dx !== r) continue;
          var nx = cx + dx;
          if (nx < 0 || nx >= w) continue;
          if (skeleton[ny * w + nx]) return { x: nx, y: ny };
        }
      }
    }
    return null; // empty skeleton
  }

  // BFS shortest path along the 8-connected skeleton graph, start -> end
  // (both already-snapped skeleton pixels). Returns an array of {x,y}
  // points, or null if start/end aren't connected (e.g. a dotted "i",
  // or two separate loops) — caller falls back to a straight line.
  function bfsPath(skeleton, w, h, start, end) {
    if (start.x === end.x && start.y === end.y) return [start];
    var startIdx = start.y * w + start.x, endIdx = end.y * w + end.x;
    var visited = new Uint8Array(w * h);
    var prev = new Int32Array(w * h).fill(-1);
    visited[startIdx] = 1;
    var queue = [startIdx];
    var qi = 0;
    while (qi < queue.length) {
      var idx = queue[qi++];
      if (idx === endIdx) break;
      var px = idx % w, py = (idx / w) | 0;
      for (var dy = -1; dy <= 1; dy++) {
        for (var dx = -1; dx <= 1; dx++) {
          if (!dx && !dy) continue;
          var nx = px + dx, ny = py + dy;
          if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
          var nIdx = ny * w + nx;
          if (!skeleton[nIdx] || visited[nIdx]) continue;
          visited[nIdx] = 1;
          prev[nIdx] = idx;
          queue.push(nIdx);
        }
      }
    }
    if (!visited[endIdx]) return null; // disconnected

    var path = [];
    var cur = endIdx;
    while (cur !== -1) {
      path.push({ x: cur % w, y: (cur / w) | 0 });
      if (cur === startIdx) break;
      cur = prev[cur];
    }
    path.reverse();
    return path;
  }

  /**
   * Resolve authored stroke data for `char` into actual pixel paths.
   *
   * @param opts.strokes   window.STROKE_ORDER_DATA[script][char] — array of
   *                        strokes, each an array of [x,y] anchors normalised
   *                        0..1 against the glyph's own ink bounding box.
   * @param opts.w, opts.h  render size, in the same pixel space as opts.canvas
   *                        (when given) or the internal render (otherwise).
   * @param opts.canvas     optional: an already-rendered offscreen canvas
   *                        (white bg, dark glyph ink, size w x h) to thin
   *                        directly instead of rendering internally — lets a
   *                        caller that already validated its own render (with
   *                        whatever fallback it needed, e.g. an SVG retry for
   *                        a complex script) hand it over so this doesn't
   *                        redundantly re-render and risk failing where the
   *                        caller's render succeeded. When omitted, falls
   *                        back to rendering opts.char internally.
   * @param opts.char       the character to render (opts.canvas omitted only).
   * @param opts.fontSpec   canvas font shorthand, e.g. "bold 90px 'Noto Sans'".
   * @param opts.baseX, opts.baseY  canvas fillText anchor point.
   *
   * @returns { strokes: [[{x,y}, ...], ...], skeleton, w, h } in the same
   *          pixel space as (w, h) — or null if the glyph didn't render or
   *          has no authored strokes.
   */
  function resolve(opts) {
    if (!opts.strokes || !opts.strokes.length) return null;

    var rendered = opts.canvas
      ? skeletonFromCanvas(opts.canvas, opts.w, opts.h)
      : renderSkeleton(opts.char, opts.fontSpec, opts.w, opts.h, opts.baseX, opts.baseY);
    if (!rendered) return null;
    var skeleton = rendered.skeleton, w = rendered.w, h = rendered.h;

    var bbox = inkBBox(rendered.mask, w, h);
    if (!bbox) return null;
    var bw = Math.max(1, bbox.maxX - bbox.minX);
    var bh = Math.max(1, bbox.maxY - bbox.minY);

    function toPixel(anchor) {
      return {
        x: bbox.minX + anchor[0] * bw,
        y: bbox.minY + anchor[1] * bh,
      };
    }

    var resolvedStrokes = [];
    for (var s = 0; s < opts.strokes.length; s++) {
      var anchors = opts.strokes[s];
      if (!anchors.length) continue;

      var snapped = anchors.map(function (a) {
        var p = toPixel(a);
        return nearestSkeletonPixel(skeleton, w, h, p.x, p.y) || { x: Math.round(p.x), y: Math.round(p.y) };
      });

      if (snapped.length === 1) {
        resolvedStrokes.push([snapped[0]]); // single-anchor stroke = a dot
        continue;
      }

      var strokePath = [snapped[0]];
      for (var i = 1; i < snapped.length; i++) {
        var seg = bfsPath(skeleton, w, h, snapped[i - 1], snapped[i]);
        if (!seg) {
          // Disconnected (dotted "i", detached parts) — straight join.
          strokePath.push(snapped[i]);
        } else {
          strokePath = strokePath.concat(seg.slice(1));
        }
      }
      resolvedStrokes.push(strokePath);
    }

    if (!resolvedStrokes.length) return null;
    return { strokes: resolvedStrokes, skeleton: skeleton, mask: rendered.mask, w: w, h: h, bbox: bbox };
  }

  /**
   * Testing helper: does every skeleton pixel lie within `tolerance` of
   * some point on some resolved stroke? Used by the UI test suite to catch
   * authored data that leaves part of a letter undrawn.
   */
  function coverageRatio(resolved, tolerance) {
    if (!resolved) return 0;
    var w = resolved.w, h = resolved.h;
    var covered = new Uint8Array(w * h);
    resolved.strokes.forEach(function (path) {
      path.forEach(function (p) {
        for (var dy = -tolerance; dy <= tolerance; dy++) {
          for (var dx = -tolerance; dx <= tolerance; dx++) {
            var nx = p.x + dx, ny = p.y + dy;
            if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
            if (dx*dx + dy*dy > tolerance*tolerance) continue;
            covered[ny * w + nx] = 1;
          }
        }
      });
    });
    var total = 0, hit = 0;
    for (var i = 0; i < w * h; i++) {
      if (!resolved.skeleton[i]) continue;
      total++;
      if (covered[i]) hit++;
    }
    return total === 0 ? 1 : hit / total;
  }

  global.StrokeOrder = {
    resolve: resolve,
    coverageRatio: coverageRatio,
    _internal: { thin: thin, renderSkeleton: renderSkeleton, skeletonFromCanvas: skeletonFromCanvas,
                 inkBBox: inkBBox, nearestSkeletonPixel: nearestSkeletonPixel, bfsPath: bfsPath },
  };
})(window);
