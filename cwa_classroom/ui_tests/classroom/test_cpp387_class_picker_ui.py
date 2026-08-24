"""
Playwright UI test for the class picker in the Add Student modal (CPP-387).

Two classes can share a name and a subject, so the picker has to name when each
one runs and where it is held — otherwise an admin adding a student has no way
to tell the Tuesday class from the Thursday one. Asserts the day/time and the
location are visible on each row, and that a class with neither says so rather
than rendering a row identical to its twin.
"""

from __future__ import annotations

from datetime import time

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def same_named_classes(db, school, department, subject):
    """Two 'Year 10 Maths' classes differing only by day and location."""
    from classroom.models import ClassRoom, Location

    hamilton = Location.objects.create(school=school, name="Hamilton Campus")
    rotorua = Location.objects.create(school=school, name="Rotorua Campus")
    tuesday = ClassRoom.objects.create(
        name="Year 10 Maths", school=school, department=department,
        subject=subject, location=hamilton, day="tuesday",
        start_time=time(16, 0), end_time=time(17, 30),
    )
    thursday = ClassRoom.objects.create(
        name="Year 10 Maths", school=school, department=department,
        subject=subject, location=rotorua, day="thursday",
        start_time=time(9, 0), end_time=time(10, 30),
    )
    unscheduled = ClassRoom.objects.create(
        name="Year 10 Maths", school=school, department=department,
        subject=subject,
    )
    return tuesday, thursday, unscheduled


def _open_add_student_modal(page: Page, live_server_url: str, school) -> None:
    page.goto(f"{live_server_url}/admin-dashboard/schools/{school.id}/students/")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_role("button", name="Add Student").click()


class TestAddStudentClassPickerUI:

    @pytest.mark.django_db(transaction=True)
    def test_each_class_row_shows_its_time_and_location(
        self, page: Page, live_server, admin_user, school, same_named_classes,
    ):
        do_login(page, live_server.url, admin_user)
        _open_add_student_modal(page, live_server.url, school)

        tuesday, thursday, _ = same_named_classes
        tuesday_row = page.locator(f'label:has(input[name="class_ids"][value="{tuesday.id}"])')
        thursday_row = page.locator(f'label:has(input[name="class_ids"][value="{thursday.id}"])')

        expect(tuesday_row).to_contain_text("Tuesday 4:00 PM – 5:30 PM")
        expect(tuesday_row).to_contain_text("Hamilton Campus")
        expect(thursday_row).to_contain_text("Thursday 9:00 AM – 10:30 AM")
        expect(thursday_row).to_contain_text("Rotorua Campus")

    @pytest.mark.django_db(transaction=True)
    def test_class_without_schedule_or_location_says_so(
        self, page: Page, live_server, admin_user, school, same_named_classes,
    ):
        do_login(page, live_server.url, admin_user)
        _open_add_student_modal(page, live_server.url, school)

        _, _, unscheduled = same_named_classes
        row = page.locator(f'label:has(input[name="class_ids"][value="{unscheduled.id}"])')
        expect(row).to_contain_text("Time not set")
        expect(row).to_contain_text("Location not set")

    @pytest.mark.django_db(transaction=True)
    def test_the_checked_class_is_the_one_the_student_joins(
        self, page: Page, live_server, admin_user, school, same_named_classes,
    ):
        """The extra detail must not shift which checkbox the click lands on."""
        from classroom.models import ClassStudent

        do_login(page, live_server.url, admin_user)
        _open_add_student_modal(page, live_server.url, school)

        _, thursday, _ = same_named_classes
        page.fill('input[name="first_name"]', "Picker")
        page.fill('input[name="last_name"]', "Student")
        page.fill('input[name="email"]', "picker.student@test.local")
        page.fill('input[name="password"]', "securepass1")
        page.locator(f'input[name="class_ids"][value="{thursday.id}"]').check()
        page.locator('form:has(input[name="class_ids"]) button[type="submit"]').last.click()
        page.wait_for_load_state("domcontentloaded")

        enrolled = list(
            ClassStudent.objects.filter(
                student__email="picker.student@test.local", is_active=True,
            ).values_list("classroom_id", flat=True)
        )
        assert enrolled == [thursday.id]
