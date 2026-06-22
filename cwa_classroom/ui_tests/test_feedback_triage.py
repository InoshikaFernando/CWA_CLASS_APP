"""
Playwright UI tests for the feedback triage dashboard (CPP-323).

Covers the owner workflow (set priority + move status inline), filtering the
queue, and authorization (a teacher cannot open the dashboard).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import wait_for_htmx

pytestmark = pytest.mark.dashboard


@pytest.fixture
def feedback_items(db, school, teacher_user):
    """A couple of feedback items to triage."""
    from feedback.models import Feedback
    from accounts.models import Role

    bug = Feedback.objects.create(
        submitted_by=teacher_user, school=school, role=Role.TEACHER,
        category=Feedback.CATEGORY_BUG, title="Save button broken",
        description="Nothing happens on save.", status=Feedback.STATUS_NEW,
    )
    feature = Feedback.objects.create(
        submitted_by=teacher_user, school=school, role=Role.TEACHER,
        category=Feedback.CATEGORY_FEATURE, title="Dark mode",
        description="Add a dark theme.", status=Feedback.STATUS_NEW,
    )
    return bug, feature


def test_owner_triages_feedback_sets_priority_and_status(
    page, live_server, admin_user, feedback_items,
):
    bug, _ = feedback_items
    do_login(page, live_server.url, admin_user)
    page.goto(f"{live_server.url}/feedback/triage/")
    page.wait_for_load_state("domcontentloaded")

    row = page.locator(f"#feedback-row-{bug.pk}")
    expect(row).to_be_visible()

    row.locator("select[name='priority']").select_option("high", force=True)
    wait_for_htmx(page)
    row.locator("select[name='status']").select_option("triaged", force=True)
    wait_for_htmx(page)

    from feedback.models import Feedback
    bug.refresh_from_db()
    assert bug.priority == Feedback.PRIORITY_HIGH
    assert bug.status == Feedback.STATUS_TRIAGED


def test_owner_filters_queue(page, live_server, admin_user, feedback_items):
    bug, feature = feedback_items
    do_login(page, live_server.url, admin_user)
    page.goto(f"{live_server.url}/feedback/triage/")
    page.wait_for_load_state("domcontentloaded")

    # Both visible initially.
    expect(page.locator(f"#feedback-row-{bug.pk}")).to_be_visible()
    expect(page.locator(f"#feedback-row-{feature.pk}")).to_be_visible()

    # Filter to bugs only.
    page.locator("select[name='category']").select_option("bug", force=True)
    wait_for_htmx(page)
    page.wait_for_load_state("domcontentloaded")

    expect(page.locator(f"#feedback-row-{bug.pk}")).to_be_visible()
    expect(page.locator(f"#feedback-row-{feature.pk}")).to_have_count(0)


def test_teacher_cannot_open_triage_dashboard(page, live_server, teacher_user):
    do_login(page, live_server.url, teacher_user)
    resp = page.goto(f"{live_server.url}/feedback/triage/")
    # Owner-only surface → 403 for a non-owner role.
    assert resp.status == 403
    expect(page.locator("#feedback-queue")).to_have_count(0)
