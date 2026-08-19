#!/bin/bash
# cron_process_email_queue.sh — droplet-side cron that delivers queued email.
#
# Runs `manage.py process_email_queue`, which drains classroom.EmailQueue.
# Every invoice email is force-queued at issue time (see invoicing_services
# .issue_invoices), so WITHOUT THIS CRON NO INVOICE IS EVER DELIVERED — the
# invoice is marked issued, the row sits in EmailQueue as 'pending', and
# nothing surfaces the backlog. That is not hypothetical: production accrued
# 316 undelivered invoice emails over ten weeks because the only crontab entry
# for this command pointed at the CWA_CLASS_APP_TEST directory instead of the
# production one, so the production queue had no drainer at all.
#
# Taking APP_DIR as an argument is the guard against a repeat: the drop-in
# written by deploy/setup-app-prod.sh passes the app it belongs to, so the
# path cannot silently drift to a different checkout.
#
# Install (cron drop-in written by deploy/setup-app-prod.sh) — every 2 min:
#   */2 * * * * /home/cwa/CWA_CLASS_APP/scripts/cron_process_email_queue.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/email_queue.log 2>&1

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP}"
ENV_FILE="${2:-/etc/cwa/cwa.env}"

# Load the app env (DB creds etc.). The file is a systemd EnvironmentFile (plain
# KEY=value, values NOT shell-quoted) so it must NOT be `source`d — a value with
# shell metacharacters would break bash. Export each assignment verbatim instead.
if [[ -f "$ENV_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
        [[ "$line" == *=* ]] || continue
        export "$line"
    done < "$ENV_FILE"
fi

cd "$APP_DIR"
source venv/bin/activate

python cwa_classroom/manage.py process_email_queue
