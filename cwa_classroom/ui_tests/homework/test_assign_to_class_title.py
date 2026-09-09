"""UI test — CPP-405: the "Assign to Another Class" screen carries a title field.

Covers the browser-level flow a teacher actually walks: open the assign screen,
edit the prefilled title, tick a second class, submit, and land back on the
detail page with a copy that carries the new name. Also pins the client-side
unlock — a class already holding the original title is locked until the title
is changed, at which point it becomes a valid target again.
"""

from datetime import timedelta

import pytest
from playwright.sync_api import expect

from ..conftest import _make_user, do_login

pytestmark = pytest.mark.dashboard


def _make_homework(classroom, teacher, title):
    from django.utils import timezone
    from homework.models import Homework
    return Homework.objects.create(
        classroom=classroom, created_by=teacher, title=title,
        homework_type='topic', num_questions=5,
        due_date=timezone.now() + timedelta(days=7), max_attempts=2,
        published_at=timezone.now(),
    )


class TestAssignToClassTitle:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, classroom, school, department,
               subject, level):
        from classroom.models import ClassRoom, ClassTeacher

        self.url = live_server.url
        self.page = page
        self.teacher = teacher_user
        self.classroom = classroom

        # A second class owned by the same teacher — the assign target.
        self.other_class = ClassRoom.objects.create(
            name="Year 8 Maths CPP405",
            school=school, department=department, subject=subject,
        )
        self.other_class.levels.add(level)
        ClassTeacher.objects.create(classroom=self.other_class, teacher=teacher_user)

        self.homework = _make_homework(classroom, teacher_user, "Fractions Week 1 UI")
        do_login(page, self.url, teacher_user)

    def _open_assign(self):
        self.page.goto(f"{self.url}/homework/{self.homework.id}/assign/")
        self.page.wait_for_load_state("domcontentloaded")

    def test_title_field_is_prefilled_and_renames_the_copy(self):
        from homework.models import Homework

        self._open_assign()

        title_input = self.page.locator("input[name='homework_title']")
        expect(title_input).to_have_value("Fractions Week 1 UI")

        title_input.fill("Fractions Week 1 — Year 8")
        self.page.locator(
            f"input[name='classroom_ids'][value='{self.other_class.id}']"
        ).check()
        self.page.get_by_role("button", name="Assign to Selected Classes").click()
        self.page.wait_for_load_state("domcontentloaded")

        assert f"/homework/{self.homework.id}/" in self.page.url

        copy = Homework.objects.get(classroom=self.other_class)
        assert copy.title == "Fractions Week 1 — Year 8"
        # The original keeps its own name.
        self.homework.refresh_from_db()
        assert self.homework.title == "Fractions Week 1 UI"

    def test_mobile_viewport_shows_the_title_field(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self._open_assign()

        expect(self.page.locator("input[name='homework_title']")).to_be_visible()

    def test_already_assigned_class_unlocks_once_the_title_changes(self):
        _make_homework(self.other_class, self.teacher, "Fractions Week 1 UI")

        self._open_assign()

        checkbox = self.page.locator(
            f"input[name='classroom_ids'][value='{self.other_class.id}']"
        )
        expect(checkbox).to_be_disabled()

        # Renaming makes it a valid target again — and the box is left unticked
        # rather than carrying over the "already assigned" checked state.
        self.page.locator("input[name='homework_title']").fill("Fractions Week 1 Retake")
        expect(checkbox).to_be_enabled()
        expect(checkbox).not_to_be_checked()

    def test_another_teacher_cannot_open_the_assign_screen(self, roles):
        other_teacher = _make_user("teacher_cpp405", "teacher")
        do_login(self.page, self.url, other_teacher)
        resp = self.page.goto(f"{self.url}/homework/{self.homework.id}/assign/")

        assert resp.status == 404
