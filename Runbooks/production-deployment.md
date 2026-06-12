# CWA Classroom — Production Deployment Runbook

How CWA Classroom is brought up on a fresh DigitalOcean Droplet, how releases
are shipped after first install, and the day-2 operations (rollback, admin
password reset, log access). The supporting scripts live in
[`deploy/`](../deploy/) and [`scripts/`](../scripts/).

## TL;DR

- **Test site:** every merge to `test` auto-deploys (`deploy-test.yml`).
- **Production:** scheduled weekly release, Sunday ~03:00 NZ, of `main`
  (`deploy-prod.yml`); also runnable manually. See § 2 for the full model.

Both run the same script the manual path does:

```bash
# On the server, as the cwa user, from the repo root:
DEPLOY_BRANCH=<test|main> bash scripts/deploy.sh
```

That pulls the branch, installs deps, migrates, collects static, runs
`check --deploy`, restarts gunicorn, **and runs a deep health gate** that fails
the deploy if the DB, migrations, or cache aren't healthy. Verify manually with:

```bash
curl -s https://www.wizardslearninghub.co.nz/api/health/            # shallow: version + liveness
curl -s "https://www.wizardslearninghub.co.nz/api/health/?deep=1"   # deep: DB + migrations + cache
# Shallow expect: {"status":"ok","version":"1.5.0", ...}  (version == the tag you shipped)
# Deep expect:   adds "checks":{...}; HTTP 503 + "status":"degraded" if anything is wrong
```

---

## Architecture

| Component | What | Where |
|-----------|------|-------|
| Reverse proxy / TLS | **Caddy** (auto Let's Encrypt) | `deploy/Caddyfile`, `/etc/caddy/Caddyfile` |
| App server | **gunicorn** (3 workers, unix socket) | `deploy/cwa-gunicorn.service` → `/etc/systemd/system/` |
| App | Django 4.2 (`cwa_classroom.wsgi`) | `/home/cwa/CWA_CLASS_APP/cwa_classroom` |
| Database | DigitalOcean **Managed MySQL** (TLS) | configured in `/etc/cwa/cwa.env` |
| Cache / sessions / broker | **Redis** | `REDIS_URL` in env |
| Static files | **WhiteNoise** (served by Django) | `collectstatic` |
| Media | DigitalOcean **Spaces** (S3-compatible) | `USE_S3=True` + `AWS_*` in env |
| Code execution (coding app) | **Piston** | `docker-compose.piston.yml` |

Socket path: gunicorn binds `unix:/run/cwa/gunicorn.sock`; Caddy
`reverse_proxy`'s to it. Logs land in `/var/log/cwa/` and `/var/log/caddy/`.

---

## Prerequisites on the host

| Requirement | Why |
|-------------|-----|
| Ubuntu 24.04 Droplet (SYD1) | Base OS the setup script targets |
| Ports `80`, `443` open | Caddy (HTTP→HTTPS + TLS) |
| DNS `wizardslearninghub.co.nz` → Droplet reserved IP | Caddy provisions the cert by hostname |
| DigitalOcean Managed MySQL reachable from the Droplet | App database |
| DO Spaces bucket + keys | Media storage |
| The DO Managed-MySQL CA cert | TLS to the DB (`DB_SSL_CA`) |

No Python/MySQL-server install needed beyond what `setup-app-prod.sh` installs;
the database is managed by DigitalOcean.

---

## 1. First-time install (fresh Droplet)

Run the one-time setup script as root. It is idempotent enough to re-run, but
is designed for a clean Droplet.

```bash
scp deploy/setup-app-prod.sh root@<droplet-ip>:/tmp/
ssh root@<droplet-ip> bash /tmp/setup-app-prod.sh
```

What it does (see `deploy/setup-app-prod.sh`):

1. `apt` update/upgrade; installs Python 3, build deps,
   `default-libmysqlclient-dev`, git, ufw, and **Caddy**.
2. Creates the `cwa` deploy user and the dirs `/etc/cwa`, `/var/log/cwa`,
   `/var/log/caddy`, `/run/cwa`.
3. Clones the repo to `/home/cwa/CWA_CLASS_APP`, checks out the deploy branch
   (`DEPLOY_BRANCH`, default `main`), creates the venv, installs
   `requirements.txt` + gunicorn.
4. Installs the systemd unit `cwa-gunicorn` and enables it.
5. Installs the Caddyfile and enables Caddy.
6. Sets up logrotate for `/var/log/cwa/*.log`.
7. Grants the `cwa` user passwordless `systemctl restart/reload cwa-gunicorn`
   (so `deploy.sh` can restart without root).

### 1.1 Configure secrets

```bash
cp /home/cwa/CWA_CLASS_APP/deploy/cwa.env.example /etc/cwa/cwa.env
chmod 600 /etc/cwa/cwa.env
chown cwa:cwa /etc/cwa/cwa.env
# Edit /etc/cwa/cwa.env with real values:
```

Required (see `deploy/cwa.env.example`): `SECRET_KEY` (generate fresh — see
below), `DEBUG=False`, `ALLOWED_HOSTS`, the `DB_*` block (incl. `DB_SSL_CA`),
`REDIS_URL`, the `AWS_*` Spaces block with `USE_S3=True`, the email provider
keys, the `STRIPE_*` keys, `PISTON_API_URL`, and `SITE_URL`.

```bash
# Generate a SECRET_KEY:
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# Download the DO Managed-MySQL CA cert (URL from the DO dashboard):
curl -o /etc/cwa/do-ca.pem "<ca-cert-url-from-DO>"
chown cwa:cwa /etc/cwa/do-ca.pem
```

### 1.2 Initialise the database & static

```bash
sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python \
    /home/cwa/CWA_CLASS_APP/cwa_classroom/manage.py migrate --noinput
sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python \
    /home/cwa/CWA_CLASS_APP/cwa_classroom/manage.py collectstatic --noinput
# Seed roles + create the first admin:
sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python \
    /home/cwa/CWA_CLASS_APP/cwa_classroom/manage.py setup_roles
sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python \
    /home/cwa/CWA_CLASS_APP/cwa_classroom/manage.py createsuperuser
```

> Do **not** run `reset_users_for_dev`, `setup_dev`, or any sanitise script in
> production — those set every password to `Password1!`. They are dev/test only.

### 1.3 Start services & point DNS

```bash
systemctl start cwa-gunicorn && systemctl status cwa-gunicorn --no-pager
systemctl start caddy        && systemctl status caddy        --no-pager
```

Point `wizardslearninghub.co.nz` (and `www`) at the Droplet's reserved IP.
Caddy provisions the TLS cert automatically on the first HTTPS request once DNS
resolves.

### 1.4 Verify

```bash
curl -s https://www.wizardslearninghub.co.nz/api/health/ | python3 -m json.tool
# status: ok, version matches settings.APP_VERSION
```

Then run the scripted liveness check from your workstation (prod-safe, no
login required):

```bash
cd cwa_classroom && python smoke_test.py https://www.wizardslearninghub.co.nz --public-only
```

---

## 2. Release model & shipping

Two pipelines, matching the `test` → `main` branch flow:

| Branch | Trigger | What it does | Workflow |
|--------|---------|--------------|----------|
| `test` | **every push** (each merged PR) | deploys to the **test site** | [`deploy-test.yml`](../.github/workflows/deploy-test.yml) |
| `main` | **scheduled — Sunday ~03:00 NZ** (+ manual) | **auto-merges `test` → `main`, then deploys to production** | [`deploy-prod.yml`](../.github/workflows/deploy-prod.yml) |

So PRs land on `test` and deploy to the test site immediately. Once a week the
prod job promotes the whole `test` branch into `main` (a `--no-ff` merge it
pushes itself) and deploys the result to production — **no review PR, no manual
step.** The deep health gate, the public smoke test, and the Sunday-morning
timing are the only safety net; a `test → main` merge conflict aborts the
release (nothing deploys). Both pipelines run `scripts/deploy.sh` over SSH and
alert to `DEPLOY_ALERT_WEBHOOK` on failure.

> **The prod schedule only fires from the default branch (`main`).** So
> `deploy-prod.yml` must live on `main` — the initial `test` → `main`
> reconciliation handles that. Need an off-schedule release (hotfix)? Use
> **Actions → Deploy to Production → Run workflow** on `main`; it runs the same
> promote-then-deploy.
>
> **Branch protection:** the promote step pushes to `main` with `GITHUB_TOKEN`.
> If `main` forbids direct pushes, add a `RELEASE_TOKEN` secret (a PAT allowed
> to bypass) — it's preferred over `GITHUB_TOKEN` when set. Without one, a
> protected `main` will reject the auto-push and the release fails.
>
> Cron is UTC with no DST awareness: `0 15 * * 6` = Sun 03:00 NZST (winter) /
> 04:00 NZDT (summer). Switch to `0 14 * * 6` for 03:00 in summer.

### 2.0 Enabling the deploys (one-time)

Each pipeline no-ops until its host secret is set (Settings → Secrets and
variables → Actions), so adopting this never breaks CI.

**Test site** (`deploy-test.yml`):

| Secret | Purpose | Default if unset |
|--------|---------|------------------|
| `TEST_DEPLOY_HOST` | test server IP/hostname | — (required; absent ⇒ skipped) |
| `TEST_DEPLOY_SSH_KEY` | private key for the test deploy user | — (required) |
| `TEST_DEPLOY_USER` | SSH user | `cwa` |
| `TEST_DEPLOY_PATH` | repo path on the test server | `/home/cwa/CWA_CLASS_APP` |
| `TEST_SMOKE_URL` | URL the post-deploy smoke hits | `https://test.wizardslearninghub.co.nz` |

**Production** (`deploy-prod.yml`):

| Secret | Purpose | Default if unset |
|--------|---------|------------------|
| `DEPLOY_HOST` | prod Droplet IP/hostname | — (required; absent ⇒ skipped) |
| `DEPLOY_SSH_KEY` | private key for the prod deploy user | — (required) |
| `DEPLOY_USER` | SSH user | `cwa` |
| `DEPLOY_PATH` | repo path on the Droplet | `/home/cwa/CWA_CLASS_APP` |
| `SMOKE_URL` | URL the post-deploy smoke hits | `https://www.wizardslearninghub.co.nz` |
| `RELEASE_TOKEN` | token to push `main` if it's branch-protected | — (falls back to `GITHUB_TOKEN`) |

**Shared:**

| Secret | Purpose | Default if unset |
|--------|---------|------------------|
| `DEPLOY_ALERT_WEBHOOK` | Slack/Discord incoming-webhook URL for failure alerts | — (unset ⇒ no chat alert; GitHub still emails the run owner) |

The deploy user already has the needed `systemctl` sudo rights from
`setup-app-prod.sh` on each server.

**Failure alerts.** If a deploy or the post-deploy smoke fails, the
`notify-failure` job posts `🚨 CWA TEST/PROD deploy FAILED on <branch> (<sha>) —
<run-url>` to `DEPLOY_ALERT_WEBHOOK`. The payload carries both `text` (Slack)
and `content` (Discord), so the same webhook URL works for either. Independently,
turn on **Settings → Notifications → Actions → "Failed workflows only"** for the
built-in email/mobile push.

### 2.0a Generating the deploy SSH key (`*_DEPLOY_SSH_KEY`)

Each server's deploy job logs in as the `cwa` user with a private key held in
the corresponding secret. Make a dedicated key per environment (don't reuse a
personal key):

```bash
# one keypair per environment, e.g. test:
ssh-keygen -t ed25519 -C "gha-cwa-deploy-test" -f ~/.ssh/cwa_deploy_test -N ""
```

This writes `~/.ssh/cwa_deploy_test` (private — paste into `TEST_DEPLOY_SSH_KEY`)
and `~/.ssh/cwa_deploy_test.pub` (public — install on the server). Authorise the
public key for `cwa`:

```bash
ssh-copy-id -i ~/.ssh/cwa_deploy_test.pub cwa@<test-host>
# …or manually as root on the server:
#   mkdir -p /home/cwa/.ssh && cat >> /home/cwa/.ssh/authorized_keys   # paste the .pub, Ctrl-D
#   chown -R cwa:cwa /home/cwa/.ssh && chmod 700 /home/cwa/.ssh && chmod 600 /home/cwa/.ssh/authorized_keys
```

Verify: `ssh -i ~/.ssh/cwa_deploy_test cwa@<test-host> "echo ok"` prints `ok`
without a password. Repeat with a separate key for prod (`DEPLOY_SSH_KEY`). The
private key lives only in GitHub Secrets (encrypted, never printed in logs); if
one ever leaks, remove that line from `authorized_keys` and rotate the secret.

### 2.0b Manual deploy (fallback / before secrets are set)

The script path still works by hand exactly as before — bump the version
(§ 2.1) and run the script on the server (§ 2.2). The automated workflows run
those same steps for you.

### 2.1 Bump the version (optional but recommended)

`APP_VERSION` in `settings.py` is what `/api/health/` reports — bump it so you
can confirm the new build is live:

```bash
python scripts/bump_version.py patch   # or minor / major
git commit -am "Release vX.Y.Z" && git push origin main
```

### 2.2 Deploy on the Droplet

```bash
ssh cwa@<droplet-ip>
cd /home/cwa/CWA_CLASS_APP
bash scripts/deploy.sh
```

`scripts/deploy.sh` does, in order (and **aborts on any error** — `set -euo
pipefail`):

1. `git fetch` + `git reset --hard origin/main` (deploy branch is
   `DEPLOY_BRANCH`, default `main`).
2. `pip install -r requirements.txt`.
3. `manage.py migrate --noinput`.
4. `manage.py collectstatic --noinput --clear`.
5. `manage.py check --deploy` (warnings are non-fatal here).
6. `systemctl restart cwa-gunicorn` and verify it's active — on failure it
   prints the last 20 journal lines and exits non-zero.
7. **Deep health gate** — curls `https://<host>/api/health/?deep=1` (host
   derived from `ALLOWED_HOSTS` in `/etc/cwa/cwa.env`). A non-200 (e.g. 503
   `degraded` from a failed DB/migration/cache probe) aborts the deploy with
   the failing check and the last journal lines.

### 2.3 Verify the deploy

```bash
curl -s https://www.wizardslearninghub.co.nz/api/health/   # version == the tag you shipped
sudo journalctl -u cwa-gunicorn --no-pager -n 30       # no traceback on boot
```

If `version` still shows the old number, the restart didn't pick up the new
code — check `journalctl -u cwa-gunicorn` for an import/migration error that
kept the old workers alive.

---

## 3. Rollback

There is no blue/green here — rollback is "deploy an older commit".

```bash
cd /home/cwa/CWA_CLASS_APP
git fetch origin
git reset --hard <last-good-commit-sha>
bash scripts/deploy.sh    # re-runs migrate/collectstatic/restart against the old code
```

> **Migrations are the rollback hazard.** `deploy.sh` always runs `migrate`
> forward; it does **not** reverse migrations. If the bad release added a
> migration, rolling the code back will not undo the schema change. Only
> reverse a migration deliberately:
> `manage.py migrate <app> <previous_migration_name>` — and only if it is
> safely reversible. When in doubt, fix forward with a new release rather than
> reversing schema under live traffic.

---

## 4. Day-2 operations

### 4.1 Where everything lives

| What | Path |
|------|------|
| App / repo | `/home/cwa/CWA_CLASS_APP` |
| venv | `/home/cwa/CWA_CLASS_APP/venv` |
| Secrets | `/etc/cwa/cwa.env` (mode 600, owned by `cwa`) |
| DB CA cert | `/etc/cwa/do-ca.pem` |
| gunicorn unit | `/etc/systemd/system/cwa-gunicorn.service` |
| gunicorn logs | `/var/log/cwa/gunicorn-{access,error}.log` + `journalctl -u cwa-gunicorn` |
| Caddyfile | `/etc/caddy/Caddyfile` |
| Caddy logs | `/var/log/caddy/access.log` + `journalctl -u caddy` |
| Error cron check | `scripts/cron_check_errors.sh` |

### 4.2 Restart / reload

```bash
sudo systemctl restart cwa-gunicorn   # full restart (picks up code/env changes)
sudo systemctl reload  cwa-gunicorn   # graceful HUP (re-reads workers)
sudo systemctl reload  caddy          # after a Caddyfile edit
```

### 4.3 Reset a user's password (production)

In production passwords are in MySQL via Django auth. Reset one user with the
shell — **never** with a dev/sanitise script:

```bash
sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python \
    /home/cwa/CWA_CLASS_APP/cwa_classroom/manage.py shell -c \
    "from django.contrib.auth import get_user_model as G; u=G().objects.get(email='admin@wizardslearninghub.co.nz'); u.set_password('<new-strong-pw>'); u.save(update_fields=['password']); print('done')"
```

Or `manage.py changepassword <username>` for an interactive prompt.

### 4.4 Tail logs / find errors

```bash
sudo journalctl -u cwa-gunicorn -f                       # live app log
sudo tail -f /var/log/cwa/gunicorn-error.log
bash scripts/cron_check_errors.sh                        # scans logs for error spikes
```

### 4.5 Run a management command in prod

```bash
sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python \
    /home/cwa/CWA_CLASS_APP/cwa_classroom/manage.py <command>
# e.g. auto_complete_sessions (cron), send_trial_expiry_warnings, sync_stripe_prices
```

See `cwa_classroom/MANAGEMENT_COMMANDS.md` for the full catalogue. Several are
cron-driven (e.g. `auto_complete_sessions` every ~15 min).

---

## 5. Troubleshooting

### 5.1 502 / "no upstream" from Caddy

gunicorn isn't serving the socket. Check it's up and the socket exists:

```bash
sudo systemctl status cwa-gunicorn --no-pager
ls -l /run/cwa/gunicorn.sock
sudo journalctl -u cwa-gunicorn --no-pager -n 50
```

Most common: a boot-time crash (bad `cwa.env`, failed migration, import error).
Fix the env/migration, then `systemctl restart cwa-gunicorn`.

### 5.2 TLS cert not issued

Caddy needs ports 80+443 reachable and DNS resolving to the Droplet. Check:

```bash
sudo journalctl -u caddy --no-pager -n 50    # look for ACME errors
dig +short wizardslearninghub.co.nz          # must be the Droplet's IP
```

### 5.3 Static files 404 / unstyled site

`collectstatic` didn't run or WhiteNoise isn't picking up the manifest. Re-run
`collectstatic --noinput --clear` and restart gunicorn. Confirm
`https://.../static/css/output.css` returns 200.

### 5.4 DB connection / SSL errors

Verify `DB_SSL_CA` points at the DO CA cert and the Droplet is on the DB's
trusted sources / VPC. Test:

```bash
sudo -u cwa /home/cwa/CWA_CLASS_APP/venv/bin/python \
    /home/cwa/CWA_CLASS_APP/cwa_classroom/manage.py dbshell -c "SELECT 1;"
```

### 5.5 `.env` ownership / permissions

`/etc/cwa/cwa.env` must be mode `600` owned by `cwa`. If gunicorn can't read it
the workers crash on boot:

```bash
sudo chown cwa:cwa /etc/cwa/cwa.env && sudo chmod 600 /etc/cwa/cwa.env
```

---

## 6. Legacy: PythonAnywhere

The app previously ran on PythonAnywhere (`*.pythonanywhere.com`). Migration to
the DigitalOcean Droplet is tracked in `docs/MIGRATION_PLAN.md`; the
prod→test DB-copy scripts (`scripts/restore_prod_to_test.sh`,
`scripts/migrate_db_pa_to_do.sh`) still reference the PythonAnywhere MySQL host.
Treat PythonAnywhere as the **legacy** path — new deploys go to the Droplet via
this runbook. See `test-env-db-refresh.md` for the DB-side of the migration.

---

## See also

- [`test-env-db-refresh.md`](test-env-db-refresh.md) — refresh + sanitise the test DB from prod
- [`ui-smoketest.md`](ui-smoketest.md) — post-deploy CRUD validation
- [`deploy/setup-app-prod.sh`](../deploy/setup-app-prod.sh) — one-time host setup
- [`scripts/deploy.sh`](../scripts/deploy.sh) — the release script
