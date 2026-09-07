#!/bin/bash
# record_ops_metrics.sh — droplet-side cron that snapshots server health.
#
# Runs `manage.py record_ops_metrics`, which reads local RAM/swap/disk/load,
# OOM kills, systemd service state and RQ queue depth, stores an OpsSnapshot
# row (powering the in-app Ops dashboard's trend charts) and posts a critical
# alert to DEPLOY_ALERT_WEBHOOK when the box first turns critical. This replaces
# the old ops-dashboard GitHub Action — it needs no SSH and burns no Actions
# minutes.
#
# Idempotent and cheap; run OFTEN so the charts are fine-grained and alerts are
# timely. Recommended every 10 minutes.
#
# Install (crontab on the DO server) — every 10 min, PROD app:
#   */10 * * * * /home/cwa/CWA_CLASS_APP/scripts/record_ops_metrics.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/ops_metrics.log 2>&1
#
# Also prune old rows daily (retention ~400 days) so the table stays small:
#   30 3 * * * /home/cwa/CWA_CLASS_APP/scripts/record_ops_metrics.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env prune >> /var/log/cwa/ops_metrics.log 2>&1

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP}"
ENV_FILE="${2:-/etc/cwa/cwa.env}"
MODE="${3:-record}"

# Load the app env (DB creds, DEPLOY_ALERT_WEBHOOK, etc.). The file is a systemd
# EnvironmentFile (plain KEY=value, values NOT shell-quoted) so it must NOT be
# `source`d — a value with shell metacharacters (e.g. ')') would break bash.
# Read it line by line and export each assignment verbatim instead.
if [[ -f "$ENV_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
        [[ "$line" == *=* ]] || continue
        export "$line"
    done < "$ENV_FILE"
fi

cd "$APP_DIR"
source venv/bin/activate

if [[ "$MODE" == "prune" ]]; then
    python cwa_classroom/manage.py prune_ops_metrics
else
    python cwa_classroom/manage.py record_ops_metrics
fi
