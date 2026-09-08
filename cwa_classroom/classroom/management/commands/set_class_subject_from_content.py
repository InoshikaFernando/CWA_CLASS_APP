"""Fill ``ClassRoom.subject`` from the work a class actually sets.

Migration 0120 repaired what it could infer from levels and deliberately
SKIPPED the rest rather than guess. What it left behind is what a progress
report sees as "No subject set" — and an unknown subject means the report
cannot scope itself, so a coding class keeps showing the student's times
tables (progress.reports.covered_subject_slugs returns None: do not scope,
because dropping a class's work on the strength of a blank field would be
worse).

Levels are the wrong evidence for these classes. Two better sources, in order:

1. **Homework.** A class whose homework all carries ``subject_slug='coding'``
   teaches coding, whatever its levels say.
2. **Its department**, when that department maps to exactly ONE subject. This
   is what 0120 could not reach: it consults the department only for a class
   with NO LEVELS AT ALL, and any level it cannot resolve skips the class
   outright — so a coding class with coding levels never got as far as its
   department, however unambiguously that department was mapped.

A department mapping to two or more subjects decides nothing and is reported
rather than guessed: ``Department.subjects`` is many-to-many precisely because
a department can teach several.

Refuses to guess in exactly the cases 0120 refused:

  * a class whose homework spans two subjects  -> skipped and named
  * a class with no homework at all            -> skipped and named
  * a slug with no matching Subject row        -> skipped and named

Writes nothing without ``--apply``.
"""

from collections import Counter

from django.core.management.base import BaseCommand

from classroom.models import ClassRoom, Subject


class Command(BaseCommand):
    help = "Set a class's subject from the homework assigned to it."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Write the changes. Without it, nothing is saved.')
        parser.add_argument('--school', type=int, default=None,
                            help='Limit to one school id.')

    def _from_department(self, classroom):
        """The department's subject, when it maps to exactly one.

        Returns ``(subject, reason)``. *subject* is None when the department
        cannot decide, and *reason* is what a human reads to know why.
        """
        if classroom.department_id is None:
            return None, 'no homework, and no department'

        subjects = list(classroom.department.subjects.all())
        if not subjects:
            return None, (
                f'no homework, and department {classroom.department.name!r} '
                f'maps to no subject'
            )
        if len(subjects) > 1:
            names = ', '.join(sorted(s.name for s in subjects))
            return None, (
                f'no homework, and department {classroom.department.name!r} '
                f'maps to several subjects ({names})'
            )
        return subjects[0], f'department {classroom.department.name!r}'

    def handle(self, *args, **options):
        from homework.models import Homework

        qs = ClassRoom.objects.filter(subject__isnull=True, is_active=True)
        if options['school']:
            qs = qs.filter(school_id=options['school'])
        classrooms = list(
            qs.select_related('department')
            .prefetch_related('department__subjects')
            .order_by('school_id', 'name')
        )

        if not classrooms:
            self.stdout.write(self.style.SUCCESS(
                'Every active class already has a subject. Nothing to do.'
            ))
            return

        subjects = {s.slug: s for s in Subject.objects.filter(school__isnull=True)}
        resolved, skipped = [], []

        for classroom in classrooms:
            slugs = Counter(
                Homework.objects
                .filter(classroom=classroom, deleted_at__isnull=True)
                .values_list('subject_slug', flat=True)
            )
            slugs.pop('', None)

            if not slugs:
                subject, why = self._from_department(classroom)
                if subject is not None:
                    resolved.append((classroom, subject, why))
                else:
                    skipped.append((classroom, why))
            elif len(slugs) > 1:
                # Named, never guessed: only a human knows which one the class
                # actually teaches.
                spread = ', '.join(f'{s}×{n}' for s, n in slugs.most_common())
                skipped.append((classroom, f'homework spans {spread}'))
            else:
                slug = next(iter(slugs))
                subject = subjects.get(slug)
                if subject is None:
                    skipped.append((classroom, f'no global Subject with slug {slug!r}'))
                else:
                    resolved.append(
                        (classroom, subject, f'{slugs[slug]} homework'),
                    )

        for classroom, subject, why in resolved:
            self.stdout.write(
                f'  set   {classroom.name} -> {subject.name} ({why})'
            )
        for classroom, reason in skipped:
            self.stdout.write(self.style.WARNING(
                f'  skip  {classroom.name}: {reason}'
            ))

        if options['apply']:
            for classroom, subject, _why in resolved:
                classroom.subject = subject
                classroom.save(update_fields=['subject'])

        self.stdout.write('')
        self.stdout.write(
            f'{len(resolved)} {"updated" if options["apply"] else "would be updated"}, '
            f'{len(skipped)} left for a human.'
        )
        if not options['apply']:
            self.stdout.write(self.style.NOTICE(
                'Dry run — nothing written. Re-run with --apply.'
            ))
        if skipped:
            self.stdout.write(self.style.NOTICE(
                'Skipped classes need their subject set by hand on the class '
                'edit page; a wrong subject scopes a report to the wrong work.'
            ))
