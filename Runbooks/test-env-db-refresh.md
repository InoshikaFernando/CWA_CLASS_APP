# CWA Classroom — Test Environment & DB Refresh Runbook

How to refresh a **test** or **local** database from a production snapshot and
**sanitise** it so it is safe to develop against — scrambled PII, reset
passwords, no carried-over sessions. The supporting scripts live in
[`scripts/`](../scripts/).

> ⚠️ **Direction is one-way: prod → test → local.** Never run any sanitise or
> reset command against the production database. Every script in this runbook
> rewrites every user's email and password; running it on prod would lock out
> real users and destroy their data. Double-check the target DB name before
> every destructive step.

> 🔑 **Credentials never live in this runbook.** The scripts read DB host/user/
> password from environment variables (`DB_HOST`, `DB_USER`, `DB_PASS`,
> `SRC_DB`, `DST_DB`, …). Set them in your shell (or a sourced, git-ignored
> env file) — do not paste real passwords into commits, tickets, or chat.

---

## When to use this

- A tester/dev needs realistic data that mirrors prod shape without prod PII.
- You're reproducing a prod-only bug locally.
- You're validating a migration against real-world data before it ships.

The two supported flows:

| Flow | Scripts | Runs where |
|------|---------|------------|
| **Refresh the shared test DB** (same MySQL server as prod) | `restore_prod_to_test.sh` → `sanitise_test_db.sh` | On the DB host (e.g. a PythonAnywhere/SSH console) |
| **Refresh your local DB from a `.sql` backup** | `prepare_local_db.sh <backup.sql>` | Your workstation (local MySQL) |

---

## Prerequisites

- `mysql` + `mysqldump` clients available on the box you run from.
- Network reach to the source (prod) and destination (test/local) MySQL.
- The repo checked out; commands run from the **repo root** (the scripts expect
  `manage.py` at `cwa_classroom/manage.py`).
- The destination's Django env points at the destination DB — for the shared
  test DB that's `cwa_classroom/settings_test.py`
  (`--settings=cwa_classroom.settings_test`); locally it's your `.env`.
- Credentials exported as env vars (see the box above). Confirm them with a
  dry run before doing anything destructive.

---

## Flow A — Refresh the shared test database

This copies prod into a **separate test schema on the same MySQL server**, then
sanitises it. No SSH-into-prod required; it's pure SQL between two schemas.

### A.1 Dry-run the copy first

```bash
# Export creds for the source + destination (NOT committed):
export DB_HOST=<mysql-host> DB_PORT=3306 DB_USER=<user> DB_PASS=<password>
export SRC_DB='<prod_schema>'        # e.g. avinesh$cwa_classroom
export DST_DB='<test_schema>'        # e.g. avinesh$cwa_classroom_test

bash scripts/restore_prod_to_test.sh --dry-run
```

The dry run prints the source/target/host and what it *would* do without
touching anything. **Read the `Source`/`Target` lines and confirm `Target` is
the test schema, never prod.**

### A.2 Run the copy

```bash
bash scripts/restore_prod_to_test.sh
```

What it does (`scripts/restore_prod_to_test.sh`):

1. Verifies the **source** DB is reachable.
2. Creates the **destination** schema if missing, else drops + recreates it.
3. `mysqldump`s the source (`--single-transaction --routines --triggers
   --set-gtid-purged=OFF`) to a temp file.
4. Drops + recreates the destination, restores the dump, deletes the temp file.

At the end the destination is a byte-for-byte copy of prod — **including real
emails, phones, and password hashes.** It is **not yet safe.** Do not let anyone
log in until A.3 + A.4 complete.

### A.3 Apply migrations against the test schema

The dump is at prod's migration state; bring it to the current code's state:

```bash
cd cwa_classroom
python manage.py migrate --settings=cwa_classroom.settings_test
# Apply any prod data fixes the app expects:
python ../scripts/run_all_prod_fixes.py --settings=cwa_classroom.settings_test
```

### A.4 Sanitise (mandatory before anyone touches it)

```bash
# Same DB_* / DST_DB env as A.1 must still be exported.
bash scripts/sanitise_test_db.sh
```

What it does (`scripts/sanitise_test_db.sh`):

1. **Scrambles PII** — rewrites every email/phone across
   `accounts_customuser`, `accounts_pendingregistration`, `classroom_guardian`,
   `classroom_parentinvite`, `classroom_contactmessage`, `classroom_school`,
   `classroom_department`, `classroom_emaillog` to
   `<id>+test@example.com` and blanks phones.
2. **Resets every password** to `Password1!` (Django `set_password`).
3. **Clears `django_session`** so no prod login carries over.

> **Keep the scrub list current.** If a new model gains an email/phone column,
> add it to `sanitise_test_db.sh`. The script embeds the discovery query —
> re-run it after a schema change to catch new PII columns:
> ```sql
> SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
>  WHERE TABLE_SCHEMA = DATABASE()
>    AND (COLUMN_NAME LIKE '%email%' OR COLUMN_NAME LIKE '%phone%');
> ```
> A new PII column that isn't scrubbed is a **leak**, not a cosmetic gap.

### A.5 Verify sanitisation

```bash
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" "$DST_DB" -e "
  SELECT COUNT(*) AS unscrubbed_emails
    FROM accounts_customuser
   WHERE email NOT LIKE '%+test@example.com';"
# Expect: 0
```

Then smoke the test site:

```bash
cd cwa_classroom && python smoke_test.py https://<test-host>   # logs in as user1@test.local / Password1!
```

Any non-zero `unscrubbed_emails`, or a login that fails with `Password1!`, means
the sanitise step didn't fully run — **stop and re-run A.4** before handing the
environment to anyone.

---

## Flow B — Refresh a local database from a `.sql` backup

Use this to load a prod backup onto your workstation's MySQL and sanitise it for
local dev. Driven by `scripts/prepare_local_db.sh`.

### B.1 Run it

```bash
export DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=root DB_PASS=<local-pw> DB_NAME=cwa_classroom
bash scripts/prepare_local_db.sh /path/to/prod_backup.sql
```

What it does (`scripts/prepare_local_db.sh`):

1. Drops + recreates the local `DB_NAME` and imports the `.sql` dump.
2. Rewrites every user email → `wlhtestmails+<username>@gmail.com`.
3. Resets every password → `Password1!`.
4. Resets Stripe price IDs → dev/test IDs (so local billing doesn't hit live
   Stripe objects).
5. Clears sessions.

> On Windows/Git-Bash the script points `MYSQL_BIN` at the MySQL 8.0 install
> path — override it with `MYSQL_BIN=/path/to/mysql` if yours differs.

### B.2 Migrate + run locally

```bash
cd cwa_classroom
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Log in with any user's email and `Password1!`. From here you can drive the
[`ui-smoketest.md`](ui-smoketest.md) against real-shaped data.

---

## Sanitised-environment invariants

After **either** flow, all of the following must hold before the environment is
considered safe:

- ✅ No email anywhere resolves to a real person (`+test@example.com` /
  `wlhtestmails+...@gmail.com` only).
- ✅ Every password is `Password1!`.
- ✅ Sessions cleared — no prod login is active.
- ✅ Stripe/payment identifiers are dev/test, not live (Flow B does this; for
  Flow A confirm the test env's `STRIPE_*` env points at test keys).
- ✅ Outgoing email is pointed at a sink or a test mailbox, so sanitised users
  can't trigger real mail. **Never** run `send_*` management commands (e.g.
  `send_trial_expiry_warnings`) against a freshly-restored env until you've
  confirmed the email backend is non-production.

A failure of any invariant is a data-protection incident, not a test nit — fix
it before proceeding.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Cannot connect to source DB` | Wrong `DB_*` / `SRC_DB` | Re-export creds; verify with `mysql ... -e "SELECT 1"` |
| `mysqldump: Couldn't execute 'FLUSH TABLES'` | Insufficient privileges on managed MySQL | The script already uses `--single-transaction --no-tablespaces`; ensure the user has `SELECT, LOCK TABLES, SHOW VIEW` |
| `Unknown database` on restore | Schema name has a `$` and wasn't escaped | The scripts escape it (`avinesh\$cwa_classroom`); export `SRC_DB`/`DST_DB` with the literal `$`, quoted in single quotes |
| Migrations fail after restore | Prod schema older than code | That's expected — A.3 migrates forward. A genuine failure is a migration bug; fix it, don't skip |
| Login fails with `Password1!` after restore | Sanitise step skipped/failed | Re-run `sanitise_test_db.sh` (A.4) and verify A.5 |
| Real emails still present | New PII column not in the scrub list | Add the table/column to `sanitise_test_db.sh`, re-run |

---

## Legacy / migration note

The Flow-A scripts (`restore_prod_to_test.sh`, `sanitise_test_db.sh`) target the
**PythonAnywhere** MySQL host, and `scripts/migrate_db_pa_to_do.sh` exists to
move data from PythonAnywhere to the DigitalOcean Managed MySQL. As the app
completes its move to the Droplet (see `docs/MIGRATION_PLAN.md` and
`production-deployment.md` § 6), point `DB_HOST`/`SRC_DB`/`DST_DB` at the
DigitalOcean instance instead — the sanitise logic is host-agnostic and applies
unchanged.

---

## See also

- [`production-deployment.md`](production-deployment.md) — prod host + release flow
- [`ui-smoketest.md`](ui-smoketest.md) — exercise the refreshed environment
- [`scripts/restore_prod_to_test.sh`](../scripts/restore_prod_to_test.sh),
  [`scripts/sanitise_test_db.sh`](../scripts/sanitise_test_db.sh),
  [`scripts/prepare_local_db.sh`](../scripts/prepare_local_db.sh)
