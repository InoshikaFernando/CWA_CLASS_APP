"""Editing the explanation — the field the repair could not reach.

The explanation is what a child reads AFTER they answer: in the quiz review, on
the worksheet feedback. So a question whose answer key was wrong almost always
carries an explanation that argues for the wrong answer, and correcting the key
without it leaves the reasoning still telling the child the old answer was
right — a half-repair that reads, to the only person who sees it, like no
repair at all. The editor had no input for it.

Two things are defended here: the field saves, and saving it never moves a
mark. No grader reads an explanation, so an edit to it must not re-run the
grader over answers already recorded.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question, StudentAnswer

User = get_user_model()


class ExplanationEditTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Role

        cls.admin = User.objects.create_superuser(
            username='explainadmin', email='explain@test.com',
            password='pass1234')
        role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'})
        cls.admin.roles.add(role)

        cls.subject = Subject.objects.create(name='Maths Explain',
                                             slug='maths-explain')
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(name='Area', slug='area',
                                         subject=cls.subject)

    def setUp(self):
        self.client = Client()
        self.client.login(username='explainadmin', password='pass1234')
        self.question = Question.objects.create(
            level=self.level, topic=self.topic,
            question_text='Figure A is made of four identical rectangles. '
                          'Find the area of Figure A.',
            question_type=Question.MULTIPLE_CHOICE,
            explanation='Each rectangle is 3 cm by 9 cm, so add the sides.')
        self.right = Answer.objects.create(
            question=self.question, answer_text='108 cm²',
            is_correct=True, order=0)
        self.wrong = Answer.objects.create(
            question=self.question, answer_text='72 cm',
            is_correct=False, order=1)
        self.url = reverse('admin_global_question_edit',
                           args=[self.question.id])

    def form(self, **overrides):
        """The modal's fields, as the browser posts them."""
        data = {
            'question_type': self.question.question_type,
            'question_text': self.question.question_text,
            'explanation': self.question.explanation,
            'answer_id': [self.right.id, self.wrong.id],
            f'answer_text_{self.right.id}': self.right.answer_text,
            f'is_correct_{self.right.id}': 'on',
            f'answer_text_{self.wrong.id}': self.wrong.answer_text,
        }
        data.update(overrides)
        return data

    def test_the_stored_explanation_is_shown_to_edit(self):
        html = self.client.get(self.url).content.decode()

        self.assertIn('name="explanation"', html)
        self.assertIn('Each rectangle is 3 cm by 9 cm', html)

    def test_saving_writes_the_new_explanation(self):
        response = self.client.post(self.url, self.form(
            explanation='Four rectangles of 3 cm × 9 cm: 4 × 27 = 108 cm².'))

        self.assertEqual(response.status_code, 200)
        self.question.refresh_from_db()
        self.assertEqual(
            self.question.explanation,
            'Four rectangles of 3 cm × 9 cm: 4 × 27 = 108 cm².')

    def test_an_explanation_can_be_cleared(self):
        self.client.post(self.url, self.form(explanation='   '))

        self.question.refresh_from_db()
        self.assertEqual(self.question.explanation, '')

    def test_a_post_without_the_field_leaves_the_explanation_alone(self):
        """The listing's preview button posts no form.

        A blanket read of the field would wipe the explanation of every
        question previewed from there — the silent data loss this guard exists
        to prevent.
        """
        data = self.form()
        data.pop('explanation')

        self.client.post(self.url, data)

        self.question.refresh_from_db()
        self.assertEqual(self.question.explanation,
                         'Each rectangle is 3 cm by 9 cm, so add the sides.')

    def test_changing_only_the_explanation_re_marks_nothing(self):
        """No grader reads it, so no mark may move on it.

        The re-mark is guarded by a grading fingerprint; the explanation is not
        part of it. A child marked wrong stays marked wrong until the thing
        that marked them — the key — actually changes.
        """
        student = User.objects.create_user(
            username='explainkid', email='ek@test.com', password='pass1234')
        answer = StudentAnswer.objects.create(
            student=student, question=self.question,
            selected_answer=self.wrong, is_correct=False)

        self.client.post(self.url, self.form(
            explanation='A completely rewritten explanation.',
            regrade_answers='on'))

        answer.refresh_from_db()
        self.assertFalse(answer.is_correct)
        self.question.refresh_from_db()
        self.assertEqual(self.question.explanation,
                         'A completely rewritten explanation.')

    def test_the_explanation_saves_alongside_a_key_correction(self):
        """The two halves of the same repair, in one save.

        Fixing the key and leaving the explanation arguing for the old answer
        is the failure this field exists to close, so they must be writable
        together rather than in two passes.
        """
        student = User.objects.create_user(
            username='explainkid2', email='ek2@test.com', password='pass1234')
        answer = StudentAnswer.objects.create(
            student=student, question=self.question,
            selected_answer=self.wrong, is_correct=False)

        data = self.form(explanation='72 cm is the perimeter, not the area.',
                         regrade_answers='on')
        data.pop(f'is_correct_{self.right.id}')       # untick the old key
        data[f'is_correct_{self.wrong.id}'] = 'on'    # tick what they picked

        self.client.post(self.url, data)

        answer.refresh_from_db()
        self.question.refresh_from_db()
        self.assertTrue(answer.is_correct)            # the mark came back
        self.assertEqual(self.question.explanation,
                         '72 cm is the perimeter, not the area.')
