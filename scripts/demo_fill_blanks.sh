#!/usr/bin/env bash
#
# demo_fill_blanks.sh — see the fill-in-the-blank question type before and after.
#
# Builds a THROWAWAY SQLite database (never your real one), seeds the same
# sample questions twice — once stored the way they are today, once converted by
# the same code path the bulk command uses — and starts the dev server so both
# can be opened side by side.
#
#   ./scripts/demo_fill_blanks.sh              # seed + run the server
#   ./scripts/demo_fill_blanks.sh --report     # also print the answer mapping
#   ./scripts/demo_fill_blanks.sh --no-serve   # seed and print URLs only
#
# The database lives at cwa_classroom/fill_blank_demo.sqlite3 and can be deleted
# at any time. Nothing here touches the test or production databases.
set -euo pipefail

cd "$(dirname "$0")/../cwa_classroom"

export DB_ENGINE=sqlite
export SQLITE_NAME=fill_blank_demo.sqlite3
export DJANGO_DEBUG=True

SERVE=1
REPORT=()
for arg in "$@"; do
  case "$arg" in
    --no-serve) SERVE=0 ;;
    --report)   REPORT+=(--report) ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

echo "==> Preparing the demo database ($SQLITE_NAME)"
rm -f "$SQLITE_NAME" "$SQLITE_NAME"-wal "$SQLITE_NAME"-shm

# Build the schema straight from the models, with migrations switched off —
# the same thing the test suite does on SQLite (see conftest.py's
# django_db_use_migrations). The migration history has MySQL-only steps in it,
# so replaying it against SQLite fails; the models are the source of truth here
# and this keeps the demo independent of that.
python - <<'PY'
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cwa_classroom.settings')
django.setup()

from django.conf import settings


class _NoMigrations:
    """Report every app as unmigrated, so migrate --run-syncdb builds its tables."""

    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


settings.MIGRATION_MODULES = _NoMigrations()

from django.core.management import call_command
call_command('migrate', run_syncdb=True, interactive=False, verbosity=0)
PY

echo "==> Seeding BEFORE / AFTER questions"
python manage.py seed_fill_blank_demo --force "${REPORT[@]+"${REPORT[@]}"}"

echo
echo "==> What the bulk converter would do to the BEFORE copies"
echo "    (dry run — this is the command you would run against the real database)"
python manage.py convert_fill_blanks --min-blanks 1

if [ "$SERVE" -eq 1 ]; then
  echo
  echo "==> Starting the server — Ctrl-C to stop"
  python manage.py runserver 0.0.0.0:8000
fi
