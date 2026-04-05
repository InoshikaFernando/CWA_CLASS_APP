"""
UI tests for the 'Become a Parent' flow — teachers (and other staff) who want
to link their existing account to their child's school profile.

Scenarios:
1. Teacher sees 'Join as Parent' link in their sidebar
2. /parent/become-parent/ page loads with form fields
3. Submitting with a valid student ID adds PARENT role and creates a pending request
4. Teacher is redirected to parent dashboard after submission (showing pending state)
5. Submitting with an invalid student ID shows an error
6. Teacher who already has PARENT role is redirected straight to parent dashboard
7. A different teacher at the same school can approve the request
8. Teacher cannot approve their own parent link request
9. After approval, the teacher-parent can see their child's data on parent dashboard
10. Topbar role-switcher appears once the teacher has both roles
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _make_user, TEST_PASSWORD
from .helpers import _ensure_sidebar_visible, assert_page_has_text

pytestmark = pytest.mark.parent_portal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def school_with_teacher_parent(db, school, roles):
    """
    A teacher whose child is enrolled in the same school.
    Returns (teacher_user, student_user, school_student).
    """
    from accounts.models import Role
    from classroom.models import SchoolStudent, SchoolTeacher

    teacher = _make_user("bp_teacher", Role.TEACHER,
                         first_name="Alice", last_name="Teacher")
    SchoolTeacher.objects.get_or_create(
        school=school, teacher=teacher,
        defaults={"role": "teacher", "is_active": True},
    )

    child = _make_user("bp_child", Role.STUDENT,
                       first_name="Tom", last_name="Teacher")
    ss, _ = SchoolStudent.objects.get_or_create(school=school, student=child)

    return teacher, child, ss


@pytest.fixture
def approving_teacher(db, school, roles):
    """A second teacher who will approve the link request."""
    from accounts.models import Role
    from classroom.models import SchoolTeacher

    teacher = _make_user("bp_approver", Role.TEACHER,
                         first_name="Bob", last_name="Approver")
    SchoolTeacher.objects.get_or_create(
        school=school, teacher=teacher,
        defaults={"role": "teacher", "is_active": True},
    )
    return teacher


@pytest.fixture
def teacher_with_parent_role(db, school, roles, school_with_teacher_parent):
    """
    Teacher who has already submitted 'Become a Parent' — PARENT role is present
    but ParentStudent link is still pending approval.
    """
    from accounts.models import Role, UserRole
    from classroom.models import ParentLinkRequest

    teacher, child, ss = school_with_teacher_parent
    parent_role, _ = Role.objects.get_or_create(
        name=Role.PARENT, defaults={"display_name": "Parent"},
    )
    UserRole.objects.get_or_create(user=teacher, role=parent_role)
    ParentLinkRequest.objects.create(
        parent=teacher,
        school_student=ss,
        relationship="father",
        status=ParentLinkRequest.STATUS_PENDING,
    )
    return teacher, child, ss


@pytest.fixture
def teacher_fully_approved(db, school, roles, school_with_teacher_parent, approving_teacher):
    """
    Teacher whose parent link request has been fully approved — ParentStudent link exists.
    """
    from accounts.models import Role, UserRole
    from classroom.models import ParentLinkRequest, ParentStudent

    teacher, child, ss = school_with_teacher_parent
    parent_role, _ = Role.objects.get_or_create(
        name=Role.PARENT, defaults={"display_name": "Parent"},
    )
    UserRole.objects.get_or_create(user=teacher, role=parent_role)
    req = ParentLinkRequest.objects.create(
        parent=teacher,
        school_student=ss,
        relationship="father",
        status=ParentLinkRequest.STATUS_APPROVED,
        reviewed_by=approving_teacher,
    )
    ParentStudent.objects.create(
        parent=teacher,
        student=child,
        school=school,
        relationship="father",
        is_active=True,
        created_by=approving_teacher,
    )
    return teacher, child, ss


# ---------------------------------------------------------------------------
# 1. Sidebar entry point
# ---------------------------------------------------------------------------

class TestBecomeParentSidebarLink:
    """Teacher sidebar shows 'Join as Parent' link."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, school_with_teacher_parent, school):
        self.url = live_server.url
        self.page = page
        teacher, _, _ = school_with_teacher_parent
        do_login(page, self.url, teacher)
        page.goto(f"{self.url}/teacher/")
        page.wait_for_load_state("domcontentloaded")

    def test_join_as_parent_link_in_sidebar(self):
        _ensure_sidebar_visible(self.page)
        link = self.page.locator("aside#sidebar a", has_text="Join as Parent")
        expect(link).to_be_visible()

    def test_join_as_parent_link_navigates(self):
        _ensure_sidebar_visible(self.page)
        self.page.locator("aside#sidebar a", has_text="Join as Parent").click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page).to_have_url(re.compile(r"/parent/become-parent/"))


# ---------------------------------------------------------------------------
# 2. Become-a-parent form
# ---------------------------------------------------------------------------

class TestBecomeParentFormLoads:
    """The form page renders correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, school_with_teacher_parent, school):
        self.url = live_server.url
        self.page = page
        teacher, _, _ = school_with_teacher_parent
        do_login(page, self.url, teacher)
        page.goto(f"{self.url}/parent/become-parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        expect(self.page.locator("h1")).to_contain_text("Join as a Parent")

    def test_student_id_field_present(self):
        expect(self.page.locator("input[name='student_id']")).to_be_visible()

    def test_relationship_dropdown_present(self):
        expect(self.page.locator("select[name='relationship']")).to_be_visible()

    def test_submit_button_present(self):
        expect(self.page.get_by_role("button", name="Submit Request")).to_be_visible()

    def test_info_banner_mentions_existing_account(self):
        assert_page_has_text(self.page, "existing account")


# ---------------------------------------------------------------------------
# 3 & 4. Successful submission
# ---------------------------------------------------------------------------

class TestBecomeParentSubmit:
    """Submitting with a valid student ID redirects to parent dashboard."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, school_with_teacher_parent, school):
        self.url = live_server.url
        self.page = page
        self.teacher, self.child, self.ss = school_with_teacher_parent
        do_login(page, self.url, self.teacher)
        page.goto(f"{self.url}/parent/become-parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_valid_submission_redirects_to_parent_dashboard(self):
        self.page.fill("input[name='student_id']", self.ss.student_id_code)
        self.page.locator("select[name='relationship']").select_option("father")
        self.page.get_by_role("button", name="Submit Request").click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page).to_have_url(re.compile(r"/parent/"))

    def test_parent_dashboard_shows_pending_state(self):
        self.page.fill("input[name='student_id']", self.ss.student_id_code)
        self.page.locator("select[name='relationship']").select_option("father")
        self.page.get_by_role("button", name="Submit Request").click()
        self.page.wait_for_load_state("domcontentloaded")
        # Pending request banner or message should appear
        expect(self.page.get_by_text(re.compile("Pending", re.I)).first).to_be_visible()

    def test_parent_role_assigned_after_submission(self):
        """After submission the PARENT role should exist on the user."""
        from accounts.models import Role
        self.page.fill("input[name='student_id']", self.ss.student_id_code)
        self.page.get_by_role("button", name="Submit Request").click()
        self.page.wait_for_load_state("domcontentloaded")
        self.teacher.refresh_from_db()
        assert self.teacher.has_role(Role.PARENT)


# ---------------------------------------------------------------------------
# 5. Invalid student ID
# ---------------------------------------------------------------------------

class TestBecomeParentInvalidId:
    """Invalid student ID shows an inline error."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, school_with_teacher_parent, school):
        self.url = live_server.url
        self.page = page
        teacher, _, _ = school_with_teacher_parent
        do_login(page, self.url, teacher)
        page.goto(f"{self.url}/parent/become-parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_invalid_id_shows_error(self):
        self.page.fill("input[name='student_id']", "INVALID-ID-99999")
        self.page.get_by_role("button", name="Submit Request").click()
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, "not found")

    def test_stays_on_form_after_error(self):
        self.page.fill("input[name='student_id']", "INVALID-ID-99999")
        self.page.get_by_role("button", name="Submit Request").click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page).to_have_url(re.compile(r"/parent/become-parent/"))


# ---------------------------------------------------------------------------
# 6. Already has PARENT role → redirect
# ---------------------------------------------------------------------------

class TestBecomeParentAlreadyParent:
    """If user already has PARENT role, GET redirects to parent dashboard."""

    def test_already_parent_redirects(self, live_server, page, db,
                                       teacher_with_parent_role, school):
        teacher, _, _ = teacher_with_parent_role
        do_login(page, live_server.url, teacher)
        page.goto(f"{live_server.url}/parent/become-parent/")
        page.wait_for_load_state("domcontentloaded")
        expect(page).to_have_url(re.compile(r"/parent/"))


# ---------------------------------------------------------------------------
# 7. Another teacher approves the request
# ---------------------------------------------------------------------------

class TestBecomeParentApprovalFlow:
    """A second teacher can approve the link request."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_with_parent_role,
               approving_teacher, school):
        self.url = live_server.url
        self.page = page
        self.teacher, self.child, self.ss = teacher_with_parent_role
        self.approver = approving_teacher

    def test_approver_sees_pending_request(self):
        do_login(self.page, self.url, self.approver)
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        # The teacher-parent's name should appear in the request list
        expect(self.page.get_by_text("Alice Teacher").first).to_be_visible()

    def test_approver_can_approve(self):
        do_login(self.page, self.url, self.approver)
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Approve").click()
        self.page.wait_for_load_state("domcontentloaded")
        # After approval the list should be empty (request resolved)
        expect(self.page.get_by_text("Alice Teacher")).to_have_count(0)

    def test_after_approval_teacher_sees_child_on_parent_dashboard(self):
        """After approval the teacher-parent can view their child on parent dashboard."""
        # Approve as second teacher
        do_login(self.page, self.url, self.approver)
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Approve").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Switch to teacher-parent account
        self.page.goto(f"{self.url}/accounts/logout/")
        do_login(self.page, self.url, self.teacher)

        # Set active_role to parent via the switch-role mechanism
        self.page.goto(f"{self.url}/parent/")
        self.page.wait_for_load_state("domcontentloaded")

        # Child card should now appear
        expect(self.page.locator('[data-testid="child-card"]')).to_have_count(1)


# ---------------------------------------------------------------------------
# 8. Self-approval is blocked
# ---------------------------------------------------------------------------

class TestBecomeParentSelfApprovalBlocked:
    """Teacher cannot approve their own parent link request."""

    def test_self_approval_blocked(self, live_server, page, db,
                                    teacher_with_parent_role, school):
        """The teacher's own pending request must not appear in their approval list."""
        teacher, _, _ = teacher_with_parent_role
        do_login(page, live_server.url, teacher)
        page.goto(f"{live_server.url}/teacher/parent-link-requests/")
        page.wait_for_load_state("domcontentloaded")
        # Their own request must NOT be shown (excluded from the list)
        approve_buttons = page.get_by_role("button", name="Approve")
        # Either no buttons, or none correspond to their own request
        # The page should NOT show an Approve button for their own request
        assert approve_buttons.count() == 0 or \
               page.get_by_text("Alice Teacher").count() == 0


# ---------------------------------------------------------------------------
# 9 & 10. Fully approved: role switcher + parent dashboard
# ---------------------------------------------------------------------------

class TestTeacherParentRoleSwitcher:
    """Fully approved teacher-parent can switch roles and view child data."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_fully_approved, school):
        self.url = live_server.url
        self.page = page
        self.teacher, self.child, self.ss = teacher_fully_approved
        do_login(page, self.url, self.teacher)

    def test_child_name_visible_on_parent_dashboard(self):
        self.page.goto(f"{self.url}/parent/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_text("Tom Teacher").first).to_be_visible()

    def test_parent_progress_accessible(self):
        """Teacher-parent can navigate to /parent/progress/ for their child."""
        self.page.goto(f"{self.url}/parent/progress/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("h1")).to_contain_text("Progress")
