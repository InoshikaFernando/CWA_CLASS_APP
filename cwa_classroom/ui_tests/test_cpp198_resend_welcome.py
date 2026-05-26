"""
Playwright UI tests for CPP-198: HoI manual re-send welcome email.

UI1  Welcome status badge visible on staff dashboard (sent / not-sent)
UI2  'Resend Welcome' button visible in expanded teacher row
UI3  Clicking button opens confirmation modal with correct user info
UI4  Modal shows 'new temporary password' info for institute account
UI5  Modal shows self-registered info for self-registered account
UI6  Confirming modal redirects back to teachers page with success message
UI7  Student dashboard shows welcome status badge + resend button
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import _RUN_ID, do_login, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def resend_school(db, admin_user):
    """School with HoI admin and active subscription."""
    from decimal import Decimal
    from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
    from classroom.models import School

    school = School.objects.create(
        name=f"Resend Test School {_RUN_ID}",
        slug=f"resend-school-{_RUN_ID}",
        admin=admin_user,
        is_active=True,
    )
    plan, _ = InstitutePlan.objects.get_or_create(
        slug=f"resend-plan-{_RUN_ID}",
        defaults={
            "name": f"Resend Plan {_RUN_ID}",
            "price": Decimal("89.00"),
            "stripe_price_id": "price_test",
            "class_limit": 50,
            "student_limit": 500,
            "invoice_limit_yearly": 500,
            "extra_invoice_rate": Decimal("0.30"),
        },
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status="active")
    for module_key, _ in ModuleSubscription.MODULE_CHOICES:
        ModuleSubscription.objects.create(school_subscription=sub, module=module_key, is_active=True)
    return school


@pytest.fixture
def hoi_admin(db, roles, resend_school):
    """HoI who is the school admin (school.admin = this user)."""
    return resend_school.admin


@pytest.fixture
def institute_teacher(db, roles, resend_school):
    """Institute-created teacher at the school with no welcome email sent."""
    from accounts.models import CustomUser, Role, UserRole
    from classroom.models import SchoolTeacher

    user = CustomUser.objects.create_user(
        username=f"inst_tch_{_RUN_ID}",
        password=TEST_PASSWORD,
        email=f"inst_tch_{_RUN_ID}@test.local",
        first_name="Institute",
        last_name="Teacher",
        creation_method="institute",
        welcome_email_sent=None,
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(
        name=Role.TEACHER, defaults={"display_name": "Teacher"}
    )
    UserRole.objects.create(user=user, role=role)
    SchoolTeacher.objects.create(
        school=resend_school, teacher=user, role="teacher", is_active=True,
    )
    return user


@pytest.fixture
def self_reg_teacher(db, roles, resend_school):
    """Self-registered teacher at the school."""
    from accounts.models import CustomUser, Role, UserRole
    from classroom.models import SchoolTeacher
    from django.utils import timezone

    user = CustomUser.objects.create_user(
        username=f"self_tch_{_RUN_ID}",
        password=TEST_PASSWORD,
        email=f"self_tch_{_RUN_ID}@test.local",
        first_name="Self",
        last_name="Registered",
        creation_method="self_registered",
        welcome_email_sent=timezone.now(),
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(
        name=Role.TEACHER, defaults={"display_name": "Teacher"}
    )
    UserRole.objects.create(user=user, role=role)
    SchoolTeacher.objects.create(
        school=resend_school, teacher=user, role="teacher", is_active=True,
    )
    return user


@pytest.fixture
def institute_student(db, roles, resend_school):
    """Institute-created student at the school."""
    from accounts.models import CustomUser, Role, UserRole
    from classroom.models import SchoolStudent

    user = CustomUser.objects.create_user(
        username=f"inst_stu_{_RUN_ID}",
        password=TEST_PASSWORD,
        email=f"inst_stu_{_RUN_ID}@test.local",
        first_name="Institute",
        last_name="Student",
        creation_method="institute",
        welcome_email_sent=None,
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT, defaults={"display_name": "Student"}
    )
    UserRole.objects.create(user=user, role=role)
    SchoolStudent.objects.create(school=resend_school, student=user, is_active=True)
    return user


def _teachers_url(live_server, school):
    return f"{live_server.url}/admin-dashboard/schools/{school.id}/teachers/"


def _students_url(live_server, school):
    return f"{live_server.url}/admin-dashboard/schools/{school.id}/students/"


# ---------------------------------------------------------------------------
# UI1: Welcome status badge visible in teacher list
# ---------------------------------------------------------------------------

class TestWelcomeStatusBadge:

    def test_not_sent_badge_visible_for_institute_teacher(
        self, page: Page, live_server, hoi_admin, resend_school, institute_teacher,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_teachers_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")
        expect(page.locator("text=Welcome not sent").first).to_be_visible()

    def test_sent_badge_visible_for_self_reg_teacher(
        self, page: Page, live_server, hoi_admin, resend_school, self_reg_teacher,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_teachers_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")
        expect(page.locator("text=Welcome sent").first).to_be_visible()


# ---------------------------------------------------------------------------
# UI2: Resend Welcome button visible in expanded teacher row
# ---------------------------------------------------------------------------

class TestResendButtonVisible:

    def test_resend_welcome_button_visible_after_expand(
        self, page: Page, live_server, hoi_admin, resend_school, institute_teacher,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_teachers_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")

        # Click the teacher row to expand it
        page.locator(f"text={institute_teacher.get_full_name()}").first.click()
        page.wait_for_timeout(300)

        expect(page.locator("button:has-text('Resend Welcome')").first).to_be_visible()


# ---------------------------------------------------------------------------
# UI3: Clicking Resend Welcome opens modal with correct user info
# ---------------------------------------------------------------------------

class TestResendWelcomeModal:

    def test_modal_opens_with_user_name(
        self, page: Page, live_server, hoi_admin, resend_school, institute_teacher,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_teachers_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")

        page.locator(f"text={institute_teacher.get_full_name()}").first.click()
        page.wait_for_timeout(300)
        page.locator("button:has-text('Resend Welcome')").first.click()
        page.wait_for_timeout(500)

        expect(page.locator("text=Resend Welcome Email").first).to_be_visible()
        expect(page.locator(f"text={institute_teacher.get_full_name()}").first).to_be_visible()

    # UI4: Modal shows new-password info for institute account
    def test_modal_shows_new_password_info_for_institute(
        self, page: Page, live_server, hoi_admin, resend_school, institute_teacher,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_teachers_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")

        page.locator(f"text={institute_teacher.get_full_name()}").first.click()
        page.wait_for_timeout(300)
        page.locator("button:has-text('Resend Welcome')").first.click()
        page.wait_for_timeout(500)

        expect(page.locator("text=new temporary password").first).to_be_visible()

    # UI5: Modal shows self-registered info for self-registered account
    def test_modal_shows_self_registered_info(
        self, page: Page, live_server, hoi_admin, resend_school, self_reg_teacher,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_teachers_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")

        page.locator(f"text={self_reg_teacher.get_full_name()}").first.click()
        page.wait_for_timeout(300)
        page.locator("button:has-text('Resend Welcome')").first.click()
        page.wait_for_timeout(500)

        expect(page.locator("text=self-registered").first).to_be_visible()

    def test_modal_cancel_closes_modal(
        self, page: Page, live_server, hoi_admin, resend_school, institute_teacher,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_teachers_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")

        page.locator(f"text={institute_teacher.get_full_name()}").first.click()
        page.wait_for_timeout(300)
        page.locator("button:has-text('Resend Welcome')").first.click()
        page.wait_for_timeout(500)

        page.locator("#staff-edit-modal-content button:has-text('Cancel')").first.click()
        page.wait_for_timeout(300)

        expect(page.locator("h2:has-text('Resend Welcome Email')").first).not_to_be_visible()


# ---------------------------------------------------------------------------
# UI6: Confirming modal submits and shows success message
# ---------------------------------------------------------------------------

class TestResendWelcomeSubmit:

    def test_submit_shows_success_message(
        self, page: Page, live_server, hoi_admin, resend_school, institute_teacher,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_teachers_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")

        page.locator(f"text={institute_teacher.get_full_name()}").first.click()
        page.wait_for_timeout(300)
        page.locator("button:has-text('Resend Welcome')").first.click()
        page.wait_for_timeout(500)

        # Submit the modal form
        page.locator("button[type='submit']:has-text('Resend Welcome Email')").click()
        page.wait_for_load_state("networkidle")

        # Toast message (success or warning) should appear
        expect(page.locator(".toast-item").first).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# UI7: Student dashboard shows welcome status badge + resend button
# ---------------------------------------------------------------------------

class TestStudentDashboardResend:

    def test_student_welcome_not_sent_badge_visible(
        self, page: Page, live_server, hoi_admin, resend_school, institute_student,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_students_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")

        expect(page.locator("text=Welcome not sent").first).to_be_visible()

    def test_student_resend_button_visible_after_expand(
        self, page: Page, live_server, hoi_admin, resend_school, institute_student,
    ):
        do_login(page, live_server.url, hoi_admin)
        page.goto(_students_url(live_server, resend_school))
        page.wait_for_load_state("networkidle")

        page.locator(f"text={institute_student.get_full_name()}").first.click()
        page.wait_for_timeout(300)

        expect(page.locator("button:has-text('Resend Welcome')").first).to_be_visible()
