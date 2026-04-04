"""
Tests for class-level bank account and GST overrides.

Covers:
- ClassSettingsView GET/POST
- School.get_effective_settings() with classroom overrides
- Invoice email uses class-level bank account number over department/school defaults
"""
import datetime
from decimal import Decimal
from unittest.mock import patch, call

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, Department, ClassRoom, SchoolTeacher, SchoolStudent,
    Subject, DepartmentSubject, ClassStudent,
    Invoice, InvoiceLineItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)


def _setup_school(username='hoi_cls', bank_account_number='111111',
                  bank_account_name='School Account', bank_name='School Bank',
                  bank_bsb='000-000', gst_number='SCHOOL-GST'):
    user = CustomUser.objects.create_user(
        username=username, password='pass12345', email=f'{username}@test.com',
    )
    _assign_role(user, Role.HEAD_OF_INSTITUTE)
    school = School.objects.create(
        name='Test School', slug=f'test-school-{username}', admin=user,
        bank_account_number=bank_account_number,
        bank_account_name=bank_account_name,
        bank_name=bank_name,
        bank_bsb=bank_bsb,
        gst_number=gst_number,
    )
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{username}', price=Decimal('89.00'),
        stripe_price_id=f'price_{username}', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return user, school


def _setup_dept(school, bank_account_number='', bank_account_name='',
                bank_name='', bank_bsb='', gst_number=''):
    subj, _ = Subject.objects.get_or_create(
        slug='maths-cls', defaults={'name': 'Maths', 'is_active': True},
    )
    dept = Department.objects.create(
        school=school, name='Maths Dept', slug='maths-cls-dept',
        bank_account_number=bank_account_number,
        bank_account_name=bank_account_name,
        bank_name=bank_name,
        bank_bsb=bank_bsb,
        gst_number=gst_number,
    )
    DepartmentSubject.objects.create(department=dept, subject=subj)
    return dept


def _setup_classroom(school, dept, bank_account_number='', bank_account_name='',
                     bank_name='', bank_bsb='', gst_number=''):
    return ClassRoom.objects.create(
        name='Test Class', school=school, department=dept,
        bank_account_number=bank_account_number,
        bank_account_name=bank_account_name,
        bank_name=bank_name,
        bank_bsb=bank_bsb,
        gst_number=gst_number,
    )


def _setup_student(school, username='stu_cls'):
    student = CustomUser.objects.create_user(
        username=username, password='pass12345', email=f'{username}@test.com',
        first_name='Test', last_name='Student',
    )
    _assign_role(student, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=student)
    return student


def _make_issued_invoice(school, student, classroom, created_by, amount='200.00'):
    inv = Invoice.objects.create(
        invoice_number=f'INV-CLS-{Invoice.objects.count() + 1:04d}',
        school=school,
        student=student,
        billing_period_start=datetime.date(2025, 1, 1),
        billing_period_end=datetime.date(2025, 1, 31),
        attendance_mode='all_class_days',
        calculated_amount=Decimal(amount),
        amount=Decimal(amount),
        status='issued',
        issued_at=datetime.datetime(2025, 1, 1, 9, 0, tzinfo=datetime.timezone.utc),
        due_date=datetime.date(2025, 1, 31),
        created_by=created_by,
    )
    InvoiceLineItem.objects.create(
        invoice=inv,
        classroom=classroom,
        department=classroom.department,
        daily_rate=Decimal('10.00'),
        rate_source='department_default',
        sessions_held=20,
        sessions_attended=20,
        sessions_charged=20,
        line_amount=Decimal(amount),
    )
    return inv


# ============================================================================
# get_effective_settings — unit tests
# ============================================================================

class GetEffectiveSettingsTests(TestCase):
    """Unit tests for School.get_effective_settings() classroom override logic."""

    def setUp(self):
        self.owner, self.school = _setup_school(
            username='eff_hoi',
            bank_account_number='SCHOOL-111',
            bank_account_name='School Name',
            bank_name='School Bank',
            bank_bsb='100-100',
            gst_number='SCHOOL-GST',
        )
        self.dept = _setup_dept(self.school)

    def test_school_defaults_when_no_overrides(self):
        classroom = _setup_classroom(self.school, self.dept)
        eff = self.school.get_effective_settings(self.dept, classroom=classroom)
        self.assertEqual(eff['bank_account_number'], 'SCHOOL-111')
        self.assertEqual(eff['gst_number'], 'SCHOOL-GST')

    def test_department_overrides_school(self):
        self.dept.bank_account_number = 'DEPT-222'
        self.dept.save()
        classroom = _setup_classroom(self.school, self.dept)
        eff = self.school.get_effective_settings(self.dept, classroom=classroom)
        self.assertEqual(eff['bank_account_number'], 'DEPT-222')

    def test_classroom_overrides_department(self):
        self.dept.bank_account_number = 'DEPT-222'
        self.dept.save()
        classroom = _setup_classroom(
            self.school, self.dept, bank_account_number='CLASS-333',
        )
        eff = self.school.get_effective_settings(self.dept, classroom=classroom)
        self.assertEqual(eff['bank_account_number'], 'CLASS-333')

    def test_classroom_overrides_school_when_no_dept_override(self):
        classroom = _setup_classroom(
            self.school, self.dept, bank_account_number='CLASS-333',
        )
        eff = self.school.get_effective_settings(self.dept, classroom=classroom)
        self.assertEqual(eff['bank_account_number'], 'CLASS-333')

    def test_classroom_gst_overrides_school(self):
        classroom = _setup_classroom(
            self.school, self.dept, gst_number='CLASS-GST',
        )
        eff = self.school.get_effective_settings(self.dept, classroom=classroom)
        self.assertEqual(eff['gst_number'], 'CLASS-GST')

    def test_partial_class_override_keeps_dept_values_for_other_fields(self):
        """Class overrides only bank_account_number; other banking from dept."""
        self.dept.bank_name = 'DEPT-BANK'
        self.dept.bank_bsb = 'DEPT-BSB'
        self.dept.bank_account_name = 'Dept Account'
        self.dept.save()
        classroom = _setup_classroom(
            self.school, self.dept, bank_account_number='CLASS-333',
        )
        eff = self.school.get_effective_settings(self.dept, classroom=classroom)
        self.assertEqual(eff['bank_account_number'], 'CLASS-333')
        self.assertEqual(eff['bank_name'], 'DEPT-BANK')
        self.assertEqual(eff['bank_bsb'], 'DEPT-BSB')
        self.assertEqual(eff['bank_account_name'], 'Dept Account')

    def test_empty_classroom_field_does_not_override(self):
        """A blank class field should not overwrite a set dept value."""
        self.dept.bank_account_number = 'DEPT-222'
        self.dept.save()
        # classroom has blank bank_account_number (default)
        classroom = _setup_classroom(self.school, self.dept)
        eff = self.school.get_effective_settings(self.dept, classroom=classroom)
        self.assertEqual(eff['bank_account_number'], 'DEPT-222')

    def test_no_classroom_kwarg_behaves_as_before(self):
        """Passing no classroom should give same result as before the feature."""
        self.dept.bank_account_number = 'DEPT-222'
        self.dept.save()
        eff = self.school.get_effective_settings(self.dept)
        self.assertEqual(eff['bank_account_number'], 'DEPT-222')


# ============================================================================
# ClassSettingsView — view tests
# ============================================================================

class ClassSettingsViewTests(TestCase):
    """Tests for the ClassSettingsView GET and POST."""

    def setUp(self):
        self.owner, self.school = _setup_school(username='cls_view_hoi')
        self.dept = _setup_dept(
            self.school,
            bank_account_number='DEPT-999',
            bank_name='Dept Bank',
        )
        self.classroom = _setup_classroom(self.school, self.dept)
        self.client = Client()
        self.client.login(username='cls_view_hoi', password='pass12345')
        self.url = reverse('class_settings', kwargs={'class_id': self.classroom.id})

    # ── GET ──────────────────────────────────────────────────────────────────

    def test_get_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_get_contains_classroom_in_context(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['classroom'], self.classroom)

    def test_get_form_data_shows_effective_default(self):
        """Placeholder shows dept/school effective value."""
        resp = self.client.get(self.url)
        form_data = resp.context['form_data']
        # Dept has bank_account_number='DEPT-999' — should show as effective_default
        self.assertEqual(form_data['bank_account_number']['effective_default'], 'DEPT-999')

    def test_get_is_overridden_false_when_no_class_override(self):
        resp = self.client.get(self.url)
        form_data = resp.context['form_data']
        self.assertFalse(form_data['bank_account_number']['is_overridden'])

    def test_get_is_overridden_true_when_class_has_value(self):
        self.classroom.bank_account_number = 'CLASS-777'
        self.classroom.save()
        resp = self.client.get(self.url)
        form_data = resp.context['form_data']
        self.assertTrue(form_data['bank_account_number']['is_overridden'])
        self.assertEqual(form_data['bank_account_number']['value'], 'CLASS-777')

    def test_get_requires_login(self):
        anon = Client()
        resp = anon.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

    # ── POST — save overrides ─────────────────────────────────────────────

    def test_post_saves_bank_account_number_override(self):
        resp = self.client.post(self.url, {
            'override_bank_account_number': '1',
            'bank_account_number': 'CLASS-555',
        })
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.bank_account_number, 'CLASS-555')

    def test_post_saves_all_banking_fields(self):
        resp = self.client.post(self.url, {
            'override_bank_name': '1',
            'bank_name': 'Class Bank',
            'override_bank_bsb': '1',
            'bank_bsb': '12-3456',
            'override_bank_account_number': '1',
            'bank_account_number': 'CLASS-123',
            'override_bank_account_name': '1',
            'bank_account_name': 'Class Account Name',
            'override_gst_number': '1',
            'gst_number': 'CLASS-GST-789',
        })
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.bank_name, 'Class Bank')
        self.assertEqual(self.classroom.bank_bsb, '12-3456')
        self.assertEqual(self.classroom.bank_account_number, 'CLASS-123')
        self.assertEqual(self.classroom.bank_account_name, 'Class Account Name')
        self.assertEqual(self.classroom.gst_number, 'CLASS-GST-789')

    def test_post_clears_override_when_checkbox_unchecked(self):
        self.classroom.bank_account_number = 'CLASS-555'
        self.classroom.save()
        # Post WITHOUT override_bank_account_number checkbox
        resp = self.client.post(self.url, {
            'bank_account_number': 'CLASS-555',
        })
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.bank_account_number, '')

    def test_post_redirects_back_to_settings_page(self):
        resp = self.client.post(self.url, {
            'override_bank_account_number': '1',
            'bank_account_number': 'X',
        })
        self.assertRedirects(resp, self.url)

    def test_post_trims_whitespace(self):
        resp = self.client.post(self.url, {
            'override_bank_account_number': '1',
            'bank_account_number': '  CLASS-TRIM  ',
        })
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.bank_account_number, 'CLASS-TRIM')


# ============================================================================
# Invoice email — bank account number priority tests
# ============================================================================

class InvoiceEmailBankAccountTests(TestCase):
    """
    Verify that _send_invoice_email passes the correct bank_account_number
    to the email template, respecting class → dept → school priority.
    """

    def setUp(self):
        self.owner, self.school = _setup_school(
            username='inv_email_hoi',
            bank_account_number='SCHOOL-ACC',
            bank_account_name='School Acct',
            bank_name='School Bank',
            bank_bsb='000-000',
        )
        self.dept = _setup_dept(self.school)
        self.student = _setup_student(self.school, username='inv_email_stu')

    def _send_email_and_capture_context(self, classroom):
        """Issue an invoice for classroom and return the email context dict."""
        from classroom.invoicing_services import _send_invoice_email
        inv = _make_issued_invoice(
            self.school, self.student, classroom, created_by=self.owner,
        )
        with patch('classroom.email_service.send_templated_email') as mock_send:
            _send_invoice_email(inv)
            if mock_send.called:
                return mock_send.call_args[1]['context']
            return None

    def test_school_account_number_used_when_no_overrides(self):
        classroom = _setup_classroom(self.school, self.dept)
        ctx = self._send_email_and_capture_context(classroom)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['bank_account_number'], 'SCHOOL-ACC')

    def test_department_account_number_overrides_school(self):
        self.dept.bank_account_number = 'DEPT-ACC'
        self.dept.save()
        classroom = _setup_classroom(self.school, self.dept)
        ctx = self._send_email_and_capture_context(classroom)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['bank_account_number'], 'DEPT-ACC')

    def test_class_account_number_overrides_department(self):
        self.dept.bank_account_number = 'DEPT-ACC'
        self.dept.save()
        classroom = _setup_classroom(
            self.school, self.dept, bank_account_number='CLASS-ACC',
        )
        ctx = self._send_email_and_capture_context(classroom)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['bank_account_number'], 'CLASS-ACC')

    def test_class_account_number_overrides_school_directly(self):
        """Class override works even when department has no override."""
        classroom = _setup_classroom(
            self.school, self.dept, bank_account_number='CLASS-DIRECT',
        )
        ctx = self._send_email_and_capture_context(classroom)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['bank_account_number'], 'CLASS-DIRECT')

    def test_class_gst_number_in_effective_settings(self):
        """Class-level GST number is captured in effective settings."""
        classroom = _setup_classroom(
            self.school, self.dept, gst_number='CLASS-GST-INV',
        )
        eff = self.school.get_effective_settings(self.dept, classroom=classroom)
        self.assertEqual(eff['gst_number'], 'CLASS-GST-INV')

    def test_all_bank_fields_from_class_override(self):
        classroom = _setup_classroom(
            self.school, self.dept,
            bank_account_number='CLS-NUM',
            bank_account_name='Class Acct Name',
            bank_name='Class Bank Ltd',
            bank_bsb='999-999',
        )
        ctx = self._send_email_and_capture_context(classroom)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['bank_account_number'], 'CLS-NUM')
        self.assertEqual(ctx['bank_account_name'], 'Class Acct Name')
        self.assertEqual(ctx['bank_name'], 'Class Bank Ltd')
        self.assertEqual(ctx['bank_bsb'], '999-999')

    def test_student_with_no_email_does_not_crash(self):
        """Invoice email is silently skipped for students with no email."""
        from classroom.invoicing_services import _send_invoice_email
        self.student.email = ''
        self.student.save()
        classroom = _setup_classroom(
            self.school, self.dept, bank_account_number='CLASS-ACC',
        )
        inv = _make_issued_invoice(
            self.school, self.student, classroom, created_by=self.owner,
        )
        # Should not raise
        _send_invoice_email(inv)
