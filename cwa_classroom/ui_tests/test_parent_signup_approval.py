"""
UI tests for the parent signup & student linking approval flow.

Scenarios:
1. Parent signup form is accessible from the login page footer link
2. Parent signup creates a pending request (no child card yet on dashboard)
3. Teacher sees the pending request on the parent link requests page
4. After teacher approves, parent sees their student on the dashboard
5. After teacher rejects, parent does NOT see a child card
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login, do_logout, TEST_PASSWORD, _make_user, _assign_role

pytestmark = pytest.mark.parent_approval


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def teacher_for_approval(db, school, roles):
    """A teacher belonging to the school fixture."""
    from accounts.models import Role
    from classroom.models import SchoolTeacher

    teacher = _make_user("ui_approval_teacher", Role.TEACHER)
    SchoolTeacher.objects.get_or_create(
        school=school,
        teacher=teacher,
        defaults={"role": "teacher", "is_active": True},
    )
    return teacher


@pytest.fixture
def student_with_id(db, school, roles):
    """A student enrolled in the school with a known student_id_code."""
    from accounts.models import Role
    from classroom.models import SchoolStudent

    student = _make_user("ui_link_student", Role.STUDENT,
                         first_name="Zara", last_name="Smith")
    ss, _ = SchoolStudent.objects.get_or_create(
        school=school, student=student,
    )
    return student, ss


@pytest.fixture
def pending_parent_request(db, school, student_with_id, roles):
    """
    A parent user whose link request is pending (created programmatically,
    bypassing the signup form for speed).
    """
    from accounts.models import Role
    from classroom.models import ParentLinkRequest

    student, ss = student_with_id
    parent = _make_user("ui_pending_parent", Role.PARENT,
                        first_name="Jane", last_name="Doe")
    req = ParentLinkRequest.objects.create(
        parent=parent,
        school_student=ss,
        relationship="mother",
        status=ParentLinkRequest.STATUS_PENDING,
    )
    return parent, req


@pytest.fixture
def approved_parent(db, school, student_with_id, teacher_for_approval, roles):
    """
    A parent whose link request has been approved (ParentStudent link exists).
    """
    from accounts.models import Role
    from classroom.models import ParentLinkRequest, ParentStudent

    student, ss = student_with_id
    parent = _make_user("ui_approved_parent", Role.PARENT,
                        first_name="Maria", last_name="Doe")
    req = ParentLinkRequest.objects.create(
        parent=parent,
        school_student=ss,
        relationship="mother",
        status=ParentLinkRequest.STATUS_APPROVED,
        reviewed_by=teacher_for_approval,
    )
    ParentStudent.objects.create(
        parent=parent,
        student=student,
        school=school,
        relationship="mother",
        is_primary_contact=True,
        created_by=teacher_for_approval,
    )
    return parent


# ---------------------------------------------------------------------------
# 1. Login page has "Join as Parent" link
# ---------------------------------------------------------------------------

class TestLoginPageParentLink:
    """Login page footer must include a Join as Parent link."""

    def test_login_page_has_join_as_parent(self, live_server, page):
        page.goto(f"{live_server.url}/accounts/login/")
        page.wait_for_load_state("domcontentloaded")
        link = page.get_by_role("link", name=re.compile("Join as Parent", re.I))
        expect(link).to_be_visible()

    def test_join_as_parent_link_navigates_to_signup(self, live_server, page):
        page.goto(f"{live_server.url}/accounts/login/")
        page.wait_for_load_state("domcontentloaded")
        page.get_by_role("link", name=re.compile("Join as Parent", re.I)).click()
        page.wait_for_load_state("domcontentloaded")
        expect(page).to_have_url(re.compile(r"/accounts/register/parent-join/"))


# ---------------------------------------------------------------------------
# 2. Join Class page also has "Join as Parent" card
# ---------------------------------------------------------------------------

class TestJoinClassPageParentCard:
    """The public /join/ page must offer a Register as Parent card."""

    def test_join_class_page_has_parent_card(self, live_server, page):
        page.goto(f"{live_server.url}/join/")
        page.wait_for_load_state("domcontentloaded")
        link = page.get_by_role("link", name=re.compile("Join as Parent", re.I))
        expect(link).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Parent signup creates a pending request visible on dashboard
# ---------------------------------------------------------------------------

class TestParentSignupPendingFlow:
    """After signup, parent sees pending request, no child card yet."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, student_with_id):
        self.url = live_server.url
        self.page = page
        self.student, self.ss = student_with_id

    def test_pending_request_shown_on_dashboard_after_signup(self):
        """Fill signup form → redirect to dashboard → pending banner visible."""
        page = self.page
        page.goto(f"{self.url}/accounts/register/parent-join/")
        page.wait_for_load_state("domcontentloaded")

        page.fill("input[name='first_name']", "Jane")
        page.fill("input[name='last_name']", "Doe")
        page.fill("input[name='email']", "ui_signup_parent@test.local")
        page.fill("input[name='password']", TEST_PASSWORD)
        page.fill("input[name='confirm_password']", TEST_PASSWORD)
        page.fill("input[name='student_id_0']", self.ss.student_id_code)
        # The terms checkbox is disabled until scrolled — force-enable and check it
        page.evaluate(
            "const cb = document.getElementById('accept-terms');"
            "cb.removeAttribute('disabled'); cb.checked = true;"
        )

        page.locator("button[type='submit']").click()
        page.wait_for_url(re.compile(r"/parent/"), timeout=10_000)
        page.wait_for_load_state("domcontentloaded")

        # Pending banner must appear
        expect(page.get_by_text(re.compile("Pending", re.I)).first).to_be_visible()

    def test_no_child_card_before_approval(self):
        """Child data card must NOT appear before teacher approves."""
        page = self.page
        page.goto(f"{self.url}/accounts/register/parent-join/")
        page.wait_for_load_state("domcontentloaded")

        page.fill("input[name='first_name']", "Jane")
        page.fill("input[name='last_name']", "Doe")
        page.fill("input[name='email']", "ui_pending_only@test.local")
        page.fill("input[name='password']", TEST_PASSWORD)
        page.fill("input[name='confirm_password']", TEST_PASSWORD)
        page.fill("input[name='student_id_0']", self.ss.student_id_code)
        page.evaluate(
            "const cb = document.getElementById('accept-terms');"
            "cb.removeAttribute('disabled'); cb.checked = true;"
        )

        page.locator("button[type='submit']").click()
        page.wait_for_url(re.compile(r"/parent/"), timeout=10_000)
        page.wait_for_load_state("domcontentloaded")

        # No child card with data-testid
        expect(page.locator('[data-testid="child-card"]')).to_have_count(0)


# ---------------------------------------------------------------------------
# 4. Teacher sees pending requests
# ---------------------------------------------------------------------------

class TestTeacherParentLinkRequestsView:
    """Teacher can view pending parent link requests."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_for_approval, pending_parent_request):
        self.url = live_server.url
        self.page = page
        self.teacher = teacher_for_approval
        self.parent, self.req = pending_parent_request
        do_login(page, self.url, teacher_for_approval)

    def test_page_loads(self):
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page).to_have_url(re.compile(r"/teacher/parent-link-requests/"))

    def test_pending_request_visible(self):
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_text("Jane Doe")).to_be_visible()

    def test_student_name_visible(self):
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_text(re.compile("Zara Smith", re.I))).to_be_visible()

    def test_approve_and_reject_buttons_present(self):
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_role("button", name="Approve")).to_be_visible()
        expect(self.page.get_by_role("button", name="Reject")).to_be_visible()


# ---------------------------------------------------------------------------
# 5. Teacher approves → parent sees student card
# ---------------------------------------------------------------------------

class TestApprovalFlow:
    """End-to-end: teacher approves → parent sees child on dashboard."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_for_approval,
               pending_parent_request, student_with_id):
        self.url = live_server.url
        self.page = page
        self.teacher = teacher_for_approval
        self.parent, self.req = pending_parent_request
        self.student, self.ss = student_with_id

    def test_teacher_approves_request(self):
        """Teacher clicks Approve → request disappears from list."""
        do_login(self.page, self.url, self.teacher)
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")

        self.page.get_by_role("button", name="Approve").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Approved request no longer in pending list
        expect(self.page.get_by_text("Jane Doe")).to_have_count(0)

    def test_parent_sees_child_after_approval(self):
        """After approval, parent dashboard shows child card."""
        # First approve as teacher
        do_login(self.page, self.url, self.teacher)
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Approve").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Now log in as parent
        do_logout(self.page, self.url)
        do_login(self.page, self.url, self.parent)
        self.page.goto(f"{self.url}/parent/")
        self.page.wait_for_load_state("domcontentloaded")

        # Child card must appear
        expect(self.page.locator('[data-testid="child-card"]')).to_have_count(1)
        expect(self.page.locator('[data-testid="child-card"]').get_by_text("Zara Smith")).to_be_visible()


# ---------------------------------------------------------------------------
# 6. Teacher rejects → parent sees no child card
# ---------------------------------------------------------------------------

class TestRejectionFlow:
    """End-to-end: teacher rejects → parent has no child card."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_for_approval,
               pending_parent_request, student_with_id):
        self.url = live_server.url
        self.page = page
        self.teacher = teacher_for_approval
        self.parent, self.req = pending_parent_request
        self.student, self.ss = student_with_id

    def test_teacher_rejects_request(self):
        """Teacher clicks Reject → list clears."""
        do_login(self.page, self.url, self.teacher)
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")

        # Intercept confirm dialog
        self.page.on("dialog", lambda d: d.accept())
        self.page.get_by_role("button", name="Reject").click()
        self.page.wait_for_load_state("domcontentloaded")

        expect(self.page.get_by_text("Jane Doe")).to_have_count(0)

    def test_parent_has_no_child_card_after_rejection(self):
        """After rejection, parent dashboard shows no child card."""
        # Reject as teacher
        do_login(self.page, self.url, self.teacher)
        self.page.goto(f"{self.url}/teacher/parent-link-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.on("dialog", lambda d: d.accept())
        self.page.get_by_role("button", name="Reject").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Log in as parent
        do_logout(self.page, self.url)
        do_login(self.page, self.url, self.parent)
        self.page.goto(f"{self.url}/parent/")
        self.page.wait_for_load_state("domcontentloaded")

        expect(self.page.locator('[data-testid="child-card"]')).to_have_count(0)


# ---------------------------------------------------------------------------
# 7. Approved parent sees student data (verification requirement)
# ---------------------------------------------------------------------------

class TestApprovedParentStudentVisibility:
    """Verification: approved parent can see their student's data on dashboard."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, approved_parent, student_with_id):
        self.url = live_server.url
        self.page = page
        self.parent = approved_parent
        self.student, self.ss = student_with_id
        do_login(page, self.url, approved_parent)
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_child_card_visible(self):
        expect(self.page.locator('[data-testid="child-card"]')).to_have_count(1)

    def test_student_name_in_card(self):
        expect(self.page.locator('[data-testid="child-card"]').get_by_text("Zara Smith")).to_be_visible()

    def test_no_pending_banner(self):
        """No pending banner when all requests are resolved."""
        pending_text = self.page.get_by_text(re.compile("Pending Approval", re.I))
        expect(pending_text).to_have_count(0)
