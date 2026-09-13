"""Playwright UI test — the quiz Submit button stays on screen on a phone (CPP-412).

The short-answer branch of the topic quiz put the answer box, the symbol keypad
and Submit in one non-wrapping flex row. The keypad is a fixed-width grid and
Submit had no shrink allowance, so on a phone the button was pushed off the
right edge: the page scrolled sideways and part of the button could not be
tapped.

Measured on the real quiz page before the fix — the document was 427px wide at
BOTH 390px and 320px viewports, i.e. a hard min-content floor, with the Submit
button sitting at x327..427.

The assertions are deliberately about the page rather than about one CSS rule:
no horizontal scroll, and the whole button inside the viewport. That way the
test still means something if the layout is solved a different way later.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login

# iPhone 14 and iPhone SE — the widest and narrowest phones worth supporting.
PHONE_WIDTHS = [390, 320]


@pytest.fixture
def short_answer_question(db, level, topic):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic,
        question_text='What is 5 + 7?',
        question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
    )
    Answer.objects.create(question=q, answer_text='12', is_correct=True, order=0)
    return q


class TestMobileSubmitOverflow:

    def _open_quiz(self, page, live_server, enrolled_student, level, topic,
                   width):
        # do_login forces a 1280px desktop viewport (the sidebar is hidden
        # below md), so the phone width has to be applied AFTER logging in and
        # before the quiz page is fetched — otherwise the page lays out at
        # desktop width and the overflow this test is about cannot appear.
        do_login(page, live_server.url, enrolled_student)
        page.set_viewport_size({'width': width, 'height': 800})
        page.goto(
            f'{live_server.url}/maths/level/{level.level_number}'
            f'/topic/{topic.id}/quiz/'
        )
        page.wait_for_load_state('domcontentloaded')
        expect(page.locator('#question-card')).to_contain_text('5 + 7')
        # The keypad is injected by maths_exponent.js, and it is what makes the
        # row wide — so nothing can be measured until it is actually there.
        expect(page.locator('.cwa-sym-panel')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_the_page_does_not_scroll_sideways_on_a_phone(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, short_answer_question,
    ):
        for width in PHONE_WIDTHS:
            self._open_quiz(page, live_server, enrolled_student, level, topic,
                            width)

            scroll_width = page.evaluate('document.documentElement.scrollWidth')
            inner_width = page.evaluate('window.innerWidth')
            assert scroll_width <= inner_width, (
                f'at {width}px the page scrolls sideways: '
                f'scrollWidth {scroll_width} > innerWidth {inner_width}'
            )

    @pytest.mark.django_db(transaction=True)
    def test_the_whole_submit_button_is_on_screen_on_a_phone(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, short_answer_question,
    ):
        for width in PHONE_WIDTHS:
            self._open_quiz(page, live_server, enrolled_student, level, topic,
                            width)

            button = page.get_by_role('button', name='Submit')
            box = button.bounding_box()
            assert box is not None, 'the Submit button was not rendered'
            right_edge = box['x'] + box['width']
            assert right_edge <= width, (
                f'at {width}px the Submit button runs to x={right_edge:.0f}, '
                f'{right_edge - width:.0f}px past the right edge of the screen'
            )

    @pytest.mark.django_db(transaction=True)
    def test_the_keypad_is_still_usable_at_the_narrowest_width(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, short_answer_question,
    ):
        """Fixing the overflow must not shrink the keypad out of usefulness."""
        self._open_quiz(page, live_server, enrolled_student, level, topic, 320)

        keys = page.locator('.cwa-sym-panel button')
        assert keys.count() > 0, 'the symbol keypad rendered no keys'
        for i in range(keys.count()):
            box = keys.nth(i).bounding_box()
            assert box is not None and box['width'] >= 24 and box['height'] >= 24, (
                f'key {i} is {box} — too small to tap reliably at 320px'
            )
            assert box['x'] + box['width'] <= 320, f'key {i} is off-screen'

    @pytest.mark.django_db(transaction=True)
    def test_the_desktop_layout_is_unchanged(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, short_answer_question,
    ):
        """Submit still sits BESIDE the answer row at desktop width.

        flex-wrap only takes effect when the line is too narrow to hold both,
        so this pins that the fix is invisible on a desktop: the button shares
        a line with the answer box rather than dropping below it.
        """
        self._open_quiz(page, live_server, enrolled_student, level, topic, 1280)

        row = page.locator('.cwa-answer-row').first.bounding_box()
        button = page.get_by_role('button', name='Submit').bounding_box()
        assert row is not None and button is not None

        # Same line: the button starts to the RIGHT of the answer row and their
        # vertical extents overlap.
        assert button['x'] >= row['x'] + row['width'] - 1, (
            'the Submit button wrapped below the answer row on desktop'
        )
        assert button['y'] < row['y'] + row['height'], (
            'the Submit button dropped to a new line on desktop'
        )
