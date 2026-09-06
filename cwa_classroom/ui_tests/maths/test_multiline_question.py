"""Playwright UI test — a multi-line question renders on multiple lines.

135 of the bank's questions carry structure in their text: embedded option
lists, multi-part stems, worked layouts. Every surface printed that into a
plain <p>, and HTML collapses whitespace, so all of them displayed as one
run-on line. ``whitespace-pre-line`` fixes it.

That is a CSS behaviour, so a template test asserting the class name proves
nothing about what a child actually sees. This drives the real take page in
Chromium and reads back the LAID-OUT text: Playwright's ``inner_text()``
reflects rendering (it honours white-space), where ``text_content()`` would
return the raw source and pass either way.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from ..conftest import do_login

STEM = 'Which is the shortest?\n\nA) Your finger\nB) A spoon\nC) A book'


@pytest.fixture
def multiline_question(db, level, topic):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic, question_text=STEM,
        question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1,
    )
    for order, (text, correct) in enumerate(
            [('Your finger', True), ('A spoon', False), ('A book', False)]):
        Answer.objects.create(question=q, answer_text=text,
                              is_correct=correct, order=order)
    return q


@pytest.fixture
def multiline_homework(db, classroom, teacher_user, topic, multiline_question):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title='Multi-line stem', homework_type='topic', num_questions=1,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=multiline_question,
                                    order=0)
    return hw


class TestMultiLineQuestionTake:

    @pytest.mark.django_db(transaction=True)
    def test_the_option_list_is_not_run_together(
        self, page: Page, live_server, enrolled_student, multiline_homework
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/homework/{multiline_homework.pk}/take/')
        page.wait_for_load_state('networkidle')

        stem = page.locator('p.whitespace-pre-line').first
        rendered = stem.inner_text()

        # The laid-out text keeps the author's line breaks ...
        assert 'A) Your finger\nB) A spoon' in rendered, repr(rendered)
        # ... and does NOT run the options onto one line, which is what every
        # one of these questions looked like before.
        assert 'A) Your finger B) A spoon' not in rendered, repr(rendered)
