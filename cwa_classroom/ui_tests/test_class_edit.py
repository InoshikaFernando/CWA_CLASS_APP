"""
Playwright UI tests for the Edit Class page (/class/<id>/edit/).

Covers ``EditClassView`` (classroom/views.py:897):

  - Page loads with current class name and day prefilled
  - Subject dropdown is populated from DepartmentSubject rows
  - Selecting a subject renders its levels via inline JS
  - Submitting an updated name redirects and persists
  - Day/time updates persist
  - Teacher without ownership of the class gets 404
  - HoD can reach the edit page for a class in their department
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _goto_edit(page: Page, live_server_url: str, class_id: int) -> None:
    page.goto(f"{live_server_url}/class/{class_id}/edit/")
    page.wait_for_load_state("networkidle")


class TestClassEdit:

    @pytest.mark.django_db(transaction=True)
    def test_page_loads_with_prefilled_fields(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_edit(page, live_server.url, classroom.pk)
        expect(page.get_by_role("heading", name="Edit Class")).to_be_visible()
        assert page.locator("input[name='name']").input_value() == classroom.name
        assert page.locator("select[name='day']").input_value() == "monday"

    @pytest.mark.django_db(transaction=True)
    def test_subject_dropdown_contains_department_subjects(
        self, page: Page, live_server, teacher_user, classroom, subject
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_edit(page, live_server.url, classroom.pk)
        select = page.locator("#subject_select")
        options = select.locator("option").all_text_contents()
        # "Mathematics" is a DepartmentSubject for this department
        assert any("Mathematics" in o for o in options), (
            f"Expected Mathematics in subject options, got {options!r}"
        )

    @pytest.mark.django_db(transaction=True)
    def test_updating_name_persists(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_edit(page, live_server.url, classroom.pk)

        new_name = f"{classroom.name} (updated)"
        name_input = page.locator("input[name='name']")
        name_input.fill(new_name)

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Save Changes", re.I)).click()
        page.wait_for_load_state("networkidle")

        from classroom.models import ClassRoom
        classroom.refresh_from_db()
        assert classroom.name == new_name

    @pytest.mark.django_db(transaction=True)
    def test_updating_day_persists(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_edit(page, live_server.url, classroom.pk)

        page.locator("select[name='day']").select_option("friday")
        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Save Changes", re.I)).click()
        page.wait_for_load_state("networkidle")

        classroom.refresh_from_db()
        assert classroom.day == "friday"

    @pytest.mark.django_db(transaction=True)
    def test_level_renders_after_subject_selection(
        self, page: Page, live_server, teacher_user, classroom, department, level,
    ):
        """When the department has a DepartmentLevel for the subject, its checkbox renders."""
        from classroom.models import DepartmentLevel

        DepartmentLevel.objects.get_or_create(
            department=department, level=level,
            defaults={"order": level.level_number},
        )

        do_login(page, live_server.url, teacher_user)
        _goto_edit(page, live_server.url, classroom.pk)

        # Page load auto-selects the current subject → renderLevels() runs.
        checkboxes = page.locator("input[name='levels']")
        assert checkboxes.count() >= 1, "At least one level checkbox should render"

    @pytest.mark.django_db(transaction=True)
    def test_unrelated_teacher_gets_404(
        self, page: Page, live_server, roles, classroom
    ):
        """A teacher who is not assigned to this class should not reach edit."""
        from accounts.models import Role
        from .conftest import _make_user

        other = _make_user("other_teacher_ce", Role.TEACHER)
        do_login(page, live_server.url, other)
        page.goto(f"{live_server.url}/class/{classroom.pk}/edit/")
        page.wait_for_load_state("networkidle")
        # 404 page does not show the Edit Class heading
        assert page.get_by_role("heading", name="Edit Class").count() == 0

    @pytest.mark.django_db(transaction=True)
    def test_hod_can_edit_class_in_their_department(
        self, page: Page, live_server, hod_user, department, classroom
    ):
        do_login(page, live_server.url, hod_user)
        _goto_edit(page, live_server.url, classroom.pk)
        expect(page.get_by_role("heading", name="Edit Class")).to_be_visible()
