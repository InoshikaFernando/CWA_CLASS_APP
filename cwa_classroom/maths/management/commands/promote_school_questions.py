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

``--year`` / ``--topic`` scope the promotion to one slice of the school's bank
— the safer move when a single gap was found, since promoting a whole school
publishes every one of its private questions to every other school at once.

Usage
-----
    # Preview (writes nothing):
    python manage.py promote_school_questions --school 4 --dry-run

    # Just the gap you found — Year 4 Number Patterns:
    python manage.py promote_school_questions --school-slug maths-hub-melbourne-pty-ltd \
        --year 4 --topic "Number Patterns" --dry-run

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
        parser.add_argument('--school', type=int,
                            help='School id whose maths questions to promote.')
        parser.add_argument('--school-slug', type=str,
                            help='School slug, as an alternative to --school.')
        parser.add_argument('--year', type=int,
                            help='Only promote this year level (Level.level_number).')
        parser.add_argument('--topic', type=str,
                            help='Only promote this topic — matched against the topic '
                                 "name, its parent strand's name, or its slug.")
        parser.add_argument('--exact-topic', action='store_true',
                            help='Match --topic as a full name instead of a substring.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Preview every step without writing to the DB.')
        parser.add_argument('--keep-json', type=str, default='',
                            help='Write the export JSON to this path and keep it '
                                 '(default: a temp file that is deleted afterwards).')

    def handle(self, *args, **opts):
        from classroom.models import School

        dry_run = opts['dry_run']
        if not opts['school'] and not opts['school_slug']:
            raise CommandError('Provide --school <id> or --school-slug <slug>.')
        try:
            school = (School.objects.get(pk=opts['school']) if opts['school']
                      else School.objects.get(slug=opts['school_slug']))
        except School.DoesNotExist:
            raise CommandError(
                f"School {opts['school'] or opts['school_slug']!r} not found.")
        school_id = school.id

        scope = ''
        if opts['year'] is not None:
            scope += f", year {opts['year']}"
        if opts['topic']:
            scope += f", topic {opts['topic']!r}"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== Promote '{school.name}' (id {school_id}{scope}) -> global bank"
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
            call_command('export_school_questions', school=school_id, output=out_path,
                         year=opts['year'], topic=opts['topic'],
                         exact_topic=opts['exact_topic'])

            self.stdout.write(self.style.HTTP_INFO('\n[2/2] Import into global bank'))
            call_command('import_global_questions', out_path, dry_run=dry_run)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

        self.stdout.write(self.style.SUCCESS(
            "\n=== Done" + (" (dry run - nothing written)" if dry_run else "") + " ==="))
