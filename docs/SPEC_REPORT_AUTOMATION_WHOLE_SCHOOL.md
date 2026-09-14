# Report Automation — Whole-School Sending

**Jira:** CPP-422 | **Builds on:** CPP-388 (period reports), CPP-395 (per-subject reports)

## Problem

Report automation reached a narrow slice of a school. Three independent filters
stacked up:

1. a student had to be in a class with that period switched on
   (`progress.report_settings.enabled_classrooms`);
2. the staff preview's *Subscribed students only* filter could narrow it
   further (`billing.selectors.filter_subscribed`);
3. a report with no activity was generated but never delivered — both
   `notify_report` and `email_parents_term_report` returned early on
   `not report.has_activity`.

So the families a school most wants to hear from — the ones who never
subscribed, and the ones who subscribed and then did nothing — were exactly the
ones who received silence. From a parent's side that is indistinguishable from
the school not bothering.

## Scope

A school can switch its run to cover **every active student in the school**.
Nobody in a covered school is silently skipped: a student with nothing to show
produces a short note to their parents that says so, and says why.

Off until switched on, like every other flag in this cascade. Installing the
release changes nothing for a school that does not ask for it.

## Settings

Two new tri-state fields on `ProgressReportSetting`, in their own tuple
(`OUTREACH_FIELDS`) so the per-class `DELIVERY_FIELDS` loop cannot pick them up:

| Field | Meaning | Default |
|-------|---------|---------|
| `whole_school` | The run covers every active `SchoolStudent`, not only students in a class with the report switched on, and not only subscribed ones. | off |
| `email_parents_no_data` | Email the parents when there is nothing to show. | on, once `whole_school` is on |

**Read from the school row only** — `report_settings.outreach(school)`, not the
class cascade. The cascade exists so a department or class can answer a question
differently, and "does the run cover every student in the school?" is not a
question a class can answer at all: the students it decides about are precisely
the ones with no class row to read. The settings page therefore offers these two
switches on the **school form only**, and `ReportSettingsView.post` accepts them
only when `scope == 'school'`, so nobody is given a control that would be saved
and never read.

`email_parents_no_data` resolves to `False` whenever `whole_school` is off, so a
tick left behind on a school that later turns coverage back off cannot mail
anybody in the meantime.

## Who is covered, and when

Coverage **widens a send that is happening**; it does not create one. A school
is only reached for a period if `classrooms_for_period` returned at least one
class for it — i.e. that school is actually sending this period's reports today,
by its own schedule. A school with `whole_school` on and no class switched on
sends nothing.

Two scopes skip the cohort entirely, because in both the operator has already
said who they mean:

* a **single-class** run — "this class" is not "every student in the school";
* a **`subscribed_only`** run — its whole purpose is to leave the unsubscribed
  out, and they are most of this cohort.

The preview page applies the same two exclusions, so the page and the
*Generate and send* button cannot disagree — the disagreement the preview exists
to prevent.

## The two reasons

| Reason | Test | What the parent is told |
|--------|------|-------------------------|
| `no_subscription` | `billing.selectors.is_subscribed` is False — their own `Subscription` is not `active` / `trialing` | why it is empty, the sign-in link, and the school's discount code when it has a valid one |
| `no_activity` | subscribed, but `has_activity` is False for the window | why it is empty, and a link to get started. No code. |

`no_subscription` wins when both are true: a family who never got through the
paywall could not have done the work, so telling them their child was idle is
the wrong sentence.

Deliberately **two**-valued, not three. "In no class with reports switched on"
is a true fact and an internal one — a parent reading it learns about the
school's configuration rather than about their child.

## The discount code

The school's existing `School.subscription_discount_code`, resolved by
`billing.selectors.school_discount_offer(school)` → `(code, percent)`.

Validity is `DiscountCode.is_valid()`, not `is_active` alone: a code can also be
past its `expires_at` or have burned through `max_uses`, and the checkout gate
checks all three. Emailing a code the gate will reject hands the family a
credential that fails on use — worse than sending none, because they cannot tell
the difference. An unset, expired, exhausted or inactive code simply drops out
of the email; the note still goes, and still gives the reason.

The rule was lifted out of `classroom.views_password_admin._resolve_school_discount`
(the welcome / resend email), which now delegates to it, so a family cannot be
offered a code by one email and refused it by the other.

## Delivery and idempotency

New model `PeriodReportNotice`, keyed `(student, period_type, period_start)` and
deliberately **not** on subject:

* one note per student per period — a child taking maths and coding has one
  absence, not two;
* the row *is* the idempotency key, so the daily cron can be re-run after a
  failure without a family hearing the same thing twice;
* `recipients` records how many addresses it actually reached. Zero is a real
  outcome (no parent email on file) and is recorded rather than retried, so the
  run does not mail the same nobody nightly.

No `PeriodReport` is written for a student in no reporting class: there is no
subject for it to be about, and `subject=NULL` already means "legacy row" on
that model.

`--no-notify` silences the notes along with everything else — it exists so a
school can generate and read the numbers before a family sees anything, and a
note is something a family sees.

## Reporting

Nothing about this is allowed to be silent.

* `generate_progress_reports` prints a second line per period naming the cohort,
  the reason breakdown, the notes sent and the addresses reached, plus any note
  that **reached nobody**. A school with coverage off has a zero cohort and gets
  no line, which is the default rather than a failure.
* `--dry-run` cannot know who was active (it never builds report data), so its
  figure is the students no enabled class holds — printed as "at least N … the
  real figure is this or higher" rather than as a wrong number.
* The manual send's success message and its audit `detail` carry the same
  counts.
* The settings page states in words who is currently covered and who is not.
* The preview lists the cohort with each student's reason, whether a note has
  already gone, and — when `email_parents_no_data` is off — that they will be
  written to by nobody.

## Files

| File | Change |
|------|--------|
| `progress/models.py` | `whole_school`, `email_parents_no_data`, `OUTREACH_FIELDS`/`OUTREACH_DEFAULTS`; new `PeriodReportNotice` |
| `progress/migrations/0011_whole_school_outreach.py` | new |
| `progress/report_settings.py` | `outreach()`, `covers_whole_school()` |
| `progress/outreach.py` | new — cohort, reasons, context, the email, `run_notices` |
| `progress/services.py` | `run_period` tracks who had activity and calls `_run_outreach`; `students_for_period` accepts pre-resolved classes |
| `progress/management/commands/generate_progress_reports.py` | `_report_notices` |
| `progress/views_settings.py`, `templates/progress/report_settings.html` | school-only switches + the coverage sentence |
| `progress/views_preview.py`, `templates/progress/report_preview.html` | the cohort table |
| `templates/email/transactional/progress_report_no_data.html` | new |
| `billing/selectors.py` | `is_subscribed`, `school_discount_offer` |
| `classroom/views_password_admin.py` | delegates to the moved helper |
| `progress/tests/test_whole_school_outreach.py` | new — 37 tests |
| `progress/tests/test_generate_command.py` | `WholeSchoolCommandTests` |
| `ui_tests/progress/test_whole_school_outreach_ui.py` | new — 6 Playwright tests |
| `.github/workflows/ci.yml` | `progress` filter watches `billing/selectors.py` and the new email template |
