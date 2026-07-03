"""Assign a student's legacy class-less ProgressRecords to a specific class.

Progress is now tracked per class (§12.10). Records created before that change
have ``classroom=NULL``. This one-off, idempotent command moves a given student's
class-less records onto a chosen class — e.g. Pamith Ranasinghe's shared records
belong to the Tuesday Web class, not the Wednesday one.

    python manage.py reassign_progress_records --student "Pamith Ranasinghe" \
        --classroom "Web Programing (Tuesday)" --dry-run
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from classroom.models import ClassRoom, ProgressRecord


def _resolve(model, value, label, extra_q=None):
    qs = model.objects.all()
    if extra_q is not None:
        qs = qs.filter(extra_q)
    if str(value).isdigit():
        obj = qs.filter(pk=int(value)).first()
        if obj:
            return obj
    matches = list(qs.filter(Q(name__iexact=value) | Q(name__icontains=value))[:5])
    if not matches:
        raise CommandError(f'No {label} matching {value!r}.')
    if len(matches) > 1:
        raise CommandError(
            f'{label} {value!r} is ambiguous: '
            + ', '.join(f'{m.pk}:{m.name}' for m in matches)
        )
    return matches[0]


class Command(BaseCommand):
    help = "Assign a student's class-less progress records to a specific class."

    def add_arguments(self, parser):
        parser.add_argument('--student', required=True,
                            help='Student user id, username, or full name.')
        parser.add_argument('--classroom', required=True,
                            help='Target class id or name.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would change without writing.')

    def _resolve_student(self, value):
        from accounts.models import CustomUser
        if str(value).isdigit():
            u = CustomUser.objects.filter(pk=int(value)).first()
            if u:
                return u
        qs = CustomUser.objects.filter(
            Q(username__iexact=value)
            | Q(first_name__icontains=value.split()[0])
        )
        # Prefer an exact full-name match when possible.
        exact = [u for u in qs if u.get_full_name().lower() == value.lower()]
        cands = exact or list(qs[:5])
        if not cands:
            raise CommandError(f'No student matching {value!r}.')
        if len(cands) > 1:
            raise CommandError(
                f'Student {value!r} is ambiguous: '
                + ', '.join(f'{u.pk}:{u.get_full_name() or u.username}' for u in cands)
            )
        return cands[0]

    def handle(self, *args, **opts):
        student = self._resolve_student(opts['student'])
        classroom = _resolve(ClassRoom, opts['classroom'], 'class')
        dry = opts['dry_run']

        legacy = ProgressRecord.objects.filter(student=student, classroom__isnull=True)
        moved = skipped = 0
        for rec in legacy:
            # Skip if a record already exists for this criterion in the target class.
            clash = ProgressRecord.objects.filter(
                student=student, criteria_id=rec.criteria_id,
                classroom=classroom, session=rec.session,
            ).exclude(pk=rec.pk).exists()
            if clash:
                skipped += 1
                self.stdout.write(f'  [skip] {rec.criteria} — already recorded in target class')
                continue
            self.stdout.write(f'  [{"would move" if dry else "move"}] {rec.criteria} -> {classroom.name}')
            if not dry:
                rec.classroom = classroom
                rec.save(update_fields=['classroom'])
            moved += 1

        prefix = '[DRY RUN] ' if dry else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{student.get_full_name() or student.username}: '
            f'{moved} record(s) {"would move" if dry else "moved"} to '
            f'{classroom.name}, {skipped} skipped.'
        ))
