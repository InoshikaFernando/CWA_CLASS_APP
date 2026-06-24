"""
Management command: sync_sprint_burndown

Records burndown snapshots from Jira. A burndown is time-series and Jira only
reports each issue's *current* state, so this runs on a schedule to build up
history. Snapshots are upserted per day, so running several times a day just
refreshes that day's point.

It records two things each run:
  * a **whole-project** snapshot (story points remaining across the project) —
    this is what the /sprints/burndown/ page shows; and
  * the **active-sprint** snapshot (if a board/active sprint is configured) —
    kept for per-sprint history.

Run via cron 3x/day using scripts/cron_sync_sprint_burndown.sh, e.g.:
    0 8,14,22 * * * /home/cwa/.../scripts/cron_sync_sprint_burndown.sh

No-ops (logs a warning) when the Jira env is unconfigured.
"""
from django.core.management.base import BaseCommand

from sprints import services


class Command(BaseCommand):
    help = "Record today's whole-project (and active-sprint) burndown snapshots."

    def handle(self, *args, **options):
        # Whole-project snapshot — the figure the burndown page renders.
        project = services.sync_project_burndown()
        if project is None:
            self.stdout.write(self.style.WARNING(
                'No project snapshot recorded (Jira unconfigured or search '
                'failed). See logs for detail.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Project snapshot on {project.snapshot_date}: '
                f'{project.remaining_points:g} points remaining of '
                f'{project.total_points:g} ({project.open_issue_count} open).'
            ))

        # Active-sprint snapshot — kept for per-sprint history; no-op if no board.
        sprint = services.sync_active_sprint()
        if sprint is not None:
            self.stdout.write(self.style.SUCCESS(
                f'Sprint snapshot for "{sprint.sprint.name}" on '
                f'{sprint.snapshot_date}: {sprint.remaining_points:g} of '
                f'{sprint.total_points:g}.'
            ))
