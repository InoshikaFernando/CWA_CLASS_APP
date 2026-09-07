"""Make ``Topic.levels`` for the times tables agree with the curriculum.

Why this exists
---------------
Two different things decide which times tables a student sees, and they had
drifted apart:

* the times-tables QUIZ picker reads ``TIMES_TABLES_BY_YEAR``;
* the year accordion on ``/maths/`` and the Mixed Quiz read ``Topic.levels``
  from the database (``maths/views.py`` filters ``Topic.objects.filter(
  levels=level)``; ``quiz.views.MixedQuizView`` draws its pool from
  ``level.topics.all()``).

So a "Multiplication (7x)" topic linked to Year 3 puts 7x in a nine-year-old's
mixed quiz no matter what the constant says. The links got that way honestly:
the maths tree carried a duplicate set of times tables under their own
``Multiplication``/``Division`` strands, the two sets were linked to different
years, and merging them unions the links — which is right for not losing data
and wrong for the curriculum.

This command makes the database say what ``TIMES_TABLES_BY_YEAR`` says.

What it does NOT do
-------------------
It never deletes a Topic and never touches a Question. A table no year reaches
keeps its topic row and its questions; it just stops appearing at any year. So
the change is reversible by editing the constant and running this again.

It also leaves every non-times-table topic alone. Only rows named exactly
``Multiplication (Nx)`` or ``Division (Nx)`` are touched.

Usage
-----
    python manage.py set_times_table_years --dry-run
    python manage.py set_times_table_years
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

SUBJECT_SLUG = 'mathematics'

#: "Multiplication (7x)" / "Division (12x)". The x is U+00D7, the character the
#: seed data and the merge plan both use; matching a plain ASCII "x" as well
#: costs nothing and stops a hand-typed row being silently skipped.
NAME_RE = re.compile(r'^(Multiplication|Division)\s*\((\d+)\s*[×x]\)$',
                     re.IGNORECASE)


class Command(BaseCommand):
    help = ('Reset Topic.levels for the times tables so the year pages and the '
            'mixed quiz offer what TIMES_TABLES_BY_YEAR says they should.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change, write nothing.')

    def handle(self, *args, **opts):
        from classroom.models import Level, Subject, Topic
        from maths.constants import TIMES_TABLES_BY_YEAR, times_tables_for_year

        subject = (Subject.objects.filter(slug=SUBJECT_SLUG).first()
                   or Subject.objects.filter(name__iexact='Mathematics').first())
        if subject is None:
            raise CommandError('No Mathematics subject in this database.')

        dry = opts['dry_run']
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'=== set_times_table_years — {subject.name}'
            f'{"  [DRY RUN]" if dry else ""} ==='))

        # Year levels only. Basic facts live at 100+ and are a different ladder
        # entirely — linking a times table to them would put drill topics in a
        # curriculum year page, which is the confusion this command exists to
        # end rather than to spread.
        year_levels = {
            level.level_number: level
            for level in Level.objects.filter(level_number__lt=100)
        }
        if not year_levels:
            raise CommandError('No year levels (level_number < 100) found.')

        wanted = {}   # table number -> set of year numbers
        for year in year_levels:
            for table in times_tables_for_year(year):
                wanted.setdefault(table, set()).add(year)

        topics = (Topic.objects.filter(subject=subject)
                  .prefetch_related('levels').order_by('name'))

        changed = unchanged = skipped_no_year = 0
        retired = []

        with transaction.atomic():
            for topic in topics:
                match = NAME_RE.match(topic.name or '')
                if match is None:
                    continue
                table = int(match.group(2))

                want_years = wanted.get(table, set())
                # Year links only. A times table linked to a basic-facts level
                # is not this command's business, and dropping it here would be
                # a deletion nobody asked for.
                have = {lv.level_number for lv in topic.levels.all()}
                have_years = {n for n in have if n < 100}

                if have_years == want_years:
                    unchanged += 1
                    continue

                added = sorted(want_years - have_years)
                removed = sorted(have_years - want_years)
                self.stdout.write(
                    f'  [{topic.id}] {topic.name}: '
                    + (f'+{added} ' if added else '')
                    + (f'-{removed}' if removed else ''))

                if not dry:
                    if removed:
                        topic.levels.remove(
                            *[year_levels[n] for n in removed])
                    if added:
                        topic.levels.add(*[year_levels[n] for n in added])

                changed += 1
                if not want_years:
                    # Not an error and not a deletion: no year in the current
                    # curriculum reaches this table, so it is off the year
                    # pages until the constant says otherwise. Named rather
                    # than left for someone to notice from a topic count.
                    retired.append(f'{topic.name} (table {table})')
                if not have_years:
                    skipped_no_year += 1

            if dry:
                transaction.set_rollback(True)

        self.stdout.write('')
        if retired:
            self.stdout.write(self.style.WARNING(
                f'{len(retired)} topic(s) now reach no year — the row and its '
                f'questions are kept, they are simply off every year page:'))
            for name in retired:
                self.stdout.write(f'    {name}')
            self.stdout.write('')

        self.stdout.write(self.style.SUCCESS(
            f'{"Would change" if dry else "Changed"} {changed} topic(s); '
            f'{unchanged} already correct.'))
        self.stdout.write(
            'Curriculum: ' + ', '.join(
                f'Y{year}={TIMES_TABLES_BY_YEAR[year]}'
                for year in sorted(TIMES_TABLES_BY_YEAR)))
        if dry:
            self.stdout.write('Nothing was written.  [DRY RUN]')
