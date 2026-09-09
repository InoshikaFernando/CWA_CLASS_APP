"""Playwright UI test — a retired question stops reaching children (CPP-410).

The unit tests pin the helper. This drives the real take page, because that is
where a withdrawn question would actually reach a child, and a filter that is
right in a queryset but wrong in the view would pass those tests and fail here.

A question is normally retired because it is BROKEN — no diagram, no table — so
"stops being served" has to mean immediately, including inside homework that
already contains it, not at the next assignment.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def two_questions(db, level, topic):
    from maths.models import Answer, Question

    made = []
    for text in ('KEEPTHISONE What is 2 + 2?', 'WITHDRAWTHISONE Find the value of x.'):
        q = Question.objects.create(
            level=level, topic=topic, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)
        Answer.objects.create(question=q, answer_text='4', is_correct=True, order=0)
        Answer.objects.create(question=q, answer_text='5', is_correct=False, order=1)
        made.append(q)
    return made


@pytest.fixture
def homework_with_both(db, classroom, teacher_user, topic, two_questions):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user, title='Retirement',
        homework_type='topic', num_questions=2,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3)
    hw.topics.add(topic)
    for order, q in enumerate(two_questions):
        HomeworkQuestion.objects.create(homework=hw, question=q, order=order)
    return hw


class TestRetiredQuestionOnTakePage:

    @pytest.mark.django_db(transaction=True)
    def test_a_withdrawn_question_is_not_served(
        self, page: Page, live_server, enrolled_student,
        homework_with_both, two_questions
    ):
        keep, withdraw = two_questions
        withdraw.retire('No diagram; unanswerable (CPP-406).')

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/homework/{homework_with_both.pk}/take/')
        page.wait_for_load_state('networkidle')

        body = page.locator('body')
        expect(body).to_contain_text('KEEPTHISONE')
        expect(body).not_to_contain_text('WITHDRAWTHISONE')

    @pytest.mark.django_db(transaction=True)
    def test_both_are_served_while_neither_is_retired(
        self, page: Page, live_server, enrolled_student, homework_with_both
    ):
        """The control: without retirement the page shows both."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/homework/{homework_with_both.pk}/take/')
        page.wait_for_load_state('networkidle')

        body = page.locator('body')
        expect(body).to_contain_text('KEEPTHISONE')
        expect(body).to_contain_text('WITHDRAWTHISONE')

    @pytest.mark.django_db(transaction=True)
    def test_the_homework_row_survives_retirement(
        self, page: Page, live_server, enrolled_student,
        homework_with_both, two_questions
    ):
        """What the homework contained is a fact about the past."""
        two_questions[1].retire('unanswerable')

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/homework/{homework_with_both.pk}/take/')
        page.wait_for_load_state('networkidle')

        assert homework_with_both.homework_questions.count() == 2
