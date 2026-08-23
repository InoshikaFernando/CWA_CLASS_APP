/*
 * fill_blank.js — interactive "fill in the blanks" sentence.
 *
 * Dependency-free. Mounts on every `[data-fb-stage]`: each gap in the sentence
 * is an `[data-fb-input]` carrying its position in data-index, and the typed
 * values are collected into the stage's hidden input as JSON
 * {"blanks":["15","live"]} — positional, one entry per gap, graded server-side
 * by maths.blank_grading.grade_fill_blank. Correct answers are never emitted
 * into the page.
 *
 * Idempotent (a `data-fb-mounted` flag guards re-mounts); mounting — on load
 * and again after the topic quiz and worksheet session swap questions in with
 * innerHTML (inline scripts would not run) — is handled by the shared registry
 * in maths_mounts.js. Each stage is scoped to its own element, so any number of
 * fill-in-the-blank questions can share a page. Reads the hidden input's
 * current value on mount, so a restored/resumed draft re-fills correctly.
 */
(function () {
  "use strict";

  function mount(stage) {
    if (!stage || stage.dataset.fbMounted === "1") return;
    var hidden = stage.querySelector("[data-fb-hidden]");
    var inputs = [].slice.call(stage.querySelectorAll("[data-fb-input]"));
    if (!hidden || !inputs.length) return;
    stage.dataset.fbMounted = "1";

    // Order by the position the gap holds in the sentence, not by DOM order, so
    // the payload stays aligned with the spec even if the markup is ever
    // re-laid-out.
    inputs.sort(function (a, b) {
      return (parseInt(a.dataset.index, 10) || 0) - (parseInt(b.dataset.index, 10) || 0);
    });

    function refresh() {
      hidden.value = JSON.stringify({
        blanks: inputs.map(function (el) { return (el.value || "").trim(); }),
      });
    }

    inputs.forEach(function (el, i) {
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
      el.addEventListener("blur", refresh);
      // Enter moves to the next gap rather than submitting a half-filled
      // sentence; the last gap falls through to the form's own submit.
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && i < inputs.length - 1) {
          e.preventDefault();
          inputs[i + 1].focus();
        }
      });
    });
    var form = stage.closest("form");
    if (form) form.addEventListener("submit", refresh, true);

    // Rehydrate from a saved/resumed value, then keep the hidden field in sync.
    try {
      var saved = JSON.parse(hidden.value || "{}");
      if (saved && Array.isArray(saved.blanks)) {
        inputs.forEach(function (el, i) {
          if (saved.blanks[i] != null) el.value = saved.blanks[i];
        });
      }
    } catch (e) { /* malformed saved value — start blank */ }
    refresh();
  }

  var SELECTOR = "[data-fb-stage]";

  if (!window.MathsMounts) {
    // Loud, not silent: without the registry the widget simply would not mount
    // and the student would face an inert question.
    console.error("fill_blank.js: maths_mounts.js must load first.");
    return;
  }
  window.MathsMounts.register(SELECTOR, mount);
})();
