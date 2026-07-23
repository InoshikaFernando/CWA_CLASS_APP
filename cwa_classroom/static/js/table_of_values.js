/*
 * table_of_values.js — interactive "fill in the x/y table" tool.
 *
 * Dependency-free. Mounts on every `[data-tv-stage]`: each blank cell
 * (`[data-tv-cell]`, carrying its "row,col" key in data-rc) is collected into
 * the stage's hidden input as JSON {"cells":{"r,c":"value"}}. Given cells are
 * static text and need no wiring.
 *
 * Idempotent (a `data-tv-mounted` flag guards re-mounts) and re-scans on
 * DOMContentLoaded AND via a MutationObserver, because the topic quiz and the
 * worksheet session swap questions in with innerHTML (inline scripts would not
 * run). Each stage is scoped to its own element, so any number of table
 * questions can share a page. Reads the hidden input's current value on mount,
 * so a restored/resumed draft re-fills correctly.
 */
(function () {
  "use strict";

  function mount(stage) {
    if (!stage || stage.dataset.tvMounted === "1") return;
    var hidden = stage.querySelector("[data-tv-hidden]");
    var cells = stage.querySelectorAll("[data-tv-cell]");
    if (!hidden || !cells.length) return;
    stage.dataset.tvMounted = "1";

    function refresh() {
      var out = {};
      cells.forEach(function (el) {
        var v = (el.value || "").trim();
        if (v !== "") out[el.dataset.rc] = v;
      });
      hidden.value = JSON.stringify({ cells: out });
    }

    cells.forEach(function (el) {
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
      el.addEventListener("blur", refresh);
    });
    var form = stage.closest("form");
    if (form) form.addEventListener("submit", refresh, true);

    // Rehydrate from a saved/resumed value, then keep the hidden field in sync.
    try {
      var saved = JSON.parse(hidden.value || "{}");
      if (saved && saved.cells) {
        cells.forEach(function (el) {
          if (saved.cells[el.dataset.rc] != null) el.value = saved.cells[el.dataset.rc];
        });
      }
    } catch (e) { /* malformed saved value — start blank */ }
    refresh();
  }

  var SELECTOR = "[data-tv-stage]";

  // Mount every matching stage within a freshly-added subtree (the node itself
  // or any descendants). Scoped to what actually changed — never a
  // full-document rescan.
  function scanRoot(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.matches && node.matches(SELECTOR)) mount(node);
    if (node.querySelectorAll) node.querySelectorAll(SELECTOR).forEach(mount);
  }

  function scanAll() {
    document.querySelectorAll(SELECTOR).forEach(mount);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scanAll);
  } else {
    scanAll();
  }

  if (typeof MutationObserver !== "undefined") {
    // NOTE: this observer block is duplicated in number_line.js. If a THIRD
    // observer-mounted interactive type is added (or draw_on_grid / plot_points /
    // shape_select move off their inline scripts onto the quiz/worksheet
    // surfaces), consolidate all of them into one shared maths_mounts.js registry
    // — register({selector, mount}) + a single debounced observer — instead of
    // copying this again. Not worth it for two files today.
    //
    // Coalesce a burst of mutations into one requestAnimationFrame-batched pass,
    // and only scan the subtrees that were actually added — not the whole
    // document on every mutation (the quiz/worksheet surfaces mutate a lot).
    var queue = [];
    var scheduled = false;
    var raf = window.requestAnimationFrame || function (cb) { return setTimeout(cb, 16); };
    function flush() {
      scheduled = false;
      var nodes = queue;
      queue = [];
      nodes.forEach(scanRoot);
    }
    new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var added = muts[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          if (added[j].nodeType === 1) queue.push(added[j]);
        }
      }
      if (queue.length && !scheduled) { scheduled = true; raf(flush); }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
})();
