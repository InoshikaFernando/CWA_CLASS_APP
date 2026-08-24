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

    def handle(self, *args, **options):
        reference = self._reference_date(options.get('date'))
        windows = self._windows(options.get('period'), reference)

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

    def _report(self, period_type, counts, dry_run):
        prefix = 'Would generate' if dry_run else 'Generated'
        line = (
            f'{period_type}: {counts["period"]} — '
            f'{prefix} {counts["generated"]} report(s) for '
            f'{counts["students"]} student(s)'
        )
        if not dry_run:
            line += (
                f'; {counts["refreshed"]} already existed, '
                f'{counts["notified"]} notified, {counts["emailed"]} parent email(s)'
            )
        self.stdout.write(self.style.SUCCESS(line))
