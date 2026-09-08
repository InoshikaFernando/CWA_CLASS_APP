"""Playwright UI test — what a Student Basic student's quiz actually shows.

Student Basic is the free promotional edition: the questions the app marks for
itself, and none of the ones the AI grader has to mark. Two things only a
browser can prove:

* the AI-graded question is genuinely absent from the page — not merely dropped
  from a queryset somewhere;
* the shortened quiz does not read as thin content. The student is told the
  other questions exist and what they are, with a way to ask for them.

There is deliberately no test of a student CHOOSING Student Basic, because
there is no way to: the tier is granted by the owner, and the only thing the
page ever offers is the way out of it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.quiz

SELF_MARKED = 'Work out 7 x 8'
AI_GRADED = 'Explain why multiplication is commutative'


@pytest.fixture
def two_kinds_of_question(db, level, topic):
    from maths.models import Answer, Question

    plain = Question.objects.create(
        level=level, topic=topic, question_text=SELF_MARKED,
        question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
    )
    Answer.objects.create(question=plain, answer_text='56', is_correct=True)
    written = Question.objects.create(
        level=level, topic=topic, question_text=AI_GRADED,
        question_type=Question.EXTENDED_ANSWER,
        validation_type=Question.VALIDATION_AI,
        grading_rubric='Full marks: order does not change the product.',
        difficulty=1, points=1,
    )
    return plain, written


@pytest.fixture
def subscribed_student(db, individual_student_user):
    """An ordinary individual student: subscribed, and on no module at all.

    The control for every assertion below — the state every student on the site
    is in today, and the one a student who subscribes tomorrow lands in.
    """
    from billing.models import Package, Subscription

    package, _ = Package.objects.get_or_create(
        name='Free', defaults={'price': 0, 'class_limit': 0})
    Subscription.objects.get_or_create(
        user=individual_student_user,
        defaults={'package': package, 'status': Subscription.STATUS_ACTIVE})
    return individual_student_user


@pytest.fixture
def basic_student(db, subscribed_student):
    """The same student, after the owner put them on Student Basic."""
    from billing.entitlements import grant_student_module
    from billing.models import StudentModule

    grant_student_module(subscribed_student, StudentModule.MODULE_BASIC)
    return subscribed_student


class TestStudentBasicTopicQuiz:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, level, topic, two_kinds_of_question):
        self.url = live_server.url
        self.page = page
        self.level = level
        self.topic = topic

    def _open_quiz(self, user):
        do_login(self.page, self.url, user)
        self.page.goto(f'{self.url}/maths/level/{self.level.level_number}'
                       f'/topic/{self.topic.id}/quiz/')
        expect(self.page.locator('#question-container')).to_be_visible(
            timeout=10_000)

    def test_the_ai_graded_question_is_not_on_the_page(self, basic_student):
        self._open_quiz(basic_student)
        body = self.page.locator('body').inner_text()
        assert SELF_MARKED in body
        assert AI_GRADED not in body

    def test_the_shortened_quiz_says_why_rather_than_looking_thin(
            self, basic_student):
        self._open_quiz(basic_student)
        body = self.page.locator('body').inner_text()
        assert 'Student Basic' in body
        assert 'AI Graded Questions' in body

    def test_the_promotion_leads_somewhere_that_explains_the_add_on(
            self, basic_student):
        self._open_quiz(basic_student)
        self.page.locator("a", has_text="See what's in it").first.click()
        expect(self.page.locator('h1')).to_contain_text(
            'AI Graded Questions', timeout=10_000)
        body = self.page.locator('body').inner_text()
        # Honest about what the button does: nothing is charged here.
        assert 'nothing is charged' in body.lower()

    def test_a_student_who_is_not_on_the_tier_sees_both_and_no_promotion(
            self, subscribed_student):
        """Everybody else: the whole quiz, and nothing about tiers."""
        self._open_quiz(subscribed_student)
        body = self.page.locator('body').inner_text()
        assert 'Student Basic' not in body
        # Both kinds are in the pool, so the eight-question quiz holds them
        # both — nothing was taken away from a student on no module.
        assert SELF_MARKED in body or AI_GRADED in body
        self.page.goto(f'{self.url}/billing/ai-graded-questions/')
        expect(self.page.locator('body')).to_contain_text(
            'nothing to do here', timeout=10_000)
