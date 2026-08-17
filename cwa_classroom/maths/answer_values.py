"""Numeric interpretation of stored answer text, for detecting multiple-choice
questions whose *distractors* are mathematically equal to the correct answer.

Why this exists (CPP-377): a student reported being marked wrong on a Year 7
fractions quiz. The grading code was fine — multiple-choice is graded purely by
``Answer.is_correct`` (``quiz/views.py``), so no amount of grader tolerance was
involved. The fault was in the *question data*: options were authored as
"traps for students who don't simplify", e.g.

    Q: A baker uses 1/3 kg of flour per cake. 9 cakes?
       [correct] '3 kg'      '2 3/3 kg'      '9/3 kg'      '3 1/3 kg'

``2 3/3 kg`` and ``9/3 kg`` both *equal* 3 kg. A student who works the problem
correctly and picks the unsimplified form is marked wrong for a right answer.
Such an option is never a valid distractor.

This module answers one question — "what number is this answer text?" — so both
the audit command and any validator agree on the interpretation.

Deliberately conservative: anything not unambiguously a single number returns
``None`` (no value), and callers must treat ``None`` as "can't compare" rather
than "not equal". Compound answers ("6/30 and 2/30"), inequality symbols (">"),
and free text ("C = 8, D = 3") are all ``None``.
"""
import re
from fractions import Fraction

# Units and currency words are stripped before parsing: within a single
# question the options share a unit ('3 kg' vs '9/3 kg'), so the unit carries
# no distinguishing information and only blocks the numeric comparison.
_UNIT_RE = re.compile(
    r'\b('
    r'mm|cm|m|km|mg|g|kg|ml|l'
    r'|litres?|liters?|metres?|meters?|grams?|kilograms?'
    r'|teaspoons?|tablespoons?|cups?|slices?|pieces?'
    r'|cakes?|pizzas?|apples?|units?'
    r'|hours?|hrs?|minutes?|mins?|seconds?|secs?|days?|weeks?|months?|years?'
    r'|dollars?|cents?'
    r')\b',
    re.IGNORECASE,
)

_MIXED_RE = re.compile(r'(-?\d+)\s+(\d+)\s*/\s*(\d+)')      # 3 3/4
_FRACTION_RE = re.compile(r'(-?\d+)\s*/\s*(\d+)')            # 15/4
_DECIMAL_RE = re.compile(r'-?\d+(?:\.\d+)?')                 # 3 or 0.75


def parse_answer_value(text):
    """Return the ``Fraction`` an answer string denotes, or ``None``.

    ``None`` means "not a single comparable number" — the caller must not
    treat two ``None`` values as equal to each other.

    >>> parse_answer_value('3 3/4 teaspoons')
    Fraction(15, 4)
    >>> parse_answer_value('15/4')
    Fraction(15, 4)
    >>> parse_answer_value('$60')
    Fraction(60, 1)
    >>> parse_answer_value('6/30 and 2/30') is None
    True
    """
    if text is None:
        return None
    s = str(text).strip().lower()
    if not s:
        return None

    # Compound answers ("6/30 and 2/30", "C = 8, D = 3") describe more than one
    # value; there is no single number to compare.
    if ' and ' in s or '=' in s:
        return None

    s = s.replace('$', '').replace(',', '')
    s = _UNIT_RE.sub(' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if not s:
        return None

    # Mixed number first — "3 3/4" must not be read as the fraction "3/4".
    m = _MIXED_RE.fullmatch(s)
    if m:
        whole_text, num, den = m.group(1), int(m.group(2)), int(m.group(3))
        if den == 0:
            return None
        whole = int(whole_text)
        # "-2 1/2" is -(2 + 1/2), not (-2 + 1/2): the sign covers the whole
        # quantity, so apply it after combining the parts.
        sign = -1 if whole_text.lstrip().startswith('-') else 1
        return sign * (Fraction(abs(whole)) + Fraction(num, den))

    m = _FRACTION_RE.fullmatch(s)
    if m:
        den = int(m.group(2))
        if den == 0:
            return None
        return Fraction(int(m.group(1)), den)

    m = _DECIMAL_RE.fullmatch(s)
    if m:
        return Fraction(s)

    return None


def find_equivalent_options(question):
    """Return ``[(distractor_answer, correct_answer), ...]`` for every option
    on ``question`` that is numerically equal to a correct option but is not
    itself flagged correct.

    An empty list means the question is clean *or* not comparable (non-numeric
    options). Only meaningful for choice-graded questions — the caller decides
    which those are.
    """
    options = list(question.answers.all())
    correct = [a for a in options if a.is_correct]
    if not correct:
        return []

    correct_values = [(a, parse_answer_value(a.answer_text)) for a in correct]
    correct_values = [(a, v) for a, v in correct_values if v is not None]
    if not correct_values:
        return []

    clashes = []
    for option in options:
        if option.is_correct:
            continue
        value = parse_answer_value(option.answer_text)
        if value is None:
            continue
        for correct_answer, correct_value in correct_values:
            if value == correct_value:
                clashes.append((option, correct_answer))
                break
    return clashes
