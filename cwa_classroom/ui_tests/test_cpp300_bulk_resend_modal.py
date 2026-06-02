"""
CPP-300 — per-class bulk "Resend Welcome" modal (browser UI).

Drives the class-detail modal as a real user: opens it, toggles Select all /
Unselect all, checks the live "Resend to N of M" count, and verifies the submit
button disables at zero. Also covers role gating (parent cannot reach the page).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _assign_role, TEST_PASSWORD, _RUN_ID


pytestmark = pytest.mark.csv_import


def _enrol_two_students(school, classroom):
    """Create + enrol two students with emails so the modal lists them checked."""
    from accounts.models import CustomUser, Role
    from classroom.models import SchoolStudent, ClassStudent

    students = []
    for i in range(2):
        u = CustomUser.objects.create_user(
            username=f"resend_stu_{_RUN_ID}_{i}",
            password=TEST_PASSWORD,
            email=f"resend_stu_{_RUN_ID}_{i}@test.local",
            first_name=f"Resend{i}",
            last_name="Student",
            profile_completed=False,
            must_change_password=True,
            creation_method=CustomUser.CREATION_INSTITUTE,
        )
        _assign_role(u, Role.STUDENT)
        SchoolStudent.objects.create(school=school, student=u, is_active=True)
        ClassStudent.objects.create(classroom=classroom, student=u, is_active=True)
        students.append(u)
    return students


class TestBulkResendModal:

    def test_hoi_bulk_resend_modal_select_all_unselect_all(
        self, live_server, page, admin_user, school, classroom,
    ):
        url = live_server.url
        _enrol_two_students(school, classroom)

        do_login(page, url, admin_user)
        page.goto(f"{url}/class/{classroom.id}/")
        page.wait_for_load_state("domcontentloaded")

        # Open the modal.
        page.get_by_role("button", name="Resend Welcome").click()

        modal = page.locator("text=Resend Welcome Emails")
        expect(modal).to_be_visible()

        checkboxes = page.locator("input[name='student_ids']")
        expect(checkboxes).to_have_count(2)

        # All checked by default → live count shows 2, submit enabled.
        count_label = page.locator("text=/Resend to/")
        expect(count_label).to_contain_text("2")
        submit = page.get_by_role("button", name="Send Welcome Emails")
        expect(submit).to_be_enabled()

        # Unselect all → count 0, submit disabled.
        page.get_by_role("button", name="Unselect all", exact=True).click()
        expect(submit).to_be_disabled()

        # Select all → count back to 2, submit enabled.
        page.get_by_role("button", name="Select all", exact=True).click()
        expect(submit).to_be_enabled()
        expect(count_label).to_contain_text("2")

    def test_resend_modal_live_count_and_disabled_when_zero(
        self, live_server, page, admin_user, school, classroom,
    ):
        url = live_server.url
        _enrol_two_students(school, classroom)

        do_login(page, url, admin_user)
        page.goto(f"{url}/class/{classroom.id}/")
        page.wait_for_load_state("domcontentloaded")
        page.get_by_role("button", name="Resend Welcome").click()

        submit = page.get_by_role("button", name="Send Welcome Emails")
        checkboxes = page.locator("input[name='student_ids']")

        # Uncheck one → count 1, still enabled.
        checkboxes.nth(0).uncheck()
        expect(page.locator("text=/Resend to/")).to_contain_text("1")
        expect(submit).to_be_enabled()

        # Uncheck the other → count 0, disabled.
        checkboxes.nth(1).uncheck()
        expect(submit).to_be_disabled()

    def test_parent_cannot_access_bulk_resend(
        self, live_server, page, parent_user, school, classroom,
    ):
        """A parent has no route to the class page / bulk resend (role-gated)."""
        url = live_server.url
        do_login(page, url, parent_user)
        resp = page.goto(f"{url}/class/{classroom.id}/")
        # RoleRequiredMixin denies — not a 200 class-detail page.
        assert resp.status in (403, 302) or "/class/" not in page.url
