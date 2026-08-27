#!/bin/bash
# sync_expenses.sh — daily refresh of the income-vs-expense dashboard.
#
# Runs both expense cron commands for CWA Classroom:
#   1. materialize_recurring_expenses — books flat recurring templates (GoDaddy,
#      Claude Code, Resend, DO estimate) for any month not yet generated, and
#      syncs the Anthropic AI-usage cost from taskqueue.AIUsageLog.
#   2. sync_vendor_charges — pulls real vendor charges: AI usage again (cheap,
#      idempotent) + DigitalOcean invoices when DIGITALOCEAN_API_TOKEN is set
#      (the actual invoice supersedes the DO estimate for that month) + what
#      Anthropic and OpenAI actually billed, when ANTHROPIC_ADMIN_API_KEY /
#      OPENAI_ADMIN_API_KEY are set (each supersedes that month's token
#      estimate). A vendor with no admin key is reported as skipped and keeps
#      the estimate — the figure is never silently zeroed. Also GitHub's own
#      bill (Actions minutes, Packages, LFS, Copilot), using the GitHub
#      credentials already set for the AI-usage dashboard unless the
#      GITHUB_BILLING_* overrides say otherwise.
#
# GitHub invoices monthly like DigitalOcean, but its usage report is queried by
# calendar month and re-read for the last three each run, so a late line item is
# picked up rather than frozen at whatever the 1st happened to show.
#
# Idempotent and safe to re-run, so run DAILY: the Anthropic AI-usage cost
# accrues every day as students use AI features, so a monthly run left the
# current month's figure frozen between runs (the bug this addresses). A daily
# run keeps the current month current. DigitalOcean still invoices the prior
# month on the 1st, but a daily run picks that invoice up on the 2nd (and the
# sync is idempotent, so re-running on later days is a no-op).
#
# Install (crontab on the DO server) — 02:00 every day, TEST app:
#   0 2 * * * /home/cwa/CWA_CLASS_APP_TEST/scripts/sync_expenses.sh >> /var/log/cwa/sync_expenses.log 2>&1
#
# For PROD, pass the prod app dir + env file as args:
#   0 2 * * * /home/cwa/CWA_CLASS_APP/scripts/sync_expenses.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/sync_expenses.log 2>&1

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP_TEST}"
ENV_FILE="${2:-/etc/cwa/cwa-test.env}"

# Load the app env (DB creds, DIGITALOCEAN_API_TOKEN, FX/USD rate, etc.),
# exported so manage.py's Python child sees them — same vars systemd injects.
#
# The file is a systemd EnvironmentFile (plain KEY=value; values are NOT
# shell-quoted), so it must NOT be `source`d: a value containing shell
# metacharacters (e.g. a secret with ')') makes bash abort with a syntax
# error. Read it line by line and export each assignment verbatim instead, so
# the value is never interpreted by the shell — matching systemd's semantics.
if [[ -f "$ENV_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue  # skip comments/blanks
        [[ "$line" == *=* ]] || continue                 # skip non-assignments
        export "$line"
    done < "$ENV_FILE"
fi

cd "$APP_DIR"
source venv/bin/activate

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z')  ($APP_DIR) ====="
python cwa_classroom/manage.py materialize_recurring_expenses
python cwa_classroom/manage.py sync_vendor_charges
echo
