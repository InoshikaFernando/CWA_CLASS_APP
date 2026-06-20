"""Promote a school's maths questions into the global bank — the weekly pipeline
in one command.

Steps (both honour ``--dry-run``, both idempotent):
  1. export the school's maths questions to a JSON grouped by year/title/subtitle.
  2. import them into the global bank (school=NULL): deduped (image questions by
     image path, text questions by text+level), with each topic registered for
     its level so it appears in the topic-quiz picker.

Re-running is safe — questions already in global are skipped, so this is the
command to run each week as a school adds content.

Note: this does NOT run the homework-PDF *recovery* (``recover_homework_pdf_images``).
That was a one-off fix for image questions dropped by an old dedup bug; the bug
is fixed, so routine uploads don't need it. Run that command manually if you ever
need to backfill historical drops.

Usage
-----
    # Preview (writes nothing):
    python manage.py promote_school_questions --school 4 --dry-run

    # Promote for real:
    python manage.py promote_school_questions --school 4

    # Keep the intermediate JSON for review instead of a temp file:
    python manage.py promote_school_questions --school 4 --keep-json /tmp/mhm.json
"""
import os
import tempfile

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Promote a school's maths questions into the global bank (export → import)."

    def add_arguments(self, parser):
        parser.add_argument('--school', type=int, required=True,
                            help='School id whose maths questions to promote.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Preview every step without writing to the DB.')
        parser.add_argument('--keep-json', type=str, default='',
                            help='Write the export JSON to this path and keep it '
                                 '(default: a temp file that is deleted afterwards).')

    def handle(self, *args, **opts):
        from classroom.models import School

        school_id = opts['school']
        dry_run = opts['dry_run']
        try:
            school = School.objects.get(pk=school_id)
        except School.DoesNotExist:
            raise CommandError(f'School id {school_id} not found.')

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== Promote '{school.name}' (id {school_id}) -> global bank"
            f"{'  [DRY RUN]' if dry_run else ''} ==="))

        out_path = opts['keep_json']
        tmp_path = None
        if not out_path:
            fd, out_path = tempfile.mkstemp(
                prefix=f'promote_school_{school_id}_', suffix='.json')
            os.close(fd)
            tmp_path = out_path

        try:
            self.stdout.write(self.style.HTTP_INFO('\n[1/2] Export school questions -> JSON'))
            call_command('export_school_questions', school=school_id, output=out_path)

            self.stdout.write(self.style.HTTP_INFO('\n[2/2] Import into global bank'))
            call_command('import_global_questions', out_path, dry_run=dry_run)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

        self.stdout.write(self.style.SUCCESS(
            "\n=== Done" + (" (dry run - nothing written)" if dry_run else "") + " ==="))
