"""Playwright UI test — a hyphen typed against an en-dash key is marked right.

CPP-407. The unit tests pin ``match_value``; this drives the whole path a
child actually takes — type into the take page, submit, get graded — because
that is where the mark is won or lost, and it is the only place that proves
the grader the student meets is the one that was fixed.

The stored key uses U+2013 (EN DASH), exactly as CPP-406's question does.
Before the fix this attempt was recorded ``is_correct=False``.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from ..conftest import do_login

EN_DASH_KEY = '–3'          # U+2013, as stored by the PDF importer


@pytest.fixture
def en_dash_question(db, level, topic):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic,
        question_text='x + 7 = 4\n\nThe value of x is:',
        question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
    )
    Answer.objects.create(question=q, answer_text=EN_DASH_KEY,
                          is_correct=True, order=0)
    return q


@pytest.fixture
def en_dash_homework(db, classroom, teacher_user, topic, en_dash_question):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title='En dash grading', homework_type='topic', num_questions=1,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=en_dash_question,
                                    order=0)
    return hw


class TestEnDashAnswerGrading:

    @pytest.mark.django_db(transaction=True)
    def test_a_typed_hyphen_matches_an_en_dash_key(
        self, page: Page, live_server, enrolled_student,
        en_dash_homework, en_dash_question
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/homework/{en_dash_homework.pk}/take/')
        page.wait_for_load_state('networkidle')

        # An ordinary hyphen — what a keyboard produces.
        page.locator(f"input[name='answer_{en_dash_question.pk}']").fill('-3')
        with page.expect_navigation():
            page.get_by_role(
                'button', name=re.compile(r'Submit Homework', re.I)).click()
        page.wait_for_load_state('networkidle')

        submission = HomeworkSubmission.objects.filter(
            homework=en_dash_homework, student=enrolled_student).first()
        assert submission is not None
        answer = HomeworkStudentAnswer.objects.get(
            submission=submission, question=en_dash_question)

        assert answer.text_answer == '-3'
        assert answer.is_correct is True, (
            'a correct answer typed with a keyboard hyphen was marked wrong '
            'against a key stored with an en dash')
        assert submission.score == 1
