"""Playwright UI test — swapped factors are marked right (CPP-360).

"Factorise 16p^2 - 81q^2" stores its key as ``(4p - 9q)(4p + 9q)``. A student
who types the two factors the other way round has factorised it correctly, and
was marked wrong.

The unit tests pin ``match_value``; this drives the whole path a child actually
takes — type into the take page, submit, get graded — because that is where the
mark is won or lost, and it is the only place that proves the grader the student
meets is the one that was fixed.

Both answer formats are covered. On ``algebra`` the fault was worse than a
swapped pair: every bracketed answer was rejected up front, so not even the
stored key itself could be entered correctly.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from ..conftest import do_login

FACTORISED_KEY = '(4p - 9q)(4p + 9q)'
SWAPPED = '(4p + 9q)(4p - 9q)'


def _make_question(level, topic, answer_format):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic,
        question_text='Factorise: 16p^2 - 81q^2',
        question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
        answer_format=answer_format,
    )
    Answer.objects.create(question=q, answer_text=FACTORISED_KEY,
                          is_correct=True, order=0)
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
    """Take the homework, type *typed*, submit, and return the graded answer."""
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


class TestFactorOrderGrading:

    @pytest.mark.django_db(transaction=True)
    def test_swapped_factors_are_marked_correct_on_a_text_question(
        self, page: Page, live_server, enrolled_student, classroom,
        teacher_user, level, topic
    ):
        question = _make_question(level, topic, 'text')
        homework = _make_homework(classroom, teacher_user, topic, question,
                                  'Factorise (text)')

        submission, answer = _submit(
            page, live_server, enrolled_student, homework, question, SWAPPED)

        assert answer.text_answer == SWAPPED
        assert answer.is_correct is True, (
            'a correctly factorised answer was marked wrong because the two '
            'factors were written in the other order')
        assert submission.score == 1

    @pytest.mark.django_db(transaction=True)
    def test_swapped_factors_are_marked_correct_on_an_algebra_question(
        self, page: Page, live_server, enrolled_student, classroom,
        teacher_user, level, topic
    ):
        question = _make_question(level, topic, 'algebra')
        homework = _make_homework(classroom, teacher_user, topic, question,
                                  'Factorise (algebra)')

        submission, answer = _submit(
            page, live_server, enrolled_student, homework, question, SWAPPED)

        assert answer.is_correct is True, (
            'on answer_format=algebra every bracketed answer was rejected, so '
            'a factorise question could not be answered correctly at all')
        assert submission.score == 1

    @pytest.mark.django_db(transaction=True)
    def test_the_unfactorised_expression_is_still_wrong(
        self, page: Page, live_server, enrolled_student, classroom,
        teacher_user, level, topic
    ):
        """The guard: typing the question back is not an answer."""
        question = _make_question(level, topic, 'algebra')
        homework = _make_homework(classroom, teacher_user, topic, question,
                                  'Factorise (no work done)')

        submission, answer = _submit(
            page, live_server, enrolled_student, homework, question,
            '16p^2 - 81q^2')

        assert answer.is_correct is False, (
            'the expanded form is the question, not the answer — accepting it '
            'would mark a student correct for doing no factorising')
        assert submission.score == 0
