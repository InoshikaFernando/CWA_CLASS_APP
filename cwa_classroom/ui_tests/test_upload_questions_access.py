"""
Playwright UI tests for role-based access to /upload-questions/.

Covers ``UploadQuestionsView.required_roles`` + the teacher-classroom rule in
``_base_context`` (classroom/views.py).

  - Unauthenticated user is redirected to login
  - Student is blocked (redirect to login or forbidden)
  - Teacher sees classroom dropdown
  - HoD does NOT see classroom dropdown (scope covers the whole department)
  - HoI does NOT see classroom dropdown (scope covers the whole school)
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _goto_upload(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/upload-questions/")
    page.wait_for_load_state("networkidle")


class TestUploadQuestionsAccess:

    @pytest.mark.django_db(transaction=True)
    def test_unauthenticated_redirects_to_login(
        self, page: Page, live_server
    ):
        page.goto(f"{live_server.url}/upload-questions/")
        page.wait_for_load_state("networkidle")
        assert "/accounts/login" in page.url

    @pytest.mark.django_db(transaction=True)
    def test_student_is_blocked(
        self, page: Page, live_server, enrolled_student, classroom
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/upload-questions/")
        page.wait_for_load_state("networkidle")
        # RoleRequiredMixin redirects to subjects_hub for students; either
        # way, they must NOT see the upload form title.
        heading = page.get_by_role("heading", name="Upload Questions")
        assert heading.count() == 0 or "/upload-questions/" not in page.url

    @pytest.mark.django_db(transaction=True)
    def test_teacher_sees_classroom_dropdown(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)
        # Classroom selector is rendered (it's hidden by Alpine unless subject==mathematics,
        # but the element is in the DOM for teachers).
        select = page.locator("select[name='classroom']")
        assert select.count() == 1, "Teachers should see a classroom <select>"

    @pytest.mark.django_db(transaction=True)
    def test_hod_does_not_see_classroom_dropdown(
        self, page: Page, live_server, hod_user, department, classroom
    ):
        do_login(page, live_server.url, hod_user)
        _goto_upload(page, live_server.url)
        # HoD scope covers the whole department — no classroom selector rendered
        select = page.locator("select[name='classroom']")
        assert select.count() == 0

    @pytest.mark.django_db(transaction=True)
    def test_hoi_does_not_see_classroom_dropdown(
        self, page: Page, live_server, hoi_user, hoi_school_setup, classroom
    ):
        do_login(page, live_server.url, hoi_user)
        _goto_upload(page, live_server.url)
        select = page.locator("select[name='classroom']")
        assert select.count() == 0
