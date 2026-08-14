"""
Playwright UI test for per-location colour on the Classes page tiles (CPP-373).

Mirrors the CPP-372 manage-classes tests (``test_cpp372_manage_classes_ui.py``).
Asserts that a class whose location carries a colour renders a tile with that
colour as its left border, and that a class without a coloured location falls
back to the default border (no location-colour attribute / left accent).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


MANAGE_URL = "/department/manage-classes/"
LOC_COLOR = "#f97316"  # a distinctive orange
# The browser reports colours as rgb(); #f97316 == rgb(249, 115, 22).
LOC_COLOR_RGB = "rgb(249, 115, 22)"


@pytest.fixture
def coloured_and_plain_classes(db, school, department, subject):
    """One class at a coloured location, one class with no location."""
    from classroom.models import ClassRoom, Location

    loc = Location.objects.create(
        school=school, name="Orange Hall", color=LOC_COLOR,
    )
    ClassRoom.objects.create(
        name="Coloured Class", school=school, department=department,
        subject=subject, location=loc,
    )
    ClassRoom.objects.create(
        name="Plain Class", school=school, department=department,
        subject=subject,
    )
    return loc


class TestLocationColorTileUI:

    @pytest.mark.django_db(transaction=True)
    def test_tile_carries_location_color(
        self, page: Page, live_server, hod_user, coloured_and_plain_classes,
    ):
        do_login(page, live_server.url, hod_user)
        page.goto(f"{live_server.url}{MANAGE_URL}")
        page.wait_for_load_state("domcontentloaded")

        # The coloured class's tile exposes the location colour.
        tile = page.locator('#hod-classes [data-location-color]')
        expect(tile).to_have_count(1)
        assert tile.get_attribute("data-location-color") == LOC_COLOR

        # ...and the browser actually paints the left border in that colour.
        border = tile.evaluate(
            "el => getComputedStyle(el).borderLeftColor"
        )
        assert border == LOC_COLOR_RGB

    @pytest.mark.django_db(transaction=True)
    def test_plain_tile_has_no_location_color(
        self, page: Page, live_server, hod_user, coloured_and_plain_classes,
    ):
        do_login(page, live_server.url, hod_user)
        page.goto(f"{live_server.url}{MANAGE_URL}")
        page.wait_for_load_state("domcontentloaded")

        # Exactly one of the two class tiles carries a location colour; the
        # plain class falls back to the default border.
        expect(page.locator('#hod-classes [data-location-color]')).to_have_count(1)
