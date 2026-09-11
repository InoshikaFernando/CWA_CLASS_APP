/*
 * progress_art.js — the reward picture that draws itself as a student works.
 *
 * A quiz, a homework paper and a worksheet each hand this a picture (an ordered
 * list of SVG paths, built by classroom/progress_art.py), a question total and
 * how many are done. It reveals `done / total` of the drawing's TOTAL PATH
 * LENGTH — not a whole number of strokes — using stroke-dashoffset, so the same
 * picture works for a 15-question quiz and a 120-question homework without
 * anything having to divide evenly. Question one always produces a visible mark
 * because every picture opens with a small dot.
 *
 * Two ways to drive it:
 *
 *   1. `ProgressArt.set(n)` — pages that show one question at a time (the topic
 *      quiz) just say how many are done as each answer is graded.
 *
 *   2. Answer groups — pages that show every question at once (the homework
 *      take page, the mixed quiz) mark each question block `data-pa-group` and
 *      let this file count them. The count STARTS from the server's `data-pa-done`
 *      and only a group the student actually touches is re-examined. That
 *      matters: a coding question's textarea arrives pre-filled with starter
 *      code, and a naive "is this field non-empty?" sweep would count it as
 *      answered the moment the page loaded and gift away part of the picture.
 *
 * Progress is derived, never stored client-side: a resumed homework draft
 * continues the drawing because the server already knows how many answers the
 * draft holds. Only the *choice* of picture is persisted, so a student cannot
 * come back the next day to a different drawing.
 *
 * Dependency-free and idempotent (a `data-pa-mounted` flag guards re-mounts).
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var DURATION = 900;          // ms for one reveal animation
  var MIN_LENGTH = 0.01;       // guards a zero-length path against /0

  var registry = [];           // every mounted panel, for the public API

  function reducedMotion() {
    return !!(window.matchMedia &&
              window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

  function intAttr(el, name, fallback) {
    var raw = parseInt(el.getAttribute(name), 10);
    return isNaN(raw) ? fallback : raw;
  }

  /* Whether a JSON payload holds anything a student actually entered. The
   * construction widgets (draw-on-grid, shape-select, number line) post an
   * empty skeleton — {"segments": []} — before anything has been drawn, and
   * counting that as an answer would gift away picture on page load. Mirrors
   * classroom.progress_art.answer_is_present(); the two must agree or the
   * drawing would jump whenever the page reloads. */
  function jsonHasContent(value) {
    if (value === null || value === undefined) return false;
    if (Array.isArray(value)) return value.some(jsonHasContent);
    if (typeof value === "object") {
      return Object.keys(value).some(function (k) { return jsonHasContent(value[k]); });
    }
    if (typeof value === "string") return value.trim() !== "";
    return true;
  }

  function hasAnswerValue(raw) {
    var text = String(raw == null ? "" : raw).trim();
    if (!text) return false;
    if (text.charAt(0) === "{" || text.charAt(0) === "[") {
      var parsed;
      try { parsed = JSON.parse(text); } catch (e) { return true; }
      return jsonHasContent(parsed);
    }
    return true;
  }

  /* Whether one question block currently holds an answer. Only ever asked
   * about a group the student has just interacted with — see the header. */
  function groupAnswered(group) {
    var fields = group.querySelectorAll("input, textarea, select");
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i];
      if (f.disabled || f.name === "csrfmiddlewaretoken") continue;
      if (f.type === "radio" || f.type === "checkbox") {
        if (f.checked) return true;
      } else if (hasAnswerValue(f.value)) {
        return true;
      }
    }
    return false;
  }

  function Panel(root) {
    this.root = root;
    this.total = Math.max(intAttr(root, "data-pa-total", 0), 0);
    this.done = clamp(intAttr(root, "data-pa-done", 0), 0, this.total);
    this.paths = [];
    this.totalLength = 0;
    this.shownRatio = 0;
    this.frame = null;
  }

  Panel.prototype.build = function () {
    var root = this.root;
    // json_script renders a plain <script type="application/json"> — it
    // cannot carry a data- attribute, so accept either spelling.
    var dataEl = root.querySelector("script[data-pa-picture]")
              || root.querySelector('script[type="application/json"]');
    var svg = root.querySelector("[data-pa-canvas]");
    if (!dataEl || !svg) return false;

    var picture;
    try {
      picture = JSON.parse(dataEl.textContent);
    } catch (e) {
      // A malformed payload must not leave an empty frame pretending to be a
      // picture — drop the whole panel and let the page read as it did before.
      return false;
    }
    if (!picture || !picture.strokes || !picture.strokes.length) return false;

    this.picture = picture;
    svg.setAttribute("viewBox", "0 0 " + picture.width + " " + picture.height);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

    for (var i = 0; i < picture.strokes.length; i++) {
      var el = document.createElementNS(NS, "path");
      el.setAttribute("d", picture.strokes[i]);
      el.setAttribute("class", "pa-stroke");
      svg.appendChild(el);
      var len = MIN_LENGTH;
      try { len = el.getTotalLength() || MIN_LENGTH; } catch (e) { len = MIN_LENGTH; }
      el.style.strokeDasharray = len + " " + len;
      el.style.strokeDashoffset = len;
      this.paths.push({ el: el, len: len });
      this.totalLength += len;
    }

    /* Every picture opens with a small dot (see classroom/progress_art.py), and
     * that dot is free: it is on the page before the first question is answered
     * so the panel reads as "your picture starts here" rather than as an empty
     * box someone forgot to fill. Only the length AFTER it is rationed out over
     * the questions. */
    this.seedLength = this.paths.length ? this.paths[0].len : 0;

    var title = root.querySelector("[data-pa-title]");
    if (title && picture.title) title.textContent = picture.title;
    return true;
  };

  /* Paint the drawing at *ratio* (0 → just the opening dot, 1 → finished). */
  Panel.prototype.paint = function (ratio) {
    var revealed = this.seedLength + ratio * (this.totalLength - this.seedLength);
    var used = 0;
    for (var i = 0; i < this.paths.length; i++) {
      var p = this.paths[i];
      var shown = clamp(revealed - used, 0, p.len);
      // A fully-dashed-out path is not reliably invisible: `stroke-linecap:
      // round` still paints a cap dot at the start of each subpath, which
      // scattered a constellation of stray dots (every star, cloud and grass
      // tuft) across a picture that had barely been started. Hide the element
      // outright until it has actual length to show.
      p.el.style.visibility = shown > 0.01 ? "" : "hidden";
      p.el.style.strokeDashoffset = (p.len - shown);
      used += p.len;
    }
    this.shownRatio = ratio;
  };

  Panel.prototype.targetRatio = function () {
    if (!this.total) return 0;
    return clamp(this.done / this.total, 0, 1);
  };

  Panel.prototype.animate = function () {
    var self = this;
    var from = this.shownRatio;
    var to = this.targetRatio();
    if (this.frame) { cancelAnimationFrame(this.frame); this.frame = null; }
    if (reducedMotion() || Math.abs(to - from) < 0.0005) {
      this.paint(to);
      this.syncLabels();
      return;
    }
    this.root.classList.add("pa-drawing");
    var started = null;
    function step(ts) {
      if (started === null) started = ts;
      var t = clamp((ts - started) / DURATION, 0, 1);
      self.paint(from + (to - from) * easeOutCubic(t));
      if (t < 1) {
        self.frame = requestAnimationFrame(step);
      } else {
        self.frame = null;
        self.root.classList.remove("pa-drawing");
        self.syncLabels();
      }
    }
    this.frame = requestAnimationFrame(step);
  };

  Panel.prototype.syncLabels = function () {
    var root = this.root;
    var countEl = root.querySelector("[data-pa-count]");
    if (countEl) {
      countEl.textContent = this.done + " of " + this.total;
    }
    var complete = this.total > 0 && this.done >= this.total;
    root.classList.toggle("pa-complete", complete);
    var hint = root.querySelector("[data-pa-hint]");
    if (hint) {
      hint.textContent = complete
        ? "Finished! You drew the whole picture."
        : "Answer more questions to draw more of the picture.";
    }
    root.setAttribute("data-pa-done", String(this.done));
    if (complete && !this._announced) {
      this._announced = true;
      root.dispatchEvent(new CustomEvent("progress-art:complete", {
        bubbles: true,
        detail: { key: this.picture ? this.picture.key : "" },
      }));
    }
  };

  Panel.prototype.setDone = function (done) {
    var next = clamp(parseInt(done, 10) || 0, 0, this.total);
    if (next === this.done) return;
    this.done = next;
    this.animate();
  };

  /* Count-the-groups mode. Re-examines ONLY the block the student touched. */
  Panel.prototype.watchGroups = function () {
    var selector = this.root.getAttribute("data-pa-scope");
    var scope = selector ? document.querySelector(selector) : null;
    if (!scope) return;
    var self = this;

    function reexamine(group) {
      var answered = groupAnswered(group) ? "1" : "0";
      if (group.getAttribute("data-pa-answered") === answered) return;
      group.setAttribute("data-pa-answered", answered);
      self.setDone(scope.querySelectorAll('[data-pa-group][data-pa-answered="1"]').length);
    }

    var handler = function (event) {
      var group = event.target && event.target.closest
        ? event.target.closest("[data-pa-group]")
        : null;
      if (!group) return;
      // Deferred by a tick on purpose. A click on a <label for> only checks its
      // radio as the event's DEFAULT ACTION, after every listener has run — and
      // the homework take page has its own label handler that sets `checked`
      // first, which then suppresses the radio's `change` event entirely. So
      // `click` has to be watched as well as `input`/`change`, and the field
      // has to be read after the browser has finished with it.
      setTimeout(function () { reexamine(group); }, 0);
    };
    scope.addEventListener("input", handler);
    scope.addEventListener("change", handler);
    scope.addEventListener("click", handler);
  };

  function mount(root) {
    if (!root || root.getAttribute("data-pa-mounted") === "1") return null;
    var panel = new Panel(root);
    if (!panel.build()) {
      root.setAttribute("data-pa-mounted", "failed");
      return null;
    }
    root.setAttribute("data-pa-mounted", "1");
    panel.paint(panel.targetRatio());
    panel.syncLabels();
    panel.watchGroups();
    registry.push(panel);
    return panel;
  }

  function mountAll() {
    var roots = document.querySelectorAll("[data-progress-art]");
    for (var i = 0; i < roots.length; i++) mount(roots[i]);
  }

  window.ProgressArt = {
    mount: mountAll,
    /* Pages that serve one question at a time call this after each answer. */
    set: function (done) {
      for (var i = 0; i < registry.length; i++) registry[i].setDone(done);
    },
    panels: function () { return registry.slice(); },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountAll);
  } else {
    mountAll();
  }
})();
