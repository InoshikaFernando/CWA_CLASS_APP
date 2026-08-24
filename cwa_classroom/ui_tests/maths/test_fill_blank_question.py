"""Playwright UI test — fill-in-the-blank question end-to-end.

A student opens a homework containing a fill-in-the-blank question, sees the
sentence laid out with an input sitting in each gap (not one box for the whole
thing, and not the sentence printed twice), types into the gaps, submits, and
the submission is graded gap by gap: correct only when every gap is right, but
worth the share of the gaps that are. Mirrors the fixtures in
test_measure_question.py.

The JS half matters as much as the grading half here: the gaps are collected
into a hidden field by static/js/fill_blank.js, mounted through the shared
maths_mounts.js registry. If that never mounts, the hidden field stays empty and
every student is marked wrong — which no server-side test would catch.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from ..conftest import do_login

SENTENCE = (
    "Out of 100 000 births, 99 231 females are expected to survive to the age "
    "of ___. From that age, the survivors are expected to ___ for another "
    "67.0 years."
)


@pytest.fixture
def blank_question(db, level, topic):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level,
        topic=topic,
        question_text=SENTENCE,
        question_type=Question.FILL_BLANK,
        difficulty=1,
        points=1,
        blank_spec={
            "blanks": [{"answers": ["15"]}, {"answers": ["live", "survive"]}],
        },
    )
    # The pre-conversion answer row a converted question keeps. It must not be
    # what grades, and must not leak into the page.
    Answer.objects.create(question=q, answer_text="15; live", is_correct=True)
    return q


@pytest.fixture
def blank_homework_ready(db, classroom, teacher_user, topic, blank_question):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Fill Blank E2E",
        homework_type="topic",
        num_questions=1,
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=blank_question, order=0)
    return hw


def _open_take(page, live_server, student, homework):
    do_login(page, live_server.url, student)
    page.goto(f"{live_server.url}/homework/{homework.pk}/take/")
    page.wait_for_load_state("networkidle")


def _submit(page):
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
    page.wait_for_load_state("networkidle")


def _answer(homework, student, question):
    from homework.models import HomeworkStudentAnswer, HomeworkSubmission

    sub = HomeworkSubmission.objects.filter(
        homework=homework, student=student
    ).first()
    assert sub is not None
    return HomeworkStudentAnswer.objects.get(submission=sub, question=question)


class TestFillBlankQuestionTake:

    @pytest.mark.django_db(transaction=True)
    def test_sentence_renders_with_one_input_per_gap(
        self, page: Page, live_server, enrolled_student, blank_homework_ready, blank_question
    ):
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        stage = page.locator("[data-fb-stage]")
        expect(stage).to_be_visible()
        expect(stage.locator("[data-fb-input]")).to_have_count(2)
        # The sentence around the gaps is what the student reads.
        expect(stage).to_contain_text("Out of 100 000 births")
        expect(stage).to_contain_text("for another")

    @pytest.mark.django_db(transaction=True)
    def test_the_question_is_not_printed_twice(
        self, page: Page, live_server, enrolled_student, blank_homework_ready
    ):
        """The sentence IS the widget, so the take page must not also print it
        above as plain text."""
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        body = page.content()
        assert body.count("Out of 100 000 births") == 1

    @pytest.mark.django_db(transaction=True)
    def test_the_answers_never_reach_the_page(
        self, page: Page, live_server, enrolled_student, blank_homework_ready
    ):
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        body = page.content()
        assert "15; live" not in body          # the stored answer row
        assert "live or survive" not in body   # the answer-key form

    @pytest.mark.django_db(transaction=True)
    def test_no_symbol_keypad_hangs_off_a_gap(
        self, page: Page, live_server, enrolled_student, blank_homework_ready
    ):
        """A gap must not carry the "cwa-exp-input" class.

        maths_exponent.js moves any field with it into a flex row and hangs a
        12-button symbol keypad beside it — right for one answer box at the end
        of a question, and ruinous for a gap inside a sentence: every gap gets
        its own keypad and the sentence breaks apart into stacked blocks.
        """
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        stage = page.locator("[data-fb-stage]")
        expect(stage.locator(".cwa-sym-panel")).to_have_count(0)
        expect(stage.locator(".cwa-answer-row")).to_have_count(0)

    @pytest.mark.django_db(transaction=True)
    def test_the_gaps_sit_on_the_line_of_their_own_text(
        self, page: Page, live_server, enrolled_student, blank_homework_ready
    ):
        """The sentence reads as a sentence: the first gap sits beside the words
        before it, not on a line of its own below them."""
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        sentence = page.locator("[data-fb-stage] p").bounding_box()
        gap = page.locator("[data-fb-input]").first.bounding_box()
        # The gap starts within the first line of the paragraph, and is nowhere
        # near full width (a block-level input would span the card).
        assert gap["y"] - sentence["y"] < 40
        assert gap["width"] < sentence["width"] / 2

    @pytest.mark.django_db(transaction=True)
    def test_typing_syncs_the_gaps_into_the_hidden_field(
        self, page: Page, live_server, enrolled_student, blank_homework_ready
    ):
        """fill_blank.js mounts through maths_mounts.js and keeps the payload in
        step with the inputs — without it the hidden field stays empty and every
        student is graded wrong."""
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        inputs = page.locator("[data-fb-input]")
        inputs.nth(0).fill("15")
        inputs.nth(1).fill("live")

        # fill() fires a real input event, which is what the widget listens for.
        payload = json.loads(page.locator("[data-fb-hidden]").input_value())
        assert payload == {"blanks": ["15", "live"]}

    @pytest.mark.django_db(transaction=True)
    def test_every_gap_right_is_marked_correct(
        self, page: Page, live_server, enrolled_student, blank_homework_ready, blank_question
    ):
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        inputs = page.locator("[data-fb-input]")
        inputs.nth(0).fill("15")
        inputs.nth(1).fill("survive")   # the second accepted spelling
        _submit(page)

        ans = _answer(blank_homework_ready, enrolled_student, blank_question)
        assert ans.is_correct is True
        assert ans.points_earned == blank_question.points

    @pytest.mark.django_db(transaction=True)
    def test_one_wrong_gap_fails_the_sentence_but_keeps_the_other_gaps_marks(
        self, page: Page, live_server, enrolled_student, blank_homework_ready, blank_question
    ):
        """One gap of two: not a correct sentence, and not worth nothing."""
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        inputs = page.locator("[data-fb-input]")
        inputs.nth(0).fill("15")
        inputs.nth(1).fill("die")
        _submit(page)

        ans = _answer(blank_homework_ready, enrolled_student, blank_question)
        assert ans.is_correct is False
        assert ans.points_earned == blank_question.points * 0.5
        assert ans.answer_data["parts_correct"] == 1
        assert ans.answer_data["parts_total"] == 2

    @pytest.mark.django_db(transaction=True)
    def test_result_page_shows_the_answer_readably(
        self, page: Page, live_server, enrolled_student, blank_homework_ready
    ):
        """A blanks payload is JSON; the review must show "15, die", not the
        raw payload, and must name what the answer should have been."""
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        inputs = page.locator("[data-fb-input]")
        inputs.nth(0).fill("15")
        inputs.nth(1).fill("die")
        _submit(page)

        body = page.content()
        assert '{"blanks"' not in body
        assert "15, die" in body
        # A partly-right answer is still told the whole answer, not only the
        # gap it lost.
        assert "15, live or survive" in body

    @pytest.mark.django_db(transaction=True)
    def test_result_page_explains_which_gap_was_wrong(
        self, page: Page, live_server, enrolled_student, blank_homework_ready
    ):
        """The mark is partial, so the page says so and names the gap that
        cost it — "Not quite right" for work that was half correct tells the
        student nothing they can act on."""
        _open_take(page, live_server, enrolled_student, blank_homework_ready)

        inputs = page.locator("[data-fb-input]")
        inputs.nth(0).fill("15")
        inputs.nth(1).fill("die")
        _submit(page)

        body = page.content()
        assert "Partially correct" in body
        assert "1 of the 2 blanks are right." in body
        assert "Blank 2" in body
