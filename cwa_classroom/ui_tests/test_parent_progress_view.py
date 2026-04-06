"""
UI tests for the parent progress view (CPP-69).

Scenarios:
1. Parent can navigate to the progress page via sidebar
2. Approved criteria appear with correct name and status badge
3. 'Not Assessed' badge shown when no ProgressRecord exists
4. 'Achieved' badge shown after a ProgressRecord with status='achieved'
5. 'In Progress' badge shown after a ProgressRecord with status='in_progress'
6. Overall summary stat cards are visible
7. Non-approved (draft) criteria are NOT shown
8. Parent with no linked child sees empty state
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _make_user
from .helpers import click_sidebar_link, assert_page_has_text, _ensure_sidebar_visible

pytestmark = pytest.mark.parent_progress

PROGRESS_URL = "/parent/progress/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def progress_school_setup(db, school, roles, admin_user):
    """
    Create:
    - A subject and level
    - Two approved ProgressCriteria for the school
    - One draft ProgressCriteria (should not appear)
    Returns (subject, level, criteria_1, criteria_2, draft_criteria).
    """
    from classroom.models import Subject, Level, ProgressCriteria

    subj, _ = Subject.objects.get_or_create(
        slug="reading-prog-ui",
        defaults={"name": "Reading", "school": None, "is_active": True},
    )
    lvl, _ = Level.objects.get_or_create(
        level_number=2,
        defaults={"display_name": "Year 2"},
    )
    c1 = ProgressCriteria.objects.create(
        school=school,
        subject=subj,
        level=lvl,
        name="Read aloud fluently",
        status="approved",
        created_by=admin_user,
    )
    c2 = ProgressCriteria.objects.create(
        school=school,
        subject=subj,
        level=lvl,
        name="Identify story structure",
        status="approved",
        created_by=admin_user,
    )
    draft = ProgressCriteria.objects.create(
        school=school,
        subject=subj,
        level=lvl,
        name="Draft Hidden Criteria",
        status="draft",
        created_by=admin_user,
    )
    return subj, lvl, c1, c2, draft


@pytest.fixture
def parent_with_progress_child(db, school, roles, admin_user, progress_school_setup):
    """
    A parent linked to a student enrolled in the school.
    Returns (parent_user, student_user).
    """
    from accounts.models import Role
    from classroom.models import SchoolStudent, ParentStudent

    student = _make_user("ui_prog_student", Role.STUDENT,
                         first_name="Leo", last_name="Learner")
    SchoolStudent.objects.get_or_create(school=school, student=student)
    parent = _make_user("ui_prog_parent", Role.PARENT,
                        first_name="Mary", last_name="Parent")
    ParentStudent.objects.create(
        parent=parent,
        student=student,
        school=school,
        relationship="mother",
        is_active=True,
    )
    return parent, student


@pytest.fixture
def parent_with_achieved_record(db, parent_with_progress_child, progress_school_setup, admin_user):
    """
    Add an 'achieved' ProgressRecord for criteria_1 and an 'in_progress' for criteria_2.
    """
    from classroom.models import ProgressRecord

    parent, student = parent_with_progress_child
    _, _, c1, c2, _ = progress_school_setup

    ProgressRecord.objects.create(
        student=student,
        criteria=c1,
        status="achieved",
        recorded_by=admin_user,
        notes="Well done!",
    )
    ProgressRecord.objects.create(
        student=student,
        criteria=c2,
        status="in_progress",
        recorded_by=admin_user,
    )
    return parent, student


def _go_to_progress(page, live_server):
    """Navigate to the parent progress page and wait for content."""
    page.goto(f"{live_server.url}{PROGRESS_URL}")
    page.wait_for_load_state("networkidle")


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestParentProgressPageAccess:

    def test_sidebar_progress_link_navigates(self, page, live_server, parent_with_progress_child):
        """Clicking 'Progress' in the sidebar navigates to the progress page."""
        parent, _ = parent_with_progress_child
        do_login(page, live_server.url, parent)
        page.goto(f"{live_server.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

        click_sidebar_link(page, "Progress")
        expect(page).to_have_url(f"{live_server.url}{PROGRESS_URL}")

    def test_progress_page_loads(self, page, live_server, parent_with_progress_child):
        """Navigating directly to /parent/progress/ shows the Progress Report heading."""
        parent, _ = parent_with_progress_child
        do_login(page, live_server.url, parent)

        _go_to_progress(page, live_server)
        expect(page.locator("h1")).to_contain_text("Progress")


class TestParentProgressCriteriaDisplay:

    def test_approved_criteria_visible(self, page, live_server, parent_with_progress_child, progress_school_setup):
        """Both approved criteria names appear on the page."""
        parent, _ = parent_with_progress_child
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "Read aloud fluently")
        assert_page_has_text(page, "Identify story structure")

    def test_draft_criteria_not_visible(self, page, live_server, parent_with_progress_child, progress_school_setup):
        """Draft criteria must NOT appear on the page."""
        parent, _ = parent_with_progress_child
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        body = page.locator("body")
        expect(body).not_to_contain_text("Draft Hidden Criteria")

    def test_not_assessed_badge_when_no_record(self, page, live_server, parent_with_progress_child, progress_school_setup):
        """When no ProgressRecord exists, 'Not Assessed' badge should appear."""
        parent, _ = parent_with_progress_child
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "Not Assessed")


class TestParentProgressStatusBadges:

    def test_achieved_badge_visible(self, page, live_server, parent_with_achieved_record, progress_school_setup):
        """After an 'achieved' ProgressRecord, the 'Achieved' badge appears."""
        parent, _ = parent_with_achieved_record
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "Achieved")

    def test_in_progress_badge_visible(self, page, live_server, parent_with_achieved_record, progress_school_setup):
        """After an 'in_progress' ProgressRecord, the 'In Progress' badge appears."""
        parent, _ = parent_with_achieved_record
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "In Progress")

    def test_notes_shown_on_page(self, page, live_server, parent_with_achieved_record, progress_school_setup):
        """Teacher notes from ProgressRecord appear on the page."""
        parent, _ = parent_with_achieved_record
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "Well done!")


class TestParentProgressSummaryStats:

    def test_overall_total_stat_card_visible(self, page, live_server, parent_with_progress_child, progress_school_setup):
        """The 'Total Criteria' stat card is visible."""
        parent, _ = parent_with_progress_child
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "Total Criteria")

    def test_achieved_stat_card_visible(self, page, live_server, parent_with_achieved_record, progress_school_setup):
        """The 'Achieved' and 'In Progress' stat cards are visible after records are added."""
        parent, _ = parent_with_achieved_record
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "Total Criteria")
        assert_page_has_text(page, "In Progress")

    def test_overall_progress_bar_visible(self, page, live_server, parent_with_achieved_record, progress_school_setup):
        """The 'Overall Achievement' progress bar section renders."""
        parent, _ = parent_with_achieved_record
        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "Overall Achievement")


class TestParentProgressNoChild:

    def test_no_child_empty_state(self, page, live_server, db, roles):
        """Parent with no linked children sees 'No child selected' empty state."""
        from accounts.models import Role
        parent = _make_user("ui_no_child_parent_prog", Role.PARENT)

        do_login(page, live_server.url, parent)
        _go_to_progress(page, live_server)

        assert_page_has_text(page, "No child selected.")
