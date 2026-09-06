/* ===========================================================================
 * code_window.js — the shared "coding window": editor on one side, console on
 * the other.
 *
 * Every page that shows code renders this: the standalone compilers, the
 * exercise and problem pages, homework, the worksheet session, and the
 * preview a teacher opens while building a worksheet. Each used to paste in
 * its own CodeMirror setup, which is how the worksheet session ended up
 * stacking its output UNDER the editor while every other page put it beside —
 * one component, six behaviours.
 *
 * Markup lives in templates/coding/partials/_code_window.html; this file only
 * brings it to life.  Everything is scoped to the window's root element, never
 * to document-wide ids, so a page can host several windows at once — homework
 * renders one per question, and the exercise page renders the two halves as
 * separate windows so the console can sit beside the exercise text.
 *
 * Usage from a template:
 *     {% include "coding/partials/_code_window_head.html" %}   (once, in head)
 *     {% include "coding/partials/_code_window.html" with ... %}
 *
 * A page that needs more than "run this and show the output" hooks in through
 * two events on the window root:
 *
 *     code-window:run     — Run/Ctrl-Enter, when cw_external_run is set, so
 *                           the page makes the request itself (the problem
 *                           page submits against test cases).
 *     code-window:result  — after every run, carrying the response, so the
 *                           page can layer its own reading on it (the
 *                           exercise page's score card and mark-complete).
 *
 * Windows mount themselves on DOMContentLoaded and after any htmx swap — so
 * a page script running inline must look a window up when it needs one, not
 * cache it at parse time, when nothing is mounted yet. A window swapped into
 * a container that is still hidden (the builder's preview modal) renders at
 * zero height, so call CodeWindow.refreshAll() once the container is visible.
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
    // A page can render one half only: "editor" where it shows results its own
    // way (the problem page runs against test cases, so a stdout pane would be
    // wrong), "console" where the editor is not a textarea at all (the Scratch
    // exercises are a Blockly workspace).
    this.panes = cfg.panes || 'both';
    this.editor = null;
    this.editorHtml = null;
    this.editorCss = null;

    if (this.panes !== 'console') this._buildEditors();
    this._bind();

    // Show something in the iframe before the first click — but only when
    // this window has editors of its own to build a document from. A
    // console-only preview is fed by its page (the exercise page's Run
    // renders the editor window's code into it).
    if (this.isPreview && this.editorHtml && cfg.autoRun !== false) {
      this.run();
    }
  }

  CodeWindow.prototype._makeEditor = function (textarea, mode) {
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
        // Word completion, where the page asked for it and the addon loaded.
        'Ctrl-Space': this.cfg.autocomplete ? 'autocomplete' : undefined,
      },
    });
    // fromTextArea seeds the editor from the textarea's own value — do NOT
    // setValue() over it. On the homework page a saved draft is written into
    // that textarea before mount, and overwriting it would silently throw a
    // student's resumed work away. cfg.starter is only what Reset goes back to.
    var cm = CodeMirror.fromTextArea(textarea, opts);
    cm.clearHistory();
    cm.setSize('100%', '100%');
    return cm;
  };

  CodeWindow.prototype._buildEditors = function () {
    if (this.isPreview) {
      this.editorHtml = this._makeEditor($(this.root, '.cw-editor-html'), 'htmlmixed');
      this.editorCss = this._makeEditor($(this.root, '.cw-editor-css'), 'css');
    } else {
      this.editor = this._makeEditor(
        $(this.root, '.cw-editor'), this.cfg.cmMode || 'python');
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
   * `state` is true (match), false (mismatch) or null (nothing to say);
   * `message` overrides the default wording. */
  CodeWindow.prototype._setMatch = function (state, message) {
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
    el.textContent = message || (state
      ? '✓ Output matches the expected output.'
      : '✗ Output does not match the expected output.');
  };

  /* Replace what is in the editor (the HTML pane, in preview mode). */
  CodeWindow.prototype.setCode = function (code) {
    var cm = this.isPreview ? this.editorHtml : this.editor;
    if (!cm) return;
    cm.setValue(code || '');
    cm.refresh();
    if (this.isPreview) this.run();
  };

  CodeWindow.prototype.reset = function () {
    if (!this.editor && !this.editorHtml) return;
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
    if (!this.editor && !this.editorHtml) return '';
    return this.isPreview ? this.buildDocument() : this.editor.getValue();
  };

  /* Run code the page supplies rather than the editor's own.
   * A console-only window has no editor to read — the Scratch exercises
   * generate their code from a Blockly workspace. `extraPayload` is merged
   * into the request (Scratch sends its blocks XML along for the record). */
  CodeWindow.prototype.runWith = function (code, extraPayload) {
    return this._runRemote(code, extraPayload);
  };

  /* HTML + CSS are two editors but one document: inject the stylesheet just
   * before </head>, or prepend it when the snippet has no head. */
  CodeWindow.prototype.buildDocument = function () {
    if (!this.editorHtml) return '';
    var html = this.editorHtml.getValue();
    var styleTag = '<style>\n' + this.editorCss.getValue() + '\n</style>';
    if (/<\/head>/i.test(html)) {
      return html.replace(/<\/head>/i, styleTag + '\n</head>');
    }
    return styleTag + '\n' + html;
  };

  CodeWindow.prototype.run = function () {
    // A page that owns the running — the problem page submits against test
    // cases, the exercise page drives an editor window and a console window
    // as a pair — gets told to run rather than having a request made for it.
    // Keeps Ctrl-Enter meaning the same thing on every page.
    if (this.cfg.externalRun) {
      this.root.dispatchEvent(new CustomEvent('code-window:run', { bubbles: true }));
      return Promise.resolve();
    }
    if (this.isPreview) {
      this.setPreview(this.buildDocument());
      return Promise.resolve();
    }
    return this._runRemote();
  };

  /* Render a document in the live-preview iframe. Used by a console-only
   * preview window, which has no editor of its own to build one from. */
  CodeWindow.prototype.setPreview = function (html) {
    var frame = $(this.root, '.cw-preview');
    if (frame) frame.srcdoc = html || '';
  };

  CodeWindow.prototype._runRemote = function (overrideCode, extraPayload) {
    var self = this;
    var btn = $(this.root, '.cw-run');
    var stdout = $(this.root, '.cw-stdout');
    var stdinEl = $(this.root, '.cw-stdin');
    var originalLabel = btn ? btn.innerHTML : '';
    var code = overrideCode !== undefined && overrideCode !== null
      ? overrideCode
      : (this.editor ? this.editor.getValue() : '');

    if (!code.trim()) {
      if (stdout) stdout.textContent = 'Write some code first.';
      this._setStderr('');
      this._setMatch(null);
      return Promise.resolve();
    }

    if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
    if (stdout) stdout.textContent = 'Running…';
    this._setStderr('');
    this._setMatch(null);

    // `language` and `language_slug` carry the same value: the playground and
    // teacher-preview endpoints read the first, api_run_code the second. One
    // window serves all three rather than each caller owning a spelling.
    var payload = Object.assign({
      language: this.cfg.language,
      language_slug: this.cfg.language,
      code: code,
      stdin: stdinEl ? stdinEl.value : '',
    }, this.cfg.payload || {}, extraPayload || {});

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
      // Pages layer their own reading on a run — the exercise page shows a
      // score card and unlocks "mark complete". Hand them the response rather
      // than teaching the window about exercises.
      self.root.dispatchEvent(new CustomEvent('code-window:result', {
        bubbles: true,
        detail: { ok: result.ok, status: result.status, data: result.data },
      }));
    }).catch(function () {
      if (stdout) stdout.textContent = 'Network error — please try again.';
    }).then(function () {
      if (btn) { btn.disabled = false; btn.innerHTML = originalLabel; }
    });
  };

  CodeWindow.prototype._render = function (result) {
    var stdout = $(this.root, '.cw-stdout');
    var data = result.data || {};
    if (!stdout) return;   // editor-only window: the page renders results

    if (!result.ok) {
      stdout.textContent = data.error || ('Server error ' + result.status);
      return;
    }

    // HTML/CSS and DOM exercises render in the browser and never reach the
    // sandbox, so api_run_code answers with this instead of output.
    if (data.browser_sandbox) {
      stdout.textContent = 'This one runs in the browser — open it on the '
                         + 'exercise page to see the rendered result.';
      this._setStderr('');
      this._setMatch(null);
      return;
    }

    var out = data.stdout || '';
    stdout.textContent = out || (data.error ? data.error : '(no output)');
    this._setStderr(data.stderr || '');
    this._setVerdict(data, out);
  };

  /* Did the run produce what the exercise wanted?
   *
   * Prefer the server's answer whenever it gives one: api_run_code also
   * enforces the exercise's required_code_patterns, so a plain client-side
   * comparison would cheerfully tell a student "matches" on a run the server
   * is about to reject for using the wrong approach. Fall back to comparing
   * against cfg.expectedOutput only where no exercise is in play (the teacher
   * preview, which scores nothing). */
  CodeWindow.prototype._setVerdict = function (data, out) {
    if (data.exercise_has_expected && typeof data.exercise_score === 'number') {
      if (data.exercise_score === 100) {
        this._setMatch(true);
      } else {
        this._setMatch(false, data.exercise_pattern_fail
          ? '✗ Output is correct, but use the approach shown in the starter code.'
          : null);
      }
      return;
    }

    var expected = this.cfg.expectedOutput;
    if (expected !== null && expected !== undefined && expected !== '') {
      this._setMatch(out.trim() === String(expected).trim());
    }
  };

  /* Write the editor's text back into the textarea it replaced.
   *
   * CodeMirror does this itself on a NATIVE form submit, which is not enough
   * here: the worksheet session posts over htmx, and the homework page
   * serialises the form for autosave without submitting it at all. Both read
   * the textarea, so both need an explicit flush first — see syncAll(). */
  CodeWindow.prototype.save = function () {
    [this.editor, this.editorHtml, this.editorCss].forEach(function (cm) {
      if (cm) cm.save();
    });
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

    /* Flush every window's editor back into its textarea, so a form read
     * (submit, htmx serialisation, autosave) sees the current code. */
    syncAll: function (scope) {
      var host = scope || document;
      var save = function (root) {
        if (root[INSTANCE]) root[INSTANCE].save();
      };
      if (host.matches && host.matches('[data-code-window]')) save(host);
      Array.prototype.forEach.call(
        host.querySelectorAll('[data-code-window]'), save);
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

    // An htmx post serialises the form itself, without a native submit, so
    // CodeMirror's own submit hook never fires. The worksheet session submits
    // this way, and flushing the textarea here is NOT enough on its own:
    // htmx:configRequest fires AFTER htmx has already read the form, so the
    // request would still carry whatever the textarea held at page load — the
    // starter code, every time, with nothing anywhere reporting a problem.
    // The fresh value therefore goes into the outgoing parameters directly.
    document.body.addEventListener('htmx:configRequest', function (evt) {
      var target = evt.target;
      var scope = (target && target.closest && target.closest('form')) || target || document;
      api.syncAll(scope);

      var params = evt.detail && evt.detail.parameters;
      if (!params || !scope.querySelectorAll) return;

      Array.prototype.forEach.call(
        scope.querySelectorAll('[data-code-window] textarea[name]'), function (ta) {
          // htmx 2 hands over a FormData; htmx 1 a plain object.
          if (typeof params.set === 'function') params.set(ta.name, ta.value);
          else params[ta.name] = ta.value;
        });
    });
  });

})(window, document);
