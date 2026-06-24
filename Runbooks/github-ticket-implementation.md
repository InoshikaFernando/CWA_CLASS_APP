# CWA Classroom — Ticket Implementation Runbook

**Applies to:** Any CWA Classroom work item that originates as a GitHub issue
(or a ticket the user pastes).
**Audience:** Agent (Claude Code) — end-to-end execution of a single ticket.

---

## Overview

This runbook is the full lifecycle of taking one ticket from "assigned" to
"done": understand it, implement it, verify it locally, raise the PR, get CI
green, merge when allowed, watch it onto the environment, verify there, and
close the ticket. The agent owns every step — nothing here is hand-off-able. If
a step fails, the agent fixes it (via a follow-up commit or PR) before closing.

Repo: `InoshikaFernando/CWA_CLASS_APP`. Default/deploy branch: `main`. CI runs
on pushes/PRs to `main` and `test` (`.github/workflows/ci.yml`).

---

## Prerequisites

- Local repo on the working branch, clean tree, deps installed
  (`pip install -r cwa_classroom/requirements-test.txt`).
- GitHub access via the **GitHub MCP tools** (`mcp__github__*`) — this
  environment has **no `gh` CLI**. Use `mcp__github__pull_request_read`,
  `create_pull_request`, `get_job_logs`, etc.
- Browser MCP (`mcp__claude-in-chrome__*`) for UI verification, loaded via
  `ToolSearch` if needed.
- Familiarity with the repo's no-silent-failure rule and the per-app test
  layout.

> **Branch discipline.** Develop on the branch you were assigned. Never push to
> `main` directly. Open a PR; `main` is updated only by merging a green PR.

---

## Step 1: Read the ticket

1. Resolve the ticket — a GitHub issue number/URL, or text the user pasted.
   For an issue, read it with `mcp__github__issue_read` (title, body, comments,
   labels, linked PRs).
2. Read it in full. Identify the **observable behaviour** the ticket asks for —
   not just the mechanism.
3. **Check it isn't already claimed/done.** If an open PR already references the
   issue, or the issue is closed, stop and report that back in one line rather
   than duplicating work.
4. Classify:
   - **Well-specified** — clear acceptance criterion and scope. Go to Step 3.
   - **Sparse** — title-only or vague. Do Step 2 first.

---

## Step 2: Sharpen a sparse ticket

If the ticket is bare, give it substance before coding:

1. **Locate what exists.** `Grep`/`Glob` the relevant app(s) under
   `cwa_classroom/` (accounts, classroom, quiz, billing, progress, maths,
   coding, brainbuzz, …). Find the views, models, templates, and existing tests
   the change touches.
2. **Identify the gap** concretely — endpoint missing, validation absent, UI
   control unwired, template renders the wrong field, etc. (cite
   `app/file.py:line`).
3. **Write it down.** Add an issue comment (`mcp__github__add_issue_comment`)
   capturing: what the feature is, current state with file paths, the gap, and
   **acceptance criteria** a reviewer can check. Surface it to the user before
   implementing if scope is non-trivial — they may redirect.

---

## Step 3: Plan (when non-trivial)

For anything beyond a one-liner:

- Decide which app(s) own the change and where the test goes (the per-app
  `tests/` dir, or `ui_tests/` for a Playwright flow).
- Check `docs/` for a relevant SPEC (e.g. `SPEC_INVOICING.md`,
  `SPEC_SUBSCRIPTION.md`, `SPEC_TEACHER_CLASS_STUDENT_PROGRESS.md`) — you may be
  about to contradict an intentional design. If the change touches a SPEC,
  flag it for human review early.
- For schema changes, plan the migration (`makemigrations`) and confirm it's
  reversible / additive where possible.

---

## Step 4: Implement

1. Make sure you're on your assigned branch (create it from `main` if needed).
2. **Set the Jira task's Start date to today** as you move it into *In Progress*
   (see [`jira-task-dates.md`](jira-task-dates.md)).
3. **Write the test first** when the change has observable behaviour. Put it in
   the owning app's suite (e.g. `cwa_classroom/billing/tests.py`,
   `cwa_classroom/classroom/tests/...`) or `ui_tests/` for a browser flow.
4. Implement the change. Follow the no-silent-failure rule — no bare `except:`,
   no `?? "—"` placeholder rendered past a missing FK, no swallowed 4xx.
5. If you changed models, generate the migration:
   ```bash
   cd cwa_classroom && python manage.py makemigrations
   ```
   Commit the migration file alongside the model change.

---

## Step 5: Verify locally — mandatory before the PR

Tests passing is necessary but not sufficient; tests prove the code does what
its tests say, local verification proves it does what the **ticket** says.

### 5a. Run the affected app's test suite

Run the suite(s) for whatever you touched and confirm green. These are the
exact commands CI runs (`.github/workflows/ci.yml`), from `cwa_classroom/`:

| You touched | Run (from `cwa_classroom/`) |
|---|---|
| Migrations / any model | `pytest tests_migrations.py -v` (migration health) |
| `classroom` | `pytest classroom/tests/ -n auto --dist=loadscope` |
| `maths` | `pytest maths/tests/ -n auto --dist=loadscope` |
| `number_puzzles` | `pytest number_puzzles/tests/ -n auto --dist=loadscope` |
| `coding` | `pytest coding/tests/ -n auto --dist=loadscope` |
| `accounts` | `pytest accounts/tests.py -n auto --dist=loadscope` |
| `audit` | `pytest audit/tests.py -n auto --dist=loadscope` |
| `billing` | `pytest billing/tests.py billing/tests_admin.py billing/tests_gaps.py billing/tests_parent_invoice_payment.py billing/tests_stripe.py billing/tests_views_coverage.py billing/tests_webhook_handlers.py -n auto --dist=loadscope` |
| `homework` | `pytest homework/tests.py -n auto --dist=loadscope` |
| `brainbuzz` | `pytest brainbuzz/tests/ --ignore=brainbuzz/tests/test_student_playwright_mobile.py -n auto --dist=loadscope` |
| `worksheets` | `pytest worksheets/tests/ -n auto --dist=loadscope` |
| Any UI/template/JS | `pytest ui_tests/ brainbuzz/tests/test_student_playwright_mobile.py -n auto` (needs `playwright install --with-deps chromium`) |

Tests default to SQLite (`conftest.py`). If your change is MySQL-specific, run
the relevant suite with `DB_ENGINE=mysql` and the `DB_*` vars set.

> **Always run `pytest tests_migrations.py`** if you touched any model — it's
> the CI "Migration Health" gate and catches missing/conflicting migrations
> before they reach `main`.

### 5b. Drive the change end-to-end

For a user-facing change, **run the app and click the actual control**:

```bash
cd cwa_classroom
python manage.py migrate && python manage.py setup_dev && python manage.py reset_users_for_dev
python manage.py runserver 0.0.0.0:8000
```

Then drive it via `mcp__claude-in-chrome__*` against `http://localhost:8000`
(see [`ui-smoketest.md`](ui-smoketest.md) for login + the relevant phase).
For a backend-only change, trigger the behaviour and confirm the `runserver`
log shows the new path with no traceback. Record what you did — the exact URL,
the log line, a screenshot for multi-step flows — for the PR body.

---

## Step 6: Raise the PR

Commit with a clear inline message, push the branch, and open the PR with
`mcp__github__create_pull_request` against `main`.

PR body, in order:

1. **Summary** — what changed and why; the issue it closes (`Closes #N`).
2. **Verification performed** — the app suite(s) you ran (quote the green
   summary line), and the end-to-end check from 5b (URL driven, log line, or
   screenshot). If a verification couldn't be done locally, name the specific
   blocker — that's a request for review, not a free pass.
3. **Test plan** — checklist for the reviewer's spot checks.
4. **Migration note** — if a migration is included, say so and whether it's
   reversible.

> Once the PR exists, offer to **watch it** — the harness can subscribe to PR
> activity (`subscribe_pr_activity`) and auto-handle CI failures / review
> comments rather than polling.

---

## Step 7: Get CI green

1. After pushing, give CI ~30–45s to register, then read status with
   `mcp__github__pull_request_read` (status/checks) — the workflow is a matrix
   of per-app jobs plus Migration Health and UI Tests.
2. For a failing job, pull its log with `mcp__github__get_job_logs`
   (`failed_only` for the PR's run) and diagnose the **root cause** — do not
   re-run blindly hoping it passes.
3. Fix on the branch, push, re-check. **Do not** bypass with `--no-verify` or
   by skipping the failing test.
4. `concurrency: cancel-in-progress: true` is set on the workflow — a newer
   push **cancels** the older run. A `cancelled` conclusion caused by your own
   newer push is not a failure; watch the latest run for the branch instead.

Loop until every required check is green.

---

## Step 8: Merge (when allowed)

Merge only if **all** hold:

- Every required check is green.
- The PR body has the **Verification performed** section.
- No unresolved review comments require human resolution.
- The change does **not** touch `docs/SPEC_*.md` (specs) without human
  approval — if it does, **stop and hand off**.

Merge with `mcp__github__merge_pull_request` using the repo's standard strategy
(check `.github/` for a policy; default to the team's convention). Do **not**
merge your own PR with red or pending checks.

---

## Step 9: Ship & verify on the test site

PRs merge to `test`, and **every push to `test` auto-deploys to the test site**
via [`deploy-test.yml`](../.github/workflows/deploy-test.yml). Production is a
separate, scheduled release (Sunday ~03:00 NZ via
[`deploy-prod.yml`](../.github/workflows/deploy-prod.yml)) — see
[`production-deployment.md`](production-deployment.md) § 2.

After your PR merges to `test`:

1. Watch the **Deploy to Test** run (`mcp__github__actions_list` /
   `get_job_logs`). It runs `scripts/deploy.sh` on the test server then a public
   smoke gate. If deploy secrets aren't configured yet it no-ops. Either way, do
   **not** SSH-hotfix the server outside the sanctioned `scripts/deploy.sh` path.
2. Once deployed, verify the version bumped and the app is healthy on **test**:
   ```bash
   curl -s "https://test.wizardslearninghub.co.nz/api/health/?deep=1"   # version + DB/migrations/cache
   ```
3. Prove the ticket's acceptance criteria on the deployed **test** stack — drive
   Chrome MCP against the test URL for UI changes, or exercise the endpoint for
   backend changes. If it fails, it's your job to fix it via a follow-up PR —
   never patch the server directly.
4. The change rides the next weekly `test` → `main` release to production; the
   prod deploy runs the same health + smoke gates.

---

## Step 10: Close the ticket

Only after Step 9 passes:

1. **Set the Jira task's End date to today** as you move it to *Done* (see
   [`jira-task-dates.md`](jira-task-dates.md)).
2. Close the issue (it auto-closes if the PR said `Closes #N` and merged).
3. Add a brief closing comment (`mcp__github__add_issue_comment`): the merged
   PR link, the deploy/verification note (what you tested, what passed).

---

## What to do when things go wrong

| Situation | Action |
|---|---|
| CI job fails | Pull the job log, fix root cause on the branch, push, re-check. No `--no-verify`. |
| Migration Health fails | You added/changed a model without a migration, or there's a conflict — `makemigrations`, resolve conflicts, commit. |
| Spec-touching PR (`docs/SPEC_*`) | Stop, hand off to a human reviewer — do not merge. |
| Deploy/verify fails | Follow-up PR with the fix; never SSH-hotfix the Droplet outside `scripts/deploy.sh`. |
| Scope grows mid-implementation | Pause, update the issue with the new scope, surface to the user before continuing. |
| Pre-existing flaky UI test blocks you | Don't bundle a flake fix into an unrelated PR — note it on the issue as a deferred follow-up (quote the test name + conditions), ship the contained change. |

---

## Anti-patterns (do not do these)

- Pushing to `main` directly, or merging your own PR with red/pending checks.
- Merging a `docs/SPEC_*` change without human approval.
- Faking verification — asserting a UI flow works without driving it, or
  rendering `—`/`null` past a missing FK to make a page "look green".
- Editing the database by hand (raw SQL) to make a test or a flow pass.
- Skipping `pytest tests_migrations.py` after a model change.
- SSH-ing to the production Droplet to swap code/containers outside
  `scripts/deploy.sh`.

---

## See also

- [`ui-smoketest.md`](ui-smoketest.md) — the local verification flow for Step 5b
- [`production-deployment.md`](production-deployment.md) — what happens after merge
- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — the exact CI jobs
- `cwa_classroom/MANAGEMENT_COMMANDS.md` — seed/admin commands
