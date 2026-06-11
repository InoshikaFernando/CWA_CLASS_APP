# CWA Classroom — Runbooks

Operational runbooks for the **CWA Classroom** app (Wizards Learning Hub).
Each runbook is a self-contained, start-to-finish procedure that an engineer
**or an AI agent** can execute against the real stack without guessing.

CWA Classroom is a Django 4.2 monolith:

- **Backend:** Django 4.2 (single `cwa_classroom` project, ~18 apps).
- **Database:** MySQL in production; SQLite for the test suite (`DB_ENGINE`).
- **Cache / sessions / Celery broker:** Redis.
- **Serving:** gunicorn (systemd unit `cwa-gunicorn`, unix socket) behind
  **Caddy** (auto-TLS reverse proxy). Static via WhiteNoise; media on
  DigitalOcean Spaces.
- **Code execution (coding app):** Piston (`docker-compose.piston.yml`).
- **Hosting:** DigitalOcean Droplet (`app-prod`, SYD1). A legacy
  PythonAnywhere deployment is being migrated out (see `docs/MIGRATION_PLAN.md`).

## Index

| Runbook | When to use it |
|---------|----------------|
| [`ui-smoketest.md`](ui-smoketest.md) | End-to-end click-through of the running app — login + CRUD across the core surfaces (classes, students, attendance, questions, quizzes, invoices). Run before/after a risky change or a release. |
| [`production-deployment.md`](production-deployment.md) | Bring up a fresh production Droplet, ship a release, roll back, reset the admin password, run day-2 ops. |
| [`test-env-db-refresh.md`](test-env-db-refresh.md) | Refresh the test/dev database from a prod snapshot and **sanitise** it (scramble PII, reset passwords) before anyone touches it. |
| [`github-ticket-implementation.md`](github-ticket-implementation.md) | Agent workflow for taking one issue/ticket from "assigned" to merged-and-verified: implement, test, PR, watch CI, deploy-verify, close. |

## Conventions used across these runbooks

- **No silent failure.** If a page renders `—`/blank where data should be, a
  save swallows a 4xx, or a management command exits 0 having done nothing —
  that is the bug. Trace it (browser → view → model → DB), fix the right
  layer, add/extend a test, then resume. Never patch the database by hand to
  make a runbook "pass".
- **Sanitised test credentials.** After a DB refresh every user's password is
  `Password1!` and emails are scrambled (`<id>+test@example.com`). These
  credentials are **only** valid on dev/test — never in production.
- **Secrets live in env files, not here.** Production secrets are in
  `/etc/cwa/cwa.env` (mode 600). The DB-refresh scripts read credentials from
  environment variables — never paste real passwords into a runbook or a
  commit.
- **`manage.py` lives at `cwa_classroom/manage.py`.** Every Django command in
  these runbooks is run from that directory (or with the venv python and a
  full path). The repo root is one level up.
