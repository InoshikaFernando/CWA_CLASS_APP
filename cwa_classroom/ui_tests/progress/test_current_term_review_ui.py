"""
UI tests for reviewing a term that is still running (CPP-425).

Scenarios:
1. The term selector appears for a term preview and marks the running term.
2. Choosing the running term shows a "(to date)" window ending today.
3. That view offers no send button, and says why in words.
4. The finished term still offers one.
5. Opening one student keeps the chosen term rather than snapping back.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from playwright.sync_api import expect

from ..conftest import do_login, _make_user

pytestmark = pytest.mark.progress_reports

PREVIEW_URL = "/progress/reports/preview/"


@pytest.fixture
def hoi(db, roles, school):
    from accounts.models import Role
    from classroom.models import SchoolTeacher

    user = _make_user("ui_term_hoi", Role.HEAD_OF_INSTITUTE)
    SchoolTeacher.objects.create(
        school=school, teacher=user, role="head_of_institute",
    )
    return user


@pytest.fixture
def terms(db, school):
    """One finished term and one still running, on the school's calendar."""
    from classroom.models import AcademicYear, Term
    from progress import periods
    from progress.tests.factories import enable_reports

    today = periods.today()
    year = AcademicYear.objects.create(
        school=school, year=today.year,
        start_date=today - timedelta(days=300),
        end_date=today + timedelta(days=65),
    )
    finished = Term.objects.create(
        school=school, academic_year=year, name="Term 1", order=1,
        start_date=today - timedelta(days=120),
        end_date=today - timedelta(days=40),
    )
    running = Term.objects.create(
        school=school, academic_year=year, name="Term 2", order=2,
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=30),
    )
    enable_reports(school, kind="school", term=True)
    return finished, running


def _preview(page, live_server, school, term=None):
    url = f"{live_server.url}{PREVIEW_URL}?school={school.id}&period=term"
    if term is not None:
        url += f"&term={term.id}"
    page.goto(url)


def test_the_term_selector_marks_the_running_term(
        page, live_server, hoi, classroom, terms):
    _finished, running = terms
    do_login(page, live_server.url, hoi)
    _preview(page, live_server, classroom.school)

    selector = page.get_by_test_id("preview-term")
    expect(selector).to_be_visible()
    expect(selector).to_contain_text("Term 1")
    # The option reads "Term 2 <year> — in progress", so the marker and the
    # name are asserted separately rather than as one string.
    expect(selector).to_contain_text(running.name)
    expect(selector).to_contain_text("in progress")


def test_the_page_opens_on_the_finished_term(
        page, live_server, hoi, classroom, terms, enrolled_student):
    do_login(page, live_server.url, hoi)
    _preview(page, live_server, classroom.school)

    # Unchanged default: the term a school is about to send is still the one
    # the page opens on.
    expect(page.get_by_test_id("preview-period")).to_contain_text("Term 1")
    expect(page.get_by_test_id("preview-period")).not_to_contain_text("to date")
    expect(page.get_by_test_id("preview-send")).to_be_visible()


def test_choosing_the_running_term_shows_it_to_date(
        page, live_server, hoi, classroom, terms):
    _finished, running = terms
    do_login(page, live_server.url, hoi)
    _preview(page, live_server, classroom.school, running)

    expect(page.get_by_test_id("preview-period")).to_contain_text("Term 2")
    expect(page.get_by_test_id("preview-period")).to_contain_text("(to date)")


def test_a_running_term_is_review_only_and_says_why(
        page, live_server, hoi, classroom, terms):
    _finished, running = terms
    do_login(page, live_server.url, hoi)
    _preview(page, live_server, classroom.school, running)

    expect(page.get_by_test_id("preview-review-only")).to_be_visible()
    # No disabled button either — there is nothing to click at all.
    expect(page.get_by_test_id("preview-send")).to_have_count(0)
    expect(page.get_by_test_id("preview-partial-note")).to_contain_text(
        "progress check, not a result")


def test_switching_terms_from_the_selector_works(
        page, live_server, hoi, classroom, terms):
    _finished, running = terms
    do_login(page, live_server.url, hoi)
    _preview(page, live_server, classroom.school)

    page.get_by_test_id("preview-term").select_option(str(running.id))
    page.get_by_role("button", name="Preview").click()

    expect(page.get_by_test_id("preview-review-only")).to_be_visible()
    expect(page.get_by_test_id("preview-period")).to_contain_text("(to date)")
