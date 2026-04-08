#!/usr/bin/env bash
# restore_prod_to_test.sh
# -----------------------
# Copies the production PythonAnywhere database into the test database
# on the same MySQL server (no SSH required — run this from a
# PythonAnywhere Bash console or scheduled task).
#
# Usage:
#   bash restore_prod_to_test.sh
#
# Add --dry-run to see what would happen without changing anything.

# ── Config ────────────────────────────────────────────────────────────────────
DB_HOST="${DB_HOST:-avinesh.mysql.pythonanywhere-services.com}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-avinesh}"
DB_PASS="${DB_PASS:-wenuskala!1}"

SRC_DB="${SRC_DB:-avinesh\$cwa_classroom}"       # production
DST_DB="${DST_DB:-avinesh\$cwa_classroom_test}"  # test

DUMP_FILE="/tmp/prod_to_test_$(date +%Y%m%d_%H%M%S).sql"
# ─────────────────────────────────────────────────────────────────────────────

DRY_RUN=false
if [[ "${1}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[DRY RUN] No changes will be made to the database."
fi

MYSQL_OPTS="-h ${DB_HOST} -P ${DB_PORT} -u ${DB_USER} -p${DB_PASS}"

echo ""
echo "Source : ${SRC_DB}"
echo "Target : ${DST_DB}"
echo "Host   : ${DB_HOST}:${DB_PORT}"
echo ""

# ── Step 1: verify source DB is reachable ────────────────────────────────────
echo "==> Checking source DB..."
mysql ${MYSQL_OPTS} -e "SELECT 1;" "${SRC_DB}" > /dev/null 2>&1
if [[ $? -ne 0 ]]; then
    echo "ERROR: Cannot connect to source DB '${SRC_DB}'. Check credentials."
    exit 1
fi
echo "    OK"

# ── Step 2: verify (or create) destination DB ────────────────────────────────
echo "==> Checking destination DB..."
DB_EXISTS=$(mysql ${MYSQL_OPTS} -sse \
    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='${DST_DB}';" 2>/dev/null)

if [[ -z "$DB_EXISTS" ]]; then
    echo "    Destination DB '${DST_DB}' does not exist — will create it."
    if [[ "$DRY_RUN" == false ]]; then
        mysql ${MYSQL_OPTS} -e \
            "CREATE DATABASE \`${DST_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
        if [[ $? -ne 0 ]]; then
            echo "ERROR: Could not create database '${DST_DB}'."
            exit 1
        fi
    fi
else
    echo "    Destination DB exists — will drop and recreate."
fi

# ── Step 3: dump source ──────────────────────────────────────────────────────
echo "==> Dumping '${SRC_DB}' -> ${DUMP_FILE} ..."
if [[ "$DRY_RUN" == false ]]; then
    mysqldump ${MYSQL_OPTS} \
        --single-transaction \
        --routines \
        --triggers \
        --set-gtid-purged=OFF \
        "${SRC_DB}" > "${DUMP_FILE}"
    if [[ $? -ne 0 ]]; then
        echo "ERROR: mysqldump failed."
        rm -f "${DUMP_FILE}"
        exit 1
    fi
    DUMP_SIZE=$(du -sh "${DUMP_FILE}" | cut -f1)
    echo "    Dump complete (${DUMP_SIZE})"
else
    echo "    [DRY RUN] Would dump '${SRC_DB}' to ${DUMP_FILE}"
fi

# ── Step 4: drop and recreate destination ────────────────────────────────────
echo "==> Recreating '${DST_DB}'..."
if [[ "$DRY_RUN" == false ]]; then
    mysql ${MYSQL_OPTS} -e \
        "DROP DATABASE IF EXISTS \`${DST_DB}\`;
         CREATE DATABASE \`${DST_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    if [[ $? -ne 0 ]]; then
        echo "ERROR: Could not recreate '${DST_DB}'."
        rm -f "${DUMP_FILE}"
        exit 1
    fi
    echo "    OK"
else
    echo "    [DRY RUN] Would DROP + CREATE '${DST_DB}'"
fi

# ── Step 5: restore dump into destination ────────────────────────────────────
echo "==> Restoring dump into '${DST_DB}'..."
if [[ "$DRY_RUN" == false ]]; then
    mysql ${MYSQL_OPTS} "${DST_DB}" < "${DUMP_FILE}"
    if [[ $? -ne 0 ]]; then
        echo "ERROR: Restore failed."
        rm -f "${DUMP_FILE}"
        exit 1
    fi
    echo "    OK"
else
    echo "    [DRY RUN] Would restore ${DUMP_FILE} into '${DST_DB}'"
fi

# ── Cleanup ──────────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == false ]]; then
    rm -f "${DUMP_FILE}"
fi

echo ""
if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY RUN] Done — no changes were made."
else
    echo "Done — '${DST_DB}' is now a copy of '${SRC_DB}'."
    echo ""
    echo "Next steps (on PythonAnywhere, in your test virtualenv):"
    echo "  cd ~/cwa_classroom"
    echo "  python manage.py migrate --settings=cwa_classroom.settings_test"
    echo "  python ../scripts/run_all_prod_fixes.py --settings=cwa_classroom.settings_test"
fi
