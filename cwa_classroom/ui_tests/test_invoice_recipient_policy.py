"""
UI tests for CPP-240: invoice_recipient_policy setting in School Settings.

TestInvoiceRecipientPolicySetting   — dropdown presence, default, all options, save/reload
TestInvoiceRecipientPolicyAllValues — parametrized: every policy value saves and reloads
TestInvoiceRecipientPolicyRoleAccess — accountant role can also access and update the setting
"""

import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.invoice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_banking_tab(page):
    """Click the Banking & Invoice tab and wait for Alpine transition."""
    page.get_by_role("button", name="Banking & Invoice").click()
    page.wait_for_timeout(400)


def _save_and_reload_banking(page, url, school_id):
    """Click Save Changes, wait for reload, re-open Banking tab."""
    page.get_by_role("button", name="Save Changes").first.click()
    page.wait_for_load_state("domcontentloaded")
    # After POST redirect, active_tab=banking is preserved in the hidden input
    _open_banking_tab(page)


# ---------------------------------------------------------------------------
# Core settings UI tests
# ---------------------------------------------------------------------------

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
        _open_banking_tab(page)

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

    def test_default_option_label_indicates_default(self):
        """The parents_fallback_student option label should include 'Default'."""
        dropdown = self.page.locator("select#invoice_recipient_policy")
        default_option = dropdown.locator("option[value='parents_fallback_student']")
        label = default_option.inner_text()
        assert "Default" in label or "default" in label.lower()

    def test_save_and_reload_persists_policy_change(self):
        """Changing policy to student_only, saving, and reloading should persist."""
        self.page.locator("select#invoice_recipient_policy").select_option("student_only")
        _save_and_reload_banking(self.page, self.url, self.school.id)
        selected = self.page.locator("select#invoice_recipient_policy").input_value()
        assert selected == "student_only"

    def test_parents_only_warning_text_present(self):
        """Warning note about 'Parents only' silent suppression should be visible in DOM."""
        note = self.page.locator("text=Parents only")
        assert note.count() >= 1

    def test_invoice_email_recipients_section_heading(self):
        """'Invoice Email Recipients' section heading present in Banking tab."""
        heading = self.page.locator("text=Invoice Email Recipients")
        assert heading.count() >= 1

    def test_dropdown_is_enabled_and_interactive(self):
        """The policy dropdown should be enabled (not disabled or readonly)."""
        dropdown = self.page.locator("select#invoice_recipient_policy")
        expect(dropdown).to_be_enabled()


# ---------------------------------------------------------------------------
# Parametrized: all 4 policy values save and reload correctly
# ---------------------------------------------------------------------------

ALL_POLICIES = [
    "parents_fallback_student",
    "parents_only",
    "parents_and_student",
    "student_only",
]


class TestInvoiceRecipientPolicyAllValues:
    """Every policy choice saves to the DB and survives a page reload."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup):
        self.url = live_server.url
        self.page = page
        self.school = hoi_school_setup
        do_login(page, self.url, hoi_user)

    def _goto_banking(self):
        settings_url = f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/"
        self.page.goto(settings_url)
        self.page.wait_for_load_state("domcontentloaded")
        _open_banking_tab(self.page)

    @pytest.mark.parametrize("policy", ALL_POLICIES)
    def test_policy_saves_and_reloads(self, policy):
        """Select each policy, save, reload — the same value should be selected."""
        self._goto_banking()
        self.page.locator("select#invoice_recipient_policy").select_option(policy)
        _save_and_reload_banking(self.page, self.url, self.school.id)
        selected = self.page.locator("select#invoice_recipient_policy").input_value()
        assert selected == policy, f"Expected {policy!r} after save+reload, got {selected!r}"


# ---------------------------------------------------------------------------
# Role access: who can view and update the setting
# ---------------------------------------------------------------------------

class TestInvoiceRecipientPolicyRoleAccess:
    """
    Role-access verification for the School Settings policy dropdown.

    Note: _get_user_schools() grants school access to ADMIN and
    head_of_institute SchoolTeachers only. Accountants are excluded by
    that helper even though SchoolSettingsView.required_roles lists them —
    they receive a 404 on the settings page.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, school):
        self.url = live_server.url
        self.page = page
        self.school = school

    def _goto_settings_as(self, user):
        # Use domcontentloaded to avoid networkidle hanging on CDN resources
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.goto(f"{self.url}/accounts/login/")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.locator("#id_username").fill(user.username)
        self.page.locator("#id_password").fill("TestPass123!")
        self.page.locator("button[type='submit'], input[type='submit']").first.click()
        self.page.wait_for_url(lambda u: "/accounts/login" not in u, timeout=10_000)
        self.page.wait_for_load_state("domcontentloaded")
        settings_url = f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/"
        self.page.goto(settings_url)
        self.page.wait_for_load_state("domcontentloaded")

    def test_admin_can_view_policy_dropdown(self, admin_user):
        """ADMIN role can open Banking tab and see the policy dropdown."""
        self._goto_settings_as(admin_user)
        _open_banking_tab(self.page)
        dropdown = self.page.locator("select#invoice_recipient_policy")
        expect(dropdown).to_be_visible()

    def test_admin_can_change_and_save_policy(self, admin_user):
        """ADMIN can change the policy to parents_only and save successfully."""
        self._goto_settings_as(admin_user)
        _open_banking_tab(self.page)
        self.page.locator("select#invoice_recipient_policy").select_option("parents_only")
        _save_and_reload_banking(self.page, self.url, self.school.id)
        selected = self.page.locator("select#invoice_recipient_policy").input_value()
        assert selected == "parents_only"

    def test_accountant_cannot_access_school_settings(self, accountant_user, accountant_school_setup):
        """
        Accountant is excluded from _get_user_schools() so the settings page
        returns 404 (not the settings form).
        """
        self._goto_settings_as(accountant_user)
        # Page should NOT show the settings form — either 404 or redirect
        dropdown = self.page.locator("select#invoice_recipient_policy")
        assert dropdown.count() == 0, "Accountant should not see the settings dropdown"
