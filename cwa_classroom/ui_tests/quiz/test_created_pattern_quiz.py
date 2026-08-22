"""Playwright UI test — "create your own" pattern questions in the topic quiz.

Reported from ``/maths/level/4/topic/147/quiz/``, question 2 of 16:

    "Create your own tricky subtraction number pattern of six numbers and
     write down the rule you used."

A student answered ``20,18, 16, 14, 12, 10`` — six numbers, two off each time —
and the quiz said ❌ Incorrect, with no correct answer shown beside it. The
question stores no correct answer (there is no single right one), and a typed
answer with nothing to match against scored zero, for every student, always.

The question now carries answer_format='pattern' — graded against what the
question asks for, with the grader's own sentence shown as feedback. These
tests drive the real quiz page, because the feedback box is rendered by the
page's JavaScript and only a browser proves it reaches the student.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.quiz

QUESTION_TEXT = ('Create your own tricky subtraction number pattern of six '
                 'numbers and write down the rule you used.')


@pytest.fixture
def pattern_question(db, level, topic):
    """The reported question, authored as the live one is: no Answer rows."""
    from maths.models import Question

    return Question.objects.create(
        level=level, topic=topic,
        question_text=QUESTION_TEXT,
        question_type=Question.SHORT_ANSWER,
        answer_format=Question.ANSWER_FORMAT_PATTERN,
        explanation=('A subtraction pattern takes away the same amount each '
                     'time, e.g. rule -7 gives 60, 53, 46, 39, 32, 25.'),
        difficulty=1, points=1,
    )


class TestCreateYourOwnPatternTopicQuiz:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, level, topic,
               pattern_question):
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

    def test_the_reported_answer_is_marked_correct(self):
        # The exact answer from the report, comma spacing and all.
        assert 'Correct!' in self._answer('20,18, 16, 14, 12, 10')

    def test_the_student_is_told_why_it_was_right(self):
        feedback = self._answer('20,18, 16, 14, 12, 10')
        assert 'goes down by 2' in feedback, (
            'The mark on a question with no printable answer has to explain '
            f'itself. Got: {feedback!r}')

    def test_a_pattern_with_a_broken_step_is_incorrect(self):
        feedback = self._answer('20, 18, 15, 14, 12, 10')
        assert 'Incorrect' in feedback
        assert '18 to 15' in feedback, (
            f'The feedback must name the number that broke it. Got: {feedback!r}')

    def test_an_addition_pattern_does_not_answer_a_subtraction_question(self):
        feedback = self._answer('2, 4, 6, 8, 10, 12')
        assert 'Incorrect' in feedback
        assert 'subtraction' in feedback

    def test_a_wrong_answer_is_shown_a_worked_example(self):
        # The reported symptom was an ❌ with nothing beside it.
        feedback = self._answer('i dont know')
        assert 'Incorrect' in feedback
        assert 'for example' in feedback.lower(), (
            'A question with no stored answer must still show the student '
            f'what a right answer looks like. Got: {feedback!r}')
