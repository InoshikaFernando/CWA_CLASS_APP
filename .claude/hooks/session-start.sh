#!/bin/bash
# .claude/hooks/session-start.sh
# ------------------------------
# SessionStart hook for Claude Code on the web.
# Installs the Python deps so the pytest suites, the Django dev server, and
# the Playwright UI tests work the moment a remote session starts.
#
# Idempotent and non-interactive — safe to run repeatedly. The container
# state is cached after this completes, so a clean second run is fast.
set -euo pipefail

# Only run in Claude Code on the web (remote) sessions — local users manage
# their own virtualenv.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$REPO_DIR"

echo "==> [session-start] Ensuring MySQL client headers for mysqlclient..."
# The apt index may carry broken third-party PPAs (deadsnakes/ondrej) that
# 403 on update — those are unrelated to us, so never let them abort setup.
apt-get update -qq 2>/dev/null || true
apt-get install -y -qq default-libmysqlclient-dev pkg-config build-essential 2>/dev/null \
  || echo "    (MySQL client lib unavailable — will fall back to a sqlite-only install)"

echo "==> [session-start] Installing Python dependencies..."
if pip install -q -r cwa_classroom/requirements-test.txt; then
  echo "    Full test requirements installed (MySQL + Playwright tooling)."
else
  # mysqlclient could not build. Tests default to SQLite (see conftest.py),
  # so install everything except mysqlclient and keep going rather than
  # leaving the session with no deps at all.
  echo "    mysqlclient build failed — installing the sqlite-compatible subset."
  TMP_REQS="$(mktemp)"
  grep -viE '^mysqlclient' cwa_classroom/requirements.txt > "$TMP_REQS"
  grep -viE '^-r |^mysqlclient' cwa_classroom/requirements-test.txt >> "$TMP_REQS"
  pip install -q -r "$TMP_REQS"
  rm -f "$TMP_REQS"
fi

echo "==> [session-start] Checking the Playwright Chromium browser (UI tests)..."
# Non-fatal: UI tests need a browser, but a missing one shouldn't block a
# session that's only touching backend code. Failures are reported rather than
# hidden — a silently skipped install produced a container where all 120
# ui_tests/ died with a bare "Executable doesn't exist", which reads like
# broken tests instead of a missing browser.
if [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && \
   compgen -G "${PLAYWRIGHT_BROWSERS_PATH}/chromium*" >/dev/null 2>&1; then
  # The image pre-installs Chromium and blocks re-downloading. The build may
  # not match the one our pinned playwright expects, so ui_tests/conftest.py
  # resolves the executable explicitly (see _preinstalled_chromium).
  echo "    Using the pre-installed Chromium in ${PLAYWRIGHT_BROWSERS_PATH} (no download)."
elif PW_OUTPUT="$(playwright install chromium 2>&1)"; then
  echo "    Chromium installed."
else
  echo "    WARNING: Chromium install failed — ui_tests/ will not run."
  echo "${PW_OUTPUT}" | tail -5 | sed 's/^/      /'
fi

echo "==> [session-start] Done. Run tests from cwa_classroom/ (e.g. pytest classroom/tests/)."
