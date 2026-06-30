"""Give a subject the classroom Levels it needs to be usable like Maths.

Most of the app's curriculum hierarchy (class levels, progress-criteria levels,
level pickers) hangs off ``classroom.Level`` (keyed by Subject). Mathematics
shipped with a full set of levels; other subjects (e.g. Coding) often have none,
so they show "No levels available" in the class editor and can't carry
progress criteria.

This command creates **global** Level rows for a subject (numbered 300+, clear of
Maths's Year 1-8 / Basic-Facts ranges) and links them to the departments that
teach the subject (via DepartmentLevel) — exactly what the Subject/Levels admin
does, but scriptable and idempotent.

    python manage.py seed_subject_levels --subject coding --dry-run
    python manage.py seed_subject_levels --subject coding
    python manage.py seed_subject_levels --subject coding \
        --levels "Beginner,Intermediate,Advanced" --department "Information Technology"
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max, Q

from classroom.models import Subject, Level, Department, DepartmentSubject, DepartmentLevel


class Command(BaseCommand):
    help = "Create classroom Levels for a subject and link them to its departments."

    def add_arguments(self, parser):
        parser.add_argument('--subject', required=True,
                            help='Subject id, slug, or unambiguous name')
        parser.add_argument('--levels', default='Beginner,Intermediate,Advanced',
                            help='Comma-separated level display names (in order)')
        parser.add_argument('--department',
                            help='Limit to one department (id/slug/name). '
                                 'Default: every department that teaches the subject.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would change without writing.')

    def _resolve_subject(self, value):
        qs = Subject.objects.all()
        if value.isdigit():
            subj = qs.filter(pk=int(value)).first()
            if subj:
                return subj
        by_slug = list(qs.filter(slug=value))
        if len(by_slug) == 1:
            return by_slug[0]
        by_name = list(qs.filter(name__iexact=value))
        if len(by_name) == 1:
            return by_name[0]
        matches = by_slug or by_name
        if not matches:
            raise CommandError(f'No subject matches {value!r}.')
        raise CommandError(
            f'{value!r} is ambiguous ({len(matches)} subjects): '
            + ', '.join(f'id={s.id} ({s.name}, school={s.school_id})' for s in matches)
            + '. Pass the id.'
        )

    def _departments(self, subject, value):
        if value:
            dq = Department.objects.filter(is_active=True)
            dept = None
            if value.isdigit():
                dept = dq.filter(pk=int(value)).first()
            dept = dept or dq.filter(Q(slug=value) | Q(name__iexact=value)).first()
            if not dept:
                raise CommandError(f'No active department matches {value!r}.')
            return [dept]
        dept_ids = DepartmentSubject.objects.filter(
            subject=subject,
        ).values_list('department_id', flat=True)
        return list(Department.objects.filter(id__in=dept_ids, is_active=True).order_by('name'))

    @transaction.atomic
    def handle(self, *args, **opts):
        subject = self._resolve_subject(opts['subject'])
        names = [n.strip() for n in opts['levels'].split(',') if n.strip()]
        if not names:
            raise CommandError('No level names given.')
        dry = opts['dry_run']
        depts = self._departments(subject, opts.get('department'))

        self.stdout.write(
            f'Subject: {subject.name} (id={subject.id}, school={subject.school_id})'
        )

        existing = {lv.display_name: lv for lv in Level.objects.filter(subject=subject)}
        next_num = max((Level.objects.aggregate(m=Max('level_number'))['m'] or 0) + 1, 300)

        levels = []
        for name in names:
            lv = existing.get(name)
            if lv:
                self.stdout.write(f'  [exists] Level "{name}" (level_number={lv.level_number})')
            else:
                self.stdout.write(f'  [{"would add" if dry else "add"}] Level "{name}" '
                                  f'(level_number={next_num})')
                if not dry:
                    lv = Level.objects.create(
                        level_number=next_num, display_name=name,
                        subject=subject, school=None,
                    )
                next_num += 1
            if lv:
                levels.append(lv)

        if not depts:
            self.stdout.write(self.style.WARNING(
                '  No departments teach this subject yet — levels created but not '
                'mapped. Add the subject to a department, or pass --department.'))

        link_count = 0
        for dept in depts:
            for lv in levels:
                exists = DepartmentLevel.objects.filter(department=dept, level=lv).exists()
                if exists:
                    self.stdout.write(f'  [exists] {dept.name} ← "{lv.display_name}"')
                    continue
                self.stdout.write(f'  [{"would link" if dry else "link"}] {dept.name} '
                                  f'← "{lv.display_name}"')
                if not dry:
                    DepartmentLevel.objects.create(
                        department=dept, level=lv, order=lv.level_number,
                    )
                link_count += 1

        if dry:
            self.stdout.write(self.style.WARNING('[DRY RUN] No changes written.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Done. {subject.name}: {len(levels)} level(s), {link_count} new department link(s).'))
