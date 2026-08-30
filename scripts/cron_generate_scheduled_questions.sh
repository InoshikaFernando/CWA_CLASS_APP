#!/bin/bash
# cron_generate_scheduled_questions.sh — droplet-side cron that builds the
# homework a question schedule's teaching plan is due to produce (CPP-399).
#
# Runs `manage.py generate_scheduled_questions`. Each set it creates has a
# FUTURE publish_at, so nothing reaches a student from this script alone —
# cron_... / `publish_scheduled_homework` publishes it when the release time
# arrives. WITHOUT THIS CRON a teacher's plan silently produces nothing: the
# weeks stay 'pending' and the class gets no homework, with no error anywhere.
#
# Taking APP_DIR as an argument is the guard against the failure that cost
# production ten weeks of undelivered invoice email — a crontab entry pointing
# at the wrong checkout, so the environment it was meant to serve had no runner
# at all. The drop-in written by deploy/setup-app-prod.sh passes the app it
# belongs to, so the path cannot silently drift.
#
# Runs under flock so two ticks can never generate concurrently. generate_week()
# is idempotent per week, so an overlap would not double-create — but a second
# run starting mid-pass would still redo the repeat-avoidance queries against a
# half-written picture, and the lock is cheaper than reasoning about that.
#
# Use this script for manual runs too, so an operator run and a cron tick
# contend for the same lock instead of racing.
#
# Install (cron drop-in written by deploy/setup-app-prod.sh) — daily at 02:15:
#   15 2 * * * /home/cwa/CWA_CLASS_APP/scripts/cron_generate_scheduled_questions.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/scheduled_questions.log 2>&1

set -euo pipefail

# Re-exec under an exclusive lock keyed on the app dir, so the test and
# production checkouts never block each other. -n exits immediately rather than
# queueing ticks behind a long run.
LOCK_FILE="/tmp/cwa-scheduled-questions-$(echo "${1:-default}" | tr '/' '_').lock"
if [[ "${_CWA_SCHED_Q_LOCKED:-}" != "1" ]]; then
    export _CWA_SCHED_Q_LOCKED=1
    # -E 99 distinguishes "could not get the lock" from the run's own exit code,
    # so a skipped tick is reported as a skip and a real failure still surfaces
    # its status to cron. Not `exec`: that would replace this shell and the
    # contention branch below could never run, making a skip silent.
    set +e
    flock -n -E 99 "$LOCK_FILE" "$0" "$@"
    rc=$?
    set -e
    if [[ $rc -eq 99 ]]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') another generation run is still going — skipping this tick."
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

python cwa_classroom/manage.py generate_scheduled_questions "${@:3}"
