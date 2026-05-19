# CPP-300: Enforce Credit Card Details During Registration

## Problem

Users registering as an Institute (Head of Institute) or Individual Student
could complete registration and gain platform access without providing credit
card details when:

1. A paid plan/package had a blank `stripe_price_id` in the database
2. Stripe API threw an exception during checkout session creation

**Affected flows:**

- `TeacherCenterRegisterView` - silent `except Exception: pass` swallowed
  Stripe failures, user got full access with `STATUS_TRIALING`
- `IndividualStudentRegisterView` - `needs_stripe_payment` was `False` when
  `stripe_price_id` was blank, falling through to the free-account path
- `CompleteProfileView` - already partially handled (blocked profile
  completion), but used inline `import logging` instead of module logger

## Fix

### 1. Early validation guard (views)

Both `TeacherCenterRegisterView` and `IndividualStudentRegisterView` now check
**before account creation** whether a paid plan/package has `stripe_price_id`
set. If missing, registration is blocked with a user-facing error message.

The guard is skipped for 100% discount codes (`is_fully_free`), since those
bypass Stripe entirely.

### 2. No more silent exception swallowing

`TeacherCenterRegisterView` previously had `except Exception: pass` around the
Stripe checkout redirect. This now logs the error and shows a warning message
to the user. The account is still created (it was already committed in the
atomic block), but the user is informed that payment setup failed.

### 3. Model-level validation

`Package.clean()` and `InstitutePlan.clean()` now raise `ValidationError` if
`price > 0` and `stripe_price_id` is blank. This prevents the misconfiguration
from being saved via Django admin.

### 4. CompleteProfileView cleanup

Replaced inline `import logging; logging.getLogger(__name__)` calls with the
module-level `logger` instance for consistency.

## Files Changed

- `accounts/views.py` - Registration view guards and error handling
- `billing/models.py` - `clean()` validation on Package and InstitutePlan
- `accounts/tests.py` - Updated fixtures, added CPP-300 test classes
- `billing/tests.py` - Updated `_ensure_plans_exist()` helper with stripe IDs
- `docs/specs/CPP-300_enforce_stripe_payment.md` - This spec

## Test Coverage

- 4 new test classes with 13 CPP-300-specific tests
- Updated 4 existing test fixtures to use `stripe_price_id`
- Updated 2 tests that relied on buggy behavior
- All 384 billing + accounts tests pass
