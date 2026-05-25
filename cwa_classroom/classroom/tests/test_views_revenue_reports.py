from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, InvoiceStripePayment, SchoolSubscription
from classroom.models import (
    ClassRoom, ClassStudent, Department, DepartmentSubject,
    DepartmentTeacher, Invoice, InvoiceLineItem, InvoicePayment,
    School, SchoolStudent, SchoolTeacher, Subject,
)

URL = reverse('reports_revenue')


def _role(name):
    r, _ = Role.objects.get_or_create(name=name, defaults={'display_name': name})
    return r


def _user(username, role_name, **kwargs):
    u = CustomUser.objects.create_user(
        username=username, password='password1!',
        email=f'wlhtestmails+{username}@gmail.com', **kwargs,
    )
    UserRole.objects.get_or_create(user=u, role=_role(role_name))
    return u


def _school(admin):
    school = School.objects.create(name='Test School', slug=f'ts-{admin.pk}', admin=admin)
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{admin.pk}', price=Decimal('89.00'),
        stripe_price_id='price_test', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    SchoolTeacher.objects.get_or_create(
        school=school, teacher=admin, defaults={'role': 'head_of_institute'},
    )
    return school


def _enrol_student(school, username='stu1'):
    stu = _user(username, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=stu)
    return stu


def _subject():
    subj, _ = Subject.objects.get_or_create(
        slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
    )
    return subj


_dept_seq = 0


def _dept(school, head=None):
    global _dept_seq
    _dept_seq += 1
    dept = Department.objects.create(
        school=school, name=f'Dept {_dept_seq}', slug=f'dept-{school.pk}-{_dept_seq}',
    )
    DepartmentSubject.objects.create(department=dept, subject=_subject())
    if head:
        dept.head = head
        dept.save()
        DepartmentTeacher.objects.create(department=dept, teacher=head)
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=head, defaults={'role': 'head_of_department'},
        )
    return dept


_inv_seq = 0


def _invoice(school, student, amount='100.00', status='issued', created_by=None, **kwargs):
    global _inv_seq
    _inv_seq += 1
    return Invoice.objects.create(
        invoice_number=f'INV-{school.pk}-{_inv_seq}',
        school=school,
        student=student,
        billing_period_start=kwargs.get('billing_period_start', date(2026, 4, 1)),
        billing_period_end=kwargs.get('billing_period_end', date(2026, 4, 30)),
        attendance_mode='all_class_days',
        calculated_amount=Decimal(amount),
        amount=Decimal(amount),
        status=status,
        created_by=created_by,
    )


def _payment(invoice, amount='50.00', method='bank_transfer', status='confirmed'):
    return InvoicePayment.objects.create(
        invoice=invoice,
        student=invoice.student,
        school=invoice.school,
        amount=Decimal(amount),
        payment_date=date(2026, 4, 15),
        payment_method=method,
        status=status,
    )


class TestRevenueReportAccess(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('rv_hoi1', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)

    def test_requires_login(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_student_denied(self):
        stu = _user('rv_stu', Role.STUDENT)
        self.client.force_login(stu)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)

    def test_teacher_denied(self):
        teacher = _user('rv_teach', Role.TEACHER)
        self.client.force_login(teacher)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)

    def test_parent_denied(self):
        parent = _user('rv_parent', Role.PARENT)
        self.client.force_login(parent)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)

    def test_hoi_can_access(self):
        self.client.force_login(self.hoi)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)

    def test_owner_can_access(self):
        owner = _user('rv_owner', Role.INSTITUTE_OWNER)
        _school(owner)
        self.client.force_login(owner)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access(self):
        hod = _user('rv_hod1', Role.HEAD_OF_DEPARTMENT)
        _dept(self.school, head=hod)
        self.client.force_login(hod)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)


class TestRevenueReportTenantIsolation(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi_a = _user('rv_hoi_a', Role.HEAD_OF_INSTITUTE)
        self.school_a = _school(self.hoi_a)
        self.hoi_b = _user('rv_hoi_b', Role.HEAD_OF_INSTITUTE)
        self.school_b = _school(self.hoi_b)

    def test_cannot_see_other_school_invoices(self):
        stu_b = _enrol_student(self.school_b, 'rv_stu_b')
        _invoice(self.school_b, stu_b, created_by=self.hoi_b)
        self.client.force_login(self.hoi_a)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 0)


class TestRevenueReportHodScoping(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('rv_hoi3', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.hod = _user('rv_hod2', Role.HEAD_OF_DEPARTMENT)
        self.dept = _dept(self.school, head=self.hod)
        self.other_dept = _dept(self.school)

    def test_hod_sees_only_department_invoices(self):
        stu = _enrol_student(self.school, 'rv_stu_dept')
        inv_in = _invoice(self.school, stu, created_by=self.hoi)
        InvoiceLineItem.objects.create(
            invoice=inv_in, department=self.dept, daily_rate=10, rate_source='department_default',
            sessions_held=10, sessions_attended=10, sessions_charged=10, line_amount=100,
        )
        inv_out = _invoice(self.school, stu, created_by=self.hoi)
        InvoiceLineItem.objects.create(
            invoice=inv_out, department=self.other_dept, daily_rate=10, rate_source='department_default',
            sessions_held=10, sessions_attended=10, sessions_charged=10, line_amount=100,
        )
        self.client.force_login(self.hod)
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_count'], 1)
        invoice_ids = [inv.id for inv in resp.context['page_obj']]
        self.assertIn(inv_in.id, invoice_ids)
        self.assertNotIn(inv_out.id, invoice_ids)


class TestRevenueReportFilters(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('rv_hoi4', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.client.force_login(self.hoi)
        self.stu1 = _enrol_student(self.school, 'rv_fstu1')
        self.stu2 = _enrol_student(self.school, 'rv_fstu2')

    def test_filter_by_status(self):
        _invoice(self.school, self.stu1, status='paid', created_by=self.hoi)
        _invoice(self.school, self.stu2, status='issued', created_by=self.hoi)
        resp = self.client.get(URL, {'status': 'paid'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_by_student(self):
        _invoice(self.school, self.stu1, created_by=self.hoi)
        _invoice(self.school, self.stu2, created_by=self.hoi)
        resp = self.client.get(URL, {'student_id': self.stu1.pk})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_by_date_range(self):
        _invoice(self.school, self.stu1, created_by=self.hoi,
                 billing_period_start=date(2026, 3, 1), billing_period_end=date(2026, 3, 31))
        _invoice(self.school, self.stu2, created_by=self.hoi,
                 billing_period_start=date(2026, 5, 1), billing_period_end=date(2026, 5, 31))
        resp = self.client.get(URL, {'date_from': '2026-04-01', 'date_to': '2026-06-30'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_by_class(self):
        cls = ClassRoom.objects.create(name='Maths A', school=self.school, is_active=True)
        inv = _invoice(self.school, self.stu1, created_by=self.hoi)
        InvoiceLineItem.objects.create(
            invoice=inv, classroom=cls, daily_rate=10, rate_source='department_default',
            sessions_held=10, sessions_attended=10, sessions_charged=10, line_amount=100,
        )
        _invoice(self.school, self.stu2, created_by=self.hoi)
        resp = self.client.get(URL, {'class_id': cls.pk})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_by_payment_method(self):
        inv1 = _invoice(self.school, self.stu1, created_by=self.hoi)
        _payment(inv1, method='cash')
        inv2 = _invoice(self.school, self.stu2, created_by=self.hoi)
        _payment(inv2, method='bank_transfer')
        resp = self.client.get(URL, {'payment_method': 'cash'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_empty_state(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_count'], 0)

    def test_htmx_returns_partial(self):
        resp = self.client.get(URL, HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'reports/_partials/revenue_report_table.html')
        self.assertTemplateNotUsed(resp, 'reports/revenue.html')

    def test_full_request_returns_full_page(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'reports/revenue.html')
        self.assertTemplateUsed(resp, 'reports/_partials/revenue_report_table.html')


class TestRevenueReportSummaryTotals(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('rv_hoi5', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.client.force_login(self.hoi)
        self.stu = _enrol_student(self.school, 'rv_tstu')

    def test_totals_correct_with_manual_payments(self):
        inv1 = _invoice(self.school, self.stu, amount='200.00', created_by=self.hoi)
        _payment(inv1, amount='100.00')
        inv2 = _invoice(self.school, self.stu, amount='300.00', created_by=self.hoi)
        _payment(inv2, amount='300.00')
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_invoiced'], Decimal('500.00'))
        self.assertEqual(resp.context['total_paid'], Decimal('400.00'))
        self.assertEqual(resp.context['total_outstanding'], Decimal('100.00'))

    def test_totals_with_stripe_payments(self):
        inv = _invoice(self.school, self.stu, amount='200.00', created_by=self.hoi)
        _payment(inv, amount='50.00')
        parent = _user('rv_parent_s', Role.PARENT)
        InvoiceStripePayment.objects.create(
            parent=parent, total_charged=Decimal('110.00'),
            amount_applied=Decimal('100.00'), stripe_fee=Decimal('10.00'),
            status='succeeded',
            invoice_allocations=[{'invoice_id': inv.id, 'amount': '100.00'}],
        )
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_invoiced'], Decimal('200.00'))
        self.assertEqual(resp.context['total_paid'], Decimal('150.00'))
        self.assertEqual(resp.context['total_outstanding'], Decimal('50.00'))

    def test_rejected_payments_not_counted(self):
        inv = _invoice(self.school, self.stu, amount='100.00', created_by=self.hoi)
        _payment(inv, amount='50.00', status='rejected')
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_paid'], Decimal('0.00'))
        self.assertEqual(resp.context['total_outstanding'], Decimal('100.00'))
