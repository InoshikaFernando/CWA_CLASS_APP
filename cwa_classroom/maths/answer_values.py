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

# Units and currency words are stripped before parsing so that '3 kg' and
# '9/3 kg' compare as the same number.
#
# The unit is NOT discarded, though — parse_answer_unit reads it separately and
# callers compare (value, unit) pairs. Stripping it outright made '4 kg' and
# '4 g' look identical, so an estimation question ("The mass of a pet cat would
# most likely be about: 4 t / 4 kg / 400 g / 4 g") was reported as having a
# distractor equal to its answer. In that question the unit is the ENTIRE point:
# the numbers are deliberately the same so the student has to think about scale.
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



# Synonyms folded onto one token so 'kg' and 'kilograms' compare equal. Only
# spellings of the SAME unit belong here — never two units that merely relate
# to each other, or 'g' and 'kg' would collapse and take the false positive
# with them.
_UNIT_SYNONYMS = {
    'litres': 'l', 'litre': 'l', 'liters': 'l', 'liter': 'l',
    'metres': 'm', 'metre': 'm', 'meters': 'm', 'meter': 'm',
    'grams': 'g', 'gram': 'g',
    'kilograms': 'kg', 'kilogram': 'kg',
    'hrs': 'hour', 'hr': 'hour', 'hours': 'hour',
    'mins': 'minute', 'min': 'minute', 'minutes': 'minute',
    'secs': 'second', 'sec': 'second', 'seconds': 'second',
    'days': 'day', 'weeks': 'week', 'months': 'month', 'years': 'year',
    'dollars': '$', 'dollar': '$', 'cents': 'cent',
    'teaspoons': 'teaspoon', 'tablespoons': 'tablespoon', 'cups': 'cup',
    'slices': 'slice', 'pieces': 'piece', 'cakes': 'cake',
    'pizzas': 'pizza', 'apples': 'apple', 'units': 'unit',
}


def parse_answer_unit(text):
    """The unit an answer is expressed in, normalised, or '' when there is none.

    Two answers are the same quantity only if they agree on BOTH the number and
    the unit. '4 kg' and '4 g' share a number and are not the same mass.
    """
    if text is None:
        return ''
    s = str(text).strip().lower().replace(',', '')
    found = {_UNIT_SYNONYMS.get(u, u) for u in _UNIT_RE.findall(s)}
    if '$' in s:
        found.add('$')
    # Any trailing letters the table does not know — 't' for tonnes, 'ft', a
    # made-up unit — still count. An unrecognised unit must not silently read
    # as "no unit", which would make it equal to a bare number.
    tail = re.sub(r'[\d\s./+-]', '', s)
    for known in list(found):
        tail = tail.replace(known.replace('$', ''), '')
    tail = tail.replace('$', '').strip()
    if tail:
        found.add(tail)
    return ' '.join(sorted(found))


def parse_answer_quantity(text):
    """``(value, unit)`` for an answer, or ``None`` when there is no number.

    This is the comparable form: callers that ask "are these two options the
    same answer?" must compare quantities, not bare values.
    """
    value = parse_answer_value(text)
    if value is None:
        return None
    return (value, parse_answer_unit(text))


def quantities_match(a, b):
    """Are two ``(value, unit)`` quantities the same answer?

    Equal numbers are necessary but not sufficient — the units have to be
    compatible too:

      '4 kg' vs '4 g'        DIFFERENT. Both units are stated and they differ,
                             which is the whole point of an estimation
                             question ("the mass of a pet cat").

      '3 3/4 teaspoons'      THE SAME. One option states the unit and the other
        vs '15/4'            leaves it implied by the question, which is how
                             production Q6013 mismarked a student who picked
                             the improper fraction.

    So a blank unit is compatible with anything; two different stated units
    never are.
    """
    if a is None or b is None:
        return False
    (value_a, unit_a), (value_b, unit_b) = a, b
    if value_a != value_b:
        return False
    return not unit_a or not unit_b or unit_a == unit_b


def group_by_quantity(items, quantity_of):
    """Group ``items`` into lists that are all the same answer.

    Grouping cannot use the quantity as a dict key, because a blank unit
    matches a stated one without being equal to it. Items join the first group
    they match, so an option carrying no unit lands with the stated-unit group
    it agrees with rather than forming a lookalike group of its own.
    """
    groups = []
    for item in items:
        quantity = quantity_of(item)
        if quantity is None:
            continue
        for group in groups:
            if quantities_match(quantity_of(group[0]), quantity):
                group.append(item)
                break
        else:
            groups.append([item])
    return groups


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

    # Quantities, not bare values: an option only equals the answer when it
    # agrees on the unit too.
    correct_values = [(a, parse_answer_quantity(a.answer_text)) for a in correct]
    correct_values = [(a, v) for a, v in correct_values if v is not None]
    if not correct_values:
        return []

    clashes = []
    for option in options:
        if option.is_correct:
            continue
        value = parse_answer_quantity(option.answer_text)
        if value is None:
            continue
        for correct_answer, correct_value in correct_values:
            if quantities_match(value, correct_value):
                clashes.append((option, correct_answer))
                break
    return clashes
