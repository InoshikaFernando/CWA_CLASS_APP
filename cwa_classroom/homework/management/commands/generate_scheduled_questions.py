"""
Build the homework sets that a question schedule's teaching plan is due to
produce (CPP-399).

Run via cron once a day (see cwa_classroom/MANAGEMENT_COMMANDS.md):
    15 2 * * * /home/cwa/CWA_CLASS_APP/scripts/cron_generate_scheduled_questions.sh \
        /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/scheduled_questions.log 2>&1

Each generated homework has a FUTURE ``publish_at``, so this command never
makes anything visible to a student on its own — ``publish_scheduled_homework``
does that when the release time arrives. The gap between the two is the
teacher's preview window.

Idempotent: a week that already points at a homework is skipped, so re-running
after a partial failure (or a cron tick overlapping a manual run) can never give
a class two sets for the same week.
"""

from datetime import datetime, time as datetime_time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from homework import schedule_services as svc
from homework.models import ScheduleWeek


class Command(BaseCommand):
    help = 'Generate homework for question-schedule weeks whose build time has arrived.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be generated without writing anything.',
        )
        parser.add_argument(
            '--schedule', type=int, default=None,
            help='Limit to a single QuestionSchedule id.',
        )
        parser.add_argument(
            '--as-of', default=None,
            help=('Pretend "now" is this date (YYYY-MM-DD), for rehearsing a '
                  'future run. Combine with --dry-run.'),
        )

    def handle(self, *args, **options):
        now = self._resolve_now(options.get('as_of'))
        dry_run = options['dry_run']
        results = svc.run_due(now, schedule_id=options['schedule'], dry_run=dry_run)

        if not results:
            self.stdout.write('No schedule weeks are due.')
            return

        counts = {}
        for result in results:
            counts[result.status] = counts.get(result.status, 0) + 1
            week = result.week
            line = (f'{week.schedule.classroom.name} / {week.schedule.name} '
                    f'week {week.week_number} ({week.week_start_date}): '
                    f'{result.status}')
            if result.message:
                line += f' — {result.message}'
            if result.status == ScheduleWeek.STATUS_GENERATED:
                self.stdout.write(self.style.SUCCESS(line))
            elif result.status in (ScheduleWeek.STATUS_NO_CONTENT, ScheduleWeek.STATUS_ERROR):
                # Surfaced as an error line, not swallowed: a plan that quietly
                # sets nothing is the failure mode this feature must never have.
                self.stderr.write(self.style.ERROR(line))
            else:
                self.stdout.write(line)

        summary = ', '.join(f'{n} {status}' for status, n in sorted(counts.items()))
        prefix = 'Dry run: ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(f'{prefix}{summary}.'))

    def _resolve_now(self, as_of):
        if not as_of:
            return timezone.now()
        try:
            day = datetime.strptime(as_of, '%Y-%m-%d').date()
        except ValueError as exc:
            raise CommandError('--as-of must be a date as YYYY-MM-DD.') from exc
        # End of the named day, so "as of 7 Sep" means everything due on or
        # before the 7th rather than only what was due before midnight.
        return timezone.make_aware(
            datetime.combine(day, datetime_time(23, 59, 59)),
            timezone.get_current_timezone(),
        )
