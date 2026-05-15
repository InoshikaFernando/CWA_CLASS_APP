"""UI tests for CPP-240: invoice_recipient_policy setting in School Settings."""

import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.invoice


class TestInvoiceRecipientPolicySetting:
    """Banking & Invoice tab — invoice_recipient_policy dropdown UI."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup):
        self.url = live_server.url
        self.page = page
        self.school = hoi_school_setup
        do_login(page, self.url, hoi_user)
        settings_url = f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/"
        page.goto(settings_url)
        page.wait_for_load_state("domcontentloaded")
        # Navigate to Banking & Invoice tab
        page.get_by_role("button", name="Banking & Invoice").click()
        page.wait_for_timeout(300)  # Alpine transition

    def test_banking_tab_visible(self):
        """Banking & Invoice section heading should be visible after tab click."""
        expect(self.page.get_by_text("Banking & Invoice Settings")).to_be_visible()

    def test_recipient_policy_dropdown_present(self):
        """invoice_recipient_policy select element should exist in the Banking tab."""
        dropdown = self.page.locator("select#invoice_recipient_policy")
        expect(dropdown).to_be_visible()

    def test_all_four_policy_options_present(self):
        """All 4 policy choices should be present in the dropdown."""
        dropdown = self.page.locator("select#invoice_recipient_policy")
        options = dropdown.locator("option").all()
        values = [opt.get_attribute("value") for opt in options]
        assert "parents_fallback_student" in values
        assert "parents_only" in values
        assert "parents_and_student" in values
        assert "student_only" in values

    def test_default_policy_is_parents_fallback_student(self):
        """Default selected option should be parents_fallback_student."""
        dropdown = self.page.locator("select#invoice_recipient_policy")
        selected = dropdown.input_value()
        assert selected == "parents_fallback_student"

    def test_save_and_reload_persists_policy_change(self):
        """Changing policy to student_only, saving, and reloading should persist."""
        self.page.locator("select#invoice_recipient_policy").select_option("student_only")
        self.page.get_by_role("button", name="Save Changes").first.click()
        self.page.wait_for_load_state("domcontentloaded")

        # Re-open Banking tab after reload
        self.page.get_by_role("button", name="Banking & Invoice").click()
        self.page.wait_for_timeout(300)

        selected = self.page.locator("select#invoice_recipient_policy").input_value()
        assert selected == "student_only"

    def test_parents_only_warning_text_present(self):
        """Warning note about 'Parents only' silent suppression should be visible."""
        # Note is always in DOM (no conditional rendering)
        note = self.page.locator("text=Parents only")
        assert note.count() >= 1
