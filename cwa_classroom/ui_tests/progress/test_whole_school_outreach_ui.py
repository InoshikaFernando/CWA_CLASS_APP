"""
UI tests for whole-school report coverage (CPP-422).

Scenarios:
1. The coverage switches are on the school form, and only on the school form.
2. The settings page says, in words, who is currently covered and who is not.
3. Switching coverage on changes that sentence.
4. The preview lists the families with nothing to show, with the reason.
5. A student with no subscription is shown as such, and told about the code.
6. With the email switched off, the cohort is still listed and said to reach
   nobody — a silent send is the failure this whole feature exists to end.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login, _make_user

pytestmark = pytest.mark.progress_reports

SETTINGS_URL = "/progress/reports/settings/"
PREVIEW_URL = "/progress/reports/preview/"


@pytest.fixture
def hoi(db, roles, school):
    from accounts.models import Role
    from classroom.models import SchoolTeacher

    user = _make_user("ui_outreach_hoi", Role.HEAD_OF_INSTITUTE)
    SchoolTeacher.objects.create(
        school=school, teacher=user, role="head_of_institute",
    )
    return user


@pytest.fixture
def unpaid_student(db, school, classroom):
    """A student of the school with no subscription and a parent on file.

    Deliberately not enrolled in the class: this is the child the old run could
    not see at all, and the one the whole-school cohort exists for.
    """
    from accounts.models import Role
    from classroom.models import ParentStudent, SchoolStudent

    student = _make_user("ui_outreach_unpaid", Role.STUDENT)
    student.first_name = "Nula"
    student.last_name = "Nodata"
    student.save(update_fields=["first_name", "last_name"])
    SchoolStudent.objects.get_or_create(school=school, student=student)

    parent = _make_user("ui_outreach_parent", Role.PARENT)
    ParentStudent.objects.create(
        parent=parent, student=student, school=school, is_active=True,
    )
    return student


def _cover(school, **flags):
    from progress.tests.factories import enable_reports

    values = {"weekly": True, "whole_school": True}
    values.update(flags)
    enable_reports(school, kind="school", **values)


def test_coverage_switches_are_on_the_school_form_only(
        page, live_server, hoi, classroom):
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{SETTINGS_URL}")

    school_scope = page.get_by_test_id("scope-school")
    expect(school_scope).to_contain_text("Cover every student in the school")
    expect(school_scope).to_contain_text(
        "Email parents when there is nothing to show")

    # The class form decides nothing about coverage, so it must not offer a
    # switch that would be saved and never read.
    class_scope = page.get_by_test_id("scope-classes")
    expect(class_scope).not_to_contain_text("Cover every student in the school")


def test_the_page_says_who_is_covered_before_and_after(
        page, live_server, hoi, classroom):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{SETTINGS_URL}")

    note = page.get_by_test_id("coverage-note")
    expect(note).to_contain_text("only students in a class with the report")
    expect(note).to_contain_text("hears nothing")

    _cover(classroom.school)
    page.goto(f"{live_server.url}{SETTINGS_URL}")

    note = page.get_by_test_id("coverage-note")
    expect(note).to_contain_text("every active student")
    expect(note).to_contain_text("emailed the reason")


def test_the_preview_lists_the_family_with_nothing_and_why(
        page, live_server, hoi, classroom, unpaid_student):
    _cover(classroom.school)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}?school={classroom.school.id}&period=weekly")

    expect(page.get_by_test_id("preview-no-data")).to_be_visible()
    row = page.get_by_test_id("preview-no-data-row").filter(
        has_text="Nula Nodata")
    expect(row).to_contain_text("No active subscription")
    expect(row).to_contain_text("signup link")


def test_the_preview_lists_nobody_when_coverage_is_off(
        page, live_server, hoi, classroom, unpaid_student):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}?school={classroom.school.id}&period=weekly")

    expect(page.get_by_test_id("preview-no-data")).to_have_count(0)


def test_the_discount_code_is_named_when_the_school_has_one(
        page, live_server, hoi, classroom, unpaid_student):
    from billing.models import DiscountCode

    DiscountCode.objects.create(code="UIWS40", discount_percent=40)
    school = classroom.school
    school.subscription_discount_code = "UIWS40"
    school.save(update_fields=["subscription_discount_code"])
    _cover(school)

    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}?school={school.id}&period=weekly")

    expect(page.get_by_test_id("preview-no-data")).to_contain_text("UIWS40")


def test_emailing_switched_off_is_said_out_loud(
        page, live_server, hoi, classroom, unpaid_student):
    _cover(classroom.school, email_parents_no_data=False)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}?school={classroom.school.id}&period=weekly")

    panel = page.get_by_test_id("preview-no-data")
    expect(panel).to_contain_text("Emailing is switched off")
    row = page.get_by_test_id("preview-no-data-row").filter(has_text="Nula Nodata")
    expect(row).to_contain_text("Nothing — emailing is off")


def test_an_empty_row_says_the_note_is_coming_not_that_nothing_is(
        page, live_server, hoi, classroom, enrolled_student):
    """CPP-426 — the table and the panel below it must agree.

    This row used to read "nothing will be sent" while the panel underneath
    said a note was going to the same family.
    """
    _cover(classroom.school)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}?school={classroom.school.id}&period=weekly")

    row = page.get_by_test_id("preview-row").first
    expect(row).to_contain_text("their parents will be sent a")
    expect(row).to_contain_text("Parents (note)")
    expect(row).not_to_contain_text("nothing will be sent")


def test_with_coverage_off_the_row_keeps_the_original_wording(
        page, live_server, hoi, classroom, enrolled_student):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}?school={classroom.school.id}&period=weekly")

    expect(page.get_by_test_id("preview-row").first).to_contain_text(
        "nothing will be sent")
