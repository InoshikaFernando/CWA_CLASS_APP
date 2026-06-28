#!/usr/bin/env bash
# deploy.sh
# ---------
# Deploy a CWA Classroom checkout. Designed to run from inside the checkout
# you want to deploy (the current directory), so one script serves every
# environment on the shared droplet (prod / test / dev) by passing env vars:
#
#   cd /home/cwa/CWA_CLASS_APP      && DEPLOY_BRANCH=main SERVICE=cwa-gunicorn \
#       ENV_FILE=/etc/cwa/cwa.env   HEALTH_SOCKET=/run/cwa/gunicorn.sock bash scripts/deploy.sh
#   cd /home/cwa/CWA_CLASS_APP_TEST && DEPLOY_BRANCH=test SERVICE=cwa-gunicorn-test \
#       ENV_FILE=/etc/cwa/cwa-test.env HEALTH_SOCKET=/run/cwa-test.sock bash scripts/deploy.sh
#
# What it does: pull branch → install deps → migrate → collectstatic →
# check --deploy → restart the systemd service → deep health gate.
#
# Overridable knobs (all have prod defaults):
#   REPO_DIR       default: the current directory
#   VENV_DIR       default: $REPO_DIR/venv
#   APP_DIR        default: $REPO_DIR/cwa_classroom
#   DEPLOY_BRANCH  default: main
#   SERVICE        default: cwa-gunicorn
#   ENV_FILE       default: /etc/cwa/cwa.env   (read for ALLOWED_HOSTS → Host header)
#   HEALTH_SOCKET  default: (none) — if set, the health gate curls this unix
#                  socket directly (works regardless of upstream TLS)
#   WORKER         default: (none) — if set, the RQ worker unit is restarted
#                  AFTER the web service so it picks up the new code. Without
#                  this the worker keeps running stale code after a deploy and
#                  background jobs (AI import, worksheets, homework) run old
#                  logic. e.g. WORKER=cwa-rqworker-prod (prod) /
#                  cwa-rqworker-test (test).

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(pwd)}"
VENV_DIR="${VENV_DIR:-${REPO_DIR}/venv}"
APP_DIR="${APP_DIR:-${REPO_DIR}/cwa_classroom}"
BRANCH="${DEPLOY_BRANCH:-main}"
SERVICE="${SERVICE:-cwa-gunicorn}"
ENV_FILE="${ENV_FILE:-/etc/cwa/cwa.env}"
HEALTH_SOCKET="${HEALTH_SOCKET:-}"
WORKER="${WORKER:-}"

cd "$REPO_DIR"

# --- Safety guards -----------------------------------------------------------
# These exist because a manual run once reset the PROD checkout to origin/dev
# (run as root, from the prod dir, with DEPLOY_BRANCH=dev) — taking the whole
# site down with NoReverseMatch errors and poisoning .git ownership for the
# cwa user. Both guards below would have blocked it; neither affects the
# automated deploys (they run as cwa, from the matching dir, with the matching
# branch — see .github/workflows/deploy-*.yml).

# 1) Never deploy as root. git-as-root rewrites .git ownership so the cwa user
#    can no longer fetch/reset, silently breaking every subsequent deploy.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    echo "ERROR: refusing to deploy as root — run as the app user instead:" >&2
    echo "       sudo -u cwa DEPLOY_BRANCH=${BRANCH} bash scripts/deploy.sh" >&2
    exit 1
fi

# 2) Bind each checkout to the one branch it is allowed to deploy, derived from
#    the directory itself — so "deploy dev from the prod dir" is impossible.
#    A DEPLOY_BRANCH that disagrees is a hard error, never a silent reset.
case "$REPO_DIR" in
    */CWA_CLASS_APP)      EXPECTED_BRANCH=main ;;
    */CWA_CLASS_APP_TEST) EXPECTED_BRANCH=test ;;
    */CWA_CLASS_APP_DEV)  EXPECTED_BRANCH=dev  ;;
    *)                    EXPECTED_BRANCH=""   ;;  # unknown dir: no binding
esac
if [[ -n "$EXPECTED_BRANCH" && "$BRANCH" != "$EXPECTED_BRANCH" ]]; then
    echo "ERROR: ${REPO_DIR} only deploys '${EXPECTED_BRANCH}', not '${BRANCH}'." >&2
    echo "       Refusing to reset this checkout to origin/${BRANCH}." >&2
    exit 1
fi
# -----------------------------------------------------------------------------

echo "==> Deploying ${REPO_DIR} (branch ${BRANCH}, service ${SERVICE})"

echo "==> Pulling latest from ${BRANCH}..."
git fetch origin "$BRANCH"
git reset --hard "origin/${BRANCH}"

echo "==> Installing dependencies..."
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt" --quiet

echo "==> Running migrations..."
"${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" migrate --noinput

echo "==> Collecting static files..."
"${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" collectstatic --noinput --clear

echo "==> Running deploy checks..."
"${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" check --deploy 2>&1 || true

echo "==> Restarting ${SERVICE}..."
sudo systemctl restart "$SERVICE"

echo "==> Verifying service status..."
sleep 2
if systemctl is-active --quiet "$SERVICE"; then
    echo "    ${SERVICE} is running."
else
    echo "ERROR: ${SERVICE} failed to start!"
    sudo journalctl -u "$SERVICE" --no-pager -n 20
    exit 1
fi

# Restart the RQ worker AFTER the web service, so background jobs run the same
# code we just deployed. Skipped (with a notice) if the unit doesn't exist yet.
if [[ -n "$WORKER" ]]; then
    if systemctl list-unit-files "${WORKER}.service" --no-legend | grep -q .; then
        echo "==> Restarting worker ${WORKER}..."
        sudo systemctl restart "$WORKER"
        sleep 2
        if systemctl is-active --quiet "$WORKER"; then
            echo "    ${WORKER} is running."
        else
            echo "ERROR: ${WORKER} failed to start!"
            sudo journalctl -u "$WORKER" --no-pager -n 20
            exit 1
        fi
    else
        echo "==> WARNING: WORKER=${WORKER} set but ${WORKER}.service not found — skipping."
        echo "    Background jobs will NOT be processed until this unit exists."
    fi
fi

echo "==> Deep health check..."
# A running process is not a working app. The deep probe checks DB, migrations,
# and cache; it returns HTTP 503 'degraded' if any fails. We hit the app's own
# gunicorn socket directly (HEALTH_SOCKET) with a Host header from ALLOWED_HOSTS,
# so it works regardless of how/where TLS is terminated upstream.
HEALTH_DOMAIN="${HEALTH_DOMAIN:-$(grep -E '^ALLOWED_HOSTS=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | cut -d, -f1)}"
if [[ -n "$HEALTH_SOCKET" && -n "$HEALTH_DOMAIN" ]]; then
    HEALTH_BODY_FILE="$(mktemp)"
    # curl writes the body to -o and the status to stdout (-w). We capture the
    # status into HTTP_CODE and use `|| true` (NOT `|| echo 000`) so a non-zero
    # curl exit (e.g. error 23 "write error", which can fire even on a real 200)
    # neither aborts the script under `set -e` nor concatenates onto the code —
    # the old `|| echo 000` turned a "200" into "200000" and failed healthy
    # deploys. Genuine failures still surface: a no-response curl emits "000".
    HTTP_CODE="$(curl -sS --unix-socket "$HEALTH_SOCKET" \
        -H "Host: ${HEALTH_DOMAIN}" \
        -o "$HEALTH_BODY_FILE" -w '%{http_code}' \
        "http://localhost/api/health/?deep=1" 2>/dev/null)" || true
    HTTP_CODE="${HTTP_CODE:0:3}"   # guard against any stray trailing characters
    if [[ "$HTTP_CODE" == "200" ]]; then
        echo "    Healthy: $(cat "$HEALTH_BODY_FILE")"
        rm -f "$HEALTH_BODY_FILE"
    else
        echo "ERROR: health check via ${HEALTH_SOCKET} returned HTTP ${HTTP_CODE:-000} (expected 200)."
        echo "       Body: $(cat "$HEALTH_BODY_FILE" 2>/dev/null)"
        rm -f "$HEALTH_BODY_FILE"
        sudo journalctl -u "$SERVICE" --no-pager -n 20
        exit 1
    fi
else
    echo "    (HEALTH_SOCKET or ALLOWED_HOSTS not set — skipping deep health gate;"
    echo "     ${SERVICE} is running per systemctl.)"
fi

echo ""
echo "==> Deploy complete."
