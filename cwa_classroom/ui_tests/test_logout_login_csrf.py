"""UI tests for switching accounts — logging out of one user and into another.

Signing in rotates Django's CSRF secret, so any sign-in form the browser still
holds from before that login carries a token the server no longer accepts.
Submitting it used to dump the user on the bare "CSRF verification failed.
Request aborted." page, with no way to complete the sign-in (CPP-36).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from accounts.models import Role

from .conftest import TEST_PASSWORD, _make_user, do_login, do_logout

pytestmark = pytest.mark.dashboard


def _submit_login_form(page, base_url: str, username: str, token: str) -> None:
    """Post the sign-in form with a token the browser is still holding."""
    page.evaluate(
        """([action, username, password, token]) => {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = action;
            for (const [name, value] of Object.entries(
                {csrfmiddlewaretoken: token, username, password})) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = name;
                input.value = value;
                form.appendChild(input);
            }
            document.body.appendChild(form);
            form.submit();
        }""",
        [f"{base_url}/accounts/login/", username, TEST_PASSWORD, token],
    )
    page.wait_for_load_state("domcontentloaded")


class TestSwitchingAccounts:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db, roles):
        self.url = live_server.url
        self.page = page
        self.user_a = _make_user("csrf_switch_a", Role.TEACHER)
        self.user_b = _make_user("csrf_switch_b", Role.TEACHER)

    def test_logout_then_login_as_another_user(self):
        do_login(self.page, self.url, self.user_a)
        do_logout(self.page, self.url)
        do_login(self.page, self.url, self.user_b)      # raises if it 403s
        expect(self.page.locator("body")).not_to_contain_text("CSRF verification failed")

    def test_stale_sign_in_form_offers_a_retry(self):
        """The sign-in page the browser kept from before the first login."""
        self.page.goto(f"{self.url}/accounts/login/")
        self.page.wait_for_load_state("domcontentloaded")
        stale = self.page.locator("input[name='csrfmiddlewaretoken']").first.get_attribute("value")

        do_login(self.page, self.url, self.user_a)      # rotates the CSRF secret
        do_logout(self.page, self.url)

        _submit_login_form(self.page, self.url, self.user_b.username, stale)

        expect(self.page.locator("body")).not_to_contain_text("CSRF verification failed")
        expect(self.page.locator("body")).to_contain_text("session had already ended")

        # The freshly-tokened page it lands on completes the sign-in.
        self.page.locator("#id_username").fill(self.user_b.username)
        self.page.locator("#id_password").fill(TEST_PASSWORD)
        self.page.locator("button[type='submit'], input[type='submit']").first.click()
        self.page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)

    def test_stale_log_out_button_still_logs_out(self):
        """A tab left open from an earlier session must still be able to sign out."""
        self.page.goto(f"{self.url}/accounts/login/")
        self.page.wait_for_load_state("domcontentloaded")
        stale = self.page.locator("input[name='csrfmiddlewaretoken']").first.get_attribute("value")

        do_login(self.page, self.url, self.user_a)

        self.page.evaluate(
            """([action, token]) => {
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = action;
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'csrfmiddlewaretoken';
                input.value = token;
                form.appendChild(input);
                document.body.appendChild(form);
                form.submit();
            }""",
            [f"{self.url}/accounts/logout/", stale],
        )
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("body")).not_to_contain_text("CSRF verification failed")

        # Really signed out: a protected page bounces to the login form.
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("domcontentloaded")
        assert "/accounts/login" in self.page.url
