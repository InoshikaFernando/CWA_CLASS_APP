"""Grading for the question types whose answer is the arithmetic itself.

A column sum and a long division store no Answer row: the numbers ARE the
question, so the answer is worked out from ``operands``/``operator`` and from
``dividend``/``divisor`` (this is the contract
``answer_verification.SELF_GRADED_ANSWER_FIELDS`` states, and what the upload
and import paths rely on when they save such a question with no answers).

Every surface that marks these types must therefore grade them here rather than
against the Answer rows. It lives in its own module because it did not: the
quiz had no branch for a column sum, so 867 × 8 = 6936 — the answer the
question's own explanation works out — was scored wrong for every student who
ever typed it, while the identical question on a worksheet was scored right.
"""
import re

# The student writes the result one digit per box, so what arrives is a bare
# run of digits, sometimes with a leading blank box ("06936") or stray spaces.
_NUMBER_RE = re.compile(r'^\s*(-?\d+)\s*$')

# "12", "12 r 3", "12r3", "12 R 3" — the quotient, optionally with a remainder.
_QUOTIENT_RE = re.compile(r'^\s*(-?\d+)\s*(?:r\s*(-?\d+))?\s*$')


def grade_column_operation(question, text_answer: str) -> bool:
    """Is *text_answer* the result of *question*'s stacked sum?

    Tolerant of surrounding spaces and of leading zeros, so a student who
    starts a column late and submits "06936" is marked on the number they
    wrote. An empty submission is wrong, never zero.
    """
    if question.column_result is None:
        return False
    m = _NUMBER_RE.match((text_answer or '').replace(' ', ''))
    return bool(m) and int(m.group(1)) == question.column_result


def grade_long_division(question, text_answer: str) -> bool:
    """Is *text_answer* the quotient (and remainder) of *question*'s division?

    Accepts "12", "12 r 0", "12r0" and "12 R 0" as the same answer: a division
    that comes out exactly is right whether or not the student wrote "r 0".
    """
    if question.dividend is None or not question.divisor:
        return False
    quotient, remainder = divmod(question.dividend, question.divisor)
    m = _QUOTIENT_RE.match((text_answer or '').strip().lower())
    if not m:
        return False
    got_quotient = int(m.group(1))
    got_remainder = int(m.group(2)) if m.group(2) is not None else 0
    return got_quotient == quotient and got_remainder == remainder


def self_graded_answer_text(question) -> str:
    """The computed answer as it should be SHOWN, or '' if not this kind.

    A student who gets one of these wrong has nothing to learn from a bare ❌:
    there is no Answer row behind it, so ``correct_answer_display()`` had
    nothing to print.
    """
    from maths.models import Question

    if question.question_type == Question.COLUMN_OPERATION:
        result = question.column_result
        return '' if result is None else str(result)
    if question.question_type == Question.LONG_DIVISION:
        if question.dividend is None or not question.divisor:
            return ''
        quotient, remainder = divmod(question.dividend, question.divisor)
        return str(quotient) if remainder == 0 else f'{quotient} r {remainder}'
    return ''


def grade_self_graded_arithmetic(question, text_answer):
    """Grade *question* from its own numbers, or ``None`` if it has none.

    ``None`` means "not one of these, or not carrying the numbers to work its
    answer out" — the caller then grades it the ordinary way, against its
    Answer rows, exactly as it did before.
    """
    from maths.models import Question

    if question.question_type == Question.COLUMN_OPERATION:
        if question.column_result is None:
            return None
        return grade_column_operation(question, text_answer)
    if question.question_type == Question.LONG_DIVISION:
        if question.dividend is None or not question.divisor:
            return None
        return grade_long_division(question, text_answer)
    return None
