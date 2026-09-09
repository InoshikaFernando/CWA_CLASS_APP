"""Playwright UI tests — the flagged-question highlight on the PDF review page.

A question the verifier flags used to announce itself with one small "⚠ Review"
badge in a card header. On a 40-question review page that is easy to scroll
straight past, and a wrong answer key then reaches the students. The whole card
is now red until the teacher ticks "Reviewed" beside the badge, which clears the
highlight there and then and is saved with the rest of the page.

These drive the real page because the thing under test is what the teacher sees:
the card's painted background, not a class name in the HTML.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


_WHITE = "rgb(255, 255, 255)"
_RED_50 = "rgb(254, 242, 242)"


def _session(user, school, *, review_ack=False):
    from homework.models import HomeworkUploadSession

    return HomeworkUploadSession.objects.create(
        user=user, school=school, pdf_filename="stats.pdf",
        # The title input is required=true — a blank one blocks the submit.
        homework_title="Five number summary",
        status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
        extracted_data={
            "year_level": 8, "subject": "Mathematics", "topic": "Statistics",
            "questions": [
                {
                    "question_text": "In the five number summary, what does the Minimum represent?",
                    "question_type": "short_answer",
                    "answers": [{"text": "the lowest number", "is_correct": True}],
                    "explanation": "The minimum is the smallest value in the ordered data set.",
                    "validation_type": "auto", "difficulty": 1, "points": 1,
                    "include": True,
                    "needs_review": True,
                    "review_reason": "the second opinion disagreed with this answer",
                    "review_ack": review_ack,
                },
                {
                    "question_text": "What does the Median represent?",
                    "question_type": "short_answer",
                    "answers": [{"text": "the middle value", "is_correct": True}],
                    "validation_type": "auto", "difficulty": 1, "points": 1,
                    "include": True,
                },
            ],
        },
        extracted_images={},
    )


def _background(page: Page, selector: str) -> str:
    return page.locator(selector).evaluate(
        "el => getComputedStyle(el).backgroundColor")


def _expect_background(page: Page, selector: str, expected: str) -> None:
    """Wait for the card's painted background to settle on `expected`.

    The card fades between the two colours, so reading the computed style the
    instant after a click can catch a midpoint like rgb(254, 247, 247).
    """
    try:
        page.wait_for_function(
            "([sel, want]) => getComputedStyle(document.querySelector(sel))"
            ".backgroundColor === want",
            arg=[selector, expected], timeout=5_000)
    except Exception:
        raise AssertionError(
            f"{selector} background is {_background(page, selector)}, expected {expected}")


class TestFlaggedQuestionHighlight:

    @pytest.mark.django_db(transaction=True)
    def test_a_flagged_card_is_red_and_an_unflagged_one_is_not(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        _expect_background(page, "#card-0", _RED_50)
        _expect_background(page, "#card-1", _WHITE)
        expect(page.get_by_test_id("review-badge-0")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_ticking_reviewed_clears_the_red_and_unticking_brings_it_back(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        tick = page.get_by_test_id("review-ack-0")
        tick.check()
        _expect_background(page, "#card-0", _WHITE)
        tick.uncheck()
        _expect_background(page, "#card-0", _RED_50)

    @pytest.mark.django_db(transaction=True)
    def test_the_tick_is_saved_so_the_card_stays_normal_on_the_way_back(
        self, page: Page, live_server, school, teacher_user
    ):
        from homework.models import HomeworkUploadSession

        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_test_id("review-ack-0").check()
        page.get_by_role("button", name="Continue to Confirm").click()
        page.wait_for_url(lambda url: "/confirm/" in url, timeout=15_000)

        saved = HomeworkUploadSession.objects.get(pk=session.pk).extracted_data["questions"][0]
        assert saved["review_ack"] is True
        # The flag itself survives — the teacher acknowledged it, the verifier
        # did not change its mind.
        assert saved["needs_review"] is True

        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")
        _expect_background(page, "#card-0", _WHITE)
        expect(page.get_by_test_id("review-ack-0")).to_be_checked()
