#!/bin/bash
# reap_stuck_uploads.sh — droplet-side cron that self-heals dead PDF uploads.
#
# Runs `manage.py reap_stuck_uploads`, which flips any upload session left in
# 'processing' by a hard-killed work-horse (OOM, crash, worker reboot) to a
# failed state. Without it those sessions sit in 'processing' forever and the
# teacher's upload page polls a job that will never finish.
#
# Homework sessions heartbeat while they work and are judged on their last sign
# of life, so a long worksheet that is still classifying is never reaped; the
# --minutes threshold is deliberately generous for the other flows, whose jobs
# can sit queued behind a long one before they start.
#
# Install (cron drop-in written by deploy/setup-app-prod.sh) — every 5 min:
#   */5 * * * * /home/cwa/CWA_CLASS_APP/scripts/reap_stuck_uploads.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/reap_uploads.log 2>&1

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP}"
ENV_FILE="${2:-/etc/cwa/cwa.env}"
MINUTES="${3:-30}"

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

python cwa_classroom/manage.py reap_stuck_uploads --minutes "$MINUTES"
