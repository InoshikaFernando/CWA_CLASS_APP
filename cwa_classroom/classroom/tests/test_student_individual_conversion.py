"""
Tests for converting a student to an individual on last-school removal.

Rules verified (see classroom/student_lifecycle.py):
- Removed from ONE of several schools  -> role + subscription untouched.
- Removed from LAST school             -> role STUDENT -> INDIVIDUAL_STUDENT.
- Last-school + 100% (free) discount   -> role swapped, discount KEPT (stays free).
- Last-school + partial discount       -> role swapped, discount CLEARED (pay full).
- Restore to a school                  -> role swapped back to STUDENT.
- The student's account (CustomUser.is_active) is never touched.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription, Package, Subscription
from classroom.models import School, SchoolStudent
from classroom.student_lifecycle import (
    convert_to_individual_if_last_school,
    restore_school_student_role,
)


def _role(name):
    r, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()})
    return r


def _student(username):
    u = CustomUser.objects.create_user(
        username=username, password='password1!', email=f'wlhtestmails+{username}@gmail.com',
        first_name=username.title(), last_name='Test',
    )
    UserRole.objects.get_or_create(user=u, role=_role(Role.STUDENT))
    return u


def _school(slug, admin):
    school = School.objects.create(name=f'School {slug}', slug=slug, admin=admin)
    plan, _ = InstitutePlan.objects.get_or_create(
        slug=f'plan-{slug}', defaults=dict(
            name=f'Plan {slug}', price=Decimal('89.00'), stripe_price_id=f'price_{slug}',
            class_limit=50, student_limit=500, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30')))
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return school


def _has_role(user, name):
    return UserRole.objects.filter(user=user, role__name=name).exists()


class ConvertToIndividualServiceTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username='svc_admin', password='password1!', email='wlhtestmails+svcadmin@gmail.com')
        UserRole.objects.get_or_create(user=self.admin, role=_role(Role.HEAD_OF_INSTITUTE))
        self.school_a = _school('svc-a', self.admin)
        self.school_b = _school('svc-b', self.admin)

    def test_still_in_another_school_is_noop(self):
        student = _student('multi')
        SchoolStudent.objects.create(school=self.school_a, student=student, is_active=True)
        SchoolStudent.objects.create(school=self.school_b, student=student, is_active=True)
        # Simulate removal from A (deactivate its link), B still active.
        SchoolStudent.objects.filter(school=self.school_a, student=student).update(is_active=False)

        result = convert_to_individual_if_last_school(student, actor=self.admin)
        self.assertFalse(result['converted'])
        self.assertEqual(result['reason'], 'still_in_school')
        self.assertTrue(_has_role(student, Role.STUDENT))
        self.assertFalse(_has_role(student, Role.INDIVIDUAL_STUDENT))

    def test_last_school_no_subscription_swaps_role(self):
        student = _student('lastnosub')
        SchoolStudent.objects.create(school=self.school_a, student=student, is_active=False)

        result = convert_to_individual_if_last_school(student, actor=self.admin)
        self.assertTrue(result['converted'])
        self.assertEqual(result['discount'], 'none')
        self.assertFalse(_has_role(student, Role.STUDENT))
        self.assertTrue(_has_role(student, Role.INDIVIDUAL_STUDENT))
        # Account itself stays active.
        student.refresh_from_db()
        self.assertTrue(student.is_active)

    def test_last_school_100pct_discount_is_kept(self):
        student = _student('freekid')
        student.profile_completed = True
        student.save(update_fields=['profile_completed'])
        SchoolStudent.objects.create(school=self.school_a, student=student, is_active=False)
        pkg = Package.objects.create(name='Ind', price=Decimal('19.90'), stripe_price_id='price_ind1')
        Subscription.objects.create(
            user=student, package=pkg, status=Subscription.STATUS_ACTIVE,
            discount_percent_snapshot=100)

        result = convert_to_individual_if_last_school(student, actor=self.admin)
        self.assertTrue(result['converted'])
        self.assertEqual(result['discount'], 'kept_free_100')
        self.assertTrue(_has_role(student, Role.INDIVIDUAL_STUDENT))
        sub = student.subscription
        sub.refresh_from_db()
        self.assertEqual(sub.discount_percent_snapshot, 100)
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        student.refresh_from_db()
        self.assertTrue(student.profile_completed)  # still free — not re-gated

    def test_last_school_partial_discount_is_cleared(self):
        student = _student('partialkid')
        student.profile_completed = True
        student.save(update_fields=['profile_completed'])
        SchoolStudent.objects.create(school=self.school_a, student=student, is_active=False)
        pkg = Package.objects.create(name='Ind2', price=Decimal('19.90'), stripe_price_id='price_ind2')
        Subscription.objects.create(
            user=student, package=pkg, status=Subscription.STATUS_ACTIVE,
            stripe_subscription_id='sub_partial123', discount_percent_snapshot=50)

        with patch('stripe.Subscription.delete') as mock_del:
            result = convert_to_individual_if_last_school(student, actor=self.admin)
            mock_del.assert_called_once_with('sub_partial123')

        self.assertTrue(result['converted'])
        self.assertEqual(result['discount'], 'cleared')
        self.assertTrue(_has_role(student, Role.INDIVIDUAL_STUDENT))
        sub = student.subscription
        sub.refresh_from_db()
        self.assertIsNone(sub.discount_percent_snapshot)
        self.assertEqual(sub.status, Subscription.STATUS_CANCELLED)
        student.refresh_from_db()
        self.assertFalse(student.profile_completed)  # re-gated -> pays full next login

    def test_restore_swaps_role_back(self):
        student = _student('restoreme')
        # Make them individual first (as if converted).
        UserRole.objects.filter(user=student, role__name=Role.STUDENT).delete()
        UserRole.objects.get_or_create(user=student, role=_role(Role.INDIVIDUAL_STUDENT))

        swapped = restore_school_student_role(student)
        self.assertTrue(swapped)
        self.assertTrue(_has_role(student, Role.STUDENT))
        self.assertFalse(_has_role(student, Role.INDIVIDUAL_STUDENT))


class ConvertOnRemoveViewTests(TestCase):
    """Integration through SchoolStudentRemoveView / RestoreView."""

    def setUp(self):
        self.client = Client()
        self.admin = CustomUser.objects.create_user(
            username='viewadmin', password='password1!', email='wlhtestmails+viewadmin@gmail.com')
        UserRole.objects.get_or_create(user=self.admin, role=_role(Role.HEAD_OF_INSTITUTE))
        self.school_a = _school('view-a', self.admin)
        self.school_b = _school('view-b', self.admin)
        self.client.login(username='viewadmin', password='password1!')

    def _remove(self, school, student):
        return self.client.post(reverse('admin_school_student_remove', kwargs={
            'school_id': school.id, 'student_id': student.id}))

    def test_remove_from_last_school_converts_to_individual(self):
        student = _student('viewlast')
        SchoolStudent.objects.create(school=self.school_a, student=student, is_active=True)

        self._remove(self.school_a, student)

        self.assertFalse(_has_role(student, Role.STUDENT))
        self.assertTrue(_has_role(student, Role.INDIVIDUAL_STUDENT))
        # Account not deleted/deactivated.
        student.refresh_from_db()
        self.assertTrue(student.is_active)

    def test_remove_from_one_of_two_schools_keeps_student_role(self):
        student = _student('viewmulti')
        SchoolStudent.objects.create(school=self.school_a, student=student, is_active=True)
        SchoolStudent.objects.create(school=self.school_b, student=student, is_active=True)

        self._remove(self.school_a, student)

        # Still in school B → remains a school student everywhere.
        self.assertTrue(_has_role(student, Role.STUDENT))
        self.assertFalse(_has_role(student, Role.INDIVIDUAL_STUDENT))
        # School B link untouched.
        self.assertTrue(
            SchoolStudent.objects.get(school=self.school_b, student=student).is_active)

    def test_restore_after_last_school_removal_returns_student_role(self):
        student = _student('viewrestore')
        SchoolStudent.objects.create(school=self.school_a, student=student, is_active=True)
        self._remove(self.school_a, student)
        self.assertTrue(_has_role(student, Role.INDIVIDUAL_STUDENT))

        self.client.post(reverse('admin_school_student_restore', kwargs={
            'school_id': self.school_a.id, 'student_id': student.id}))

        self.assertTrue(_has_role(student, Role.STUDENT))
        self.assertFalse(_has_role(student, Role.INDIVIDUAL_STUDENT))
