"""
Playwright UI tests for the Homework module (CPP-74).

Covers:
  - Teacher: sidebar link (single), create form, monitor page
  - Student: sidebar link, homework list page
  - Access control: student blocked from teacher create URL
  - End-to-end flow: teacher creates → student submits → teacher validates
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


# ---------------------------------------------------------------------------
# Extra fixture: homework with HomeworkQuestion records attached
# ---------------------------------------------------------------------------

@pytest.fixture
def homework_with_questions(db, classroom, teacher_user, level, topic, questions):
    """
    A homework assignment that already has HomeworkQuestion rows so a student
    can navigate to the take page and see real MCQ questions.
    """
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="End-to-End Test Homework",
        homework_type="topic",
        num_questions=len(questions),
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    for i, q in enumerate(questions):
        HomeworkQuestion.objects.create(homework=hw, question=q, order=i)
    return hw


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
        page.goto(f"{live_server.url}/homework/monitor/?classroom={classroom.pk}")
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

    # -----------------------------------------------------------------------
    # Sidebar → Monitor → New Homework button flow  (CPP-137)
    # -----------------------------------------------------------------------

    @pytest.mark.django_db(transaction=True)
    def test_sidebar_homework_link_navigates_to_monitor(
        self, page: Page, live_server, teacher_user, classroom
    ):
        """Clicking Homework in the sidebar navigates to /homework/monitor/."""
        do_login(page, live_server.url, teacher_user)
        sidebar = page.locator("aside")
        sidebar.get_by_role("link", name="Homework").first.click()
        page.wait_for_load_state("networkidle")
        assert "/homework/monitor/" in page.url

    @pytest.mark.django_db(transaction=True)
    def test_monitor_shows_new_homework_button_on_load(
        self, page: Page, live_server, teacher_user, classroom
    ):
        """Monitor auto-selects the first class and shows the New Homework button."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/monitor/")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("link", name="+ New Homework")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_new_homework_button_href_points_to_create_form(
        self, page: Page, live_server, teacher_user, classroom
    ):
        """New Homework button href contains /homework/class/<id>/create/."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/monitor/")
        page.wait_for_load_state("networkidle")
        btn = page.get_by_role("link", name="+ New Homework")
        href = btn.get_attribute("href")
        assert href is not None
        assert f"/homework/class/{classroom.pk}/create/" in href

    @pytest.mark.django_db(transaction=True)
    def test_new_homework_button_navigates_to_create_form(
        self, page: Page, live_server, teacher_user, classroom, homework_topic
    ):
        """Clicking New Homework navigates to the create form."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/monitor/")
        page.wait_for_load_state("networkidle")
        page.get_by_role("link", name="+ New Homework").click()
        page.wait_for_load_state("networkidle")
        assert f"/homework/class/{classroom.pk}/create/" in page.url
        expect(page.get_by_role("heading", name="Create Homework")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_monitor_class_dropdown_selection_updates_button_href(
        self, page: Page, live_server, teacher_user, classroom
    ):
        """Selecting a class from the dropdown keeps the New Homework button for that class."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/monitor/")
        page.wait_for_load_state("networkidle")
        # Select the classroom by value in the dropdown
        page.locator("select[name='classroom']").select_option(str(classroom.pk))
        page.wait_for_load_state("networkidle")
        btn = page.get_by_role("link", name="+ New Homework")
        expect(btn).to_be_visible()
        href = btn.get_attribute("href")
        assert f"/homework/class/{classroom.pk}/create/" in href


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


# ===========================================================================
# End-to-End Flow UI Tests
# ===========================================================================

class TestHomeworkCreateFlow:
    """Teacher creates homework through the UI form."""

    @pytest.mark.django_db(transaction=True)
    def test_teacher_creates_homework_and_lands_on_detail(
        self, page: Page, live_server, teacher_user, classroom, topic, questions
    ):
        """
        Teacher fills the create homework form, submits it, and is redirected
        to the detail page showing the new homework title.
        Requires questions in DB for the selected topic so the form does not
        reject the submission with 'No questions found'.
        """
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/")
        page.wait_for_load_state("networkidle")

        # Fill required fields
        page.locator("#id_title").fill("E2E Algebra Sprint 1")
        due = (timezone.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
        page.locator("#id_due_date").fill(due)

        # Tick the topic checkbox
        page.locator(f"input[type='checkbox'][value='{topic.pk}']").check()

        # Set number of questions to 3 (DB has 5)
        page.locator("#id_num_questions").fill("3")

        page.get_by_role("button", name="Create Homework").click()
        page.wait_for_load_state("networkidle")

        # Should redirect to the detail page for the newly created homework
        assert "/homework/" in page.url
        assert "/create/" not in page.url
        expect(page.get_by_role("heading", name="E2E Algebra Sprint 1")).to_be_visible()

        # Detail page shows the student results table columns
        expect(page.get_by_role("columnheader", name="Student")).to_be_visible()
        expect(page.get_by_role("columnheader", name="Best Score")).to_be_visible()


class TestHomeworkStudentSubmitFlow:
    """Student submits homework through the UI."""

    @pytest.mark.django_db(transaction=True)
    def test_student_submits_homework_and_sees_result(
        self, page: Page, live_server, enrolled_student, homework_with_questions
    ):
        """
        Student navigates to homework list, starts the homework, selects an
        answer for every question, submits, and lands on the result page with
        a score and answer review.
        """
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/")
        page.wait_for_load_state("networkidle")

        # Homework appears in the list
        expect(page.get_by_text("End-to-End Test Homework")).to_be_visible()

        # Click Start
        page.get_by_role("link", name="Start").first.click()
        page.wait_for_load_state("networkidle")
        assert "/take/" in page.url

        # Select the first answer option for every question card
        for card in page.locator("div.rounded-2xl.border.shadow-sm").all():
            labels = card.locator(".answer-option label")
            if labels.count() > 0:
                labels.first.click()

        page.get_by_role("button", name="Submit Homework").click()
        page.wait_for_load_state("networkidle")

        # Should land on the result page
        assert "/result/" in page.url
        # Score circle and review are present
        expect(page.get_by_text("End-to-End Test Homework")).to_be_visible()
        expect(page.get_by_text("correct", exact=False)).to_be_visible()
        expect(page.get_by_text("Answer Review")).to_be_visible()


class TestHomeworkTeacherValidatesSubmission:
    """Teacher views the detail page after a student submits homework."""

    @pytest.mark.django_db(transaction=True)
    def test_teacher_sees_student_submission_on_detail_page(
        self, page: Page, live_server, teacher_user, enrolled_student,
        homework_with_questions
    ):
        """
        After a student submits homework, the teacher's detail page shows
        the student's name with a non-Pending status and a visible score.
        """
        from homework.models import HomeworkSubmission

        # Create submission directly — bypasses student UI to keep test focused
        HomeworkSubmission.objects.create(
            homework=homework_with_questions,
            student=enrolled_student,
            attempt_number=1,
            score=4,
            total_questions=5,
            points=80.0,
        )

        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/{homework_with_questions.pk}/")
        page.wait_for_load_state("networkidle")

        # Heading matches the homework
        expect(page.get_by_role("heading", name="End-to-End Test Homework")).to_be_visible()

        # Student row is present
        student_name = enrolled_student.get_full_name() or enrolled_student.username
        expect(page.get_by_text(student_name)).to_be_visible()

        # Score column shows 4/5
        expect(page.get_by_text("4/5")).to_be_visible()

        # Status is not "Pending" — student has submitted
        expect(page.get_by_text("Pending")).not_to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_teacher_full_flow_create_then_validate(
        self, page: Page, live_server, teacher_user, enrolled_student,
        classroom, topic, questions
    ):
        """
        Full end-to-end: teacher creates homework → student submits →
        teacher views detail page and sees submission score.
        """
        from homework.models import Homework, HomeworkQuestion, HomeworkSubmission

        # ── Step 1: Teacher creates homework ──────────────────────────────
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/")
        page.wait_for_load_state("networkidle")

        page.locator("#id_title").fill("Full E2E Homework")
        due = (timezone.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
        page.locator("#id_due_date").fill(due)
        page.locator(f"input[type='checkbox'][value='{topic.pk}']").check()
        page.locator("#id_num_questions").fill("3")
        page.get_by_role("button", name="Create Homework").click()
        page.wait_for_load_state("networkidle")

        # Confirm redirect to detail page
        assert "/homework/" in page.url and "/create/" not in page.url
        expect(page.get_by_role("heading", name="Full E2E Homework")).to_be_visible()

        # Extract the homework id from the URL (e.g. /homework/42/)
        hw_id = int(page.url.rstrip("/").split("/")[-1])
        hw = Homework.objects.get(pk=hw_id)

        # ── Step 2: Student submits (DB shortcut) ─────────────────────────
        HomeworkSubmission.objects.create(
            homework=hw,
            student=enrolled_student,
            attempt_number=1,
            score=3,
            total_questions=3,
            points=75.0,
        )

        # ── Step 3: Teacher refreshes detail page and sees the score ──────
        page.reload()
        page.wait_for_load_state("networkidle")

        student_name = enrolled_student.get_full_name() or enrolled_student.username
        expect(page.get_by_text(student_name)).to_be_visible()
        expect(page.get_by_text("3/3")).to_be_visible()
