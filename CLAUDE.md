# CLAUDE.md

Project memory for agents working in this repo (CWA Classroom — Wizards Learning Hub).
Operational procedures live in [`Runbooks/`](Runbooks/README.md).

## Jira workflow conventions

**Always set a Jira task's dates as you move it through the workflow:**

- **When you START a task** (move it to *In Progress*): set its **Start date** (the
  "create"/start date) to that day.
- **When you CLOSE a task** (move it to *Done*): set its **Due date** (the end date)
  to that day.

Do this on every task, every time. Cycle-time reporting and the sprint/project
**burndown** (`/sprints/burndown/`, fed by `manage.py sync_sprint_burndown`) depend
on these dates being present and truthful — Jira's API only reports an issue's
*current* state, so the dates must be recorded as the work happens.

Full convention + the one-time historical backfill procedure:
[`Runbooks/jira-task-dates.md`](Runbooks/jira-task-dates.md).

**Always estimate Jira issues with the standard story-point scheme** so the
burndown can trend down: **Story = 3, Task = 2, Bug = 3 if High/Highest priority
else 2, Subtask = skip** (subtasks stay empty so they don't double-count their
parent Story; Epics never carry points).
These are default baselines — re-estimate to a truer value when you know it, and
keep the points on an issue when you close it. Convention + the idempotent
bulk-fill script: [`Runbooks/jira-story-points.md`](Runbooks/jira-story-points.md).

## Conventions & layout

- `manage.py` lives at `cwa_classroom/manage.py`; run Django commands from there.
- Per-app test suites (`cwa_classroom/<app>/tests/`); CI runs one job per app
  (`.github/workflows/ci.yml`). Tests use SQLite via `DB_ENGINE=sqlite`.
- Every CI job points at an app directory (`pytest billing/`), never a
  hand-written file list — `pytest.ini` widens `python_files` so `tests.py` and
  `tests_*.py` are collected. `tests_workflows.py` fails the build if any test
  file ends up in no job, i.e. never runs anywhere.
- Playwright UI tests are split by app area into `cwa_classroom/ui_tests/<group>/`
  and CI runs only the groups a change touches — where a group's filter watches
  every app its tests drive, not just its namesake. A new UI test goes **inside** a
  group package — one left at the `ui_tests/` root belongs to no CI job and would
  never run (`tests_workflows.py` fails the build if that happens). See
  [`cwa_classroom/ui_tests/README.md`](cwa_classroom/ui_tests/README.md).
- Branch discipline: develop on a feature branch; `test` deploys to the test
  site, `main` deploys to production. Open a PR; never push to `main` directly.
- **Bump `APP_VERSION` on the feature branch, before the PR merges — never on
  `test` afterwards.** A push to `test` runs the full CI matrix (~119 billed
  Actions minutes), so a later bump buys a second one AND cancels the first
  mid-flight. `scripts/bump_version.py` refuses to run on `test`/`main`
  (`--allow-protected` for a hotfix). This exhausted the Actions spending limit
  once, which stopped the production deploy:
  [`Runbooks/production-deployment.md`](Runbooks/production-deployment.md) § 2.1.
- No silent failure — surface errors (blank data, swallowed 4xx, no-op commands)
  rather than hiding them.

## Hosting & deployment

**Both sites run on DigitalOcean Droplets — NOT PythonAnywhere.** The app was
migrated off PythonAnywhere (see `scripts/migrate_db_pa_to_do.sh`); any
PythonAnywhere instruction you find in a skill, runbook, or older ticket is
stale. The stack is Caddy (TLS) → gunicorn → Django, with DigitalOcean Managed
MySQL, Redis, and Spaces for media. Full details:
[`Runbooks/production-deployment.md`](Runbooks/production-deployment.md).

**Deploys are automatic — do not hand anyone a manual server checklist.**

| Push to | Workflow | Result |
|---------|----------|--------|
| `test`  | `.github/workflows/deploy-test.yml` | deploys the test site |
| `main`  | `.github/workflows/deploy-prod.yml` | deploys production |

Merging the release PR **is** the deploy: the workflow SSHes to the droplet and
runs `scripts/deploy.sh` (reset to origin → deps → `migrate` → `collectstatic`
→ `check --deploy` → restart gunicorn → deep health gate → restart RQ worker),
then a public smoke test. Both workflows also accept `workflow_dispatch` for a
manual re-deploy. If `DEPLOY_HOST` is unset the deploy no-ops rather than
half-deploying.

So after merging to `main`, the job is to **verify the deploy run went green**,
not to tell anyone to pull and migrate by hand:

```bash
curl -s https://www.wizardslearninghub.co.nz/api/health/          # version + liveness
curl -s "https://www.wizardslearninghub.co.nz/api/health/?deep=1" # DB + migrations + cache
```

`version` in the response should equal the `APP_VERSION` just shipped. Note the
sandbox's egress proxy blocks this host, so check the workflow run instead when
curl returns a 403 CONNECT.

Tagging releases needs a human: this environment's GitHub credentials can push
branches but get **403 on tag refs**.
