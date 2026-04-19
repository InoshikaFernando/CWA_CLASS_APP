"""
Management command: fix_text_encoding
======================================
Repairs double-encoded UTF-8 text stored as Latin-1 across all coding
content models.  The corruption pattern looks like:

    Â°  →  °      (degree sign)
    Ã©  →  é
    â€™ →  '      (smart apostrophe)
    â€œ →  "      (left double quote)
    â€  →  "      (right double quote)
    â€" →  –      (en dash)
    â€" →  —      (em dash)

The fix: encode the corrupted string back to Latin-1 bytes, then decode
those bytes as UTF-8.  This reverses the original mis-read.

Usage:
    python manage.py fix_text_encoding
    python manage.py fix_text_encoding --dry-run
"""
from django.core.management.base import BaseCommand


def _fix(text: str) -> str:
    if not text:
        return text
    try:
        fixed = text.encode('latin-1').decode('utf-8')
        return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _fix_obj(obj, fields, dry_run, stats):
    changed = []
    for field in fields:
        original = getattr(obj, field, '') or ''
        fixed = _fix(original)
        if fixed != original:
            changed.append(field)
            if not dry_run:
                setattr(obj, field, fixed)
    if changed:
        stats['objects'] += 1
        stats['fields'] += len(changed)
        if not dry_run:
            obj.save(update_fields=changed)
    return changed


class Command(BaseCommand):
    help = 'Fix double-encoded UTF-8 text (Â°→° etc.) across all coding content.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview changes without writing to the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be saved.\n'))

        stats = {'objects': 0, 'fields': 0}

        try:
            from coding.models import (
                CodingLanguage, CodingTopic, TopicLevel,
                CodingExercise, CodingProblem,
            )
        except ImportError as exc:
            self.stderr.write(f'Could not import coding models: {exc}')
            return

        for obj in CodingLanguage.objects.all():
            _fix_obj(obj, ['name', 'description'], dry_run, stats)

        for obj in CodingTopic.objects.all():
            _fix_obj(obj, ['name', 'description'], dry_run, stats)

        for obj in TopicLevel.objects.all():
            _fix_obj(obj, ['name', 'description'], dry_run, stats)

        for obj in CodingExercise.objects.all():
            changed = _fix_obj(obj, [
                'title', 'description', 'starter_code',
                'solution_code', 'expected_output', 'hints',
            ], dry_run, stats)
            if changed and dry_run:
                self.stdout.write(f'  Exercise [{obj.id}] "{obj.title}" — fields: {changed}')

        for obj in CodingProblem.objects.all():
            changed = _fix_obj(obj, [
                'title', 'description', 'starter_code',
                'solution_code', 'hints',
            ], dry_run, stats)
            if changed and dry_run:
                self.stdout.write(f'  Problem [{obj.id}] "{obj.title}" — fields: {changed}')

        try:
            from coding.models import ProblemTestCase
            for obj in ProblemTestCase.objects.all():
                _fix_obj(obj, ['input_data', 'expected_output', 'description'],
                         dry_run, stats)
        except ImportError:
            pass

        action = 'Would fix' if dry_run else 'Fixed'
        self.stdout.write(self.style.SUCCESS(
            f'\n{action} {stats["objects"]} object(s) across {stats["fields"]} field(s).'
        ))
