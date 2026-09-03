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

## Where the superuser sets it

**Admin dashboard → Billing → Coupon Codes → + New Code**, the same screen the
codes are already managed on. Pick **Student (Billing)** as the Target and the
Student Basic panel appears under Applicable Packages.

### Only Student (Billing) — the other two targets cannot carry it

The three targets are three different models with three different redemption
paths, and only one of them reaches a subscription:

| Target | Model | Redeemed where | Grants |
|---|---|---|---|
| Institute | `InstituteDiscountCode` | institute checkout | % off a school's plan, plan/limit overrides |
| Student (Promo) | `PromoCode` | **Select Classes** page (`SelectClassesView`, `action=redeem`) | class access (`class_limit`) — **never touches the subscription** |
| Student (Billing) | `DiscountCode` | **sign-up step 5** and **Complete Profile** | % off the student's subscription price |

Student Basic hangs off `billing.Subscription`. An institute has no student
tier at all, and a Student (Promo) redemption only adds the student to
`redeemed_by` and bumps `uses` — there is no subscription in that code path for
a tier to attach to, so a ticked promo code would do *nothing*, silently. The
form therefore shows the panel only for Student (Billing), and the view refuses
the combination outright rather than storing a flag that can never fire.

The `grants_student_basic` field stays on `PromoCode` because
`sync_student_modules` reads both code types off a subscription, and
`ApplyPromoCodeView` — which *does* create subscriptions from promo codes,
though no page currently reaches it — would honour it correctly.

The tick is disabled unless Discount Percent is exactly 100 — enforced three
times over, because each layer sees something the others cannot: the form
(so the superuser is told before submitting), the view (so a hand-crafted POST
cannot get past it), and the model's `clean()` (so the Django admin and any
future form are covered).

The Coupon Codes list shows a **Student Basic** badge beside the discount, so
which of two 100%-off codes is the promotional one is visible at a glance
rather than something to remember.

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

### Only a 100%-off code may carry Student Basic

Nothing in account creation mentions tiers. The student picks a plan at **step
3** of the sign-up form, where they read the full price (`$19.90/mo`), and types
the code at **step 5**, which gives no feedback — it is validated on submit.
There is no screen in between.

So a code that still charges must not carry Student Basic: the student would
pay for a plan whose page they had just read, and get fewer questions than it
described, with no disclosure anywhere. `DiscountCode.clean()` and
`PromoCode.clean()` refuse the combination, which is what the admin form runs;
`apply_code_student_modules` refuses it again and logs an error, because the
form guard cannot see a row written by a script, a fixture or an old migration.

### A new promotion needs a NEW code

The flag **freezes once a code has been redeemed** (`uses > 0`), in either
direction. Reusing an existing code does not only affect the next cohort: the
code is recorded on every subscription that redeemed it, and the tier is
resolved from it each time one of those subscriptions is activated. So flipping
the flag on a circulating code reaches *backwards* — the next time an existing
holder re-checks-out, or the success page runs for them, they land on Student
Basic having been promised nothing of the sort.

CWA's own 100%-off free students are exactly the population that would hit —
`CWAEBC` (14 redemptions) and `FULLACCESS2026` (26) are already in circulation.
Do not re-flag them; issue a new code. The validation error says so.

A code nobody has redeemed yet can still be corrected — a typo is just a typo —
and the freeze is on the flag alone, not the whole row (`max_uses`, `expires_at`
and the rest stay editable).

**Consequence, stated plainly:** a fully-free code never goes to Stripe, so no
*code* reaches the webhook path today. The activation machinery below is still
correct and still tested — the free paths use it, and it is what a paid student
module (`student_ai_grading`, when it is sold) will need — but for Student Basic
it is belt-and-braces rather than load-bearing.

### What the upgrade costs

The way out of Student Basic is **becoming an ordinary paying subscriber**, not
buying a cheap module on the side. So `/billing/ai-graded-questions/` quotes the
live `Package` price — the same figure step 3 of the registration form shows —
and can never drift from it. `is_default` wins if set, else the cheapest active
paid package; free packages are excluded, since quoting `$0.00` as the upgrade
price would be worse than quoting nothing. With no paid package at all the price
block is simply absent and the page still renders.

There is deliberately **no `ModuleProduct` row** for `student_ai_grading`. A
module price would be a second place for the number to live, and the first
version of this page read one — which meant it showed no price at all, because
no such row exists.

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
| `billing/tests_student_module_signup.py` | every route to a subscription lands on the same tier; the 100%-only guard, at both layers; the quoted price is the real plan's |
| `quiz/test_student_basic_quiz.py` | the quiz serves only the self-marked half; the two halves of the bank agree; who is offered the promotion |
| `worksheets/tests/test_student_basic_grading.py` | the money guard — no model call for an unentitled student, and a cache hit still counts |
| `ui_tests/quiz/test_student_basic_promo.py` | the AI-graded question is really absent from the page, and the shortened quiz says why |
