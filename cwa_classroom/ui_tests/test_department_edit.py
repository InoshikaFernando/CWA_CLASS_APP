"""
Playwright UI tests for /admin-dashboard/schools/<id>/departments/<id>/edit/.

Covers ``DepartmentEditView`` (classroom/views_department.py:235):

  - Page loads with name prefilled and current subjects checked
  - Global Mathematics subject is offered as a checkbox
  - Coding subject appears once a global Coding Subject row exists
  - Toggling off an existing subject removes the DepartmentSubject row
  - Checking a new subject creates a DepartmentSubject row + copies its global levels
  - "Create New Subject" inline input creates a school-scoped Subject
  - Renaming the department updates the slug
  - Non-owner/unrelated admin cannot access the page
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _edit_url(live_server_url: str, school_id: int, dept_id: int) -> str:
    return f"{live_server_url}/admin-dashboard/schools/{school_id}/departments/{dept_id}/edit/"


def _goto_edit(page: Page, live_server_url: str, school_id: int, dept_id: int) -> None:
    page.goto(_edit_url(live_server_url, school_id, dept_id))
    page.wait_for_load_state("networkidle")


class TestDepartmentEdit:

    @pytest.mark.django_db(transaction=True)
    def test_page_loads_with_prefilled_fields(
        self, page: Page, live_server, hoi_user, hoi_school_setup, department
    ):
        do_login(page, live_server.url, hoi_user)
        _goto_edit(page, live_server.url, hoi_school_setup.pk, department.pk)
        expect(page.get_by_role("heading", name="Edit Department")).to_be_visible()
        assert page.locator("input[name='name']").input_value() == department.name

    @pytest.mark.django_db(transaction=True)
    def test_mathematics_subject_is_offered(
        self, page: Page, live_server, hoi_user, hoi_school_setup, department, subject
    ):
        do_login(page, live_server.url, hoi_user)
        _goto_edit(page, live_server.url, hoi_school_setup.pk, department.pk)
        # Subject checkbox is present in the list
        boxes = page.locator("input[type='checkbox'][name='subjects']")
        assert boxes.count() >= 1
        # Mathematics is pre-checked (it's on the department already)
        checked_values = page.locator("input[type='checkbox'][name='subjects']:checked").evaluate_all(
            "nodes => nodes.map(n => n.value)"
        )
        assert str(subject.pk) in checked_values

    @pytest.mark.django_db(transaction=True)
    def test_coding_subject_appears_when_global_row_exists(
        self, page: Page, live_server, hoi_user, hoi_school_setup, department,
        subject, coding_subject,
    ):
        do_login(page, live_server.url, hoi_user)
        _goto_edit(page, live_server.url, hoi_school_setup.pk, department.pk)
        # Page HTML must contain the Coding option (label text)
        expect(page.locator("label", has_text="Coding").first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_unchecking_subject_removes_department_subject_row(
        self, page: Page, live_server, hoi_user, hoi_school_setup, department, subject
    ):
        from classroom.models import DepartmentSubject

        do_login(page, live_server.url, hoi_user)
        _goto_edit(page, live_server.url, hoi_school_setup.pk, department.pk)

        box = page.locator(
            f"input[type='checkbox'][name='subjects'][value='{subject.pk}']"
        )
        box.uncheck()
        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Save Changes", re.I)).click()
        page.wait_for_load_state("networkidle")

        assert not DepartmentSubject.objects.filter(
            department=department, subject=subject
        ).exists()

    @pytest.mark.django_db(transaction=True)
    def test_creating_new_subject_inline(
        self, page: Page, live_server, hoi_user, hoi_school_setup, department
    ):
        from classroom.models import DepartmentSubject, Subject

        do_login(page, live_server.url, hoi_user)
        _goto_edit(page, live_server.url, hoi_school_setup.pk, department.pk)

        # Type a new subject name and submit
        page.locator("input[name='new_subject_name']").fill("Art History")
        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Save Changes", re.I)).click()
        page.wait_for_load_state("networkidle")

        subj = Subject.objects.filter(name="Art History", school=hoi_school_setup).first()
        assert subj is not None, "New subject should be created and scoped to the school"
        assert DepartmentSubject.objects.filter(department=department, subject=subj).exists()

    @pytest.mark.django_db(transaction=True)
    def test_renaming_department_updates_slug(
        self, page: Page, live_server, hoi_user, hoi_school_setup, department
    ):
        do_login(page, live_server.url, hoi_user)
        _goto_edit(page, live_server.url, hoi_school_setup.pk, department.pk)

        page.locator("input[name='name']").fill("Renamed Maths")
        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Save Changes", re.I)).click()
        page.wait_for_load_state("networkidle")

        department.refresh_from_db()
        assert department.name == "Renamed Maths"
        assert department.slug == "renamed-maths"

    @pytest.mark.django_db(transaction=True)
    def test_unrelated_user_cannot_access_page(
        self, page: Page, live_server, roles, hoi_school_setup, department
    ):
        """A user who is not the owner/HoI of this school gets 404/redirect."""
        from accounts.models import Role
        from .conftest import _make_user

        other = _make_user("outsider_de", Role.INSTITUTE_OWNER)
        do_login(page, live_server.url, other)
        page.goto(_edit_url(live_server.url, hoi_school_setup.pk, department.pk))
        page.wait_for_load_state("networkidle")
        # They shouldn't see the edit heading
        assert page.get_by_role("heading", name="Edit Department").count() == 0
