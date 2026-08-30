"""Fill the gaps of a question from the arithmetic written around them —
the question's own, or a worked answer's.

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

The worked answer
-----------------
:func:`read_worked_answer` is the other half, for the questions whose stored
answer is the question itself with its blanks filled in::

    question:  __ + __ + __ + __ + __ + __ + __ = 63, so ___ x ___ = 63
    answer:     9 +  9 +  9 +  9 +  9 +  9 +  9 = 63,     7 x  9  = 63

Arithmetic alone cannot do these: seven equal addends of 63 is 9 each, but
"___ x ___ = 63" is 7 x 9 or 9 x 7 or 63 x 1, and picking one would be a
guess about what the author wanted. The row settles it — and it is only read
when the two line up symbol for symbol, every printed number against the same
number, so a row that is prose or a partial answer aligns with nothing and is
dropped. That alignment is its own proof; there is nothing else to check it
against.

Pure functions, no Django. The stored-answer check for the arithmetic route
lives with the caller in ``maths.blank_grading``, which already knows how
answers are compared.
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

# A digit touching a letter is an algebraic term, not a number: "18xyz" reads
# as 18, and the "complete the factorisation" questions then line up perfectly
# against their own worked answer and convert with gaps of 6 where the answer
# is 6xyz — a correct child marked wrong, which is the one outcome none of
# this may produce. Numbers here are numbers.
#
# Adjacency only, never across a space: "3 x 6", "7 equal addends" and "6 rows
# of 3" are ordinary arithmetic and prose. A product written closed up ("3x6")
# is refused with the algebra, which costs a question that keeps working and
# buys the rule being obvious.
_ALGEBRAIC_RE = re.compile(r'\d[A-Za-z]|[A-Za-z]\d')

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
    if _ALGEBRAIC_RE.search(text):
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


# --------------------------------------------------------------------------
# A worked answer, aligned against the question it completes
# --------------------------------------------------------------------------
# "x" is multiplication only when it stands alone — never the letter inside a
# word, which would turn "six" into an operator and every sentence into
# arithmetic.
_TOKEN_RE = re.compile(r'_{2,}|\d+(?:\.\d+)?|\+|=|(?<![A-Za-z])[x×*](?![A-Za-z])')

_GAP = 'gap'
_NUMBER_TOKEN = 'number'
_OPERATOR_TOKEN = 'operator'


def _tokens(text):
    """*text* as ``(kind, value, position)`` — gaps, numbers and operators.

    Everything else is skipped, so the prose a question wraps its arithmetic
    in ("so", "and find the product") never has to be matched.
    """
    found = []
    for match in _TOKEN_RE.finditer(text):
        token = match.group()
        if token.startswith('_'):
            found.append((_GAP, None, match.start()))
        elif token[0].isdigit():
            found.append((_NUMBER_TOKEN, Fraction(token), match.start()))
        elif token == '=':
            found.append((_OPERATOR_TOKEN, '=', match.start()))
        else:
            found.append((_OPERATOR_TOKEN, _normalise_operator(token),
                          match.start()))
    return found


def read_worked_answer(question_text, answer_text):
    """``{blank index: value}`` when *answer_text* is *question_text* completed.

    Empty unless the two line up exactly from the question's first gap: the
    same operators in the same order, every printed number matched by the same
    number, and one number in the answer for each gap. At least one operator
    must take part, so a bare "___" answered "5300" is never filled this way —
    with nothing to line up, there is nothing being proved.
    """
    question = str(question_text or '')
    answer = str(answer_text or '')
    if not question or not answer:
        return {}
    if _GLUED_GAP_RE.search(question) or _GROUPED_NUMBER_RE.search(question):
        return {}
    if _GROUPED_NUMBER_RE.search(answer):
        return {}
    if _ALGEBRAIC_RE.search(question) or _ALGEBRAIC_RE.search(answer):
        return {}

    runs = [match.start() for match in _BLANK_RE.finditer(question)]
    if not runs:
        return {}

    asked = _tokens(question)
    # From the first gap: a question may count its own addends in words ("with
    # 7 equal addends: __ + __ …"), and that 7 is not part of the arithmetic
    # the answer writes out.
    first = next((i for i, (kind, _, _) in enumerate(asked) if kind == _GAP), None)
    if first is None:
        return {}
    asked = asked[first:]
    written = _tokens(answer)

    if len(asked) != len(written):
        return {}
    if not any(kind == _OPERATOR_TOKEN for kind, _, _ in asked):
        return {}

    filled = {}
    for (kind, value, position), (other_kind, other_value, _) in zip(asked, written):
        if kind == _GAP:
            if other_kind != _NUMBER_TOKEN:
                return {}
            filled[runs.index(position)] = other_value
        elif kind != other_kind or value != other_value:
            return {}

    return filled if len(filled) == len(runs) else {}
