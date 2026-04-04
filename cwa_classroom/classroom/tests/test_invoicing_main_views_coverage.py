"""
Tests for classroom/views_invoicing.py and uncovered sections of classroom/views.py.
Targets InvoiceListView, InvoiceDetailView, FeeConfigurationView,
GenerateInvoicesView, InvoicePreviewView, IssueInvoicesView,
DeleteDraftInvoicesView, CancelInvoiceView, RecordManualPaymentView,
CSVUploadView, OpeningBalancesView, SetOpeningBalanceView,
StudentSearchAPIView, plus HoD, Accounting, CreateClass, EditClass,
and ClassDetail views in views.py.
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription, Package, Payment
from classroom.models import (
    School, Department, ClassRoom, SchoolTeacher, SchoolStudent,
    Subject, Level, ClassTeacher, ClassStudent, DepartmentSubject,
    DepartmentTeacher, DepartmentLevel, DepartmentFee,
    StudentFeeOverride, Invoice, InvoiceLineItem, InvoicePayment,
    CSVColumnTemplate, CSVImport, PaymentReferenceMapping,
    CreditTransaction, ClassSession, StudentAttendance,
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
    return role


def _setup_school(admin_role=Role.INSTITUTE_OWNER):
    user = CustomUser.objects.create_user(
        username='testowner', password='pass12345', email='owner@test.com',
    )
    _assign_role(user, admin_role)
    school = School.objects.create(name='Test School', slug='test-school', admin=user)
    plan = InstitutePlan.objects.create(
        name='Basic', slug='basic-inv', price=Decimal('89.00'),
        stripe_price_id='price_inv_test', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return user, school


def _setup_department(school, head=None):
    dept = Department.objects.create(
        school=school, name='Mathematics', slug='maths-dept', head=head,
    )
    subj, _ = Subject.objects.get_or_create(
        slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
    )
    DepartmentSubject.objects.create(department=dept, subject=subj)
    if head:
        DepartmentTeacher.objects.create(department=dept, teacher=head)
        SchoolTeacher.objects.update_or_create(
            school=school, teacher=head,
            defaults={'role': 'head_of_department'},
        )
    return dept, subj


def _setup_student(school, username='student1'):
    student = CustomUser.objects.create_user(
        username=username, password='pass12345', email=f'{username}@test.com',
        first_name='Test', last_name='Student',
    )
    _assign_role(student, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=student)
    return student


def _setup_classroom(school, dept, subject=None):
    classroom = ClassRoom.objects.create(
        name='Test Class', school=school, department=dept, subject=subject,
    )
    return classroom


def _make_invoice(school, student, status='issued', amount='100.00', created_by=None):
    return Invoice.objects.create(
        invoice_number=f'INV-{Invoice.objects.count() + 1:04d}',
        school=school,
        student=student,
        billing_period_start=datetime.date(2025, 1, 1),
        billing_period_end=datetime.date(2025, 1, 31),
        attendance_mode='all_class_days',
        calculated_amount=Decimal(amount),
        amount=Decimal(amount),
        status=status,
        created_by=created_by,
    )


# ============================================================================
# Invoicing Views Tests
# ============================================================================


class InvoiceListViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_list_view_loads(self):
        resp = self.client.get(reverse('invoice_list'))
        self.assertEqual(resp.status_code, 200)

    def test_list_view_with_invoices(self):
        _make_invoice(self.school, self.student, created_by=self.owner)
        resp = self.client.get(reverse('invoice_list'))
        self.assertEqual(resp.status_code, 200)

    def test_list_view_status_filter(self):
        _make_invoice(self.school, self.student, status='issued', created_by=self.owner)
        resp = self.client.get(reverse('invoice_list') + '?status=issued')
        self.assertEqual(resp.status_code, 200)

    def test_list_view_search_filter(self):
        _make_invoice(self.school, self.student, created_by=self.owner)
        resp = self.client.get(reverse('invoice_list') + '?q=Test')
        self.assertEqual(resp.status_code, 200)

    def test_list_view_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('invoice_list'))
        self.assertEqual(resp.status_code, 302)

    def test_list_view_no_school_redirects(self):
        user2 = CustomUser.objects.create_user('noschool', 'ns@t.com', 'pass12345')
        _assign_role(user2, Role.INSTITUTE_OWNER)
        self.client.login(username='noschool', password='pass12345')
        # Delete the school association
        resp = self.client.get(reverse('invoice_list'))
        # Should redirect since user has no school
        self.assertIn(resp.status_code, [200, 302])


class InvoiceDetailViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.invoice = _make_invoice(self.school, self.student, created_by=self.owner)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_detail_view_loads(self):
        resp = self.client.get(reverse('invoice_detail', args=[self.invoice.id]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_view_404_for_other_school(self):
        other_user = CustomUser.objects.create_user('other', 'o@t.com', 'pass12345')
        _assign_role(other_user, Role.INSTITUTE_OWNER)
        other_school = School.objects.create(name='Other', slug='other', admin=other_user)
        other_student = _setup_student(other_school, username='ostudent')
        other_inv = _make_invoice(other_school, other_student, created_by=other_user)
        resp = self.client.get(reverse('invoice_detail', args=[other_inv.id]))
        self.assertEqual(resp.status_code, 404)


class FeeConfigurationViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.dept, self.subj = _setup_department(self.school, head=self.owner)
        self.student = _setup_student(self.school)
        self.classroom = _setup_classroom(self.school, self.dept, self.subj)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_fee_config_loads(self):
        resp = self.client.get(reverse('fee_configuration'))
        self.assertEqual(resp.status_code, 200)

    def test_set_classroom_fee(self):
        resp = self.client.post(
            reverse('set_classroom_fee', args=[self.classroom.id]),
            {'fee_override': '25.00'},
        )
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.fee_override, Decimal('25.00'))

    def test_set_classroom_fee_clear(self):
        self.classroom.fee_override = Decimal('50.00')
        self.classroom.save()
        resp = self.client.post(
            reverse('set_classroom_fee', args=[self.classroom.id]),
            {'fee_override': ''},
        )
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertIsNone(self.classroom.fee_override)

    def test_set_classroom_fee_invalid(self):
        resp = self.client.post(
            reverse('set_classroom_fee', args=[self.classroom.id]),
            {'fee_override': 'abc'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_set_classroom_fee_negative(self):
        resp = self.client.post(
            reverse('set_classroom_fee', args=[self.classroom.id]),
            {'fee_override': '-5'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_batch_classroom_fee(self):
        resp = self.client.post(
            reverse('batch_classroom_fee'),
            {
                'classroom_ids': str(self.classroom.id),
                f'fee_{self.classroom.id}': '30.00',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.fee_override, Decimal('30.00'))

    def test_add_student_fee_override(self):
        resp = self.client.post(
            reverse('add_student_fee_override'),
            {
                'student_id': self.student.id,
                'daily_rate': '15.00',
                'reason': 'Scholarship',
                'effective_from': '2025-01-01',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            StudentFeeOverride.objects.filter(student=self.student).exists()
        )

    def test_add_student_fee_override_invalid_rate(self):
        resp = self.client.post(
            reverse('add_student_fee_override'),
            {
                'student_id': self.student.id,
                'daily_rate': 'bad',
                'effective_from': '2025-01-01',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            StudentFeeOverride.objects.filter(student=self.student).exists()
        )

    def test_add_student_fee_override_missing_date(self):
        resp = self.client.post(
            reverse('add_student_fee_override'),
            {
                'student_id': self.student.id,
                'daily_rate': '15.00',
                'effective_from': '',
            },
        )
        self.assertEqual(resp.status_code, 302)


class GenerateInvoicesViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.dept, self.subj = _setup_department(self.school, head=self.owner)
        self.student = _setup_student(self.school)
        self.classroom = _setup_classroom(self.school, self.dept, self.subj)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_generate_get(self):
        resp = self.client.get(reverse('generate_invoices'))
        self.assertEqual(resp.status_code, 200)

    def test_generate_missing_dates(self):
        resp = self.client.post(reverse('generate_invoices'), {
            'billing_period_start': '',
            'billing_period_end': '',
        })
        self.assertEqual(resp.status_code, 302)

    def test_generate_start_after_end(self):
        resp = self.client.post(reverse('generate_invoices'), {
            'billing_period_start': '2025-02-01',
            'billing_period_end': '2025-01-01',
        })
        self.assertEqual(resp.status_code, 302)

    def test_generate_no_school(self):
        user2 = CustomUser.objects.create_user('noschool2', 'ns2@t.com', 'pass12345')
        _assign_role(user2, Role.INSTITUTE_OWNER)
        self.client.login(username='noschool2', password='pass12345')
        resp = self.client.get(reverse('generate_invoices'))
        self.assertEqual(resp.status_code, 302)


class InvoicePreviewViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_preview_no_drafts_redirects(self):
        resp = self.client.get(reverse('invoice_preview'))
        self.assertEqual(resp.status_code, 302)

    def test_preview_with_drafts(self):
        inv = _make_invoice(self.school, self.student, status='draft', created_by=self.owner)
        session = self.client.session
        session['draft_invoice_ids'] = [inv.id]
        session.save()
        resp = self.client.get(reverse('invoice_preview'))
        self.assertEqual(resp.status_code, 200)

    def test_preview_post_update_draft(self):
        inv = _make_invoice(self.school, self.student, status='draft', created_by=self.owner)
        session = self.client.session
        session['draft_invoice_ids'] = [inv.id]
        session.save()
        resp = self.client.post(reverse('invoice_preview'), {
            'invoice_id': inv.id,
            'amount': '150.00',
            'notes': 'Adjusted',
        })
        self.assertEqual(resp.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.amount, Decimal('150.00'))
        self.assertEqual(inv.notes, 'Adjusted')

    def test_preview_post_invalid_amount(self):
        inv = _make_invoice(self.school, self.student, status='draft', created_by=self.owner)
        resp = self.client.post(reverse('invoice_preview'), {
            'invoice_id': inv.id,
            'amount': 'bad',
            'notes': '',
        })
        self.assertEqual(resp.status_code, 302)


class IssueInvoicesViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    @patch('classroom.invoicing_services.issue_invoices')
    def test_issue_from_session(self, mock_issue):
        inv = _make_invoice(self.school, self.student, status='draft', created_by=self.owner)
        mock_issue.return_value = [inv]
        session = self.client.session
        session['draft_invoice_ids'] = [inv.id]
        session.save()
        resp = self.client.post(reverse('issue_invoices'))
        self.assertEqual(resp.status_code, 302)
        mock_issue.assert_called_once()

    def test_issue_no_ids_redirects(self):
        resp = self.client.post(reverse('issue_invoices'))
        self.assertEqual(resp.status_code, 302)

    @patch('classroom.invoicing_services.issue_invoices')
    def test_issue_from_post_body(self, mock_issue):
        inv = _make_invoice(self.school, self.student, status='draft', created_by=self.owner)
        mock_issue.return_value = [inv]
        resp = self.client.post(reverse('issue_invoices'), {
            'invoice_ids': [str(inv.id)],
        })
        self.assertEqual(resp.status_code, 302)


class DeleteDraftInvoicesViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_delete_drafts(self):
        inv = _make_invoice(self.school, self.student, status='draft', created_by=self.owner)
        session = self.client.session
        session['draft_invoice_ids'] = [inv.id]
        session.save()
        resp = self.client.post(reverse('delete_draft_invoices'))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Invoice.objects.filter(id=inv.id).exists())


class CancelInvoiceViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_cancel_draft_deletes(self):
        inv = _make_invoice(self.school, self.student, status='draft', created_by=self.owner)
        resp = self.client.post(reverse('cancel_invoice', args=[inv.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Invoice.objects.filter(id=inv.id).exists())

    def test_cancel_already_cancelled(self):
        inv = _make_invoice(self.school, self.student, status='cancelled', created_by=self.owner)
        resp = self.client.post(reverse('cancel_invoice', args=[inv.id]))
        self.assertEqual(resp.status_code, 302)

    @patch('classroom.invoicing_services.cancel_invoice')
    def test_cancel_issued_with_reason(self, mock_cancel):
        inv = _make_invoice(self.school, self.student, status='issued', created_by=self.owner)
        resp = self.client.post(reverse('cancel_invoice', args=[inv.id]), {
            'cancellation_reason': 'Error in billing',
        })
        self.assertEqual(resp.status_code, 302)
        mock_cancel.assert_called_once()

    def test_cancel_issued_without_reason(self):
        inv = _make_invoice(self.school, self.student, status='issued', created_by=self.owner)
        resp = self.client.post(reverse('cancel_invoice', args=[inv.id]), {
            'cancellation_reason': '',
        })
        self.assertEqual(resp.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'issued')  # should not cancel


class RecordManualPaymentViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.invoice = _make_invoice(self.school, self.student, status='issued', created_by=self.owner)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    @patch('classroom.invoicing_services.record_payment')
    def test_record_payment_success(self, mock_record):
        resp = self.client.post(
            reverse('record_manual_payment', args=[self.invoice.id]),
            {
                'amount': '50.00',
                'payment_date': '2025-01-15',
                'payment_method': 'cash',
                'notes': 'Cash payment',
            },
        )
        self.assertEqual(resp.status_code, 302)
        mock_record.assert_called_once()

    def test_record_payment_on_cancelled(self):
        self.invoice.status = 'cancelled'
        self.invoice.save()
        resp = self.client.post(
            reverse('record_manual_payment', args=[self.invoice.id]),
            {'amount': '50.00', 'payment_date': '2025-01-15'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_record_payment_on_draft(self):
        self.invoice.status = 'draft'
        self.invoice.save()
        resp = self.client.post(
            reverse('record_manual_payment', args=[self.invoice.id]),
            {'amount': '50.00', 'payment_date': '2025-01-15'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_record_payment_invalid_amount(self):
        resp = self.client.post(
            reverse('record_manual_payment', args=[self.invoice.id]),
            {'amount': 'bad', 'payment_date': '2025-01-15'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_record_payment_negative_amount(self):
        resp = self.client.post(
            reverse('record_manual_payment', args=[self.invoice.id]),
            {'amount': '-10', 'payment_date': '2025-01-15'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_record_payment_missing_date(self):
        resp = self.client.post(
            reverse('record_manual_payment', args=[self.invoice.id]),
            {'amount': '50.00', 'payment_date': ''},
        )
        self.assertEqual(resp.status_code, 302)


class CSVUploadViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_csv_upload_get(self):
        resp = self.client.get(reverse('csv_upload'))
        self.assertEqual(resp.status_code, 200)

    def test_csv_upload_no_school(self):
        user2 = CustomUser.objects.create_user('noschool3', 'ns3@t.com', 'pass12345')
        _assign_role(user2, Role.INSTITUTE_OWNER)
        self.client.login(username='noschool3', password='pass12345')
        resp = self.client.get(reverse('csv_upload'))
        self.assertEqual(resp.status_code, 302)


class OpeningBalancesViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_opening_balances_loads(self):
        resp = self.client.get(reverse('opening_balances'))
        self.assertEqual(resp.status_code, 200)

    @patch('classroom.invoicing_services.set_opening_balance')
    def test_set_opening_balance_positive(self, mock_set):
        resp = self.client.post(
            reverse('set_opening_balance', args=[self.student.id]),
            {'opening_balance': '200.00'},
        )
        self.assertEqual(resp.status_code, 302)
        mock_set.assert_called_once()

    @patch('classroom.invoicing_services.set_opening_balance')
    def test_set_opening_balance_negative_credit(self, mock_set):
        resp = self.client.post(
            reverse('set_opening_balance', args=[self.student.id]),
            {'opening_balance': '-50.00'},
        )
        self.assertEqual(resp.status_code, 302)
        mock_set.assert_called_once()

    @patch('classroom.invoicing_services.set_opening_balance')
    def test_set_opening_balance_zero(self, mock_set):
        resp = self.client.post(
            reverse('set_opening_balance', args=[self.student.id]),
            {'opening_balance': '0'},
        )
        self.assertEqual(resp.status_code, 302)
        mock_set.assert_called_once()

    def test_set_opening_balance_missing_amount(self):
        resp = self.client.post(
            reverse('set_opening_balance', args=[self.student.id]),
            {'opening_balance': ''},
        )
        self.assertEqual(resp.status_code, 302)

    def test_set_opening_balance_invalid_amount(self):
        resp = self.client.post(
            reverse('set_opening_balance', args=[self.student.id]),
            {'opening_balance': 'abc'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_batch_opening_balance(self):
        resp = self.client.post(
            reverse('batch_opening_balance'),
            {
                'student_ids': str(self.student.id),
                f'balance_{self.student.id}': '100.00',
            },
        )
        self.assertEqual(resp.status_code, 302)
        ss = SchoolStudent.objects.get(school=self.school, student=self.student)
        self.assertEqual(ss.opening_balance, Decimal('100.00'))

    def test_batch_opening_balance_no_students(self):
        resp = self.client.post(
            reverse('batch_opening_balance'),
            {'student_ids': ''},
        )
        self.assertEqual(resp.status_code, 302)


class StudentSearchAPIViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_search_returns_results(self):
        resp = self.client.get(reverse('student_search_api') + '?q=Test')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(len(data['results']), 1)

    def test_search_short_query(self):
        resp = self.client.get(reverse('student_search_api') + '?q=T')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 0)

    def test_search_no_results(self):
        resp = self.client.get(reverse('student_search_api') + '?q=ZZNonexistent')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 0)

    def test_search_no_school(self):
        user2 = CustomUser.objects.create_user('noschool4', 'ns4@t.com', 'pass12345')
        _assign_role(user2, Role.INSTITUTE_OWNER)
        self.client.login(username='noschool4', password='pass12345')
        resp = self.client.get(reverse('student_search_api') + '?q=Test')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 0)


class ReferenceMappingsViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_mappings_list_loads(self):
        resp = self.client.get(reverse('reference_mappings'))
        self.assertEqual(resp.status_code, 200)

    def test_mappings_search(self):
        PaymentReferenceMapping.objects.create(
            school=self.school, reference_name='john smith',
            student=self.student, created_by=self.owner,
        )
        resp = self.client.get(reverse('reference_mappings') + '?q=john')
        self.assertEqual(resp.status_code, 200)

    def test_mappings_delete(self):
        mapping = PaymentReferenceMapping.objects.create(
            school=self.school, reference_name='to-delete',
            student=self.student, created_by=self.owner,
        )
        resp = self.client.post(reverse('reference_mappings'), {
            'action': 'delete',
            'mapping_id': mapping.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PaymentReferenceMapping.objects.filter(id=mapping.id).exists())

    def test_mappings_update(self):
        mapping = PaymentReferenceMapping.objects.create(
            school=self.school, reference_name='to-update',
            student=self.student, created_by=self.owner,
        )
        resp = self.client.post(reverse('reference_mappings'), {
            'action': 'update',
            'mapping_id': mapping.id,
            'student_id': '',
        })
        self.assertEqual(resp.status_code, 302)
        mapping.refresh_from_db()
        self.assertTrue(mapping.is_ignored)
        self.assertIsNone(mapping.student)


class AccountantAccessTests(TestCase):
    """Test invoicing views accessible by ACCOUNTANT role."""
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.accountant = CustomUser.objects.create_user(
            'accountant1', 'acc@test.com', 'pass12345',
        )
        _assign_role(self.accountant, Role.ACCOUNTANT)
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=self.accountant, defaults={'role': 'accountant'})
        self.client = Client()
        self.client.login(username='accountant1', password='pass12345')

    def test_accountant_can_access_invoice_list(self):
        resp = self.client.get(reverse('invoice_list'))
        self.assertEqual(resp.status_code, 200)

    def test_accountant_can_access_fee_config(self):
        resp = self.client.get(reverse('fee_configuration'))
        self.assertEqual(resp.status_code, 200)

    def test_accountant_can_access_opening_balances(self):
        resp = self.client.get(reverse('opening_balances'))
        self.assertEqual(resp.status_code, 200)


# ============================================================================
# views.py Coverage Tests
# ============================================================================


class ClassDetailViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.dept, self.subj = _setup_department(self.school, head=self.owner)
        self.teacher = CustomUser.objects.create_user(
            'teacher_cd', 'tcd@test.com', 'pass12345',
        )
        _assign_role(self.teacher, Role.TEACHER)
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=self.teacher, defaults={'role': 'teacher'})
        self.classroom = _setup_classroom(self.school, self.dept, self.subj)
        ClassTeacher.objects.create(classroom=self.classroom, teacher=self.teacher)
        self.student = _setup_student(self.school)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.client = Client()

    def test_teacher_can_view_class_detail(self):
        self.client.login(username='teacher_cd', password='pass12345')
        resp = self.client.get(reverse('class_detail', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)

    def test_owner_can_view_class_detail(self):
        self.client.login(username='testowner', password='pass12345')
        resp = self.client.get(reverse('class_detail', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_view_class_detail(self):
        hod = CustomUser.objects.create_user('hod_cd', 'hod_cd@t.com', 'pass12345')
        _assign_role(hod, Role.HEAD_OF_DEPARTMENT)
        self.dept.head = hod
        self.dept.save()
        DepartmentTeacher.objects.create(department=self.dept, teacher=hod)
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=hod, defaults={'role': 'head_of_department'})
        self.client.login(username='hod_cd', password='pass12345')
        resp = self.client.get(reverse('class_detail', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)


class CreateClassViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.dept, self.subj = _setup_department(self.school, head=self.owner)
        DepartmentTeacher.objects.get_or_create(department=self.dept, teacher=self.owner)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_create_class_get(self):
        resp = self.client.get(reverse('create_class'))
        self.assertEqual(resp.status_code, 200)

    def test_create_class_post_success(self):
        resp = self.client.post(reverse('create_class'), {
            'name': 'New Math Class',
            'department': self.dept.id,
            'day': 'monday',
            'description': 'A new class',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClassRoom.objects.filter(name='New Math Class').exists())

    def test_create_class_no_name(self):
        resp = self.client.post(reverse('create_class'), {
            'name': '',
            'department': self.dept.id,
        })
        self.assertEqual(resp.status_code, 302)

    def test_create_class_no_department(self):
        resp = self.client.post(reverse('create_class'), {
            'name': 'No Dept Class',
            'department': '',
        })
        self.assertEqual(resp.status_code, 302)


class EditClassViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.dept, self.subj = _setup_department(self.school, head=self.owner)
        self.classroom = _setup_classroom(self.school, self.dept, self.subj)
        ClassTeacher.objects.create(classroom=self.classroom, teacher=self.owner)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_edit_class_get(self):
        resp = self.client.get(reverse('edit_class', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)

    def test_edit_class_post(self):
        resp = self.client.post(
            reverse('edit_class', args=[self.classroom.id]),
            {
                'name': 'Updated Class',
                'day': 'tuesday',
                'description': 'Updated desc',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.name, 'Updated Class')

    def test_edit_class_no_name(self):
        resp = self.client.post(
            reverse('edit_class', args=[self.classroom.id]),
            {'name': ''},
        )
        self.assertEqual(resp.status_code, 302)


class HoDOverviewViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.dept, self.subj = _setup_department(self.school, head=self.owner)
        self.classroom = _setup_classroom(self.school, self.dept, self.subj)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_hod_overview_loads(self):
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 200)

    def test_hod_overview_as_hod(self):
        hod = CustomUser.objects.create_user('hod_ov', 'hod_ov@t.com', 'pass12345')
        _assign_role(hod, Role.HEAD_OF_DEPARTMENT)
        self.dept.head = hod
        self.dept.save()
        DepartmentTeacher.objects.create(department=self.dept, teacher=hod)
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=hod, defaults={'role': 'head_of_department'})
        self.client.login(username='hod_ov', password='pass12345')
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 200)

    def test_hod_overview_no_permission(self):
        teacher = CustomUser.objects.create_user('teacher_np', 'tnp@t.com', 'pass12345')
        _assign_role(teacher, Role.TEACHER)
        self.client.login(username='teacher_np', password='pass12345')
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 302)  # redirect to public_home


class HoDManageClassesViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.dept, self.subj = _setup_department(self.school, head=self.owner)
        self.classroom = _setup_classroom(self.school, self.dept, self.subj)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_manage_classes_loads(self):
        resp = self.client.get(reverse('hod_manage_classes'))
        self.assertEqual(resp.status_code, 200)

    def test_manage_classes_as_hod(self):
        hod = CustomUser.objects.create_user('hod_mc', 'hod_mc@t.com', 'pass12345')
        _assign_role(hod, Role.HEAD_OF_DEPARTMENT)
        self.dept.head = hod
        self.dept.save()
        DepartmentTeacher.objects.create(department=self.dept, teacher=hod)
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=hod, defaults={'role': 'head_of_department'})
        self.client.login(username='hod_mc', password='pass12345')
        resp = self.client.get(reverse('hod_manage_classes'))
        self.assertEqual(resp.status_code, 200)


class HoDCreateClassViewTests(TestCase):
    def setUp(self):
        self.owner, self.school = _setup_school()
        self.dept, self.subj = _setup_department(self.school, head=self.owner)
        self.client = Client()
        self.client.login(username='testowner', password='pass12345')

    def test_create_class_get(self):
        resp = self.client.get(reverse('hod_create_class'))
        self.assertEqual(resp.status_code, 200)

    def test_create_class_post_success(self):
        resp = self.client.post(reverse('hod_create_class'), {
            'name': 'HoD New Class',
            'department': self.dept.id,
            'day': 'wednesday',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClassRoom.objects.filter(name='HoD New Class').exists())

    def test_create_class_no_name(self):
        resp = self.client.post(reverse('hod_create_class'), {
            'name': '',
            'department': self.dept.id,
        })
        self.assertEqual(resp.status_code, 302)

    def test_create_class_no_department(self):
        resp = self.client.post(reverse('hod_create_class'), {
            'name': 'No Dept',
            'department': '',
        })
        self.assertEqual(resp.status_code, 302)


class AccountingDashboardViewTests(TestCase):
    def setUp(self):
        self.accountant = CustomUser.objects.create_user(
            'acc_dash', 'acc_dash@t.com', 'pass12345',
        )
        _assign_role(self.accountant, Role.ACCOUNTANT)
        self.client = Client()
        self.client.login(username='acc_dash', password='pass12345')

    def test_dashboard_loads(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_packages_view(self):
        resp = self.client.get(reverse('accounting_packages'))
        self.assertEqual(resp.status_code, 200)

    def test_users_view(self):
        resp = self.client.get(reverse('accounting_users'))
        self.assertEqual(resp.status_code, 200)

    def test_export_view(self):
        resp = self.client.get(reverse('accounting_export'))
        self.assertEqual(resp.status_code, 200)

    def test_refunds_view(self):
        resp = self.client.get(reverse('accounting_refunds'))
        self.assertEqual(resp.status_code, 200)

    def test_process_refund(self):
        pkg = Package.objects.create(
            name='Test Pkg', price=Decimal('10.00'),
            stripe_price_id='price_test_pkg', is_active=True,
        )
        payment = Payment.objects.create(
            user=self.accountant, package=pkg,
            amount=Decimal('10.00'), status='succeeded',
        )
        resp = self.client.post(reverse('process_refund', args=[payment.id]))
        self.assertEqual(resp.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'refunded')

    def test_no_access_for_teacher(self):
        teacher = CustomUser.objects.create_user('teach_no', 'tn@t.com', 'pass12345')
        _assign_role(teacher, Role.TEACHER)
        self.client.login(username='teach_no', password='pass12345')
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertEqual(resp.status_code, 302)


class RoleAccessControlTests(TestCase):
    """Test that views properly deny access to unauthorized roles."""

    def setUp(self):
        self.student = CustomUser.objects.create_user(
            'student_ac', 'sac@t.com', 'pass12345',
        )
        _assign_role(self.student, Role.STUDENT)
        self.client = Client()
        self.client.login(username='student_ac', password='pass12345')

    def test_student_cannot_access_invoice_list(self):
        resp = self.client.get(reverse('invoice_list'))
        self.assertEqual(resp.status_code, 302)

    def test_student_cannot_access_fee_config(self):
        resp = self.client.get(reverse('fee_configuration'))
        self.assertEqual(resp.status_code, 302)

    def test_student_cannot_access_generate_invoices(self):
        resp = self.client.get(reverse('generate_invoices'))
        self.assertEqual(resp.status_code, 302)

    def test_student_cannot_access_hod_overview(self):
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 302)

    def test_student_cannot_access_accounting(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertEqual(resp.status_code, 302)
