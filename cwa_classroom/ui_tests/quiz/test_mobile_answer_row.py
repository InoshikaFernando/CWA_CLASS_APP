"""Playwright UI test — the quiz answer row fits a phone screen (CPP-412).

The short-answer row carries three things once maths_exponent.js has injected
the symbol keypad: the answer box, the keypad, and Submit. The row could not
wrap, and the keypad's 3-column grid holds a ~120px floor that will not shrink,
so on a phone Submit was pushed clean off the right edge — at 390px it sat at
x327..427, 37px past the screen, and the page scrolled sideways with the button
clipped.

These assert the property that was violated rather than a pixel layout: nothing
on the page extends past the viewport, and Submit is reachable. Written against
the real topic quiz, because the bug only appears once the keypad is in the row
— a template-only test would never have seen it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login

# iPhone SE, iPhone 14, and a small Android — the widths a student actually has.
PHONE_WIDTHS = [320, 360, 390]


@pytest.fixture
def short_answer_question(db, level, topic):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level,
        topic=topic,
        question_text=(
            "Solve the equation, rounding to two decimal places: x² = 23"
        ),
        question_type=Question.SHORT_ANSWER,
        difficulty=1,
        points=1,
    )
    Answer.objects.create(question=q, answer_text="x=±4.80", is_correct=True, order=0)
    return q


def _open_quiz(page, live_server, student, level, topic):
    do_login(page, live_server.url, student)
    page.goto(
        f"{live_server.url}/maths/level/{level.level_number}"
        f"/topic/{topic.id}/quiz/"
    )
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("#question-card")).to_contain_text("x² = 23")


def _resize(page, width):
    """Resize AFTER login — conftest's do_login forces a 1280x800 desktop
    viewport, so setting the phone size before it would be overwritten."""
    page.set_viewport_size({"width": width, "height": 844})
    page.wait_for_timeout(250)


class TestAnswerRowFitsAPhone:

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize("width", PHONE_WIDTHS)
    def test_the_page_does_not_scroll_sideways(
        self, page: Page, live_server, enrolled_student, school, classroom,
        level, topic, short_answer_question, width,
    ):
        _open_quiz(page, live_server, enrolled_student, level, topic)
        _resize(page, width)

        overflowing = page.evaluate("""() => {
          const vw = window.innerWidth;
          const out = [];
          document.querySelectorAll('*').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.right > vw + 0.5) {
              out.push(el.tagName.toLowerCase() + '.' +
                       (el.className || '').toString().slice(0, 40));
            }
          });
          return out;
        }""")
        assert overflowing == [], (
            f"at {width}px these elements extend past the viewport: {overflowing}"
        )

        doc_width = page.evaluate("document.documentElement.scrollWidth")
        assert doc_width <= width, (
            f"at {width}px the page scrolls sideways (scrollWidth {doc_width})"
        )

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize("width", PHONE_WIDTHS)
    def test_the_submit_button_is_fully_on_screen(
        self, page: Page, live_server, enrolled_student, school, classroom,
        level, topic, short_answer_question, width,
    ):
        _open_quiz(page, live_server, enrolled_student, level, topic)
        _resize(page, width)

        submit = page.locator('button[onclick*="submitTextAnswer"]')
        expect(submit).to_be_visible()
        box = submit.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width + 0.5, (
            f"at {width}px Submit sits at x{box['x']:.0f}..{box['x'] + box['width']:.0f}, "
            f"outside the {width}px screen"
        )

    @pytest.mark.django_db(transaction=True)
    def test_the_keypad_is_still_usable_on_a_phone(
        self, page: Page, live_server, enrolled_student, school, classroom,
        level, topic, short_answer_question,
    ):
        """Wrapping must not be paid for by shrinking the keys out of reach."""
        _open_quiz(page, live_server, enrolled_student, level, topic)
        _resize(page, 320)

        keys = page.locator(".cwa-sym-panel .cwa-sym-btn")
        assert keys.count() >= 11, "the symbol keypad lost keys on a phone"
        for i in range(keys.count()):
            box = keys.nth(i).bounding_box()
            assert box["width"] >= 28 and box["height"] >= 28, (
                f"keypad key {i} is {box['width']:.0f}x{box['height']:.0f} — too small to tap"
            )
            assert box["x"] + box["width"] <= 320.5, f"keypad key {i} is off-screen"

    @pytest.mark.django_db(transaction=True)
    def test_a_student_can_still_answer_on_a_phone(
        self, page: Page, live_server, enrolled_student, school, classroom,
        level, topic, short_answer_question,
    ):
        """The button has to work, not merely be on screen."""
        from maths.models import StudentAnswer

        _open_quiz(page, live_server, enrolled_student, level, topic)
        _resize(page, 390)

        page.locator("#text-answer-input").click()
        page.keyboard.type("x=4.80 or x=-4.80")
        page.locator('button[onclick*="submitTextAnswer"]').click()

        expect(page.locator("#question-card")).to_contain_text(
            "Correct", timeout=10_000
        )
        assert StudentAnswer.objects.filter(
            student=enrolled_student, question=short_answer_question,
        ).exists()

    @pytest.mark.django_db(transaction=True)
    def test_the_desktop_layout_is_unchanged(
        self, page: Page, live_server, enrolled_student, school, classroom,
        level, topic, short_answer_question,
    ):
        """Submit stays beside the answer box on a desktop — the wrap is only
        meant to engage when the row genuinely cannot fit."""
        _open_quiz(page, live_server, enrolled_student, level, topic)
        _resize(page, 1280)

        input_box = page.locator("#text-answer-input").bounding_box()
        submit_box = page.locator('button[onclick*="submitTextAnswer"]').bounding_box()
        assert abs(submit_box["y"] - input_box["y"]) < 5, (
            "Submit dropped below the answer box on a desktop viewport"
        )
        assert submit_box["x"] > input_box["x"], "Submit is no longer to the right"
