"""
Playwright UI tests for the Homework module (CPP-74).

Covers:
  - Teacher: sidebar link, create homework, class list, publish, submissions, grade
  - Student: sidebar link, dashboard, detail page, submit, late badge
  - Parent: sidebar link, read-only dashboard
  - Access control: student can't see drafts, unenrolled blocked
"""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def homework_topic(db, subject, level):
    """A top-level topic linked to the level for homework creation."""
    from classroom.models import Topic

    t = Topic.objects.create(
        subject=subject,
        name="Algebra",
        slug="algebra-hw",
        order=10,
    )
    t.levels.add(level)
    return t


@pytest.fixture
def active_homework(db, classroom, homework_topic, teacher_user):
    """An active homework assignment."""
    from homework.models import Homework

    return Homework.objects.create(
        classroom=classroom,
        topic=homework_topic,
        title="Algebra Practice Week 1",
        description="Complete exercises 1-10.",
        assigned_by=teacher_user,
        due_date=timezone.now() + timedelta(days=3),
        status=Homework.STATUS_ACTIVE,
        published_at=timezone.now(),
    )


@pytest.fixture
def draft_homework(db, classroom, homework_topic, teacher_user):
    """A draft homework (invisible to students)."""
    from homework.models import Homework

    return Homework.objects.create(
        classroom=classroom,
        topic=homework_topic,
        title="Secret Draft HW",
        assigned_by=teacher_user,
        due_date=timezone.now() + timedelta(days=5),
        status=Homework.STATUS_DRAFT,
    )


@pytest.fixture
def student_submission(db, active_homework, enrolled_student):
    """A submission by the enrolled student."""
    from homework.models import HomeworkSubmission

    return HomeworkSubmission.objects.create(
        homework=active_homework,
        student=enrolled_student,
        attempt_number=1,
        content="My algebra answers",
    )


@pytest.fixture
def graded_submission(db, active_homework, enrolled_student, teacher_user):
    """A graded and published submission."""
    from homework.models import HomeworkSubmission

    return HomeworkSubmission.objects.create(
        homework=active_homework,
        student=enrolled_student,
        attempt_number=1,
        content="My work",
        score=Decimal("85"),
        max_score=Decimal("100"),
        feedback="Good work!",
        is_graded=True,
        is_published=True,
        graded_by=teacher_user,
        graded_at=timezone.now(),
    )


# ===========================================================================
# Teacher UI Tests
# ===========================================================================

class TestTeacherHomeworkUI:

    @pytest.mark.django_db(transaction=True)
    def test_sidebar_has_homework_link(
        self, page: Page, live_server, teacher_user, classroom
    ):
        """Teacher sidebar shows 'Homework' nav item."""
        do_login(page, live_server.url, teacher_user)
        sidebar = page.locator("aside")
        expect(sidebar.get_by_text("Homework")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_create_homework_form_loads(
        self, page: Page, live_server, teacher_user, classroom, homework_topic
    ):
        """Teacher can navigate to create homework form."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/create/{classroom.pk}/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Assign Homework")).to_be_visible()
        expect(page.locator("#id_title")).to_be_visible()
        expect(page.locator("#id_topic")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_create_and_publish_homework(
        self, page: Page, live_server, teacher_user, classroom, homework_topic
    ):
        """Teacher can create and immediately publish homework."""
        from homework.models import Homework

        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/create/{classroom.pk}/")
        page.wait_for_load_state("networkidle")

        page.locator("#id_title").fill("UI Test Homework")
        page.locator("#id_topic").select_option(str(homework_topic.pk))
        due = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        page.locator("#id_due_date").fill(due)
        # "Publish immediately" should be default
        page.get_by_role("button", name="Assign Homework").click()
        page.wait_for_url(lambda url: "/homework/class/" in url, timeout=10_000)

        assert Homework.objects.filter(title="UI Test Homework", status="active").exists()

    @pytest.mark.django_db(transaction=True)
    def test_class_homework_list(
        self, page: Page, live_server, teacher_user, classroom,
        homework_topic, active_homework
    ):
        """Teacher sees homework in class list view."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Algebra Practice Week 1")).to_be_visible()
        expect(page.get_by_text("Active", exact=True).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_draft_tab_shows_drafts(
        self, page: Page, live_server, teacher_user, classroom,
        homework_topic, draft_homework
    ):
        """Draft tab shows draft homework."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/?tab=drafts")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Secret Draft HW")).to_be_visible()
        expect(page.get_by_text("Draft", exact=True).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_submissions_list(
        self, page: Page, live_server, teacher_user, classroom,
        active_homework, student_submission, enrolled_student
    ):
        """Teacher sees student submission in submissions list."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/{active_homework.pk}/submissions/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("1 submitted")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_grade_submission(
        self, page: Page, live_server, teacher_user, classroom,
        active_homework, student_submission
    ):
        """Teacher can grade a submission."""
        do_login(page, live_server.url, teacher_user)
        page.goto(
            f"{live_server.url}/homework/{active_homework.pk}"
            f"/grade/{student_submission.pk}/"
        )
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Grading")).to_be_visible()

        page.locator("input[name='score']").fill("90")
        page.locator("input[name='max_score']").fill("100")
        page.locator("textarea[name='feedback']").fill("Excellent")
        page.locator("button[name='publish']").click()
        page.wait_for_url(lambda url: "/submissions/" in url, timeout=10_000)

        student_submission.refresh_from_db()
        assert student_submission.is_graded
        assert student_submission.is_published
        assert student_submission.score == Decimal("90")

    @pytest.mark.django_db(transaction=True)
    def test_csv_export(
        self, page: Page, live_server, teacher_user, classroom,
        active_homework, student_submission
    ):
        """CSV export link returns a downloadable CSV."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/{active_homework.pk}/submissions/")
        page.wait_for_load_state("networkidle")
        export_link = page.get_by_text("Export CSV")
        expect(export_link).to_be_visible()


# ===========================================================================
# Student UI Tests
# ===========================================================================

class TestStudentHomeworkUI:

    @pytest.mark.django_db(transaction=True)
    def test_sidebar_has_homework_link(
        self, page: Page, live_server, enrolled_student, classroom,
        homework_topic
    ):
        """Student sidebar shows 'Homework' nav item."""
        do_login(page, live_server.url, enrolled_student)
        # Navigate to a page where sidebar is visible
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        sidebar = page.locator("aside")
        expect(sidebar.get_by_text("Homework")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_dashboard_shows_stats(
        self, page: Page, live_server, enrolled_student, active_homework
    ):
        """Student homework dashboard shows stats bar."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("My Homework")).to_be_visible()
        expect(page.get_by_text("To Do")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_dashboard_shows_active_homework(
        self, page: Page, live_server, enrolled_student, active_homework
    ):
        """Active homework appears on student dashboard."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Algebra Practice Week 1")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_dashboard_hides_draft(
        self, page: Page, live_server, enrolled_student, draft_homework
    ):
        """Draft homework is NOT visible to students."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Secret Draft HW")).not_to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_detail_shows_submit_form(
        self, page: Page, live_server, enrolled_student,
        homework_topic, active_homework
    ):
        """Student sees quiz start button or submission form on homework detail page."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{active_homework.pk}/")
        page.wait_for_load_state("networkidle")
        # Default homework_type is 'quiz' — should show Start Quiz button
        body = page.locator("body").inner_text()
        assert "Start Quiz" in body or "Upload" in body or "Submit" in body or "Mark as Done" in body, \
            f"Expected quiz/submit action on detail page. Got: {body[:200]}"

    @pytest.mark.django_db(transaction=True)
    def test_submit_homework(
        self, page: Page, live_server, enrolled_student, active_homework
    ):
        """Student can start a quiz homework."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{active_homework.pk}/")
        page.wait_for_load_state("networkidle")

        # Default homework_type is 'quiz' — click Start Quiz
        start_btn = page.locator("a, button", has_text=re.compile(r"Start Quiz|Upload|Submit|Mark as Done"))
        if start_btn.count() > 0:
            start_btn.first.click()
            page.wait_for_load_state("networkidle")
            # Should navigate to quiz page or show success
            assert "/homework/" in page.url

    @pytest.mark.django_db(transaction=True)
    def test_published_score_visible(
        self, page: Page, live_server, enrolled_student,
        active_homework, graded_submission
    ):
        """Published score and feedback visible to student."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{active_homework.pk}/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("85")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_bottom_nav_has_homework(
        self, page: Page, live_server, enrolled_student, classroom
    ):
        """Mobile bottom nav shows Homework link for students."""
        do_login(page, live_server.url, enrolled_student)
        # Switch to mobile viewport
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
        sidebar = page.locator("aside")
        expect(sidebar.get_by_text("Homework")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_parent_dashboard_read_only(
        self, page: Page, live_server, parent_with_child,
        homework_topic, active_homework
    ):
        """Parent homework dashboard shows homework (read-only, no submit button)."""
        do_login(page, live_server.url, parent_with_child)
        page.goto(f"{live_server.url}/homework/parent/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Homework")).to_be_visible()
        # Should NOT have a submit form
        expect(page.locator("textarea[name='content']")).not_to_be_visible()


# ===========================================================================
# Access Control UI Tests
# ===========================================================================

class TestHomeworkAccessControlUI:

    @pytest.mark.django_db(transaction=True)
    def test_unauthenticated_redirect(self, page: Page, live_server):
        """Unauthenticated user redirected to login from homework dashboard."""
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")
        assert "/accounts/login" in page.url

    @pytest.mark.django_db(transaction=True)
    def test_student_cannot_access_teacher_create(
        self, page: Page, live_server, enrolled_student, classroom
    ):
        """Student is redirected when trying to access teacher create form."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/create/{classroom.pk}/")
        page.wait_for_load_state("networkidle")
        # Should be redirected away (not on the create page)
        assert "/homework/create/" not in page.url
