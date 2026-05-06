#!/usr/bin/env bash
# setup-app-prod.sh
# -----------------
# One-time setup for app-prod Droplet (Ubuntu 24.04, SYD1).
# Run as root after creating the Droplet.
#
# What it does:
#   1. Creates cwa deploy user
#   2. Installs Python 3, MySQL client, Caddy
#   3. Clones repo, creates venv, installs deps
#   4. Sets up systemd, Caddy, log directories
#
# Usage:
#   scp deploy/setup-app-prod.sh root@<droplet-ip>:/tmp/
#   ssh root@<droplet-ip> bash /tmp/setup-app-prod.sh

set -euo pipefail

REPO_URL="https://github.com/InoshikaFernando/CWA_CLASS_APP.git"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
APP_USER="cwa"
APP_HOME="/home/${APP_USER}"
REPO_DIR="${APP_HOME}/CWA_CLASS_APP"

echo "==> Updating system..."
apt-get update && apt-get upgrade -y

echo "==> Installing base packages..."
apt-get install -y \
    python3 python3-venv python3-pip python3-dev \
    build-essential \
    default-libmysqlclient-dev pkg-config \
    git curl ufw

# ── Caddy ────────────────────────────────────────────────────────────────────
echo "==> Installing Caddy..."
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
    gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
    tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy

# ── Deploy user ──────────────────────────────────────────────────────────────
echo "==> Creating deploy user '${APP_USER}'..."
if ! id "$APP_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$APP_USER"
fi

# ── Directories ──────────────────────────────────────────────────────────────
echo "==> Creating directories..."
mkdir -p /etc/cwa /var/log/cwa /var/log/caddy /run/cwa
chown "${APP_USER}:${APP_USER}" /etc/cwa /var/log/cwa /run/cwa
chmod 700 /etc/cwa

# ── Clone & venv ─────────────────────────────────────────────────────────────
echo "==> Cloning repo..."
if [ ! -d "$REPO_DIR" ]; then
    sudo -u "$APP_USER" git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"
sudo -u "$APP_USER" git checkout "$DEPLOY_BRANCH"
sudo -u "$APP_USER" git pull origin "$DEPLOY_BRANCH"

echo "==> Creating venv and installing deps..."
sudo -u "$APP_USER" python3 -m venv "${REPO_DIR}/venv"
sudo -u "$APP_USER" "${REPO_DIR}/venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "${REPO_DIR}/venv/bin/pip" install -r requirements.txt
sudo -u "$APP_USER" "${REPO_DIR}/venv/bin/pip" install gunicorn

# ── systemd ──────────────────────────────────────────────────────────────────
echo "==> Installing systemd unit..."
cp "${REPO_DIR}/deploy/cwa-gunicorn.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable cwa-gunicorn

# ── Caddy config ─────────────────────────────────────────────────────────────
echo "==> Installing Caddyfile..."
cp "${REPO_DIR}/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl enable caddy

# ── Log rotation ─────────────────────────────────────────────────────────────
echo "==> Setting up log rotation..."
cat > /etc/logrotate.d/cwa <<'LOGROTATE'
/var/log/cwa/*.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload cwa-gunicorn 2>/dev/null || true
    endscript
}
LOGROTATE

# ── Sudoers for deploy ───────────────────────────────────────────────────────
echo "==> Granting cwa user restart permissions..."
cat > /etc/sudoers.d/cwa <<'SUDOERS'
cwa ALL=(ALL) NOPASSWD: /bin/systemctl restart cwa-gunicorn, /bin/systemctl reload cwa-gunicorn, /bin/journalctl -u cwa-gunicorn *
SUDOERS
chmod 440 /etc/sudoers.d/cwa

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Copy your env file:  cp deploy/cwa.env.example /etc/cwa/cwa.env && chmod 600 /etc/cwa/cwa.env"
echo "  2. Edit /etc/cwa/cwa.env with real values"
echo "  3. Download DO CA cert: curl -o /etc/cwa/do-ca.pem <url-from-do-dashboard>"
echo "  4. Run migrations:      sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python cwa_classroom/manage.py migrate"
echo "  5. Collect static:      sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python cwa_classroom/manage.py collectstatic --noinput"
echo "  6. Start services:      systemctl start cwa-gunicorn && systemctl start caddy"
echo "  7. Point DNS:           wizardslearninghub.co.nz → Droplet Reserved IP"
