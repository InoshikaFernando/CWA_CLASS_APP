"""Playwright UI test — multiple-choice grading and answer recording (CPP-377).

Reported by a student on ``/maths/level/7/topic/75/quiz/``:

    "THIS QESTION WAS SUPOSED TO BE CORRECT"

Two defects sat behind it. The first was in the *content*: 14 of the 57
questions on that topic offered a distractor numerically equal to the correct
answer ('2/6' alongside '1/3', '9/3 kg' alongside '3 kg'), so a student who
solved the problem and picked the unsimplified form of their own answer was
marked wrong. That is a data fault, fixed in the questions and prevented from
returning by ``manage.py verify_quiz_grading`` — grading by ``is_correct`` is
the intended behaviour, so there is nothing to assert about it here.

The second was in the *code*: the quiz saved only ``is_correct`` and never
which option was clicked, which is why the report could not be checked against
the data at all. These tests drive the real quiz page in a browser to prove the
chosen option now survives to the database.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.quiz


@pytest.fixture
def fractions_question(db, level, topic):
    """A well-formed MC question in the shape of the reported topic.

    Every option is a genuinely different value — which is what the fixed
    content looks like.
    """
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic,
        question_text='A bag contains 5/6 kg of apples. If 1/2 kg is removed, how much is left?',
        question_type=Question.MULTIPLE_CHOICE,
        difficulty=1, points=1,
    )
    q.correct_option = Answer.objects.create(
        question=q, answer_text='1/3', is_correct=True, order=1)
    q.wrong_option = Answer.objects.create(
        question=q, answer_text='1/6', is_correct=False, order=2)
    Answer.objects.create(
        question=q, answer_text='1/2', is_correct=False, order=3)
    return q


class TestTopicQuizAnswerRecording:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, level, topic,
               fractions_question):
        self.url = live_server.url
        self.page = page
        self.level = level
        self.topic = topic
        self.question = fractions_question
        self.student = enrolled_student
        do_login(page, self.url, enrolled_student)

    def _click_option(self, answer):
        """Open the quiz and click one answer button, as a student would."""
        page = self.page
        page.goto(
            f'{self.url}/maths/level/{self.level.level_number}'
            f'/topic/{self.topic.id}/quiz/'
        )
        page.wait_for_load_state('networkidle')

        button = page.locator(f'.answer-btn[data-answer-id="{answer.id}"]')
        expect(button).to_be_visible(timeout=10_000)
        button.click()
        page.wait_for_timeout(1_500)
        return page.locator('#question-container, main').first.inner_text()

    def test_correct_option_is_accepted(self):
        assert 'Correct!' in self._click_option(self.question.correct_option)

    def test_wrong_option_is_rejected(self):
        assert 'Correct!' not in self._click_option(self.question.wrong_option)

    def test_clicked_option_is_recorded(self):
        """The heart of CPP-377: a real click must leave a recoverable record.

        Before the fix the row stored only is_correct, so a student's report
        that they were marked wrong unfairly could not be checked — there was
        no way to see what they had actually clicked.
        """
        from maths.models import StudentAnswer

        self._click_option(self.question.wrong_option)

        row = (StudentAnswer.objects
               .filter(student=self.student, question=self.question)
               .latest('answered_at'))
        assert row.selected_answer_id == self.question.wrong_option.id, (
            'the option clicked in the browser was not recorded on the '
            'StudentAnswer row'
        )
        assert row.is_correct is False
