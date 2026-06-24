# CWA Classroom — Jira Task Dates Runbook

**Applies to:** Every Jira work item worked by an engineer or an AI agent.
**Audience:** Engineer / Agent — a standing convention, plus a one-time backfill
procedure for historical issues.

---

## Convention (going forward)

Every Jira task carries an honest **Start date** and **End date** so cycle-time,
velocity, and the sprint burndown reflect when work actually happened.

1. **When you start a task** — as you move it into *In Progress* — set the
   **Start date** to today.
2. **When you finish a task** — as you move it to *Done* — set the **End date**
   (Due date) to today.

Do this every time, on every task. The burndown sync (`sync_sprint_burndown`,
see `cwa_classroom/MANAGEMENT_COMMANDS.md`) and any future cycle-time report
depend on these dates being present and truthful.

> **Field names are instance-specific.** "Start date" / "End date" may be native
> fields or custom fields on your board (Settings → Issues → Custom fields). Use
> whichever your team has standardised on — but use them consistently.

### Why this matters

Jira's REST API only reports an issue's **current** state — it cannot tell you
when an issue *became* Done after the fact. Recording the dates as work happens
is the only reliable source for historical reporting (and is what lets a
burndown be reconstructed rather than only built forward from daily snapshots).

---

## One-time backfill (historical *Done* tasks)

Existing tasks that were closed before this convention won't have dates. Backfill
them once, for **all tasks currently in the *Done* status**:

- **Start date** ← the date of the task's **first comment**.
  *Rationale:* the first comment is the earliest reliable "work has begun"
  signal on a legacy ticket.
  *No comments?* → fall back to the issue's **Created date**.
- **End date** ← the date the task was **marked Done** (the timestamp of its
  transition into the Done status category; use the resolution date if the
  transition history isn't available).

### How to do it

This edits real Jira data, so confirm scope before running anything at volume.
Two options:

1. **Manual / small volume** — open each Done issue, read the first comment's
   date and the Done-transition date from the history, set the two fields.
2. **Scripted / large volume** — a script against the Jira API
   (`/rest/agile/1.0/...` for issues, `/rest/api/3/issue/{key}/comment` for the
   first comment, and the changelog for the Done transition). This **mutates
   every Done issue**, so:
   - Dry-run first: print `key → start, end` for every issue and review it.
   - Then apply. Keep the dry-run output as a record of what changed.

> No silent failure: if an issue has neither comments nor a usable created date,
> or its Done-transition timestamp can't be determined, **report it** in the
> dry-run output and leave it for manual handling — don't guess a date.

---

## See also

- [`github-ticket-implementation.md`](github-ticket-implementation.md) — the
  full ticket lifecycle; sets the Start date in Step 4 and the End date in
  Step 10.
- `cwa_classroom/MANAGEMENT_COMMANDS.md` → `sync_sprint_burndown` — the daily
  burndown sync that consumes sprint/issue data.
