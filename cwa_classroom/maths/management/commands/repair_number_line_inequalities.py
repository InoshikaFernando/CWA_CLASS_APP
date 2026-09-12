"""Rebuild the answer key of a number-line INEQUALITY graph from the inequality
the question states, instead of the ticks someone spelled out.

The report: a student met

    Q10  Draw a graph for the inequality k <= -2.   marked -7 -6 -5 -4 -3 -2
    Q11  Draw a graph for the inequality m > 1.     marked 2 3 4 5 6 7

Both answers are right. Both were marked wrong. Nothing was wrong with the
grader — ``grade_number_line`` compares the marked set against the spec's
target set, and it does that correctly. What was wrong was the target set: a
"draw the graph" answer is a RAY, and whoever (or whatever) turned the ray into
a list of ticks stopped one tick early, so the closed boundary of the ``<=``
(-2) and the line's own end tick on the ``>`` (7) were missing from the key. The
student's correct mark on the boundary then read as an extra mark.

THE REPAIR IS TO STOP ENUMERATING. A spec can now say

    "inequality": {"op": "<=", "value": -2}

and ``number_line_targets`` derives the ticks from the line's own tick list
every time they are needed (see maths.geometry_grading). An inequality block
cannot drop a boundary, so the question is right by construction from here on.

This command converts the questions already in the bank: it reads the
inequality off the question text, checks it against the stored ticks, and
rewrites the spec to state the inequality. Questions whose stored target ALREADY
matches the inequality are converted too — they grade correctly today, but only
by luck of a correct enumeration, and the block is what keeps them correct.

REFUSES TO GUESS. A question whose text states no inequality, or states more
than one (a compound "1 < x <= 4"), is reported and left alone — the spec's own
target set is the only answer key anyone recorded for it, and replacing that on
a guess would swap a question that grades correctly for one that does not.

DRY-RUN BY DEFAULT. Pass --apply to write. Idempotent: a converted spec still
matches, and the rewrite is byte-identical, so a second run reports it as
already correct and writes nothing.

    python manage.py repair_number_line_inequalities
    python manage.py repair_number_line_inequalities --question 9710
    python manage.py repair_number_line_inequalities --apply
"""
from django.core.management.base import BaseCommand, CommandError

from maths.geometry_grading import (
    inequality_ticks,
    number_line_ticks,
    number_line_targets,
    parse_inequality_text,
    spec_inequality,
    validate_number_line_spec,
    _num_key,
)


def inequality_repair(question):
    """What this question needs, as ``(status, detail)``.

    ``status`` is one of:
      ``'no_inequality'``  the text states none (or more than one) — leave alone.
      ``'unusable'``       the inequality matches no tick on the drawn line.
      ``'converted'``      already stating its inequality, key matches — no-op.
      ``'wrong_key'``      stored target disagrees with the inequality — REPAIR,
                           and the stored key is marking correct answers wrong.
      ``'enumerated'``     key agrees but is spelled out — REPAIR (pin it down).
    ``detail`` carries ``(op, value, derived_ticks, stored_targets)`` for every
    status that has an inequality to report, else ``None``.
    """
    spec = question.number_line_spec or {}
    if (spec.get('mode') or 'mark') != 'mark':
        return 'no_inequality', None
    stated = parse_inequality_text(question.question_text)
    if stated is None:
        return 'no_inequality', None
    op, value = stated
    ticks = number_line_ticks(spec) or []
    derived = inequality_ticks(op, value, ticks)
    if not derived:
        # The inequality is satisfied by nothing the line draws (a scale that
        # does not reach the boundary). Surfaced, never "repaired" to an empty
        # answer key — the line itself is wrong and a person has to widen it.
        return 'unusable', (op, value, derived, list(number_line_targets(spec)))
    stored = list(number_line_targets(spec))
    same_key = {_num_key(v) for v in stored} == {_num_key(v) for v in derived}
    if spec_inequality(spec) is not None:
        return ('converted' if same_key else 'wrong_key',
                (op, value, derived, stored))
    return ('enumerated' if same_key else 'wrong_key',
            (op, value, derived, stored))


def repaired_spec(spec, op, value):
    """A copy of ``spec`` stating the inequality, with the ticks derived from it.

    ``target`` is kept in step rather than dropped: it is what an export, an
    older release, or a teacher reading the JSON sees, and leaving a stale list
    behind would be exactly the drift this repair exists to end.
    """
    out = dict(spec)
    out['inequality'] = {'op': op, 'value': value}
    out['target'] = inequality_ticks(op, value, number_line_ticks(spec) or [])
    return out


class Command(BaseCommand):
    help = ("Derive a number-line inequality graph's answer key from the "
            "inequality the question states, instead of a spelled-out tick list.")

    def add_arguments(self, parser):
        parser.add_argument('--question', type=int, default=None,
                            help='Repair just this question id.')
        parser.add_argument('--apply', action='store_true',
                            help='Write the change (default is a dry run).')

    def handle(self, *args, **options):
        from maths.models import Question

        qs = Question.objects.filter(
            question_type=Question.NUMBER_LINE,
            number_line_spec__isnull=False,
        ).order_by('id')
        if options['question'] is not None:
            qs = qs.filter(id=options['question'])
            if not qs.exists():
                raise CommandError(
                    f'No number_line question with id {options["question"]}.')

        buckets = {k: [] for k in
                   ('no_inequality', 'unusable', 'converted', 'wrong_key', 'enumerated')}
        repaired, failed = 0, 0

        for question in qs:
            status, detail = inequality_repair(question)
            buckets[status].append((question, detail))
            if status not in ('wrong_key', 'enumerated'):
                continue
            op, value, derived, stored = detail
            flag = self.style.ERROR('MARKS CORRECT ANSWERS WRONG') if status == 'wrong_key' else 'enumerated'
            self.stdout.write(
                f'Q{question.id}: "{question.question_text.strip()[:70]}" [{flag}]\n'
                f'    inequality  {op} {value}\n'
                f'    stored key  {sorted(_num_key(v) for v in stored)}\n'
                f'    correct key {derived}'
            )
            if not options['apply']:
                continue
            spec = repaired_spec(question.number_line_spec, op, value)
            try:
                validate_number_line_spec(spec)
            except ValueError as exc:
                # Never write a spec the app would then refuse to render or
                # grade — report it and move on, loudly.
                failed += 1
                self.stderr.write(self.style.ERROR(
                    f'    NOT WRITTEN — the repaired spec is invalid: {exc}'))
                continue
            question.number_line_spec = spec
            question.save(update_fields=['number_line_spec'])
            repaired += 1
            self.stdout.write(self.style.SUCCESS('    repaired'))

        for question, detail in buckets['unusable']:
            op, value, _derived, stored = detail
            self.stderr.write(self.style.WARNING(
                f'Q{question.id}: "{question.question_text.strip()[:70]}"\n'
                f'    states {op} {value}, which no tick on its line satisfies. '
                f'The scale is wrong, not the key — left alone (stored key '
                f'{sorted(_num_key(v) for v in stored)}).'))

        needing = len(buckets['wrong_key']) + len(buckets['enumerated'])
        self.stdout.write('')
        self.stdout.write(
            f'{qs.count()} number-line question(s): '
            f'{len(buckets["wrong_key"])} with a key that contradicts the '
            f'inequality, {len(buckets["enumerated"])} spelled out but correct, '
            f'{len(buckets["converted"])} already stating their inequality, '
            f'{len(buckets["unusable"])} unusable, '
            f'{len(buckets["no_inequality"])} not inequality graphs.')
        if failed:
            self.stderr.write(self.style.ERROR(
                f'{failed} question(s) could not be repaired — see above.'))
        if needing and not options['apply']:
            self.stdout.write(self.style.WARNING(
                f'Dry run — nothing written. Re-run with --apply to repair '
                f'{needing} question(s).'))
        elif options['apply']:
            self.stdout.write(self.style.SUCCESS(f'{repaired} question(s) repaired.'))
