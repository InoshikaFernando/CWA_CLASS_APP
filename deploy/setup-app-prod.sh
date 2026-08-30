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
sudo -u "$APP_USER" "${REPO_DIR}/venv/bin/pip" install -r "${REPO_DIR}/cwa_classroom/requirements.txt"
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
    # Rotate as the cwa user and recreate the fresh log owned by cwa. Without
    # these, logrotate (running as root) recreates the files root-owned, so
    # gunicorn/Django (running as cwa) can no longer write to them and errors
    # are silently dropped until someone notices and chowns them back.
    su cwa cwa
    create 0644 cwa cwa
    postrotate
        systemctl reload cwa-gunicorn 2>/dev/null || true
    endscript
}
LOGROTATE

# ── Ops metrics cron ─────────────────────────────────────────────────────────
# Powers the in-app Ops dashboard (/admin-dashboard/ops/). Without this the
# dashboard silently shows empty charts, so install it here rather than relying
# on a manual `crontab -e`. A /etc/cron.d drop-in is idempotent (re-running
# setup overwrites it) and leaves the cwa user's personal crontab untouched.
echo "==> Installing ops-metrics cron..."
cat > /etc/cron.d/cwa-ops <<'OPSCRON'
# CWA ops metrics — record droplet health every 10 min; prune old rows daily.
# Managed by deploy/setup-app-prod.sh; edit there, not here.
*/10 * * * * cwa /home/cwa/CWA_CLASS_APP/scripts/record_ops_metrics.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/ops_metrics.log 2>&1
30 3 * * * cwa /home/cwa/CWA_CLASS_APP/scripts/record_ops_metrics.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env prune >> /var/log/cwa/ops_metrics.log 2>&1
OPSCRON
chmod 644 /etc/cron.d/cwa-ops

# ── Stuck-upload reaper cron ─────────────────────────────────────────────────
# A work-horse killed by the OOM killer never runs its failure handler, leaving
# the PDF upload session in 'processing' — the teacher's page then polls a job
# that will never finish. The reaper flips those to failed so the page self-heals
# into a retry. Install it here; without the cron the command never runs.
echo "==> Installing stuck-upload reaper cron..."
cat > /etc/cron.d/cwa-uploads <<'REAPCRON'
# CWA stuck-upload reaper — self-heal PDF uploads whose worker died.
# Managed by deploy/setup-app-prod.sh; edit there, not here.
*/5 * * * * cwa /home/cwa/CWA_CLASS_APP/scripts/reap_stuck_uploads.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env 30 >> /var/log/cwa/reap_uploads.log 2>&1
REAPCRON
chmod 644 /etc/cron.d/cwa-uploads

# ── Email queue cron ─────────────────────────────────────────────────────────
# Every invoice email is force-queued at issue time, so this command IS the
# delivery path — without it invoices are marked issued and silently never sent.
# Production once accrued 316 undelivered invoice emails over ten weeks because
# the only crontab entry for it pointed at the CWA_CLASS_APP_TEST checkout, so
# the production queue had no drainer. Installing it here (rather than by hand)
# is what stops that recurring; the explicit app dir stops the path drifting to
# another checkout.
echo "==> Installing email-queue cron..."
cat > /etc/cron.d/cwa-email <<'MAILCRON'
# CWA email queue — deliver queued mail (all invoice email) every 2 min.
# Managed by deploy/setup-app-prod.sh; edit there, not here.
*/2 * * * * cwa /home/cwa/CWA_CLASS_APP/scripts/cron_process_email_queue.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/email_queue.log 2>&1
MAILCRON
chmod 644 /etc/cron.d/cwa-email

# ── Email queue watchdog cron ────────────────────────────────────────────────
# A drain that stops is invisible: invoices still read as issued while their
# emails sit queued. This posts to Discord once the backlog ages past the
# threshold. Kept as its own cron because a watchdog running inside the job it
# watches cannot report that job being dead.
echo "==> Installing email-queue watchdog cron..."
cat > /etc/cron.d/cwa-email-health <<'MAILHEALTHCRON'
# CWA email queue watchdog — alert if queued mail stops being delivered.
# Managed by deploy/setup-app-prod.sh; edit there, not here.
0 * * * * cwa /home/cwa/CWA_CLASS_APP/scripts/cron_check_email_queue.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/email_queue_health.log 2>&1
MAILHEALTHCRON
chmod 644 /etc/cron.d/cwa-email-health

# ── Progress report cron ─────────────────────────────────────────────────────
# Nothing else calls the report generator, and its absence is invisible: the
# reports page just stays empty, which reads as "no activity yet" rather than as
# a dead job. Installed here for the same reason as the email cron — a crontab
# entry added by hand is one that points at the wrong checkout.
echo "==> Installing progress-report cron..."
cat > /etc/cron.d/cwa-progress-reports <<'REPORTCRON'
# CWA progress reports — close the week / month / term and notify families.
# Managed by deploy/setup-app-prod.sh; edit there, not here.
10 6 * * * cwa /home/cwa/CWA_CLASS_APP/scripts/cron_generate_progress_reports.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/progress_reports.log 2>&1
REPORTCRON
chmod 644 /etc/cron.d/cwa-progress-reports

# ── Question schedule cron ───────────────────────────────────────────────────
# Builds the homework a teacher's weekly teaching plan is due to produce
# (CPP-399). Its absence is invisible in exactly the way the progress-report
# job's is: the plan's weeks stay 'pending', the class gets no homework, and
# nothing anywhere says why. Runs before the school day so the sets are ready
# for a teacher to review in the morning.
echo "==> Installing question-schedule cron..."
cat > /etc/cron.d/cwa-scheduled-questions <<'SCHEDQCRON'
# CWA question schedules — turn each planned teaching week into homework.
# Managed by deploy/setup-app-prod.sh; edit there, not here.
15 2 * * * cwa /home/cwa/CWA_CLASS_APP/scripts/cron_generate_scheduled_questions.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/scheduled_questions.log 2>&1
SCHEDQCRON
chmod 644 /etc/cron.d/cwa-scheduled-questions

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
