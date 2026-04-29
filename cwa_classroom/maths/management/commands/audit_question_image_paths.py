"""
Audit every Question.image against the agreed naming convention:

    questions/year<N>/<topic>/<filename>

Read-only. Prints the offending rows and exits non-zero if any are found,
so a scheduled task / CI step can detect drift automatically.

Usage:
    python manage.py audit_question_image_paths            # human output
    python manage.py audit_question_image_paths --quiet    # only summary
"""
import re
import sys

from django.core.management.base import BaseCommand


VALID_PATH_RE = re.compile(r'^questions/year[0-9]+/[a-zA-Z0-9_-]+/.+')


class Command(BaseCommand):
    help = 'Audit Question.image paths against the questions/year<N>/<topic>/ convention.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet', action='store_true',
            help='Suppress per-row output; print only the summary.',
        )

    def handle(self, *args, **options):
        from maths.models import Question

        quiet = options['quiet']

        rows = (
            Question.objects
            .exclude(image__isnull=True).exclude(image='')
            .values_list('id', 'image')
        )

        bad = sorted(
            (pk, str(path))
            for pk, path in rows
            if not VALID_PATH_RE.match(str(path))
        )

        total = len(rows) if hasattr(rows, '__len__') else Question.objects.exclude(image__isnull=True).exclude(image='').count()

        if not quiet:
            for pk, path in bad:
                self.stdout.write(f'  Q{pk}: {path}')

        msg = f'Audited image paths — {len(bad)} violation(s)'
        if bad:
            self.stdout.write(self.style.ERROR(msg))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS(msg))
