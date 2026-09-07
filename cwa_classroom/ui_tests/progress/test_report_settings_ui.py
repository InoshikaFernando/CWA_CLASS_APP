"""
UI tests for the progress report settings page (CPP-388 follow-up).

Scenarios:
1. A Head of Institute reaches the page from the sidebar.
2. Switching the school on is reflected in the per-class badges.
3. A class override beats the school switch, and the badge says which level won.
4. A class that inherits stays collapsed; one with its own rule is expanded.
5. A student in an unconfigured school has no "My Reports" link at all.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from ..conftest import do_login, _make_user
from ..helpers import assert_sidebar_has_link, assert_sidebar_missing_link

pytestmark = pytest.mark.progress_reports

SETTINGS_URL = "/progress/reports/settings/"


@pytest.fixture
def hoi(db, roles, school):
    from accounts.models import Role
    from classroom.models import SchoolTeacher

    user = _make_user("ui_settings_hoi", Role.HEAD_OF_INSTITUTE)
    SchoolTeacher.objects.create(
        school=school, teacher=user, role="head_of_institute",
    )
    return user


def _save_school(page, live_server, weekly="on"):
    page.goto(f"{live_server.url}{SETTINGS_URL}")
    scope = page.get_by_test_id("scope-school")
    scope.get_by_role("radio", name="On").first.check()
    scope.get_by_role("button", name="Save school settings").click()


def test_hoi_reaches_the_settings_page_from_the_sidebar(page, live_server, hoi,
                                                        classroom):
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}/admin-dashboard/")

    assert_sidebar_has_link(page, "Report Automation")
    page.goto(f"{live_server.url}{SETTINGS_URL}")
    expect(page.get_by_test_id("report-settings")).to_be_visible()


def test_reports_start_switched_off(page, live_server, hoi, classroom):
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{SETTINGS_URL}")

    expect(page.get_by_test_id("enabled-count")).to_have_text("0")
    expect(page.get_by_test_id("class-row").first).to_contain_text("Off")


def test_switching_the_school_on_enables_its_classes(page, live_server, hoi,
                                                     classroom):
    do_login(page, live_server.url, hoi)
    _save_school(page, live_server)

    expect(page.get_by_test_id("enabled-count")).to_have_text("1")
    row = page.get_by_test_id("class-row").first
    expect(row).to_contain_text("Reporting")
    # The badge names the level that decided it, so nobody switches off a class
    # thinking they are switching off the school.
    expect(row).to_contain_text("Weekly: on (school)")


def test_a_class_override_beats_the_school_switch(page, live_server, hoi,
                                                  classroom):
    from progress.tests.factories import enable_reports

    do_login(page, live_server.url, hoi)
    _save_school(page, live_server)

    enable_reports(classroom.school, classroom, kind="class", weekly=False)
    page.goto(f"{live_server.url}{SETTINGS_URL}")

    row = page.get_by_test_id("class-row").first
    expect(row).to_contain_text("Weekly: off (class)")
    expect(page.get_by_test_id("enabled-count")).to_have_text("0")


def test_a_class_with_its_own_rule_opens_expanded(page, live_server, hoi,
                                                  classroom):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, classroom, kind="class", weekly=True)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{SETTINGS_URL}")

    # An overridden class is expanded so its rule is visible without hunting;
    # an inheriting one stays collapsed.
    details = page.get_by_test_id("class-row").first.locator("details")
    expect(details).to_have_attribute("open", "")


def test_a_student_in_an_unconfigured_school_has_no_reports_link(
        page, live_server, enrolled_student):
    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/student-dashboard/")

    assert_sidebar_missing_link(page, "My Reports")


def test_the_link_appears_once_the_school_switches_reports_on(
        page, live_server, enrolled_student, classroom):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)

    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/student-dashboard/")

    assert_sidebar_has_link(page, "My Reports")


# ---------------------------------------------------------------------------
# Manual / automatic mode and the staff preview
# ---------------------------------------------------------------------------

PREVIEW_URL = "/progress/reports/preview/"


def test_a_school_starts_in_manual_mode(page, live_server, hoi, classroom):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{SETTINGS_URL}")

    # Enabled, but nothing sends on its own until someone chooses automatic.
    expect(page.get_by_test_id("enabled-count")).to_have_text("1")
    expect(page.get_by_test_id("auto-count")).to_have_text("0")
    expect(page.get_by_test_id("class-row").first).to_contain_text("Manual")


def test_switching_a_school_to_automatic_shows_in_the_counts(
        page, live_server, hoi, classroom):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True, mode="auto")
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{SETTINGS_URL}")

    expect(page.get_by_test_id("auto-count")).to_have_text("1")
    expect(page.get_by_test_id("class-row").first).to_contain_text("Auto")


def test_hoi_previews_every_student_before_sending(page, live_server, hoi,
                                                   classroom, enrolled_student):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)
    do_login(page, live_server.url, hoi)

    assert_sidebar_has_link(page, "Preview Reports")
    page.goto(f"{live_server.url}{PREVIEW_URL}")

    expect(page.get_by_test_id("report-preview")).to_be_visible()
    expect(page.get_by_test_id("preview-row")).to_have_count(1)
    expect(page.get_by_test_id("preview-send")).to_be_visible()


def test_previewing_an_unconfigured_school_offers_nothing_to_send(
        page, live_server, hoi, classroom, enrolled_student):
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}")

    expect(page.get_by_test_id("preview-empty")).to_be_visible()
    expect(page.get_by_test_id("preview-send")).to_have_count(0)


@pytest.fixture
def previewable_work(db, classroom, enrolled_student):
    """Two attempts on one homework, inside the week the preview will pick.

    Dated from ``periods.previous_week`` rather than a fixed date: the preview
    always shows the most recently closed window, so a hard-coded week would
    pass this week and quietly stop covering anything the next.
    """
    from datetime import datetime, time

    from django.utils import timezone
    from homework.models import Homework, HomeworkSubmission
    from progress import periods

    start = periods.previous_week(periods.today())[0]
    when = timezone.make_aware(
        datetime.combine(start, time(10, 0)), timezone.get_current_timezone(),
    )
    homework = Homework.objects.create(
        classroom=classroom, title="Fractions Practice",
        due_date=when, num_questions=10,
    )
    for attempt, score in ((1, 4), (2, 9)):
        submission = HomeworkSubmission.objects.create(
            homework=homework, student=enrolled_student,
            attempt_number=attempt, score=score, total_questions=10,
            points=score, time_taken_seconds=300,
        )
        HomeworkSubmission.objects.filter(pk=submission.pk).update(
            submitted_at=when,
        )
    return enrolled_student


def test_hoi_opens_one_students_report_before_sending(
        page, live_server, hoi, classroom, previewable_work):
    """The whole point of the link: read the real report, send nothing."""
    from progress.models import PeriodReport
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}")

    page.get_by_test_id("preview-view-report").first.click()

    expect(page.get_by_test_id("period-report")).to_be_visible()
    expect(page.get_by_test_id("report-preview-banner")).to_be_visible()
    expect(page.get_by_test_id("report-kpis")).to_contain_text("90%")

    # Reading a preview must not create the thing it is previewing.
    assert not PeriodReport.objects.exists()


def test_the_preview_offers_a_way_back_without_sending(
        page, live_server, hoi, classroom, previewable_work):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}")
    page.get_by_test_id("preview-view-report").first.click()

    page.get_by_role("link", name=re.compile("Back to preview")).click()

    expect(page.get_by_test_id("report-preview")).to_be_visible()
    expect(page.get_by_test_id("preview-send")).to_be_visible()


def test_a_student_with_no_submissions_has_nothing_to_open(
        page, live_server, hoi, classroom, enrolled_student):
    from progress.tests.factories import enable_reports

    enable_reports(classroom.school, kind="school", weekly=True)
    do_login(page, live_server.url, hoi)
    page.goto(f"{live_server.url}{PREVIEW_URL}")

    expect(page.get_by_test_id("preview-row")).to_have_count(1)
    expect(page.get_by_test_id("preview-view-report")).to_have_count(0)
