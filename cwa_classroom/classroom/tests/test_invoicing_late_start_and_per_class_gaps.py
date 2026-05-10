"""
Tests for two related invoicing fixes:

1. ``ClassStudent.billing_start_date`` — distinguishes a backdated data-entry
   enrollment (NULL → bill full period) from a genuine late-starter (set →
   bill only from that date forward).

2. ``find_uncovered_date_ranges_by_classroom`` — gap-invoice logic must
   compute uncovered ranges per classroom, not just per date window. Adding
   a student to a new class after an invoice has been issued for some other
   class in the same window should not silently drop the new class's
   sessions.

Both fixes are wired through ``calculate_invoice_lines`` (with the new
``restrict_classroom_ids`` parameter) and the gap-invoice branch of
``GenerateInvoicesView``.
"""

import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from classroom import invoicing_services as svc
from classroom.models import (
    ClassRoom, ClassSession, ClassStudent, ClassTeacher,
    Department, DepartmentSubject, Invoice, InvoiceLineItem,
    SchoolStudent, SchoolTeacher, StudentAttendance, Subject,
)

from .test_e2e_invoicing import (
    _create_user, _assign_role, _setup_school_with_subscription,
    _create_classroom, _create_completed_session, _mark_attendance,
)


def _make_school_with_two_classes(name_suffix=''):
    """
    Build a school with one department + two classrooms (CR_A daily=$35,
    CR_B daily=$25 via dept default), a student enrolled in BOTH classes,
    and an admin user. Mirrors the Min Htet scenario shape.
    """
    admin = _create_user(
        f'admin_lps{name_suffix}', first_name='Admin', last_name='LPS',
    )
    _assign_role(admin, Role.ADMIN)
    _assign_role(admin, Role.HEAD_OF_INSTITUTE)

    school = _setup_school_with_subscription(admin, f'LPS School{name_suffix}')

    teacher = _create_user(
        f'teacher_lps{name_suffix}', first_name='Teach', last_name='LPS',
    )
    _assign_role(teacher, Role.TEACHER)
    SchoolTeacher.objects.update_or_create(
        school=school, teacher=teacher, defaults={'role': 'teacher'},
    )

    subject = Subject.objects.create(
        name=f'Maths{name_suffix}', slug=f'maths{name_suffix}', school=school,
    )
    department = Department.objects.create(
        school=school, name=f'Mathematics{name_suffix}',
        slug=f'mathematics{name_suffix}',
        default_fee=Decimal('25.00'),  # CR_B inherits this
    )
    DepartmentSubject.objects.create(department=department, subject=subject)

    cr_a = _create_classroom(school, department, subject, name='CR_A')
    cr_a.fee_override = Decimal('35.00')
    cr_a.save(update_fields=['fee_override'])
    ClassTeacher.objects.create(classroom=cr_a, teacher=teacher)

    cr_b = _create_classroom(school, department, subject, name='CR_B')
    ClassTeacher.objects.create(classroom=cr_b, teacher=teacher)

    student = _create_user(
        f'student_lps{name_suffix}', first_name='Min Htet', last_name='Kyaw',
    )
    _assign_role(student, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=student)

    return {
        'admin': admin, 'school': school, 'teacher': teacher,
        'department': department, 'subject': subject,
        'cr_a': cr_a, 'cr_b': cr_b, 'student': student,
    }


# ---------------------------------------------------------------------------
# Pure-function tests (no Django client / no HTTP)
# ---------------------------------------------------------------------------

class FindUncoveredDateRangesByClassroomTest(TestCase):
    """
    Unit-tests for ``find_uncovered_date_ranges_by_classroom`` — the helper
    that computes per-classroom uncovered windows.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ctx = _make_school_with_two_classes(name_suffix='_unit')
        cls.cr_a, cls.cr_b = cls.ctx['cr_a'], cls.ctx['cr_b']
        cls.student = cls.ctx['student']
        cls.school = cls.ctx['school']
        cls.admin = cls.ctx['admin']
        ClassStudent.objects.create(
            classroom=cls.cr_a, student=cls.student, is_active=True,
        )
        ClassStudent.objects.create(
            classroom=cls.cr_b, student=cls.student, is_active=True,
        )

    def _make_issued_invoice(self, classroom_ids, start, end):
        """Helper: create an issued invoice with one line item per classroom."""
        invoice = Invoice.objects.create(
            invoice_number=f'INV-{start.isoformat()}-{",".join(str(c) for c in classroom_ids)}',
            school=self.school,
            student=self.student,
            billing_period_start=start,
            billing_period_end=end,
            attendance_mode='all_class_days',
            billing_type='upfront',
            period_type='custom',
            calculated_amount=Decimal('0.00'),
            amount=Decimal('0.00'),
            status='issued',
            issued_at=timezone.now(),
            created_by=self.admin,
        )
        for cid in classroom_ids:
            InvoiceLineItem.objects.create(
                invoice=invoice, classroom_id=cid,
                daily_rate=Decimal('35.00'), rate_source='class_default',
                sessions_held=1, sessions_attended=0, sessions_charged=1,
                line_amount=Decimal('35.00'),
            )
        return invoice

    def test_classroom_with_no_invoice_is_fully_uncovered(self):
        """An enrolled classroom with no issued line is uncovered for the full window."""
        start = datetime.date(2026, 4, 15)
        end = datetime.date(2026, 4, 30)

        # Issue an invoice that only covers CR_A (Apr 19-28)
        inv = self._make_issued_invoice(
            [self.cr_a.id], datetime.date(2026, 4, 19), datetime.date(2026, 4, 28),
        )

        gaps = svc.find_uncovered_date_ranges_by_classroom(
            [inv], start, end, [self.cr_a.id, self.cr_b.id],
        )

        # CR_A: gaps Apr 15-18 + Apr 29-30
        self.assertIn(self.cr_a.id, gaps)
        self.assertEqual(
            gaps[self.cr_a.id],
            [(datetime.date(2026, 4, 15), datetime.date(2026, 4, 18)),
             (datetime.date(2026, 4, 29), datetime.date(2026, 4, 30))],
        )

        # CR_B: full window uncovered (this is the key bug fix)
        self.assertIn(self.cr_b.id, gaps)
        self.assertEqual(
            gaps[self.cr_b.id],
            [(datetime.date(2026, 4, 15), datetime.date(2026, 4, 30))],
        )

    def test_fully_covered_classroom_excluded_from_result(self):
        """A classroom whose entire window is covered should not appear."""
        start = datetime.date(2026, 4, 15)
        end = datetime.date(2026, 4, 30)

        inv = self._make_issued_invoice(
            [self.cr_a.id, self.cr_b.id], start, end,
        )

        gaps = svc.find_uncovered_date_ranges_by_classroom(
            [inv], start, end, [self.cr_a.id, self.cr_b.id],
        )
        self.assertEqual(gaps, {})

    def test_no_issued_invoices_returns_full_window_per_class(self):
        """When no invoices have been issued, every classroom's full window is uncovered."""
        start = datetime.date(2026, 4, 15)
        end = datetime.date(2026, 4, 30)

        gaps = svc.find_uncovered_date_ranges_by_classroom(
            [], start, end, [self.cr_a.id, self.cr_b.id],
        )

        self.assertEqual(set(gaps.keys()), {self.cr_a.id, self.cr_b.id})
        for cid in (self.cr_a.id, self.cr_b.id):
            self.assertEqual(gaps[cid], [(start, end)])

    def test_overlapping_invoices_merge_per_classroom(self):
        """Two adjacent invoices for the same classroom merge into one covered range."""
        start = datetime.date(2026, 4, 1)
        end = datetime.date(2026, 4, 30)

        inv1 = self._make_issued_invoice(
            [self.cr_a.id], datetime.date(2026, 4, 1), datetime.date(2026, 4, 15),
        )
        inv2 = self._make_issued_invoice(
            [self.cr_a.id], datetime.date(2026, 4, 16), datetime.date(2026, 4, 25),
        )

        gaps = svc.find_uncovered_date_ranges_by_classroom(
            [inv1, inv2], start, end, [self.cr_a.id],
        )

        # Apr 1-25 fully covered, only Apr 26-30 left
        self.assertEqual(
            gaps[self.cr_a.id],
            [(datetime.date(2026, 4, 26), datetime.date(2026, 4, 30))],
        )


class CalculateInvoiceLinesBillingStartDateTest(TestCase):
    """
    Unit-tests for the ``billing_start_date`` clamp inside
    ``calculate_invoice_lines``.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ctx = _make_school_with_two_classes(name_suffix='_bsd')
        cls.cr_a = cls.ctx['cr_a']
        cls.student = cls.ctx['student']
        cls.school = cls.ctx['school']
        cls.teacher = cls.ctx['teacher']

        # Sessions: Apr 17, Apr 24 (both in window Apr 15-30)
        cls.s1 = _create_completed_session(cls.cr_a, datetime.date(2026, 4, 17), cls.teacher)
        cls.s2 = _create_completed_session(cls.cr_a, datetime.date(2026, 4, 24), cls.teacher)

    def _enroll(self, billing_start=None):
        return ClassStudent.objects.create(
            classroom=self.cr_a, student=self.student, is_active=True,
            billing_start_date=billing_start,
        )

    def test_null_billing_start_date_bills_full_period(self):
        """NULL billing_start_date → backdated case: every session in window is billed."""
        self._enroll(billing_start=None)

        lines, _ = svc.calculate_invoice_lines(
            self.student, self.school,
            datetime.date(2026, 4, 15), datetime.date(2026, 4, 30),
            attendance_mode='all_class_days', billing_type='upfront',
        )

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['sessions_held'], 2)
        self.assertEqual(lines[0]['sessions_charged'], 2)
        self.assertEqual(lines[0]['line_amount'], Decimal('70.00'))

    def test_billing_start_date_skips_earlier_sessions(self):
        """billing_start_date set mid-window → only later sessions billed."""
        self._enroll(billing_start=datetime.date(2026, 4, 20))

        lines, _ = svc.calculate_invoice_lines(
            self.student, self.school,
            datetime.date(2026, 4, 15), datetime.date(2026, 4, 30),
            attendance_mode='all_class_days', billing_type='upfront',
        )

        # Apr 17 skipped, only Apr 24 billed
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['sessions_held'], 1)
        self.assertEqual(lines[0]['line_amount'], Decimal('35.00'))

    def test_billing_start_date_after_period_emits_no_line(self):
        """billing_start_date past the requested window → no line at all."""
        self._enroll(billing_start=datetime.date(2026, 5, 1))

        lines, _ = svc.calculate_invoice_lines(
            self.student, self.school,
            datetime.date(2026, 4, 15), datetime.date(2026, 4, 30),
            attendance_mode='all_class_days', billing_type='upfront',
        )

        self.assertEqual(lines, [])

    def test_restrict_classroom_ids_filters_lines(self):
        """``restrict_classroom_ids`` limits output to those classes only."""
        self._enroll(billing_start=None)
        # Also enroll in CR_B
        cr_b = self.ctx['cr_b']
        ClassStudent.objects.create(
            classroom=cr_b, student=self.student, is_active=True,
        )
        _create_completed_session(cr_b, datetime.date(2026, 4, 18), self.teacher)

        # No restriction → both classes
        lines_all, _ = svc.calculate_invoice_lines(
            self.student, self.school,
            datetime.date(2026, 4, 15), datetime.date(2026, 4, 30),
            attendance_mode='all_class_days', billing_type='upfront',
        )
        classroom_names = {l['classroom'].name for l in lines_all}
        self.assertEqual(classroom_names, {'CR_A', 'CR_B'})

        # Restrict to CR_A only
        lines_a, _ = svc.calculate_invoice_lines(
            self.student, self.school,
            datetime.date(2026, 4, 15), datetime.date(2026, 4, 30),
            attendance_mode='all_class_days', billing_type='upfront',
            restrict_classroom_ids=[self.cr_a.id],
        )
        self.assertEqual({l['classroom'].name for l in lines_a}, {'CR_A'})


# ---------------------------------------------------------------------------
# End-to-end test through GenerateInvoicesView (the Min Htet bug)
# ---------------------------------------------------------------------------

class GapInvoicePerClassroomEndToEndTest(TestCase):
    """
    Reproduces the Min Htet scenario end-to-end:

    - Student enrolled in CR_A from the start.
    - Invoice 1 issued for CR_A covering Apr 19-28 (CR_A line only).
    - Student then added to CR_B; sessions for CR_B exist in Apr 18 + Apr 25.
    - Generate a NEW invoice for Apr 15-30.

    Pre-fix (date-only gap logic): silently dropped CR_B's Apr 25 session
    because Apr 25 ∈ Apr 19-28 was treated as "covered" even though the
    issued invoice never billed CR_B.

    Post-fix: per-classroom coverage means CR_B is uncovered for the full
    Apr 15-30 window, so both CR_B sessions get billed.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ctx = _make_school_with_two_classes(name_suffix='_e2e')
        cls.school = cls.ctx['school']
        cls.admin = cls.ctx['admin']
        cls.teacher = cls.ctx['teacher']
        cls.cr_a = cls.ctx['cr_a']
        cls.cr_b = cls.ctx['cr_b']
        cls.student = cls.ctx['student']

        # Enroll in CR_A from the start
        ClassStudent.objects.create(
            classroom=cls.cr_a, student=cls.student, is_active=True,
        )
        # CR_A sessions: Apr 17 + Apr 24
        _create_completed_session(cls.cr_a, datetime.date(2026, 4, 17), cls.teacher)
        _create_completed_session(cls.cr_a, datetime.date(2026, 4, 24), cls.teacher)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def _issue_invoice_for_cr_a(self):
        """Manually create + issue an invoice covering Apr 19-28 with CR_A only."""
        invoice = Invoice.objects.create(
            invoice_number='INV-CR-A-19-28',
            school=self.school,
            student=self.student,
            billing_period_start=datetime.date(2026, 4, 19),
            billing_period_end=datetime.date(2026, 4, 28),
            attendance_mode='all_class_days',
            billing_type='upfront',
            period_type='custom',
            calculated_amount=Decimal('35.00'),
            amount=Decimal('35.00'),
            status='issued',
            issued_at=timezone.now(),
            created_by=self.admin,
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, classroom=self.cr_a,
            daily_rate=Decimal('35.00'), rate_source='class_default',
            sessions_held=1, sessions_attended=0, sessions_charged=1,
            line_amount=Decimal('35.00'),
        )
        return invoice

    def test_min_htet_scenario_bills_cr_b_in_overlapping_window(self):
        """
        After issuing CR_A invoice for Apr 19-28 then adding student to CR_B,
        the Apr 25 CR_B session must still be billed in the gap invoice.
        """
        self._issue_invoice_for_cr_a()

        # Now add student to CR_B (mid-period) and create CR_B sessions
        # Note: backdated entry, so billing_start_date stays NULL → bill full period
        ClassStudent.objects.create(
            classroom=self.cr_b, student=self.student, is_active=True,
            billing_start_date=None,
        )
        _create_completed_session(self.cr_b, datetime.date(2026, 4, 18), self.teacher)
        _create_completed_session(self.cr_b, datetime.date(2026, 4, 25), self.teacher)

        # Generate fresh invoice for Apr 15-30
        url = reverse('generate_invoices')
        response = self.client.post(url, {
            'billing_period_start': '2026-04-15',
            'billing_period_end': '2026-04-30',
            'attendance_mode': 'all_class_days',
            'billing_type': 'upfront',
        })
        self.assertEqual(response.status_code, 302)

        gap_invoice = Invoice.objects.filter(
            school=self.school, student=self.student, status='draft',
        ).order_by('-id').first()
        self.assertIsNotNone(gap_invoice, 'gap invoice should have been generated')

        # Build a {classroom: line} map
        lines_by_class = {
            li.classroom_id: li for li in gap_invoice.line_items.all()
        }

        # CR_A line: covers only the gap Apr 15-18 + Apr 29-30 → just Apr 17
        self.assertIn(self.cr_a.id, lines_by_class)
        self.assertEqual(lines_by_class[self.cr_a.id].sessions_held, 1)
        self.assertEqual(lines_by_class[self.cr_a.id].line_amount, Decimal('35.00'))

        # CR_B line: full window uncovered → both Apr 18 + Apr 25 billed
        # (this is what was BROKEN pre-fix — CR_B was silently dropped)
        self.assertIn(self.cr_b.id, lines_by_class)
        self.assertEqual(lines_by_class[self.cr_b.id].sessions_held, 2)
        self.assertEqual(lines_by_class[self.cr_b.id].line_amount, Decimal('50.00'))

        # Total: $35 (CR_A Apr 17) + $50 (CR_B Apr 18 + 25) = $85
        self.assertEqual(gap_invoice.calculated_amount, Decimal('85.00'))

    def test_late_starter_on_cr_b_skips_pre_start_sessions(self):
        """
        Same setup, but student is a GENUINE late starter on CR_B
        (billing_start_date = Apr 25). The Apr 18 CR_B session must NOT
        be billed.
        """
        self._issue_invoice_for_cr_a()

        ClassStudent.objects.create(
            classroom=self.cr_b, student=self.student, is_active=True,
            billing_start_date=datetime.date(2026, 4, 25),
        )
        _create_completed_session(self.cr_b, datetime.date(2026, 4, 18), self.teacher)
        _create_completed_session(self.cr_b, datetime.date(2026, 4, 25), self.teacher)

        url = reverse('generate_invoices')
        self.client.post(url, {
            'billing_period_start': '2026-04-15',
            'billing_period_end': '2026-04-30',
            'attendance_mode': 'all_class_days',
            'billing_type': 'upfront',
        })

        gap_invoice = Invoice.objects.filter(
            school=self.school, student=self.student, status='draft',
        ).order_by('-id').first()
        self.assertIsNotNone(gap_invoice)

        lines_by_class = {
            li.classroom_id: li for li in gap_invoice.line_items.all()
        }

        # CR_B: only Apr 25 billed (Apr 18 pre-dates billing_start_date)
        self.assertIn(self.cr_b.id, lines_by_class)
        self.assertEqual(lines_by_class[self.cr_b.id].sessions_held, 1)
        self.assertEqual(lines_by_class[self.cr_b.id].line_amount, Decimal('25.00'))

        # CR_A unchanged: Apr 17 only
        self.assertEqual(lines_by_class[self.cr_a.id].line_amount, Decimal('35.00'))

        # Total: $35 + $25 = $60
        self.assertEqual(gap_invoice.calculated_amount, Decimal('60.00'))

    def test_full_coverage_skips_student(self):
        """
        If every enrolled classroom is fully covered by issued invoices, the
        student should be skipped (no draft generated).
        """
        # Issue invoice covering CR_A for the full window
        invoice = Invoice.objects.create(
            invoice_number='INV-FULL',
            school=self.school, student=self.student,
            billing_period_start=datetime.date(2026, 4, 15),
            billing_period_end=datetime.date(2026, 4, 30),
            attendance_mode='all_class_days',
            billing_type='upfront', period_type='custom',
            calculated_amount=Decimal('70.00'), amount=Decimal('70.00'),
            status='issued', issued_at=timezone.now(),
            created_by=self.admin,
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, classroom=self.cr_a,
            daily_rate=Decimal('35.00'), rate_source='class_default',
            sessions_held=2, sessions_attended=0, sessions_charged=2,
            line_amount=Decimal('70.00'),
        )
        # Student is only enrolled in CR_A in this test (not CR_B)

        url = reverse('generate_invoices')
        self.client.post(url, {
            'billing_period_start': '2026-04-15',
            'billing_period_end': '2026-04-30',
            'attendance_mode': 'all_class_days',
            'billing_type': 'upfront',
        })

        # No new draft for this student
        drafts = Invoice.objects.filter(
            school=self.school, student=self.student, status='draft',
        )
        self.assertEqual(drafts.count(), 0)


# ---------------------------------------------------------------------------
# Sanity: existing find_uncovered_date_ranges still works (regression guard)
# ---------------------------------------------------------------------------

class FindUncoveredDateRangesRegressionTest(TestCase):
    """The original date-only helper is still used elsewhere; make sure it
    still returns the documented gaps."""

    def test_basic_gap(self):
        ctx = _make_school_with_two_classes(name_suffix='_reg')
        invoice = Invoice.objects.create(
            invoice_number='INV-REG',
            school=ctx['school'], student=ctx['student'],
            billing_period_start=datetime.date(2026, 1, 6),
            billing_period_end=datetime.date(2026, 1, 20),
            attendance_mode='all_class_days',
            billing_type='upfront', period_type='custom',
            calculated_amount=Decimal('0'), amount=Decimal('0'),
            status='issued', issued_at=timezone.now(),
            created_by=ctx['admin'],
        )
        gaps = svc.find_uncovered_date_ranges(
            [invoice],
            datetime.date(2026, 1, 1), datetime.date(2026, 1, 31),
        )
        self.assertEqual(
            gaps,
            [(datetime.date(2026, 1, 1), datetime.date(2026, 1, 5)),
             (datetime.date(2026, 1, 21), datetime.date(2026, 1, 31))],
        )
