"""
UI test for the "Move student to another class" action on the class detail page.

An admin moves a student from one class to another; afterwards the student still
sees the *old* class's homework in their list, because a move retains homework
access (unlike a plain removal, which revokes it).
"""
import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect

from ..conftest import do_login, do_logout
from ..helpers import assert_page_has_text

pytestmark = pytest.mark.student_move


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # The sandbox ships a newer Chromium (build 1194) than the pinned Playwright
    # expects, so its version-specific headless-shell lookup misses. Launch the
    # installed full Chrome directly instead of downloading. In CI the pinned
    # browser matches, so this override is a harmless no-op path there.
    import os
    exe = "/opt/pw-browsers/chromium"
    if os.path.exists(exe):
        return {**browser_type_launch_args, "executable_path": exe}
    return browser_type_launch_args


def _second_class(school):
    from classroom.models import ClassRoom
    return ClassRoom.objects.create(
        name=f"Junior Scholarship {uuid.uuid4().hex[:6]}",
        school=school, is_active=True,
    )


def _published_homework(classroom):
    from homework.models import Homework
    return Homework.objects.create(
        classroom=classroom,
        title="Year 4 fractions worksheet",
        due_date=timezone.now() + timedelta(days=7),
        published_at=timezone.now(),
    )


class TestMoveStudentRetainsHomework:
    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, classroom,
               enrolled_student, student_user):
        self.url = live_server.url
        self.page = page
        self.admin = admin_user
        self.source = classroom
        self.student = student_user
        self.target = _second_class(school)
        self.homework = _published_homework(classroom)
        # The Move form fires a native confirm() — auto-accept it.
        page.on("dialog", lambda d: d.accept())

    def test_admin_move_keeps_old_homework_visible(self):
        # Admin opens the source class and moves the student to the target class.
        do_login(self.page, self.url, self.admin)
        self.page.goto(self.url + reverse('class_detail', kwargs={'class_id': self.source.id}))
        self.page.wait_for_load_state("domcontentloaded")

        form = self.page.locator(
            f"form[action*='/student/{self.student.id}/move/']").first
        expect(form).to_be_visible()
        form.locator("select[name='target_class_id']").select_option(str(self.target.id))
        form.locator("button[type='submit']").click()

        # Back on the class page, the student is no longer an active member here.
        self.page.wait_for_load_state("domcontentloaded")

        # The move is recorded: source retained, target active.
        from classroom.models import ClassStudent
        src = ClassStudent.objects.get(classroom=self.source, student=self.student)
        assert src.is_active is False
        assert src.moved_at is not None
        tgt = ClassStudent.objects.get(classroom=self.target, student=self.student)
        assert tgt.is_active is True

        # The student logs in and still sees the old class's homework.
        do_logout(self.page, self.url)
        do_login(self.page, self.url, self.student)
        self.page.goto(self.url + reverse('homework:student_list'))
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, "Year 4 fractions worksheet")
