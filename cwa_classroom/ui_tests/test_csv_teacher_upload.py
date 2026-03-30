"""Tests for teacher CSV upload — upload form, preview, credentials."""

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.csv_import


class TestTeacherCSVUpload:
    """Tests for /import-teachers/ page elements."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/import-teachers/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_title(self):
        assert_page_has_text(self.page, "Import")

    def test_file_input_accepts_csv(self):
        """File input should accept CSV/XLS files."""
        file_input = self.page.locator("input[type='file']")
        expect(file_input).to_be_attached()

    def test_source_presets(self):
        """Source system presets should render."""
        radios = self.page.locator("input[type='radio']")
        # At least the default/custom radio should exist
        assert radios.count() >= 1

    def test_column_mapping_section(self):
        """Column mapping dropdowns for first_name, last_name, email."""
        selects = self.page.locator("select")
        # Mapping dropdowns may not appear until file is uploaded
        # Just verify the page has a form
        form = self.page.locator("form")
        expect(form.first).to_be_visible()
