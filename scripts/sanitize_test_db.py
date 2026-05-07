#!/usr/bin/env python
"""
sanitize_test_db.py
-------------------
Sanitizes a restored prod database for use as a test/dev environment.

Run from the cwa_classroom directory:
    python manage.py shell < ../scripts/sanitize_test_db.py

Or:
    cd /home/cwa/CWA_CLASS_APP/cwa_classroom
    ../venv/bin/python manage.py shell < ../scripts/sanitize_test_db.py

What it does:
  1. Resets all user passwords to Password1!
  2. Replaces all email addresses with safe test addresses
  3. Clears Stripe IDs (set via env vars in test)
  4. Clears email logs
  5. Clears pending passwords and invite tokens
"""

import os
import sys

# ── Guard: refuse to run against prod ────────────────────────────────────────
db_name = os.environ.get('DB_NAME', '')
if db_name and 'test' not in db_name.lower():
    print(f'ABORT: DB_NAME is "{db_name}" — this does not look like a test database.')
    print('Set DB_NAME to a name containing "test" before running this script.')
    sys.exit(1)

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

User = get_user_model()

# ── 1. Reset all passwords ──────────────────────────────────────────────────
print('==> Resetting all passwords to Password1! ...')
hashed = make_password('Password1!')
count = User.objects.all().update(password=hashed, must_change_password=True)
print(f'    {count} users updated.')

# ── 2. Replace email addresses ──────────────────────────────────────────────
print('==> Replacing email addresses with test addresses ...')
for user in User.objects.all():
    if user.email:
        user.email = f'user{user.pk}@test.local'
        user.save(update_fields=['email'])
print(f'    {User.objects.count()} user emails replaced.')

# PendingRegistration
from accounts.models import PendingRegistration
pr_count = PendingRegistration.objects.all().update(email='pending@test.local')
print(f'    {pr_count} pending registrations sanitized.')

# ParentInvite
from classroom.models import ParentInvite
pi_count = ParentInvite.objects.all().update(parent_email='invite@test.local')
print(f'    {pi_count} parent invites sanitized.')

# EmailLog recipient emails
from classroom.models import EmailLog
EmailLog.objects.all().delete()
print('    Email logs cleared.')

# EmailPreference
from classroom.models import EmailPreference
EmailPreference.objects.all().delete()
print('    Email preferences cleared.')

# ── 3. Clear Stripe IDs ─────────────────────────────────────────────────────
print('==> Clearing Stripe IDs ...')

from billing.models import (
    Payment, Package, DiscountCode, InstituteDiscountCode,
    InstitutePlan, SchoolSubscription, ModuleProduct,
    ModuleSubscription, Subscription,
)
from classroom.models import Department, ClassRoom, School, InvoiceStripePayment

Payment.objects.all().update(stripe_payment_intent_id='', stripe_checkout_session_id='')
Package.objects.all().update(stripe_price_id='')
DiscountCode.objects.all().update(stripe_coupon_id='')
InstituteDiscountCode.objects.all().update(stripe_coupon_id='')
InstitutePlan.objects.all().update(stripe_price_id='', stripe_overage_price_id='')
SchoolSubscription.objects.all().update(stripe_subscription_id='', stripe_customer_id='')
ModuleProduct.objects.all().update(stripe_price_id='')
ModuleSubscription.objects.all().update(stripe_subscription_item_id='')
Subscription.objects.all().update(stripe_subscription_id='', stripe_customer_id='')
InvoiceStripePayment.objects.all().update(stripe_checkout_session_id='')
Department.objects.all().update(stripe_payment_link='')
ClassRoom.objects.all().update(stripe_payment_link='')
School.objects.all().update(stripe_payment_link='')
print('    All Stripe IDs cleared.')

# ── 4. Clear pending passwords and tokens ────────────────────────────────────
print('==> Clearing pending passwords and invite tokens ...')

from classroom.models import SchoolTeacher, SchoolStudent

SchoolTeacher.objects.exclude(pending_password='').update(pending_password='')
SchoolStudent.objects.exclude(pending_password='').update(pending_password='')
ParentInvite.objects.all().update(token=None)
print('    Pending passwords and tokens cleared.')

# ── 5. Clear welcome_email_sent so we don't accidentally resend ──────────────
print('==> Clearing welcome_email_sent timestamps ...')
User.objects.filter(welcome_email_sent__isnull=False).update(welcome_email_sent=None)
print('    Done.')

print('')
print('==> Sanitization complete!')
print('    All passwords: Password1!')
print('    All emails: user<id>@test.local')
print('    Stripe IDs: cleared')
print('    Email logs: cleared')
