/*
 * sketch_graph.js — "sketch the graph and state its key features" tool.
 *
 * Dependency-free. Mounts on every `[data-sk-stage]`: each feature box
 * (`[data-sk-feature]`, carrying its feature kind in data-kind) is collected
 * into the stage's hidden input as JSON {"features":{"vertex":"(-0.5,-2.25)"}}.
 * The blank plane beside the boxes is a static SVG — there is nothing to click,
 * because the marks on these questions are for the FEATURES the stem names, not
 * for a hand-drawn curve.
 *
 * Idempotent (a `data-sk-mounted` flag guards re-mounts); mounting — on load and
 * again after the topic quiz and worksheet session swap questions in with
 * innerHTML (inline scripts would not run) — is handled by the shared registry
 * in maths_mounts.js. Each stage is scoped to its own element, so any number of
 * sketch questions can share a page. Reads the hidden input's current value on
 * mount, so a restored/resumed draft re-fills correctly.
 */
(function () {
  "use strict";

  function mount(stage) {
    if (!stage || stage.dataset.skMounted === "1") return;
    var hidden = stage.querySelector("[data-sk-hidden]");
    var boxes = stage.querySelectorAll("[data-sk-feature]");
    if (!hidden || !boxes.length) return;
    stage.dataset.skMounted = "1";

    function refresh() {
      var out = {};
      boxes.forEach(function (el) {
        var v = (el.value || "").trim();
        if (v !== "") out[el.dataset.kind] = v;
      });
      hidden.value = JSON.stringify({ features: out });
    }

    boxes.forEach(function (el) {
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
      el.addEventListener("blur", refresh);
    });
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
    } catch (e) { /* malformed saved value — start blank */ }
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
