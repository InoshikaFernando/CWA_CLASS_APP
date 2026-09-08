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
# Runs under flock so two ticks can never drain concurrently. The command has
# no locking of its own: it materialises the pending rows, then marks each one
# sent only after its send returns. A second run starting mid-loop would pick up
# every row the first had not reached yet and send it AGAIN. That is not
# theoretical on a backlog — clearing a few hundred queued emails takes longer
# than the two-minute tick once the provider starts rate-limiting, so the second
# tick would land mid-drain and double-send invoices to families.
#
# Use this script for manual drains too, so an operator run and a cron tick
# contend for the same lock instead of racing.
#
# Install (cron drop-in written by deploy/setup-app-prod.sh) — every 2 min:
#   */2 * * * * /home/cwa/CWA_CLASS_APP/scripts/cron_process_email_queue.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/email_queue.log 2>&1

set -euo pipefail

# Re-exec under an exclusive lock keyed on the app dir, so the test and
# production checkouts never block each other. -n exits immediately rather than
# queueing ticks behind a long drain.
LOCK_FILE="/tmp/cwa-email-queue-$(echo "${1:-default}" | tr '/' '_').lock"
if [[ "${_CWA_EMAIL_LOCKED:-}" != "1" ]]; then
    export _CWA_EMAIL_LOCKED=1
    # -E 99 distinguishes "could not get the lock" from the drain's own exit
    # code, so a skipped tick is reported as a skip and a real failure still
    # surfaces its status to cron. Not `exec`: that would replace this shell and
    # the contention branch below could never run, making a skip silent.
    set +e
    flock -n -E 99 "$LOCK_FILE" "$0" "$@"
    rc=$?
    set -e
    if [[ $rc -eq 99 ]]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') another drain is still running — skipping this tick."
        exit 0
    fi
    exit $rc
fi

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
