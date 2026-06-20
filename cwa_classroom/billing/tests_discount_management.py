"""Tests for HoI student discount management (CPP-XXX)."""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from audit.models import AuditLog
from billing.models import DiscountCode, Package, Payment, Subscription
from classroom.models import (
    ClassRoom, ClassStudent, Department, ParentStudent, School, SchoolStudent,
)


def _role(name):
    r, _ = Role.objects.get_or_create(name=name, defaults={'display_name': name})
    return r


def _student(username):
    u = CustomUser.objects.create_user(username, f'{username}@t.com', 'pass1234')
    u.roles.add(_role(Role.STUDENT))
    return u


# ---------------------------------------------------------------------------
# Subscription.discount_state — including the legacy-paid guard
# ---------------------------------------------------------------------------

class DiscountStateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pkg = Package.objects.create(name='Wizard', price=Decimal('19.90'), stripe_price_id='price_x')

    def _sub(self, **kw):
        u = _student(f'stu{Subscription.objects.count()}')
        return Subscription.objects.create(user=u, package=self.pkg, **kw)

    def test_free_100_from_snapshot(self):
        s = self._sub(status=Subscription.STATUS_ACTIVE, discount_percent_snapshot=100)
        self.assertEqual(s.discount_state, Subscription.DISCOUNT_FREE_100)
        self.assertTrue(s.has_discount)

    def test_partial_from_snapshot(self):
        s = self._sub(status=Subscription.STATUS_ACTIVE, discount_percent_snapshot=75)
        self.assertEqual(s.discount_state, Subscription.DISCOUNT_PARTIAL)

    def test_full_when_paid_stripe_sub(self):
        s = self._sub(status=Subscription.STATUS_ACTIVE, stripe_subscription_id='sub_live')
        self.assertEqual(s.discount_state, Subscription.DISCOUNT_FULL)
        self.assertFalse(s.has_discount)

    def test_none_when_cancelled(self):
        s = self._sub(status=Subscription.STATUS_CANCELLED, discount_percent_snapshot=100)
        self.assertEqual(s.discount_state, Subscription.DISCOUNT_NONE)

    def test_legacy_free_inferred(self):
        # active, no stripe sub, no snapshot, no payment -> free_100
        s = self._sub(status=Subscription.STATUS_ACTIVE)
        self.assertEqual(s.discount_state, Subscription.DISCOUNT_FREE_100)

    def test_legacy_paid_guard(self):
        # active, no stripe sub, no snapshot, BUT a succeeded Payment -> full, NOT free_100
        s = self._sub(status=Subscription.STATUS_ACTIVE)
        Payment.objects.create(
            user=s.user, package=self.pkg, amount=Decimal('19.90'),
            status=Payment.STATUS_SUCCEEDED,
        )
        self.assertEqual(s.discount_state, Subscription.DISCOUNT_FULL)
        self.assertFalse(s.has_discount)


# ---------------------------------------------------------------------------
# StudentDiscountClearView
# ---------------------------------------------------------------------------

class ClearDiscountViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pkg = Package.objects.create(name='Wizard', price=Decimal('19.90'), stripe_price_id='price_x')
        cls.hoi = CustomUser.objects.create_user('hoi', 'hoi@t.com', 'pass1234')
        cls.hoi.roles.add(_role(Role.HEAD_OF_INSTITUTE))
        cls.school = School.objects.create(name='CWA', slug='cwa', admin=cls.hoi)

        cls.student = _student('siheli')
        SchoolStudent.objects.create(school=cls.school, student=cls.student, is_active=True)
        cls.sub = Subscription.objects.create(
            user=cls.student, package=cls.pkg,
            status=Subscription.STATUS_ACTIVE, discount_percent_snapshot=100,
            discount_code=DiscountCode.objects.create(code='CWA100', discount_percent=100),
        )

    def _url(self, student=None):
        return reverse('admin_student_discount_clear',
                       kwargs={'school_id': self.school.id, 'student_id': (student or self.student).id})

    def test_hoi_clears_free_100(self):
        self.client.force_login(self.hoi)
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_CANCELLED)
        self.assertIsNone(self.sub.discount_percent_snapshot)
        self.assertIsNone(self.sub.discount_code)
        self.assertIsNotNone(self.sub.discount_cleared_at)
        self.assertEqual(self.sub.discount_cleared_by, self.hoi)
        # re-gated
        self.student.refresh_from_db()
        self.assertFalse(self.student.profile_completed)
        # audited
        self.assertTrue(AuditLog.objects.filter(action='student_discount_cleared').exists())

    @patch('stripe.Subscription.delete')
    def test_partial_cancels_stripe_sub(self, mock_delete):
        self.sub.discount_percent_snapshot = 75
        self.sub.stripe_subscription_id = 'sub_partial'
        self.sub.save()
        self.client.force_login(self.hoi)
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 302)
        mock_delete.assert_called_once_with('sub_partial')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_CANCELLED)

    def test_paying_full_is_noop(self):
        self.sub.discount_percent_snapshot = None
        self.sub.stripe_subscription_id = 'sub_live'
        self.sub.save()
        self.client.force_login(self.hoi)
        self.client.post(self._url())
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)  # unchanged
        self.student.refresh_from_db()
        self.assertTrue(self.student.profile_completed)  # not re-gated

    def test_teacher_cannot_clear(self):
        teacher = CustomUser.objects.create_user('teach', 'teach@t.com', 'pass1234')
        teacher.roles.add(_role(Role.TEACHER))
        self.client.force_login(teacher)
        resp = self.client.post(self._url())
        # RoleRequiredMixin redirects unauthorized roles
        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)

    def test_cross_school_404(self):
        other_hoi = CustomUser.objects.create_user('hoi2', 'hoi2@t.com', 'pass1234')
        other_hoi.roles.add(_role(Role.HEAD_OF_INSTITUTE))
        School.objects.create(name='Other', slug='other', admin=other_hoi)
        self.client.force_login(other_hoi)
        # other_hoi tries to clear a student in CWA (not their school)
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 404)

    def test_hod_cannot_clear(self):
        # Per product decision, only institute leadership (HoI/Owner/Admin) may
        # clear discounts — an HoD is redirected and nothing changes, even for a
        # student in their own department.
        hod = CustomUser.objects.create_user('hod', 'hod@t.com', 'pass1234')
        hod.roles.add(_role(Role.HEAD_OF_DEPARTMENT))
        dept = Department.objects.create(school=self.school, name='Coding', head=hod)
        cls_room = ClassRoom.objects.create(name='C1', code='CL1', school=self.school, department=dept)
        ClassStudent.objects.create(classroom=cls_room, student=self.student, is_active=True)
        self.client.force_login(hod)
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 302)  # RoleRequiredMixin redirect
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)  # unchanged


# ---------------------------------------------------------------------------
# Email + backfill
# ---------------------------------------------------------------------------

class DiscountClearedEmailTest(TestCase):
    def test_notifies_student_and_parent(self):
        from billing.email_utils import send_discount_cleared_notification
        school = School.objects.create(
            name='S', slug='s',
            admin=CustomUser.objects.create_user('a', 'a@t.com', 'pass1234'),
        )
        student = _student('kid')
        parent = CustomUser.objects.create_user('par', 'par@t.com', 'pass1234')
        parent.roles.add(_role(Role.PARENT))
        ParentStudent.objects.create(parent=parent, student=student, school=school, is_active=True)
        recipients = send_discount_cleared_notification(student, school)
        self.assertIn('kid@t.com', recipients)
        self.assertIn('par@t.com', recipients)


class BackfillCommandTest(TestCase):
    def test_backfill_infers_free_but_guards_paid(self):
        from django.core.management import call_command
        pkg = Package.objects.create(name='W', price=Decimal('19.90'), stripe_price_id='p')
        free = Subscription.objects.create(
            user=_student('free1'), package=pkg, status=Subscription.STATUS_ACTIVE)
        paid = Subscription.objects.create(
            user=_student('paid1'), package=pkg, status=Subscription.STATUS_ACTIVE)
        Payment.objects.create(user=paid.user, package=pkg, amount=Decimal('19.90'),
                               status=Payment.STATUS_SUCCEEDED)
        call_command('backfill_subscription_discounts')
        free.refresh_from_db(); paid.refresh_from_db()
        self.assertEqual(free.discount_percent_snapshot, 100)   # inferred free
        self.assertIsNone(paid.discount_percent_snapshot)        # paid -> left full
