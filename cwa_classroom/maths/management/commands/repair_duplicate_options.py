"""Replace repeated multiple-choice options with distinct values (CPP-377).

Reports by default and changes nothing. ``--apply`` is required to write, and
every edit is written to the audit log with the text it replaced, so a bad run
can be traced and undone.

Usage
-----
    python manage.py repair_duplicate_options                 # dry run, all
    python manage.py repair_duplicate_options --level 7       # dry run, Year 7
    python manage.py repair_duplicate_options --blocking-only # only mismarks
    python manage.py repair_duplicate_options --apply         # write
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from maths.answer_verification import (
    DUPLICATE_CORRECT, DUPLICATE_OPTION, DUPLICATE_VALUE, EQUIVALENT_OPTION,
    verify_question)
from maths.duplicate_repair import Skipped, plan_repair
from maths.management.commands.verify_question_answers import ADVISORY_CODES

# The faults this command repairs — one option offering the same answer as
# another, whether by identical text or by identical value. Anything else on
# the question means a human should look at it, so we leave the whole question
# alone rather than fixing half of it and making the remaining fault look
# addressed.
REPAIRABLE = {DUPLICATE_CORRECT, DUPLICATE_OPTION,
              EQUIVALENT_OPTION, DUPLICATE_VALUE}

# Faults that can mismark a student, as opposed to merely reading badly. Both
# hand a student a correct-looking option that the grader rejects.
BLOCKING = {DUPLICATE_CORRECT, EQUIVALENT_OPTION}


class Command(BaseCommand):
    help = 'Replace duplicated multiple-choice options with distinct values.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Write the changes. Without it, nothing is saved.')
        parser.add_argument('--level', type=int, help='Restrict to one year level.')
        parser.add_argument('--topic', type=int, help='Restrict to one topic id.')
        parser.add_argument('--limit', type=int,
                            help='Stop after this many repaired questions.')
        parser.add_argument('--blocking-only', action='store_true',
                            help='Only repair DUPLICATE-CORRECT (the mismarks).')

    def handle(self, *args, **options):
        from maths.models import Question

        questions = (Question.objects
                     .filter(question_type='multiple_choice')
                     .prefetch_related('answers')
                     .select_related('level', 'topic')
                     .order_by('id'))
        if options['level']:
            questions = questions.filter(level__level_number=options['level'])
        if options['topic']:
            questions = questions.filter(topic_id=options['topic'])

        repaired = skipped = 0
        skip_reasons = {}
        limit = options['limit']

        for question in questions.iterator(chunk_size=200):
            answers = list(question.answers.all())
            issues, _verified = verify_question(question)
            codes = {i.code for i in issues}

            if not (codes & REPAIRABLE):
                continue
            if options['blocking_only'] and not (codes & BLOCKING):
                continue

            try:
                edits = plan_repair(question, answers)
            except Skipped as exc:
                skipped += 1
                skip_reasons[str(exc)] = skip_reasons.get(str(exc), 0) + 1
                continue

            if not edits:
                continue

            # Advisory codes may coexist; another blocking fault may not — a
            # half-repair would leave the row looking handled.
            #
            # EQUIVALENT-OPTION used to need special handling here, because the
            # repair could not address it and it had to be told apart from the
            # duplicated-correct case that reports the same code. It is now
            # repaired directly, so it is in REPAIRABLE and never reaches this.
            others = {c for c in codes
                      if c not in REPAIRABLE and c not in ADVISORY_CODES}

            if others:
                skipped += 1
                reason = 'also has ' + ', '.join(sorted(others))
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            kind = ('MISMARK ' if DUPLICATE_CORRECT in codes else 'duplicate')
            for _answer, old, new in edits:
                self.stdout.write(
                    f'  Q{question.id} [{kind}] '
                    f'{(question.question_text or "")[:60]!r}: '
                    f'{old!r} -> {new!r}')

            if options['apply']:
                self._apply(question, edits)
            repaired += 1

            if limit and repaired >= limit:
                self.stdout.write(self.style.WARNING(
                    f'\nStopped at the --limit of {limit}; more remain.'))
                break

        self.stdout.write('')
        verb = 'Repaired' if options['apply'] else 'Would repair'
        self.stdout.write(self.style.SUCCESS(f'{verb}: {repaired} question(s)'))
        if skipped:
            self.stdout.write(f'Skipped: {skipped} (left for a human)')
            for reason, count in sorted(skip_reasons.items(),
                                        key=lambda kv: -kv[1]):
                self.stdout.write(f'  {count:>5}  {reason}')
        if not options['apply'] and repaired:
            self.stdout.write(self.style.WARNING(
                '\nDry run — nothing was saved. Re-run with --apply to write.'))

    def _apply(self, question, edits):
        """Write one question's edits in a single transaction, and log them."""
        from audit.services import log_event

        with transaction.atomic():
            for answer, _old, new in edits:
                answer.answer_text = new
                answer.save(update_fields=['answer_text'])

            log_event(
                user=None, school=question.school,
                category='data_change', action='duplicate_option_repaired',
                detail={
                    'question_id': question.id,
                    # The replaced text is recorded so the change is reversible
                    # without a database backup.
                    'edits': [{'answer_id': a.id, 'was': old, 'now': new}
                              for a, old, new in edits],
                },
            )
