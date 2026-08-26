/**
 * stroke_order.js — turns a rendered glyph into an ordered, correctly directed
 * sequence of handwriting strokes.
 *
 * Why this exists
 * ---------------
 * The first version of the "watch how it's written" animation skeletonised the
 * glyph and then walked the skeleton with a depth-first search that started at
 * the topmost pixel and followed whichever neighbour happened to come first in
 * raster order.  That produces a path, but the path has nothing to do with how
 * the letter is actually written: "A" came out as one continuous scribble
 * instead of ⟋ then ⟍ then the crossbar, and Sinhala letters — which are drawn
 * as a handful of anticlockwise loops in a fixed order — came out as nonsense.
 *
 * So the order is no longer guessed.  `stroke_order_data.js` stores, for every
 * character the app teaches, the real stroke order as a list of strokes, each
 * one a short list of anchor points in glyph-box coordinates.  This module
 * snaps those anchors onto the skeleton of the *actual rendered glyph* and
 * walks the skeleton between them, so the animation traces the true letterform
 * while following the authored order and direction.
 *
 * Anchor coordinate space
 * -----------------------
 * Anchors are [x, y] with 0..1 spanning the glyph's ink bounding box, y down.
 * [0, 0] is the top-left of the inked area, [1, 1] the bottom-right.  Using the
 * ink box rather than the canvas keeps the data font-size independent and lets
 * the same anchors work for a tall "b" and a short "a".
 *
 * Usage:
 *   var skel    = StrokeOrder.thin(mask, w, h);
 *   var strokes = StrokeOrder.build(skel, w, h, StrokeOrder.lookup('A'));
 *   // strokes = [[{x,y}, ...], [{x,y}, ...], ...] in writing order
 */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------------------
  // Zhang-Suen iterative thinning — reduces the filled glyph to a 1px skeleton
  // ---------------------------------------------------------------------------
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
            var p2 = px[(y - 1) * w + x],     p3 = px[(y - 1) * w + x + 1];
            var p4 = px[ y      * w + x + 1], p5 = px[(y + 1) * w + x + 1];
            var p6 = px[(y + 1) * w + x],     p7 = px[(y + 1) * w + x - 1];
            var p8 = px[ y      * w + x - 1], p9 = px[(y - 1) * w + x - 1];
            var B  = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9;
            if (B < 2 || B > 6) continue;
            var A = (!p2 && p3 ? 1 : 0) + (!p3 && p4 ? 1 : 0) + (!p4 && p5 ? 1 : 0) +
                    (!p5 && p6 ? 1 : 0) + (!p6 && p7 ? 1 : 0) + (!p7 && p8 ? 1 : 0) +
                    (!p8 && p9 ? 1 : 0) + (!p9 && p2 ? 1 : 0);
            if (A !== 1) continue;
            if (pass === 0 && (p2 * p4 * p6 || p4 * p6 * p8)) continue;
            if (pass === 1 && (p2 * p4 * p8 || p2 * p6 * p8)) continue;
            rem.push(y * w + x);
          }
        }
        rem.forEach(function (i) { px[i] = 0; changed = true; });
      }
    }
    return px;
  }

  // ---------------------------------------------------------------------------
  // Skeleton geometry helpers
  // ---------------------------------------------------------------------------

  /** Ink bounding box of a mask/skeleton, or null when nothing is set. */
  function inkBox(mask, w, h) {
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        if (!mask[y * w + x]) continue;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
    if (minX === Infinity) return null;
    return { minX: minX, minY: minY, maxX: maxX, maxY: maxY };
  }

  /**
   * Nearest skeleton pixel to (px, py), searched in growing square rings so the
   * first hit is (near enough) the closest one.  Anchors only have to land in
   * the right neighbourhood; this pins them to real ink.
   */
  function nearestInk(skel, w, h, px, py) {
    var cx = Math.round(px), cy = Math.round(py);
    if (cx >= 0 && cy >= 0 && cx < w && cy < h && skel[cy * w + cx]) return cy * w + cx;
    var maxR = Math.max(w, h);
    for (var r = 1; r < maxR; r++) {
      var best = -1, bestD = Infinity;
      for (var dy = -r; dy <= r; dy++) {
        for (var dx = -r; dx <= r; dx++) {
          // ring only — interior was covered by smaller r
          if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue;
          var x = cx + dx, y = cy + dy;
          if (x < 0 || y < 0 || x >= w || y >= h) continue;
          if (!skel[y * w + x]) continue;
          var d = dx * dx + dy * dy;
          if (d < bestD) { bestD = d; best = y * w + x; }
        }
      }
      if (best >= 0) return best;
    }
    return -1;
  }

  /**
   * Shortest path between two skeleton pixels, walking 8-connected skeleton ink
   * only.  Returns an array of {x, y} inclusive of both ends, or null when the
   * two pixels sit in different connected components (a dotted "i", a Sinhala
   * letter whose parts do not touch).
   */
  function walk(skel, w, h, fromIdx, toIdx) {
    if (fromIdx < 0 || toIdx < 0) return null;
    if (fromIdx === toIdx) return [{ x: fromIdx % w, y: Math.floor(fromIdx / w) }];

    var prev = new Int32Array(w * h).fill(-1);
    var seen = new Uint8Array(w * h);
    var queue = [fromIdx];
    seen[fromIdx] = 1;

    for (var qi = 0; qi < queue.length; qi++) {
      var cur = queue[qi];
      if (cur === toIdx) break;
      var cx = cur % w, cy = (cur - cx) / w;
      for (var dy = -1; dy <= 1; dy++) {
        for (var dx = -1; dx <= 1; dx++) {
          if (!dx && !dy) continue;
          var nx = cx + dx, ny = cy + dy;
          if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
          var ni = ny * w + nx;
          if (seen[ni] || !skel[ni]) continue;
          seen[ni] = 1;
          prev[ni] = cur;
          queue.push(ni);
        }
      }
    }
    if (!seen[toIdx]) return null;

    var out = [];
    for (var p = toIdx; p !== -1; p = prev[p]) {
      out.push({ x: p % w, y: Math.floor(p / w) });
      if (p === fromIdx) break;
    }
    return out.reverse();
  }

  /** Straight line between two points — used when the skeleton has a gap. */
  function segment(a, b) {
    var steps = Math.max(1, Math.round(Math.hypot(b.x - a.x, b.y - a.y)));
    var out = [];
    for (var i = 0; i <= steps; i++) {
      out.push({ x: a.x + (b.x - a.x) * i / steps, y: a.y + (b.y - a.y) * i / steps });
    }
    return out;
  }

  // ---------------------------------------------------------------------------
  // Build ordered strokes from authored anchors
  // ---------------------------------------------------------------------------

  /**
   * @param skel  Uint8Array skeleton, 1 = ink
   * @param w,h   skeleton dimensions
   * @param spec  array of strokes, each an array of [x, y] anchors in 0..1 ink-box space
   * @returns array of strokes, each an array of {x, y} pixel points, in writing order
   */
  function build(skel, w, h, spec) {
    if (!spec || !spec.length) return [];
    var box = inkBox(skel, w, h);
    if (!box) return [];

    var bw = Math.max(1, box.maxX - box.minX);
    var bh = Math.max(1, box.maxY - box.minY);

    function toPixel(anchor) {
      return {
        x: box.minX + anchor[0] * bw,
        y: box.minY + anchor[1] * bh,
      };
    }

    var strokes = [];
    for (var s = 0; s < spec.length; s++) {
      var anchors = spec[s];
      if (!anchors || !anchors.length) continue;

      var snapped = anchors.map(function (a) {
        var p = toPixel(a);
        var idx = nearestInk(skel, w, h, p.x, p.y);
        return idx >= 0 ? idx : null;
      });

      // A single-anchor stroke is a dot (the tittle on "i", a Tamil pulli).
      if (snapped.length === 1) {
        if (snapped[0] === null) continue;
        strokes.push([{ x: snapped[0] % w, y: Math.floor(snapped[0] / w) }]);
        continue;
      }

      var path = [];
      for (var i = 0; i < snapped.length - 1; i++) {
        var a = snapped[i], b = snapped[i + 1];
        var leg = (a !== null && b !== null) ? walk(skel, w, h, a, b) : null;
        if (!leg) {
          // Skeleton gap (or an anchor that found no ink at all): join the two
          // authored positions directly rather than dropping the stroke.
          var pa = a !== null ? { x: a % w, y: Math.floor(a / w) } : toPixel(anchors[i]);
          var pb = b !== null ? { x: b % w, y: Math.floor(b / w) } : toPixel(anchors[i + 1]);
          leg = segment(pa, pb);
        }
        // Drop the duplicated joint between consecutive legs
        if (path.length) leg = leg.slice(1);
        path = path.concat(leg);
      }
      if (path.length) strokes.push(path);
    }
    return strokes;
  }

  /**
   * Share of skeleton ink that ends up within `tol` pixels of some stroke.
   * A low number means the authored anchors miss part of the letter — used by
   * the stroke-order tests to catch a forgotten stroke.
   */
  function coverage(skel, w, h, strokes, tol) {
    tol = tol || 4;
    var total = 0, hit = 0;
    var covered = new Uint8Array(w * h);
    strokes.forEach(function (path) {
      path.forEach(function (p) {
        var cx = Math.round(p.x), cy = Math.round(p.y);
        for (var dy = -tol; dy <= tol; dy++) {
          for (var dx = -tol; dx <= tol; dx++) {
            if (dx * dx + dy * dy > tol * tol) continue;
            var x = cx + dx, y = cy + dy;
            if (x < 0 || y < 0 || x >= w || y >= h) continue;
            covered[y * w + x] = 1;
          }
        }
      });
    });
    for (var i = 0; i < w * h; i++) {
      if (!skel[i]) continue;
      total++;
      if (covered[i]) hit++;
    }
    return total ? hit / total : 0;
  }

  // ---------------------------------------------------------------------------
  // Data lookup
  // ---------------------------------------------------------------------------

  /** Authored stroke order for `ch`, or null when the character has none. */
  function lookup(ch) {
    var table = root.LETTER_STROKE_ORDER;
    if (!table) return null;
    return Object.prototype.hasOwnProperty.call(table, ch) ? table[ch] : null;
  }

  root.StrokeOrder = {
    thin: thin,
    inkBox: inkBox,
    nearestInk: nearestInk,
    walk: walk,
    build: build,
    coverage: coverage,
    lookup: lookup,
  };
})(typeof window !== 'undefined' ? window : globalThis);
