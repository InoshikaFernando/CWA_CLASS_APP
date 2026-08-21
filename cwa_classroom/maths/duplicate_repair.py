"""Repair multiple-choice questions that list the same option twice (CPP-377).

Two faults, one repair. In both the offending copy is REPLACED with a freshly
generated value rather than deleted, so the question keeps the number of
choices it was written with:

  DUPLICATE-CORRECT  the correct answer also appears as an unselected option.
                     A student who picks that copy is marked wrong for a right
                     answer. The unselected copy is replaced.

  DUPLICATE-OPTION   a wrong option appears twice. Nobody is mismarked, but the
                     question offers fewer real choices than it appears to. The
                     second copy is replaced.

WHY GENERATING A REPLACEMENT IS SAFE HERE

The worry with inventing a distractor is inventing the right answer by mistake.
That worry does not apply, because multiple choice is graded purely on
``Answer.is_correct`` (quiz/views.py) — the grader accepts exactly one stored
option. A replacement therefore only has to differ from THAT option, which is
in the data in front of us; we never have to know whether it is mathematically
true. Distinctness from the accepted answer is the whole safety condition, and
it is checkable.

What we refuse to do, rather than guess:

  * touch anything whose options are not all readable as single numbers — the
    replacement style would be a guess, and text distractors carry meaning a
    generator cannot infer;
  * touch a question carrying any OTHER blocking issue — it needs a human, and
    a half-repair would hide that;
  * emit a value equal to any existing option, by number or by text.

Nothing here writes to the database; ``plan_repair`` returns intent, and the
management command decides whether to apply it.
"""
from fractions import Fraction

from .answer_values import parse_answer_value

# Offsets tried in order, relative to the value being replaced. Small
# near-misses first: a distractor a student might plausibly land on beats an
# arbitrary number, which reads as filler and teaches nothing.
_OFFSETS = (1, -1, 2, -2, 3, -3, 5, -5, 10, -10, 4, -4, 20, -20, 100, -100)


class Skipped(Exception):
    """This question is not safely repairable; the reason is the message."""


def _is_integral(values):
    return all(v.denominator == 1 for v in values)


def _decimals(texts):
    """Longest run of decimal places among the option texts, or 0."""
    places = 0
    for text in texts:
        if '.' in text:
            tail = text.split('.', 1)[1]
            digits = ''
            for ch in tail:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            places = max(places, len(digits))
    return places


def _format_like(value, texts, integral):
    """Render ``value`` in the style the other options already use."""
    if integral:
        return str(int(value))
    places = _decimals(texts)
    if places:
        return f'{float(value):.{places}f}'
    if value.denominator != 1:
        return f'{value.numerator}/{value.denominator}'
    return str(int(value))


def _candidates(anchor, integral):
    for offset in _OFFSETS:
        yield anchor + offset
    # Only once the near-misses are exhausted, and only where the options are
    # whole numbers — a doubled or halved fraction rarely reads naturally.
    if integral:
        yield anchor * 2
        if anchor.denominator == 1 and int(anchor) % 2 == 0:
            yield anchor / 2


def suggest_replacement(anchor, taken_values, taken_texts, integral):
    """A value distinct from every option, in their own numeric style.

    ``anchor`` is the value being replaced, so the substitute stays in the same
    neighbourhood and still looks like a plausible mistake.
    """
    for candidate in _candidates(anchor, integral):
        if integral and candidate.denominator != 1:
            continue
        if candidate < 0 and all(v >= 0 for v in taken_values):
            continue          # don't introduce a negative among positives
        if candidate in taken_values:
            continue
        text = _format_like(candidate, taken_texts, integral)
        if text.strip().lower() in {t.strip().lower() for t in taken_texts}:
            continue
        return candidate, text
    raise Skipped('no distinct replacement value found near the duplicate')


def plan_repair(question, options=None):
    """Return ``[(answer, old_text, new_text), ...]`` for one question.

    Raises :class:`Skipped` with a human-readable reason when the question is
    not safely repairable. An empty list means there was nothing to repair.
    """
    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    if len(options) < 3:
        raise Skipped('too few options to replace one safely')

    correct = [o for o in options if o.is_correct]
    if len(correct) != 1:
        raise Skipped('needs exactly one correct option')

    texts = [(o.answer_text or '').strip() for o in options]
    if any(not t for t in texts):
        raise Skipped('has a blank option')

    values = [parse_answer_value(t) for t in texts]
    if any(v is None for v in values):
        raise Skipped('options are not all single numbers')

    integral = _is_integral(values)
    by_option = dict(zip(options, values))

    # Group by normalised text: this repairs LITERAL repeats. Options that
    # merely share a value (3 vs 6/2) are EQUIVALENT-OPTION / DUPLICATE-VALUE
    # and are a different fault with a different fix.
    groups = {}
    for option, text in zip(options, texts):
        groups.setdefault(text.lower(), []).append(option)

    edits = []
    taken_values = set(values)
    taken_texts = list(texts)

    for group in groups.values():
        if len(group) < 2:
            continue
        # Keep the correct copy where there is one; otherwise keep the first.
        keep = next((o for o in group if o.is_correct), group[0])
        for option in group:
            if option is keep:
                continue
            value, text = suggest_replacement(
                by_option[option], taken_values, taken_texts, integral)
            edits.append((option, option.answer_text, text))
            taken_values.add(value)
            taken_texts.append(text)

    return edits


def plan_padding(question, options=None, target=4):
    """Return ``[new_text, ...]`` distractors that bring a question up to
    ``target`` options.

    Same safety condition as :func:`plan_repair`: each generated value must
    differ from the option the grader accepts and from every option already
    present. Used for questions with too few choices to be a real multiple
    choice — the common case being one that was left with a single option.
    """
    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    if not options:
        raise Skipped('has no options to work from')
    if len(options) >= target:
        return []

    correct = [o for o in options if o.is_correct]
    if len(correct) != 1:
        raise Skipped('needs exactly one correct option')

    texts = [(o.answer_text or '').strip() for o in options]
    if any(not t for t in texts):
        raise Skipped('has a blank option')

    values = [parse_answer_value(t) for t in texts]
    if any(v is None for v in values):
        raise Skipped('options are not all single numbers')

    integral = _is_integral(values)
    anchor = parse_answer_value((correct[0].answer_text or '').strip())
    taken_values = set(values)
    taken_texts = list(texts)

    added = []
    while len(taken_texts) < target:
        value, text = suggest_replacement(
            anchor, taken_values, taken_texts, integral)
        added.append(text)
        taken_values.add(value)
        taken_texts.append(text)
    return added
