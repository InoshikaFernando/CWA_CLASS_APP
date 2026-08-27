"""
Report what a ClassRoom.subject / Level.subject repair would change — and
what it would cost.

READ-ONLY. This command never writes: no save(), no update(), no create().
Run it on a production snapshot to see every row a future backfill would
touch, review the output, and only then decide whether to run the repair.

Why this exists
---------------
``ClassRoom.subject`` is not stored from what the user picked — the create and
edit views derive it from ``levels.first()``, which orders by ``level_number``.
Maths owns 1-10 and every other subject starts at 300, so a class holding any
maths level is labelled Mathematics regardless of what it teaches. Separately,
Year levels 1-9 were seeded before ``Level.subject`` existed and carry NULL,
which makes them belong to no subject at all.

Both are fixable, but ``classroom.subject`` feeds the invoice fee cascade
(``fee_utils.get_effective_fee_for_class`` step 4 keys on ``subject_id``), so a
repair can move what a parent is billed. This command quantifies that before
anything changes.

Proposed repair rules (reported, not applied)
---------------------------------------------
Levels:
  * ``level_number < 200`` with no subject  -> Mathematics
    (Year levels and Basic Facts both belong to maths per the Level docstring)
  * ``level_number >= 200`` with no subject -> reported as UNKNOWN; a school
    custom level cannot be assumed to be maths.

Classes, from the subjects of their levels (after the level rule above):
  * exactly one subject   -> that subject
  * no levels             -> department.primary_subject, only when the class
                             has no subject already
  * two or more subjects  -> AMBIGUOUS. Reported for a human. Never guessed.

Usage:
    python manage.py audit_class_subjects
    python manage.py audit_class_subjects --school 3
    python manage.py audit_class_subjects --csv /tmp/subject_audit.csv
"""

import csv

from django.core.management.base import BaseCommand

from classroom.fee_utils import get_effective_fee_for_class
from classroom.models import (
    ClassRoom, DepartmentLevel, DepartmentSubject, Level, School, Subject,
)

# Levels below this number belong to Mathematics: 1-99 are Year levels and
# 100-199 are Basic Facts. 200+ are school-created and carry no such promise.
MATHS_LEVEL_CEILING = 200


class Command(BaseCommand):
    help = 'Report (never apply) what a ClassRoom.subject / Level.subject repair would change.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--school', help='Limit to one school (id, slug or exact name).',
        )
        parser.add_argument(
            '--csv', dest='csv_path',
            help='Also write the per-class rows to this CSV path.',
        )

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _resolve_school(self, value):
        if not value:
            return None
        qs = School.objects.all()
        school = None
        if value.isdigit():
            school = qs.filter(pk=int(value)).first()
        school = school or qs.filter(slug=value).first() or qs.filter(name=value).first()
        if not school:
            self.stderr.write(self.style.ERROR(f'No school matches {value!r}.'))
        return school

    def _maths_subject(self):
        """The global Mathematics subject, or None if this install has none."""
        return Subject.objects.filter(slug='mathematics', school__isnull=True).first()

    def _level_subject_id(self, level, maths):
        """Subject a level would have after the repair, or None if unknowable."""
        if level.subject_id:
            return level.subject_id
        if level.level_number < MATHS_LEVEL_CEILING and maths:
            return maths.id
        return None

    def _proposed_subject_id(self, classroom, maths):
        """Return (subject_id, reason). subject_id None means 'leave alone'."""
        subject_ids = set()
        unknown = False
        for level in classroom.levels.all():
            sid = self._level_subject_id(level, maths)
            if sid:
                subject_ids.add(sid)
            else:
                unknown = True

        if len(subject_ids) == 1 and not unknown:
            return subject_ids.pop(), 'from levels'
        if len(subject_ids) > 1:
            return None, 'AMBIGUOUS: levels span %d subjects' % len(subject_ids)
        if unknown:
            return None, 'UNKNOWN: level has no subject and is not a maths level'
        # No levels at all.
        if classroom.subject_id:
            return None, 'no levels — keeping current subject'
        primary = classroom.department.primary_subject if classroom.department_id else None
        if primary:
            return primary.id, "from department's first subject"
        return None, 'no levels and no department subject'

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def handle(self, *args, **opts):
        school = self._resolve_school(opts.get('school'))
        if opts.get('school') and not school:
            return

        maths = self._maths_subject()
        if not maths:
            self.stdout.write(self.style.WARNING(
                'No global Mathematics subject found — level inference is disabled '
                'and every subject-less level is reported as UNKNOWN.'))

        self._section_levels(maths)
        rows = self._section_classes(school, maths)
        self._section_fee_exposure(rows)
        self._section_cross_subject_mappings(school, maths)

        if opts.get('csv_path'):
            self._write_csv(opts['csv_path'], rows)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            'Read-only audit complete. Nothing was changed.'))

    # -- 1. Levels ------------------------------------------------------

    def _section_levels(self, maths):
        self._heading('1. Levels with no subject')

        orphans = Level.objects.filter(subject__isnull=True).order_by('level_number')
        if not orphans.exists():
            self.stdout.write('  None — every level already names its subject.')
            return

        would_set, unknown = [], []
        for level in orphans:
            (would_set if self._level_subject_id(level, maths) else unknown).append(level)

        if would_set:
            self.stdout.write(f'  {len(would_set)} would be set to Mathematics:')
            for level in would_set:
                self.stdout.write(
                    f'    level_number={level.level_number:<5} {level.display_name}')
        if unknown:
            self.stdout.write(self.style.WARNING(
                f'  {len(unknown)} cannot be inferred — a human must assign these:'))
            for level in unknown:
                scope = f'school={level.school_id}' if level.school_id else 'global'
                self.stdout.write(
                    f'    level_number={level.level_number:<5} {level.display_name}  ({scope})')

    # -- 2. Classes -----------------------------------------------------

    def _section_classes(self, school, maths):
        self._heading('2. Classes whose subject would change')

        qs = ClassRoom.objects.filter(is_active=True)
        if school:
            qs = qs.filter(school=school)
        qs = qs.select_related('school', 'department', 'subject').prefetch_related('levels')

        subject_names = {s.id: s.name for s in Subject.objects.all()}
        changed, ambiguous, unchanged = [], [], 0

        for classroom in qs.order_by('school__name', 'department__name', 'name'):
            proposed_id, reason = self._proposed_subject_id(classroom, maths)

            if proposed_id is None:
                if reason.startswith(('AMBIGUOUS', 'UNKNOWN')):
                    ambiguous.append((classroom, reason))
                else:
                    unchanged += 1
                continue

            if proposed_id == classroom.subject_id:
                unchanged += 1
                continue

            fee_before = get_effective_fee_for_class(classroom)
            # In-memory only — this object is never saved.
            original_subject_id = classroom.subject_id
            classroom.subject_id = proposed_id
            fee_after = get_effective_fee_for_class(classroom)
            classroom.subject_id = original_subject_id

            changed.append({
                'classroom': classroom,
                'school': classroom.school.name if classroom.school_id else '',
                'department': classroom.department.name if classroom.department_id else '',
                'name': classroom.name,
                'old_subject': subject_names.get(classroom.subject_id, '(none)'),
                'new_subject': subject_names.get(proposed_id, '(none)'),
                'reason': reason,
                'fee_before': fee_before,
                'fee_after': fee_after,
                'fee_moves': fee_before != fee_after,
                'levels': ', '.join(
                    lv.display_name for lv in classroom.levels.all()) or '(none)',
            })

        if changed:
            self.stdout.write(f'  {len(changed)} class(es) would change:')
            for row in changed:
                flag = self.style.ERROR('  FEE MOVES') if row['fee_moves'] else ''
                self.stdout.write(
                    f"    [{row['school']}] {row['name']}: "
                    f"{row['old_subject']} -> {row['new_subject']}  ({row['reason']}){flag}")
                if row['fee_moves']:
                    self.stdout.write(
                        f"        fee {row['fee_before']} -> {row['fee_after']}")
        else:
            self.stdout.write('  None — every class already names the right subject.')

        if ambiguous:
            self._heading('3. Classes a human must decide (never auto-repaired)')
            for classroom, reason in ambiguous:
                school_name = classroom.school.name if classroom.school_id else ''
                current = subject_names.get(classroom.subject_id, '(none)')
                levels = ', '.join(lv.display_name for lv in classroom.levels.all())
                self.stdout.write(
                    f'    [{school_name}] {classroom.name}: currently {current} — {reason}')
                self.stdout.write(f'        levels: {levels}')
        else:
            self._heading('3. Classes a human must decide (never auto-repaired)')
            self.stdout.write('  None.')

        self.stdout.write('')
        self.stdout.write(f'  Unchanged: {unchanged}')
        return changed

    # -- 4. Fee exposure ------------------------------------------------

    def _section_fee_exposure(self, rows):
        self._heading('4. Fee impact')

        priced_by_subject = DepartmentSubject.objects.filter(
            fee_override__isnull=False,
        ).count()
        self.stdout.write(
            f'  Departments pricing by subject (DepartmentSubject.fee_override set): '
            f'{priced_by_subject}')

        movers = [r for r in rows if r['fee_moves']]
        if not movers:
            self.stdout.write(self.style.SUCCESS(
                '  No class changes its effective fee. The repair is billing-neutral.'))
            return

        self.stdout.write(self.style.ERROR(
            f'  {len(movers)} class(es) would be billed differently:'))
        for row in movers:
            self.stdout.write(
                f"    [{row['school']}] {row['name']}: "
                f"{row['fee_before']} -> {row['fee_after']}")
        self.stdout.write(self.style.WARNING(
            '  Review these with the school before applying any repair.'))

    # -- 5. Cross-subject department mappings ---------------------------

    def _section_cross_subject_mappings(self, school, maths):
        self._heading('5. Department level mappings to review')
        self.stdout.write(
            '  Maths levels mapped under a department that does not teach maths.\n'
            '  A repair must LEAVE THESE ALONE — they are listed so a human can look.')

        qs = DepartmentLevel.objects.select_related(
            'department', 'department__school', 'level',
        )
        if school:
            qs = qs.filter(department__school=school)

        dept_subject_ids = {}
        odd = []
        for mapping in qs:
            level_subject_id = self._level_subject_id(mapping.level, maths)
            if not level_subject_id:
                continue
            dept_id = mapping.department_id
            if dept_id not in dept_subject_ids:
                dept_subject_ids[dept_id] = set(
                    DepartmentSubject.objects.filter(department_id=dept_id)
                    .values_list('subject_id', flat=True)
                )
            if dept_subject_ids[dept_id] and level_subject_id not in dept_subject_ids[dept_id]:
                odd.append(mapping)

        if not odd:
            self.stdout.write('  None.')
            return

        self.stdout.write(self.style.WARNING(f'  {len(odd)} mapping(s):'))
        for mapping in odd:
            school_name = (
                mapping.department.school.name if mapping.department.school_id else '')
            self.stdout.write(
                f'    [{school_name}] {mapping.department.name} '
                f'<- "{mapping.level.display_name}" (level_number={mapping.level.level_number})')

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _heading(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _write_csv(self, path, rows):
        fields = [
            'school', 'department', 'name', 'old_subject', 'new_subject',
            'reason', 'fee_before', 'fee_after', 'fee_moves', 'levels',
        ]
        with open(path, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'CSV written to {path} ({len(rows)} row(s)).'))
