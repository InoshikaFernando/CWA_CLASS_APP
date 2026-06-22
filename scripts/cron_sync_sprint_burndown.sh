#!/bin/bash
# cron_sync_sprint_burndown.sh — daily Jira sprint burndown snapshot for CWA.
#
# Records one SprintSnapshot (story points remaining) for the active Jira sprint
# on the configured board. A burndown is time-series and Jira only reports each
# issue's *current* state, so this MUST run daily to accumulate history — the
# in-app chart (/sprints/burndown/) reads back these stored snapshots.
#
# No-ops (logs a warning, exits 0) when the Jira env / JIRA_BOARD_ID is unset,
# so it's safe to install before Jira is configured.
#
# A snapshot is upserted per (sprint, day), so running multiple times a day just
# refreshes that day's point — the last run of the day is the one kept for the
# date. We run 3x/day (08:00, 14:00, 22:00) to keep the chart current intraday.
#
# Install (crontab on the DO server) — 3x daily for the TEST app:
#   0 8,14,22 * * * /home/cwa/CWA_CLASS_APP_TEST/scripts/cron_sync_sprint_burndown.sh >> /var/log/cwa/sprint_burndown.log 2>&1
#
# For PROD, pass the prod app dir + env file as args:
#   0 8,14,22 * * * /home/cwa/CWA_CLASS_APP/scripts/cron_sync_sprint_burndown.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/sprint_burndown.log 2>&1
#
# Required env (in the env file): JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN,
# JIRA_BOARD_ID, and JIRA_STORY_POINTS_FIELD if your instance differs from the
# customfield_10016 default.

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP_TEST}"
ENV_FILE="${2:-/etc/cwa/cwa-test.env}"

# Load the app env (DB + Jira creds etc.), exported so manage.py's Python child
# sees them — same vars systemd injects via EnvironmentFile.
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

cd "$APP_DIR"
source venv/bin/activate

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z')  ($APP_DIR) ====="
python cwa_classroom/manage.py sync_sprint_burndown
