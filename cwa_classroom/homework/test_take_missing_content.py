"""The take page must not 500 when an item's backing content was deleted.

A ``HomeworkQuestion`` is identified by ``(subject_slug, content_id)``. For
non-legacy rows the ``content_id`` is a plain integer with no FK protection, so
the underlying content (a maths ``Question``, a coding ``CodingExercise``, ...)
can be deleted after assignment — e.g. a teacher regenerates a topic. When that
happens the student's take page must degrade gracefully (skip the dead item)
rather than raise ``DoesNotExist`` and serve an HTTP 500.
"""
from datetime import timedelta

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maths.models import Answer, Question
from .models import Homework, HomeworkQuestion
from .tests import HomeworkTestBase


class TakeMissingContentTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')

    def _homework(self, title):
        return Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher,
            title=title, homework_type='topic', num_questions=1,
            due_date=timezone.now() + timedelta(days=7),
        )

    def _take(self, hw):
        return self.client.get(
            reverse('homework:student_take', kwargs={'homework_id': hw.id}))

    def test_deleted_content_does_not_500(self):
        hw = self._homework('Dangling item')
        q = Question.objects.create(
            level=self.level, question_text='temp',
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1)
        HomeworkQuestion.objects.create(
            homework=hw, subject_slug='mathematics', content_id=q.id, order=0)
        Question.objects.filter(id=q.id).delete()

        resp = self._take(hw)
        self.assertEqual(resp.status_code, 200)

    def test_good_items_still_render_when_one_is_missing(self):
        hw = self._homework('Mixed valid + dangling')
        good = Question.objects.create(
            level=self.level, question_text='Two plus two?',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)
        Answer.objects.create(question=good, answer_text='4', is_correct=True, order=0)
        Answer.objects.create(question=good, answer_text='5', is_correct=False, order=1)
        dead = Question.objects.create(
            level=self.level, question_text='temp',
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1)
        HomeworkQuestion.objects.create(
            homework=hw, subject_slug='mathematics', content_id=good.id, order=0)
        HomeworkQuestion.objects.create(
            homework=hw, subject_slug='mathematics', content_id=dead.id, order=1)
        Question.objects.filter(id=dead.id).delete()

        resp = self._take(hw)
        self.assertEqual(resp.status_code, 200)
        # The surviving question is still shown, and its answer input exists.
        self.assertContains(resp, 'Two plus two?')
        self.assertContains(resp, f'name="answer_{good.id}"')
        # Only the good item renders — one item was dropped.
        self.assertEqual(len(resp.context['items']), 1)
