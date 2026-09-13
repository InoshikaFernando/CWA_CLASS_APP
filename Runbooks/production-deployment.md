# CWA Classroom — Production Deployment Runbook

How CWA Classroom is brought up on a fresh DigitalOcean Droplet, how releases
are shipped after first install, and the day-2 operations (rollback, admin
password reset, log access). The supporting scripts live in
[`deploy/`](../deploy/) and [`scripts/`](../scripts/).

## TL;DR

- **Test site:** every merge to `test` auto-deploys (`deploy-test.yml`).
- **Production:** every push to `main` auto-deploys (`deploy-prod.yml`) — in
  practice, merging the weekly release PR. Also runnable on demand via
  `workflow_dispatch`. See § 2 for the full model.
  (There is no cron for this: the release *cadence* is weekly by convention,
  but the *trigger* is the push to `main`, not a schedule.)

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

### 2.1 Bump the version — on the FEATURE BRANCH, before the merge

`APP_VERSION` lives in `cwa_classroom/cwa_classroom/version.py` and is what
`/api/health/` reports — bump it so you can confirm the new build is live.
Use `scripts/bump_version.py`; do not edit the file by hand and do not move
the constant back into `settings.py`. Every file in that package is watched
by ci.yml's `shared` filter — the one that runs every suite in the repo — so
a version line there made every PR a full-matrix run.

**Bump before the PR merges, never on `test` afterwards.** A push to `test`
runs the full CI matrix (~29 jobs, ~119 billed Actions minutes; path filters
are ignored there on purpose). Bumping on `test` after a merge buys a second
full matrix per release, and that second push cancels the first mid-flight, so
~25 already-running jobs are paid for and thrown away. Three of those in one
evening exhausted the Actions spending limit on 2026-08-24 and stopped every
workflow in the repo — the production deploy included.

```bash
git checkout <your-feature-branch>
python scripts/bump_version.py patch   # or minor / major
git commit -am "Release vX.Y.Z" && git push
```

Then merge the PR into `test`. That single push carries the version, costs one
matrix, and is the run the release gate ("Release tree already tested on test")
looks for when you open the `test` → `main` PR.

**What the `test` → `main` PR runs.** CI looks for a passing push run on `test`
for that exact commit. If it finds one the tree is already proven, so the
suites are skipped and "Release tree already tested on test" names the run that
covered it. If it does **not** — a release PR carrying a commit of its own, or
one opened before CI on `test` finished — the full matrix runs on the release
PR instead: every unit suite, the classroom suite and all 15 UI groups, path
filters ignored. So a release is never promoted on a tree nothing has tested,
and the ordinary release still costs nothing.

`bump_version.py` refuses to run on `test` or `main` for this reason. A hotfix
going straight out can override with `--allow-protected`, accepting the second
matrix.

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
| Question-health cron | `scripts/cron_record_question_health.sh` — **must be installed**, or `/admin-dashboard/question-health/` stays empty forever |

#### Cron drop-ins are installed by hand, NOT by a deploy

Every scheduled job runs from an `/etc/cron.d/cwa-*` drop-in written by
`scripts/install_crons.sh`. Nothing in the deploy path touches cron, so a
drop-in added to the repo does not exist on a droplet until someone runs that
script there.

```bash
# On the droplet, as root:
/home/cwa/CWA_CLASS_APP/scripts/install_crons.sh --check   # report drift, write nothing
sudo /home/cwa/CWA_CLASS_APP/scripts/install_crons.sh      # install / update them
sudo /home/cwa/CWA_CLASS_APP_TEST/scripts/install_crons.sh test   # the test checkout
```

`--check` prints one line per drop-in (`ok` / `MISSING` / `STALE`) and exits
non-zero if any are wrong, so it is safe to run any time and answers "is this
droplet correctly wired?" without changing anything. Installing is idempotent
and touches nothing but `/etc/cron.d` — safe on a live site, and `cron` re-reads
that directory by itself, so no reload.

The `test` profile suffixes both drop-in and log names (`cwa-publish-homework-test`,
`publish_scheduled_homework-test.log`) so the two checkouts on a shared droplet
cannot overwrite each other's jobs or logs. It omits `cwa-unpaid-access`, which
is prod-only: live PageHits accrue only there.

Expected drop-ins (prod): `cwa-ops`, `cwa-uploads`, `cwa-email`,
`cwa-email-health`, `cwa-unpaid-access`, `cwa-progress-reports`,
`cwa-publish-homework`, `cwa-scheduled-questions`.

**Why this is a script of its own.** The drop-ins used to be inlined in
`deploy/setup-app-prod.sh`, which is one-time provisioning: it also runs
`apt-get upgrade -y`, overwrites `/etc/caddy/Caddyfile` and the gunicorn unit,
rebuilds the venv and re-pulls the repo. Installing a crontab line therefore
meant doing all of that to a live site, so nobody did — and
`cwa-publish-homework`, added on 2026-08-31, was still missing from production
on 2026-09-13. For two weeks the question automation built a homework set for
every planned week and not one was ever sent, with nothing erroring; a teacher
found it by noticing she published every set by hand. The attempt to fix it by
re-running the provisioning script upgraded 35 packages on production and
restarted Caddy under live traffic before being aborted.
`tests_workflows.py` now fails the build if the drop-ins drift back into the
provisioning script, or if `install_crons.sh` grows anything beyond writing
cron files.

#### Daily health checks

These watchdogs exist because their failure mode is silence, not an error. All
are installed by `deploy/setup-app-prod.sh` and all are readable on the Ops
dashboard (`/admin-dashboard/ops/`) and in `/api/health/?deep=1` under
`warnings.*` — so a leak is visible without reading a chat channel. The first
two also post to Discord; the publish check has no alert cron of its own on
purpose, since a cron is the thing it is watching for.

| Check | Cron drop-in | Log | Catches |
|-------|--------------|-----|---------|
| `check_email_queue_health` | `/etc/cron.d/cwa-email-health` (hourly) | `/var/log/cwa/email_queue_health.log` | the `process_email_queue` drain stopping — invoices read as issued but are never sent |
| `check_unpaid_access` | `/etc/cron.d/cwa-unpaid-access` (daily 09:00) | `/var/log/cwa/unpaid_access.log` | a delinquent subscription still reaching restricted pages — the paywall letting unpaid accounts through |
| `publish_scheduled_homework` | `/etc/cron.d/cwa-publish-homework` (every 5 min) | `/var/log/cwa/publish_scheduled_homework.log` | the publish cron stopping — scheduled homework (including every set the question automation builds) created, previewed, and never sent to the class |

Run either by hand with `sudo -u cwa .../manage.py <command>` (§ 4.5); each
exits non-zero when it finds something, which is the alert condition.

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

### 4.6 Discord / Jira feedback integration

Bug-category feedback (and the daily error-log cron) auto-files a Jira **CPP
Bug** and pings the `#cwa-feedback` Discord channel. Everything is
**config-gated**: with the env unset the app logs a warning and no-ops, so a
missing integration never breaks feedback submission. To enable it on a host,
set these env vars (mode-600 `.env` files, no quotes, no `export`):

| Var | Goes in | Purpose |
|-----|---------|---------|
| `FEEDBACK_DISCORD_WEBHOOK` | `cwa.env`, `cwa-test.env`, `cron_jira.env` | Discord webhook for `#cwa-feedback`. Empty = no ping. |
| `JIRA_BASE_URL` | `cwa.env`, `cwa-test.env` | e.g. `https://codewizardsaotearoa.atlassian.net`. Already in `cron_jira.env`. |
| `JIRA_USER_EMAIL` | `cwa.env`, `cwa-test.env` | Atlassian account email for the API token. |
| `JIRA_API_TOKEN` | `cwa.env`, `cwa-test.env` | Atlassian API token. **Without all three Jira vars the Discord ping still fires but says `(Jira not configured)` and no issue is created.** |

The webhook is needed in all three files because the **cron** (`cron_jira.env`)
and the **app** (`cwa.env` / `cwa-test.env`) each read their own env. The Jira
creds already live in `cron_jira.env`; copy them into the two app env files so
the app can file issues too — e.g.:

```bash
# copy the three Jira vars from the cron env into the two app env files
SRC=/etc/cwa/cron_jira.env
for VAR in JIRA_BASE_URL JIRA_USER_EMAIL JIRA_API_TOKEN; do
  LINE=$(grep "^$VAR=" "$SRC") || { echo "MISSING $VAR in $SRC"; continue; }
  for f in /etc/cwa/cwa.env /etc/cwa/cwa-test.env; do
    grep -q "^$VAR=" "$f" && sudo sed -i "s#^$VAR=.*#$LINE#" "$f" \
                          || echo "$LINE" | sudo tee -a "$f" >/dev/null
  done
done
sudo systemctl restart cwa-gunicorn cwa-gunicorn-test   # env is read at process start
```

The cron reads its env fresh each run, so it needs no restart — only gunicorn
caches env at start. Verify (without printing the secret):

```bash
for f in /etc/cwa/cwa.env /etc/cwa/cwa-test.env /etc/cwa/cron_jira.env; do
  grep -q '^FEEDBACK_DISCORD_WEBHOOK=' "$f" && echo "OK  $f" || echo "MISS $f"
done
```

To test end-to-end: submit a feedback item with category **Bug** on the site →
expect a Jira CPP Bug + a `#cwa-feedback` message. Code lives in
`cwa_classroom/feedback/services.py`; see also `cwa_classroom/feedback/README.md`.

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

The app previously ran on PythonAnywhere (`*.pythonanywhere.com`). The move to
the DigitalOcean Droplet is tracked in `docs/MIGRATION_PLAN.md` and is done:
`scripts/migrate_db_pa_to_do.sh` is the one-off that carried the data across and
is the only script still naming the PythonAnywhere host. The prod→test and
prod→dev copies (`scripts/restore_prod_to_test.sh`,
`scripts/restore_prod_to_dev.sh`) read their credentials from `/etc/cwa/*.env`
on the droplet, like the deploy does. Any instruction you find telling you to
run either against PythonAnywhere is stale. See `test-env-db-refresh.md`.

---

## See also

- [`test-env-db-refresh.md`](test-env-db-refresh.md) — refresh + sanitise the test DB from prod
- [`ui-smoketest.md`](ui-smoketest.md) — post-deploy CRUD validation
- [`deploy/setup-app-prod.sh`](../deploy/setup-app-prod.sh) — one-time host setup
- [`scripts/deploy.sh`](../scripts/deploy.sh) — the release script
