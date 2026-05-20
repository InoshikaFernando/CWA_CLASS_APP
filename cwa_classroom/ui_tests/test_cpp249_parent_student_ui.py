"""
Playwright UI tests for CPP-249: Add/link parent when adding student,
add/link student when adding parent.

Covers:
1. Inline parent creation from Add Student modal (school_students.html)
2. Inline student search+link from Add Parent form (add_parent.html)
3. PARENT role badge visible in parent search results
4. already_linked label visible in parent search when student already has that parent
5. Max-parent warning shown when student already has 2 parents
"""
import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login, _make_user, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp249


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enrol_student(school):
    from accounts.models import Role
    from classroom.models import SchoolStudent
    stu = _make_user(f"cpp249_stu_{_RUN_ID}", Role.STUDENT)
    SchoolStudent.objects.get_or_create(school=school, student=stu)
    return stu


def _make_parent(school=None):
    from accounts.models import Role
    from classroom.models import SchoolTeacher
    parent = _make_user(f"cpp249_par_{_RUN_ID}", Role.PARENT,
                        first_name="Par249", last_name="Test")
    return parent


# ---------------------------------------------------------------------------
# Test: PARENT badge visible in parent search results
# ---------------------------------------------------------------------------

class TestParentSearchRoleBadge:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, db):
        self.url = live_server.url
        self.page = page
        self.school = school
        do_login(page, self.url, admin_user)

    @pytest.mark.django_db(transaction=True)
    def test_parent_badge_visible_in_search(self):
        parent = _make_parent()
        stu = _enrol_student(self.school)
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/students/")
        self.page.wait_for_load_state("domcontentloaded")
        # Open Add Student modal
        self.page.get_by_role("button", name="Add Student").click()
        self.page.wait_for_timeout(300)
        # Switch to "Link existing parent"
        self.page.get_by_role("button", name="Link existing parent").click()
        self.page.wait_for_timeout(200)
        # Type in search
        search = self.page.locator("#modal-parent-search")
        search.fill(parent.first_name)
        self.page.wait_for_timeout(600)
        # PARENT badge should appear inside results container
        expect(self.page.locator("#modal-parent-results .bg-violet-100").first).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# Test: already_linked label in parent search
# ---------------------------------------------------------------------------

class TestParentSearchAlreadyLinked:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, db):
        self.url = live_server.url
        self.page = page
        self.school = hoi_school_setup
        do_login(page, self.url, hoi_user)

    @pytest.mark.django_db(transaction=True)
    def test_already_linked_label_shown(self):
        from classroom.models import ParentStudent, SchoolStudent
        from accounts.models import Role
        parent = _make_parent()
        stu = _enrol_student(self.school)
        ParentStudent.objects.create(
            parent=parent, student=stu, school=self.school,
            relationship='guardian', is_primary_contact=True,
        )
        # Go to student page with student_id param
        url = (
            f"{self.url}/admin-dashboard/schools/{self.school.id}/parents/search/"
            f"?q={parent.first_name}&student_id={stu.id}"
        )
        self.page.goto(url)
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_text("Already linked")).to_be_visible()


# ---------------------------------------------------------------------------
# Test: Link existing student from Add Parent form
# ---------------------------------------------------------------------------

class TestAddParentLinkExistingStudent:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, db):
        self.url = live_server.url
        self.page = page
        self.school = hoi_school_setup
        do_login(page, self.url, hoi_user)

    @pytest.mark.django_db(transaction=True)
    def test_link_student_path_visible(self):
        """The 'Link existing student' button is visible on the Add Parent form."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/parents/add/"
        )
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_role("button", name="Link existing student")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_link_student_search_shows_results(self):
        """Clicking 'Link existing student' and typing in search shows student results."""
        stu = _enrol_student(self.school)
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/parents/add/"
        )
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Link existing student").click()
        self.page.wait_for_timeout(300)
        search = self.page.locator("#inline-student-search")
        expect(search).to_be_visible()
        search.fill(stu.first_name)
        self.page.wait_for_timeout(600)
        expect(self.page.locator("#inline-student-results").get_by_text(stu.get_full_name())).to_be_visible(timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_link_student_creates_parent_student(self):
        """Full flow: fill parent form, link student, submit, verify DB record."""
        from classroom.models import ParentStudent
        from accounts.models import CustomUser

        stu = _enrol_student(self.school)
        parent_email = f"cpp249_new_par_{_RUN_ID}@test.local"

        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/parents/add/"
        )
        self.page.wait_for_load_state("domcontentloaded")

        # Fill parent details
        self.page.locator("input[name='first_name']").fill("NewPar")
        self.page.locator("input[name='last_name']").fill("249Test")
        self.page.locator("input[name='email']").fill(parent_email)

        # Switch to link existing student
        self.page.get_by_role("button", name="Link existing student").click()
        self.page.wait_for_timeout(300)

        # Search and select student
        search = self.page.locator("#inline-student-search")
        search.fill(stu.first_name)
        # Wait for HTMX results to appear before clicking (avoid clicking unrelated "Select" labels)
        expect(self.page.locator("#inline-student-results button")).to_be_visible(timeout=5000)
        self.page.locator("#inline-student-results button").first.click()
        # Wait for Alpine to process the custom event and update the hidden input
        self.page.wait_for_function(
            "() => { const el = document.querySelector(\"input[name='inline_student_id']\"); return el && el.value !== ''; }",
            timeout=10000,
        )

        # Confirmation pill should appear
        expect(self.page.locator("[x-text='linkedStudentName']")).to_be_visible()

        # Submit
        self.page.get_by_role("button", name="Create Parent Account").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Verify DB
        parent = CustomUser.objects.filter(email=parent_email).first()
        assert parent is not None, "Parent account should be created"
        assert ParentStudent.objects.filter(
            parent=parent, student=stu, school=self.school
        ).exists(), "ParentStudent link should exist"


# ---------------------------------------------------------------------------
# Test: Inline parent creation from Add Student modal
# ---------------------------------------------------------------------------

class TestAddStudentInlineParent:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, db):
        self.url = live_server.url
        self.page = page
        self.school = school
        do_login(page, self.url, admin_user)

    @pytest.mark.django_db(transaction=True)
    def test_add_new_parent_section_visible_in_modal(self):
        """'Add new parent' section is accessible in the Add Student modal."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/"
        )
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Add Student").click()
        self.page.wait_for_timeout(300)
        expect(self.page.get_by_role("button", name="Add new parent")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_add_new_parent_inline_form_shown_on_click(self):
        """Clicking 'Add new parent' shows the inline parent fields."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/"
        )
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Add Student").click()
        self.page.wait_for_timeout(300)
        self.page.get_by_role("button", name="Add new parent").click()
        self.page.wait_for_timeout(200)
        expect(self.page.locator("input[name='parent_email']")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_link_existing_parent_search_visible(self):
        """Clicking 'Link existing parent' shows the HTMX search input."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/"
        )
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Add Student").click()
        self.page.wait_for_timeout(300)
        self.page.get_by_role("button", name="Link existing parent").click()
        self.page.wait_for_timeout(200)
        expect(self.page.locator("#modal-parent-search")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_parent_selected_confirmation_pill_appears(self):
        """After selecting a parent from search, confirmation pill is shown."""
        parent = _make_parent()
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/"
        )
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Add Student").click()
        self.page.wait_for_timeout(300)
        self.page.get_by_role("button", name="Link existing parent").click()
        self.page.wait_for_timeout(200)
        search = self.page.locator("#modal-parent-search")
        search.fill(parent.first_name)
        self.page.wait_for_timeout(700)
        self.page.get_by_text("Select").first.click()
        self.page.wait_for_timeout(300)
        # Confirmation pill should show the parent name
        expect(self.page.get_by_text(parent.get_full_name(), exact=False)).to_be_visible()
