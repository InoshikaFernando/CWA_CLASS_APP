"""UI test — the creator (HoI/HoD/teacher) can delete homework they added.

Covers the browser-level flow: the Delete button is visible on the homework
detail page, clicking it (and accepting the confirm dialog) soft-deletes the
homework, redirects to the monitor, and the homework no longer appears.
"""

from datetime import timedelta

import pytest
from playwright.sync_api import expect

from .conftest import do_login

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


class TestHomeworkDelete:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, classroom):
        self.url = live_server.url
        self.page = page
        self.teacher = teacher_user
        self.homework = _make_homework(classroom, teacher_user, "Delete Me Homework UI")
        do_login(page, self.url, teacher_user)

    def test_creator_sees_and_uses_delete_button(self):
        from homework.models import Homework

        self.page.goto(f"{self.url}/homework/{self.homework.id}/")
        self.page.wait_for_load_state("domcontentloaded")

        delete_form = self.page.locator(
            f"form[action='/homework/{self.homework.id}/delete/']"
        )
        expect(delete_form).to_have_count(1)

        # Accept the "are you sure" confirm() before clicking.
        self.page.on("dialog", lambda dialog: dialog.accept())
        delete_form.locator("button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Redirected to the monitor with a confirmation, and the homework is gone.
        assert "/homework/monitor/" in self.page.url
        detail_link = self.page.locator(f"a[href='/homework/{self.homework.id}/']")
        expect(detail_link).to_have_count(0)

        # Soft-deleted in the DB: hidden from the default manager, preserved row.
        assert not Homework.objects.filter(pk=self.homework.pk).exists()
        assert Homework.all_objects.get(pk=self.homework.pk).deleted_at is not None
