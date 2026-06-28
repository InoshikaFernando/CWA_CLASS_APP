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
- Branch discipline: develop on a feature branch; `test` deploys to the test
  site, `main` deploys to production. Open a PR; never push to `main` directly.
- No silent failure — surface errors (blank data, swallowed 4xx, no-op commands)
  rather than hiding them.
