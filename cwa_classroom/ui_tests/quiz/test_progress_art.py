"""Playwright UI test — the progress-art picture during a topic quiz.

A topic quiz swaps each new question into the page with innerHTML rather than
navigating, so the panel is never re-rendered by the server after the first
load: everything depends on the page telling the renderer as each answer is
graded. That handshake only exists in the browser, so it is tested here.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


_VISIBLE_STROKES = """
() => Array.from(document.querySelectorAll('[data-progress-art] path.pa-stroke'))
        .filter(p => p.style.visibility !== 'hidden').length
"""


@pytest.fixture
def quiz_questions(db, level, topic):
    """Four plain multiple-choice questions, enough to watch the count move."""
    from maths.models import Answer, Question

    made = []
    for i in range(4):
        q = Question.objects.create(
            level=level, topic=topic,
            question_text=f"What is {i} + 1?",
            question_type=Question.MULTIPLE_CHOICE,
            difficulty=i + 1, points=1,
        )
        Answer.objects.create(question=q, answer_text=str(i + 1), is_correct=True, order=0)
        Answer.objects.create(question=q, answer_text=str(i + 9), is_correct=False, order=1)
        made.append(q)
    return made


class TestTopicQuizProgressArt:

    @pytest.mark.django_db(transaction=True)
    def test_each_graded_answer_draws_more_of_the_picture(
        self, page: Page, live_server, monkeypatch,
        enrolled_student, school, classroom, level, topic, quiz_questions,
    ):
        # Keep question order deterministic (see test_topic_quiz_interactive_swap).
        monkeypatch.setattr("random.shuffle", lambda seq: None)

        page_errors: list[str] = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        do_login(page, live_server.url, enrolled_student)
        page.goto(
            f"{live_server.url}/maths/level/{level.level_number}"
            f"/topic/{topic.id}/quiz/"
        )
        page.wait_for_load_state("domcontentloaded")

        panel = page.locator("[data-progress-art]")
        expect(panel).to_be_visible()
        count = panel.locator("[data-pa-count]")
        expect(count).to_have_text(re.compile(r"^0 of \d+$"))
        assert page.evaluate(_VISIBLE_STROKES) == 1   # just the opening dot

        # Answer question one — the picture must grow WITH the feedback, not
        # when the next question loads.
        page.locator(".answer-btn").first.click()
        expect(page.locator("#question-card")).to_contain_text(
            re.compile(r"Correct|Not quite", re.I), timeout=10_000)
        expect(count).to_have_text(re.compile(r"^1 of \d+$"))
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll("
            "'[data-progress-art] path.pa-stroke'))"
            ".filter(p => p.style.visibility !== 'hidden').length > 1"
        )

        # …and again on the next question, which arrives via an innerHTML swap.
        next_btn = page.get_by_role("button", name=re.compile(r"Next Question"))
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()
        page.locator(".answer-btn").first.click()
        expect(count).to_have_text(re.compile(r"^2 of \d+$"), timeout=10_000)

        assert not page_errors, page_errors

    @pytest.mark.django_db(transaction=True)
    def test_the_picture_survives_the_question_swap(
        self, page: Page, live_server, monkeypatch,
        enrolled_student, school, classroom, level, topic, quiz_questions,
    ):
        """The panel lives outside #question-container, so swapping a question
        in must not tear it down and restart the drawing."""
        monkeypatch.setattr("random.shuffle", lambda seq: None)

        do_login(page, live_server.url, enrolled_student)
        page.goto(
            f"{live_server.url}/maths/level/{level.level_number}"
            f"/topic/{topic.id}/quiz/"
        )
        page.wait_for_load_state("domcontentloaded")

        key = page.evaluate(
            "() => JSON.parse(document.querySelector("
            "'[data-progress-art] script[type=\"application/json\"]').textContent).key"
        )

        page.locator(".answer-btn").first.click()
        next_btn = page.get_by_role("button", name=re.compile(r"Next Question"))
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()
        expect(page.locator("#question-card")).to_contain_text("What is 1 + 1?")

        after = page.evaluate(
            "() => JSON.parse(document.querySelector("
            "'[data-progress-art] script[type=\"application/json\"]').textContent).key"
        )
        assert after == key
        expect(page.locator("[data-progress-art] [data-pa-count]")).to_have_text(
            re.compile(r"^1 of \d+$"))


class TestPanelSitsBesideTheQuiz:
    """The panel belongs next to the question, not under it.

    It first shipped below the quiz, where it was off-screen on anything but the
    shortest page: a child had to scroll away from the question they were
    answering to see the picture they were earning. base_quiz.html now gives any
    quiz carrying a panel a sticky side column, and these pin that down for both
    quiz shapes — one question at a time, and all of them on one page.
    """

    @pytest.fixture
    def quiz_questions(self, db, level, topic):
        from maths.models import Answer, Question
        made = []
        for i in range(6):
            q = Question.objects.create(
                level=level, topic=topic,
                question_text=f"What is {i} + 4?",
                question_type=Question.MULTIPLE_CHOICE,
                difficulty=i + 1, points=1,
            )
            Answer.objects.create(question=q, answer_text=str(i + 4), is_correct=True, order=0)
            Answer.objects.create(question=q, answer_text=str(i + 9), is_correct=False, order=1)
            made.append(q)
        return made

    def _assert_beside(self, page, quiz_selector):
        quiz = page.locator(quiz_selector).bounding_box()
        panel = page.locator("[data-progress-art]").bounding_box()
        assert quiz is not None and panel is not None
        # Side by side: the panel starts after the quiz column ends, and the two
        # overlap vertically. Stacked-below would fail the first; stacked-above
        # the second.
        assert panel["x"] >= quiz["x"] + quiz["width"] - 1, (quiz, panel)
        assert panel["y"] < quiz["y"] + quiz["height"], (quiz, panel)

    @pytest.mark.django_db(transaction=True)
    def test_topic_quiz_puts_it_beside_the_question(
        self, page: Page, live_server, monkeypatch,
        enrolled_student, school, classroom, level, topic, quiz_questions,
    ):
        monkeypatch.setattr("random.shuffle", lambda seq: None)
        do_login(page, live_server.url, enrolled_student)
        page.set_viewport_size({"width": 1400, "height": 900})
        page.goto(
            f"{live_server.url}/maths/level/{level.level_number}"
            f"/topic/{topic.id}/quiz/"
        )
        page.wait_for_load_state("domcontentloaded")
        expect(page.locator("[data-progress-art]")).to_be_visible()
        self._assert_beside(page, "#question-card")

    @pytest.mark.django_db(transaction=True)
    def test_mixed_quiz_puts_it_beside_the_questions(
        self, page: Page, live_server, enrolled_student,
        school, classroom, level, topic, quiz_questions,
    ):
        do_login(page, live_server.url, enrolled_student)
        page.set_viewport_size({"width": 1400, "height": 900})
        page.goto(f"{live_server.url}/maths/level/{level.level_number}/quiz/")
        page.wait_for_load_state("networkidle")
        self._assert_beside(page, "#mixed-form")

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_panel_is_rendered(
        self, page: Page, live_server, enrolled_student,
        school, classroom, level, topic, quiz_questions,
    ):
        """base_quiz.html owns the placement now. When the mixed quiz built its
        own column as well, the page carried two."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/maths/level/{level.level_number}/quiz/")
        page.wait_for_load_state("networkidle")
        expect(page.locator("[data-progress-art]")).to_have_count(1)

    @pytest.mark.django_db(transaction=True)
    def test_a_quiz_without_a_panel_keeps_its_narrow_column(
        self, page: Page, live_server, enrolled_student, level,
    ):
        """The times-tables drill shares base_quiz.html and supplies no panel,
        so it must not inherit the widened two-column shell."""
        do_login(page, live_server.url, enrolled_student)
        page.set_viewport_size({"width": 1400, "height": 900})
        page.goto(
            f"{live_server.url}/maths/level/{level.level_number}"
            f"/multiplication/3/"
        )
        page.wait_for_load_state("networkidle")
        expect(page.locator("[data-progress-art]")).to_have_count(0)
        main = page.locator("main").bounding_box()
        assert main["width"] <= 800, main   # max-w-3xl plus its padding
