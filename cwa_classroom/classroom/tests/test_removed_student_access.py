"""
Post-removal access for a student who no longer belongs to any school.

After removal from their last school (converted to an individual student):
- They can still LOG IN and use the app *if they hold an active subscription*
  (an individual student with no subscription is correctly walled to the
  payment page — that path is asserted too).
- Their OLD invoices remain and stay visible to their parent (invoices are
  keyed by student, never school-membership-gated).
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription, Package, Subscription
from classroom.models import (
    School, SchoolStudent, ParentStudent, Invoice,
)


def _role(name):
    r, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()})
    return r


def _has_role(user, name):
    return UserRole.objects.filter(user=user, role__name=name).exists()


class RemovedStudentLoginTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = CustomUser.objects.create_user(
            username='acc_admin', password='password1!', email='wlhtestmails+accadmin@gmail.com')
        UserRole.objects.get_or_create(user=self.admin, role=_role(Role.HEAD_OF_INSTITUTE))
        self.school = School.objects.create(name='Acc School', slug='acc-school', admin=self.admin)
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic-acc', price=Decimal('89.00'), stripe_price_id='price_acc',
            class_limit=50, student_limit=500, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'))
        SchoolSubscription.objects.create(school=self.school, plan=plan, status='active')

        self.student = CustomUser.objects.create_user(
            username='acc_student', password='password1!',
            email='wlhtestmails+accstudent@gmail.com', profile_completed=True)
        UserRole.objects.get_or_create(user=self.student, role=_role(Role.STUDENT))
        SchoolStudent.objects.create(school=self.school, student=self.student, is_active=True)

    def _give_subscription(self):
        pkg = Package.objects.create(name='Ind', price=Decimal('19.90'), stripe_price_id='price_accind')
        return Subscription.objects.create(
            user=self.student, package=pkg, status=Subscription.STATUS_ACTIVE,
            discount_percent_snapshot=100)

    def _remove_from_school(self):
        self.client.login(username='acc_admin', password='password1!')
        self.client.post(reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id}))
        self.client.logout()

    def test_login_succeeds_with_subscription_after_removal(self):
        self._give_subscription()
        self._remove_from_school()
        # Converted to an individual student, account still active.
        self.assertTrue(_has_role(self.student, Role.INDIVIDUAL_STUDENT))
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)

        logged_in = self.client.login(username='acc_student', password='password1!')
        self.assertTrue(logged_in)
        # An authenticated, subscribed individual student is not walled.
        resp = self.client.get(reverse('homework:student_list'))
        self.assertEqual(resp.status_code, 200)

    def test_removed_student_without_subscription_is_walled(self):
        self._remove_from_school()
        self.client.login(username='acc_student', password='password1!')
        # Individual student, no subscription → redirected to the payment wall
        # (still logged in — kept for billing access).
        resp = self.client.get(reverse('homework:student_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('trial-expired', resp.url)


class RemovedStudentInvoiceVisibilityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = CustomUser.objects.create_user(
            username='inv_admin', password='password1!', email='wlhtestmails+invadmin@gmail.com')
        UserRole.objects.get_or_create(user=self.admin, role=_role(Role.HEAD_OF_INSTITUTE))
        self.school = School.objects.create(name='Inv School', slug='inv-school', admin=self.admin)
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic-inv', price=Decimal('89.00'), stripe_price_id='price_inv',
            class_limit=50, student_limit=500, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'))
        SchoolSubscription.objects.create(school=self.school, plan=plan, status='active')

        self.student = CustomUser.objects.create_user(
            username='inv_student', password='password1!',
            email='wlhtestmails+invstudent@gmail.com', first_name='Ivy', last_name='Nguyen',
            profile_completed=True)
        UserRole.objects.get_or_create(user=self.student, role=_role(Role.STUDENT))
        SchoolStudent.objects.create(school=self.school, student=self.student, is_active=True)

        self.parent = CustomUser.objects.create_user(
            username='inv_parent', password='password1!',
            email='wlhtestmails+invparent@gmail.com', profile_completed=True)
        UserRole.objects.get_or_create(user=self.parent, role=_role(Role.PARENT))
        ParentStudent.objects.create(
            parent=self.parent, student=self.student, school=self.school,
            is_active=True, relationship='guardian')

        self.invoice = Invoice.objects.create(
            invoice_number='INV-ACC-0001', school=self.school, student=self.student,
            billing_period_start=timezone.now().date(),
            billing_period_end=timezone.now().date(),
            attendance_mode='all_class_days',
            calculated_amount=Decimal('50.00'), amount=Decimal('50.00'),
            status='issued', due_date=timezone.now().date(),
        )

    def test_invoice_survives_removal(self):
        self.client.login(username='inv_admin', password='password1!')
        self.client.post(reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id}))
        # Invoice row is untouched by school removal.
        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.student_id, self.student.id)

    def test_parent_still_sees_old_invoice_after_removal(self):
        # Remove the student from the school first.
        self.client.login(username='inv_admin', password='password1!')
        self.client.post(reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id}))
        self.client.logout()

        # Parent opens their invoices page — the old invoice is still listed.
        self.client.login(username='inv_parent', password='password1!')
        resp = self.client.get(reverse('parent_invoices'))
        self.assertEqual(resp.status_code, 200)
        invoice_numbers = [inv.invoice_number for inv in resp.context['invoices']]
        self.assertIn('INV-ACC-0001', invoice_numbers)
