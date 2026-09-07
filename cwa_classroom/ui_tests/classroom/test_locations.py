"""CPP-371 — UI tests for institute class locations.

Exercises the Locations management page (add / list / online flag) and the
Locations quick-stat link on the school detail page.
"""

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.sidebar


class TestLocationManagement:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        self.school = school
        do_login(page, self.url, admin_user)

    def _locations_url(self):
        return f"{self.url}/admin-dashboard/schools/{self.school.id}/locations/"

    def test_add_location_form_visible(self):
        self.page.goto(self._locations_url())
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("input[name='name']").first).to_be_visible()
        expect(self.page.locator("textarea[name='address']").first).to_be_visible()
        expect(self.page.locator("input[name='is_online']").first).to_be_visible()

    def test_create_location_persists(self):
        self.page.goto(self._locations_url())
        self.page.wait_for_load_state("networkidle")
        self.page.locator("input[name='name']").first.fill("Downtown Campus")
        self.page.locator("textarea[name='address']").first.fill("42 Queen St")
        self.page.locator("input[name='is_online']").first.check()
        self.page.locator("button:has-text('Add Location')").click()
        self.page.wait_for_load_state("networkidle")

        expect(self.page.locator("body")).to_contain_text("Downtown Campus")

        from classroom.models import Location
        loc = Location.objects.get(school=self.school, name="Downtown Campus")
        assert loc.address == "42 Queen St"
        assert loc.is_online is True

    def test_locations_link_on_school_detail(self):
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/")
        self.page.wait_for_load_state("networkidle")
        link = self.page.locator(
            f"a[href='/admin-dashboard/schools/{self.school.id}/locations/']"
        )
        expect(link.first).to_be_visible()

    def test_delete_location(self):
        from classroom.models import Location
        loc = Location.objects.create(school=self.school, name="Temp Venue")
        self.page.goto(self._locations_url())
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("body")).to_contain_text("Temp Venue")

        self.page.on("dialog", lambda dialog: dialog.accept())
        # The delete control is the submit button inside the form carrying the
        # hidden action=delete input (the edit Save button is x-cloaked).
        delete_form = self.page.locator("form:has(input[value='delete'])").first
        delete_form.locator("button[type='submit']").click()
        self.page.wait_for_load_state("networkidle")

        assert not Location.objects.filter(id=loc.id).exists()
