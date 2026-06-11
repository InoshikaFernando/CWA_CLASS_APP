#!/usr/bin/env bash
# deploy.sh
# ---------
# Deploy CWA Classroom on DigitalOcean app-prod.
# Run from the repo root on the Droplet:
#   bash scripts/deploy.sh
#
# What it does:
#   1. Pulls latest code from the deploy branch
#   2. Installs/updates Python dependencies
#   3. Runs Django migrations
#   4. Collects static files (WhiteNoise serves them)
#   5. Restarts gunicorn via systemd

set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/cwa/CWA_CLASS_APP}"
VENV_DIR="${REPO_DIR}/venv"
APP_DIR="${REPO_DIR}/cwa_classroom"
BRANCH="${DEPLOY_BRANCH:-main}"
SERVICE="cwa-gunicorn"

cd "$REPO_DIR"

echo "==> Pulling latest from ${BRANCH}..."
git fetch origin "$BRANCH"
git reset --hard "origin/${BRANCH}"

echo "==> Installing dependencies..."
"${VENV_DIR}/bin/pip" install -r requirements.txt --quiet

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
# A running process is not a working app. The deep probe checks DB
# connectivity, unapplied migrations, and the cache backend; it returns
# HTTP 503 'degraded' if any fails. Go through the real hostname over HTTPS
# (prod ALLOWED_HOSTS excludes localhost, and Caddy only serves the domain).
ENV_FILE="${ENV_FILE:-/etc/cwa/cwa.env}"
HEALTH_DOMAIN="${HEALTH_DOMAIN:-$(grep -E '^ALLOWED_HOSTS=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | cut -d, -f1)}"
if [[ -z "$HEALTH_DOMAIN" ]]; then
    echo "    WARNING: could not determine hostname (no ALLOWED_HOSTS in ${ENV_FILE});"
    echo "             skipping deep health gate. Service is running per systemctl."
else
    HEALTH_URL="https://${HEALTH_DOMAIN}/api/health/?deep=1"
    HTTP_CODE=$(curl -sS -o /tmp/cwa-health.json -w '%{http_code}' "$HEALTH_URL" || echo 000)
    if [[ "$HTTP_CODE" == "200" ]]; then
        echo "    Healthy: $(cat /tmp/cwa-health.json)"
    else
        echo "ERROR: health check ${HEALTH_URL} returned HTTP ${HTTP_CODE} (expected 200)."
        echo "       Body: $(cat /tmp/cwa-health.json 2>/dev/null)"
        sudo journalctl -u "$SERVICE" --no-pager -n 20
        exit 1
    fi
fi

echo ""
echo "==> Deploy complete."
