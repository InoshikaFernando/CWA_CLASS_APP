# Student Basic — the free edition without the AI-graded questions

## Why

The question bank has two halves that cost very different amounts to serve.

Most questions the app marks for itself: a stored answer, a tolerance band, a
set comparison, a table of values. Serving one costs nothing.

The rest are **AI-graded** — written prose the model has to read and judge.
A question is in this half when it is an `extended_answer` (there is no stored
answer to match against) **or** its `validation_type` is `ai_graded` (the
author said explicitly that a model must mark it). Every one of those costs an
API call each time a student answers it.

There was no way to sell the first half on its own. This adds one, so a
promotional cohort can be given the app for free without giving away the metered
part of it.

## The one rule everything else follows

> **A student with no `billing.StudentModule` rows is on no tier at all.**

That is every student on the site the day this ships, and every student who
subscribes afterwards. Nothing about their access changes: individual students
are still AI-graded, and school students still answer to their school's module
or `School.free_ai_grading` exactly as before. Their 100%-discount code has
never had anything to do with AI grading and still doesn't.

Student Basic is **granted, never chosen**. There is no student-facing route
onto it — not a plan picker, not a checkout, not a form field. The owner
attaches it in the Django admin, with `manage.py student_modules`, or by
flagging a promotion code they issue. The only thing the app ever offers a
student is the way *out* of it.

## The separation

`maths.Question` owns the definition of "AI-graded", in one place and in two
matching forms, so a queryset filter and a row check can never disagree:

| | |
|---|---|
| `Question.ai_graded_q()` | the `Q` that selects the AI-graded half |
| `Question.is_ai_graded` | the same rule for one row |
| `Question.objects.ai_graded()` | that half of the bank |
| `Question.objects.not_ai_graded()` | the half Student Basic covers |

`quiz.views.gradable_for` filters on `ai_graded_q()`; `grade_extended_answer`
guards on the entitlement. Before this, `gradable_for` wrote the condition out
by hand and nothing else checked it at all.

## The modules

`billing.StudentModule` — per-student rows on `billing.Subscription`, the
individual mirror of `billing.ModuleSubscription` (which does the same job for a
school).

| slug | meaning |
|---|---|
| `student_basic` | The free promotional edition. A **withhold**: no AI-graded questions. |
| `student_ai_grading` | The paid add-on that puts them back. **Wins** over `student_basic` — it is what a Basic student upgrades to. |

### Resolution order

`worksheets.grading_service.student_can_be_ai_graded(user)`:

1. The student's **own modules** get first say
   (`billing.entitlements.student_module_ai_verdict`):
   - holds `student_ai_grading` → **yes**, whatever else is true;
   - holds `student_basic` → **no**, even at a school that bought the module
     (the promotion is given to named students, so it has to hold wherever they sit);
   - holds neither → no opinion, fall through.
2. **No school** → yes (individual students, unchanged).
3. **Schools** → yes if any of them has an `ai_grading_*` module or
   `School.free_ai_grading` (unchanged).

## Enforcement

- **Quizzes** — `gradable_for` never offers the question. Already the case for
  school students without the module; Student Basic joins them.
- **Worksheets and homework** — assigned by a *teacher*, so an AI-graded
  question can reach a student the quiz would have hidden it from.
  `grade_extended_answer(..., student=user)` refuses to make the call and
  returns `not_entitled: True`. Every caller reads that flag beside
  `quota_exceeded`, so the answer goes to the teacher's review queue.
  **It is never recorded as wrong** — a billing tier is not a reason to mark a
  child down.
- **A cache hit is still served.** It costs nothing and is a verdict this
  question has already given; withholding it would save no money and only lose
  the student a mark. The guard sits *after* the cache lookup on purpose.

## The promotion

A Student Basic student whose quiz came back short sees a banner
(`templates/billing/_ai_grading_promo.html`) naming how many questions are
waiting and what the add-on does, linking to `/billing/ai-graded-questions/`.

Shown **only** to a student who can act on it. A school student whose school
never bought the module is equally short of questions and is deliberately shown
nothing: pointing a child at a purchase only their school can make is worse than
saying nothing. `quiz.views.ai_upsell_for` draws that line.

The destination page is **not a checkout**. Per-student modules have no Stripe
flow yet, so the button records interest in the audit log
(`student_ai_grading_interest`) and says so — nothing is charged and nothing on
the account changes.

## Operating it

```bash
# Who is on what (empty is the healthy default)
python manage.py student_modules --list

# Put a cohort on the free edition
python manage.py student_modules --grant basic --user ada --user grace
python manage.py student_modules --grant basic --file promo_cohort.txt --dry-run

# Sell one of them the questions back
python manage.py student_modules --grant ai_grading --user ada

# End the promotion
python manage.py student_modules --revoke basic --user ada
```

Grants are idempotent, so a partly-applied cohort can be re-run. A revoke
deactivates the row rather than deleting it, so who had what, and when, survives
the promotion ending. A student with no `Subscription` cannot carry a module and
is reported as a skip rather than a silent success.

For a cohort signing up fresh, tick **grants student basic** on the
`DiscountCode` or `PromoCode` you issue them. The flag is off on every code that
exists, and a student typing a code can only receive the tier the owner put on
it — never pick one.

### Why the grant happens at activation, not when the code is typed

There are two shapes of promotion and they activate at completely different
moments:

- a code that covers the price **in full** activates the student on the spot,
  before Stripe is ever involved;
- a code that leaves a **balance to pay by card** sends them to Stripe, and the
  subscription is activated minutes later by the webhook — or, if that is lost,
  by the success page.

Granting when the code was *typed* would work only for the first kind. A
half-price promotion would quietly hand out the AI-graded questions it was sold
without, and nothing would fail loudly.

So the code is **recorded on the subscription**, and the tier is resolved from
it by `billing.entitlements.sync_student_modules(subscription)` every time that
subscription becomes real. It is idempotent, so every path can call it and the
webhook and the success page can both fire.

| how the student subscribed | where the code is recorded | where the tier is granted |
|---|---|---|
| individual sign-up, free or 100% code | `sub.discount_code` | inline, `accounts.views` |
| individual sign-up, paid + code | `PendingRegistration.data`, then `sub.discount_code` | `_create_account_from_pending` |
| school student, 100% code | `sub.discount_code` | inline, `CompleteProfileView` |
| school student, partial code → card | `sub.discount_code` | Stripe webhook |
| `ApplyPromoCodeView`, 100% code | `sub.discount_code` / `sub.promo_code_used` | inline |
| `ApplyPromoCodeView`, partial → card | `sub.discount_code` / `sub.promo_code_used` | Stripe webhook |

Three of those six recorded nothing at all before this: the individual sign-up
paths and both `ApplyPromoCodeView` branches bumped the code's `uses` counter
and moved on, so afterwards nothing knew which code had let the student in —
not the tier, and not anyone asking later why a student pays nothing.

A `PromoCode` leaves only its string in `promo_code_used` (there is no foreign
key for it), so `codes_on_subscription` looks both up. A code deleted after
redemption resolves to nothing rather than breaking an activation.

## Tests

| file | pins |
|---|---|
| `billing/tests_student_modules.py` | nobody is on a tier by default; grant/revoke/idempotence; code flags; the command |
| `billing/tests_student_module_signup.py` | every route to a subscription lands on the same tier — free codes, pay-the-remainder codes through the Stripe webhook, and sign-up-then-pay |
| `quiz/test_student_basic_quiz.py` | the quiz serves only the self-marked half; the two halves of the bank agree; who is offered the promotion |
| `worksheets/tests/test_student_basic_grading.py` | the money guard — no model call for an unentitled student, and a cache hit still counts |
| `ui_tests/quiz/test_student_basic_promo.py` | the AI-graded question is really absent from the page, and the shortened quiz says why |
