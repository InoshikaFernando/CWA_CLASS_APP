"""The homework 'take' partial renders an image question with its picture.

Covers the questions restored by ``recover_homework_pdf_images`` — image-based
items (e.g. "What is the name of this shape?") that each carry a distinct image.
Confirms the figure is shown on the quiz/take page, not dropped.
"""
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level
from maths.models import Question


class ImageTakeRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=996, defaults={'display_name': 'img render fixture'},
        )

    def _render(self, q):
        return render_to_string(
            'homework/partials/_maths_take_item.html', {'ctx': {'question': q}},
        )

    def test_image_question_shows_its_picture_and_text(self):
        q = Question.objects.create(
            level=self.level,
            question_text='What is the name of this shape?',
            question_type=Question.SHORT_ANSWER,
            image='questions/year1/2d-shapes/upload_8a7b1e24_3.png',
            difficulty=1, points=1,
        )
        html = self._render(q)
        self.assertIn('<img', html)
        # The exact restored image path is what gets served (from Spaces in prod).
        self.assertIn('questions/year1/2d-shapes/upload_8a7b1e24_3.png', html)
        self.assertIn('What is the name of this shape?', html)
        # And the student still gets an answer box.
        self.assertIn('name="answer_', html)

    def test_two_restored_questions_show_distinct_images(self):
        # The whole point of the fix: same stem, different images → different
        # pictures rendered (not one shared/collapsed image).
        q1 = Question.objects.create(
            level=self.level, question_text='What is the name of this shape?',
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
            image='questions/year1/2d-shapes/shape_a.png')
        q2 = Question.objects.create(
            level=self.level, question_text='What is the name of this shape?',
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
            image='questions/year1/2d-shapes/shape_b.png')
        self.assertIn('shape_a.png', self._render(q1))
        self.assertIn('shape_b.png', self._render(q2))
