"""
Seed the standard Code Wizards "All-Subjects" progress criteria for a school.

These are subject-agnostic learning behaviours (Focus & Engagement, Problem
Solving, ...), so each row is created with ``subject = None`` ("All Subjects",
see SPEC_TEACHER_CLASS_STUDENT_PROGRESS §12.6) and ``level = None`` (all levels).
The 7 categories become top-level criteria; their bullet points become
sub-criteria (children). Everything is created ``approved`` so it is immediately
usable for recording progress.

Idempotent: re-running only fills in anything missing (matched on
school + name + parent). Safe to re-run.

Usage:
    python manage.py seed_code_wizards_criteria --school <id|slug|name>
    python manage.py seed_code_wizards_criteria --school code-wizards-aotearoa --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from classroom.models import ProgressCriteria, School


# (category, [sub-criteria]) in display order.
CRITERIA = [
    ('Focus & Engagement', [
        'Pays attention during lessons',
        'Stays on task and uses learning time well',
        'Participates actively in activities',
        'Shows curiosity and willingness to learn',
    ]),
    ('Problem Solving', [
        'Understands problems before starting',
        'Breaks challenges into smaller steps',
        'Tries different strategies',
        'Keeps trying when facing difficulties',
    ]),
    ('Logical Thinking', [
        'Identifies patterns and relationships',
        'Thinks step-by-step',
        'Makes connections between ideas',
        'Explains reasoning clearly',
    ]),
    ('Independence', [
        'Follows instructions independently',
        'Uses resources effectively',
        'Attempts solutions before asking for help',
        'Takes responsibility for own learning',
    ]),
    ('Accuracy & Improvement', [
        'Checks work carefully',
        'Learns from mistakes',
        'Corrects errors and improves solutions',
        'Pays attention to details',
    ]),
    ('Creativity & Application', [
        'Creates original ideas and solutions',
        'Applies skills to new situations',
        'Experiments and explores different approaches',
        'Builds confidence in sharing ideas',
    ]),
    ('Communication & Collaboration', [
        'Explains thinking clearly',
        'Listens to others',
        'Works well with classmates',
        'Gives and receives feedback',
    ]),
]


class Command(BaseCommand):
    help = 'Seed the standard Code Wizards All-Subjects progress criteria for a school.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--school', required=True,
            help='School to seed: numeric id, slug, or (unambiguous) name.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be created without making changes.',
        )

    def _resolve_school(self, identifier):
        if identifier.isdigit():
            school = School.objects.filter(pk=int(identifier)).first()
            if school:
                return school
        school = School.objects.filter(slug=identifier).first()
        if school:
            return school
        matches = list(School.objects.filter(name__icontains=identifier)[:5])
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise CommandError(f'No school found matching "{identifier}".')
        names = ', '.join(f'{s.id}:{s.name}' for s in matches)
        raise CommandError(
            f'"{identifier}" is ambiguous — matches: {names}. '
            f'Re-run with a numeric id or exact slug.'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        school = self._resolve_school(options['school'])

        self.stdout.write(f'Seeding All-Subjects criteria for: {school.name} (id={school.id})')

        created_parents = created_children = 0

        with transaction.atomic():
            for p_order, (category, children) in enumerate(CRITERIA, start=1):
                parent, p_created = self._get_or_create(
                    school, name=category, parent=None, order=p_order, dry_run=dry_run,
                )
                if p_created:
                    created_parents += 1
                    self.stdout.write(
                        f'  {"[would add] " if dry_run else "+ "}{category}'
                    )

                # In a dry run a brand-new parent has no pk, so children can't be
                # linked — report them as "would add" and move on.
                for c_order, child_name in enumerate(children, start=1):
                    if dry_run and parent is None:
                        created_children += 1
                        self.stdout.write(f'      [would add] {child_name}')
                        continue
                    _, c_created = self._get_or_create(
                        school, name=child_name, parent=parent,
                        order=c_order, dry_run=dry_run,
                    )
                    if c_created:
                        created_children += 1
                        self.stdout.write(
                            f'      {"[would add] " if dry_run else "+ "}{child_name}'
                        )

            if dry_run:
                # Don't persist anything on a dry run.
                transaction.set_rollback(True)

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Done. {created_parents} categories + {created_children} '
            f'sub-criteria {"would be " if dry_run else ""}created.'
        ))

    def _get_or_create(self, school, *, name, parent, order, dry_run):
        """Return (obj_or_None, created_bool). On dry-run, never writes."""
        existing = ProgressCriteria.objects.filter(
            school=school, name=name, parent=parent,
        ).first()
        if existing:
            return existing, False
        if dry_run:
            return None, True
        obj = ProgressCriteria.objects.create(
            school=school,
            subject=None,   # All Subjects
            level=None,     # All Levels
            parent=parent,
            name=name,
            order=order,
            status='approved',
        )
        return obj, True
