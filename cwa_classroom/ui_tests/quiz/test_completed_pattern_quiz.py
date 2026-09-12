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
from ..helpers import content_excluding_progress_art

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


@pytest.fixture
def converted_question(db, completion_question):
    """The same question after ``convert_fill_blanks --add-rule-blank``.

    Converted through the real command, not by hand-writing a spec: what is
    being checked is that what the command produces is what the quiz can
    render and mark.
    """
    from django.core.management import call_command
    from io import StringIO

    call_command('convert_fill_blanks', '--add-rule-blank', '--apply',
                 '--id', str(completion_question.pk), stdout=StringIO())
    completion_question.refresh_from_db()
    return completion_question


class TestConvertedPatternTopicQuiz:
    """The same question as a fill-in-the-blank sentence, in the quiz.

    Four gaps — 45, 90, 105 and the rule — instead of one box for the lot, so
    three right out of four is no longer worth nothing. The gaps are collected
    into a hidden field by static/js/fill_blank.js; if that never mounts on the
    quiz page the payload stays empty and every student is marked wrong, which
    no server-side test would catch.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, level, topic,
               converted_question):
        self.url = live_server.url
        self.page = page
        self.level = level
        self.topic = topic
        self.question = converted_question
        do_login(page, self.url, enrolled_student)

    def _open(self):
        self.page.goto(
            f'{self.url}/maths/level/{self.level.level_number}'
            f'/topic/{self.topic.id}/quiz/'
        )
        stage = self.page.locator('[data-fb-stage]')
        expect(stage).to_be_visible(timeout=10_000)
        return stage

    def _answer(self, *values):
        self._open()
        inputs = self.page.locator('[data-fb-input]')
        for index, value in enumerate(values):
            inputs.nth(index).fill(value)
        self.page.locator('button', has_text='Submit').first.click()
        self.page.wait_for_timeout(1_500)
        return self.page.locator('#question-container, main').first.inner_text()

    def test_the_sentence_renders_with_a_gap_for_each_answer(self):
        stage = self._open()
        expect(stage.locator('[data-fb-input]')).to_have_count(4)
        expect(stage).to_contain_text('complete the pattern')
        expect(stage).to_contain_text('What is the rule?')

    def test_the_rule_gap_is_labelled_on_its_own_line(self):
        # A bare box under the sequence gives a child no way to know it wants
        # the rule rather than another number.
        stage = self._open()
        expect(stage).to_contain_text('The rule is:')
        assert stage.locator('br').count() >= 1, (
            'the rule sentence must render on its own line, not run on from '
            'the sequence')

    def test_the_answers_never_reach_the_page(self):
        self._open()
        # Everything except the progress-art panel, whose picture is a few
        # hundred SVG coordinates in which a bare "105" shows up by coincidence
        # — see the helper. The check stays whole-page for all real markup.
        body = content_excluding_progress_art(self.page)
        assert '105' not in body
        assert 'add 15' not in body

    def test_every_gap_right_is_marked_correct(self):
        assert 'Correct!' in self._answer('45', '90', '105', '+15')

    def test_the_rule_gap_takes_the_wording_the_child_writes(self):
        assert 'Correct!' in self._answer('45', '90', '105', 'add 15')

    def test_one_wrong_gap_fails_the_sentence_but_not_for_nothing(self):
        # The whole reason for converting: one slip no longer scores zero, and
        # the student is told which gap cost the mark.
        feedback = self._answer('45', '90', '100', '+15')
        assert 'partly correct' in feedback
        assert '3 of the 4 blanks are right' in feedback
        assert 'Blank 3: you wrote 100 — the answer is 105' in feedback

    def test_a_wrong_rule_costs_the_rule_gap_and_nothing_else(self):
        feedback = self._answer('45', '90', '105', 'add 5')
        assert '3 of the 4 blanks are right' in feedback
