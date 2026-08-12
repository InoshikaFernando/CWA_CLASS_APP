"""
Playwright UI tests for the Manage Classes page update (CPP-372).

Covers ``HoDManageClassesView`` (/department/manage-classes/):

  - Default view is Grid (the grid toggle button is active and the container
    carries the ``cwa-grid`` class on first load).
  - Action button captions (Edit / Assign Staff / Delete) are hidden in grid
    view, leaving icon-only buttons.
  - The tile shows the class location (school) and level.
  - The sort control reorders the list (by level here).
"""

from __future__ import annotations

from datetime import time

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


MANAGE_URL = "/department/manage-classes/"


@pytest.fixture
def two_classes(db, school, department, subject):
    """Two classes in the HoD's department with different names and levels."""
    from classroom.models import ClassRoom, Level

    lvl3, _ = Level.objects.get_or_create(
        level_number=3, defaults={"display_name": "Level 3", "subject": subject},
    )
    lvl6, _ = Level.objects.get_or_create(
        level_number=6, defaults={"display_name": "Level 6", "subject": subject},
    )
    # "Zed" carries the lower level so name-order and level-order differ.
    zed = ClassRoom.objects.create(
        name="Zed Class", school=school, department=department, subject=subject,
        day="tuesday", start_time=time(11, 0),
    )
    zed.levels.add(lvl3)
    amy = ClassRoom.objects.create(
        name="Amy Class", school=school, department=department, subject=subject,
        day="thursday", start_time=time(13, 0),
    )
    amy.levels.add(lvl6)
    return zed, amy


class TestManageClassesUI:

    @pytest.mark.django_db(transaction=True)
    def test_defaults_to_grid_view(self, page: Page, live_server, hod_user, two_classes):
        do_login(page, live_server.url, hod_user)
        page.goto(f"{live_server.url}{MANAGE_URL}")
        page.wait_for_load_state("domcontentloaded")

        # Container is in grid mode on first load.
        container = page.locator("#hod-classes")
        assert "cwa-grid" in (container.get_attribute("class") or "")
        # The grid toggle button is the active one.
        grid_btn = page.locator('[data-view-toggle="hod-classes"] [data-view-btn="grid"]')
        assert "is-active" in (grid_btn.get_attribute("class") or "")

    @pytest.mark.django_db(transaction=True)
    def test_grid_hides_button_captions(self, page: Page, live_server, hod_user, two_classes):
        do_login(page, live_server.url, hod_user)
        page.goto(f"{live_server.url}{MANAGE_URL}")
        page.wait_for_load_state("domcontentloaded")

        # In grid view the caption spans are hidden (icon-only buttons).
        label = page.locator("#hod-classes .cwa-btn-label").first
        expect(label).to_be_hidden()

        # Switching to list view reveals the captions again.
        page.locator('[data-view-toggle="hod-classes"] [data-view-btn="list"]').click()
        expect(page.locator("#hod-classes .cwa-btn-label").first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_tile_shows_location_and_level(self, page: Page, live_server, hod_user, school, two_classes):
        do_login(page, live_server.url, hod_user)
        page.goto(f"{live_server.url}{MANAGE_URL}")
        page.wait_for_load_state("domcontentloaded")

        body = page.locator("#hod-classes")
        expect(body).to_contain_text(school.name)   # location
        expect(body).to_contain_text("Level 3")     # level
        expect(body).to_contain_text("Level 6")

    @pytest.mark.django_db(transaction=True)
    def test_sort_by_level_reorders(self, page: Page, live_server, hod_user, two_classes):
        do_login(page, live_server.url, hod_user)
        page.goto(f"{live_server.url}{MANAGE_URL}?sort=level")
        page.wait_for_load_state("domcontentloaded")

        # Zed (Level 3) should appear before Amy (Level 6) when sorted by level.
        html = page.content()
        assert html.index("Zed Class") < html.index("Amy Class")
        # The control reflects the active sort.
        assert page.locator("#sort-select").input_value() == "level"
