"""UI test — Recently Added Students page: list, time-window filter, deactivate & restore.

Covers the MHM audit flow: an admin opens the "Recently Added Students" page,
sees students newest-first with their add date/time, deactivates a wrongly-added
student (with confirm), then restores them — all without leaving the page.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.dashboard


class TestRecentStudentsUI:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        from accounts.models import CustomUser, Role
        from classroom.models import SchoolStudent

        self.url = live_server.url
        self.page = page
        self.school = school

        student_role = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'})[0]

        def make(username, first, last, joined_delta):
            u = CustomUser.objects.create_user(
                username=username, email=f'{username}@t.com', password='pass1234',
                first_name=first, last_name=last, profile_completed=True,
            )
            u.roles.add(student_role)
            ss = SchoolStudent.objects.create(school=school, student=u, is_active=True)
            SchoolStudent.objects.filter(pk=ss.pk).update(
                joined_at=timezone.now() - joined_delta)
            return u

        # Newest first: Newton (2h) → Wolf (3d) → Ancient (40d, outside 7d window)
        self.new_student = make('rs_newton', 'Isaac', 'Newton', timedelta(hours=2))
        self.week_student = make('rs_wolf', 'Wanda', 'Wolf', timedelta(days=3))
        self.old_student = make('rs_ancient', 'Olduvai', 'Ancient', timedelta(days=40))

        do_login(page, self.url, admin_user)

    def _recent_url(self, window=None):
        u = f"{self.url}/admin-dashboard/schools/{self.school.id}/students/recent/"
        if window:
            u += f"?window={window}"
        return u

    def test_recent_page_lists_students_with_add_time(self):
        self.page.goto(self._recent_url(window='all'))
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, "Recently Added Students")
        # Newest-window students show; their names render.
        assert_page_has_text(self.page, "Isaac Newton")
        assert_page_has_text(self.page, "Wanda Wolf")
        # An added date/time (e.g. "at" column) — assert the year is present.
        year = str(timezone.now().year)
        assert_page_has_text(self.page, year)

    def test_default_window_hides_old_students(self):
        self.page.goto(self._recent_url())  # default = last 7 days
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, "Isaac Newton")
        assert "Olduvai Ancient" not in self.page.content()

    def test_deactivate_then_restore_roundtrip(self):
        from classroom.models import SchoolStudent

        self.page.goto(self._recent_url(window='all'))
        self.page.wait_for_load_state("domcontentloaded")

        # Auto-accept the "Remove ...?" confirm dialog.
        self.page.on("dialog", lambda d: d.accept())

        # Deactivate Newton — his row's form posts to his remove endpoint.
        remove_action = (
            f"/admin-dashboard/schools/{self.school.id}/students/"
            f"{self.new_student.id}/remove/"
        )
        self.page.locator(f"form[action='{remove_action}'] button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")

        ss = SchoolStudent.objects.get(school=self.school, student=self.new_student)
        assert ss.is_active is False
        # We returned to the recent page and the row is now marked Removed.
        assert "/students/recent/" in self.page.url
        assert_page_has_text(self.page, "Removed")

        # Restore him again from the same page.
        restore_action = (
            f"/admin-dashboard/schools/{self.school.id}/students/"
            f"{self.new_student.id}/restore/"
        )
        self.page.locator(f"form[action='{restore_action}'] button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")

        ss.refresh_from_db()
        assert ss.is_active is True
        assert "/students/recent/" in self.page.url

    def test_recent_link_present_on_manage_students(self):
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/")
        self.page.wait_for_load_state("domcontentloaded")
        assert f"/students/recent/" in self.page.content()
