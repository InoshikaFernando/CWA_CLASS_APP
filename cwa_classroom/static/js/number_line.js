/*
 * number_line.js — interactive "mark a value on the number line" tool.
 *
 * Dependency-free. Mounts on every `[data-nl-stage]` whose mode is "mark":
 * tapping a tick toggles a marker; the marked values serialise to JSON in the
 * stage's hidden input as {"marks":[...]} on the line's own scale. Read-mode
 * number lines are answered with a plain text box and need no JS.
 *
 * Idempotent (a `data-nl-mounted` flag guards re-mounts); mounting — on load
 * and again after the topic quiz swaps a question in with innerHTML — is
 * handled by the shared registry in maths_mounts.js. Each stage is scoped to
 * its own element, so any number of number-line questions can share a page. Reads the hidden input's
 * current value on mount, so a restored/resumed draft re-renders correctly.
 */
(function () {
  "use strict";
  var SVGNS = "http://www.w3.org/2000/svg";
  var MARK = "#059669"; // emerald

  function numKey(v) {
    var f = parseFloat(v);
    return Number.isInteger(f) ? f : Math.round(f * 1e6) / 1e6;
  }

  function mount(stage) {
    if (!stage || stage.dataset.nlMounted === "1") return;
    if ((stage.dataset.nlMode || "mark") !== "mark") { stage.dataset.nlMounted = "1"; return; }
    var svg = stage.querySelector("[data-nl-wrap]");
    var hidden = stage.querySelector("[data-nl-hidden]");
    var marksG = stage.querySelector("[data-nl-marks]");
    var readout = stage.querySelector("[data-nl-readout]");
    var clearBtn = stage.querySelector("[data-nl-clear]");
    if (!svg || !hidden || !marksG) return;
    stage.dataset.nlMounted = "1";

    var marks = []; // list of {value, px, py}

    function sync() {
      var next = JSON.stringify({ marks: marks.map(function (m) { return m.value; }) });
      // Tell the page an answer happened. This widget is driven by taps on
      // the SVG, so nothing else does: the hidden field is written in script
      // and setting `.value` fires no event, which left the homework take
      // page's debounced autosave (and the progress-art panel) unaware that
      // the student had answered at all. Guarded on an actual change so a
      // no-op sync -- on submit, or when a resumed draft rebuilds the same
      // working -- stays silent.
      if (hidden.value !== next) {
        hidden.value = next;
        hidden.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (readout) {
        readout.textContent = marks.length
          ? marks.map(function (m) { return m.value; }).join(", ")
          : "—";
      }
    }
    function render() {
      while (marksG.firstChild) marksG.removeChild(marksG.firstChild);
      marks.forEach(function (m) {
        var c = document.createElementNS(SVGNS, "circle");
        c.setAttribute("cx", m.px);
        c.setAttribute("cy", m.py);
        c.setAttribute("r", "6");
        c.setAttribute("fill", MARK);
        marksG.appendChild(c);
      });
    }
    function toggle(dot) {
      var value = numKey(dot.getAttribute("data-value"));
      var px = parseFloat(dot.getAttribute("data-px"));
      var py = parseFloat(dot.getAttribute("data-py"));
      var idx = -1;
      for (var i = 0; i < marks.length; i++) {
        if (marks[i].value === value) { idx = i; break; }
      }
      if (idx !== -1) marks.splice(idx, 1);
      else marks.push({ value: value, px: px, py: py });
      render();
      sync();
    }

    svg.querySelectorAll("[data-nl-dot]").forEach(function (dot) {
      dot.addEventListener("click", function () { toggle(dot); });
      dot.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(dot); }
      });
    });
    if (clearBtn) {
      clearBtn.addEventListener("click", function () { marks = []; render(); sync(); });
    }
    var form = stage.closest("form");
    if (form) form.addEventListener("submit", sync, true);

    // Rehydrate from a saved/resumed value, then keep the hidden field in sync.
    try {
      var saved = JSON.parse(hidden.value || "{}");
      if (saved && Array.isArray(saved.marks) && saved.marks.length) {
        saved.marks.forEach(function (v) {
          var key = numKey(v);
          var dot = svg.querySelector('[data-nl-dot][data-value="' + v + '"]');
          if (dot) {
            marks.push({
              value: key,
              px: parseFloat(dot.getAttribute("data-px")),
              py: parseFloat(dot.getAttribute("data-py")),
            });
          }
        });
        render();
      }
    } catch (e) { /* malformed saved value — start blank */ }
    sync();
  }

  var SELECTOR = "[data-nl-stage]";

  if (!window.MathsMounts) {
    // Loud, not silent: without the registry the widget simply would not mount
    // and the student would face an inert question.
    console.error("number_line.js: maths_mounts.js must load first.");
    return;
  }
  window.MathsMounts.register(SELECTOR, mount);
})();
