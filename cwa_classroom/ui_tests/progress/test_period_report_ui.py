"""
UI tests for the weekly / monthly / term progress reports (CPP-388).

Scenarios:
1. A student reaches their reports from the sidebar and sees the period card.
2. The report page renders its headline figures, charts and PDF link.
3. The charts actually mount — a Chart.js canvas with no chart on it looks
   identical to a working one in a screenshot, so this asserts on the drawn
   canvas rather than on the element being present.
4. A period with no submissions says so instead of showing a wall of zeros.
5. A linked parent sees their child's report; another family's parent gets a 404.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from ..conftest import do_login, _make_user
from ..helpers import assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.progress_reports

PERIOD_START = date(2026, 8, 17)
PERIOD_END = date(2026, 8, 23)


def _at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


@pytest.fixture
def weekly_report(db, classroom, enrolled_student):
    """A generated weekly report with two attempts on one homework."""
    from homework.models import Homework, HomeworkSubmission
    from progress.models import PeriodReport
    from progress.reports import build_report_data

    homework = Homework.objects.create(
        classroom=classroom, title="Fractions Practice",
        due_date=_at(date(2026, 8, 21)), num_questions=10,
    )
    for attempt, score, day in ((1, 4, 18), (2, 9, 19)):
        submission = HomeworkSubmission.objects.create(
            homework=homework, student=enrolled_student,
            attempt_number=attempt, score=score, total_questions=10,
            points=score, time_taken_seconds=300,
        )
        HomeworkSubmission.objects.filter(pk=submission.pk).update(
            submitted_at=_at(date(2026, 8, day)),
        )

    return PeriodReport.objects.create(
        student=enrolled_student, school=classroom.school,
        period_type=PeriodReport.PERIOD_WEEKLY,
        period_start=PERIOD_START, period_end=PERIOD_END,
        data=build_report_data(
            enrolled_student, PeriodReport.PERIOD_WEEKLY,
            PERIOD_START, PERIOD_END,
        ),
    )


@pytest.fixture
def empty_report(db, classroom, enrolled_student):
    """A report for a period in which nothing was submitted."""
    from progress.models import PeriodReport
    from progress.reports import build_report_data

    start, end = date(2026, 7, 1), date(2026, 7, 31)
    return PeriodReport.objects.create(
        student=enrolled_student, school=classroom.school,
        period_type=PeriodReport.PERIOD_MONTHLY,
        period_start=start, period_end=end,
        data=build_report_data(
            enrolled_student, PeriodReport.PERIOD_MONTHLY, start, end,
        ),
    )


@pytest.fixture
def linked_parent(db, roles, enrolled_student, school):
    from accounts.models import Role
    from classroom.models import ParentStudent

    parent = _make_user("ui_report_parent", Role.PARENT)
    ParentStudent.objects.create(
        parent=parent, student=enrolled_student, school=school, is_active=True,
    )
    return parent


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------

def test_student_reaches_reports_from_the_sidebar(page, live_server, weekly_report,
                                                  enrolled_student):
    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/student-dashboard/")

    assert_sidebar_has_link(page, "My Reports")
    click_sidebar_link(page, "My Reports")

    expect(page).to_have_url(re.compile(r"/progress/reports/"))
    expect(page.get_by_test_id("report-card").first).to_be_visible()
    expect(page.get_by_text("Week of 17 Aug 2026")).to_be_visible()


def test_report_page_shows_the_headline_figures(page, live_server, weekly_report,
                                                enrolled_student):
    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/progress/reports/{weekly_report.id}/")

    expect(page.get_by_test_id("period-report")).to_be_visible()
    kpis = page.get_by_test_id("report-kpis")
    expect(kpis).to_contain_text("90%")   # best-attempt average
    expect(kpis).to_contain_text("40%")   # first-attempt average
    expect(kpis).to_contain_text("+50")   # gained by retrying


def test_report_page_offers_the_pdf(page, live_server, weekly_report, enrolled_student):
    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/progress/reports/{weekly_report.id}/")

    link = page.get_by_test_id("report-pdf-link")
    expect(link).to_be_visible()
    expect(link).to_have_attribute(
        "href", f"/progress/reports/{weekly_report.id}/pdf/",
    )


def test_the_charts_actually_render(page, live_server, weekly_report, enrolled_student):
    """A blank canvas and a drawn one look the same to a selector.

    Chart.js registers every instance it builds, so asking the page how many
    exist is the difference between "the element is there" and "the chart drew".
    """
    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/progress/reports/{weekly_report.id}/")

    page.wait_for_function(
        "() => window.Chart && Object.keys(Chart.instances).length > 0",
        timeout=10_000,
    )
    mounted = page.evaluate("() => Object.keys(Chart.instances).length")
    assert mounted >= 2, f"expected the report's charts to mount, got {mounted}"

    expect(page.get_by_test_id("chart-attempts")).to_be_visible()
    expect(page.get_by_test_id("chart-first-vs-best")).to_be_visible()


def test_an_empty_period_says_so(page, live_server, empty_report, enrolled_student):
    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/progress/reports/{empty_report.id}/")

    expect(page.get_by_test_id("report-empty")).to_be_visible()
    expect(page.get_by_test_id("report-kpis")).to_have_count(0)


# ---------------------------------------------------------------------------
# Parent
# ---------------------------------------------------------------------------

def test_parent_sees_their_childs_report(page, live_server, weekly_report,
                                         linked_parent, enrolled_student):
    do_login(page, live_server.url, linked_parent)
    page.goto(f"{live_server.url}/progress/reports/")

    expect(page.get_by_test_id("report-card").first).to_be_visible()
    page.get_by_test_id("report-card").first.click()
    expect(page.get_by_test_id("period-report")).to_be_visible()
    expect(page.get_by_test_id("report-kpis")).to_contain_text("90%")


def test_another_familys_parent_cannot_open_the_report(page, live_server,
                                                       weekly_report, roles):
    from accounts.models import Role

    stranger = _make_user("ui_report_stranger", Role.PARENT)
    do_login(page, live_server.url, stranger)

    response = page.goto(f"{live_server.url}/progress/reports/{weekly_report.id}/")
    assert response.status == 404
