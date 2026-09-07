#!/bin/bash
# cron_check_email_queue.sh — alert when queued email is not being delivered.
#
# Watchdog for the process_email_queue cron. That cron IS the delivery path for
# every invoice email, and when it stopped in June 2026 nothing noticed for ten
# weeks: 316 invoices sat queued while the app reported them as issued. This
# check posts to Discord as soon as the backlog ages past the threshold.
#
# Deliberately a separate cron from the drain: a watchdog that runs inside the
# thing it watches cannot report that thing being dead.
#
# Install (cron drop-in written by deploy/setup-app-prod.sh) — hourly:
#   0 * * * * /home/cwa/CWA_CLASS_APP/scripts/cron_check_email_queue.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/email_queue_health.log 2>&1

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP}"
ENV_FILE="${2:-/etc/cwa/cwa.env}"

# Load the app env (DB creds, FEEDBACK_DISCORD_WEBHOOK). The file is a systemd
# EnvironmentFile (plain KEY=value, values NOT shell-quoted) so it must NOT be
# `source`d — a value with shell metacharacters would break bash.
if [[ -f "$ENV_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
        [[ "$line" == *=* ]] || continue
        export "$line"
    done < "$ENV_FILE"
fi

cd "$APP_DIR"
source venv/bin/activate

# No-op cleanly until the command is deployed, so the cron can be staged early.
if ! python cwa_classroom/manage.py help check_email_queue_health >/dev/null 2>&1; then
    echo "check_email_queue_health not deployed yet — skipping."
    exit 0
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z')  ($APP_DIR) ====="

# The command exits non-zero when unhealthy, which is the alert itself; swallow
# it so cron does not also mail root about a "failed job".
python cwa_classroom/manage.py check_email_queue_health --quiet \
    --webhook "${FEEDBACK_DISCORD_WEBHOOK:-}" || true
