"""Grading helpers for geometry/measurement question types (CPP-330).

Pure functions — no DB, no request — so every delivery surface (homework,
worksheets, the maths plugin) grades identically, the same way
``Question.grade_text_answer`` is centralised on the model.

CPP-332 adds ``grade_measure`` for the ``measure`` question type. The
``draw_on_grid`` grader (``grade_draw_on_grid``) lands in CPP-337.
"""
from decimal import Decimal, InvalidOperation


def _to_decimal(raw):
    """Best-effort parse of a typed measurement into a Decimal.

    Strips any non-numeric unit characters (``135°`` -> ``135``) and a
    leading ``+``. Returns ``None`` if nothing numeric remains.
    """
    if raw is None:
        return None
    # Keep digits, sign, and a single decimal point; drop unit letters/symbols.
    cleaned = ''.join(c for c in str(raw).strip() if c.isdigit() or c in '.-+')
    if cleaned in ('', '+', '-', '.', '-.', '+.'):
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def grade_measure(question, raw):
    """True if the student's typed value is within tolerance of the answer.

    ``correct`` when ``|value - numeric_answer| <= tolerance``, where
    ``tolerance`` is ``answer_tolerance`` or 0 (NULL tolerance = exact match).
    Returns ``False`` on a missing target or an unparseable answer — never
    raises, so a malformed submission is simply wrong, not a 500.
    """
    target = question.numeric_answer
    if target is None:
        return False
    value = _to_decimal(raw)
    if value is None:
        return False
    tolerance = question.answer_tolerance or Decimal('0')
    return abs(value - target) <= tolerance
