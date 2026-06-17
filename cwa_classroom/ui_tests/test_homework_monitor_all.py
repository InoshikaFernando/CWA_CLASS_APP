"""UI tests for CPP-344 — homework monitor 'All' filter + back-to-All button."""

from datetime import timedelta

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


def _make_homework(classroom, teacher, title):
    from django.utils import timezone
    from homework.models import Homework
    return Homework.objects.create(
        classroom=classroom, created_by=teacher, title=title,
        homework_type='topic', num_questions=5,
        due_date=timezone.now() + timedelta(days=7), max_attempts=2,
        published_at=timezone.now(),
    )


class TestHomeworkMonitorAllFilter:
    """/homework/monitor/ — All option aggregates across the teacher's classes."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, classroom, school, subject):
        from classroom.models import ClassRoom, ClassTeacher
        self.url = live_server.url
        self.page = page
        # A second class taught by the same teacher.
        self.classroom2 = ClassRoom.objects.create(
            name="Year 8 Science UI", code="HWUI02", school=school, subject=subject,
        )
        ClassTeacher.objects.create(classroom=self.classroom2, teacher=teacher_user)
        self.hw1 = _make_homework(classroom, teacher_user, "Algebra Homework UI")
        self.hw2 = _make_homework(self.classroom2, teacher_user, "Science Homework UI")
        do_login(page, self.url, teacher_user)

    def _goto(self, query=""):
        self.page.goto(f"{self.url}/homework/monitor/{query}")
        self.page.wait_for_load_state("domcontentloaded")

    def test_all_option_present(self):
        self._goto()
        options = self.page.locator("select[name='classroom'] option")
        expect(self.page.locator("select[name='classroom'] option[value='all']")).to_have_count(1)
        assert "All classes" in options.all_inner_texts().__str__()

    def test_all_shows_homework_across_classes(self):
        self._goto("?classroom=all")
        assert_page_has_text(self.page, "Algebra Homework UI")
        assert_page_has_text(self.page, "Science Homework UI")

    def test_class_badge_shown_in_all_view(self):
        self._goto("?classroom=all")
        assert_page_has_text(self.page, "Year 8 Science UI")

    def test_detail_back_link_lands_on_all(self):
        self.page.goto(f"{self.url}/homework/{self.hw1.id}/")
        self.page.wait_for_load_state("domcontentloaded")
        back = self.page.locator("a[href*='/homework/monitor/?classroom=all']").first
        expect(back).to_be_visible()
        back.click()
        self.page.wait_for_load_state("domcontentloaded")
        assert "classroom=all" in self.page.url
        # All view shows both classes' homework.
        assert_page_has_text(self.page, "Science Homework UI")
