"""Reporting a problem with the question on screen (CPP-398).

A student who hits a broken question could previously only reach the global
feedback button, which records the page URL — and a topic quiz page serves
dozens of questions, so the report arrived untraceable. These tests drive the
real browser flow end to end: the link on the card, the modal it opens, and the
QuestionReport row that comes out of it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login
from ..helpers import wait_for_htmx

pytestmark = pytest.mark.quiz


def _open_quiz(page, live_server, user, level, topic):
    do_login(page, live_server.url, user)
    page.goto(
        f"{live_server.url}/maths/level/{level.level_number}"
        f"/topic/{topic.id}/quiz/"
    )
    page.wait_for_selector("#question-card", timeout=10_000)


def _report_current_question(page, description):
    page.locator("[data-report-question]").first.click()
    page.wait_for_selector("#feedback-form", state="attached", timeout=10_000)
    wait_for_htmx(page)
    page.locator("#feedback-form textarea[name='description']").fill(
        description, force=True,
    )
    page.locator("#feedback-form button[type='submit']").click(force=True)
    expect(page.locator("[data-feedback-success]")).to_be_visible(timeout=10_000)


def test_the_question_card_offers_a_report_link(
    page, live_server, monkeypatch,
    enrolled_student, school, classroom, level, topic, questions,
):
    monkeypatch.setattr("random.shuffle", lambda seq: None)
    _open_quiz(page, live_server, enrolled_student, level, topic)

    link = page.locator("[data-report-question]").first
    expect(link).to_be_visible()
    expect(link).to_contain_text("Report a problem")


def test_reporting_names_the_question_in_the_modal(
    page, live_server, monkeypatch,
    enrolled_student, school, classroom, level, topic, questions,
):
    """The reporter can see which question they are about to report."""
    monkeypatch.setattr("random.shuffle", lambda seq: None)
    _open_quiz(page, live_server, enrolled_student, level, topic)

    question_id = page.locator("#question-card").get_attribute("data-question-id")
    page.locator("[data-report-question]").first.click()
    page.wait_for_selector("#feedback-form", state="attached", timeout=10_000)
    wait_for_htmx(page)

    expect(page.locator("[data-testid='reported-question']")).to_be_visible()
    expect(page.locator("#feedback-form input[name='question_id']")).to_have_value(
        question_id
    )


def test_a_submitted_report_records_the_question(
    page, live_server, monkeypatch,
    enrolled_student, school, classroom, level, topic, questions,
):
    """The whole point of CPP-398: the complaint knows what it is about."""
    from maths.models import QuestionReport

    monkeypatch.setattr("random.shuffle", lambda seq: None)
    _open_quiz(page, live_server, enrolled_student, level, topic)
    question_id = int(
        page.locator("#question-card").get_attribute("data-question-id"))

    _report_current_question(page, "The answer says 23 or 23 pencils — why?")

    report = QuestionReport.objects.get()
    assert report.question_id == question_id
    assert report.reported_by == enrolled_student
    assert "23 pencils" in report.note


def test_the_report_link_still_works_after_moving_to_the_next_question(
    page, live_server, monkeypatch,
    enrolled_student, school, classroom, level, topic, questions,
):
    """The swapped-in card is never processed by HTMX.

    The click is delegated from the document for exactly this reason. Bound to
    the card instead, the link would work on question one and silently do
    nothing on every question after it — the quiet failure this test exists to
    catch.
    """
    from maths.models import QuestionReport

    monkeypatch.setattr("random.shuffle", lambda seq: None)
    _open_quiz(page, live_server, enrolled_student, level, topic)

    first_id = page.locator("#question-card").get_attribute("data-question-id")
    page.locator(".answer-btn").first.click(force=True)
    page.get_by_role("button", name="Next Question →").click(timeout=10_000)
    page.wait_for_function(
        "id => document.querySelector('#question-card')"
        "?.dataset.questionId !== id",
        arg=first_id, timeout=10_000,
    )
    second_id = int(
        page.locator("#question-card").get_attribute("data-question-id"))

    _report_current_question(page, "This one is wrong too")

    report = QuestionReport.objects.get()
    assert report.question_id == second_id, (
        "the report followed the first question, so the delegated listener is "
        "reading a stale id"
    )
