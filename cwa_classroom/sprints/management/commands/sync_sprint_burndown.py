"""
Management command: sync_sprint_burndown

Records one burndown snapshot (story points remaining) for the active Jira
sprint on the configured board. A burndown is time-series and Jira only reports
each issue's *current* state, so this runs on a schedule to build up history.
The snapshot is upserted per (sprint, day), so running several times a day just
refreshes that day's point.

Run via cron 3x/day using scripts/cron_sync_sprint_burndown.sh, e.g.:
    0 8,14,22 * * * /home/cwa/.../scripts/cron_sync_sprint_burndown.sh

No-ops (logs a warning) when the Jira env / JIRA_BOARD_ID is unconfigured.
"""
from django.core.management.base import BaseCommand

from sprints import services


class Command(BaseCommand):
    help = "Record today's burndown snapshot for the active Jira sprint."

    def handle(self, *args, **options):
        snapshot = services.sync_active_sprint()
        if snapshot is None:
            self.stdout.write(self.style.WARNING(
                'No snapshot recorded (Jira unconfigured or no active sprint). '
                'See logs for detail.'
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f'Snapshot recorded for "{snapshot.sprint.name}" on '
            f'{snapshot.snapshot_date}: {snapshot.remaining_points:g} points '
            f'remaining of {snapshot.total_points:g}.'
        ))
