"""Clearing a false positive from the question check page (CPP-398).

The deterministic checks are blunt: a question can be flagged and still be
perfectly sound. Before "Reviewed and correct" the only exits from such a row
were to edit the question needlessly or delete it, so the same false positives
came back on every run and the list stopped being read.

These tests drive the real page: a flagged question is listed, a super-admin
marks it correct, and it goes — visibly, with the page saying how many rows it
is no longer showing.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.dashboard

CHECK_URL = "/admin-dashboard/question-health/check/?run=1"


@pytest.fixture
def flagged_question(db, level, topic):
    """A question the verifier objects to — no option marked correct."""
    from maths.models import Answer, Question

    question = Question.objects.create(
        level=level, topic=topic, question_text="What is 7 x 8?",
        question_type="multiple_choice", difficulty=1, points=1,
    )
    for order, text in enumerate(["54", "56", "58"]):
        Answer.objects.create(question=question, answer_text=text,
                              is_correct=False, order=order)
    return question


def _open_check_page(page, live_server, user):
    do_login(page, live_server.url, user)
    page.goto(f"{live_server.url}{CHECK_URL}")
    page.wait_for_load_state("domcontentloaded")


def test_a_flagged_question_is_listed(
    page, live_server, superuser, subject, level, topic, flagged_question,
):
    _open_check_page(page, live_server, superuser)
    expect(
        page.locator(f"[data-testid='issue-row-{flagged_question.id}']")
    ).to_be_visible()


def test_reviewed_and_correct_is_offered_as_an_action(
    page, live_server, superuser, subject, level, topic, flagged_question,
):
    _open_check_page(page, live_server, superuser)
    options = page.locator("[data-testid='bulk-action'] option")
    expect(options.filter(has_text="Reviewed and correct")).to_have_count(1)


def test_marking_a_question_correct_clears_it_from_the_list(
    page, live_server, superuser, subject, level, topic, flagged_question,
):
    from maths.models import QuestionReview

    _open_check_page(page, live_server, superuser)
    row = page.locator(f"[data-testid='issue-row-{flagged_question.id}']")
    row.locator("input[name='question_id']").check()
    page.locator("[data-testid='bulk-action']").select_option(
        "mark_reviewed_correct")
    page.locator("[data-testid='bulk-apply']").click()
    page.wait_for_load_state("domcontentloaded")

    expect(
        page.locator(f"[data-testid='issue-row-{flagged_question.id}']")
    ).to_have_count(0)

    review = QuestionReview.objects.get(question=flagged_question)
    assert review.verdict == QuestionReview.VERDICT_CORRECT
    assert review.reviewed_by == superuser


def test_the_page_says_how_many_rows_it_is_hiding(
    page, live_server, superuser, subject, level, topic, flagged_question,
):
    """A row that vanishes without a word is how a bank reads clean."""
    from maths.question_review import record_review
    from maths.models import QuestionReview

    record_review(flagged_question, user=superuser,
                  verdict=QuestionReview.VERDICT_CORRECT)

    _open_check_page(page, live_server, superuser)
    note = page.locator("[data-testid='cleared-note']")
    expect(note).to_be_visible()
    expect(note).to_contain_text("not listed")


def test_editing_a_cleared_question_brings_it_back(
    page, live_server, superuser, subject, level, topic, flagged_question,
):
    """A clearance must never vouch for text written after it was given."""
    from maths.models import QuestionReview
    from maths.question_review import record_review

    record_review(flagged_question, user=superuser,
                  verdict=QuestionReview.VERDICT_CORRECT)
    _open_check_page(page, live_server, superuser)
    expect(
        page.locator(f"[data-testid='issue-row-{flagged_question.id}']")
    ).to_have_count(0)

    flagged_question.question_text = "What is 7 x 8, exactly?"
    flagged_question.save(update_fields=["question_text", "updated_at"])

    page.goto(f"{live_server.url}{CHECK_URL}")
    page.wait_for_load_state("domcontentloaded")
    expect(
        page.locator(f"[data-testid='issue-row-{flagged_question.id}']")
    ).to_be_visible()


def test_a_reported_question_reaches_the_check_page(
    page, live_server, superuser, student_user, subject, level, topic, questions,
):
    """A student's complaint is unhealthy even when every check passes it."""
    from maths.models import QuestionReport

    reported = questions[0]
    QuestionReport.objects.create(
        question=reported, reported_by=student_user,
        note="the answer was 23 or 23 pencils but why",
    )

    _open_check_page(page, live_server, superuser)
    row = page.locator(f"[data-testid='issue-row-{reported.id}']")
    expect(row).to_be_visible()
    expect(row).to_contain_text("Reported by a user")
