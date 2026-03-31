"""Tests for student CSV upload — upload form, preview, structure mapping, results."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.csv_import


class TestStudentCSVUploadPage:
    """Tests for /import-students/ — the upload form."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/import-students/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Import")

    def test_file_input_visible(self):
        """File input for CSV/XLS upload."""
        file_input = self.page.locator("input[type='file']")
        expect(file_input).to_be_attached()

    def test_source_system_presets_visible(self):
        """Source system preset radio buttons should render."""
        radios = self.page.locator("input[type='radio']")
        assert radios.count() > 0

    def test_submit_button_visible(self):
        """Upload/submit button should be visible."""
        btn = self.page.locator("button[type='submit'], input[type='submit'], button:not([type])")
        expect(btn.first).to_be_visible()


class TestTeacherCSVUploadPage:
    """Tests for /import-teachers/ — the upload form."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/import-teachers/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Import")

    def test_file_input_visible(self):
        file_input = self.page.locator("input[type='file']")
        expect(file_input).to_be_attached()

    def test_submit_button_visible(self):
        btn = self.page.locator("button[type='submit'], input[type='submit'], button:not([type])")
        expect(btn.first).to_be_visible()
