/*
 * pattern_fields.js — "create your own number pattern" boxes.
 *
 * Dependency-free. Mounts on every `[data-pat-stage]`: one `[data-pat-number]`
 * box per number the question asks for, plus one `[data-pat-rule]` box, and
 * composes them into the stage's hidden input as the single line a student
 * would have typed — "20, 18, 16, 14, 12, 10 — rule: subtract 2". That line is
 * what maths.pattern_grading.grade_pattern has always read, so the widget is
 * an input aid and nothing more: no new payload format, no server-side pairing
 * of boxes to values, and a surface that still shows a plain text box keeps
 * working unchanged.
 *
 * The composition MUST match maths.pattern_grading.compose_answer() — empty
 * boxes dropped, ", " between the numbers, " — rule: " before the rule, and a
 * leading "rule:" the student typed themselves stripped so it is not doubled.
 * test_pattern_fields.py pins the Python half; ui_tests/quiz pins that what
 * reaches the server matches.
 *
 * Idempotent (a `data-pat-mounted` flag guards re-mounts); mounting — on load
 * and again after the topic quiz swaps a question in with innerHTML (inline
 * scripts would not run) — is handled by the shared registry in
 * maths_mounts.js. Each stage is scoped to its own element. Reads the hidden
 * input's current value on mount, so a restored draft is not lost.
 */
(function () {
  "use strict";

  // Mirrors _LEADING_RULE_RE in maths/pattern_grading.py.
  var LEADING_RULE = /^\s*(?:the\s+)?rule\s*(?:is)?\s*[:=-]?\s*/i;
  var RULE_JOINER = " — rule: ";

  function mount(stage) {
    if (!stage || stage.dataset.patMounted === "1") return;
    var hidden = stage.querySelector("[data-pat-hidden]");
    var numbers = [].slice.call(stage.querySelectorAll("[data-pat-number]"));
    var ruleBox = stage.querySelector("[data-pat-rule]");
    if (!hidden || !numbers.length) return;
    stage.dataset.patMounted = "1";

    // Order by the position the box holds in the pattern, not by DOM order:
    // the order of the numbers IS the answer here.
    numbers.sort(function (a, b) {
      return (parseInt(a.dataset.index, 10) || 0) - (parseInt(b.dataset.index, 10) || 0);
    });

    function compose() {
      var values = numbers
        .map(function (el) { return (el.value || "").trim(); })
        .filter(function (value) { return value !== ""; });
      var line = values.join(", ");
      var rule = ruleBox ? (ruleBox.value || "").trim().replace(LEADING_RULE, "") : "";
      if (!rule) return line;
      return line ? line + RULE_JOINER + rule : "rule: " + rule;
    }

    function refresh() { hidden.value = compose(); }

    var boxes = numbers.concat(ruleBox ? [ruleBox] : []);
    boxes.forEach(function (el, i) {
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
      el.addEventListener("blur", refresh);
      // Enter moves to the next box rather than submitting a half-written
      // pattern; the last one falls through to the form's own submit.
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && i < boxes.length - 1) {
          e.preventDefault();
          boxes[i + 1].focus();
        }
      });
    });
    var form = stage.closest("form");
    if (form) form.addEventListener("submit", refresh, true);

    // Rehydrate from a saved/resumed value: split the line back into the boxes
    // it was composed from, so a returning student sees their own answer.
    var saved = (hidden.value || "").trim();
    if (saved) {
      var parts = saved.split(RULE_JOINER);
      var typed = parts[0].split(",").map(function (v) { return v.trim(); });
      typed.forEach(function (value, i) {
        if (numbers[i]) numbers[i].value = value;
      });
      if (ruleBox && parts.length > 1) ruleBox.value = parts.slice(1).join(RULE_JOINER);
    }
    refresh();
  }

  var SELECTOR = "[data-pat-stage]";

  if (!window.MathsMounts) {
    // Loud, not silent: without the registry the widget would not mount and
    // the student would face boxes that never reach the server.
    console.error("pattern_fields.js: maths_mounts.js must load first.");
    return;
  }
  window.MathsMounts.register(SELECTOR, mount);
})();
