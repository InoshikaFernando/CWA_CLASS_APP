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
