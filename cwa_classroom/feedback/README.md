# feedback

Platform-wide user feedback capture and triage (CPP-321 / CPP-322 / CPP-323).
Any authenticated user can submit a **bug report**, **feature request** or
**improvement** from anywhere in the app. Items are captured against the
submitter's school for reporting but triaged centrally by the product owner.

Bug-category submissions additionally **auto-file a Jira CPP Bug** and **ping a
Discord channel** (`#cwa-feedback`) so the team sees real user-reported bugs in
real time without polling the feedback queue.

## Key models

- `Feedback` — the submission. Fields of note: `category` (`bug` / `feature` /
  `improvement`), `status` lifecycle (`new` → `triaged` → `planned` → `done` /
  `rejected` / `duplicate`), `priority`, `assignee` (product owner),
  `jira_key` (the auto-created Jira issue, used for traceability **and** to
  dedupe re-reports), and `removed_at` (soft delete).

## Bug → Jira → Discord flow

When a `Feedback` with `category='bug'` is submitted
(`SubmitFeedbackView`, `views.py`):

1. The item is saved and assigned to the feedback owner.
2. A background task (`tasks.report_bug_to_jira`) is enqueued on the RQ
   `default` queue. **Enqueue is wrapped in try/except** — a queue outage logs
   but never fails the user's submission.
3. The worker runs `services.report_feedback_bug(feedback)`, which:
   - Creates a Jira **Bug** via REST v3 (ADF description) and stores the
     returned key on `feedback.jira_key`.
   - Posts a one-line announcement to the Discord webhook with the title,
     reporter and a link to the Jira issue.

The daily error-log cron (`scripts/cron_check_errors.sh`) files its own Jira
issue for error spikes and posts the **same** Discord ping — so both
user-reported and log-detected bugs land in `#cwa-feedback`.

### Design guarantees

- **Config-gated.** If `JIRA_*` or `FEEDBACK_DISCORD_WEBHOOK` is unset, the
  helpers log a warning and no-op. Local / dev / CI run with zero outbound
  calls; a missing integration never breaks feedback submission.
- **Idempotent.** A `Feedback` that already carries a `jira_key` is skipped, so
  an RQ retry or a duplicate enqueue won't create duplicate issues.
- **Bounded.** Every outbound HTTP call has a 10s timeout, so a hung
  Jira/Discord endpoint can't pin an RQ worker for the full job timeout.
- **No silent failure.** Every non-2xx / exception path is logged (warning when
  simply unconfigured, error when a configured call fails).

## Public service API

```python
from feedback import services

# Orchestrator — file Jira bug + Discord ping for one Feedback (idempotent):
services.report_feedback_bug(feedback)

# Lower-level helpers (both config-gated, never raise):
key = services.create_jira_bug(summary='...', description='...', labels=['feedback'])
services.post_discord('🐞 message text')
```

## Configuration

In `settings.py` (all default to empty / disabled):

```python
JIRA_BASE_URL = os.environ.get('JIRA_BASE_URL', '')
JIRA_USER_EMAIL = os.environ.get('JIRA_USER_EMAIL', '')
JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN', '')
JIRA_PROJECT_KEY = os.environ.get('JIRA_PROJECT_KEY', 'CPP')
FEEDBACK_DISCORD_WEBHOOK = os.environ.get('FEEDBACK_DISCORD_WEBHOOK', '')
```

Server setup (which env file gets which var, the copy-from-cron script, and the
gunicorn restart) is documented in
[`Runbooks/production-deployment.md` §4.6](../../Runbooks/production-deployment.md).
The Jira creds already live in `/etc/cwa/cron_jira.env`; the **app** needs them
in `cwa.env` / `cwa-test.env` too, or the Discord ping fires but says
`(Jira not configured)` and no issue is created.

## Dependencies

- **accounts** — `CustomUser` is the submitter (`submitted_by`) and owner.
- **classroom** — `School` is the tenant context (`school`).
- **taskqueue** — `services.enqueue_task` runs the Jira/Discord work off-request.
- **requests** — outbound Jira / Discord HTTP.

## External services

- **Jira Cloud** (`JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`) — only
  when all three are set. Instance: `codewizardsaotearoa.atlassian.net`,
  project `CPP`.
- **Discord** (`FEEDBACK_DISCORD_WEBHOOK`) — only when set. Channel
  `#cwa-feedback`.

## Tests

`tests/test_bug_reporting.py` — 8 tests, **all network mocked** (no real HTTP).
Covers enqueue-on-bug, no-enqueue-on-non-bug, queue-failure-doesn't-break-submit,
config-gating, ADF payload shape, idempotency, and the Discord post path.
