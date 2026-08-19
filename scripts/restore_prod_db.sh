#!/usr/bin/env bash
# restore_prod_db.sh
# ------------------
# Dumps the PRODUCTION MySQL database from the DigitalOcean prod server via SSH,
# streams it down, and restores it into the local dev database.
#
# Prod moved off PythonAnywhere to DigitalOcean. The prod DB is a DigitalOcean
# Managed MySQL instance; its credentials live in the systemd env file
# /etc/cwa/cwa.env on the app server (the same file the deploy uses). This script
# SSHes into the app server as the deploy user, reads the DB_* vars from that env
# file, runs mysqldump against the managed DB *from the droplet* (it has network
# access to the private DB host and the CA cert), gzips the dump, streams it back,
# and restores it locally.
#
# It reuses the same connection settings as .github/workflows/deploy-prod.yml, so
# point it at the same host/user your deploys already use.
#
# Usage:
#   DEPLOY_HOST=<prod-ip-or-hostname> bash scripts/restore_prod_db.sh
#   # optionally: DEPLOY_USER, SSH_KEY, SSH_PORT, LOCAL_MYSQL overrides (see below)
#
# Requirements:
#   - SSH access to the prod droplet (your public key authorised for DEPLOY_USER)
#   - mysql / mysqldump on the droplet (already present — the app uses MySQL)
#   - mysql client available locally (set LOCAL_MYSQL if it's not on PATH)

# ── Remote (DigitalOcean app server) — mirrors deploy-prod.yml ─────────────────
DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST to the prod server IP/hostname (same value as the DEPLOY_HOST GitHub secret)}"
DEPLOY_USER="${DEPLOY_USER:-cwa}"                 # SSH user on the droplet
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY="${SSH_KEY:-}"                            # optional path to a private key (-i)
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-/etc/cwa/cwa.env}"   # holds prod DB_* creds

# ── Local target ──────────────────────────────────────────────────────────────
LOCAL_MYSQL="${LOCAL_MYSQL:-mysql}"              # local mysql client (full path if not on PATH)
LOCAL_DB_USER="${LOCAL_DB_USER:-root}"
LOCAL_DB_PASS="${LOCAL_DB_PASS:-root}"
LOCAL_DB_HOST="${LOCAL_DB_HOST:-127.0.0.1}"
LOCAL_DB_PORT="${LOCAL_DB_PORT:-3306}"
LOCAL_DB_NAME="${LOCAL_DB_NAME:-cwa_classroom}"

DUMP_FILE="/tmp/prod_dump_$(date +%Y%m%d_%H%M%S).sql.gz"
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SSH_OPTS=(-p "$SSH_PORT" -o BatchMode=yes)
[ -n "$SSH_KEY" ] && SSH_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)

echo "==> Dumping prod DB from ${DEPLOY_USER}@${DEPLOY_HOST} (creds from ${REMOTE_ENV_FILE}) ..."

# Remote: read DB_* from the systemd env file (KEY=VALUE, quotes optional — parsed
# the same way scripts/deploy.sh reads ALLOWED_HOSTS), then mysqldump the managed
# DB and gzip on the wire. --no-tablespaces avoids needing the PROCESS privilege
# on managed MySQL. --events is omitted deliberately: managed MySQL app users
# usually lack the EVENT privilege and it would abort the dump.
ssh "${SSH_OPTS[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" \
    "REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' bash -s" > "${DUMP_FILE}" <<'REMOTE'
set -euo pipefail
ENV_FILE="${REMOTE_ENV_FILE:-/etc/cwa/cwa.env}"
if [ ! -r "$ENV_FILE" ]; then
    echo "ERROR: cannot read $ENV_FILE on the prod server" >&2
    exit 1
fi
val() {
    grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- \
        | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"
}
DB_NAME="$(val DB_NAME)"
DB_USER="$(val DB_USER)"
DB_PASSWORD="$(val DB_PASSWORD)"
DB_HOST="$(val DB_HOST)"
DB_PORT="$(val DB_PORT)"
DB_SSL_CA="$(val DB_SSL_CA)"

if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_HOST" ]; then
    echo "ERROR: DB_NAME/DB_USER/DB_HOST missing from $ENV_FILE" >&2
    exit 1
fi

SSL_OPT=""
[ -n "$DB_SSL_CA" ] && SSL_OPT="--ssl-ca=$DB_SSL_CA"

export MYSQL_PWD="$DB_PASSWORD"   # keep the password off the process command line
mysqldump \
    -h "$DB_HOST" -P "${DB_PORT:-3306}" -u "$DB_USER" $SSL_OPT \
    --single-transaction --quick --routines --triggers --no-tablespaces \
    --set-gtid-purged=OFF \
    --default-character-set=utf8mb4 \
    "$DB_NAME" | gzip
REMOTE

if [ ! -s "$DUMP_FILE" ]; then
    echo "ERROR: dump is empty — nothing was downloaded. Aborting before touching local DB." >&2
    exit 1
fi
echo "==> Downloaded $(du -h "$DUMP_FILE" | cut -f1) to ${DUMP_FILE}"

echo "==> Dropping and recreating local DB '${LOCAL_DB_NAME}' ..."
MYSQL_PWD="$LOCAL_DB_PASS" "$LOCAL_MYSQL" \
    -u "$LOCAL_DB_USER" -h "$LOCAL_DB_HOST" -P "$LOCAL_DB_PORT" \
    -e "DROP DATABASE IF EXISTS \`${LOCAL_DB_NAME}\`; CREATE DATABASE \`${LOCAL_DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "==> Restoring dump to local DB ..."
gunzip < "${DUMP_FILE}" | MYSQL_PWD="$LOCAL_DB_PASS" "$LOCAL_MYSQL" \
    -u "$LOCAL_DB_USER" -h "$LOCAL_DB_HOST" -P "$LOCAL_DB_PORT" "${LOCAL_DB_NAME}"

echo "==> Done. Local DB '${LOCAL_DB_NAME}' restored from PROD (DigitalOcean)."
echo ""
echo "If local code is ahead of prod's schema, apply any newer migrations:"
echo "  cd cwa_classroom && DB_PASSWORD=${LOCAL_DB_PASS} python manage.py migrate"

rm -f "${DUMP_FILE}"
