"""Progress art on the quiz pages.

A quiz is one sitting, so there is nothing to resume and nothing to store: the
picture is seeded on the quiz session id, which keeps it stable across a reload
of the same quiz and gives a fresh one to the next quiz.

The two quiz shapes drive the panel differently and both are covered here: the
topic quiz serves one question at a time and tells the panel as each answer is
graded, while the mixed quiz puts every question on one page and lets the panel
count the answered blocks.
"""

from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, School, SchoolStudent, Subject, Topic
from classroom import progress_art
from django.contrib.auth import get_user_model
from maths.models import Answer, Question

User = get_user_model()


class QuizProgressArtTestBase(TestCase):
    LEVEL_NUMBER = 4

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Art Quiz School')
        cls.student = User.objects.create_user(
            username='artquizstudent', password='pass1234', email='aq@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True)

        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.get_or_create(
            level_number=cls.LEVEL_NUMBER, defaults={'display_name': 'Year 4'})[0]
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Art Addition', slug='art-addition',
            is_active=True,
        )
        cls.topic.levels.add(cls.level)

        for i in range(14):
            q = Question.objects.create(
                question_text=f'Art quiz {i}+1?',
                question_type='multiple_choice',
                topic=cls.topic, level=cls.level,
            )
            Answer.objects.create(question=q, answer_text=str(i + 1),
                                  is_correct=True, order=1)
            Answer.objects.create(question=q, answer_text=str(i + 2),
                                  is_correct=False, order=2)

    def setUp(self):
        self.client = Client()
        self.client.login(username='artquizstudent', password='pass1234')


class TopicQuizPanelTest(QuizProgressArtTestBase):

    def _get(self):
        return self.client.get(reverse('topic_quiz', kwargs={
            'subject': 'mathematics',
            'level_number': self.LEVEL_NUMBER,
            'topic_id': self.topic.id,
        }))

    def test_panel_is_rendered_and_starts_empty(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        art = resp.context['progress_art']
        self.assertEqual(art['done'], 0)
        self.assertEqual(art['total'], resp.context['total_questions'])
        self.assertIn(art['key'], progress_art.PICTURES)
        self.assertContains(resp, 'data-progress-art')

    def test_the_page_tells_the_panel_as_each_answer_is_graded(self):
        """One question per page: without this call the drawing would only
        catch up when the next question loaded, landing after the feedback
        instead of with it."""
        content = self._get().content.decode()
        self.assertIn('window.ProgressArt.set(currentQ)', content)

    def test_the_year_level_bands_the_picture(self):
        key = self._get().context['progress_art']['key']
        self.assertIn(
            progress_art.get(key).band,
            (progress_art.BAND_JUNIOR, progress_art.BAND_ANY),
        )

    def test_a_new_quiz_gets_a_new_session_and_a_fresh_pick(self):
        first = self._get().context['progress_art']
        second = self._get().context['progress_art']
        # Both are real pictures of the right tier; the seed differs per quiz
        # session, so they are free to differ.
        for art in (first, second):
            self.assertIn(art['key'], progress_art.PICTURES)


class MixedQuizPanelTest(QuizProgressArtTestBase):

    def _get(self):
        return self.client.get(reverse('mixed_quiz', kwargs={
            'subject': 'mathematics',
            'level_number': self.LEVEL_NUMBER,
        }))

    def test_panel_is_rendered_in_group_counting_mode(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        art = resp.context['progress_art']
        self.assertEqual(art['done'], 0)
        self.assertEqual(art['total'], resp.context['total'])
        # Every question is on this page, so the panel counts blocks inside the
        # form rather than being told a number.
        self.assertEqual(art['scope'], '#mixed-form')

    def test_every_question_card_is_an_answer_group(self):
        resp = self._get()
        self.assertEqual(
            resp.content.decode().count('data-pa-group'),
            resp.context['total'],
        )


class BaseQuizTemplateTest(QuizProgressArtTestBase):

    def test_a_quiz_without_progress_art_renders_no_panel(self):
        """The partial is included in base_quiz.html for every quiz. It must be
        inert for the ones that have not opted in — a times-tables speed drill
        should look exactly as it did."""
        resp = self.client.get(reverse('multiplication_quiz', kwargs={
            'level_number': self.LEVEL_NUMBER,
            'table': 3,
        }))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'data-progress-art')
