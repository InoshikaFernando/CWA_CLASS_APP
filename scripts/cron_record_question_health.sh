#!/bin/bash
# cron_record_question_health.sh — daily question-bank health snapshot for CWA.
#
# Records one QuestionHealthSnapshot (issue counts across the whole question
# bank). The in-app dashboard (/admin-dashboard/question-health/) reads back
# these stored snapshots and plots the trend — with nothing recorded the page
# is empty, which is exactly how it shipped: the dashboard went live in CPP-377
# but nothing ever wrote a snapshot, so it showed "No audits yet" forever.
#
# Read-only against the question bank; it only writes its own snapshot row.
#
# Install (crontab on the DO server) — daily 02:30 for the TEST app:
#   30 2 * * * /home/cwa/CWA_CLASS_APP_TEST/scripts/cron_record_question_health.sh >> /var/log/cwa/question_health.log 2>&1
#
# For PROD, pass the prod app dir + env file as args:
#   30 2 * * * /home/cwa/CWA_CLASS_APP/scripts/cron_record_question_health.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/question_health.log 2>&1

set -euo pipefail

APP_DIR="${1:-/home/cwa/CWA_CLASS_APP_TEST}"
ENV_FILE="${2:-/etc/cwa/cwa-test.env}"

# Best-effort load of the app env file. Django loads its own config from
# cwa_classroom/.env via python-dotenv (with override), so the command gets its
# DB settings regardless of the shell — this source is only for any extras. It
# must NEVER abort the run: env files aren't always valid bash (e.g. a
# SECRET_KEY containing shell metacharacters), and such a parse error must not
# stop the snapshot from being recorded. Hence `|| true` under set -e.
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE" 2>/dev/null || true
    set +a
fi

cd "$APP_DIR"
source venv/bin/activate

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z')  ($APP_DIR) ====="
python cwa_classroom/manage.py record_question_health
