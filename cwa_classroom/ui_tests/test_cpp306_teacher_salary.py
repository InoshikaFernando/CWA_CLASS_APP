"""
Playwright UI tests for CPP-306: Teacher self-service salary slip view.

Covers:
1. "My Salary Slips" link appears in teacher sidebar
2. List page loads and shows slip row
3. Detail page loads with line items and payment history
4. Print page loads and contains slip number
5. Cross-teacher access returns 403
"""
import uuid
from decimal import Decimal
from datetime import date

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp306


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid():
    return uuid.uuid4().hex[:6]


def _make_salary_slip(teacher, school, status='issued'):
    from classroom.models import SalarySlip
    u = _uid()
    return SalarySlip.objects.create(
        teacher=teacher,
        school=school,
        slip_number=f'SS-UI-{u}',
        billing_period_start=date(2025, 1, 1),
        billing_period_end=date(2025, 1, 31),
        amount=Decimal('500.00'),
        calculated_amount=Decimal('500.00'),
        status=status,
    )


def _make_line_item(slip):
    from classroom.models import SalarySlipLineItem, ClassRoom, Department
    school = slip.school
    dept = Department.objects.create(school=school, name=f'Dept {_uid()}')
    room = ClassRoom.objects.create(
        name=f'Room {_uid()}', code=_uid(), school=school, department=dept
    )
    return SalarySlipLineItem.objects.create(
        salary_slip=slip,
        classroom=room,
        department=dept,
        hourly_rate=Decimal('25.00'),
        rate_source='default',
        sessions_taught=4,
        hours_per_session=Decimal('2.0'),
        total_hours=Decimal('8.0'),
        line_amount=Decimal('200.00'),
    )


def _make_payment(slip):
    from classroom.models import SalaryPayment
    return SalaryPayment.objects.create(
        salary_slip=slip,
        teacher=slip.teacher,
        school=slip.school,
        amount=Decimal('250.00'),
        payment_date=date(2025, 2, 1),
        payment_method='bank_transfer',
        status='confirmed',
    )


def _list_url(live_server_url):
    return f"{live_server_url}{reverse('teacher_salary_slip_list')}"


def _detail_url(live_server_url, slip_id):
    return f"{live_server_url}{reverse('teacher_salary_slip_detail', args=[slip_id])}"


def _print_url(live_server_url, slip_id):
    return f"{live_server_url}{reverse('teacher_salary_slip_print', args=[slip_id])}"


# ---------------------------------------------------------------------------
# Test: Sidebar link visible for teacher
# ---------------------------------------------------------------------------

class TestSidebarLink:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, db):
        from classroom.models import SchoolTeacher
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=teacher_user, defaults={'is_active': True}
        )
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_my_salary_slips_link_in_sidebar(self):
        self.page.goto(_list_url(self.url))
        self.page.wait_for_load_state("domcontentloaded")
        # Sidebar uses hidden md:flex — check the link is in the DOM (not just visible)
        expect(
            self.page.locator("a[href='/teacher/salary/']").first
        ).to_be_attached()


# ---------------------------------------------------------------------------
# Test: List page shows slip
# ---------------------------------------------------------------------------

class TestListPage:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, db):
        from classroom.models import SchoolTeacher
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=teacher_user, defaults={'is_active': True}
        )
        self.url = live_server.url
        self.page = page
        self.slip = _make_salary_slip(teacher_user, school, status='issued')
        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_list_page_loads(self):
        self.page.goto(_list_url(self.url))
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("h1:has-text('My Salary Slips')")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_list_page_shows_slip_row(self):
        self.page.goto(_list_url(self.url))
        self.page.wait_for_load_state("domcontentloaded")
        expect(
            self.page.locator(f"text={self.slip.slip_number}").first
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_list_view_link_navigates_to_detail(self):
        self.page.goto(_list_url(self.url))
        self.page.wait_for_load_state("domcontentloaded")
        self.page.locator("a:has-text('View')").first.click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator(f"text={self.slip.slip_number}").first).to_be_visible()


# ---------------------------------------------------------------------------
# Test: Detail page
# ---------------------------------------------------------------------------

class TestDetailPage:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, db):
        from classroom.models import SchoolTeacher
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=teacher_user, defaults={'is_active': True}
        )
        self.url = live_server.url
        self.page = page
        self.slip = _make_salary_slip(teacher_user, school, status='issued')
        _make_line_item(self.slip)
        _make_payment(self.slip)
        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_detail_page_loads(self):
        self.page.goto(_detail_url(self.url, self.slip.id))
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator(f"text={self.slip.slip_number}").first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_detail_shows_line_items_section(self):
        self.page.goto(_detail_url(self.url, self.slip.id))
        self.page.wait_for_load_state("domcontentloaded")
        expect(
            self.page.locator("h2:has-text('Breakdown by Class')").first
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_detail_shows_payment_history_section(self):
        self.page.goto(_detail_url(self.url, self.slip.id))
        self.page.wait_for_load_state("domcontentloaded")
        expect(
            self.page.locator("h2:has-text('Payment History')").first
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_detail_print_button_present(self):
        self.page.goto(_detail_url(self.url, self.slip.id))
        self.page.wait_for_load_state("domcontentloaded")
        expect(
            self.page.locator("a:has-text('Print')").first
        ).to_be_visible()


# ---------------------------------------------------------------------------
# Test: Print page
# ---------------------------------------------------------------------------

class TestPrintPage:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, db):
        from classroom.models import SchoolTeacher
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=teacher_user, defaults={'is_active': True}
        )
        self.url = live_server.url
        self.page = page
        self.slip = _make_salary_slip(teacher_user, school, status='issued')
        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_print_page_loads_with_slip_number(self):
        self.page.goto(_print_url(self.url, self.slip.id))
        self.page.wait_for_load_state("domcontentloaded")
        expect(
            self.page.locator(f"text={self.slip.slip_number}").first
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_print_page_has_print_button(self):
        self.page.goto(_print_url(self.url, self.slip.id))
        self.page.wait_for_load_state("domcontentloaded")
        expect(
            self.page.locator("button:has-text('Print')").first
        ).to_be_visible()


# ---------------------------------------------------------------------------
# Test: Cross-teacher access blocked
# ---------------------------------------------------------------------------

class TestCrossTeacherAccess:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, db):
        from classroom.models import SchoolTeacher
        from accounts.models import Role
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=teacher_user, defaults={'is_active': True}
        )
        self.url = live_server.url
        self.page = page

        # Create a second teacher who owns the slip
        from .conftest import _make_user
        other = _make_user('ui_other_teacher', Role.TEACHER)
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=other, defaults={'is_active': True}
        )
        self.other_slip = _make_salary_slip(other, school, status='issued')

        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_cross_teacher_detail_returns_403(self):
        with self.page.expect_response(
            lambda r: _detail_url(self.url, self.other_slip.id) in r.url
        ) as resp_info:
            self.page.goto(_detail_url(self.url, self.other_slip.id))
        assert resp_info.value.status == 403
