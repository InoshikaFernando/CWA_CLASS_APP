"""UI test — Recently Added Students page: list, time-window filter, deactivate & restore.

Covers the MHM audit flow: an admin opens the "Recently Added Students" page,
sees students newest-first with their add date/time, deactivates a wrongly-added
student (with confirm), then restores them — all without leaving the page.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from .conftest import do_login, do_logout, TEST_PASSWORD
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

    def test_e2e_add_via_ui_then_find_and_deactivate(self):
        """Full flow: add a student through the real Add Student modal, then
        find them on Recently Added and deactivate — the MHM scenario end to end."""
        from accounts.models import CustomUser
        from classroom.models import SchoolStudent

        # 1. Add a brand-new student through the Manage Students UI.
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Add Student").first.click()

        add_form = self.page.locator("form:has(#first_name)")
        add_form.locator("#first_name").fill("Grace")
        add_form.locator("#last_name").fill("Hopper")
        add_form.locator("#email").fill("grace.hopper.e2e@school.com")
        add_form.locator("#password").fill("TestPass123!")
        add_form.locator("button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")

        # The account really exists now (created via the UI, not the ORM fixture).
        new_user = CustomUser.objects.get(email="grace.hopper.e2e@school.com")
        assert SchoolStudent.objects.filter(
            school=self.school, student=new_user, is_active=True).exists()

        # 2. It appears on Recently Added (default 7-day window — just added).
        self.page.goto(self._recent_url())
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, "Grace Hopper")

        # 3. Deactivate it from the recent page.
        self.page.on("dialog", lambda d: d.accept())
        remove_action = (
            f"/admin-dashboard/schools/{self.school.id}/students/"
            f"{new_user.id}/remove/"
        )
        self.page.locator(
            f"form[action='{remove_action}'] button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")

        ss = SchoolStudent.objects.get(school=self.school, student=new_user)
        assert ss.is_active is False
        assert "/students/recent/" in self.page.url
        assert_page_has_text(self.page, "Removed")

    def test_e2e_add_remove_last_school_then_login_as_individual(self):
        """add via UI -> remove from last school -> log in as the converted
        individual student and confirm they can use the app."""
        from accounts.models import CustomUser, Role, UserRole
        from billing.models import Package, Subscription
        from classroom.models import SchoolStudent

        # 1. Add a student through the real Add Student modal.
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Add Student").first.click()
        add_form = self.page.locator("form:has(#first_name)")
        add_form.locator("#first_name").fill("Ada")
        add_form.locator("#last_name").fill("Lovelace")
        add_form.locator("#email").fill("ada.lovelace.e2e@school.com")
        add_form.locator("#password").fill(TEST_PASSWORD)
        add_form.locator("button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")

        user = CustomUser.objects.get(email="ada.lovelace.e2e@school.com")
        # Represent a student who has since completed onboarding and holds an
        # active (100% free) CWA subscription — so an individual student is not
        # walled by the payment gate after conversion.
        user.profile_completed = True
        user.must_change_password = False
        user.save(update_fields=["profile_completed", "must_change_password"])
        pkg = Package.objects.create(
            name="IndE2E", price=Decimal("19.90"), stripe_price_id="price_e2eind")
        Subscription.objects.create(
            user=user, package=pkg, status=Subscription.STATUS_ACTIVE,
            discount_percent_snapshot=100)

        # 2. Remove from their only (last) school via Recently Added.
        self.page.goto(self._recent_url())
        self.page.wait_for_load_state("domcontentloaded")
        self.page.on("dialog", lambda d: d.accept())
        remove_action = (
            f"/admin-dashboard/schools/{self.school.id}/students/{user.id}/remove/")
        self.page.locator(
            f"form[action='{remove_action}'] button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Converted to an individual student.
        assert UserRole.objects.filter(
            user=user, role__name=Role.INDIVIDUAL_STUDENT).exists()
        assert not UserRole.objects.filter(
            user=user, role__name=Role.STUDENT).exists()
        assert not SchoolStudent.objects.filter(student=user, is_active=True).exists()

        # 3. Log in as the now-individual student.
        do_logout(self.page, self.url)
        do_login(self.page, self.url, user)

        # 4. They can use the app — not bounced to login or the payment wall.
        self.page.goto(f"{self.url}/homework/")
        self.page.wait_for_load_state("domcontentloaded")
        assert "/accounts/login" not in self.page.url
        assert "trial-expired" not in self.page.url
