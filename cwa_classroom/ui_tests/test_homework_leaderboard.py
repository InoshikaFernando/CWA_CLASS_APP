"""UI tests for CPP-363 — per-class homework progress leaderboard.

Drives the teacher's flow: open the Leaderboard tab from the Homework Monitor,
see the podium + ranked table for a class with submissions, and switch between
the per-homework and "All homework" aggregate scopes.
"""

from datetime import timedelta

import pytest
from playwright.sync_api import expect

from .conftest import TEST_PASSWORD, _RUN_ID, _assign_role, do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


def _make_homework(classroom, teacher, title):
    from django.utils import timezone
    from homework.models import Homework
    return Homework.objects.create(
        classroom=classroom, created_by=teacher, title=title,
        homework_type='topic', num_questions=5,
        due_date=timezone.now() + timedelta(days=7), max_attempts=3,
        published_at=timezone.now(),
    )


def _make_student(school, classroom, first_name, last_name):
    from accounts.models import CustomUser, Role
    from classroom.models import ClassStudent, SchoolStudent
    user = CustomUser.objects.create_user(
        username=f"lb_{first_name.lower()}_{_RUN_ID}",
        password=TEST_PASSWORD,
        email=f"lb_{first_name.lower()}_{_RUN_ID}@test.local",
        first_name=first_name, last_name=last_name,
        profile_completed=True, must_change_password=False,
    )
    _assign_role(user, Role.STUDENT)
    SchoolStudent.objects.get_or_create(school=school, student=user)
    ClassStudent.objects.create(classroom=classroom, student=user, is_active=True)
    return user


def _submit(homework, student, attempt_number, score, points):
    from homework.models import HomeworkSubmission
    return HomeworkSubmission.objects.create(
        homework=homework, student=student,
        attempt_number=attempt_number, score=score,
        total_questions=5, points=points,
    )


class TestHomeworkLeaderboard:
    """/homework/leaderboard/ — podium + ranked board, per-homework & aggregate."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, classroom, school, subject):
        self.url = live_server.url
        self.page = page

        self.hw = _make_homework(classroom, teacher_user, "Fractions Homework LB")

        # Ada tops the board (95 pts, one attempt); Bo trails (70 pts);
        # Cy never submits and must fall below the ranking as "Not started".
        self.ada = _make_student(school, classroom, "Ada", "Topscorer")
        self.bo = _make_student(school, classroom, "Bo", "Runnerup")
        self.cy = _make_student(school, classroom, "Cy", "Nostart")
        _submit(self.hw, self.ada, attempt_number=1, score=5, points=95.0)
        _submit(self.hw, self.bo, attempt_number=1, score=3, points=70.0)

        do_login(page, self.url, teacher_user)
        self.classroom = classroom

    def _goto(self, query=""):
        self.page.goto(f"{self.url}/homework/leaderboard/{query}")
        self.page.wait_for_load_state("domcontentloaded")

    def test_leaderboard_tab_navigates_from_monitor(self):
        self.page.goto(f"{self.url}/homework/monitor/?classroom={self.classroom.id}")
        self.page.wait_for_load_state("domcontentloaded")
        tab = self.page.locator("a[href*='/homework/leaderboard/']").first
        expect(tab).to_be_visible()
        tab.click()
        self.page.wait_for_load_state("domcontentloaded")
        assert "/homework/leaderboard/" in self.page.url
        assert_page_has_text(self.page, "Homework progress")

    def test_per_homework_podium_and_ranking(self):
        self._goto(f"?classroom={self.classroom.id}&homework={self.hw.id}")
        # All three students appear; the two submitters are ranked, Cy is not.
        assert_page_has_text(self.page, "Ada Topscorer")
        assert_page_has_text(self.page, "Bo Runnerup")
        assert_page_has_text(self.page, "Cy Nostart")
        assert_page_has_text(self.page, "Not started")
        # The top scorer's best percentage shows on the board.
        assert_page_has_text(self.page, "100%")

    def test_scope_dropdown_offers_all_homework(self):
        # The scope toggle exists with an "All homework" option to switch to.
        self._goto(f"?classroom={self.classroom.id}&homework={self.hw.id}")
        expect(
            self.page.locator("select[name='homework'] option[value='all']")
        ).to_have_count(1)
        # Per-homework view shows a plain "Best score" column, not the aggregate one.
        assert_page_has_text(self.page, "Best score")

    def test_all_homework_aggregate_view(self):
        # The aggregate scope renders its own columns and keeps the ranking.
        self._goto(f"?classroom={self.classroom.id}&homework=all")
        assert_page_has_text(self.page, "Avg best score")
        assert_page_has_text(self.page, "Homework done")
        assert_page_has_text(self.page, "Ada Topscorer")
