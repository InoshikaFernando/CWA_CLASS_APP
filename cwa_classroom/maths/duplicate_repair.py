"""Repair multiple-choice questions that offer the same answer twice (CPP-377).

Four faults, one repair. In each, the offending copy is REPLACED with a freshly
generated value rather than deleted, so the question keeps the number of
choices it was written with:

  DUPLICATE-CORRECT  the correct answer also appears as an unselected option.
                     A student who picks that copy is marked wrong for a right
                     answer. The unselected copy is replaced.

  DUPLICATE-OPTION   a wrong option appears twice. Nobody is mismarked, but the
                     question offers fewer real choices than it appears to. The
                     second copy is replaced.

  EQUIVALENT-OPTION  a distractor is a different way of writing the correct
                     answer — '6/10' against a correct '3/5'. A student who
                     picks it is marked wrong for a right answer, so this is
                     the CPP-377 defect in its purest form. The distractor is
                     replaced; the correct option is never touched.

  DUPLICATE-VALUE    two distractors are the same number written differently.
                     Nobody is mismarked, but the question offers fewer real
                     choices than it appears to. The second is replaced.

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

from .answer_values import (
    group_by_quantity, parse_answer_quantity, parse_answer_unit,
    parse_answer_value, quantities_match)

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

    # Pass 2 groups on QUANTITY, not on the bare number. '4 kg' and '4 g' share
    # a number and are not the same mass — an estimation question offers them
    # on purpose, and rewriting one would destroy the question rather than
    # repair it.
    quantities = dict(zip(options, (parse_answer_quantity(t) for t in texts)))

    edits = []
    taken_values = set(values)
    taken_texts = list(texts)
    replaced = set()

    def replace(option):
        value, text = suggest_replacement(
            by_option[option], taken_values, taken_texts, integral)
        edits.append((option, option.answer_text, text))
        taken_values.add(value)
        taken_texts.append(text)
        replaced.add(id(option))

    def collapse(groups):
        for group in groups.values():
            if len(group) < 2:
                continue
            # Keep the correct copy where there is one; otherwise keep the
            # first. Keeping the correct one matters: replacing it would
            # rewrite the answer key.
            keep = next((o for o in group if o.is_correct), group[0])
            for option in group:
                if option is not keep and id(option) not in replaced:
                    replace(option)

    # Pass 1 — LITERAL repeats: the same text listed twice.
    by_text = {}
    for option, text in zip(options, texts):
        by_text.setdefault(text.lower(), []).append(option)
    collapse(by_text)

    # Pass 2 — options that merely share a VALUE: '6/10' alongside '3/5',
    # '0.5' alongside '1/2'. Two different-looking options, one number.
    #
    # This was originally treated as "a different fault with a different fix"
    # and left alone, which meant the bulk fixer answered "nothing to change"
    # on exactly the defect this whole dashboard was built for: a distractor
    # numerically equal to the correct answer marks a student wrong for a
    # right answer (CPP-377). The repair is identical — replace the copy the
    # grader does NOT accept — so there is no reason to withhold it.
    #
    # Runs after the text pass so an option already rewritten above is not
    # rewritten twice, and so its replacement value (already in taken_values)
    # cannot collide here.
    remaining = [o for o in options if id(o) not in replaced]
    collapse({index: group for index, group in enumerate(
        group_by_quantity(remaining, quantities.get))})

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


def plan_trim(question, options=None, target=4):
    """Return the options to DELETE so the question keeps ``target`` choices.

    The correct option always survives. Surplus distractors are dropped from
    the end of the display order, which is predictable and explainable — a
    reviewer can see which four will remain before applying it.

    No attempt is made to judge which distractors are "best": that is a content
    decision. A question whose distractors are wrong in an interesting way
    (mismatched units, say, so the answer is guessable without doing the maths)
    still needs a human, and silently picking for them would hide that.
    """
    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    if len(options) <= target:
        return []

    correct = [o for o in options if o.is_correct]
    if len(correct) != 1:
        # Two correct options is MULTI-CORRECT — a different fault, and
        # choosing which to drop would be choosing the answer.
        raise Skipped('needs exactly one correct option')

    keeper = correct[0]
    distractors = [o for o in options if o is not keeper]
    keep_distractors = distractors[:max(0, target - 1)]
    keep = {id(keeper), *(id(o) for o in keep_distractors)}
    return [o for o in options if id(o) not in keep]


def plan_answer_fill(question, options=None):
    """Return ``('flag', answer)`` or ``('add', text)`` to supply a missing
    correct answer, or ``None`` when there is nothing to do.

    NO-CORRECT is the most damaging fault in the bank: every student answering
    the question is marked wrong, whatever they type or pick. Until now it was
    also the one fault with no repair at all — the check page could report it
    and nothing more.

    WHY THIS IS SAFE, WHERE GENERATING A DISTRACTOR WOULD NOT BE

    Everywhere else in this module the rule is that we never have to know what
    is mathematically true, only what differs from the stored answer. Here we
    DO assert the truth — so it is restricted to the one case where the truth
    is computable and already trusted: an arithmetic expression evaluated by
    the same code that reports a stored answer key as WRONG-ANSWER-KEY. If that
    evaluation is trusted enough to contradict a human's answer, it is trusted
    enough to supply a missing one.

    Anything the evaluator will not commit to — a word problem, algebra, a
    question with a diagram — is refused and left for a human.
    """
    from .answer_verification import evaluate_expression, extract_expression

    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    if any(o.is_correct for o in options):
        return None                      # already answerable

    expression = extract_expression(question.question_text)
    if expression is None:
        raise Skipped('question text is not a plain arithmetic expression')
    value = evaluate_expression(expression)
    if value is None:
        raise Skipped(f'could not evaluate {expression!r}')

    # An existing option that already holds the right value is the answer the
    # question was written with — flag it rather than adding a second copy,
    # which would leave the correct answer listed twice (CPP-377 again).
    for option in options:
        if quantities_match(parse_answer_quantity(option.answer_text),
                            (value, parse_answer_unit(option.answer_text))):
            return ('flag', option)

    texts = [(o.answer_text or '').strip() for o in options]
    return ('add', _format_like(value, texts, _is_integral([value])))


def plan_answer_key(question, options=None):
    """Return ``(to_flag, to_unflag)`` to leave exactly one correct option.

    Repairs two faults that are the same mistake seen from different sides:

      MULTI-CORRECT      several options flagged correct. Single-select grading
                         accepts ANY of them, so a wrong answer is marked
                         RIGHT — the mirror image of CPP-377.

      WRONG-ANSWER-KEY   the flagged option is not what the arithmetic gives,
                         so the right answer is marked wrong.

    Both need the same thing: know which option is actually correct. So this is
    confined, like plan_answer_fill, to arithmetic the evaluator will commit
    to — and refuses when the answer is a judgement call. "What is 666 in
    expanded form?" flagging both '6x100 + 6x10 + 6' and '600+70+6' is a real
    fault, but choosing between them is choosing the answer.
    """
    from .answer_verification import evaluate_expression, extract_expression

    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    correct = [o for o in options if o.is_correct]

    expression = extract_expression(question.question_text)
    if expression is None:
        raise Skipped('question text is not a plain arithmetic expression')
    value = evaluate_expression(expression)
    if value is None:
        raise Skipped(f'could not evaluate {expression!r}')

    matches = [o for o in options
               if quantities_match(parse_answer_quantity(o.answer_text),
                                   (value, parse_answer_unit(o.answer_text)))]
    if not matches:
        raise Skipped(f'no option equals {value} — the answer is missing, '
                      f'not merely mis-flagged')
    if len(matches) > 1:
        raise Skipped(f'{len(matches)} options equal {value} — the duplicate '
                      f'has to go first')

    keep = matches[0]
    to_unflag = [o for o in correct if o.id != keep.id]
    to_flag = [] if keep.is_correct else [keep]
    if not to_flag and not to_unflag:
        return ([], [])
    return (to_flag, to_unflag)


def plan_blank_removal(question, options=None):
    """Return the blank answer rows to delete.

    A row with no text is not an answer anyone can pick or type. Deleting it is
    safe EXCEPT when it is the only row flagged correct — that would leave the
    question unanswerable, so it is refused and left for a human.
    """
    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    blanks = [o for o in options if not (o.answer_text or '').strip()]
    if not blanks:
        return []

    remaining = [o for o in options if o not in blanks]
    if not any(o.is_correct for o in remaining):
        raise Skipped('the only correct option is blank — deleting it would '
                      'leave nothing to answer')
    return blanks


def plan_duplicate_removal(question, options=None, min_remaining=2):
    """Return the option rows to DELETE so each answer is offered once.

    The fallback for every duplicate fault when :func:`plan_repair` refuses.
    ``plan_repair`` REPLACES a repeated option with a freshly generated value,
    which keeps the question's option count but only works when every option
    reads as a single number. Most of the bank's options are words, so on those
    the reviewer got "options are not all single numbers" and no way forward.

    Deleting the repeat needs no generator and so works on any answer text. It
    costs the question one choice, which is why it is the SECOND fix offered
    rather than the first — but a three-option question is a working question,
    and one that lists the same answer twice is not.

    The correct copy is always the survivor: deleting it would rewrite the
    answer key. Refused when it would leave fewer than ``min_remaining``
    options, because a question nobody can choose from is not a repair.
    """
    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    texts = [(o.answer_text or '').strip() for o in options]
    quantities = dict(zip(options, (parse_answer_quantity(t) for t in texts)))

    doomed = []

    def collapse(group):
        if len(group) < 2:
            return
        # Prefer the correct copy, then the earliest — a stable choice a
        # reviewer can predict before applying it.
        keep = next((o for o in group if o.is_correct), group[0])
        doomed.extend(o for o in group if o is not keep)

    # Pass 1 — the same text listed twice. Blank rows are excluded: they are
    # BLANK-OPTION's fault and drop_blank_options' job, and folding them in
    # here would delete them under a label that does not say so.
    by_text = {}
    for option, text in zip(options, texts):
        if text:
            by_text.setdefault(text.lower(), []).append(option)
    for group in by_text.values():
        collapse(group)

    # Pass 2 — one number, two spellings ('6/10' beside '3/5'). Options that
    # are not readable as a quantity are skipped by group_by_quantity, so two
    # unrelated words never land in the same group.
    remaining = [o for o in options
                 if o not in doomed and (o.answer_text or '').strip()]
    for group in group_by_quantity(remaining, quantities.get):
        collapse(group)

    if not doomed:
        return []
    if len(options) - len(doomed) < min_remaining:
        raise Skipped(
            f'deleting the repeats would leave '
            f'{len(options) - len(doomed)} option(s) — too few to choose from')
    return doomed


def plan_chosen_answer_key(question, chosen_id, options=None):
    """Return ``(to_flag, to_unflag)`` for the option a reviewer PICKED.

    The escape hatch for every answer-key fault the arithmetic cannot settle.
    ``plan_answer_key`` can only act where the question's own maths decides the
    answer; on "What is 666 in expanded form?" — two options flagged correct,
    neither computable — it refuses, and rightly so, because choosing between
    them is choosing the answer.

    So the reviewer chooses, and this applies it. No inference happens here at
    all: the judgement is a human's, and this only does the bookkeeping that
    leaves exactly one option flagged. That keeps the safety rule intact (the
    module never invents an answer) while still giving the fault a fix.

    Raises :class:`Skipped` when the pick is not an option on this question, or
    is blank — a blank answer key marks every student wrong.
    """
    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    keep = next((o for o in options if o.id == chosen_id), None)
    if keep is None:
        raise Skipped('no answer was picked for this question')
    if not (keep.answer_text or '').strip():
        raise Skipped('the option picked is blank — it cannot be the answer')

    to_unflag = [o for o in options if o.is_correct and o.id != keep.id]
    to_flag = [] if keep.is_correct else [keep]
    return (to_flag, to_unflag)


def plan_type_change(question, options=None, to='short_answer'):
    """Check that retyping ``question`` to ``to`` leaves it gradeable.

    Changing a choice question to Short Answer is the universal way out of
    TOO-FEW-OPTIONS: a question with one or two options is not a real multiple
    choice, and when its options are words there is no distractor generator
    that can honestly pad it. Typed grading needs no distractors at all.

    What it DOES need is a correct answer to match against — typed grading
    reads the ``is_correct`` rows and marks everything wrong when there are
    none. Converting an unanswerable question would therefore hide the worse
    fault behind a fixed-looking one, so it is refused.
    """
    options = list(options if options is not None
                   else question.answers.order_by('order', 'id'))
    if question.question_type == to:
        return False
    correct = [o for o in options if (o.answer_text or '').strip() and o.is_correct]
    if not correct:
        raise Skipped('no correct answer is stored — typed grading would mark '
                      'every student wrong; supply the answer first')
    return True


def plan_ai_grading(question, options=None):
    """Check that handing ``question`` to the AI grader is the right move.

    Some questions have no answer key that exact matching can hold. "160 can be
    written as 100 + 60 — write two other ways 160 could be split" has infinitely
    many right answers; "What does area mean?" has as many as there are ways to
    say it. Stored as a plain text answer, every student who answers one well is
    marked wrong, which is the fault this dashboard exists to catch. Handing them
    to the AI grader is the way out.

    It is not free, though, so three kinds are refused rather than converted:

      * **Choice questions** — multiple choice and true/false are graded on
        ``Answer.is_correct`` and already mark every student correctly. There is
        nothing here for a grader to judge.
      * **Questions that already grade themselves** — ``answer_format='pattern'``
        marks the pattern a student invented without spending a token, and the
        same will be true of any later format of that kind.
      * **Questions already handed to a grader** — ``ai_graded`` is a no-op, and
        ``human_graded`` is a teacher's standing decision that this one needs a
        person, which a bulk sweep must not quietly overturn.

    The refusals matter because an AI-graded question is HIDDEN from students
    whose school has not bought the AI grading module
    (``quiz.views.gradable_for``). Converting a question that already grades
    correctly therefore costs those students the question and buys nothing.

    Returns True when the conversion should go ahead, False when it would change
    nothing, and raises ``Skipped`` with the reason when it must not happen.
    """
    from .models import Question

    if question.question_type in (Question.MULTIPLE_CHOICE, Question.TRUE_FALSE):
        raise Skipped(
            'a choice question is already marked correctly from its options — '
            'AI grading would only hide it from schools without the module')

    if question.answer_format == Question.ANSWER_FORMAT_PATTERN:
        raise Skipped(
            'this question already grades itself without AI '
            f'(answer_format={question.answer_format!r})')

    if question.validation_type == Question.VALIDATION_HUMAN:
        raise Skipped(
            'a teacher marks this one — change it in the editor if AI grading '
            'should take over')

    if question.validation_type == Question.VALIDATION_AI:
        return False

    return True
