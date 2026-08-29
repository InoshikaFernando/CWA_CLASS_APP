"""Playwright UI test — completing a pattern the QUESTION prints, in the quiz.

Reported from ``/maths/level/4/topic/147/quiz/``, question 1 of 16:

    "Work out the number pattern rule and complete the pattern:
     30, ___, 60, 75, ___, ___. What is the rule?"

A student answered ``add 15 " 45, 90, 105 "`` — the rule AND the three missing
numbers, which is everything the question asked for — and the quiz said
❌ Incorrect above "Correct answer: +15 or add 15 or + 15". The question's
Answer rows hold only the rule, so the numbers the student was told to work out
made their answer match none of them.

The grader now checks an answer like this against the sequence printed in the
question itself (``maths.pattern_grading.completes_printed_pattern``). These
tests drive the real quiz page, because the mark and the feedback box are
rendered by the page's JavaScript and only a browser proves what the student
sees.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.quiz

QUESTION_TEXT = ('Work out the number pattern rule and complete the pattern: '
                 '30, ___, 60, 75, ___, ___. What is the rule?')


@pytest.fixture
def completion_question(db, level, topic):
    """The reported question, authored as the live one is: the rule is stored
    as the answer, in its three spellings, and the missing numbers are not."""
    from maths.models import Answer, Question

    question = Question.objects.create(
        level=level, topic=topic,
        question_text=QUESTION_TEXT,
        question_type=Question.SHORT_ANSWER,
        answer_format=Question.ANSWER_FORMAT_TEXT,
        explanation=('75 - 60 = 15, so the pattern increases by 15 each time. '
                     'The full pattern is 30, 45, 60, 75, 90, 105.'),
        difficulty=1, points=1,
    )
    for text in ('+15', 'add 15', '+ 15'):
        Answer.objects.create(question=question, answer_text=text,
                              is_correct=True)
    return question


class TestCompleteThePatternTopicQuiz:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, level, topic,
               completion_question):
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
        answer_box = page.locator('#text-answer-input')
        expect(answer_box).to_be_visible(timeout=10_000)
        answer_box.fill(text)
        page.locator('button', has_text='Submit').first.click()
        page.wait_for_timeout(1_500)
        return page.locator('#question-container, main').first.inner_text()

    def test_the_reported_answer_is_marked_correct(self):
        # The exact answer from the report, stray quote marks and all.
        assert 'Correct!' in self._answer('add 15 " 45, 90, 105 "')

    def test_the_stored_answer_on_its_own_is_still_correct(self):
        assert 'Correct!' in self._answer('+15')

    def test_the_numbers_may_come_before_the_rule(self):
        assert 'Correct!' in self._answer('45, 90, 105 - rule: add 15')

    def test_a_wrong_missing_number_is_still_incorrect(self):
        feedback = self._answer('add 15 " 45, 90, 100 "')
        assert 'Incorrect' in feedback
        assert '+15' in feedback, (
            'A wrong answer must still be shown the stored one. '
            f'Got: {feedback!r}')

    def test_a_wrong_rule_is_still_incorrect(self):
        assert 'Incorrect' in self._answer('45, 90, 105 - rule: add 5')
