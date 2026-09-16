# CWA Classroom — Free-Trial Campaign Runbook

**Applies to:** Running a time-limited, card-free promotion for a school cohort
(the MHM two-week offer and anything shaped like it).
**Audience:** Engineer / Agent / the repo owner, executing against the real stack.

The offer: a student works for a fixed number of days with **no card details**,
on the edition **without the AI-graded questions**. When the window closes,
access stops and asks them to subscribe. Paying moves them to the full plan —
AI-graded questions included — with no manual step.

Rehearse the whole thing on the **test site** first. Every step below works the
same there; only the paths and the URL differ, and both are listed.

| | Production | Test |
|---|---|---|
| Path | `/home/cwa/CWA_CLASS_APP` | `/home/cwa/CWA_CLASS_APP_TEST` |
| Env file | `/etc/cwa/cwa.env` | `/etc/cwa/cwa-test.env` |
| URL | `https://www.wizardslearninghub.co.nz` | `https://test.wizardslearninghub.co.nz` |

> **Both live on the same droplet (`app-prod`).** The only thing separating them
> is the directory and the env file. Sourcing the wrong env, or running from
> `/home/cwa/CWA_CLASS_APP/`, points the same command at **production**. Check
> `pwd` before anything that writes.

> **Never run Django as root.** Root-owned `.pyc` files break the next `cwa`
> deploy. Every command below uses `sudo -u cwa` and the venv python. If you
> have already run one as root:
> `find <path> -name '__pycache__' -user root -exec rm -rf {} + 2>/dev/null`

Throughout, `$APP` is the path from the table above:

```bash
APP=/home/cwa/CWA_CLASS_APP          # or _TEST
PY="sudo -u cwa $APP/venv/bin/python $APP/cwa_classroom/manage.py"
```

---

## 0. Pre-flight — three things that fail quietly

Each of these lets the campaign *look* like it worked while doing nothing.

### 0.1 Can the site take a payment?

The whole point is that they pay at the end. If checkout is broken, you find out
from a parent's screenshot a fortnight after you sent the email.

```bash
$PY check_stripe_prices --fresh
```

Non-zero exit → fix before going further (`sync_stripe_prices --create-missing`).
On a test site restored from a prod dump this **will** fail until re-pointed:
prod's live price ids are invisible to a `sk_test_` key, Stripe answers
*"No such price"*, and the app shows a generic "contact support".
See [`test-env-db-refresh.md`](test-env-db-refresh.md) § A.3.

### 0.2 Is there a default paid package to upgrade *to*?

```bash
$PY shell -c "
from billing.models import Package
for p in Package.objects.filter(is_active=True, price__gt=0).order_by('order','price'):
    print(f'{p.name:24} \${p.price}  default={p.is_default}  price_id={p.stripe_price_id or \"(MISSING)\"}')
"
```

Want exactly one `default=True` with a real `price_id`. That row is what the
payment wall quotes and what checkout charges.

### 0.3 Where does email actually go?

```bash
$PY shell -c "
from django.conf import settings
print('backend:', settings.EMAIL_BACKEND)
print('from   :', settings.DEFAULT_FROM_EMAIL)
print('daily limit:', getattr(settings, 'DAILY_EMAIL_LIMIT', 90))
"
```

`ResendEmailBackend` or `smtp.EmailBackend` = **real mail to whatever addresses
are in that database**. On a freshly-restored test environment, confirm the
addresses are sanitised (`user<id>@test.local`) before sending anything.
Never run a `send_*` command against an environment whose backend you have not
just checked.

---

## 1. Create the code — in the admin UI

**Billing → Coupon Codes → Create**

| Field | Value | Why |
|-------|-------|-----|
| Target | **Student (Billing)** | The only type that reaches a subscription. A Student (Promo) code grants class access and never touches the subscription the tier would hang off. |
| Code | e.g. `MHM2WEEKS` | What the student types. Case-insensitive on redemption. |
| Discount | **100%** | Skips Stripe entirely, so no card is collected. Also required — the tier below is refused on any code that still charges. |
| **Student Basic** | **ticked** | The free edition: the questions the app marks itself, none of the ones the AI grader has to. |
| **Access Duration** | **14** (days) | The window. **Leave it blank and the access never ends.** |
| Max uses | the cohort size | A forwarded code spreads without one. |
| Expires (optional) | last day to *start* | Not when access ends — a student starting on the final day still gets the full window. |

Three fields have to agree — 100% off, Student Basic, and a duration. Miss the
duration and you have handed out the free edition **permanently**; nothing
errors, the code works, and you find out months later when nobody was ever asked
to pay. The form warns you inline, but the warning is easy to click past.

The equivalent by command, for scripted or bulk setup:

```bash
$PY free_trial_code --code MHM2WEEKS --max-uses 200 --dry-run   # rehearse
$PY free_trial_code --code MHM2WEEKS --max-uses 200             # write it
$PY free_trial_code --code MHM2WEEKS --deactivate               # stop new sign-ups
```

### Verify before you tell anyone about it

```bash
$PY shell -c "
from billing.models import DiscountCode
c = DiscountCode.objects.get(code__iexact='MHM2WEEKS')
print('percent off :', c.discount_percent, '(want 100)')
print('grant_days  :', c.grant_days, '(want 14 — None means FOREVER)')
print('no AI       :', c.grants_student_basic, '(want True)')
print('active      :', c.is_active, ' valid:', c.is_valid())
print('uses        :', c.uses, '/', c.max_uses)
"
```

---

## 2. Send the invitation

Sent by an **Admin, Institute Owner or Head of Institute** — the Messaging
Centre resolves recipients from *that user's* school.

### 2.1 Compose

**Messaging → Compose**

1. **Start** row → **Free trial invitation**. Fills the subject and body with the
   offer, the no-card promise, and what happens when it ends. Every word stays
   editable; **Write my own** gives you a blank page.
2. **Fill the blanks.** The template leaves `[[CODE]]`, `[[LINK]]`, `[[PRICE]]`,
   `[[DATE]]`. **Send stays disabled until none remain**, and the page names
   which are left — this exists so nobody receives an email telling them to
   enter the code `[[CODE]]`.
3. **Recipients** — the chips above the To field:
   - **Unsubscribed Students** — everyone in the school with no live
     subscription of their own, *including students who never had one*.
   - **Their Parents** — the parents of exactly those students. The student has
     the account; the parent has the card. Usually you want both.

   Do **not** use "All Students" for a promotion: it offers a subscription to
   the families already paying for one.
4. **Send test to self** — the button beside Send. Do this every time.
5. Send Now, or schedule it.

### 2.2 Or by command

```bash
$PY notify_payment_required --school <id> \
    --audience unsubscribed --include-parents --dry-run
```

`--dry-run` prints the exact recipient list and sends nothing. **Always run it
first and read the list.** To send, drop `--dry-run` and add the offer:

```bash
$PY notify_payment_required --school <id> \
    --audience unsubscribed --include-parents \
    --discount-code MHM2WEEKS --discount-percent 100 \
    --link-url https://www.wizardslearninghub.co.nz/accounts/complete-profile/
```

- `--audience unsubscribed` — anyone with no live subscription, never-subscribed
  included. This is the campaign audience.
- `--audience regated` (the default) — the older, narrower nudge: students the
  re-gating pass put back behind the wall who have logged in before. It cannot
  see a student coming off a promotion (their profile is complete and they have
  logged in), so do not reach for it here.
- Anyone already sent this email is skipped, so a re-run is safe; `--resend`
  overrides that.

### 2.3 Mail does not leave immediately

Both routes queue into `EmailQueue`. A cron (`process_email_queue`, every two
minutes) does the delivery, **capped at `DAILY_EMAIL_LIMIT` (default 90) sends
per day**.

A 200-student cohort plus parents is ~400 emails — that is **four to five days**
of draining, not an afternoon. Plan the send date accordingly, or raise the cap
deliberately for the campaign.

```bash
$PY process_email_queue --limit 50     # drain by hand
$PY check_email_queue_health           # is anything stuck?
```

If mail has not arrived, check the queue before concluding the feature is broken.

---

## 3. What the student experiences

Worth walking one account through end to end before the cohort send.

| Day | What happens |
|-----|--------------|
| 0 | Types the code at **Complete Profile**. Goes straight into the hub. **No card form anywhere**, no Stripe iframe, no `Payment` row. |
| 0–13 | Works normally. Quiz shows only self-marked questions; the AI-graded ones are absent, with a note saying what is missing and how to get it. |
| 14+ | Next page load → payment wall: *"Your promotion has ended"*, the plan price, and a checkout link. |
| After paying | Student Basic revoked, AI grading granted, wall gone — automatically. |

**The window starts at redemption, not at code creation**, and it is exact
(`redeemed_at + grant_days`, to the second). Nothing runs overnight: the
middleware notices on the student's next request and stamps the status then.

### Verify one student

```bash
$PY shell -c "
from accounts.models import CustomUser
from billing.entitlements import active_student_modules
from worksheets.grading_service import student_can_be_ai_graded
u = CustomUser.objects.get(username='THE_STUDENT')
s = u.subscription
print('status     :', s.status)
print('trial_end  :', s.trial_end)
print('free grant :', s.is_free_grant, ' lapsed:', s.free_grant_has_lapsed)
print('stripe sub :', repr(s.stripe_subscription_id))
print('modules    :', active_student_modules(u))
print('AI graded  :', student_can_be_ai_graded(u))
"
```

- **Just redeemed:** `free grant: True`, `lapsed: False`, `stripe sub: ''`
  (empty proves no card was taken), modules include `student_basic`,
  `AI graded: False`.
- **After the window:** `lapsed: True`, and `status: expired` once they have
  loaded a page.
- **After paying:** `student_basic` gone, `student_ai_grading` present,
  `AI graded: True`, `stripe sub` populated.

Every upgrade also writes an audit event, so it is provable after the fact:

```bash
$PY shell -c "
from audit.models import AuditLog
for e in AuditLog.objects.filter(action='student_basic_upgraded_on_payment')[:20]:
    print(e.created_at, e.user)
"
```

### Testing the expiry without waiting

Set a **1-day** duration and come back tomorrow (the honest end-to-end test), or
move the clock on one subscription:

```bash
$PY shell -c "
from django.utils import timezone; from datetime import timedelta
from billing.models import Subscription
Subscription.objects.filter(user__username='THE_STUDENT').update(
    trial_end=timezone.now() - timedelta(days=1))
"
```

Then reload any page as that student. **Test site only** — never edit a real
family's subscription to prove a point.

---

## 4. Afterwards

```bash
# Who is on the promotion, and who has come off it
$PY student_modules --list

# Stop new redemptions; students already on it keep their remaining days
$PY free_trial_code --code MHM2WEEKS --deactivate
```

The `student_basic` row is deactivated rather than deleted when a student
upgrades, so who had what, and when, survives the promotion ending.

---

## Things that bite

| Symptom | Cause |
|---------|-------|
| Free access never ends | Access Duration left blank. `grant_days=None` means forever. Check `c.grant_days`. |
| "Contact support" at checkout | Stripe price ids not valid for the active key. Run `check_stripe_prices --fresh`. |
| Student pays, still no AI questions | The activation did not run. The webhook is the normal path; the success page is the fallback. Check for the `student_basic_upgraded_on_payment` audit event. |
| Email never arrives | Queued but not drained, or the daily cap is reached. `check_email_queue_health`. |
| Paying families got the offer | "All Students" was used instead of "Unsubscribed Students". |
| `[[CODE]]` reached recipients | Only possible if the message was built outside the compose form — it refuses to send with placeholders left. |
| Next deploy fails on the box | A Django command was run as root. Clear root-owned `__pycache__`. |

## Related

- [`production-deployment.md`](production-deployment.md) — hosting, deploys, day-2 ops.
- [`test-env-db-refresh.md`](test-env-db-refresh.md) — sanitising a test environment, and why Stripe ids must be re-pointed.
- `cwa_classroom/MANAGEMENT_COMMANDS.md` — every command referenced above.
