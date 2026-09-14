"""Playwright UI test — a money answer typed without the $ is marked right.

The unit tests pin ``match_value``; this drives the whole path a child takes —
type into the take page, submit, get graded — because that is where the mark is
won or lost.

It also covers the path the unit tests cannot see: ``grade_text_answer``
reimplements the text comparison inline rather than calling ``match_value``, so
a fix applied only to the shared helper leaves the real take page still marking
the answer wrong. That is exactly how CPP-360 nearly shipped half-fixed.

The guard case rides along: a question whose key states two decimal places is
still not answered by one.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from ..conftest import do_login

MONEY_KEY = '$1.25'          # as a money question is usually authored


def _make_question(level, topic, key):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic,
        question_text='A pen costs 125 cents. Write that in dollars.',
        question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
    )
    Answer.objects.create(question=q, answer_text=key, is_correct=True, order=0)
    return q


def _make_homework(classroom, teacher_user, topic, question, title):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title=title, homework_type='topic', num_questions=1,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=question, order=0)
    return hw


def _submit(page, live_server, student, homework, question, typed):
    from homework.models import HomeworkStudentAnswer, HomeworkSubmission

    do_login(page, live_server.url, student)
    page.goto(f'{live_server.url}/homework/{homework.pk}/take/')
    page.wait_for_load_state('networkidle')

    page.locator(f"input[name='answer_{question.pk}']").fill(typed)
    with page.expect_navigation():
        page.get_by_role(
            'button', name=re.compile(r'Submit Homework', re.I)).click()
    page.wait_for_load_state('networkidle')

    submission = HomeworkSubmission.objects.filter(
        homework=homework, student=student).first()
    assert submission is not None
    return submission, HomeworkStudentAnswer.objects.get(
        submission=submission, question=question)


class TestMoneyFormattingGrading:

    @pytest.mark.django_db(transaction=True)
    def test_the_amount_without_a_dollar_sign_is_marked_correct(
        self, page: Page, live_server, enrolled_student, classroom,
        teacher_user, level, topic,
    ):
        question = _make_question(level, topic, MONEY_KEY)
        homework = _make_homework(classroom, teacher_user, topic, question,
                                  'Money formatting')

        submission, answer = _submit(
            page, live_server, enrolled_student, homework, question, '1.25')

        assert answer.text_answer == '1.25'
        assert answer.is_correct is True, (
            'the right amount was marked wrong because the stored key carries '
            'a dollar sign and the student did not type one')
        assert submission.score == 1

    @pytest.mark.django_db(transaction=True)
    def test_fewer_decimal_places_than_the_key_is_still_wrong(
        self, page: Page, live_server, enrolled_student, classroom,
        teacher_user, level, topic,
    ):
        """The guard: a two-place money key is not answered by one place."""
        question = _make_question(level, topic, '$1.50')
        homework = _make_homework(classroom, teacher_user, topic, question,
                                  'Money precision')

        submission, answer = _submit(
            page, live_server, enrolled_student, homework, question, '1.5')

        assert answer.is_correct is False, (
            'a key written to two decimal places teaches the money form, so '
            'one place must not earn the mark')
        assert submission.score == 0
