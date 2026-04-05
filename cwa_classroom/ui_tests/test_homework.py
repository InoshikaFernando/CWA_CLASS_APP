"""
Playwright UI tests for the Homework module (CPP-74).

Covers:
  - Teacher: sidebar link (single), create form, monitor page
  - Student: sidebar link, homework list page
  - Access control: student blocked from teacher create URL
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def homework_topic(db, subject, level):
    """A top-level topic linked to the level."""
    from classroom.models import Topic

    t = Topic.objects.create(
        subject=subject,
        name="Algebra",
        slug="algebra-hw-ui",
        order=10,
    )
    t.levels.add(level)
    return t


@pytest.fixture
def active_homework(db, classroom, homework_topic, teacher_user):
    """A homework assignment due in 3 days."""
    from homework.models import Homework

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Algebra Practice Week 1",
        homework_type="topic",
        num_questions=5,
        due_date=timezone.now() + timedelta(days=3),
    )
    hw.topics.add(homework_topic)
    return hw


# ===========================================================================
# Teacher UI Tests
# ===========================================================================

class TestTeacherHomeworkUI:

    @pytest.mark.django_db(transaction=True)
    def test_sidebar_has_homework_link(
        self, page: Page, live_server, teacher_user, classroom
    ):
        """Teacher sidebar shows exactly one 'Homework' nav item."""
        do_login(page, live_server.url, teacher_user)
        sidebar = page.locator("aside")
        # Count to ensure there is exactly one link
        links = sidebar.get_by_role("link", name="Homework")
        expect(links.first).to_be_visible()
        assert links.count() == 1, f"Expected 1 Homework link in sidebar, found {links.count()}"

    @pytest.mark.django_db(transaction=True)
    def test_monitor_page_loads(
        self, page: Page, live_server, teacher_user, classroom
    ):
        """Teacher can load the homework monitor page."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/monitor/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Homework Monitor")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_create_homework_form_loads(
        self, page: Page, live_server, teacher_user, classroom, homework_topic
    ):
        """Teacher can navigate to create homework form."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Create Homework")).to_be_visible()
        expect(page.locator("#id_title")).to_be_visible()
        expect(page.locator("#id_due_date")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_create_homework_submit(
        self, page: Page, live_server, teacher_user, classroom, homework_topic
    ):
        """Teacher can submit create homework form and is redirected to monitor."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/")
        page.wait_for_load_state("networkidle")

        page.locator("#id_title").fill("UI Test Homework")
        due = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        page.locator("#id_due_date").fill(due)
        page.get_by_role("button", name="Create Homework").click()
        page.wait_for_load_state("networkidle")
        # After submit, redirected to homework detail
        assert "/homework/" in page.url

    @pytest.mark.django_db(transaction=True)
    def test_monitor_shows_homework_for_class(
        self, page: Page, live_server, teacher_user, classroom, active_homework
    ):
        """Homework card appears on monitor when class is selected."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/monitor/?class_id={classroom.pk}")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Algebra Practice Week 1")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_homework_detail_page_loads(
        self, page: Page, live_server, teacher_user, classroom, active_homework
    ):
        """Teacher can view homework detail page."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/{active_homework.pk}/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Algebra Practice Week 1")).to_be_visible()


# ===========================================================================
# Student UI Tests
# ===========================================================================

class TestStudentHomeworkUI:

    @pytest.mark.django_db(transaction=True)
    def test_sidebar_has_homework_link(
        self, page: Page, live_server, enrolled_student, classroom
    ):
        """Student sidebar shows 'Homework' nav item."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        sidebar = page.locator("aside")
        expect(sidebar.get_by_role("link", name="Homework").first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_list_page_loads(
        self, page: Page, live_server, enrolled_student
    ):
        """Student homework list page loads with correct heading."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="My Homework")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_list_shows_assigned_homework(
        self, page: Page, live_server, enrolled_student, active_homework
    ):
        """Assigned homework appears on student list."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Algebra Practice Week 1")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_bottom_nav_has_homework(
        self, page: Page, live_server, enrolled_student, classroom
    ):
        """Mobile bottom nav shows Homework link for students."""
        do_login(page, live_server.url, enrolled_student)
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        bottom_nav = page.locator("nav.fixed.bottom-0")
        expect(bottom_nav.get_by_text("Homework")).to_be_visible()


# ===========================================================================
# Parent UI Tests
# ===========================================================================

class TestParentHomeworkUI:

    @pytest.mark.django_db(transaction=True)
    def test_sidebar_has_homework_link(
        self, page: Page, live_server, parent_with_child
    ):
        """Parent sidebar shows 'Homework' nav item."""
        do_login(page, live_server.url, parent_with_child)
        page.goto(f"{live_server.url}/parent/")
        page.wait_for_load_state("networkidle")
        sidebar = page.locator("aside")
        expect(sidebar.get_by_role("link", name="Homework").first).to_be_visible()


# ===========================================================================
# Access Control UI Tests
# ===========================================================================

class TestHomeworkAccessControlUI:

    @pytest.mark.django_db(transaction=True)
    def test_unauthenticated_redirect(self, page: Page, live_server):
        """Unauthenticated user redirected to login from homework list."""
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        assert "/accounts/login" in page.url

    @pytest.mark.django_db(transaction=True)
    def test_student_cannot_access_teacher_create(
        self, page: Page, live_server, enrolled_student, classroom
    ):
        """Student is redirected when trying to access teacher create form."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/")
        page.wait_for_load_state("networkidle")
        # Should be redirected away (not on the create page)
        assert f"/homework/class/{classroom.pk}/create/" not in page.url
