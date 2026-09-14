"""Withdraw a question from service, or put a repaired one back (CPP-410).

Retiring is the supported way to take a broken question out of circulation.
Deleting is not, and never was: every foreign key pointing at
``maths.Question`` is ``on_delete=CASCADE``, so deleting one takes every
homework, worksheet and quiz answer ever given to it, plus the rows recording
which homeworks contained it. Removing a question because its diagram was
never attached would rewrite a child's answer history to tidy up.

A retired question stops being selected for new homework, worksheets and
quizzes, AND is skipped on the take page of homework that already contains it
— a question is normally retired because it is broken, so "stops being served"
has to mean now rather than at the next assignment. Past submissions keep it,
shown greyed with the answer the student gave. No answer row is touched and no
mark moves.

The admin has actions for the same thing; this exists so retirement can carry
a real REASON, be scripted across several questions, and be previewed before
it happens.

DRY-RUN BY DEFAULT. Pass --apply to write.

    python manage.py retire_question --question 11014 \
        --reason "No diagram; unanswerable (CPP-406)."
    python manage.py retire_question --question 11014 --question 11015 --apply
    python manage.py retire_question --question 11014 --unretire --apply
    python manage.py retire_question --list
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Withdraw a question from service, or put a repaired one back.'

    def add_arguments(self, parser):
        parser.add_argument('--question', type=int, action='append', default=None,
                            metavar='ID', help='Question id (repeatable).')
        parser.add_argument('--reason', default='',
                            help='Why it is being withdrawn. Shown to the next '
                                 'reviewer so the fault is not rediscovered.')
        parser.add_argument('--unretire', action='store_true',
                            help='Put the question back into service instead.')
        parser.add_argument('--list', action='store_true',
                            help='Show every currently withdrawn question.')
        parser.add_argument('--apply', action='store_true',
                            help='Write the change (default is a dry run).')

    def handle(self, *args, **options):
        from maths.models import Question

        if options['list']:
            return self._list(Question)

        ids = options['question']
        if not ids:
            raise CommandError(
                'Pass --question <id> (repeatable), or --list to see what is '
                'already withdrawn.')

        unretire = options['unretire']
        reason = (options['reason'] or '').strip()
        if not unretire and not reason:
            # A withdrawn question with no reason leaves the next person to
            # work out the fault from scratch — which is how 11015 became
            # unrepairable in the first place.
            self.stdout.write(self.style.WARNING(
                'No --reason given. The reason is what stops the next person '
                'rediscovering the fault; consider adding one.'))

        changed = skipped = 0
        for qid in ids:
            question = Question.objects.filter(pk=qid).first()
            if question is None:
                self.stdout.write(self.style.ERROR(f'Q{qid}: not found'))
                skipped += 1
                continue

            label = f'Q{question.id} [{question.level} / {question.topic}]'
            text = (question.question_text or '')[:60]

            if unretire:
                if not question.is_retired:
                    self.stdout.write(f'{label}: already in service — skipped')
                    skipped += 1
                    continue
                self.stdout.write(f'{label}: back into service  {text!r}')
                if options['apply']:
                    question.unretire()
                    changed += 1
                continue

            if question.is_retired:
                self.stdout.write(
                    f'{label}: already withdrawn '
                    f'({question.retired_at:%Y-%m-%d}) — skipped')
                skipped += 1
                continue

            answers = (question.homework_student_answers.count()
                       + question.worksheet_student_answers.count()
                       + question.student_answers.count())
            self.stdout.write(f'{label}: withdraw  {text!r}')
            self.stdout.write(
                f'    {answers} recorded answer(s) KEPT — retiring deletes '
                f'nothing and changes no mark')
            if reason:
                self.stdout.write(f'    reason: {reason}')
            if options['apply']:
                question.retire(reason, when=timezone.now())
                changed += 1

        self.stdout.write('')
        if options['apply']:
            self.stdout.write(self.style.SUCCESS(
                f'{changed} changed, {skipped} skipped.'))
        else:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN — nothing written ({skipped} would be skipped). '
                f'Re-run with --apply.'))

    def _list(self, Question):
        rows = list(Question.objects.retired().select_related('level', 'topic'))
        if not rows:
            self.stdout.write('No question is currently withdrawn.')
            return
        self.stdout.write(f'{len(rows)} withdrawn question(s):\n')
        for q in rows:
            when = q.retired_at.date().isoformat() if q.retired_at else '?'
            self.stdout.write(
                f'  Q{q.id:<7} {when}  {(q.question_text or "")[:50]!r}')
            if q.retired_reason:
                self.stdout.write(f'            {q.retired_reason[:90]}')
