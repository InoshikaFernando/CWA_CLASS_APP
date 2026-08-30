"""Playwright UI test — "create your own" pattern questions in the topic quiz.

Reported from ``/maths/level/4/topic/147/quiz/``, question 2 of 16:

    "Create your own tricky subtraction number pattern of six numbers and
     write down the rule you used."

A student answered ``20,18, 16, 14, 12, 10`` — six numbers, two off each time —
and the quiz said ❌ Incorrect, with no correct answer shown beside it. The
question stores no correct answer (there is no single right one), and a typed
answer with nothing to match against scored zero, for every student, always.

The question now carries answer_format='pattern' — graded against what the
question asks for, with the grader's own sentence shown as feedback — and it is
answered into a box per number plus a box for the rule rather than one empty
text field, so the shape of the answer is asked for rather than guessed at.
These tests drive the real quiz page, because both the boxes and the feedback
box are built by the page's JavaScript and only a browser proves what reaches
the student.
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

    def _open(self):
        """Open the quiz and wait for the pattern boxes to mount."""
        page = self.page
        page.goto(
            f'{self.url}/maths/level/{self.level.level_number}'
            f'/topic/{self.topic.id}/quiz/'
        )
        expect(page.locator('[data-pat-stage]')).to_be_visible(timeout=10_000)
        return page

    def _answer(self, numbers, rule=''):
        """Open the quiz, fill the boxes and submit.

        *numbers* is what goes in the number boxes, in order — a list, or a
        comma-separated string for the answers quoted from the report.
        """
        if isinstance(numbers, str):
            numbers = [n.strip() for n in numbers.split(',')]
        page = self._open()
        boxes = page.locator('[data-pat-number]')
        for i, value in enumerate(numbers):
            boxes.nth(i).fill(value)
        if rule:
            page.locator('[data-pat-rule]').fill(rule)
        page.locator('button', has_text='Submit').first.click()
        page.wait_for_timeout(1_500)
        return page.locator('#question-container, main').first.inner_text()

    # ---- the boxes -------------------------------------------------------

    def test_the_question_asks_for_six_numbers_and_shows_six_boxes(self):
        page = self._open()
        expect(page.locator('[data-pat-number]')).to_have_count(6)

    def test_there_is_somewhere_to_write_the_rule(self):
        """The question asks for the rule; a single text box never said where
        to put it."""
        page = self._open()
        expect(page.locator('[data-pat-rule]')).to_be_visible()
        assert 'The rule is' in page.locator('#question-container, main').first.inner_text()

    def test_the_boxes_compose_the_answer_the_grader_reads(self):
        page = self._open()
        boxes = page.locator('[data-pat-number]')
        for i, value in enumerate(['20', '18', '16', '14', '12', '10']):
            boxes.nth(i).fill(value)
        page.locator('[data-pat-rule]').fill('subtract 2')
        assert page.locator('[data-pat-hidden]').input_value() == (
            '20, 18, 16, 14, 12, 10 — rule: subtract 2')

    def test_an_untouched_set_of_boxes_is_not_submitted(self):
        """Submitting nothing would burn the question as wrong."""
        page = self._open()
        page.locator('button', has_text='Submit').first.click()
        page.wait_for_timeout(1_000)
        body = page.locator('#question-container, main').first.inner_text()
        assert 'Correct' not in body and 'Incorrect' not in body

    # ---- the mark --------------------------------------------------------

    def test_the_reported_answer_is_marked_correct(self):
        # The exact answer from the report, one number per box.
        assert 'Correct!' in self._answer('20,18, 16, 14, 12, 10')

    def test_the_student_is_told_why_it_was_right(self):
        feedback = self._answer('20,18, 16, 14, 12, 10')
        assert 'goes down by 2' in feedback, (
            'The mark on a question with no printable answer has to explain '
            f'itself. Got: {feedback!r}')

    def test_the_rule_box_is_not_read_as_a_seventh_number(self):
        """A rule of "2" beside six numbers is a rule, not a seventh number —
        read as seven the pattern is the wrong length and breaks at the end."""
        feedback = self._answer('20, 18, 16, 14, 12, 10', rule='2')
        assert 'Correct!' in feedback, feedback

    def test_a_rule_that_contradicts_the_numbers_is_caught(self):
        feedback = self._answer('20, 18, 16, 14, 12, 10', rule='subtract 5')
        assert 'Incorrect' in feedback
        assert '5' in feedback

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
        feedback = self._answer(['i dont know'])
        assert 'Incorrect' in feedback
        assert 'for example' in feedback.lower(), (
            'A question with no stored answer must still show the student '
            f'what a right answer looks like. Got: {feedback!r}')
