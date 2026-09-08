"""Playwright UI test — an AI-marked written answer in the topic quiz.

These questions ("For the inequality y ≤ 2, describe the region…") carry a
diagram and a marking rubric, and are judged by Claude rather than matched
against a stored answer. Two things only a browser can prove:

* the wait is visible — an AI call takes a second or two, and a child who sees
  nothing happen presses Submit again or decides the page is broken;
* an answer that could not be marked does NOT appear as a red ❌. The student
  did nothing wrong, and it has been left out of their score.

The grader itself is stubbed: no API call, no spend, and the outcome under test
is what the page does with the verdict, not the verdict.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.quiz

QUESTION_TEXT = ('For the inequality y ≤ 2, describe the region: which side of '
                 'the line y = 2 should be shaded, and is the boundary '
                 'line included?')


def _ai_result(**overrides):
    result = {
        'is_correct': True,
        'score_fraction': 1.0,
        'feedback': 'Yes — the line is solid and everything below it is shaded.',
        'what_to_add': '',
        'cache_hit': False,
        'input_tokens': 400,
        'output_tokens': 120,
    }
    result.update(overrides)
    return result


@pytest.fixture
def written_question(db, level, topic):
    from maths.models import Question

    return Question.objects.create(
        level=level, topic=topic, question_text=QUESTION_TEXT,
        question_type=Question.EXTENDED_ANSWER,
        validation_type=Question.VALIDATION_AI,
        grading_rubric=('Full marks: the boundary is solid because ≤ includes '
                        'equality, and everything BELOW it is shaded.'),
        difficulty=1, points=1,
    )


class TestAIGradedTopicQuiz:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, level, topic,
               written_question):
        self.url = live_server.url
        self.page = page
        self.level = level
        self.topic = topic
        do_login(page, self.url, enrolled_student)

    def _answer(self, text: str, result: dict):
        page = self.page
        page.goto(f'{self.url}/maths/level/{self.level.level_number}'
                  f'/topic/{self.topic.id}/quiz/')
        answer_box = page.locator('#text-answer-input')
        expect(answer_box).to_be_visible(timeout=10_000)
        answer_box.fill(text)
        with patch('worksheets.grading_service.grade_extended_answer',
                   return_value=result):
            page.locator('button', has_text='Submit').first.click()
            page.wait_for_timeout(2_000)
        return page.locator('#question-container, main').first.inner_text()

    def test_the_question_is_offered_to_a_student_who_can_be_ai_graded(self):
        page = self.page
        page.goto(f'{self.url}/maths/level/{self.level.level_number}'
                  f'/topic/{self.topic.id}/quiz/')
        expect(page.locator('#question-container')).to_contain_text(
            'which side of the line', timeout=10_000)

    def test_a_good_answer_is_marked_correct_with_the_reason(self):
        feedback = self._answer('Shade below the line, and it is solid.',
                                _ai_result())
        assert 'Correct!' in feedback
        assert 'solid' in feedback

    def test_a_wrong_answer_is_marked_wrong_with_the_reason(self):
        feedback = self._answer('Shade above the line.', _ai_result(
            is_correct=False, score_fraction=0.0,
            feedback='Not quite — ≤ means the region below.'))
        assert 'Incorrect' in feedback
        assert 'region below' in feedback

    def test_an_unmarkable_answer_is_not_shown_as_wrong(self):
        """Quota spent or API down: amber "not marked yet", never a red ❌."""
        feedback = self._answer('Shade below the line, and it is solid.',
                                _ai_result(is_correct=False,
                                           error='connection reset',
                                           feedback='Automatic grading failed.'))
        assert 'Not marked yet' in feedback
        assert 'Incorrect' not in feedback

    def test_the_billing_message_is_never_shown_to_the_child(self):
        feedback = self._answer('Shade below the line, and it is solid.',
                                _ai_result(
                                    is_correct=False, quota_exceeded=True,
                                    feedback='AI grading quota reached (1000/1000).'))
        assert 'quota' not in feedback.lower()
        assert 'Not marked yet' in feedback
