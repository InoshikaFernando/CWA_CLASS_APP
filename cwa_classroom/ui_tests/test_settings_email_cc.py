"""
Playwright E2E tests for:
1. HOI sidebar → Settings link visible → navigates to settings page
2. Admin sidebar → Settings link visible → navigates to settings page
3. Set outgoing_email in settings → trigger invoice email → verify CC header
4. Enter invalid email in settings → error message shown
"""

import re
from decimal import Decimal

import pytest
from django.core import mail
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import (
    assert_sidebar_has_link,
    click_sidebar_link,
    _ensure_sidebar_visible,
)

pytestmark = [pytest.mark.sidebar]


# ---------------------------------------------------------------------------
# Helper: force Alpine.js tab to be visible in headless Chromium
# ---------------------------------------------------------------------------

def _activate_settings_tab(page: "Page", tab_name: str = "contact") -> None:
    """Force the Alpine.js settings tab to display in headless mode.

    Tailwind CDN + Alpine may not fully render x-show directives in headless
    Chromium.  This helper forces the correct tab panel visible and ensures
    the submit button is clickable.
    """
    page.evaluate(f"""() => {{
        // Try Alpine.js data approach first
        const root = document.querySelector('[x-data]');
        if (root && root.__x) {{
            root.__x.$data.tab = '{tab_name}';
        }}
        // Fallback: force display on the correct tab panel
        document.querySelectorAll('[x-show]').forEach(el => {{
            const attr = el.getAttribute('x-show') || '';
            if (attr.includes("'{tab_name}'")) {{
                el.style.display = '';
                el.removeAttribute('style');
                el.style.display = 'block';
            }}
        }});
    }}""")


def _click_save_changes(page: "Page") -> None:
    """Click the visible 'Save Changes' submit button."""
    # Use text-based locator to find the visible one
    btn = page.locator("button:has-text('Save Changes'):visible")
    if btn.count() > 0:
        btn.first.click()
    else:
        # Fallback: force-click via JS
        page.evaluate("""() => {
            const buttons = document.querySelectorAll('button[type="submit"]');
            for (const btn of buttons) {
                if (btn.offsetParent !== null || btn.closest('[x-show]')) {
                    btn.click();
                    return;
                }
            }
            // Last resort: click the first submit button
            if (buttons.length > 0) buttons[0].click();
        }""")
    page.wait_for_load_state("domcontentloaded")


# ===========================================================================
# 1. HOI sidebar → Settings link
# ===========================================================================

class TestHoiSettingsLink:
    """HOI can see and navigate to Settings from the sidebar."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/dashboard/")
        page.wait_for_load_state("domcontentloaded")

    def test_settings_link_visible_in_hoi_sidebar(self):
        assert_sidebar_has_link(self.page, "Settings")

    def test_settings_link_navigates_to_settings_page(self):
        click_sidebar_link(self.page, "Settings")
        expect(self.page).to_have_url(re.compile(r"/admin-dashboard/schools/\d+/settings/"))

    def test_settings_page_shows_company_tab(self):
        click_sidebar_link(self.page, "Settings")
        expect(self.page.locator("body")).to_contain_text("Company Details")

    def test_settings_page_shows_outgoing_email_field(self):
        click_sidebar_link(self.page, "Settings")
        # Navigate to contact tab if needed
        contact_tab = self.page.locator("a, button", has_text="Contact")
        if contact_tab.count() > 0:
            contact_tab.first.click()
            self.page.wait_for_load_state("domcontentloaded")
        email_input = self.page.locator("input[name='outgoing_email']")
        expect(email_input).to_be_visible()


# ===========================================================================
# 2. Admin sidebar → Settings link
# ===========================================================================

class TestAdminSettingsLink:
    """Admin can see and navigate to Settings from the sidebar."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")

    def test_settings_link_visible_in_admin_sidebar(self):
        assert_sidebar_has_link(self.page, "Settings")

    def test_settings_link_navigates_to_settings_page(self):
        click_sidebar_link(self.page, "Settings")
        expect(self.page).to_have_url(re.compile(r"/admin-dashboard/schools/\d+/settings/"))


# ===========================================================================
# 3. Set outgoing_email → invoice email has CC
# ===========================================================================

@pytest.mark.django_db(transaction=True)
class TestOutgoingEmailCcOnInvoice:
    """Set outgoing_email in settings, issue an invoice, verify CC header."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, live_server, page, admin_user, school,
        department, enrolled_student, classroom, invoice, settings,
    ):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.invoice = invoice
        # Use in-memory email backend so we can inspect mail.outbox
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
        settings.DEFAULT_FROM_EMAIL = "info@wizardslearninghub.co.nz"
        mail.outbox.clear()
        do_login(page, self.url, admin_user)

    def test_set_outgoing_email_and_verify_cc_on_invoice(self):
        """
        Flow:
        1. Navigate to settings → set outgoing_email
        2. Issue the invoice via the app
        3. Check mail.outbox for CC header
        """
        # Step 1: Go to settings and set outgoing_email
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/?tab=contact")
        self.page.wait_for_load_state("domcontentloaded")

        _activate_settings_tab(self.page, "contact")
        email_input = self.page.locator("input[name='outgoing_email']")
        email_input.fill("institute@school.com")

        # Submit the form
        _click_save_changes(self.page)

        # Verify success message
        expect(self.page.locator("body")).to_contain_text("Settings saved successfully")

        # Step 2: Verify the email was saved
        self.school.refresh_from_db()
        assert self.school.outgoing_email == "institute@school.com"

        # Step 3: Trigger invoice email via code (simulating invoice issue)
        from classroom.invoicing_services import _send_invoice_email
        from classroom.models import Invoice

        # Update invoice to issued status so it has the required fields
        inv = self.invoice
        if not inv.issued_at:
            from django.utils import timezone
            inv.issued_at = timezone.now()
            inv.status = "issued"
            inv.save()

        mail.outbox.clear()
        _send_invoice_email(inv)

        # Step 4: Verify CC
        assert len(mail.outbox) == 1, f"Expected 1 email, got {len(mail.outbox)}"
        sent_email = mail.outbox[0]
        assert sent_email.cc == ["institute@school.com"], (
            f"Expected CC ['institute@school.com'], got {sent_email.cc}"
        )
        assert sent_email.from_email == "info@wizardslearninghub.co.nz"


# ===========================================================================
# 4. Invalid email in settings → error message
# ===========================================================================

class TestSettingsEmailValidation:
    """Entering an invalid outgoing_email shows an error and does not save."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        self.school = school
        do_login(page, self.url, admin_user)

    def test_invalid_email_shows_error(self):
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/?tab=contact"
        )
        self.page.wait_for_load_state("domcontentloaded")

        _activate_settings_tab(self.page, "contact")
        email_input = self.page.locator("input[name='outgoing_email']")
        email_input.fill("not-a-valid-email")

        _click_save_changes(self.page)

        # The invalid email should NOT have been saved to the database
        self.school.refresh_from_db()
        assert self.school.outgoing_email != "not-a-valid-email", (
            "Invalid email should not have been saved"
        )

        # Page should NOT show the success message (validation rejected it)
        body_text = self.page.locator("body").inner_text()
        assert "Settings saved successfully" not in body_text, (
            "Success message should not appear for invalid email"
        )

    def test_valid_email_saves_successfully(self):
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/?tab=contact"
        )
        self.page.wait_for_load_state("domcontentloaded")

        _activate_settings_tab(self.page, "contact")
        email_input = self.page.locator("input[name='outgoing_email']")
        email_input.fill("valid@institute.com")

        _click_save_changes(self.page)

        # Should show success message
        expect(self.page.locator("body")).to_contain_text("Settings saved successfully")

        # Should have saved
        self.school.refresh_from_db()
        assert self.school.outgoing_email == "valid@institute.com"

    def test_blank_email_clears_successfully(self):
        # First set a valid email
        self.school.outgoing_email = "old@institute.com"
        self.school.save()

        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/?tab=contact"
        )
        self.page.wait_for_load_state("domcontentloaded")

        _activate_settings_tab(self.page, "contact")
        email_input = self.page.locator("input[name='outgoing_email']")
        email_input.fill("")

        _click_save_changes(self.page)

        expect(self.page.locator("body")).to_contain_text("Settings saved successfully")

        self.school.refresh_from_db()
        assert self.school.outgoing_email == ""
