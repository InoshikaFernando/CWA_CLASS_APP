/*
 * sketch_graph.js — "sketch the graph and state its key features" tool.
 *
 * Dependency-free. Mounts on every `[data-sk-stage]` and collects BOTH halves
 * of the answer into the stage's hidden input:
 *
 *   {"features":{"vertex":"(-0.5,-2.25)"},"points":[[-2,0],[0,-2],[1,0]]}
 *
 * `features` are the typed boxes (`[data-sk-feature]`, each carrying its kind
 * in data-kind). `points` is the SKETCH: the student taps lattice points on the
 * plane (`[data-sk-dot]`, signed plane coords in data-gx/data-gy) and they are
 * joined left-to-right into a smooth curve, so the verb the question actually
 * uses has something to do. The plane only carries dots when the server found a
 * curve to mark a drawing against; without them this is the typed-boxes widget
 * it has always been.
 *
 * Idempotent (a `data-sk-mounted` flag guards re-mounts); mounting — on load and
 * again after the topic quiz and worksheet session swap questions in with
 * innerHTML (inline scripts would not run) — is handled by the shared registry
 * in maths_mounts.js. Each stage is scoped to its own element, so any number of
 * sketch questions can share a page. Reads the hidden input's current value on
 * mount, so a restored/resumed draft re-fills and re-plots correctly.
 */
(function () {
  "use strict";

  // Beyond this a "sketch" is a scribble. Matches MAX_DRAWN_POINTS server-side,
  // which drops the overflow — so the widget must not let them be plotted and
  // then silently ignored.
  var MAX_POINTS = 40;

  // Smooth (Catmull-Rom → cubic Bézier) path through pixel points, pre-sorted by
  // x. Same curve the plot_points widget draws through its plotted points, so a
  // sketch looks the same wherever a student meets one.
  function smoothPath(p) {
    if (p.length < 2) return "";
    if (p.length === 2) return "M" + p[0][0] + "," + p[0][1] + " L" + p[1][0] + "," + p[1][1];
    var d = "M" + p[0][0] + "," + p[0][1];
    for (var i = 0; i < p.length - 1; i++) {
      var p0 = p[i - 1] || p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] || p2;
      var c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      var c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += " C" + c1x + "," + c1y + " " + c2x + "," + c2y + " " + p2[0] + "," + p2[1];
    }
    return d;
  }

  function mount(stage) {
    if (!stage || stage.dataset.skMounted === "1") return;
    var hidden = stage.querySelector("[data-sk-hidden]");
    var boxes = stage.querySelectorAll("[data-sk-feature]");
    var dots = stage.querySelectorAll("[data-sk-dot]");
    if (!hidden || (!boxes.length && !dots.length)) return;
    stage.dataset.skMounted = "1";

    var SVGNS = "http://www.w3.org/2000/svg";
    var marks = stage.querySelector("[data-sk-marks]");
    var curve = stage.querySelector("[data-sk-curve]");
    var readout = stage.querySelector("[data-sk-readout]");
    var pad = Number(stage.dataset.skPad || 0);
    var step = Number(stage.dataset.skStep || 0);
    var xmin = Number(stage.dataset.skXmin || 0);
    var ymax = Number(stage.dataset.skYmax || 0);
    var pts = [];   // plotted points, in tap order: [[x, y], ...]

    function px(x) { return pad + (x - xmin) * step; }
    function py(y) { return pad + (ymax - y) * step; }
    function fmt(p) { return "(" + p[0] + ", " + p[1] + ")"; }
    function indexOf(x, y) {
      for (var i = 0; i < pts.length; i++) {
        if (pts[i][0] === x && pts[i][1] === y) return i;
      }
      return -1;
    }

    function refresh() {
      var out = {};
      boxes.forEach(function (el) {
        var v = (el.value || "").trim();
        if (v !== "") out[el.dataset.kind] = v;
      });
      hidden.value = JSON.stringify({ features: out, points: pts });
    }

    function draw() {
      if (!marks) return;
      while (marks.firstChild) marks.removeChild(marks.firstChild);
      pts.forEach(function (p) {
        var c = document.createElementNS(SVGNS, "circle");
        c.setAttribute("cx", px(p[0]));
        c.setAttribute("cy", py(p[1]));
        c.setAttribute("r", "5");
        c.setAttribute("fill", "#dc2626");
        marks.appendChild(c);
      });
      if (curve) {
        var pix = pts.slice()
          .sort(function (a, b) { return a[0] - b[0]; })
          .map(function (p) { return [px(p[0]), py(p[1])]; });
        curve.setAttribute("d", smoothPath(pix));
      }
      if (readout) {
        readout.textContent = pts.length
          ? pts.slice().sort(function (a, b) { return a[0] - b[0]; }).map(fmt).join(", ")
          : "—";
      }
    }

    function toggle(g) {
      var x = parseInt(g.dataset.gx, 10), y = parseInt(g.dataset.gy, 10);
      var at = indexOf(x, y);
      if (at !== -1) {
        pts.splice(at, 1);
      } else if (pts.length < MAX_POINTS) {
        pts.push([x, y]);
      }
      draw();
      refresh();
    }

    boxes.forEach(function (el) {
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
      el.addEventListener("blur", refresh);
    });
    dots.forEach(function (g) {
      g.addEventListener("click", function () { toggle(g); });
      g.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(g); }
      });
    });
    var undo = stage.querySelector("[data-sk-undo]");
    if (undo) undo.addEventListener("click", function () { pts.pop(); draw(); refresh(); });
    var clear = stage.querySelector("[data-sk-clear]");
    if (clear) clear.addEventListener("click", function () { pts = []; draw(); refresh(); });

    var form = stage.closest("form");
    if (form) form.addEventListener("submit", refresh, true);

    // Rehydrate from a saved/resumed value, then keep the hidden field in sync.
    try {
      var saved = JSON.parse(hidden.value || "{}");
      if (saved && saved.features) {
        boxes.forEach(function (el) {
          if (saved.features[el.dataset.kind] != null) {
            el.value = saved.features[el.dataset.kind];
          }
        });
      }
      if (saved && Array.isArray(saved.points)) {
        saved.points.forEach(function (p) {
          if (Array.isArray(p) && p.length === 2 && indexOf(p[0], p[1]) === -1
              && pts.length < MAX_POINTS) {
            pts.push([Number(p[0]), Number(p[1])]);
          }
        });
      }
    } catch (e) { /* malformed saved value — start blank */ }
    draw();
    refresh();
  }

  var SELECTOR = "[data-sk-stage]";

  if (!window.MathsMounts) {
    // Loud, not silent: without the registry the widget simply would not mount
    // and the student would face an inert question.
    console.error("sketch_graph.js: maths_mounts.js must load first.");
    return;
  }
  window.MathsMounts.register(SELECTOR, mount);
})();
