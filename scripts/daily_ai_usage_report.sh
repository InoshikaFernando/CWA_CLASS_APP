#!/bin/bash
# daily_ai_usage_report.sh — daily AI usage / cost summary for CWA Classroom.
#
# Prints the AI classification spend (pages, tokens, cost, $/page by source) for
# the last day and the rolling 30 days, so cost-vs-what-you-charge is visible
# without SSHing in to run it by hand. Read-only; safe to run any time.
#
# This is the DAILY summary. Per-call cost is already logged by the worker after
# every upload (see taskqueue.services.record_ai_usage) — grep the worker log:
#   journalctl -u cwa-rqworker-test.service | grep 'AI usage:'
#
# Install (crontab on the DO server) — 08:00 daily for the TEST app:
#   0 8 * * * /home/cwa/CWA_CLASS_APP_TEST/scripts/daily_ai_usage_report.sh >> /var/log/cwa/ai_usage_report.log 2>&1
#
# For PROD, pass the prod app dir + env file as args:
#   0 8 * * * /home/cwa/CWA_CLASS_APP/scripts/daily_ai_usage_report.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/ai_usage_report.log 2>&1
#
# Optional: set AI_USAGE_REPORT_WEBHOOK (Discord/Slack incoming webhook) in the
# env file to also push the summary to a channel.

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP_TEST}"
ENV_FILE="${2:-/etc/cwa/cwa-test.env}"

# Load the app env (DB creds etc.), exported so manage.py's Python child sees
# them — same vars systemd injects via EnvironmentFile.
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

cd "$APP_DIR"
source venv/bin/activate

REPORT="$(python cwa_classroom/manage.py ai_usage_report --days 1)

$(python cwa_classroom/manage.py ai_usage_report --days 30)"

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z')  ($APP_DIR) ====="
echo "$REPORT"
echo

# Optional Discord/Slack push if a webhook is configured.
if [[ -n "${AI_USAGE_REPORT_WEBHOOK:-}" ]]; then
    PAYLOAD=$(python - "$REPORT" <<'PY'
import json, sys
print(json.dumps({"content": "```\n" + sys.argv[1][:1900] + "\n```"}))
PY
)
    curl -fsS -H 'Content-Type: application/json' -d "$PAYLOAD" \
        "$AI_USAGE_REPORT_WEBHOOK" >/dev/null || true
fi
