#!/bin/bash
# sync_expenses.sh — monthly refresh of the income-vs-expense dashboard.
#
# Runs both expense cron commands for CWA Classroom:
#   1. materialize_recurring_expenses — books flat recurring templates (GoDaddy,
#      Claude Code, Resend, DO estimate) for any month not yet generated, and
#      syncs the Anthropic AI-usage cost from taskqueue.AIUsageLog.
#   2. sync_vendor_charges — pulls real vendor charges: AI usage again (cheap,
#      idempotent) + DigitalOcean invoices when DIGITALOCEAN_API_TOKEN is set
#      (the actual invoice supersedes the DO estimate for that month).
#
# Idempotent and safe to re-run. Run monthly, on the 2nd (DO invoices the prior
# month on the 1st, so the 2nd guarantees the invoice exists).
#
# Install (crontab on the DO server) — 02:00 on the 2nd of each month, TEST app:
#   0 2 2 * * /home/cwa/CWA_CLASS_APP_TEST/scripts/sync_expenses.sh >> /var/log/cwa/sync_expenses.log 2>&1
#
# For PROD, pass the prod app dir + env file as args:
#   0 2 2 * * /home/cwa/CWA_CLASS_APP/scripts/sync_expenses.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/sync_expenses.log 2>&1

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP_TEST}"
ENV_FILE="${2:-/etc/cwa/cwa-test.env}"

# Load the app env (DB creds, DIGITALOCEAN_API_TOKEN, FX/USD rate, etc.),
# exported so manage.py's Python child sees them — same vars systemd injects.
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

cd "$APP_DIR"
source venv/bin/activate

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z')  ($APP_DIR) ====="
python cwa_classroom/manage.py materialize_recurring_expenses
python cwa_classroom/manage.py sync_vendor_charges
echo
