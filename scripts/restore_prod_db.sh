#!/usr/bin/env bash
# restore_prod_db.sh
# ------------------
# Dumps the production MySQL database from PythonAnywhere via SSH,
# downloads it, and restores it to the local dev database.
#
# Usage:
#   bash restore_prod_db.sh
#
# Requirements:
#   - SSH key already added to PythonAnywhere (Account > SSH keys)
#   - mysql / mysqldump available locally
#   - Set the variables below (or export them as env vars before running)

# ── Config ────────────────────────────────────────────────────────────────────
PA_USER="${PA_USER:-inoshika}"                        # PythonAnywhere username
PA_HOST="${PA_HOST:-ssh.pythonanywhere.com}"          # SSH host
PA_DB_USER="${PA_DB_USER:-inoshika}"                  # MySQL user on PA
PA_DB_PASS="${PA_DB_PASS:-}"                          # MySQL password on PA (prompt if blank)
PA_DB_NAME="${PA_DB_NAME:-inoshika\$cwa_classroom}"   # DB name on PA

LOCAL_DB_USER="${LOCAL_DB_USER:-root}"
LOCAL_DB_PASS="${LOCAL_DB_PASS:-root}"
LOCAL_DB_HOST="${LOCAL_DB_HOST:-127.0.0.1}"
LOCAL_DB_PORT="${LOCAL_DB_PORT:-3306}"
LOCAL_DB_NAME="${LOCAL_DB_NAME:-cwa_classroom}"

DUMP_FILE="/tmp/prod_dump_$(date +%Y%m%d_%H%M%S).sql.gz"
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo "==> Dumping prod DB from PythonAnywhere..."
if [ -z "$PA_DB_PASS" ]; then
    read -s -p "PythonAnywhere MySQL password: " PA_DB_PASS
    echo
fi

ssh "${PA_USER}@${PA_HOST}" \
    "mysqldump -u '${PA_DB_USER}' -p'${PA_DB_PASS}' '${PA_DB_NAME}' | gzip" \
    > "${DUMP_FILE}"

echo "==> Downloaded to ${DUMP_FILE}"

echo "==> Dropping and recreating local DB '${LOCAL_DB_NAME}'..."
mysql -u "${LOCAL_DB_USER}" -p"${LOCAL_DB_PASS}" \
      -h "${LOCAL_DB_HOST}" -P "${LOCAL_DB_PORT}" \
      -e "DROP DATABASE IF EXISTS \`${LOCAL_DB_NAME}\`; CREATE DATABASE \`${LOCAL_DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "==> Restoring dump to local DB..."
gunzip < "${DUMP_FILE}" | \
    mysql -u "${LOCAL_DB_USER}" -p"${LOCAL_DB_PASS}" \
          -h "${LOCAL_DB_HOST}" -P "${LOCAL_DB_PORT}" \
          "${LOCAL_DB_NAME}"

echo "==> Done. Local DB '${LOCAL_DB_NAME}' restored from prod."
echo ""
echo "Next steps:"
echo "  1. cd cwa_classroom && python manage.py migrate --fake-initial"
echo "  2. python ../scripts/fix_topic_parents.py"
echo "  3. python ../scripts/fix_unsimplified_fraction_answers.py"
echo "  4. python ../scripts/seed_times_tables.py"

rm -f "${DUMP_FILE}"
