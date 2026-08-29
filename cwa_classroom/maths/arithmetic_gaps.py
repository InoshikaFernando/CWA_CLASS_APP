"""Fill the gaps of a question that prints its own arithmetic.

The third and last way ``maths.blank_grading.derive_blank_spec`` learns what
goes in a gap. The first reads it off the stored answer rows; the second solves
a printed number pattern (``maths.pattern_grading``); this one solves a printed
sum::

    "Write the sum and then write the product:
     4 + 4 + 4 + 4 + 4 + 4 = ______ and 4 x 6 = ______"      stored answer: 24

Two gaps, one stored answer, and the row rules refuse it — rightly, since one
value cannot say what goes in two places. But nothing here is a guess either:
the addition and the multiplication are both printed, both come to 24, and the
stored answer agrees. So the gaps are filled from the arithmetic, and the
stored answer is what proves the question was read correctly.

That check is the whole safety of this module. A question whose stored answer
matches nothing it computes is NOT converted, because the likeliest reason is
that the arithmetic here was misread — and a gap filled from a misreading marks
a correct child wrong, silently, forever. Refusing costs a question that keeps
working exactly as it does today.

What it reads
-------------
A *statement* is expressions joined by "=", each expression a list of numbers
and gaps joined by ONE operator::

    8 + 8 + 8 = ___ x 8                 two sides: 24, and a gap times 8
    7 x 4 = 4 + 4 + _ + _ + _ + _ + _ = _     three sides

A side with no gaps gives the statement its value; every other side is solved
against it. One gap in a side is arithmetic (24 = gap x 8 makes the gap 3).
Several gaps in one side are only filled under the **equal-terms rule**: when
every printed term of that side is the same number, the gaps are that number
too — and the side must still come to the statement's value, which is what
makes it a deduction rather than a hope.

What it refuses, and why each one matters
-----------------------------------------
* a gap glued to a digit or a decimal point ("= 0.__") — the gap is part of a
  number, not a term of its own; the percentage questions are all this shape
  and would convert to nonsense;
* letters in the arithmetic (the "complete the factorisation" questions), a
  comma inside a number, or two different operators in one side;
* a gap that belongs to no statement, so a question is converted whole or not
  at all;
* sides that disagree with each other, a gap that would have to be divided
  by nothing, several gaps whose printed terms differ — anything where the
  answer would be a guess rather than a deduction.

Pure functions, no Django. The stored-answer check lives with the caller in
``maths.blank_grading``, which already knows how answers are compared.
"""
import re
from fractions import Fraction

# A run of two or more underscores is a gap — the same marker the rest of the
# fill-in-the-blank code uses (blank_grading.BLANK_RE, kept separate so this
# module stays importable from there without a cycle).
_BLANK_RE = re.compile(r'_{2,}')

_NUMBER = r'\d+(?:\.\d+)?'
_TERM = rf'(?:{_NUMBER}|_{{2,}})'
_TERM_RE = re.compile(_TERM)
# "x" counts as multiplication only between two terms, which is what keeps it
# out of ordinary words — the regexes below never let a letter start a term.
_OPERATOR = r'[+x*×]'
_SIDE = rf'{_TERM}(?:\s*{_OPERATOR}\s*{_TERM})*'
_STATEMENT_RE = re.compile(rf'{_SIDE}(?:\s*=\s*{_SIDE})+')

# A gap touching a number is part of that number ("0.__" wants the digits after
# the point, "__5" the digits before), not a term of its own. One of these
# anywhere refuses the whole question rather than the statement, because
# whatever such a gap wants, this module cannot be the thing that says so —
# the percentage questions ("__/100 = __ = 0.__") are all this shape.
#
# The decimal point has to be part of a NUMBER to count: a gap that ends a
# sentence ("= ___. What is the total?") is followed by an ordinary full stop,
# and reading that as a decimal refused every question in the family.
_GLUED_GAP_RE = re.compile(r'\d_{2,}|_{2,}\d|\d\._{2,}|_{2,}\.\d')

# "1,000" would read as 1 and 000 — and worse, a statement can start AFTER the
# comma ("1,000 + 1,000 = ___" matching as "000 = ___", filling the gap with
# zero), so this refuses the whole question rather than one statement.
_GROUPED_NUMBER_RE = re.compile(r'\d,\d')

_MULTIPLY = '*'
_ADD = '+'


def _normalise_operator(symbol):
    return _ADD if symbol == '+' else _MULTIPLY


def _sides(statement_text, base):
    """The statement's sides as ``[(terms, operator)]``, or None if unreadable.

    A term is ``(value, index)`` — value None for a gap — where *index* is the
    offset of the term in the whole question text, so a gap can be lined up
    with the "___" runs the sentence is split on.
    """
    sides = []
    cursor = 0
    for part in statement_text.split('='):
        text = part
        start = base + cursor
        cursor += len(part) + 1  # the "=" we split on

        operators = {_normalise_operator(s) for s in re.findall(_OPERATOR, text)}
        if len(operators) > 1:
            return None  # "2 + 3 x 4" — precedence is not this module's job
        operator = operators.pop() if operators else _ADD

        terms = []
        for match in _TERM_RE.finditer(text):
            token = match.group()
            value = None if token.startswith('_') else Fraction(token)
            terms.append((value, start + match.start()))
        if not terms:
            return None
        sides.append((terms, operator))
    return sides if len(sides) > 1 else None


def _value_of(terms, operator):
    """The side's value, or None when any term is a gap."""
    if any(value is None for value, _ in terms):
        return None
    values = [value for value, _ in terms]
    if operator == _ADD:
        return sum(values, Fraction(0))
    product = Fraction(1)
    for value in values:
        product *= value
    return product


def _fill_side(terms, operator, total):
    """What the gaps of one side must be for it to come to *total*.

    ``{index: value}``, or None when that cannot be settled by arithmetic.
    """
    gaps = [index for value, index in terms if value is None]
    known = [value for value, _ in terms if value is not None]
    if not gaps:
        return {}

    if len(gaps) == 1:
        if operator == _ADD:
            return {gaps[0]: total - sum(known, Fraction(0))}
        product = Fraction(1)
        for value in known:
            product *= value
        if product == 0:
            return None
        share = total / product
        return {gaps[0]: share}

    # Several gaps: only the equal-terms rule can settle them, and only when
    # the printed terms agree with each other AND the filled side comes to the
    # total. "4 + 4 + _ + _ + _ + _ + _ = 28" is five more 4s; "3 + 5 + _ + _"
    # is anybody's guess and is refused.
    if not known or any(value != known[0] for value in known):
        return None
    if operator != _ADD:
        return None
    value = known[0]
    if value * (len(known) + len(gaps)) != total:
        return None
    return {index: value for index in gaps}


def read_arithmetic_gaps(question_text):
    """``{blank index: value}`` for a question that prints its own arithmetic.

    Empty when this is not one of those questions, or when anything about it
    would have to be guessed at. The index counts the "___" runs of
    *question_text* from the left, so the caller can line the values up with
    the gaps of the sentence.
    """
    text = str(question_text or '')
    if not text or _GLUED_GAP_RE.search(text) or _GROUPED_NUMBER_RE.search(text):
        return {}

    runs = [match.start() for match in _BLANK_RE.finditer(text)]
    if not runs:
        return {}

    filled = {}
    for statement in _STATEMENT_RE.finditer(text):
        sides = _sides(statement.group(), statement.start())
        if sides is None:
            continue

        values = {_value_of(terms, operator) for terms, operator in sides}
        values.discard(None)
        if len(values) != 1:
            # No side is fully known, or two of them disagree — either way
            # there is nothing to solve the gaps against.
            continue
        total = values.pop()

        for terms, operator in sides:
            solved = _fill_side(terms, operator, total)
            if solved is None:
                return {}
            filled.update(solved)

    if not filled:
        return {}

    # Whole or not at all: a question with a gap this cannot account for is
    # left alone, rather than converted with one blank filled from nowhere.
    by_blank = {}
    for index, value in filled.items():
        if index not in runs:
            return {}
        by_blank[runs.index(index)] = value
    if len(by_blank) != len(runs):
        return {}
    return by_blank
