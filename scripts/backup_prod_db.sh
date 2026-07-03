#!/usr/bin/env bash
# backup_prod_db.sh
# -----------------
# Pull a RETAINED, timestamped backup of the PRODUCTION database (DigitalOcean
# Managed MySQL) down to local disk. Unlike backup_local_db.ps1 (which dumps the
# LOCAL dev DB), this SSHes into the DO prod app server, reads the DB creds from
# /etc/cwa/cwa.env server-side, mysqldumps the managed DB, gzips on the wire,
# saves a timestamped file, and prunes backups older than the retention window.
#
# Prod dumps are written to a SEPARATE folder (default C:\CWA_Backups\prod) with
# a cwa_prod_ prefix so they are never confused with the local dev backups.
#
# Usage:
#   DEPLOY_HOST=<prod-ip> bash scripts/backup_prod_db.sh
#
# Schedule it (Windows Task Scheduler) to run daily for rolling prod backups, or
# run on demand before a risky change. (DO Managed MySQL also keeps its own
# automated backups; this gives you a local, restorable copy you control.)
#
# Env overrides: DEPLOY_USER, SSH_KEY, SSH_PORT, REMOTE_ENV_FILE, BACKUP_DIR,
#                RETENTION_DAYS.

DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST to the prod server IP/hostname (same value as the DEPLOY_HOST GitHub secret)}"
DEPLOY_USER="${DEPLOY_USER:-cwa}"
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY="${SSH_KEY:-}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-/etc/cwa/cwa.env}"

BACKUP_DIR="${BACKUP_DIR:-/c/CWA_Backups/prod}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

set -euo pipefail

stamp="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
OUT_FILE="${BACKUP_DIR}/cwa_prod_${stamp}.sql.gz"

SSH_OPTS=(-p "$SSH_PORT" -o BatchMode=yes)
[ -n "$SSH_KEY" ] && SSH_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "Dumping PROD DB from ${DEPLOY_USER}@${DEPLOY_HOST} (creds from ${REMOTE_ENV_FILE}) ..."
ssh "${SSH_OPTS[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" \
    "REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' bash -s" > "${OUT_FILE}" <<'REMOTE'
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
DB_NAME="$(val DB_NAME)"; DB_USER="$(val DB_USER)"; DB_PASSWORD="$(val DB_PASSWORD)"
DB_HOST="$(val DB_HOST)"; DB_PORT="$(val DB_PORT)"; DB_SSL_CA="$(val DB_SSL_CA)"
if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_HOST" ]; then
    echo "ERROR: DB_NAME/DB_USER/DB_HOST missing from $ENV_FILE" >&2
    exit 1
fi
SSL_OPT=""
[ -n "$DB_SSL_CA" ] && SSL_OPT="--ssl-ca=$DB_SSL_CA"
export MYSQL_PWD="$DB_PASSWORD"
mysqldump \
    -h "$DB_HOST" -P "${DB_PORT:-3306}" -u "$DB_USER" $SSL_OPT \
    --single-transaction --quick --routines --triggers --no-tablespaces \
    --set-gtid-purged=OFF --default-character-set=utf8mb4 \
    "$DB_NAME" | gzip
REMOTE

if [ ! -s "$OUT_FILE" ]; then
    log "ERROR: backup is empty — removing ${OUT_FILE}"
    rm -f "$OUT_FILE"
    exit 1
fi
log "Backup complete: ${OUT_FILE} ($(du -h "$OUT_FILE" | cut -f1))"

# Prune old prod backups
pruned=0
while IFS= read -r -d '' f; do
    rm -f "$f"; pruned=$((pruned + 1)); log "Pruned old backup $(basename "$f")"
done < <(find "$BACKUP_DIR" -maxdepth 1 -name 'cwa_prod_*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -print0)

count="$(find "$BACKUP_DIR" -maxdepth 1 -name 'cwa_prod_*.sql.gz' -type f | wc -l | tr -d ' ')"
log "Done. Retention: ${RETENTION_DAYS} days. ${count} prod backup(s) on disk. Pruned ${pruned}."
