"""
algebra_grading.py
~~~~~~~~~~~~~~~~~~~
Dependency-free grading for school-level polynomial answers (e.g. expanding
``(2x + 3)(x - 5)`` to ``2x^2 - 7x - 15``).

A typed answer is marked correct ONLY when it is the *fully simplified, expanded*
polynomial equal to the expected answer. Concretely:

  - term order does not matter      ``-7x + 2x^2 - 15``  == ``2x^2 - 7x - 15``  OK
  - spacing/notation does not matter ``2x^2-7x-15`` / ``2x^2 - 7x - 15``        OK
  - unicode/`**` exponents accepted  ``2x^2``  ``2x^2``  ``2x**2``  (all -> x^2) OK
  - un-combined like terms FAIL      ``2x^2 - 3x - 4x - 15``  (two x terms)      WRONG
  - un-expanded brackets FAIL        ``(2x + 3)(x - 5)``                          WRONG
  - wrong value FAIL                 ``2x^2 - 7x - 14``                           WRONG

Why not SymPy?
    SymPy auto-combines like terms the instant it parses (``-3x - 4x`` becomes
    ``-7x``), which would mark the *un-simplified* answer correct. The whole
    point here is to enforce the "combine like terms / expand the brackets"
    learning objective, so we must inspect the answer *as written* before any
    algebra collapses it. We do that by splitting the raw string into terms
    first, then checking no two written terms are "like terms".

Input notation accepted:
    coefficients : integers, decimals, and simple fractions (``2``, ``1.5``, ``3/4``)
    variables    : single letters ``a``-``z`` (multi-variable OK: ``x^2 - y^2``)
    exponents    : ``^n`` / ``**n`` / unicode superscripts (``x^2``, ``x**2``, ``x^2``)
    products     : implicit (``2x``, ``xy``) or explicit (``2*x``, ``x*y``)

The expected answer may list ``|`` separated alternative correct forms, matching
the convention already used elsewhere for short answers.
"""
import re
from fractions import Fraction
from typing import Dict, List, Set, Tuple

# A monomial signature: sorted ((variable, exponent), ...) with exponents > 0.
# The empty tuple () is the constant term.
Signature = Tuple[Tuple[str, int], ...]
Polynomial = Dict[Signature, Fraction]

_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUPERSCRIPT_MAP = str.maketrans(_SUPERSCRIPTS, "0123456789")

# A coefficient token: integer, decimal, or simple fraction (e.g. 2, 1.5, 3/4).
_NUM = r"\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?"
# One full term: optional sign, optional coefficient, then variable factors.
_TERM_RE = re.compile(rf"^([+-]?)({_NUM})?((?:\*?[a-z](?:\^\d+)?)*)$")
# A single variable factor inside a term: optional '*', a letter, optional '^n'.
_VAR_RE = re.compile(r"\*?([a-z])(?:\^(\d+))?")


class MathAnswerError(ValueError):
    """Raised when a string cannot be parsed as a simplified polynomial."""


def normalize_notation(text: str) -> str:
    """Fold the many ways of typing an exponent/product into one canonical form.

    Lowercases, converts unicode superscripts (``x^2``) and ``**`` to ``^``,
    treats ``*``, ``·``, ``×``, ``•`` as multiplication, and strips ALL
    whitespace so ``2x^2 - 7x`` and ``2x^2-7x`` compare equal.

    >>> normalize_notation("2X^2 - 7x - 15")
    '2x^2-7x-15'
    >>> normalize_notation("2x^2")
    '2x^2'
    >>> normalize_notation("2x**2 - 7x")
    '2x^2-7x'
    """
    s = text.strip().lower()
    # Unicode superscripts: a run of superscript digits -> "^" + the digits.
    s = re.sub(
        rf"[{_SUPERSCRIPTS}]+",
        lambda m: "^" + m.group(0).translate(_SUPERSCRIPT_MAP),
        s,
    )
    s = s.replace("**", "^")
    for mult in ("·", "×", "•"):
        s = s.replace(mult, "*")
    s = re.sub(r"\s+", "", s)
    return s


def fold_exponents(text: str) -> str:
    """Canonicalise exponent notation for *exact-match* (non-algebra) grading.

    Folds the three ways a student might type a power onto one form by mapping
    unicode superscripts to ASCII digits and removing the ``^`` / ``**`` markers
    entirely, so ``cm^2`` == ``cm²`` == ``cm**2`` == ``cm2``. Also lowercases and
    trims. This lets the x² button be useful on ordinary maths answers (areas,
    volumes, indices) without the teacher's stored answer having to match the
    exact notation the student typed.

    NOTE: this is for the literal-match path only. Algebra questions keep the
    ``^`` (see is_algebraic_answer_correct) because the polynomial parser needs it.

    >>> fold_exponents("2 CM^2")
    '2cm2'
    >>> fold_exponents("2cm²") == fold_exponents("2 cm^2") == fold_exponents("2cm2")
    True
    """
    s = text.lower()
    s = re.sub(rf"[{_SUPERSCRIPTS}]+", lambda m: m.group(0).translate(_SUPERSCRIPT_MAP), s)
    s = s.replace("**", "").replace("^", "")
    return re.sub(r"\s+", "", s)


def fold_inequalities(text: str) -> str:
    """Canonicalise the many ways a student types an inequality operator.

    Folds the unicode operators (``≥`` ``≤``), the reversed-typo forms
    (``=>`` ``=<``) and the ASCII forms (``>=`` ``<=``) onto a single ASCII
    spelling so a stored ``x ≥ 2`` matches ``x>=2`` / ``x=>2`` / ``x ≥ 2``.
    Whitespace is left untouched here (the caller folds it) so this composes
    cleanly with :func:`fold_exponents`.

    ``≥``/``≤`` (non-strict) and ``>``/``<`` (strict) are kept DISTINCT — a
    student typing ``x>2`` is not accepted for a stored ``x ≥ 2``. Not-equal is
    also folded: the keypad's ``≠`` and the ASCII ``<>`` both land on ``!=``.

    >>> fold_inequalities("x ≥ 2")
    'x >= 2'
    >>> fold_inequalities("x=>2") == fold_inequalities("x>=2") == "x>=2"
    True
    >>> fold_inequalities("y=<5") == fold_inequalities("y ≤ 5".replace(" ", "")) == "y<=5"
    True
    >>> fold_inequalities("a ≠ b") == fold_inequalities("a <> b") == "a != b"
    True
    """
    # Reversed typos first, then unicode, so every spelling lands on >=/<=.
    s = text.replace("=>", ">=").replace("=<", "<=")
    s = s.replace("≥", ">=").replace("≤", "<=")
    # not-equal: keypad ≠ and the ASCII <> spelling -> !=
    s = s.replace("≠", "!=").replace("<>", "!=")
    return s


def fold_degrees(text: str) -> str:
    """Drop the degree sign so an angle/temperature answer grades the same
    typed with or without it — ``50`` == ``50°``.

    The ° button on the maths keypad inserts a literal ``°``; a teacher's stored
    answer may or may not include it, and a student may or may not add it.
    Removing it on both sides of the match makes the two equal. Composes cleanly
    with :func:`fold_exponents` (whitespace left untouched here; the caller
    folds it). Literal-match path only (see ``grade_text_answer``) — the
    measure / number_line graders already strip the unit numerically in
    ``geometry_grading._to_decimal``.

    >>> fold_degrees("50°")
    '50'
    >>> fold_degrees("50")
    '50'
    """
    return text.replace("°", "")


# Separators a student (or a teacher) may use between the option labels of a
# "select every correct option" answer: commas, "and", "&", ";" or plain spaces.
# Kept here next to the folds because every grading surface needs the same
# split. Deliberately NOT "/" or "-": those are operators, and treating "x/y" or
# "a-b" as an unordered pair would accept the reversed (unequal) expression.
_LABEL_SEPARATOR_RE = re.compile(r"[,&;]|\band\b|\s+", re.IGNORECASE)
_OPTION_LABEL_RE = re.compile(r"^[A-Za-z]$")


def option_label_set(text: str):
    """Return the set of option labels in a *pick-all-that-apply* answer, or
    ``None`` when the text is not such a list.

    The question bank has no multi-select question type: a "which of these are
    correct?" question is authored as a typed short answer whose correct text
    lists the option labels — ``"D and E"``. The student types the same labels
    in whatever order and with whatever separator they reach for (``"E,D"``,
    ``"e d"``), so those answers must be compared as a **set**, not as a string
    (CPP-374).

    Only lists of *single letters* qualify. Anything else — a worded answer, an
    ordered sequence of numbers ("3, 5, 7" for "write these in order") — returns
    ``None`` and keeps its order-sensitive exact match, so making selections
    order-insensitive can't quietly accept a wrongly-ordered sequence.

    >>> option_label_set("D and E") == {"d", "e"}
    True
    >>> option_label_set("E,D") == {"d", "e"}
    True
    >>> option_label_set("D") is None          # single label: plain match is enough
    True
    >>> option_label_set("3, 5, 7") is None    # order matters, not a label list
    True
    """
    tokens = [t for t in _LABEL_SEPARATOR_RE.split(text.strip()) if t]
    if len(tokens) < 2:
        return None
    if not all(_OPTION_LABEL_RE.match(t) for t in tokens):
        return None
    return {t.lower() for t in tokens}


def _to_fraction(num: str) -> Fraction:
    """Parse an int/decimal/simple-fraction coefficient token into a Fraction."""
    if "/" in num:
        top, bottom = num.split("/", 1)
        denominator = Fraction(bottom)
        if denominator == 0:
            # e.g. a student typing "1/0x" — treat as an unparseable answer
            # (wrong) rather than letting ZeroDivisionError become an HTTP 500.
            raise MathAnswerError(f"Division by zero in coefficient: {num!r}")
        return Fraction(top) / denominator
    return Fraction(num)


def _split_terms(s: str) -> List[str]:
    """Split a normalized, bracket-free expression into signed terms.

    With brackets already rejected and exponents always non-negative, every
    ``+``/``-`` (except a leading one) begins a new term.

    >>> _split_terms("2x^2-7x-15")
    ['2x^2', '-7x', '-15']
    >>> _split_terms("-7x+2x^2-15")
    ['-7x', '+2x^2', '-15']
    """
    terms: List[str] = []
    current = ""
    for i, ch in enumerate(s):
        if ch in "+-" and i != 0:
            terms.append(current)
            current = ch
        else:
            current += ch
    if current:
        terms.append(current)
    return terms


def _parse_term(term: str) -> Tuple[Fraction, Signature]:
    """Parse one term into (coefficient, monomial signature).

    >>> _parse_term("2x^2")
    (Fraction(2, 1), (('x', 2),))
    >>> _parse_term("-15")
    (Fraction(-15, 1), ())
    >>> _parse_term("-x")
    (Fraction(-1, 1), (('x', 1),))
    """
    match = _TERM_RE.match(term)
    if not match:
        raise MathAnswerError(f"Cannot parse term: {term!r}")
    sign, num, var_part = match.group(1), match.group(2), match.group(3)

    coeff = _to_fraction(num) if num else Fraction(1)
    if sign == "-":
        coeff = -coeff

    exponents: Dict[str, int] = {}
    for var_match in _VAR_RE.finditer(var_part):
        var = var_match.group(1)
        exp = int(var_match.group(2)) if var_match.group(2) else 1
        exponents[var] = exponents.get(var, 0) + exp  # x*x -> x^2 (still a monomial)

    signature = tuple(sorted((v, e) for v, e in exponents.items() if e != 0))
    return coeff, signature


def _collect(text: str, *, strict: bool) -> Polynomial:
    """Parse text into ``{signature: coefficient}``, dropping zero coefficients.

    When ``strict`` is True (the student's answer) the form is enforced:
    brackets and un-combined like terms raise ``MathAnswerError``. When False
    (the teacher's expected answer) only the value is computed.
    """
    s = normalize_notation(text)
    if not s:
        raise MathAnswerError("Empty expression")
    if "(" in s or ")" in s:
        raise MathAnswerError("Contains brackets — not expanded")

    poly: Polynomial = {}
    seen: Set[Signature] = set()
    for term in _split_terms(s):
        if term in ("", "+", "-"):
            raise MathAnswerError(f"Dangling operator in {text!r}")
        coeff, signature = _parse_term(term)
        if strict and signature in seen:
            raise MathAnswerError("Like terms not combined")
        seen.add(signature)
        poly[signature] = poly.get(signature, Fraction(0)) + coeff

    return {sig: c for sig, c in poly.items() if c != 0}


def is_algebraic_answer_correct(user_answer: str, correct_answer: str) -> bool:
    """Return True iff ``user_answer`` is the fully simplified polynomial equal
    to ``correct_answer`` (which may list ``|`` separated acceptable forms).

    The student's answer is graded *strictly*: un-expanded brackets and
    un-combined like terms are wrong even when algebraically equal.

    >>> is_algebraic_answer_correct("2x^2 - 7x - 15", "2x^2 - 7x - 15")
    True
    >>> is_algebraic_answer_correct("-7x + 2x^2 - 15", "2x^2 - 7x - 15")
    True
    >>> is_algebraic_answer_correct("2x^2 - 3x - 4x - 15", "2x^2 - 7x - 15")
    False
    >>> is_algebraic_answer_correct("(2x + 3)(x - 5)", "2x^2 - 7x - 15")
    False
    """
    if not user_answer or not correct_answer:
        return False

    try:
        student = _collect(user_answer, strict=True)
    except MathAnswerError:
        return False

    for alternative in correct_answer.split("|"):
        alternative = alternative.strip()
        if not alternative:
            continue
        try:
            if student == _collect(alternative, strict=False):
                return True
        except MathAnswerError:
            # A misconfigured expected answer: fall back to a forgiving literal
            # compare so the question is not silently unanswerable.
            if normalize_notation(user_answer) == normalize_notation(alternative):
                return True
    return False


# ---------------------------------------------------------------------------
# Term-order fallback for plain-text ('text') answers
# ---------------------------------------------------------------------------
# "Write an algebraic expression for the total cost" is authored as an ordinary
# typed short answer (answer_format='text'), so it is graded by literal match —
# which marked a student's ``110 + 12p`` wrong against the stored ``12p + 110``
# even though addition commutes and the answer is the one being taught. Rather
# than requiring every such question to be re-tagged as 'algebra', the text path
# falls back to comparing the two as polynomials when BOTH sides are written as
# a simple expression (see _is_simple_expression).
#
# The guard matters: the polynomial parser reads a run of letters as a product
# of single-letter variables, so an unguarded fallback would grade the word
# answers "felt" and "left" — same letters — as equal. Only strings whose every
# term is ``number? letter? ^exponent?`` (so at most one letter per term) and
# which have two or more terms take this path; a worded answer, a hyphenated
# number word ("fifty-three") or anything with brackets keeps its exact match.

# One term of a "simple expression": optional sign, optional coefficient, at
# most ONE variable letter with an optional exponent.
_SIMPLE_TERM_RE = re.compile(rf"^[+-]?(?:{_NUM})?(?:\*?[a-z](?:\^\d+)?)?$")


def _is_simple_expression(text: str) -> bool:
    """True when *text* is a multi-term expression of number/single-letter terms.

    >>> _is_simple_expression("12p + 110")
    True
    >>> _is_simple_expression("2x^2 - 7x - 15")
    True
    >>> _is_simple_expression("12p")            # one term: nothing to reorder
    False
    >>> _is_simple_expression("felt")           # word, not an expression
    False
    >>> _is_simple_expression("fifty-three")    # hyphenated number word
    False
    >>> _is_simple_expression("3(x + 2)")       # brackets: not simplified
    False
    """
    s = normalize_notation(text)
    if not s or "(" in s or ")" in s:
        return False
    terms = _split_terms(s)
    if len(terms) < 2:
        return False
    return all(term not in ("", "+", "-") and _SIMPLE_TERM_RE.match(term) for term in terms)


def is_reordered_expression_correct(user_answer: str, correct_answer: str) -> bool:
    """Return True iff both answers are simple expressions with the same terms.

    The order the terms are written in is all that may differ: the student's
    answer is still graded strictly (brackets and un-combined like terms are
    wrong), so this only forgives commuting a sum — it never accepts work the
    student was asked to finish.

    >>> is_reordered_expression_correct("110 + 12p", "12p + 110")
    True
    >>> is_reordered_expression_correct("12p - 110", "12p + 110")
    False
    >>> is_reordered_expression_correct("110 + 11p", "12p + 110")
    False
    >>> is_reordered_expression_correct("felt", "left")
    False
    """
    if not user_answer or not correct_answer:
        return False
    if not _is_simple_expression(user_answer):
        return False
    for alternative in correct_answer.split("|"):
        alternative = alternative.strip()
        if _is_simple_expression(alternative) and is_algebraic_answer_correct(
            user_answer, alternative
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Equation-equivalence grading (answer_format = 'equation')
# ---------------------------------------------------------------------------
# For "write the equation of this parabola" questions, the answer key is vertex
# form (e.g. ``y = 2(x-1)^2 - 2``) but a student may legitimately give the same
# curve in factored or expanded form. Unlike ``is_algebraic_answer_correct``
# (which enforces the *expand & simplify* objective and so rejects brackets),
# this grades by algebraic EQUIVALENCE: it parses each side into a polynomial —
# brackets, powers and implicit multiplication supported — isolates ``y`` from
# the equation, and compares the resulting ``f(x)``. Any two spellings of the
# same function grade equal.
#
# Still dependency-free (no SymPy): a tiny recursive-descent parser builds the
# polynomial directly, so numerically-equal-but-differently-written answers
# (2(x-1)^2 - 2 == 2x^2 - 4x) are accepted while genuinely different curves are
# not.


def _sig_mul(s1: Signature, s2: Signature) -> Signature:
    """Multiply two monomial signatures (sum the exponents per variable)."""
    exps: Dict[str, int] = {}
    for v, e in s1:
        exps[v] = exps.get(v, 0) + e
    for v, e in s2:
        exps[v] = exps.get(v, 0) + e
    return tuple(sorted((v, e) for v, e in exps.items() if e != 0))


def _poly_const(value: Fraction) -> Polynomial:
    return {(): value} if value != 0 else {}


def _poly_scale(poly: Polynomial, factor: Fraction) -> Polynomial:
    if factor == 0:
        return {}
    return {sig: c * factor for sig, c in poly.items()}


def _poly_add(a: Polynomial, b: Polynomial) -> Polynomial:
    out: Polynomial = dict(a)
    for sig, c in b.items():
        out[sig] = out.get(sig, Fraction(0)) + c
    return {sig: c for sig, c in out.items() if c != 0}


def _poly_mul(a: Polynomial, b: Polynomial) -> Polynomial:
    out: Polynomial = {}
    for s1, c1 in a.items():
        for s2, c2 in b.items():
            sig = _sig_mul(s1, s2)
            out[sig] = out.get(sig, Fraction(0)) + c1 * c2
    return {sig: c for sig, c in out.items() if c != 0}


def _poly_pow(base: Polynomial, n: int) -> Polynomial:
    result: Polynomial = {(): Fraction(1)}
    for _ in range(n):
        result = _poly_mul(result, base)
    return result


def _poly_div(a: Polynomial, b: Polynomial) -> Polynomial:
    """Divide by a constant polynomial only (all we need for coefficients like
    ``3/4`` or ``x^2/2``). A non-constant or zero divisor is unparseable."""
    if set(b) - {()}:
        raise MathAnswerError("Cannot divide by a non-constant expression")
    denom = b.get((), Fraction(0))
    if denom == 0:
        raise MathAnswerError("Division by zero")
    return {sig: c / denom for sig, c in a.items()}


class _ExprParser:
    """Recursive-descent parser: normalized string → multivariable Polynomial.

    Grammar (implicit multiplication by adjacency):
        expr   := ('+'|'-')? term (('+'|'-') term)*
        term   := factor (('*'|'/'| adjacency) factor)*
        factor := base ('^' <int>)?
        base   := number | letter | '(' expr ')'
    """

    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def _peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def parse(self) -> Polynomial:
        poly = self._expr()
        if self.i != len(self.s):
            raise MathAnswerError(f"Unexpected {self.s[self.i:]!r}")
        return poly

    def _expr(self) -> Polynomial:
        # NB: membership tests use tuples, not the string "+-", because
        # ``"" in "+-"`` is True in Python (empty substring) — an EOF peek must
        # NOT be mistaken for an operator.
        neg = False
        if self._peek() in ("+", "-"):
            neg = self._peek() == "-"
            self.i += 1
        result = self._term()
        if neg:
            result = _poly_scale(result, Fraction(-1))
        while self._peek() in ("+", "-"):
            op = self._peek()
            self.i += 1
            term = self._term()
            result = _poly_add(result, term if op == "+" else _poly_scale(term, Fraction(-1)))
        return result

    def _term(self) -> Polynomial:
        result = self._factor()
        while True:
            c = self._peek()
            if c in ("*", "/"):
                self.i += 1
                factor = self._factor()
                result = _poly_mul(result, factor) if c == "*" else _poly_div(result, factor)
            elif c and (c == "(" or c == "." or c.isdigit() or c.isalpha()):
                result = _poly_mul(result, self._factor())  # implicit multiplication
            else:
                break
        return result

    def _factor(self) -> Polynomial:
        base = self._base()
        if self._peek() == "^":
            self.i += 1
            base = _poly_pow(base, self._integer())
        return base

    def _base(self) -> Polynomial:
        c = self._peek()
        if c == "(":
            self.i += 1
            inner = self._expr()
            if self._peek() != ")":
                raise MathAnswerError("Missing closing bracket")
            self.i += 1
            return inner
        if c.isdigit() or c == ".":
            return _poly_const(self._number())
        if c.isalpha():
            self.i += 1
            return {((c, 1),): Fraction(1)}
        raise MathAnswerError(f"Unexpected character {c!r}")

    def _number(self) -> Fraction:
        start = self.i
        while self._peek().isdigit():
            self.i += 1
        if self._peek() == ".":
            self.i += 1
            while self._peek().isdigit():
                self.i += 1
        token = self.s[start:self.i]
        try:
            return Fraction(token)
        except (ValueError, ZeroDivisionError):
            raise MathAnswerError(f"Bad number {token!r}")

    def _integer(self) -> int:
        start = self.i
        while self._peek().isdigit():
            self.i += 1
        if start == self.i:
            raise MathAnswerError("Exponent must be a non-negative integer")
        return int(self.s[start:self.i])


_Y_SIGNATURE: Signature = (("y", 1),)


def _equation_fx(text: str) -> Polynomial:
    """Reduce an equation/expression to the polynomial ``f(x)`` where ``y = f(x)``.

    Accepts ``y = <expr>``, ``f(x) = <expr>``, a bare ``<expr>``, or any single
    equation linear in ``y`` (e.g. ``y + 3 = 3/4(x-4)^2``). Raises
    ``MathAnswerError`` for anything not reducible to a single-variable ``f(x)``
    (nonlinear in y, an x·y cross term, a stray variable, malformed input).
    """
    s = normalize_notation(text)
    s = re.sub(r"^f\(x\)=", "y=", s)  # f(x)= is just another way to write y=
    if not s:
        raise MathAnswerError("Empty expression")

    if "=" in s:
        sides = s.split("=")
        if len(sides) != 2 or not sides[0] or not sides[1]:
            raise MathAnswerError("Malformed equation")
        poly = _poly_add(
            _ExprParser(sides[0]).parse(),
            _poly_scale(_ExprParser(sides[1]).parse(), Fraction(-1)),
        )
    else:
        poly = _ExprParser(s).parse()

    # Any y must appear only as the linear term y^1 (no y^2, no x*y).
    for sig in poly:
        if any(v == "y" for v, _ in sig) and sig != _Y_SIGNATURE:
            raise MathAnswerError("Equation is not of the form y = f(x)")

    cy = poly.get(_Y_SIGNATURE, Fraction(0))
    if cy != 0:
        rest = {sig: c for sig, c in poly.items() if sig != _Y_SIGNATURE}
        fx = _poly_scale(rest, Fraction(-1) / cy)  # y = -(rest)/cy
    else:
        fx = poly  # a bare expression is already f(x)

    for sig in fx:
        for v, _ in sig:
            if v != "x":
                raise MathAnswerError(f"Unexpected variable {v!r}")
    return fx


def is_equation_answer_correct(user_answer: str, correct_answer: str) -> bool:
    """Return True iff ``user_answer`` describes the same ``y = f(x)`` as
    ``correct_answer`` (which may list ``|`` separated acceptable forms).

    Graded by algebraic equivalence — vertex, factored and expanded forms of the
    same curve are all accepted; a genuinely different curve is not.

    >>> is_equation_answer_correct("y = 2(x-1)^2 - 2", "y = 2(x-1)^2 - 2")
    True
    >>> is_equation_answer_correct("y = 2x^2 - 4x", "y = 2(x-1)^2 - 2")
    True
    >>> is_equation_answer_correct("y = 2(x-1)^2 + 1", "y = 2(x-1)^2 - 2")
    False
    """
    if not user_answer or not correct_answer:
        return False
    try:
        student = _equation_fx(user_answer)
    except MathAnswerError:
        return False
    for alternative in correct_answer.split("|"):
        alternative = alternative.strip()
        if not alternative:
            continue
        try:
            if student == _equation_fx(alternative):
                return True
        except MathAnswerError:
            # A misconfigured expected answer: fall back to a forgiving literal
            # compare so the question is not silently unanswerable.
            if normalize_notation(user_answer) == normalize_notation(alternative):
                return True
    return False
