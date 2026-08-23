"""Display-only formatting filters for maths question/answer text.

These never mutate stored data — they only change how a value is *rendered*, so
grading (which folds the ASCII forms in maths.algebra_grading) is unaffected.
"""
import re

from django import template

register = template.Library()

# Map the characters that can appear in an exponent onto their Unicode
# superscript glyphs.  Letters are intentionally excluded: not every letter has
# a clean superscript, and the exponents we care about (scientific notation,
# units, indices) are numeric.
_SUPERSCRIPT = str.maketrans({
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '-': '⁻', '+': '⁺',
})

# "^5", "^-4", "**2" — a caret or double-star followed by an optional sign and
# one or more digits. Whitespace after the marker is tolerated ("10^ 5").
_EXPONENT_RE = re.compile(r'(?:\^|\*\*)\s*([+-]?\d+)')


@register.filter
def exponents(value):
    """Render caret/`**` exponents as Unicode superscripts for display.

    ``"2 × 10^5 × 9.8 × 10^-4"`` → ``"2 × 10⁵ × 9.8 × 10⁻⁴"``.

    Display-only: the stored text keeps the ASCII ``^`` form (which
    :func:`maths.algebra_grading.fold_exponents` collapses), so this never
    changes how a typed answer is matched. Returns a plain ``str`` so Django
    autoescaping still applies to the surrounding question text.
    """
    if not value:
        return value
    return _EXPONENT_RE.sub(
        lambda m: m.group(1).translate(_SUPERSCRIPT), str(value),
    )


# Display tiers for AI-graded (extended-answer) maths questions.  These decide
# only how an answer is *labelled* on the result / feedback pages — they never
# touch scoring.  The counted score (``is_correct`` and ``points_earned``) is
# still set by the grader and left as-is, so a 0.85 answer keeps its points in
# the tally while displaying as "Partially correct".
CREDIT_FULL_MARK = 1.0    # a full-marks score shows the green "Correct" tick
CREDIT_PARTIAL_FLOOR = 0.5  # >= this (but below full) shows amber "Partially correct"


@register.filter
def blank_answer(value):
    """Render a fill-in-the-blank answer payload as readable text.

    A fill-in-the-blank sentence posts one value per gap as JSON
    (``{"blanks":["15","live"]}``), so a review page that printed the stored
    text verbatim showed the student their own answer as raw JSON. This turns it
    back into ``"15, live"``, with an unfilled gap shown as "—".

    Display-only, and safe to apply to any typed answer: anything that is not a
    blanks payload is returned unchanged, so a review template can pipe every
    answer through it without first asking what type the question was.

    >>> blank_answer('{"blanks": ["15", "live"]}')
    '15, live'
    >>> blank_answer('42')
    '42'
    """
    if not value:
        return value
    from maths.blank_grading import describe_blank_answer
    return describe_blank_answer(value)


@register.filter
def credit_state(answer):
    """Return ``'correct'``, ``'partial'`` or ``'wrong'`` for how to *display* an answer.

    AI-graded answers carry an ``ai_score_fraction`` (0.0–1.0): they show as
    fully correct only at full marks, partially correct from 0.5 up to that, and
    wrong below 0.5.  Answers without a fraction (MCQ, exact-match, or not yet
    AI-graded) fall back to the stored ``is_correct`` boolean and are never
    "partial".
    """
    frac = getattr(answer, 'ai_score_fraction', None)
    if frac is None:
        return 'correct' if getattr(answer, 'is_correct', False) else 'wrong'
    if frac >= CREDIT_FULL_MARK:
        return 'correct'
    if frac >= CREDIT_PARTIAL_FLOOR:
        return 'partial'
    return 'wrong'
