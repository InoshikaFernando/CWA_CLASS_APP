#!/usr/bin/env bash
# migrate_db_pa_to_do.sh
# ----------------------
# Migrates the CWA Classroom MySQL database from PythonAnywhere to
# DigitalOcean Managed MySQL.
#
# Three modes:
#   bash migrate_db_pa_to_do.sh dump      # Step 1: dump from PA
#   bash migrate_db_pa_to_do.sh restore   # Step 2: restore to DO
#   bash migrate_db_pa_to_do.sh verify    # Step 3: row-count comparison
#
# Requirements:
#   - SSH key on PythonAnywhere
#   - mysql client that supports TLS
#   - DO Managed MySQL CA cert downloaded to DO_SSL_CA path

set -euo pipefail

# ── PythonAnywhere source ────────────────────────────────────────────────────
PA_USER="${PA_USER:-inoshika}"
PA_HOST="${PA_HOST:-ssh.pythonanywhere.com}"
PA_DB_USER="${PA_DB_USER:-inoshika}"
PA_DB_PASS="${PA_DB_PASS:-}"
PA_DB_NAME="${PA_DB_NAME:-inoshika\$cwa_classroom}"

# ── DigitalOcean target ──────────────────────────────────────────────────────
DO_DB_USER="${DO_DB_USER:-}"
DO_DB_PASS="${DO_DB_PASS:-}"
DO_DB_HOST="${DO_DB_HOST:-}"
DO_DB_PORT="${DO_DB_PORT:-25060}"
DO_DB_NAME="${DO_DB_NAME:-cwa_classroom}"
DO_SSL_CA="${DO_SSL_CA:-/etc/cwa/do-ca.pem}"

# ── Dump file ────────────────────────────────────────────────────────────────
DUMP_DIR="${DUMP_DIR:-/tmp}"
DUMP_FILE="${DUMP_DIR}/pa_to_do_$(date +%Y%m%d_%H%M%S).sql.gz"

# ── Helpers ──────────────────────────────────────────────────────────────────

prompt_pa_pass() {
    if [ -z "$PA_DB_PASS" ]; then
        read -s -p "PythonAnywhere MySQL password: " PA_DB_PASS
        echo
    fi
}

prompt_do_pass() {
    if [ -z "$DO_DB_PASS" ]; then
        read -s -p "DO Managed MySQL password: " DO_DB_PASS
        echo
    fi
}

check_do_vars() {
    for var in DO_DB_USER DO_DB_HOST; do
        if [ -z "${!var}" ]; then
            echo "ERROR: $var is not set. Export it or set it in the script."
            exit 1
        fi
    done
    if [ ! -f "$DO_SSL_CA" ]; then
        echo "ERROR: CA cert not found at $DO_SSL_CA"
        echo "Download it from the DO database dashboard → Connection Details → Download CA Certificate"
        exit 1
    fi
}

do_mysql() {
    mysql -u "$DO_DB_USER" -p"$DO_DB_PASS" \
          -h "$DO_DB_HOST" -P "$DO_DB_PORT" \
          --ssl-ca="$DO_SSL_CA" \
          "$@"
}

# ── Step 1: Dump from PythonAnywhere ─────────────────────────────────────────

cmd_dump() {
    prompt_pa_pass

    echo "==> Dumping from PythonAnywhere..."
    echo "    DB: ${PA_DB_NAME}"
    echo "    Dump: ${DUMP_FILE}"

    ssh "${PA_USER}@${PA_HOST}" \
        "mysqldump --single-transaction --routines --triggers \
         --default-character-set=utf8mb4 --no-tablespaces \
         -u '${PA_DB_USER}' -p'${PA_DB_PASS}' '${PA_DB_NAME}' | gzip" \
        > "${DUMP_FILE}"

    echo "==> Dump complete: $(du -h "$DUMP_FILE" | cut -f1)"
    echo ""
    echo "Next: bash $0 restore"
}

# ── Step 2: Restore to DigitalOcean ──────────────────────────────────────────
# Accepts a SQL file as argument: bash migrate_db_pa_to_do.sh restore /path/to/export.sql
# Supports: .sql, .sql.gz, .gz

cmd_restore() {
    check_do_vars
    prompt_do_pass

    INPUT_FILE="${2:-}"

    if [ -n "$INPUT_FILE" ]; then
        if [ ! -f "$INPUT_FILE" ]; then
            echo "ERROR: File not found: $INPUT_FILE"
            exit 1
        fi
        DUMP_FILE="$INPUT_FILE"
        echo "Using provided file: $DUMP_FILE"
    elif [ ! -f "${DUMP_FILE}" ]; then
        DUMP_FILE=$(ls -t "${DUMP_DIR}"/pa_to_do_*.sql.gz 2>/dev/null | head -1)
        if [ -z "$DUMP_FILE" ]; then
            echo "ERROR: No dump file found."
            echo "  Either provide a SQL file:  bash $0 restore /path/to/export.sql"
            echo "  Or run the dump step first: bash $0 dump"
            exit 1
        fi
        echo "Using most recent dump: $DUMP_FILE"
    fi

    echo "==> Testing DO connection..."
    do_mysql -e "SELECT 1;" "$DO_DB_NAME" > /dev/null
    echo "    Connected OK"

    echo "==> Verifying TLS..."
    TLS_CIPHER=$(do_mysql -N -e "SHOW STATUS LIKE 'Ssl_cipher';" "$DO_DB_NAME" | awk '{print $2}')
    if [ -z "$TLS_CIPHER" ]; then
        echo "ERROR: Connection is NOT encrypted!"
        exit 1
    fi
    echo "    TLS cipher: $TLS_CIPHER"

    echo "==> Restoring to DO Managed MySQL..."
    case "$DUMP_FILE" in
        *.gz)  gunzip < "$DUMP_FILE" | do_mysql "$DO_DB_NAME" ;;
        *.sql) do_mysql "$DO_DB_NAME" < "$DUMP_FILE" ;;
        *)     echo "ERROR: Unsupported file type. Use .sql or .sql.gz"; exit 1 ;;
    esac

    echo "==> Restore complete."
    echo ""
    echo "Next: bash $0 verify"
}

# ── Step 3: Verify row counts ────────────────────────────────────────────────

cmd_verify() {
    prompt_pa_pass
    check_do_vars
    prompt_do_pass

    echo "==> Comparing row counts between PA and DO..."
    echo ""

    # Get table list from DO (source of truth for what was restored)
    TABLES=$(do_mysql -N -e \
        "SELECT table_name FROM information_schema.tables
         WHERE table_schema='${DO_DB_NAME}' AND table_type='BASE TABLE'
         ORDER BY table_name;" "$DO_DB_NAME")

    PASS=0
    FAIL=0

    printf "%-50s %10s %10s %s\n" "TABLE" "PA" "DO" "STATUS"
    printf "%-50s %10s %10s %s\n" "-----" "--" "--" "------"

    for TABLE in $TABLES; do
        PA_COUNT=$(ssh "${PA_USER}@${PA_HOST}" \
            "mysql -N -u '${PA_DB_USER}' -p'${PA_DB_PASS}' '${PA_DB_NAME}' \
             -e \"SELECT COUNT(*) FROM \\\`${TABLE}\\\`;\"" 2>/dev/null || echo "ERR")

        DO_COUNT=$(do_mysql -N -e \
            "SELECT COUNT(*) FROM \`${TABLE}\`;" "$DO_DB_NAME" 2>/dev/null || echo "ERR")

        if [ "$PA_COUNT" = "$DO_COUNT" ]; then
            STATUS="OK"
            PASS=$((PASS + 1))
        else
            STATUS="MISMATCH"
            FAIL=$((FAIL + 1))
        fi

        printf "%-50s %10s %10s %s\n" "$TABLE" "$PA_COUNT" "$DO_COUNT" "$STATUS"
    done

    echo ""
    echo "==> Results: $PASS passed, $FAIL failed"

    if [ "$FAIL" -gt 0 ]; then
        echo "WARNING: Row count mismatches detected! Investigate before switching over."
        exit 1
    else
        echo "All tables match. Safe to proceed with Django wire-up."
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

case "${1:-}" in
    dump)    cmd_dump ;;
    restore) cmd_restore "$@" ;;
    verify)  cmd_verify ;;
    *)
        echo "Usage: bash $0 {dump|restore [file]|verify}"
        echo ""
        echo "  dump              — mysqldump from PythonAnywhere via SSH"
        echo "  restore           — restore most recent dump to DO"
        echo "  restore file.sql  — restore a SQL file you already have"
        echo "  verify            — compare row counts PA vs DO"
        exit 1
        ;;
esac
