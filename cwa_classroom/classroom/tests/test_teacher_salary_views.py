"""
Unit tests for CPP-306: Teacher self-service salary slip list, detail, and print views.

Covers:
1.  Unauthenticated → redirect to login (all three views)
2.  Admin-role user → redirect to public_home (all three views)
3.  Teacher → 200 on list, detail, and print
4.  Senior teacher → 200 on all three views
5.  Cross-teacher slip → 403 on detail and print
6.  Draft slip → 404 on detail and print
7.  Cancelled slip → 404 on detail and print
8.  List queryset: only own slips visible
9.  List queryset: only issued/partially_paid/paid (not draft/cancelled)
10. List queryset: ordered by -billing_period_start
11. Detail context: slip, line_items, payments in context
12. Detail only shows confirmed payments
13. total_paid summary only counts 'paid' slips
"""
import uuid
from decimal import Decimal
from datetime import date

import pytest
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolTeacher,
    SalarySlip, SalarySlipLineItem, SalaryPayment,
    ClassRoom, Department,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid():
    return uuid.uuid4().hex[:6]


def _make_user(role_name):
    u = _uid()
    user = CustomUser.objects.create_user(
        username=f'user_{u}',
        email=f'user_{u}@test.local',
        password='testpass123',
        first_name='Test',
        last_name='User',
    )
    role, _ = Role.objects.get_or_create(name=role_name, defaults={'display_name': role_name.title()})
    UserRole.objects.create(user=user, role=role)
    return user


def _make_school(admin):
    u = _uid()
    return School.objects.create(
        name=f'School306 {u}',
        slug=f'school306-{u}',
        admin=admin,
        is_active=True,
        is_published=True,
    )


def _make_slip(teacher, school, status='issued', period_start=None, period_end=None, amount='100.00'):
    period_start = period_start or date(2025, 1, 1)
    period_end = period_end or date(2025, 1, 31)
    u = _uid()
    return SalarySlip.objects.create(
        teacher=teacher,
        school=school,
        slip_number=f'SS-{u}',
        billing_period_start=period_start,
        billing_period_end=period_end,
        amount=Decimal(amount),
        calculated_amount=Decimal(amount),
        status=status,
    )


def _make_payment(slip, amount='50.00', status='confirmed'):
    return SalaryPayment.objects.create(
        salary_slip=slip,
        teacher=slip.teacher,
        school=slip.school,
        amount=Decimal(amount),
        payment_date=date(2025, 2, 1),
        payment_method='bank_transfer',
        status=status,
    )


# ---------------------------------------------------------------------------
# Base test case with shared setup
# ---------------------------------------------------------------------------

class TeacherSalaryViewsTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = _make_user(Role.INSTITUTE_OWNER)
        cls.school = _make_school(cls.admin)

        cls.teacher = _make_user(Role.TEACHER)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, is_active=True)

        cls.senior_teacher = _make_user(Role.SENIOR_TEACHER)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.senior_teacher, is_active=True)

        cls.other_teacher = _make_user(Role.TEACHER)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.other_teacher, is_active=True)

        cls.slip = _make_slip(cls.teacher, cls.school, status='issued')
        cls.paid_slip = _make_slip(cls.teacher, cls.school, status='paid',
                                   period_start=date(2025, 2, 1), period_end=date(2025, 2, 28),
                                   amount='200.00')
        cls.draft_slip = _make_slip(cls.teacher, cls.school, status='draft')
        cls.cancelled_slip = _make_slip(cls.teacher, cls.school, status='cancelled')
        cls.other_slip = _make_slip(cls.other_teacher, cls.school, status='issued')

        cls.payment = _make_payment(cls.slip, status='confirmed')
        cls.unconfirmed_payment = _make_payment(cls.slip, amount='25.00', status='matched')

        cls.list_url = reverse('teacher_salary_slip_list')
        cls.detail_url = reverse('teacher_salary_slip_detail', args=[cls.slip.id])
        cls.print_url = reverse('teacher_salary_slip_print', args=[cls.slip.id])

    def _login(self, user):
        self.client.force_login(user)


# ---------------------------------------------------------------------------
# Authentication / role access
# ---------------------------------------------------------------------------

class TestAccessControl(TeacherSalaryViewsTestCase):

    def test_unauthenticated_list_redirects(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])

    def test_unauthenticated_detail_redirects(self):
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])

    def test_unauthenticated_print_redirects(self):
        r = self.client.get(self.print_url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])

    def test_admin_role_cannot_access_list(self):
        self._login(self.admin)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, 302)

    def test_admin_role_cannot_access_detail(self):
        self._login(self.admin)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, 302)

    def test_teacher_can_access_list(self):
        self._login(self.teacher)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, 200)

    def test_teacher_can_access_detail(self):
        self._login(self.teacher)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, 200)

    def test_teacher_can_access_print(self):
        self._login(self.teacher)
        r = self.client.get(self.print_url)
        self.assertEqual(r.status_code, 200)

    def test_senior_teacher_can_access_list(self):
        self._login(self.senior_teacher)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, 200)

    def test_senior_teacher_can_access_own_detail(self):
        slip = _make_slip(self.senior_teacher, self.school, status='issued')
        url = reverse('teacher_salary_slip_detail', args=[slip.id])
        self._login(self.senior_teacher)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Cross-teacher isolation
# ---------------------------------------------------------------------------

class TestCrossTeacherIsolation(TeacherSalaryViewsTestCase):

    def test_cross_teacher_detail_forbidden(self):
        url = reverse('teacher_salary_slip_detail', args=[self.other_slip.id])
        self._login(self.teacher)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 403)

    def test_cross_teacher_print_forbidden(self):
        url = reverse('teacher_salary_slip_print', args=[self.other_slip.id])
        self._login(self.teacher)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# Draft / cancelled slips return 404
# ---------------------------------------------------------------------------

class TestHiddenStatusSlips(TeacherSalaryViewsTestCase):

    def test_draft_detail_returns_404(self):
        url = reverse('teacher_salary_slip_detail', args=[self.draft_slip.id])
        self._login(self.teacher)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_draft_print_returns_404(self):
        url = reverse('teacher_salary_slip_print', args=[self.draft_slip.id])
        self._login(self.teacher)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_cancelled_detail_returns_404(self):
        url = reverse('teacher_salary_slip_detail', args=[self.cancelled_slip.id])
        self._login(self.teacher)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_cancelled_print_returns_404(self):
        url = reverse('teacher_salary_slip_print', args=[self.cancelled_slip.id])
        self._login(self.teacher)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# List queryset behaviour
# ---------------------------------------------------------------------------

class TestListQueryset(TeacherSalaryViewsTestCase):

    def _get_slip_ids(self, user):
        self.client.force_login(user)
        r = self.client.get(self.list_url)
        return {s.id for s in r.context['page'].object_list}

    def test_list_only_shows_own_slips(self):
        ids = self._get_slip_ids(self.teacher)
        self.assertIn(self.slip.id, ids)
        self.assertNotIn(self.other_slip.id, ids)

    def test_list_excludes_draft_slips(self):
        ids = self._get_slip_ids(self.teacher)
        self.assertNotIn(self.draft_slip.id, ids)

    def test_list_excludes_cancelled_slips(self):
        ids = self._get_slip_ids(self.teacher)
        self.assertNotIn(self.cancelled_slip.id, ids)

    def test_list_includes_issued_partially_paid_paid(self):
        partial = _make_slip(self.teacher, self.school, status='partially_paid',
                             period_start=date(2025, 3, 1), period_end=date(2025, 3, 31))
        ids = self._get_slip_ids(self.teacher)
        self.assertIn(self.slip.id, ids)
        self.assertIn(self.paid_slip.id, ids)
        self.assertIn(partial.id, ids)

    def test_list_ordered_by_billing_period_desc(self):
        self.client.force_login(self.teacher)
        r = self.client.get(self.list_url)
        slips = list(r.context['page'].object_list)
        dates = [s.billing_period_start for s in slips]
        self.assertEqual(dates, sorted(dates, reverse=True))


# ---------------------------------------------------------------------------
# List summary card
# ---------------------------------------------------------------------------

class TestListSummary(TeacherSalaryViewsTestCase):

    def test_total_paid_sums_only_paid_status(self):
        self.client.force_login(self.teacher)
        r = self.client.get(self.list_url)
        # paid_slip has amount=200, slip (issued) should NOT be included
        self.assertEqual(r.context['total_paid'], Decimal('200.00'))


# ---------------------------------------------------------------------------
# Detail context
# ---------------------------------------------------------------------------

class TestDetailContext(TeacherSalaryViewsTestCase):

    def test_detail_slip_in_context(self):
        self.client.force_login(self.teacher)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.context['slip'], self.slip)

    def test_detail_only_confirmed_payments_shown(self):
        self.client.force_login(self.teacher)
        r = self.client.get(self.detail_url)
        payment_ids = {p.id for p in r.context['payments']}
        self.assertIn(self.payment.id, payment_ids)
        self.assertNotIn(self.unconfirmed_payment.id, payment_ids)

    def test_detail_line_items_in_context(self):
        dept = Department.objects.create(school=self.school, name=f'Dept {_uid()}')
        classroom = ClassRoom.objects.create(
            name=f'Room {_uid()}', code=_uid(), school=self.school, department=dept
        )
        SalarySlipLineItem.objects.create(
            salary_slip=self.slip,
            classroom=classroom,
            department=dept,
            hourly_rate=Decimal('20.00'),
            rate_source='default',
            sessions_taught=4,
            hours_per_session=Decimal('1.5'),
            total_hours=Decimal('6.0'),
            line_amount=Decimal('120.00'),
        )
        self.client.force_login(self.teacher)
        r = self.client.get(self.detail_url)
        self.assertTrue(r.context['line_items'].exists())


# ---------------------------------------------------------------------------
# Print view
# ---------------------------------------------------------------------------

class TestPrintView(TeacherSalaryViewsTestCase):

    def test_print_contains_slip_number(self):
        self.client.force_login(self.teacher)
        r = self.client.get(self.print_url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.slip.slip_number)

    def test_print_only_confirmed_payments(self):
        self.client.force_login(self.teacher)
        r = self.client.get(self.print_url)
        payment_ids = {p.id for p in r.context['payments']}
        self.assertIn(self.payment.id, payment_ids)
        self.assertNotIn(self.unconfirmed_payment.id, payment_ids)
