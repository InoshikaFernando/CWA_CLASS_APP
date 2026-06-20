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
        total_before = total_after = total_attached = total_skipped_subs = 0

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
            created = attached = skipped_subs = 0
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
                        attached, skipped_subs = self._attach_to_homeworks(s, saved)

                    if dry:
                        transaction.set_rollback(True)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'  session #{s.pk}: failed — {exc}'))
                continue

            total_before += len(questions_data)
            total_after += created
            total_attached += attached
            total_skipped_subs += skipped_subs
            self.stdout.write(
                f"  session #{s.pk} '{(s.homework_title or '')[:30]}': "
                f"{len(questions_data)} extracted, {created} question(s) recovered"
                + (f", {attached} attached" if attach else '')
                + (f", {skipped_subs} skipped (has submissions)" if skipped_subs else ''))

        verb = 'Would recover' if dry else 'Recovered'
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb}: {total_after} question(s) across {len(sessions)} session(s)"
            + (f", {total_attached} attached" if attach else '')
            + (f", {total_skipped_subs} homework(s) skipped (have submissions)"
               if total_skipped_subs else '')
            + (' (dry run — rolled back)' if dry else '')))

    def _attach_to_homeworks(self, session, saved):
        """Link recovered questions to the session's homework AND its sibling
        class copies (same teacher + title + identical question set), but only
        when a homework has NO student submissions — never retro-edit a graded
        assignment. Returns (attached_rows, skipped_homeworks_with_submissions).
        """
        from django.db.models import Max
        from homework.models import Homework, HomeworkQuestion, HomeworkSubmission

        linked = session.homework
        base_ids = set(
            HomeworkQuestion.objects.filter(homework_id=linked.id)
            .values_list('content_id', flat=True)
        )

        # Siblings: the same PDF assignment given to other classes. The confirm
        # step linked an identical question set to each, so a homework with the
        # exact same content set, title and creator is a sibling of this upload.
        targets = [linked]
        for hw in Homework.all_objects.filter(
            homework_type='pdf_upload',
            created_by_id=linked.created_by_id,
            title=linked.title,
        ).exclude(pk=linked.id):
            cids = set(
                HomeworkQuestion.objects.filter(homework_id=hw.id)
                .values_list('content_id', flat=True)
            )
            if cids and cids == base_ids:
                targets.append(hw)

        recovered = list(dict.fromkeys(q.pk for q in saved))  # de-dup, keep order
        attached = skipped = 0
        for hw in targets:
            existing = set(
                HomeworkQuestion.objects.filter(homework_id=hw.id)
                .values_list('content_id', flat=True)
            )
            to_add = [pk for pk in recovered if pk not in existing]
            if not to_add:
                continue  # nothing this homework is missing — leave it alone
            if HomeworkSubmission.objects.filter(homework_id=hw.id).exists():
                self.stderr.write(self.style.WARNING(
                    f'    HW#{hw.id} "{hw.title}" has submissions — skipped (not retro-edited).'))
                skipped += 1
                continue
            order = (HomeworkQuestion.objects.filter(homework_id=hw.id)
                     .aggregate(m=Max('order'))['m'] or 0)
            new_rows = []
            for pk in to_add:
                order += 1
                new_rows.append(HomeworkQuestion(
                    homework_id=hw.id, question_id=pk,
                    subject_slug='mathematics', content_id=pk, order=order,
                ))
            HomeworkQuestion.objects.bulk_create(new_rows)
            attached += len(new_rows)
            hw.num_questions = HomeworkQuestion.objects.filter(homework_id=hw.id).count()
            hw.save(update_fields=['num_questions'])
        return attached, skipped
