"""Restore the missing premise on a question that asks for an unknown but
gives nothing to work it out from (CPP-406).

The report: a Year 7 student opened homework 220 and met, in full,

    The value of x is:        A) -3   B) 3   C) -7   D) 7

There is no equation and no figure. The question is unanswerable, and no check
in the bank was looking for it — every existing check is about the answer
OPTIONS, and this question's options are fine.

ONE QUESTION AT A TIME, ON PURPOSE
----------------------------------
A bank scan finds a handful of these, and they do NOT all want the same repair.
"Two straight lines intersect. Find the value of x." is missing a DIAGRAM;
"The table represents a probability distribution. Solve for k." is missing a
TABLE. Prepending an equation to either would replace an unanswerable question
with a wrong one. Only a person reading the stem can say which premise is
missing, so this command refuses to sweep: it takes one --question and reports
the rest for a human to look at.

TWO WAYS TO SUPPLY THE PREMISE
------------------------------
--equation "x + 7 = 4"   The real equation, read off the source worksheet.
                         Always prefer this: it is the question the author
                         actually set, and its distractors were designed
                         around it.

--generate               Build a linear equation from the stored answer key
                         when the original is not to hand. The constant is
                         taken from the distractors where possible, so the
                         wrong options stay plausible slips rather than
                         becoming arbitrary numbers.

EITHER WAY THE EQUATION IS VERIFIED against the option already flagged
correct, and the command refuses on any mismatch. That guard is the whole
point: a question that is obviously broken is safer than one that looks fine
and marks children wrong.

DRY-RUN BY DEFAULT. Pass --apply to write. Idempotent: once the text carries an
equation it no longer matches, so a second run is a no-op.

    python manage.py repair_missing_premise --list
    python manage.py repair_missing_premise --question 9479 --generate
    python manage.py repair_missing_premise --question 9479 --equation "x + 7 = 4" --apply
"""
import re
from fractions import Fraction

from django.core.management.base import BaseCommand, CommandError

# The stem asks for the value of a named unknown.
ASKS_FOR_UNKNOWN_RE = re.compile(
    r'\b(?:value|values|solution)\s+of\s+([a-zA-Z])\b'
    r'|\bsolve\s+for\s+([a-zA-Z])\b',
    re.IGNORECASE,
)

# Imported content is full of typographic dashes: the answer key on the
# reported question is '–3' (EN DASH), not '-3'. Fraction() and
# maths.answer_values.parse_answer_value both read that as "not a number", so
# every dash has to be folded to ASCII before anything is parsed.
DASHES = {'‐': '-', '‑': '-', '‒': '-', '–': '-',
          '—': '-', '―': '-', '−': '-'}

# a*x + b = c, the only shape this command reads. Anything richer — brackets,
# an unknown on both sides, a fraction — is reported and left to a person
# rather than half-parsed.
LINEAR_RE = re.compile(
    r'^\s*(?P<a>[+-]?\d*)\s*(?P<var>[a-zA-Z])\s*'
    r'(?:(?P<sign>[+-])\s*(?P<b>\d+)\s*)?'
    r'=\s*(?P<c>[+-]?\d+)\s*$'
)


def fold_dashes(text):
    """Every flavour of dash in ``text`` as an ASCII hyphen."""
    return ''.join(DASHES.get(ch, ch) for ch in str(text or ''))


def as_number(text):
    """The integer an option denotes, or None. Dash-tolerant."""
    cleaned = fold_dashes(text).strip().replace(' ', '')
    try:
        return Fraction(cleaned)
    except (ValueError, ZeroDivisionError):
        return None


def missing_premise(question):
    """Does this stem ask for an unknown it never defines?

    True only when the text offers NOTHING to work the unknown out from: no
    equation, no number, no second mention of the unknown, and no image. A
    stem that carries any of those is answerable (or broken in some other way
    this command must not touch).
    """
    text = fold_dashes(question.question_text).strip()
    match = ASKS_FOR_UNKNOWN_RE.search(text)
    if not match or question.image:
        return False
    if '=' in text or any(ch.isdigit() for ch in text):
        return False
    unknown = next(g for g in match.groups() if g)
    rest = text[:match.start()] + text[match.end():]
    return not re.search(rf'\b{re.escape(unknown)}\b', rest, re.IGNORECASE)


# Words that carry no premise of their own. What is left after these and the
# ask itself are removed is the question's actual CONTEXT — and a stem that has
# any is describing something (a pair of intersecting lines, a probability
# table) that an equation cannot stand in for.
_FILLER = {
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'this', 'these', 'it',
    'find', 'state', 'give', 'write', 'down', 'work', 'out', 'what',
    'calculate', 'determine', 'solve', 'for', 'value', 'values', 'of',
    'solution', 'below', 'following', 'above', 'in', 'to', 'and', 'then',
}


def stem_is_bare(question):
    """Is the stem nothing but the ask?

    ``The value of x is:`` is bare — an equation is the only thing that can be
    missing. ``Two straight lines intersect. Find the value of x.`` is not: it
    describes a figure, and prepending an equation there would replace an
    unanswerable question with a wrong one. Used to stop --generate reaching
    the questions it must not touch.
    """
    text = fold_dashes(question.question_text or '')
    match = ASKS_FOR_UNKNOWN_RE.search(text)
    if not match:
        return False
    rest = text[:match.start()] + text[match.end():]
    words = re.findall(r'[a-zA-Z]+', rest)
    return not [w for w in words if w.lower() not in _FILLER]


def unknown_in(question):
    """The letter the stem asks for."""
    match = ASKS_FOR_UNKNOWN_RE.search(fold_dashes(question.question_text))
    return next(g for g in match.groups() if g) if match else None


def solve_linear(equation, unknown):
    """The exact value ``equation`` gives for ``unknown``, or None.

    None means "this command cannot read it" — never "it has no solution".
    """
    match = LINEAR_RE.match(fold_dashes(equation))
    if not match or match.group('var').lower() != unknown.lower():
        return None
    raw_a = match.group('a')
    a = Fraction(-1) if raw_a == '-' else Fraction(raw_a or 1)
    if a == 0:
        return None
    b = Fraction(match.group('b') or 0)
    if match.group('sign') == '-':
        b = -b
    return (Fraction(match.group('c')) - b) / a


def render_linear(unknown, a, b, c):
    """``a*x + b = c`` written the way a worksheet writes it."""
    if a == 1:
        lhs = str(unknown)
    elif a == -1:
        lhs = f'-{unknown}'
    else:
        lhs = f'{a}{unknown}'
    if b:
        lhs += f' {"+" if b > 0 else "-"} {abs(b)}'
    return f'{lhs} = {c}'


def generate_equation(question, unknown, answer):
    """A linear equation whose solution is exactly ``answer``.

    The constant is borrowed from a DISTRACTOR wherever one is usable, so the
    wrong options keep meaning something: on the reported question the options
    are -3 (correct), 3, -7, 7, and taking 7 as the constant rebuilds
    ``x + 7 = 4`` — where 3 is the sign slip and ±7 are the constant grabbed
    off the page. Falling back to an arbitrary coefficient would leave three
    distractors that correspond to no mistake anyone would make.
    """
    distractors = [
        abs(value) for value in (
            as_number(a.answer_text) for a in question.answers.all()
            if not a.is_correct)
        if value is not None and value != 0
    ]
    for candidate in sorted(set(distractors), reverse=True):
        if candidate != abs(answer):
            return 1, candidate, answer + candidate
    # Nothing usable in the options — a deterministic pair, so the same
    # question always yields the same equation on a re-run.
    a = 2 + (question.id % 4)
    b = 1 + (question.id % 9)
    return a, b, a * answer + b


class Command(BaseCommand):
    help = 'Restore the missing equation on a question that asks for an unknown.'

    def add_arguments(self, parser):
        parser.add_argument('--question', type=int, default=None,
                            help='The question id to repair.')
        parser.add_argument('--equation', default=None,
                            help='The real equation, e.g. "x + 7 = 4".')
        parser.add_argument('--generate', action='store_true',
                            help='Derive an equation from the stored answer key.')
        parser.add_argument('--list', action='store_true',
                            help='Report every question with a missing premise.')
        parser.add_argument('--apply', action='store_true',
                            help='Write the change (default is a dry run).')

    def handle(self, *args, **options):
        from maths.models import Question

        if options['list'] or options['question'] is None:
            return self._list(Question)

        question = Question.objects.filter(id=options['question']).first()
        if question is None:
            raise CommandError(f'No question with id {options["question"]}.')
        if not missing_premise(question):
            raise CommandError(
                f'Q{question.id} does not have a missing premise — its stem is '
                f'{question.question_text!r}. Refusing to edit a question this '
                f'command was not asked to understand.')

        unknown = unknown_in(question)
        correct = [a for a in question.answers.all() if a.is_correct]
        if len(correct) != 1:
            raise CommandError(
                f'Q{question.id} has {len(correct)} options flagged correct; '
                f'an equation can only be checked against exactly one.')
        answer = as_number(correct[0].answer_text)
        if answer is None or answer.denominator != 1:
            raise CommandError(
                f'Q{question.id}: the correct answer '
                f'{correct[0].answer_text!r} is not a whole number, so a '
                f'linear equation cannot be built for it by hand-free means. '
                f'Supply the real one with --equation.')

        if options['equation']:
            equation = options['equation'].strip()
            solved = solve_linear(equation, unknown)
            if solved is None:
                raise CommandError(
                    f'Cannot read {equation!r} as "a{unknown} + b = c". This '
                    f'command only handles that shape — edit the question in '
                    f'the admin instead.')
            if solved != answer:
                raise CommandError(
                    f'{equation!r} gives {unknown} = {solved}, but the option '
                    f'flagged correct is {correct[0].answer_text!r} '
                    f'({answer}). Refusing to write a question whose equation '
                    f'and answer key disagree.')
        elif options['generate']:
            if not stem_is_bare(question):
                raise CommandError(
                    f'Q{question.id} is not a bare stem — it reads '
                    f'{question.question_text!r}. That sentence describes '
                    f'something the student is meant to SEE (a diagram, a '
                    f'table), and an equation cannot stand in for it. Attach '
                    f'the figure, or pass the real equation with --equation.')
            a, b, c = generate_equation(question, unknown, answer)
            equation = render_linear(unknown, a, b, c)
            assert solve_linear(equation, unknown) == answer
        else:
            raise CommandError(
                'Pass --equation "…" with the real equation, or --generate to '
                'build one from the answer key.')

        new_text = f'{equation}\n\n{question.question_text}'

        self.stdout.write(f'Q{question.id}  [{question.level} / {question.topic}]')
        self.stdout.write(f'  was : {question.question_text!r}')
        self.stdout.write(f'  now : {new_text!r}')
        self.stdout.write(f'  {unknown} = {answer}, matching the option '
                          f'{correct[0].answer_text!r}')
        for option in question.answers.all().order_by('order'):
            mark = 'correct' if option.is_correct else '       '
            self.stdout.write(f'    {mark}  {option.answer_text!r}')

        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                '  DRY RUN — nothing written. Re-run with --apply.'))
            return

        question.question_text = new_text
        question.save(update_fields=['question_text'])
        self.stdout.write(self.style.SUCCESS(f'  Q{question.id} updated.'))

    def _list(self, Question):
        """Report the candidates, saying which ones this command cannot fix."""
        rows = [q for q in Question.objects.prefetch_related('answers')
                .iterator(chunk_size=500) if missing_premise(q)]
        if not rows:
            self.stdout.write('No question has a missing premise.')
            return
        self.stdout.write(f'{len(rows)} question(s) asking for an undefined '
                          f'unknown:\n')
        for q in rows:
            correct = [a for a in q.answers.all() if a.is_correct]
            value = as_number(correct[0].answer_text) if len(correct) == 1 else None
            fixable = value is not None and value.denominator == 1
            note = ('' if fixable else
                    '  <-- no single whole-number answer; needs a person')
            self.stdout.write(
                f'  Q{q.id:<7} {q.question_type:<16} '
                f'{(q.question_text or "")[:56]!r}{note}')
        self.stdout.write(
            '\nRead each stem before repairing it. A question missing a '
            'DIAGRAM or a TABLE\nwill appear here too, and an equation is the '
            'wrong repair for those.')
