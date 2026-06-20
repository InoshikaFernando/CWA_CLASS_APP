"""Recover homework PDF questions that the old dedup bug silently dropped.

Before the fix in ``_save_homework_pdf_questions``, image-based questions that
shared a generic stem (e.g. dozens of "What is the name of this shape?" items,
one per figure) were collapsed by ``get_or_create(question_text, topic, level,
school)`` into a single ``maths.Question`` — and every image but the first was
discarded. The full set still lives in each upload session's ``extracted_data``
+ ``extracted_images``.

This command re-runs the (now image-aware) save over confirmed sessions. It is
idempotent: questions that already exist are reused, and only the missing image
questions are (re)created — with their images uploaded to storage.

Run AFTER deploying the dedup fix (otherwise the re-run would collapse again).

Usage
-----
    python manage.py recover_homework_pdf_images --session 11
    python manage.py recover_homework_pdf_images --school 4
    python manage.py recover_homework_pdf_images --all --dry-run
    python manage.py recover_homework_pdf_images --school 4 --attach
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Recover image questions dropped by the old homework PDF dedup bug.'

    def add_arguments(self, parser):
        g = parser.add_mutually_exclusive_group(required=True)
        g.add_argument('--session', type=int, help='Single upload-session id.')
        g.add_argument('--school', type=int, help='All confirmed sessions for a school id.')
        g.add_argument('--all', action='store_true', help='All confirmed sessions.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be recovered without writing.')
        parser.add_argument('--attach', action='store_true',
                            help='Also link recovered questions to the session\'s homework '
                                 '(updates HomeworkQuestion + num_questions).')

    def handle(self, *args, **opts):
        from homework.models import HomeworkUploadSession, HomeworkQuestion
        from homework.views import _save_homework_pdf_questions
        from maths.models import Question

        qs = HomeworkUploadSession.objects.filter(is_confirmed=True)
        if opts['session']:
            qs = qs.filter(pk=opts['session'])
        elif opts['school']:
            qs = qs.filter(school_id=opts['school'])
        sessions = list(qs.select_related('user', 'school', 'homework'))
        if not sessions:
            raise CommandError('No matching confirmed upload sessions.')

        dry = opts['dry_run']
        attach = opts['attach']
        total_before = total_after = total_attached = 0

        for s in sessions:
            data = s.extracted_data or {}
            questions_data = [q for q in data.get('questions', []) if q.get('include', True)]
            if not questions_data:
                continue
            if not s.user:
                self.stderr.write(self.style.WARNING(
                    f'  session #{s.pk}: no user — skipped (scope cannot be resolved).'))
                continue

            before = Question.objects.count()
            created = attached = 0
            try:
                with transaction.atomic():
                    # save_images=False on a dry run so the rolled-back
                    # transaction leaves no orphan files in S3/Spaces.
                    saved = _save_homework_pdf_questions(
                        questions_data, data, s.user, s.school, s,
                        save_images=not dry,
                    )
                    created = Question.objects.count() - before

                    if attach and s.homework_id and saved:
                        existing = set(
                            HomeworkQuestion.objects
                            .filter(homework_id=s.homework_id)
                            .values_list('content_id', flat=True)
                        )
                        seen = set()
                        new_rows = []
                        order = len(existing)
                        for q in saved:
                            if q.pk in existing or q.pk in seen:
                                continue
                            seen.add(q.pk)
                            order += 1
                            new_rows.append(HomeworkQuestion(
                                homework_id=s.homework_id, question=q,
                                subject_slug='mathematics', content_id=q.pk, order=order,
                            ))
                        if new_rows:
                            HomeworkQuestion.objects.bulk_create(new_rows)
                            attached = len(new_rows)
                            hw = s.homework
                            hw.num_questions = HomeworkQuestion.objects.filter(
                                homework_id=s.homework_id).count()
                            hw.save(update_fields=['num_questions'])

                    if dry:
                        transaction.set_rollback(True)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'  session #{s.pk}: failed — {exc}'))
                continue

            total_before += len(questions_data)
            total_after += created
            total_attached += attached
            self.stdout.write(
                f"  session #{s.pk} '{(s.homework_title or '')[:30]}': "
                f"{len(questions_data)} extracted, {created} question(s) recovered"
                + (f", {attached} attached to HW#{s.homework_id}" if attach else ''))

        verb = 'Would recover' if dry else 'Recovered'
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb}: {total_after} question(s) across {len(sessions)} session(s)"
            + (f", {total_attached} attached" if attach else '')
            + (' (dry run — rolled back)' if dry else '')))
