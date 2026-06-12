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

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(pwd)}"
VENV_DIR="${VENV_DIR:-${REPO_DIR}/venv}"
APP_DIR="${APP_DIR:-${REPO_DIR}/cwa_classroom}"
BRANCH="${DEPLOY_BRANCH:-main}"
SERVICE="${SERVICE:-cwa-gunicorn}"
ENV_FILE="${ENV_FILE:-/etc/cwa/cwa.env}"
HEALTH_SOCKET="${HEALTH_SOCKET:-}"

cd "$REPO_DIR"
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

echo "==> Deep health check..."
# A running process is not a working app. The deep probe checks DB, migrations,
# and cache; it returns HTTP 503 'degraded' if any fails. We hit the app's own
# gunicorn socket directly (HEALTH_SOCKET) with a Host header from ALLOWED_HOSTS,
# so it works regardless of how/where TLS is terminated upstream.
HEALTH_DOMAIN="${HEALTH_DOMAIN:-$(grep -E '^ALLOWED_HOSTS=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | cut -d, -f1)}"
if [[ -n "$HEALTH_SOCKET" && -n "$HEALTH_DOMAIN" ]]; then
    HTTP_CODE=$(curl -sS --unix-socket "$HEALTH_SOCKET" \
        -H "Host: ${HEALTH_DOMAIN}" \
        -o /tmp/cwa-health.json -w '%{http_code}' \
        "http://localhost/api/health/?deep=1" || echo 000)
    if [[ "$HTTP_CODE" == "200" ]]; then
        echo "    Healthy: $(cat /tmp/cwa-health.json)"
    else
        echo "ERROR: health check via ${HEALTH_SOCKET} returned HTTP ${HTTP_CODE} (expected 200)."
        echo "       Body: $(cat /tmp/cwa-health.json 2>/dev/null)"
        sudo journalctl -u "$SERVICE" --no-pager -n 20
        exit 1
    fi
else
    echo "    (HEALTH_SOCKET or ALLOWED_HOSTS not set — skipping deep health gate;"
    echo "     ${SERVICE} is running per systemctl.)"
fi

echo ""
echo "==> Deploy complete."
