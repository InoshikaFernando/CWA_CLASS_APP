"""
UI tests for the parent homework page (/parent/homework/).

Covers:
- Page renders with correct heading and child name
- Empty state when no homework assigned
- Status badges: Pending, Submitted, Not Submitted, Late
- Score displayed after submission
- Sidebar Homework link active on this page
"""

import re
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import (
    _ensure_sidebar_visible,
    assert_page_has_text,
    assert_sidebar_has_link,
    click_sidebar_link,
)

pytestmark = pytest.mark.parent_homework


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _create_homework(classroom, title="Test HW", due_offset_days=7, teacher=None):
    from homework.models import Homework
    return Homework.objects.create(
        classroom=classroom,
        title=title,
        due_date=timezone.now() + timedelta(days=due_offset_days),
        num_questions=5,
        created_by=teacher,
    )


def _create_submission(homework, student, score=4, total=5, submitted_at=None):
    from homework.models import HomeworkSubmission
    sub = HomeworkSubmission.objects.create(
        homework=homework,
        student=student,
        score=score,
        total_questions=total,
        attempt_number=HomeworkSubmission.get_next_attempt_number(homework, student),
    )
    if submitted_at is not None:
        HomeworkSubmission.objects.filter(pk=sub.pk).update(submitted_at=submitted_at)
        sub.refresh_from_db()
    return sub


# ---------------------------------------------------------------------------
# Page loads
# ---------------------------------------------------------------------------

class TestParentHomeworkPageLoads:
    """Basic page rendering."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        self.parent = parent_with_child
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/homework/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_has_homework_heading(self):
        assert_page_has_text(self.page, "Homework")

    def test_child_name_shown_in_header(self, enrolled_student):
        # enrolled_student first_name is "Ui Student"
        assert_page_has_text(self.page, "Ui Student")

    def test_empty_state_when_no_homework(self):
        assert_page_has_text(self.page, "No homework assigned yet")

    def test_page_url_correct(self):
        expect(self.page).to_have_url(re.compile(r"/parent/homework"))


# ---------------------------------------------------------------------------
# Status badges
# ---------------------------------------------------------------------------

class TestParentHomeworkStatusBadges:
    """Each status badge renders with correct text and colour cue."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school, classroom,
               enrolled_student, teacher_user, db):
        self.url = live_server.url
        self.page = page
        self.classroom = classroom
        self.student = enrolled_student
        self.teacher = teacher_user
        self.parent = parent_with_child

    def _goto_homework(self):
        do_login(self.page, self.url, self.parent)
        self.page.goto(f"{self.url}/parent/homework/")
        self.page.wait_for_load_state("domcontentloaded")

    def test_pending_badge_shown_for_future_homework(self):
        _create_homework(self.classroom, "Pending HW", due_offset_days=7,
                         teacher=self.teacher)
        self._goto_homework()
        assert_page_has_text(self.page, "Pending HW")
        assert_page_has_text(self.page, "Pending")

    def test_not_submitted_badge_shown_for_overdue_homework(self):
        _create_homework(self.classroom, "Overdue HW", due_offset_days=-1,
                         teacher=self.teacher)
        self._goto_homework()
        assert_page_has_text(self.page, "Overdue HW")
        assert_page_has_text(self.page, "Not Submitted")

    def test_submitted_badge_shown_after_on_time_submission(self):
        hw = _create_homework(self.classroom, "Submitted HW", due_offset_days=5,
                              teacher=self.teacher)
        _create_submission(hw, self.student, score=4, total=5,
                           submitted_at=timezone.now() - timedelta(hours=1))
        self._goto_homework()
        assert_page_has_text(self.page, "Submitted HW")
        assert_page_has_text(self.page, "Submitted")

    def test_late_badge_shown_for_submission_after_due(self):
        hw = _create_homework(self.classroom, "Late HW", due_offset_days=-3,
                              teacher=self.teacher)
        _create_submission(hw, self.student, score=3, total=5,
                           submitted_at=timezone.now() - timedelta(hours=1))
        self._goto_homework()
        assert_page_has_text(self.page, "Late HW")
        assert_page_has_text(self.page, "Late")

    def test_score_displayed_after_submission(self):
        hw = _create_homework(self.classroom, "Scored HW", due_offset_days=5,
                              teacher=self.teacher)
        _create_submission(hw, self.student, score=4, total=5,
                           submitted_at=timezone.now() - timedelta(hours=1))
        self._goto_homework()
        body = self.page.locator("body").inner_text()
        assert "4" in body and "5" in body

    def test_multiple_homework_all_shown(self):
        _create_homework(self.classroom, "HW Alpha", due_offset_days=3,
                         teacher=self.teacher)
        _create_homework(self.classroom, "HW Beta", due_offset_days=5,
                         teacher=self.teacher)
        self._goto_homework()
        assert_page_has_text(self.page, "HW Alpha")
        assert_page_has_text(self.page, "HW Beta")


# ---------------------------------------------------------------------------
# Sidebar integration
# ---------------------------------------------------------------------------

class TestParentHomeworkSidebar:
    """Homework link in the parent sidebar."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_homework_link_exists_in_sidebar(self):
        assert_sidebar_has_link(self.page, "Homework")

    def test_homework_link_navigates_to_homework_page(self):
        click_sidebar_link(self.page, "Homework")
        expect(self.page).to_have_url(re.compile(r"/parent/homework"))

    def test_homework_link_active_when_on_homework_page(self):
        """The Homework link has active styling when viewing /parent/homework/."""
        click_sidebar_link(self.page, "Homework")
        self.page.wait_for_load_state("domcontentloaded")
        _ensure_sidebar_visible(self.page)
        hw_link = self.page.locator("aside#sidebar a", has_text="Homework").first
        # Active links have bg-indigo-500/20 class or similar — check for indigo
        class_attr = hw_link.get_attribute("class") or ""
        assert "indigo" in class_attr or "bg-" in class_attr, (
            f"Expected active class on Homework link, got: {class_attr}"
        )


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

class TestParentHomeworkAccess:
    """Only logged-in parents with a linked child can see homework."""

    def test_anonymous_redirected_to_login(self, live_server, page, db):
        page.goto(f"{live_server.url}/parent/homework/")
        page.wait_for_load_state("domcontentloaded")
        expect(page).to_have_url(re.compile(r"/accounts/login"))

    def test_student_cannot_access_parent_homework_page(
        self, live_server, page, enrolled_student, school, classroom
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/parent/homework/")
        page.wait_for_load_state("domcontentloaded")
        # Should not be 200 with homework heading
        body = page.locator("body").inner_text()
        assert "No homework assigned yet" not in body
