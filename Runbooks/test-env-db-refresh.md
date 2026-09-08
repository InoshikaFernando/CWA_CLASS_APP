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

> 🔑 **Credentials never live in this runbook, or in the scripts.** Flow A reads
> every DB credential out of the systemd env files already on the droplet
> (`/etc/cwa/cwa.env` for prod, `/etc/cwa/cwa-test.env` for test) — there is
> nothing to export and nothing to paste. Flow B reads `DB_*` from your shell.
> Do not put real passwords into commits, tickets, or chat.

---

## When to use this

- A tester/dev needs realistic data that mirrors prod shape without prod PII.
- You're reproducing a prod-only bug locally.
- You're validating a migration against real-world data before it ships.

The two supported flows:

| Flow | Scripts | Runs where |
|------|---------|------------|
| **Refresh the shared test DB** (same managed MySQL as prod) | `restore_prod_to_test.sh` (migrates + sanitises + re-points Stripe itself) | On the DigitalOcean droplet, as the `cwa` user |
| **Refresh the dev DB** | `restore_prod_to_dev.sh` | On the droplet, as the `cwa` user |
| **Refresh your local DB from a `.sql` backup** | `prepare_local_db.sh <backup.sql>` | Your workstation (local MySQL) |

---

## Prerequisites

- **Flow A runs on the droplet**, not your workstation: only the droplet can
  reach the private managed-MySQL host and read `/etc/cwa/*.env`.
- `mysql` + `mysqldump` clients on that box (already there — the app uses MySQL).
- The test checkout at `/home/cwa/CWA_CLASS_APP_TEST` with its own virtualenv.
- The test environment on **`sk_test_` Stripe keys**. The script aborts on a
  live key rather than handing a tester a site that charges real cards.
- Flow B only: `DB_*` exported in your shell for your local MySQL.

---

## Flow A — Refresh the shared test database

This copies prod into the **test schema on the same managed MySQL server**, then
migrates, sanitises, and re-points Stripe. It is one command; the steps below
describe what that command does and how to read its output.

### A.1 Dry-run first

```bash
sudo -u cwa bash scripts/restore_prod_to_test.sh --dry-run
```

The dry run prints the resolved source/target and stops. **Read the `Source`/
`Target` lines and confirm `Target` is the test schema, never prod.** The script
also refuses outright if the target DB name does not contain `test`, if source
and target are the same database, or if the test env still holds an `sk_live_`
Stripe key.

### A.2 Run it

```bash
sudo -u cwa bash scripts/restore_prod_to_test.sh
```

What it does, in order:

1. Reads prod + test DB credentials from `/etc/cwa/cwa.env` and
   `/etc/cwa/cwa-test.env`. Nothing is hardcoded and nothing is exported.
2. Runs the guards above.
3. `mysqldump`s prod (`--single-transaction --no-tablespaces --routines
   --triggers --set-gtid-purged=OFF`) to a temp file.
4. Drops + recreates the test schema, restores the dump, deletes the temp file.
   **At this instant the test DB holds real emails and real password hashes.**
   Nobody may log in until step 6 has run.
5. `manage.py migrate` against the test env — the dump is at prod's migration
   state, the code may be ahead.
6. **Sanitises** via `scripts/sanitize_test_db.py`: every password →
   `Password1!`, every email → `user<id>@test.local`, all Stripe identifiers
   blanked, email log **and the pending email queue** dropped, pending passwords
   and invite tokens cleared, sessions cleared.
7. **Re-points Stripe**: `sync_stripe_prices --create-missing` links or mints
   test-mode prices for every Package / InstitutePlan / ModuleProduct, then
   `sync_stripe_coupons` recreates the discount coupons in test mode.
8. **Verifies, and fails loudly.** It counts unscrubbed user emails (must be 0)
   and runs `check_stripe_prices --fresh`. A non-zero exit from either means the
   environment is not fit to hand over — read the listed rows and fix them.

### A.3 Why step 7 is not optional

A prod dump carries prod's **live** Stripe price ids. Restored onto a test site
running `sk_test_` keys, every one of them is an object the test key cannot see;
Stripe answers *"No such price"* and the app shows its generic *"contact
support"*. Nothing turns red — the test site simply stops taking payments, and
you find out from a tester's screenshot. That is precisely what happened in
September 2026 after a prod→test copy, and it is why the script now ends on
`check_stripe_prices` as a hard gate rather than a suggestion.

Blanking the ids is not enough on its own either: a Package with an empty
`stripe_price_id` fails checkout just as surely as one with a live id. Steps 6
and 7 only work as a pair.

### A.4 Verify by hand if you want a second opinion

```bash
cd /home/cwa/CWA_CLASS_APP_TEST/cwa_classroom
set -a; source /etc/cwa/cwa-test.env; set +a
../venv/bin/python manage.py check_stripe_prices --fresh
../venv/bin/python smoke_test.py https://test.wizardslearninghub.co.nz
```

Log in as `user<id>@test.local` / `Password1!`. A login that fails with that
password, or a non-zero `check_stripe_prices`, means the run did not finish —
re-run A.2 rather than patching around it.

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

- ✅ No email anywhere resolves to a real person — `user<id>@test.local` after
  Flow A, `wlhtestmails+<username>@gmail.com` after Flow B.
- ✅ Every password is `Password1!`.
- ✅ Sessions cleared — no prod login is active.
- ✅ Stripe/payment identifiers are dev/test, not live — and **chargeable**.
  Both flows blank the live ids; Flow A then re-points them at test-mode objects
  and proves it with `check_stripe_prices`. "No live ids" is only half the
  invariant: a test site that cannot take a test payment is also broken.
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
| `ABORT: test DB name '…' does not contain 'test'` | `DB_NAME` in `/etc/cwa/cwa-test.env` points somewhere else | Do **not** loosen the guard. Fix the env file |
| `ABORT: … holds a LIVE Stripe secret key` | Test env has `sk_live_` | Put `sk_test_` keys in `/etc/cwa/cwa-test.env` before restoring |
| Migrations fail after restore | Prod schema older than code | Expected direction; the script migrates forward. A genuine failure is a migration bug — fix it, don't skip |
| Login fails with `Password1!` after restore | The run died before the sanitise step | Re-run the script. Never hand the environment over in this state |
| `FAILED: N user email(s) are still real addresses` | Sanitiser did not complete | Re-run the script; if it repeats, a new PII column needs adding to `scripts/sanitize_test_db.py` |
| `check_stripe_prices` exits non-zero at the end | Prices could not be linked or minted in test mode | Read the per-row `→` remedy it prints; the same data is on the ops dashboard |

---

## Legacy / migration note

Flow A used to target the **PythonAnywhere** MySQL host and carried its
credentials as literal shell defaults. Both sites moved to DigitalOcean
Droplets with managed MySQL (`scripts/migrate_db_pa_to_do.sh` did the move), so
`restore_prod_to_test.sh` now reads `/etc/cwa/*.env` like the deploy does, and
the old `sanitise_test_db.sh` is gone — `scripts/sanitize_test_db.py` did
everything it did and more, and the script now calls it directly.

Any older ticket or note telling you to export `DB_HOST`/`SRC_DB`/`DST_DB` for
Flow A, or to run `sanitise_test_db.sh` afterwards, is stale.

---

## See also

- [`production-deployment.md`](production-deployment.md) — prod host + release flow
- [`ui-smoketest.md`](ui-smoketest.md) — exercise the refreshed environment
- [`scripts/restore_prod_to_test.sh`](../scripts/restore_prod_to_test.sh),
  [`scripts/restore_prod_to_dev.sh`](../scripts/restore_prod_to_dev.sh),
  [`scripts/sanitize_test_db.py`](../scripts/sanitize_test_db.py),
  [`scripts/prepare_local_db.sh`](../scripts/prepare_local_db.sh)
