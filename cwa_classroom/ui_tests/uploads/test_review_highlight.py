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
                    "review_reason": (
                        'Second-opinion check disagreed: verifier answered '
                        '"the lowest number" vs "the smallest value". '
                        'The explanation says there are 5 but lists 4 '
                        '(1, 2, 3, 4) — recount.'),
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


class TestWhatToCheck:
    """The flagged card says what to check, and takes the teacher to it.

    The reason used to be the ⚠ Review badge's title= tooltip: invisible until
    you hovered a 10px badge, so in practice a flagged question meant reading
    the whole question again to find what the verifier disliked. It is now a
    strip on the card, one point per field, each with a chip that scrolls to
    that field. These drive the real page because scrolling and the collapsed
    card body are exactly what a rendering test cannot see.
    """

    @pytest.mark.django_db(transaction=True)
    def test_the_reason_is_readable_without_hovering_anything(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        strip = page.locator("#review-points-0")
        expect(strip).to_be_visible()
        expect(strip).to_contain_text("What to check")
        expect(strip).to_contain_text("verifier answered")
        # One point per field the reason is about, not one wall of text.
        expect(page.get_by_test_id("review-point-0-0")).to_be_visible()
        expect(page.get_by_test_id("review-point-0-1")).to_be_visible()
        # ...and the question the verifier was happy with says nothing.
        expect(page.locator("#review-points-1")).to_have_count(0)

    @pytest.mark.django_db(transaction=True)
    def test_a_chip_opens_the_card_and_scrolls_to_the_field_it_names(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        # Collapse the question: the strip is the teacher's way in, so it has to
        # work on a card whose body is shut.
        page.locator("#card-0 .toggle-btn").click()
        expect(page.locator("#body-0")).to_be_hidden()

        page.locator('#review-points-0 [data-review-jump="explanation"]').click()
        explanation = page.locator('#card-0 [data-review-field="explanation"]')
        expect(explanation).to_be_visible()
        expect(explanation).to_be_in_viewport()

    @pytest.mark.django_db(transaction=True)
    def test_ticking_reviewed_clears_the_advice_with_the_highlight(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        tick = page.get_by_test_id("review-ack-0")
        tick.check()
        expect(page.locator("#review-points-0")).to_be_hidden()
        tick.uncheck()
        expect(page.locator("#review-points-0")).to_be_visible()


def _ai_import_session(user):
    """A flagged question on the AI-import preview — the third PDF screen, and
    the one whose cards collapse through Alpine rather than a class."""
    from ai_import.models import AIImportSession

    return AIImportSession.objects.create(
        user=user, pdf_filename="w.pdf",
        status=AIImportSession.STATUS_READY, is_confirmed=False,
        extracted_data={
            "year_level": 4, "subject": "Mathematics", "strand": "Number",
            "topic": "Mixed",
            "questions": [{
                "question_text": "How many squares are shaded?",
                "question_type": "short_answer", "difficulty": 1, "points": 1,
                "answers": [{"text": "10", "is_correct": True}],
                "explanation": "Count the shaded squares.",
                "needs_review": True,
                "review_reason": (
                    "Image check: a second AI counted the squares and got 12 "
                    "(3/3 agreed), but the imported answer is 10 — please "
                    "confirm the count. Image check: the crop cuts off part of "
                    "the figure."),
            }],
        },
        extracted_images={},
    )


class TestWhatToCheckOnAIImport:
    """The same strip on the AI-import preview, whose cards collapse through
    Alpine's x-show — the chip has to open the card there too."""

    @pytest.mark.django_db(transaction=True)
    def test_a_chip_opens_the_collapsed_card_and_scrolls_to_its_field(
        self, page: Page, live_server, superuser
    ):
        session = _ai_import_session(superuser)
        do_login(page, str(live_server), superuser)
        page.goto(f"{live_server}/ai-import/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        strip = page.locator("#review-points-0")
        expect(strip).to_be_visible()
        expect(strip).to_contain_text("confirm the count")

        # Collapse the card — the strip stays, that being the point of it.
        page.locator("#question-card-0 [data-review-expand]").click()
        expect(page.locator('#question-card-0 [data-review-body]')).to_be_hidden()
        expect(strip).to_be_visible()

        page.locator('#review-points-0 [data-review-jump="image"]').click()
        image = page.locator('#question-card-0 [data-review-field="image"]')
        expect(image).to_be_visible()
        expect(image).to_be_in_viewport()


class TestSubmitGate:
    """Submitting with a flagged question still unticked warns and names it.

    A red card and a "what to check" strip only help while the teacher is
    looking at that question. On a long import the flagged one is far up the
    page by the time they press Continue, so the submit itself has to say which
    questions were never checked. It warns rather than locks — the teacher can
    say "submit without checking them" — but it never goes quietly.
    """

    @pytest.mark.django_db(transaction=True)
    def test_submitting_with_a_flagged_question_warns_and_names_it(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name="Continue to Confirm").click()

        gate = page.get_by_test_id("review-gate")
        expect(gate).to_be_visible()
        expect(gate).to_contain_text("Q1 needs review")
        # ...and nothing was submitted.
        expect(page).to_have_url(f"{live_server}/homework/pdf/preview/{session.pk}/")
        assert session.__class__.objects.get(pk=session.pk).is_confirmed is False

    @pytest.mark.django_db(transaction=True)
    def test_ticking_the_question_takes_the_warning_away_and_lets_it_through(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name="Continue to Confirm").click()
        expect(page.get_by_test_id("review-gate")).to_be_visible()

        page.get_by_test_id("review-ack-0").check()
        expect(page.get_by_test_id("review-gate")).to_be_hidden()

        page.get_by_role("button", name="Continue to Confirm").click()
        page.wait_for_url(lambda url: "/confirm/" in url, timeout=15_000)
        # Nothing was left unchecked, so the confirm screen says nothing.
        expect(page.get_by_test_id("unreviewed-notice")).to_have_count(0)

    @pytest.mark.django_db(transaction=True)
    def test_submitting_anyway_is_allowed_and_the_confirm_screen_still_says_so(
        self, page: Page, live_server, school, teacher_user
    ):
        """The teacher's call — but "submit anyway" must not mean the fact
        disappears at the click that actually creates the questions."""
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name="Continue to Confirm").click()
        page.get_by_test_id("review-gate-continue").click()
        page.wait_for_url(lambda url: "/confirm/" in url, timeout=15_000)

        notice = page.get_by_test_id("unreviewed-notice")
        expect(notice).to_be_visible()
        expect(notice).to_contain_text("Q1")

    @pytest.mark.django_db(transaction=True)
    def test_a_question_the_teacher_excluded_does_not_hold_up_the_submit(
        self, page: Page, live_server, school, teacher_user
    ):
        """It is not being imported, so nobody has to check it."""
        session = _session(teacher_user, school)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        page.locator('input[name="q_0_include"]').uncheck()
        page.get_by_role("button", name="Continue to Confirm").click()
        page.wait_for_url(lambda url: "/confirm/" in url, timeout=15_000)
        expect(page.get_by_test_id("unreviewed-notice")).to_have_count(0)
