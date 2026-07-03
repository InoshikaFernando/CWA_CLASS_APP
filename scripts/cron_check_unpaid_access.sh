#!/bin/bash
# cron_check_unpaid_access.sh — alert if any delinquent-subscription user
# reached restricted pages while unpaid (see the billing check_unpaid_access
# management command). Posts leaks to FEEDBACK_DISCORD_WEBHOOK.
#
# Mirrors cron_sync_sprint_burndown.sh: pass the app dir + env file as args.
#
# Install (crontab on the DO server) — daily 09:00, PROD:
#   0 9 * * * /home/cwa/CWA_CLASS_APP/scripts/cron_check_unpaid_access.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/unpaid_access.log 2>&1
#
# Safe to install BEFORE the command ships: it no-ops (exit 0) until
# check_unpaid_access is deployed, so the cron can be staged early.

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP}"
ENV_FILE="${2:-/etc/cwa/cwa.env}"
DAYS="${3:-1}"

# Best-effort load of the env file for FEEDBACK_DISCORD_WEBHOOK (and any DB
# extras). Never abort the run on a parse error — systemd-style env files aren't
# always valid bash. The Django app reads its own DB config from
# cwa_classroom/.env via python-dotenv regardless of the shell.
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE" 2>/dev/null || true
    set +a
fi

cd "$APP_DIR"
source venv/bin/activate

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z')  ($APP_DIR) ====="

# No-op cleanly until the command is deployed (lets the cron be installed early).
if ! python cwa_classroom/manage.py help check_unpaid_access >/dev/null 2>&1; then
    echo "check_unpaid_access not deployed yet — skipping."
    exit 0
fi

# --webhook posts leaks to Discord; the command also exits non-zero on a leak,
# which we swallow (|| true) so cron doesn't treat a detected leak as a job error.
python cwa_classroom/manage.py check_unpaid_access --days "$DAYS" \
    --webhook "${FEEDBACK_DISCORD_WEBHOOK:-}" || true
