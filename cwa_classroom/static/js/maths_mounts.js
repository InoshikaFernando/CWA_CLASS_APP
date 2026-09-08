/*
 * maths_mounts.js — one mount registry for every interactive maths widget.
 *
 * The interactive question types (number line, table of values, fill in the
 * blanks) all need the same three things: mount on page load, mount again when
 * the topic quiz / worksheet session swaps a question in with innerHTML (inline
 * scripts inside swapped-in HTML do not run), and never mount the same stage
 * twice. That machinery used to be copied into each widget file; this is the
 * single copy, as the note left in number_line.js and table_of_values.js asked
 * for when a third widget appeared.
 *
 * Usage — from a widget script, after defining its own mount(stage):
 *
 *     window.MathsMounts.register("[data-fb-stage]", mount);
 *
 * register() mounts everything already in the document, then keeps mounting
 * anything added later. mount() must be idempotent on its own element (each
 * widget guards with its own data-*-mounted flag); the registry does not track
 * which elements it has seen, because a stage can legitimately be re-created.
 *
 * Load this BEFORE any widget script — the widgets error loudly rather than
 * silently not mounting if it is missing.
 */
(function () {
  "use strict";

  var widgets = [];      // [{selector, mount}]
  var queue = [];        // subtrees added since the last flush
  var scheduled = false;
  var raf = window.requestAnimationFrame || function (cb) { return setTimeout(cb, 16); };

  // Mount every registered widget found within a freshly-added subtree (the
  // node itself or any descendants). Scoped to what actually changed — never a
  // full-document rescan, because the quiz/worksheet surfaces mutate a lot.
  function scanRoot(node) {
    if (!node || node.nodeType !== 1) return;
    widgets.forEach(function (w) {
      if (node.matches && node.matches(w.selector)) w.mount(node);
      if (node.querySelectorAll) node.querySelectorAll(w.selector).forEach(w.mount);
    });
  }

  function scanAll() {
    widgets.forEach(function (w) {
      document.querySelectorAll(w.selector).forEach(w.mount);
    });
  }

  function flush() {
    scheduled = false;
    var nodes = queue;
    queue = [];
    nodes.forEach(scanRoot);
  }

  function register(selector, mount) {
    if (!selector || typeof mount !== "function") return;
    widgets.push({ selector: selector, mount: mount });
    // Mount what is already on the page. A widget script may load before or
    // after DOMContentLoaded depending on defer/caching, so handle both.
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(selector).forEach(mount);
      });
    } else {
      document.querySelectorAll(selector).forEach(mount);
    }
  }

  window.MathsMounts = { register: register, scanAll: scanAll };

  if (typeof MutationObserver !== "undefined") {
    // Coalesce a burst of mutations into one requestAnimationFrame-batched
    // pass. One observer for all widgets, rather than one per widget file.
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
