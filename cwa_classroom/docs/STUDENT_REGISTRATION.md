# Student Registration

How students get accounts in CWA Classroom.

> **Source of truth — single registration path (CPP-300).**
> There is **one** self-service registration flow. Every student registers the
> same way and pays via Stripe for paid packages. There is **no** separate
> "school student" registration form. A student becomes associated with a
> school *after* registering, by joining that school's class with a class code.
>
> This was decided in CPP-300 (commit `a130ed25`): a separate school-student
> registration form existed that **bypassed Stripe payment**. It was removed —
> `SchoolStudentRegisterView`, its URL route, template, and sitemap entry — so
> that all students go through the single payment-enforcing path.

---

## The two ways a student account is created

| Path | Who starts it | Entry point | Role | School link |
|------|---------------|-------------|------|-------------|
| **Self-service** | The student | `/accounts/register/individual-student/` | `INDIVIDUAL_STUDENT` | Optional — by joining a class later |
| **Teacher-created** | A teacher / Head of Institute | CSV import or manual add → student finishes at `/accounts/complete-profile/` | `STUDENT` | Created by the teacher |

There is intentionally **no third "register as a school student" path**.

---

## Path 1 — Self-service registration

**View:** `IndividualStudentRegisterView` (`accounts/views.py`)
**Template:** `templates/accounts/register_individual_student.html`

A single 5-step wizard, identical for everyone:

1. **Account details** — username, email, password.
2. **Personal details** — name, DOB, phone, address.
3. **Package selection** — choose a subscription package.
4. **Terms & Privacy** — must scroll and accept both documents.
5. **Discount code** (optional) — then submit.

On submit the flow creates a `CustomUser` with the **`INDIVIDUAL_STUDENT`** role,
then:

- **Free package or 100%-discount code** → account created immediately,
  subscription activated, no Stripe. Redirects to `select_classes`.
- **Paid package** → the account is *not* created yet. Registration data is
  stashed in `PendingRegistration.data` and the user is sent to Stripe Checkout.
  After payment, `billing/views.py::_create_account_from_pending` creates the
  account + subscription (idempotent, safe for the webhook + browser race).

**No card data is ever collected in-app** — Stripe Checkout handles all card
entry. This is deliberate (PCI-avoidance) and is the reason there is no
"card number" field on any registration form.

### Becoming a school student (joining a class)

After registering, the student joins a class at **`select_classes`**
(`SelectClassesView`, gated to `is_individual_student`). They enter the
**class code** their teacher gave them; on success a `ClassStudent` enrollment
is created, associating them with that class (and its school). This — not a
separate registration type — is how a self-service student "becomes a school
student." Class-count limits from their package/promo codes apply here.

---

## Path 2 — Teacher-created onboarding

**Creation:** `classroom/import_services.py` (CSV import) or manual add in the
admin dashboard. Students are created with `must_change_password=True` and
`profile_completed=False`.

**Completion:** `CompleteProfileView` (`accounts/views.py`), reached because
`ProfileCompletionMiddleware` redirects any logged-in user with
`must_change_password` or `profile_completed=False` to `/accounts/complete-profile/`.

That page asks for a new password, personal/address details, an optional
**discount code**, and routes to **Stripe** for the subscription (or activates
free on a 100% code). Teacher-created students already belong to their school
(the teacher enrolled them), so no class code is needed here.

---

## Why there is no "register as a school student" option

The original CPP-318 ticket reported that "registering as a school student asks
for a class code but not a discount code or card number." On review this did
not describe a real, supported flow:

- The **discount code** is already collected (step 5) for every student.
- **Card number** is never collected in-app by design — Stripe handles it.
- A self-service **school-student registration type** was deliberately removed
  in CPP-300 because it bypassed payment.

The correct model is the single path documented above. If student-initiated
school enrollment is ever wanted as a real feature, it should be designed
deliberately (with payment enforcement and a teacher-approval gate), not added
back as a registration shortcut.

---

## Tests

- **Unit:** `accounts/tests.py` — registration flows (institute, individual
  student, complete-profile / Stripe enforcement from CPP-300).
- **UI (Playwright):** `ui_tests/test_cpp300_import_onboarding.py` and related
  registration UI tests.

## Key files

- `accounts/views.py` — `IndividualStudentRegisterView`, `CompleteProfileView`,
  `SelectClassesView`
- `billing/views.py` — `_create_account_from_pending`
- `classroom/import_services.py` — teacher/CSV student creation
- `cwa_classroom/middleware.py` — `ProfileCompletionMiddleware`
- `templates/accounts/register_individual_student.html`
