#!/bin/bash
# cron_generate_progress_reports.sh — droplet-side cron that closes each period.
#
# Runs `manage.py generate_progress_reports`, which builds the weekly / monthly /
# term progress reports for whichever period actually closed today and delivers
# them (in-app notification to student + parents; an email to parents at term
# end). WITHOUT THIS CRON NO REPORT IS EVER GENERATED — nothing else calls the
# generator, and its absence is invisible: the reports page simply stays empty,
# which reads as "no activity yet" rather than as a broken job.
#
# Taking APP_DIR as an argument follows cron_process_email_queue.sh: the drop-in
# written by deploy/setup-app-prod.sh passes the app it belongs to, so the path
# cannot silently drift to a different checkout (which is exactly how the
# production email queue went undrained for ten weeks).
#
# Runs under flock so two ticks can never generate concurrently. Generation is
# idempotent — reports key on (student, period_type, period_start) and delivery
# is stamped — but a manual run overlapping the cron tick would double the
# database work for no gain, and on a term-end morning both would be walking
# every student in the institute.
#
# Install (cron drop-in written by deploy/setup-app-prod.sh) — daily at 06:10:
#   10 6 * * * /home/cwa/CWA_CLASS_APP/scripts/cron_generate_progress_reports.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/progress_reports.log 2>&1

set -euo pipefail

LOCK_FILE="/tmp/cwa-progress-reports-$(echo "${1:-default}" | tr '/' '_').lock"
if [[ "${_CWA_REPORTS_LOCKED:-}" != "1" ]]; then
    export _CWA_REPORTS_LOCKED=1
    # -E 99 distinguishes "could not get the lock" from the command's own exit
    # code, so a skipped tick reports as a skip and a real failure still reaches
    # cron. Not `exec`: that would replace this shell and the contention branch
    # below could never run, making a skip silent.
    set +e
    flock -n -E 99 "$LOCK_FILE" "$0" "$@"
    rc=$?
    set -e
    if [[ $rc -eq 99 ]]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') a report run is still going — skipping this tick."
        exit 0
    fi
    exit $rc
fi

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP}"
ENV_FILE="${2:-/etc/cwa/cwa.env}"

# The env file is a systemd EnvironmentFile (plain KEY=value, values NOT
# shell-quoted) so it must NOT be `source`d — a value with shell metacharacters
# would break bash. Export each assignment verbatim instead.
if [[ -f "$ENV_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
        [[ "$line" == *=* ]] || continue
        export "$line"
    done < "$ENV_FILE"
fi

cd "$APP_DIR"
source venv/bin/activate

echo "$(date '+%Y-%m-%d %H:%M:%S') generating progress reports…"
python cwa_classroom/manage.py generate_progress_reports
