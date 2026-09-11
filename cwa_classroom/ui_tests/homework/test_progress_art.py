"""Playwright UI test — the progress-art picture on the homework take page.

The panel's whole value is that the drawing grows *while* a child works and is
still there the next day. Neither half can be proved from Python: the live
growth happens entirely in static/js/progress_art.js, and the resume depends on
that JS agreeing with the server about how many answers the saved draft holds.
So this drives the real page.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from ..conftest import do_login


def _pick_answer(page, question):
    """Click the first option of *question*.

    The radio itself is `sr-only`, so Playwright cannot click it — the label is
    the real control on this page, exactly as it is for a student.
    """
    answer = question.answers.order_by("order").first()
    page.locator(f"label[for='ans_{question.id}_{answer.id}']").click()


# How many stroke paths are currently painted. The renderer hides a path until
# it has length to show, so this is a truthful "how much of the picture is on
# screen" without reaching into dash offsets.
_VISIBLE_STROKES = """
() => Array.from(document.querySelectorAll('[data-progress-art] path.pa-stroke'))
        .filter(p => p.style.visibility !== 'hidden').length
"""


@pytest.fixture
def art_homework(db, classroom, teacher_user, level, topic):
    """A four-question multiple-choice homework."""
    from homework.models import Homework, HomeworkQuestion
    from maths.models import Answer, Question

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Progress Art Homework",
        homework_type="topic",
        num_questions=4,
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    questions = []
    for i in range(4):
        q = Question.objects.create(
            level=level, topic=topic,
            question_text=f"What is {i} + 1?",
            question_type=Question.MULTIPLE_CHOICE,
            difficulty=1, points=1,
        )
        Answer.objects.create(question=q, answer_text=str(i + 1), is_correct=True, order=1)
        Answer.objects.create(question=q, answer_text=str(i + 9), is_correct=False, order=2)
        HomeworkQuestion.objects.create(homework=hw, question=q, order=i)
        questions.append(q)
    return hw, questions


class TestHomeworkProgressArt:

    @pytest.mark.django_db(transaction=True)
    def test_answering_draws_more_of_the_picture(
        self, page: Page, live_server, enrolled_student, art_homework
    ):
        hw, questions = art_homework

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        panel = page.locator("[data-progress-art]")
        expect(panel).to_be_visible()
        expect(panel.locator("[data-pa-count]")).to_have_text("0 of 4")

        # Nothing answered — only the free opening dot is on the canvas.
        assert page.evaluate(_VISIBLE_STROKES) == 1
        # …and the title is still a surprise.
        expect(panel.locator(".pa-reveal")).to_be_hidden()

        _pick_answer(page, questions[0])
        expect(panel.locator("[data-pa-count]")).to_have_text("1 of 4")
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll("
            "'[data-progress-art] path.pa-stroke'))"
            ".filter(p => p.style.visibility !== 'hidden').length > 1"
        )

        _pick_answer(page, questions[1])
        expect(panel.locator("[data-pa-count]")).to_have_text("2 of 4")

    @pytest.mark.django_db(transaction=True)
    def test_clearing_an_answer_takes_the_ink_back(
        self, page: Page, live_server, enrolled_student, art_homework
    ):
        """The count tracks what is actually answered, both ways — a picture
        that only ever grew would tell a child they had done work they hadn't."""
        hw, questions = art_homework

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        panel = page.locator("[data-progress-art]")
        _pick_answer(page, questions[0])
        expect(panel.locator("[data-pa-count]")).to_have_text("1 of 4")

        # An MCQ radio cannot be un-checked by clicking, so clear it the way a
        # "clear my answer" control would and let the change event through.

        page.evaluate(
            """(name) => {
                document.querySelectorAll(`[name="${name}"]`)
                        .forEach(el => { el.checked = false; });
                document.querySelector(`[name="${name}"]`)
                        .dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            f"answer_{questions[0].id}",
        )
        expect(panel.locator("[data-pa-count]")).to_have_text("0 of 4")

    @pytest.mark.django_db(transaction=True)
    def test_the_drawing_resumes_where_it_stopped(
        self, page: Page, live_server, enrolled_student, art_homework
    ):
        """The headline requirement: save today, come back tomorrow, same
        picture and the same amount of it already drawn."""
        from homework.models import HomeworkDraft

        hw, questions = art_homework

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        _pick_answer(page, questions[0])
        _pick_answer(page, questions[1])

        # Save & continue later — only leaves the page once the save landed.
        with page.expect_navigation():
            page.get_by_role("button", name="Save & continue later").click()
        page.wait_for_load_state("networkidle")

        draft = HomeworkDraft.objects.get(homework=hw, student=enrolled_student)
        assert draft.art_picture_key, "the picture must be pinned on the draft"
        strokes_before = None

        # Re-open the paper, as if the next day.
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        panel = page.locator("[data-progress-art]")
        expect(panel.locator("[data-pa-count]")).to_have_text("2 of 4")
        strokes_before = page.evaluate(_VISIBLE_STROKES)
        assert strokes_before > 1, "a resumed paper must show the drawing so far"

        # And the SAME picture, not a fresh one.
        title = page.evaluate(
            "() => JSON.parse(document.querySelector("
            "'[data-progress-art] script[type=\"application/json\"]').textContent).key"
        )
        assert title == draft.art_picture_key

    @pytest.mark.django_db(transaction=True)
    def test_finishing_every_question_reveals_the_picture(
        self, page: Page, live_server, enrolled_student, art_homework
    ):
        hw, questions = art_homework

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        for q in questions:
            _pick_answer(page, q)

        panel = page.locator("[data-progress-art]")
        expect(panel.locator("[data-pa-count]")).to_have_text("4 of 4")
        expect(panel.locator(".pa-reveal")).to_be_visible()
        expect(panel.locator("[data-pa-title]")).not_to_be_empty()
