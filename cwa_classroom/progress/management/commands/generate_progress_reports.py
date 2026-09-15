"""Generate end-of-period progress reports and deliver them (CPP-388).

Run daily from cron; the command works out which periods actually closed on the
given date, so the schedule is one line rather than three:

    10 6 * * * cd /home/cwa/CWA_CLASS_APP && \
      /home/cwa/CWA_CLASS_APP/venv/bin/python cwa_classroom/manage.py generate_progress_reports

Idempotent — reports key on (student, period_type, period_start) and delivery is
stamped, so a re-run never re-notifies a family.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from progress import periods
from progress.services import run_period


class Command(BaseCommand):
    help = 'Generate weekly / monthly / term progress reports for closed periods.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--period', choices=[periods.WEEKLY, periods.MONTHLY, periods.TERM],
            help=(
                'Force one period type, reporting the most recently closed '
                'window. Omit to generate whatever actually closed on --date.'
            ),
        )
        parser.add_argument(
            '--date', help='Reference date (YYYY-MM-DD). Defaults to today.',
        )
        parser.add_argument(
            '--force', action='store_true',
            help=(
                'Recompute existing reports\' data. Delivery timestamps are '
                'left alone, so this never re-notifies.'
            ),
        )
        parser.add_argument(
            '--no-notify', action='store_true',
            help='Generate the reports but send nothing.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be generated without writing anything.',
        )
        parser.add_argument(
            '--school', help='Limit to one school, by id or slug.',
        )
        parser.add_argument(
            '--manual', action='store_true',
            help=(
                'Run the classes set to manual instead of the automatic ones. '
                'Normally a staff member does this from the Report Automation '
                'page; this is the same path, for scripting and support.'
            ),
        )
        parser.add_argument(
            '--classroom', type=int,
            help=(
                'Limit to one class, by id. Use with --dry-run to see exactly '
                'what a class would produce before switching it on for real.'
            ),
        )

    def handle(self, *args, **options):
        reference = self._reference_date(options.get('date'))
        windows = self._windows(options.get('period'), reference)
        school = self._school(options.get('school'))
        classroom = self._classroom(options.get('classroom'))

        if not windows:
            # A run on a Tuesday that is not the day after a term end is a
            # legitimate no-op, not a failure — but say so rather than exiting
            # silently, which reads identically to a broken cron.
            self.stdout.write(
                f'No period closed on {reference:%Y-%m-%d} — nothing to generate.'
            )
            return

        for period_type, start, end, term in windows:
            counts = run_period(
                period_type, start, end, term=term,
                force=options['force'],
                dry_run=options['dry_run'],
                notify=not options['no_notify'],
                school=school,
                classroom=classroom,
                # The daily tick serves the automatic classes only, and only
                # those whose configured day is today. Manual classes wait for
                # a person, which is the default and the point.
                mode=(
                    periods.MODE_MANUAL if options['manual']
                    else periods.MODE_AUTO
                ),
                reference=None if options['manual'] else reference,
            )
            self._report(period_type, counts, dry_run=options['dry_run'])

    # -- helpers ---------------------------------------------------------

    def _reference_date(self, raw):
        if not raw:
            return periods.today()
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            raise CommandError(f'--date must be YYYY-MM-DD, got {raw!r}')

    def _windows(self, forced, reference):
        """The (period_type, start, end, term) tuples this run covers."""
        if not forced:
            return periods.due_periods(reference)

        if forced == periods.TERM:
            terms = periods.most_recent_ended_terms(reference)
            if not terms:
                raise CommandError(
                    f'No term has ended before {reference:%Y-%m-%d}, so there '
                    f'is no term window to report.'
                )
            return [(periods.TERM, t.start_date, t.end_date, t) for t in terms]

        start, end = periods.window_for(forced, reference)
        return [(forced, start, end, None)]

    def _school(self, raw):
        from classroom.models import School

        if not raw:
            return None
        school = (
            School.objects.filter(pk=raw).first() if str(raw).isdigit()
            else School.objects.filter(slug=raw).first()
        )
        if school is None:
            raise CommandError(f'No school matches {raw!r} (tried id and slug).')
        return school

    def _classroom(self, raw):
        from classroom.models import ClassRoom

        if not raw:
            return None
        classroom = ClassRoom.objects.filter(pk=raw).first()
        if classroom is None:
            raise CommandError(f'No class with id {raw}.')
        return classroom

    def _report(self, period_type, counts, dry_run):
        if not counts['classes']:
            # The normal state before anyone opts in — or a day no automatic
            # schedule lands on. Said out loud, because silence here is
            # indistinguishable from a broken cron.
            self.stdout.write(
                f'{period_type}: {counts["period"]} — no class is scheduled to '
                f'send a {period_type} report today; nothing to do.'
            )
            return

        prefix = 'Would generate' if dry_run else 'Generated'
        line = (
            f'{period_type}: {counts["period"]} — '
            f'{prefix} {counts["generated"]} report(s) for '
            f'{counts["students"]} student(s) across '
            f'{counts["classes"]} class(es)'
        )
        if not dry_run:
            line += (
                f'; {counts["refreshed"]} already existed, '
                f'{counts["notified"]} notified, {counts["emailed"]} parent email(s)'
            )
        self.stdout.write(self.style.SUCCESS(line))
        self._report_notices(counts, dry_run)

    def _report_notices(self, counts, dry_run):
        """The whole-school half of the run (CPP-422).

        Printed on its own line rather than folded into the one above, because
        it answers a different question — not "how did the students who are
        reporting do" but "who had nothing to show, and why". A school that has
        not switched whole-school coverage on has a zero cohort and gets no
        line at all; that is the default, not a failure.
        """
        if not counts.get('notices'):
            return

        by_reason = counts.get('notices_by_reason') or {}
        breakdown = ', '.join(
            f'{number} {reason.replace("_", " ")}'
            for reason, number in sorted(by_reason.items())
            if number
        )
        if dry_run:
            # See run_period: a dry run cannot know who was active, so this is
            # the students no enabled class holds — a floor, and saying so is
            # the difference between a caveat and a wrong number.
            self.stdout.write(
                f'  whole school: at least {counts["notices"]} student(s) would '
                f'have nothing to show ({breakdown}). A dry run does not compute '
                f'activity, so the real figure is this or higher.'
            )
            return

        line = (
            f'  whole school: {counts["notices"]} student(s) with nothing to '
            f'show ({breakdown}); {counts["notices_emailed"]} note(s) sent to '
            f'{counts["notices_recipients"]} parent address(es)'
        )
        if counts.get('notices_undelivered'):
            # Never silent: a note recorded but delivered to nobody is the
            # failure this feature exists to prevent, not a rounding error.
            line += (
                f'; {counts["notices_undelivered"]} reached nobody '
                f'(no parent email on file, or delivery failed)'
            )
        self.stdout.write(self.style.SUCCESS(line))
