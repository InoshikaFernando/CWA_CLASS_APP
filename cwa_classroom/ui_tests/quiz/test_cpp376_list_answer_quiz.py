"""Playwright UI test — list answers in the topic quiz (CPP-376).

Reported by a student on
``/maths/level/4/topic/165/quiz/``:

    "What are the multiples of 9 between 50 and 70?
     Answer is 54 and 63 but it says 54 only"

The quiz split the stored answer "54, 63" on the comma and treated the two
values as *alternatives*, so typing the full answer was marked wrong, typing
half of it was marked right, and the feedback named only "54" as the correct
answer. The question now carries answer_format='set' — every value required,
any order. These tests drive the real quiz page to prove all three.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.quiz


@pytest.fixture
def multiples_question(db, level, topic):
    """The reported question: a short answer whose value is a list."""
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic,
        question_text='What are the multiples of 9 between 50 and 70?',
        question_type=Question.SHORT_ANSWER,
        answer_format=Question.ANSWER_FORMAT_SET,
        difficulty=1, points=1,
    )
    Answer.objects.create(question=q, answer_text='54, 63', is_correct=True, order=1)
    return q


class TestListAnswerTopicQuiz:
    """A "list every value" answer grades on the values, not their order."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, level, topic,
               multiples_question):
        self.url = live_server.url
        self.page = page
        self.level = level
        self.topic = topic
        do_login(page, self.url, enrolled_student)

    def _answer(self, text: str):
        """Open the quiz, type ``text`` into the answer box and submit."""
        page = self.page
        page.goto(
            f'{self.url}/maths/level/{self.level.level_number}'
            f'/topic/{self.topic.id}/quiz/'
        )
        page.wait_for_load_state('networkidle')

        answer_box = page.locator('#text-answer-input')
        expect(answer_box).to_be_visible(timeout=10_000)
        answer_box.fill(text)
        page.locator('button', has_text='Submit').first.click()
        page.wait_for_timeout(1_500)
        return page.locator('#question-container, main').first.inner_text()

    def test_full_answer_in_either_order_is_correct(self):
        # Both multiples, listed either way round — the same answer.
        assert 'Correct!' in self._answer('54, 63')
        assert 'Correct!' in self._answer('63, 54')

    def test_natural_phrasing_is_correct(self):
        # A student writing the answer as they would say it.
        assert 'Correct!' in self._answer('54 and 63')

    def test_half_the_answer_is_marked_incorrect(self):
        # The reported bug accepted this; "what ARE the multiples" wants both.
        feedback = self._answer('54')
        assert 'Incorrect' in feedback

    def test_feedback_names_both_values(self):
        # The reported symptom: the student was told the answer was "54".
        feedback = self._answer('45')
        assert 'Incorrect' in feedback
        assert '54, 63' in feedback, (
            'The feedback must show the whole answer, not just its first value. '
            f'Got: {feedback!r}'
        )
