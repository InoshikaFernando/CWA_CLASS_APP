/* ===========================================================================
 * code_window.js — the shared "coding window": editor on one side, console on
 * the other.
 *
 * The same split view is wanted in several places (the standalone compilers,
 * the worksheet-builder preview a teacher opens while authoring, homework and
 * worksheet sessions).  It used to be copy-pasted per page, which is how the
 * worksheet session ended up stacking its output UNDER the editor while every
 * other page put it beside — same component, four different behaviours.
 *
 * Markup lives in templates/coding/partials/_code_window.html; this file only
 * brings it to life.  Everything is scoped to the window's root element, never
 * to document-wide ids, so a page can host several windows at once (homework
 * renders one per question).
 *
 * Usage from a template:
 *     {% include "coding/partials/_code_window_head.html" %}   (once, in head)
 *     {% include "coding/partials/_code_window.html" with ... %}
 *
 * Windows mount themselves on DOMContentLoaded and after any htmx swap.  A
 * window swapped into a container that is still hidden (the builder's preview
 * modal) renders at zero height, so call CodeWindow.refreshAll() once the
 * container is visible.
 * ======================================================================== */
(function (window, document) {
  'use strict';

  var MOUNTED = 'cwMounted';       // dataset flag — never mount a root twice
  var INSTANCE = '__codeWindow';   // instance stashed on the root element

  var CM_BASE_OPTS = {
    theme: 'dracula',
    lineNumbers: true,
    indentUnit: 2,
    tabSize: 2,
    indentWithTabs: false,
    autoCloseBrackets: true,
    matchBrackets: true,
    styleActiveLine: true,
  };

  var IDLE_MESSAGE = 'Press “Run” to see your output here.';

  // ── helpers ──────────────────────────────────────────────────────────────

  function $(root, selector) { return root.querySelector(selector); }

  function readConfig(root) {
    var node = $(root, '.cw-config');
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      // A malformed config would otherwise leave a dead editor on the page
      // with no clue why — say so instead of failing silently.
      console.error('code_window: could not parse config', err);
      return null;
    }
  }

  // ── the window itself ────────────────────────────────────────────────────

  function CodeWindow(root, cfg) {
    this.root = root;
    this.cfg = cfg;
    this.isPreview = cfg.mode === 'preview';
    this.editor = null;
    this.editorHtml = null;
    this.editorCss = null;

    this._buildEditors();
    this._bind();

    if (this.isPreview && cfg.autoRun !== false) {
      this.run();   // show something in the iframe before the first click
    }
  }

  CodeWindow.prototype._makeEditor = function (textarea, mode, value) {
    var self = this;
    var opts = Object.assign({}, CM_BASE_OPTS, {
      mode: mode,
      readOnly: this.cfg.readOnly ? 'nocursor' : false,
      extraKeys: {
        'Tab': function (cm) {
          if (cm.somethingSelected()) { cm.indentSelection('add'); }
          else { cm.replaceSelection('  ', 'end'); }
        },
        'Shift-Tab': 'indentLess',
        'Ctrl-Enter': function () { self.run(); },
        'Cmd-Enter': function () { self.run(); },
      },
    });
    var cm = CodeMirror.fromTextArea(textarea, opts);
    cm.setValue(value || '');
    cm.clearHistory();
    cm.setSize('100%', '100%');
    return cm;
  };

  CodeWindow.prototype._buildEditors = function () {
    if (this.isPreview) {
      this.editorHtml = this._makeEditor(
        $(this.root, '.cw-editor-html'), 'htmlmixed', this.cfg.starterHtml);
      this.editorCss = this._makeEditor(
        $(this.root, '.cw-editor-css'), 'css', this.cfg.starterCss);
    } else {
      this.editor = this._makeEditor(
        $(this.root, '.cw-editor'), this.cfg.cmMode || 'python', this.cfg.starter);
    }
  };

  CodeWindow.prototype._bind = function () {
    var self = this;
    var root = this.root;

    var runBtn = $(root, '.cw-run');
    if (runBtn) runBtn.addEventListener('click', function () { self.run(); });

    var resetBtn = $(root, '.cw-reset');
    if (resetBtn) resetBtn.addEventListener('click', function () { self.reset(); });

    var clearBtn = $(root, '.cw-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () { self.clear(); });

    // Optional "load this snippet" button — the builder preview uses it to
    // drop the reference solution into the editor so a teacher can check the
    // exercise actually produces its expected output.
    var loadBtn = $(root, '.cw-load');
    if (loadBtn) loadBtn.addEventListener('click', function () {
      self.setCode(self.cfg.extraCode || '');
    });

    Array.prototype.forEach.call(root.querySelectorAll('.cw-tab'), function (tab) {
      tab.addEventListener('click', function () { self.showTab(tab.dataset.cwTab); });
    });
  };

  // ── tabs (HTML / CSS preview mode) ───────────────────────────────────────

  CodeWindow.prototype.showTab = function (which) {
    var showHtml = which === 'html';
    var root = this.root;

    $(root, '.cw-host-html').classList.toggle('hidden', !showHtml);
    $(root, '.cw-host-css').classList.toggle('hidden', showHtml);

    Array.prototype.forEach.call(root.querySelectorAll('.cw-tab'), function (tab) {
      tab.classList.toggle('active', tab.dataset.cwTab === which);
    });

    var label = $(root, '.cw-file-label');
    if (label) label.textContent = showHtml ? 'index.html' : 'style.css';

    // CodeMirror measures itself on creation; an editor that was hidden then
    // needs a refresh or it draws as an empty box.
    var cm = showHtml ? this.editorHtml : this.editorCss;
    setTimeout(function () { cm.refresh(); }, 0);
  };

  // ── output panel ─────────────────────────────────────────────────────────

  CodeWindow.prototype.clear = function () {
    var stdout = $(this.root, '.cw-stdout');
    if (stdout) stdout.textContent = IDLE_MESSAGE;
    this._setStderr('');
    this._setMatch(null);
  };

  CodeWindow.prototype._setStderr = function (text) {
    var el = $(this.root, '.cw-stderr');
    if (!el) return;
    el.textContent = text || '';
    el.style.display = text ? 'block' : 'none';
  };

  /* Show whether stdout matched the exercise's expected output.
   * `state` is true (match), false (mismatch) or null (nothing to say). */
  CodeWindow.prototype._setMatch = function (state) {
    var el = $(this.root, '.cw-match');
    if (!el) return;
    if (state === null) {
      el.style.display = 'none';
      el.textContent = '';
      return;
    }
    el.style.display = 'block';
    el.classList.toggle('cw-match-ok', state);
    el.classList.toggle('cw-match-bad', !state);
    el.textContent = state
      ? '✓ Output matches the expected output.'
      : '✗ Output does not match the expected output.';
  };

  /* Replace what is in the editor (the HTML pane, in preview mode). */
  CodeWindow.prototype.setCode = function (code) {
    var cm = this.isPreview ? this.editorHtml : this.editor;
    cm.setValue(code || '');
    cm.refresh();
    if (this.isPreview) this.run();
  };

  CodeWindow.prototype.reset = function () {
    if (!window.confirm('Reset code to the starter template?')) return;
    if (this.isPreview) {
      this.editorHtml.setValue(this.cfg.starterHtml || '');
      this.editorCss.setValue(this.cfg.starterCss || '');
      this.run();
    } else {
      this.editor.setValue(this.cfg.starter || '');
      this.editor.clearHistory();
      this.clear();
    }
  };

  // ── running ──────────────────────────────────────────────────────────────

  CodeWindow.prototype.getValue = function () {
    return this.isPreview ? this.buildDocument() : this.editor.getValue();
  };

  /* HTML + CSS are two editors but one document: inject the stylesheet just
   * before </head>, or prepend it when the snippet has no head. */
  CodeWindow.prototype.buildDocument = function () {
    var html = this.editorHtml.getValue();
    var styleTag = '<style>\n' + this.editorCss.getValue() + '\n</style>';
    if (/<\/head>/i.test(html)) {
      return html.replace(/<\/head>/i, styleTag + '\n</head>');
    }
    return styleTag + '\n' + html;
  };

  CodeWindow.prototype.run = function () {
    if (this.isPreview) {
      $(this.root, '.cw-preview').srcdoc = this.buildDocument();
      return Promise.resolve();
    }
    return this._runRemote();
  };

  CodeWindow.prototype._runRemote = function () {
    var self = this;
    var btn = $(this.root, '.cw-run');
    var stdout = $(this.root, '.cw-stdout');
    var stdinEl = $(this.root, '.cw-stdin');
    var originalLabel = btn ? btn.innerHTML : '';

    if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
    stdout.textContent = 'Running…';
    this._setStderr('');
    this._setMatch(null);

    var payload = Object.assign({
      language: this.cfg.language,
      code: this.editor.getValue(),
      stdin: stdinEl ? stdinEl.value : '',
    }, this.cfg.payload || {});

    return fetch(this.cfg.runUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.cfg.csrfToken,
      },
      body: JSON.stringify(payload),
    }).then(function (res) {
      return res.json().then(function (data) { return { ok: res.ok, status: res.status, data: data }; });
    }).then(function (result) {
      self._render(result);
    }).catch(function () {
      stdout.textContent = 'Network error — please try again.';
    }).then(function () {
      if (btn) { btn.disabled = false; btn.innerHTML = originalLabel; }
    });
  };

  CodeWindow.prototype._render = function (result) {
    var stdout = $(this.root, '.cw-stdout');
    var data = result.data || {};

    if (!result.ok) {
      stdout.textContent = data.error || ('Server error ' + result.status);
      return;
    }

    var out = data.stdout || '';
    stdout.textContent = out || (data.error ? data.error : '(no output)');
    this._setStderr(data.stderr || '');

    var expected = this.cfg.expectedOutput;
    if (expected !== null && expected !== undefined && expected !== '') {
      this._setMatch(out.trim() === String(expected).trim());
    }
  };

  CodeWindow.prototype.refresh = function () {
    [this.editor, this.editorHtml, this.editorCss].forEach(function (cm) {
      if (cm) cm.refresh();
    });
  };

  // ── public API ───────────────────────────────────────────────────────────

  var api = {
    /* Mount one root element. Returns the instance, or null when the root is
     * already mounted / has no usable config. */
    mount: function (root) {
      if (!root || root.dataset[MOUNTED] === '1') return null;
      if (typeof CodeMirror === 'undefined') {
        console.error('code_window: CodeMirror is not loaded — include '
                      + 'coding/partials/_code_window_head.html in the page head.');
        return null;
      }
      var cfg = readConfig(root);
      if (!cfg) return null;

      root.dataset[MOUNTED] = '1';
      var instance = new CodeWindow(root, cfg);
      root[INSTANCE] = instance;
      return instance;
    },

    /* Mount every unmounted window in `scope` (default: the document).
     * `scope` itself counts — an htmx swap can land the window root directly
     * on the target, where querySelectorAll would never see it. */
    mountAll: function (scope) {
      var host = scope || document;
      if (host.matches && host.matches('[data-code-window]')) api.mount(host);
      Array.prototype.forEach.call(
        host.querySelectorAll('[data-code-window]'), api.mount);
    },

    /* Re-measure editors — call after revealing a container that was hidden
     * when its window mounted (CodeMirror draws blank otherwise). */
    refreshAll: function (scope) {
      var host = scope || document;
      var refresh = function (root) {
        if (root[INSTANCE]) root[INSTANCE].refresh();
      };
      if (host.matches && host.matches('[data-code-window]')) refresh(host);
      Array.prototype.forEach.call(
        host.querySelectorAll('[data-code-window]'), refresh);
    },

    /* The instance for a root element, or undefined. */
    get: function (root) { return root ? root[INSTANCE] : undefined; },
  };

  window.CodeWindow = api;

  document.addEventListener('DOMContentLoaded', function () {
    api.mountAll(document);
    // htmx-loaded windows (the worksheet builder's preview modal) mount as
    // soon as they land in the DOM.
    document.body.addEventListener('htmx:afterSwap', function (evt) {
      api.mountAll(evt.target || document);
    });
  });

})(window, document);
