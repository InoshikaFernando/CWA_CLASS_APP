#!/usr/bin/env bash
# install_crons.sh
# ----------------
# Write this app's /etc/cron.d drop-ins — and NOTHING else.
#
# Usage (as root, on a droplet):
#   scripts/install_crons.sh              # production checkout
#   scripts/install_crons.sh test         # test checkout
#   scripts/install_crons.sh --check      # report drift, write nothing, exit 1 if any
#   scripts/install_crons.sh --check test
#
# Overridable (env vars, for a non-standard layout):
#   APP_DIR   ENV_FILE   SUFFIX   APP_USER   LOG_DIR   CRON_DIR
#
# WHY THIS IS ITS OWN SCRIPT
# --------------------------
# These drop-ins used to live inside deploy/setup-app-prod.sh, which is
# one-time provisioning: it also runs `apt-get upgrade -y`, overwrites
# /etc/caddy/Caddyfile and the gunicorn unit, rebuilds the venv and re-pulls
# the repo. So the only supported way to add a cron was to run something far
# too dangerous to run on a live site — and therefore nobody ran it.
#
# The cost of that was not theoretical. `cwa-publish-homework` was added to the
# provisioning script on 2026-08-31 and was still absent from production on
# 2026-09-13, because no one was going to upgrade the OS to install a crontab
# line. For those two weeks the question-automation schedule built a homework
# set for every planned week, held each one behind a future publish_at, and
# never sent a single one — publish_scheduled_homework is the only thing that
# sets published_at, and students gate on it. Nothing errored. It surfaced only
# because a teacher noticed she was clicking "Publish now" every week.
# (An attempt to fix it by re-running the provisioning script upgraded 35
# packages on production, restarted Caddy under live traffic and left a kernel
# reboot pending, before it was aborted at an interactive prompt.)
#
# So: this script touches /etc/cron.d and nothing else. It is safe to run on a
# live droplet, it takes a second, and setup-app-prod.sh calls it rather than
# carrying its own copies — one source of truth, reachable without collateral.
#
# Adding a cron: add a render_* function and one JOBS entry. tests_workflows.py
# fails the build if a scripts/cron_*.sh wrapper has no drop-in here.

set -euo pipefail

CHECK_ONLY=0
PROFILE=prod

for arg in "$@"; do
    case "$arg" in
        --check)     CHECK_ONLY=1 ;;
        prod|test)   PROFILE="$arg" ;;
        -h|--help)   sed -n '2,30p' "$0"; exit 0 ;;
        *)           echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# Profile defaults. Every one is overridable by an env var of the same name, so
# a droplet with a non-standard layout needs no edit to this file.
if [[ "$PROFILE" == "test" ]]; then
    APP_DIR="${APP_DIR:-/home/cwa/CWA_CLASS_APP_TEST}"
    ENV_FILE="${ENV_FILE:-/etc/cwa/cwa-test.env}"
    # Drop-in and log names are suffixed so the test jobs can never overwrite
    # the production ones on a shared droplet — the two checkouts live side by
    # side and an unsuffixed test drop-in would silently replace prod's.
    SUFFIX="${SUFFIX:--test}"
else
    APP_DIR="${APP_DIR:-/home/cwa/CWA_CLASS_APP}"
    ENV_FILE="${ENV_FILE:-/etc/cwa/cwa.env}"
    SUFFIX="${SUFFIX:-}"
fi
APP_USER="${APP_USER:-cwa}"
LOG_DIR="${LOG_DIR:-/var/log/cwa}"
CRON_DIR="${CRON_DIR:-/etc/cron.d}"

HEADER="# Managed by scripts/install_crons.sh (profile: ${PROFILE}). Edit there, not here."

# ── The jobs ─────────────────────────────────────────────────────────────────
# One render_<name> per drop-in. Each prints the file's body; the header and
# the trailing newline are added by write_dropin.

render_ops() {
    cat <<EOF
# CWA ops metrics — record droplet health every 10 min; prune old rows daily.
# Powers /admin-dashboard/ops/; without it the dashboard charts stay empty.
*/10 * * * * ${APP_USER} ${APP_DIR}/scripts/record_ops_metrics.sh ${APP_DIR} ${ENV_FILE} >> ${LOG_DIR}/ops_metrics${SUFFIX}.log 2>&1
30 3 * * * ${APP_USER} ${APP_DIR}/scripts/record_ops_metrics.sh ${APP_DIR} ${ENV_FILE} prune >> ${LOG_DIR}/ops_metrics${SUFFIX}.log 2>&1
EOF
}

render_uploads() {
    cat <<EOF
# CWA stuck-upload reaper — self-heal PDF uploads whose worker died.
# A work-horse killed by the OOM killer never runs its failure handler, so the
# session sits in 'processing' and the teacher's page polls a job that is gone.
*/5 * * * * ${APP_USER} ${APP_DIR}/scripts/reap_stuck_uploads.sh ${APP_DIR} ${ENV_FILE} 30 >> ${LOG_DIR}/reap_uploads${SUFFIX}.log 2>&1
EOF
}

render_email() {
    cat <<EOF
# CWA email queue — deliver queued mail (all invoice email) every 2 min.
# Every invoice email is force-queued at issue time, so this command IS the
# delivery path: without it invoices read as issued and are never sent.
*/2 * * * * ${APP_USER} ${APP_DIR}/scripts/cron_process_email_queue.sh ${APP_DIR} ${ENV_FILE} >> ${LOG_DIR}/email_queue${SUFFIX}.log 2>&1
EOF
}

render_email_health() {
    cat <<EOF
# CWA email queue watchdog — alert if queued mail stops being delivered.
# Its own job on purpose: a watchdog inside the job it watches cannot report
# that job being dead.
0 * * * * ${APP_USER} ${APP_DIR}/scripts/cron_check_email_queue.sh ${APP_DIR} ${ENV_FILE} >> ${LOG_DIR}/email_queue_health${SUFFIX}.log 2>&1
EOF
}

render_unpaid_access() {
    cat <<EOF
# CWA unpaid-access watchdog — alert if a delinquent account reached a
# restricted page. Also on the Ops dashboard (/admin-dashboard/ops/).
0 9 * * * ${APP_USER} ${APP_DIR}/scripts/cron_check_unpaid_access.sh ${APP_DIR} ${ENV_FILE} 1 >> ${LOG_DIR}/unpaid_access${SUFFIX}.log 2>&1
EOF
}

render_progress_reports() {
    cat <<EOF
# CWA progress reports — close the week / month / term and notify families.
# Nothing else calls the generator; without this the reports page simply stays
# empty, which reads as "no activity yet" rather than as a dead job.
10 6 * * * ${APP_USER} ${APP_DIR}/scripts/cron_generate_progress_reports.sh ${APP_DIR} ${ENV_FILE} >> ${LOG_DIR}/progress_reports${SUFFIX}.log 2>&1
EOF
}

render_publish_homework() {
    cat <<EOF
# CWA scheduled homework — publish sets whose publish_at has arrived.
# The ONLY thing that sets published_at, which is what students gate on. Absent,
# every scheduled set — including every one the question schedule builds — is
# created, sits invisible, and is never sent, with nothing erroring anywhere.
*/5 * * * * ${APP_USER} cd ${APP_DIR} && venv/bin/python cwa_classroom/manage.py publish_scheduled_homework >> ${LOG_DIR}/publish_scheduled_homework${SUFFIX}.log 2>&1
EOF
}

render_scheduled_questions() {
    cat <<EOF
# CWA question schedules — turn each planned teaching week into homework.
# Builds with a FUTURE publish_at, so nothing reaches a student from this job
# alone; cwa-publish-homework releases it when the time comes.
15 2 * * * ${APP_USER} ${APP_DIR}/scripts/cron_generate_scheduled_questions.sh ${APP_DIR} ${ENV_FILE} >> ${LOG_DIR}/scheduled_questions${SUFFIX}.log 2>&1
EOF
}

# name:render_function:profiles
# `profiles` is prod, test, or both. unpaid-access is prod-only because live
# PageHits only accrue there — on test it would report an empty window daily
# and train everyone to ignore it.
JOBS=(
    "ops:render_ops:both"
    "uploads:render_uploads:both"
    "email:render_email:both"
    "email-health:render_email_health:both"
    "unpaid-access:render_unpaid_access:prod"
    "progress-reports:render_progress_reports:both"
    "publish-homework:render_publish_homework:both"
    "scheduled-questions:render_scheduled_questions:both"
)

# ── Apply ────────────────────────────────────────────────────────────────────

changed=0
drift=0

for job in "${JOBS[@]}"; do
    IFS=':' read -r name renderer profiles <<< "$job"
    if [[ "$profiles" != "both" && "$profiles" != "$PROFILE" ]]; then
        continue
    fi

    target="${CRON_DIR}/cwa-${name}${SUFFIX}"
    body="$(printf '%s\n%s' "$HEADER" "$($renderer)")"

    if [[ "$CHECK_ONLY" == "1" ]]; then
        if [[ ! -f "$target" ]]; then
            echo "MISSING  ${target}"
            drift=1
        elif [[ "$(cat "$target")" != "$body" ]]; then
            echo "STALE    ${target}"
            drift=1
        else
            echo "ok       ${target}"
        fi
        continue
    fi

    if [[ -f "$target" && "$(cat "$target")" == "$body" ]]; then
        echo "unchanged ${target}"
        continue
    fi
    printf '%s\n' "$body" > "$target"
    chmod 644 "$target"
    echo "written   ${target}"
    changed=$((changed + 1))
done

if [[ "$CHECK_ONLY" == "1" ]]; then
    if [[ "$drift" == "1" ]]; then
        echo
        echo "Cron drop-ins are missing or out of date for profile '${PROFILE}'."
        echo "Fix with: sudo $0 ${PROFILE}"
        exit 1
    fi
    echo
    echo "All cron drop-ins present and current for profile '${PROFILE}'."
    exit 0
fi

echo
echo "${changed} drop-in(s) updated for profile '${PROFILE}'. cron re-reads"
echo "${CRON_DIR} by itself — no reload needed."
