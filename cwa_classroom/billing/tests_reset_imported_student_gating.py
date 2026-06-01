"""
Unit tests for the CPP-300 ``reset_imported_student_gating`` management command.

The command re-gates school students (Role.STUDENT) who have
profile_completed=True but no active/trialing Subscription, so they pass back
through the first-login payment/discount flow. It must NOT touch:
  * students with an active paid subscription
  * students with a free-discount (still active) subscription
  * staff, parents, or individual students
and must be idempotent + dry-run safe.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import CustomUser, Role, UserRole
from billing.models import Package, Subscription


def _make_user(username, role_name, profile_completed=True):
    user = CustomUser.objects.create_user(
        username=username,
        email=f'{username}@example.local',
        password='TestPass123!',
        profile_completed=profile_completed,
    )
    role, _ = Role.objects.get_or_create(
        name=role_name, defaults={'display_name': role_name.title()},
    )
    UserRole.objects.create(user=user, role=role)
    return user


def _run(dry_run=False):
    out = StringIO()
    args = ['reset_imported_student_gating']
    if dry_run:
        args.append('--dry-run')
    call_command(*args, stdout=out)
    return out.getvalue()


class ResetImportedStudentGatingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='Student Monthly', price=19.90,
            stripe_price_id='price_reset_test', is_default=True,
        )

    def test_resets_student_with_no_subscription(self):
        student = _make_user('stu_nosub', Role.STUDENT, profile_completed=True)
        _run()
        student.refresh_from_db()
        self.assertFalse(student.profile_completed)

    def test_does_not_reset_student_with_active_paid_subscription(self):
        student = _make_user('stu_paid', Role.STUDENT, profile_completed=True)
        Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_ACTIVE,
            stripe_customer_id='cus_paid123',
        )
        _run()
        student.refresh_from_db()
        self.assertTrue(student.profile_completed)

    def test_does_not_reset_student_with_free_discount_subscription(self):
        """A 100%-code student has an active sub with no Stripe customer — keep access."""
        student = _make_user('stu_free', Role.STUDENT, profile_completed=True)
        Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_ACTIVE,
            promo_code_used='FREELEARN',
        )
        _run()
        student.refresh_from_db()
        self.assertTrue(student.profile_completed)

    def test_does_not_reset_student_with_trialing_subscription(self):
        student = _make_user('stu_trial', Role.STUDENT, profile_completed=True)
        Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_TRIALING,
        )
        _run()
        student.refresh_from_db()
        self.assertTrue(student.profile_completed)

    def test_does_not_touch_staff_parent_or_individual_student(self):
        teacher = _make_user('tch_x', Role.TEACHER, profile_completed=True)
        parent = _make_user('par_x', Role.PARENT, profile_completed=True)
        indiv = _make_user('indiv_x', Role.INDIVIDUAL_STUDENT, profile_completed=True)
        _run()
        for u in (teacher, parent, indiv):
            u.refresh_from_db()
            self.assertTrue(u.profile_completed, f'{u.username} should be untouched')

    def test_dry_run_makes_no_writes(self):
        student = _make_user('stu_dry', Role.STUDENT, profile_completed=True)
        output = _run(dry_run=True)
        student.refresh_from_db()
        self.assertTrue(student.profile_completed)  # unchanged
        self.assertIn('Dry run', output)

    def test_idempotent_second_run_changes_nothing(self):
        student = _make_user('stu_idem', Role.STUDENT, profile_completed=True)
        _run()
        student.refresh_from_db()
        self.assertFalse(student.profile_completed)
        # Second run: already gated → no candidates, no error.
        output = _run()
        self.assertIn('No students need re-gating', output)
        student.refresh_from_db()
        self.assertFalse(student.profile_completed)
