// Maths answer-input helpers: a symbol button panel + live superscript.
//
// For every <input>/<textarea> carrying the class "cwa-exp-input" this script:
//   1. Drops a small symbol keypad to the RIGHT of the box (x² √ π ≤ ≥ = < > ≠).
//      Clicking a button inserts the symbol at the caret. x² inserts "^".
//   2. Live-formats powers: typing "y^2" shows as "y²" (Unicode superscripts).
//
// It works on inputs added later by HTMX/AJAX or Alpine (a MutationObserver
// re-scans), and preserves the input element identity when wrapping it, so
// Alpine x-ref / x-model bindings keep working.
//
// Grading already accepts what the panel produces — the algebra grader and
// maths.algebra_grading.fold_exponents (y²/y^2, cm²) and fold_inequalities
// (≤ ≡ <=, ≥ ≡ >=, ≠ ≡ !=) make grading accept the keypad's symbols.
(function () {
  // ---------------------------------------------------------------- superscript
  var SUP = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'
  };
  function toSuper(digits) {
    return digits.replace(/[0-9]/g, function (c) { return SUP[c]; });
  }
  function format(value) {
    value = value.replace(/\^([0-9]+)/g, function (_, d) { return toSuper(d); });
    value = value.replace(/([⁰¹²³⁴⁵⁶⁷⁸⁹])([0-9]+)/g,
      function (_, sup, d) { return sup + toSuper(d); });
    return value;
  }
  function onInput(e) {
    var f = e.target;
    if (!f || !f.classList || !f.classList.contains('cwa-exp-input')) return;
    var before = f.value, after = format(before);
    if (after === before) return;
    var pos = f.selectionStart;
    f.value = after;
    var newPos = Math.max(0, (pos == null ? after.length : pos) - (before.length - after.length));
    try { f.selectionStart = f.selectionEnd = newPos; } catch (err) { /* detached */ }
  }
  document.addEventListener('input', onInput, true);

  // --------------------------------------------------------------- symbol panel
  // ins = text inserted at the caret; html = button face (defaults to ins).
  var SYMBOLS = [
    { ins: '^', html: 'x<sup>2</sup>', aria: 'exponent (power)' },
    { ins: '√', aria: 'square root' },
    { ins: 'π', aria: 'pi' },
    { ins: '≤', aria: 'less than or equal' },
    { ins: '≥', aria: 'greater than or equal' },
    { ins: '=', aria: 'equals' },
    { ins: '<', aria: 'less than' },
    { ins: '>', aria: 'greater than' },
    { ins: '≠', aria: 'not equal' }
  ];

  function insertAtCaret(field, text) {
    var s = field.selectionStart, e = field.selectionEnd;
    if (s == null) {
      field.value += text;
    } else {
      field.value = field.value.slice(0, s) + text + field.value.slice(e);
    }
    field.focus();
    if (s != null) {
      try { field.selectionStart = field.selectionEnd = s + text.length; } catch (err) {}
    }
    // Notify the superscript formatter + any framework (Alpine x-model) binding.
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function buildPanel(field) {
    var panel = document.createElement('div');
    panel.className = 'cwa-sym-panel';
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', 'Insert a maths symbol');
    SYMBOLS.forEach(function (sym) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'cwa-sym-btn';
      b.tabIndex = -1;                 // keep tab order on the answer box, not the keypad
      b.setAttribute('aria-label', sym.aria);
      b.innerHTML = sym.html || sym.ins;
      b.addEventListener('mousedown', function (ev) { ev.preventDefault(); }); // don't steal focus
      b.addEventListener('click', function () { insertAtCaret(field, sym.ins); });
      panel.appendChild(b);
    });
    return panel;
  }

  function decorate(field) {
    if (field.dataset.cwaPanel) return;
    field.dataset.cwaPanel = '1';
    var row = document.createElement('div');
    row.className = 'cwa-answer-row';
    field.parentNode.insertBefore(row, field);
    row.appendChild(field);                  // moving the node preserves Alpine bindings
    row.appendChild(buildPanel(field));
  }

  function scan(root) {
    (root || document).querySelectorAll('.cwa-exp-input').forEach(function (f) {
      if (!f.dataset.cwaPanel) decorate(f);
    });
  }

  var style = document.createElement('style');
  style.textContent =
    '.cwa-answer-row{display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap;flex:1 1 auto}' +
    '.cwa-answer-row>.cwa-exp-input{flex:1 1 220px;min-width:0}' +
    '.cwa-sym-panel{display:grid;grid-template-columns:repeat(3,2.25rem);grid-auto-rows:2.25rem;gap:6px;flex:0 0 auto}' +
    '.cwa-sym-btn{display:inline-flex;align-items:center;justify-content:center;padding:0;' +
      'border:1px solid #d1d5db;border-radius:8px;background:#fff;color:#374151;' +
      'font-size:15px;line-height:1;cursor:pointer;-webkit-user-select:none;user-select:none}' +
    '.cwa-sym-btn:hover{background:#f9fafb}' +
    '.cwa-sym-btn:active{transform:scale(0.96)}' +
    '.cwa-sym-btn sup{font-size:0.7em}';
  document.head.appendChild(style);

  function init() {
    scan(document);
    if (!document.body) return;
    var mo = new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        if (!m.addedNodes) return;
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.matches && n.matches('.cwa-exp-input')) decorate(n);
          if (n.querySelectorAll) scan(n);
        });
      });
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
