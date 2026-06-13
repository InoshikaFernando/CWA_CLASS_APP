// Live superscript formatting for maths answer inputs.
//
// Typing "y^2" renders as "y²" in the box (Unicode superscripts), so students
// see proper notation as they type. Works on any <input>/<textarea> carrying
// the class "cwa-exp-input" — including ones added later by HTMX/AJAX or Alpine
// — via a single delegated, capture-phase "input" listener.
//
// Grading already accepts the pretty form (the algebra grader normalises y² to
// y^2; fold_exponents folds y²/y^2/y2 together), so storing "9y²" is fine.
(function () {
  var SUP = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'
  };

  function toSuper(digits) {
    return digits.replace(/[0-9]/g, function (c) { return SUP[c]; });
  }

  function format(value) {
    // "^12" -> superscript digits (caret consumed)
    value = value.replace(/\^([0-9]+)/g, function (_, d) { return toSuper(d); });
    // a digit typed directly after a superscript digit extends the exponent,
    // so multi-digit powers (^12) keep formatting as you type them
    value = value.replace(/([⁰¹²³⁴⁵⁶⁷⁸⁹])([0-9]+)/g,
      function (_, sup, d) { return sup + toSuper(d); });
    return value;
  }

  function onInput(e) {
    var f = e.target;
    if (!f || !f.classList || !f.classList.contains('cwa-exp-input')) return;
    var before = f.value;
    var after = format(before);
    if (after === before) return;
    var pos = f.selectionStart;
    f.value = after;
    var removed = before.length - after.length;
    var newPos = Math.max(0, (pos == null ? after.length : pos) - removed);
    try { f.selectionStart = f.selectionEnd = newPos; } catch (err) { /* detached */ }
  }

  // Capture phase: transform the value BEFORE Alpine's bubbling x-model listener
  // reads it, so the bound model stays in sync with the displayed pretty value.
  document.addEventListener('input', onInput, true);
})();
