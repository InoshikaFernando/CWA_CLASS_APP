"""Playwright UI test — the times-tables picker warns about tables gone stale.

A best times-table score never expires, so the picker showing only the score
would claim a table mastered last term is mastered today. The fix reports
freshness instead of deleting old attempts (deleting them would quietly lower
a student's points — see maths/times_table_freshness.py).

Only a browser can prove the two things that matter here:

* the nudge is actually on the page the child lands on, not merely in a
  context dict — the picker previously rendered no result at all, so there was
  nowhere for a warning to appear;
* the old score is still visible beside it. "Needs a refresh" has to read as a
  prompt to go again, not as work taken away.
"""
from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.quiz


def _attempt(student, table, operation, days_ago, score=12):
    from maths.models import StudentFinalAnswer

    return StudentFinalAnswer.objects.create(
        student=student,
        quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
        table_number=table, operation=operation,
        score=score, total_questions=12, points=90.0, time_taken_seconds=20,
        completed_at=timezone.now() - datetime.timedelta(days=days_ago),
    )


def test_a_stale_table_asks_for_a_refresh_without_losing_its_score(
    page, live_server, enrolled_student,
):
    _attempt(enrolled_student, 3, 'multiplication', days_ago=150, score=12)

    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/maths/times-tables/")
    page.wait_for_load_state("domcontentloaded")

    # The warning is on the page the child actually sees...
    expect(page.get_by_text("Time to revisit")).to_be_visible()
    expect(page.get_by_text("Needs a refresh").first).to_be_visible()
    # ...and the result it qualifies is still right there, not taken away.
    expect(page.get_by_text("× 100%").first).to_be_visible()
    # The table is still practisable — a stale result never locks anything.
    expect(page.get_by_role("link", name="× Multiply").first).to_be_visible()


def test_a_recently_practised_table_is_not_nagged(
    page, live_server, enrolled_student,
):
    _attempt(enrolled_student, 3, 'multiplication', days_ago=2, score=12)

    do_login(page, live_server.url, enrolled_student)
    page.goto(f"{live_server.url}/maths/times-tables/")
    page.wait_for_load_state("domcontentloaded")

    expect(page.get_by_text("Needs a refresh")).to_have_count(0)
    expect(page.get_by_text("Time to revisit")).to_have_count(0)
    expect(page.get_by_text("× 100%").first).to_be_visible()
