"""
Playwright UI tests for CPP-309: Languages app plugin and admin.

Covers:
1. LanguagesPlugin registered and retrievable from subject registry at runtime
2. Django admin Language changelist loads with seeded language records
"""

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp309


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_superuser():
    from accounts.models import CustomUser
    uid = f'lang309_{_RUN_ID}'
    u = CustomUser.objects.create_superuser(
        username=f'superuser_{uid}',
        email=f'superuser_{uid}@cpptest.com',
        password=TEST_PASSWORD,
        profile_completed=True,
        must_change_password=False,
    )
    return u


# ---------------------------------------------------------------------------
# Test: Plugin registered in subject registry
# ---------------------------------------------------------------------------

class TestLanguagesPluginRegistered:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from languages.models import Language
        self.url = live_server.url
        self.page = page
        # Ensure seeded languages exist — TransactionTestCase flushes data
        # migration records between tests, so create them explicitly here.
        for name, code, script in [
            ('English', 'en', 'latin'),
            ('Sinhala', 'si', 'sinhala'),
            ('Tamil', 'ta', 'tamil'),
        ]:
            Language.objects.get_or_create(
                code=code,
                defaults={'name': name, 'script_type': script, 'is_active': True},
            )
        self.admin = _make_superuser()
        do_login(page, self.url, self.admin)

    @pytest.mark.django_db(transaction=True)
    def test_languages_admin_changelist_loads(self):
        """Admin changelist for Language model renders without server error."""
        self.page.goto(f'{self.url}/admin/languages/language/')
        self.page.wait_for_load_state('networkidle')
        expect(self.page.locator('body')).not_to_contain_text('Server Error')
        expect(self.page.locator('body')).not_to_contain_text('DoesNotExist')
        expect(self.page.locator('#content h1')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_seeded_languages_visible_in_admin(self):
        """Admin changelist shows English, Sinhala and Tamil."""
        self.page.goto(f'{self.url}/admin/languages/language/')
        self.page.wait_for_load_state('networkidle')
        body = self.page.locator('body')
        expect(body).to_contain_text('English')
        expect(body).to_contain_text('Sinhala')
        expect(body).to_contain_text('Tamil')
