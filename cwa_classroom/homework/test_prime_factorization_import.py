"""``prime_factorization`` through the homework PDF-upload pipeline.

"Write 60 as a product of its prime factors" needs one integer — strictly less
than the two ``long_division`` needs, and that has been extractable all along.
This one was not, and the gap was not the classifier: it was the SAVER. Neither
PDF importer carried ``target_number``, so had the type ever been emitted the
number would have been dropped, and ``maths.plugin`` requires a truthy
``target_number`` before its grading branch runs — the question would fall
through to text matching against no stored answer and mark every student wrong.

So this pins both halves: the extractor may emit the type and its number, and
the saver keeps it or skips the question outright.

Mirrors test_sketch_graph_import.py.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher, Subject, Topic, Level
from homework.models import HomeworkUploadSession
from homework.views import _save_homework_pdf_questions
from maths.factorization import prime_factorization_answer, prime_factors
from maths.models import Question as MQ
from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL

QUESTION_TEXT = 'Write 60 as a product of its prime factors.'


class FactorizationHelperTests(TestCase):
    """One definition of the factor list, shared by the importers and the key."""

    def test_factors_are_ascending_with_repeats(self):
        self.assertEqual(prime_factors(60), [2, 2, 3, 5])
        self.assertEqual(prime_factors(84), [2, 2, 3, 7])
        self.assertEqual(prime_factors(97), [97])       # already prime

    def test_nothing_to_factorise_is_empty_not_an_error(self):
        for n in (1, 0, -5, None, 'x', 2.5):
            with self.subTest(n=n):
                self.assertEqual(prime_factors(n), [])

    def test_the_written_answer_would_itself_mark_correct(self):
        # The graders split on x / × / * / , / whitespace, so the answer a
        # student is shown is one they could have typed.
        self.assertEqual(prime_factorization_answer(60), '2 x 2 x 3 x 5')
        self.assertEqual(prime_factorization_answer(1), '')


class ExtractionSchemaTests(TestCase):
    def test_prime_factorization_in_enum_with_its_number(self):
        props = (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']
                 ['questions']['items']['properties'])
        self.assertIn('prime_factorization', props['question_type']['enum'])
        self.assertIn('target_number', props)

    def test_the_prompt_carries_the_rule_and_what_is_not_this_type(self):
        from worksheets.services import WORKSHEET_SYSTEM_PROMPT
        self.assertIn('PRIME FACTORISATION', WORKSHEET_SYSTEM_PROMPT)
        self.assertIn('target_number', WORKSHEET_SYSTEM_PROMPT)
        # "list the factors of 24" is a different question and must not be swept in.
        self.assertIn('list the factors of 24', WORKSHEET_SYSTEM_PROMPT)


class _TeacherFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('pf_hw', 'pf_hw@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='PF School', slug='pf-school', admin=cls.user)
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.user, defaults={'role': 'teacher'})
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(
            name='Number', slug='number', subject=cls.subject)


class SavePrimeFactorizationTests(_TeacherFixture):

    def _save(self, questions):
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )
        return _save_homework_pdf_questions(
            questions, {'year_level': 7, 'subject': 'Mathematics', 'topic': 'Number'},
            self.user, self.school, session, save_images=False,
        )

    def _question(self, **overrides):
        q = {
            'question_text': QUESTION_TEXT,
            'question_type': 'prime_factorization',
            'target_number': 60,
            'validation_type': 'auto', 'difficulty': 2, 'points': 1,
            'has_image': False, 'answers': [],
        }
        q.update(overrides)
        return q

    def test_it_imports_with_its_number(self):
        saved = self._save([self._question()])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].question_type, MQ.PRIME_FACTORIZATION)
        self.assertEqual(saved[0].target_number, 60)

    def test_the_imported_question_grades_through_the_maths_plugin(self):
        """The regression this whole change is about: without target_number the
        grader marks every student wrong."""
        from maths.plugin import MathsPlugin
        q = self._save([self._question()])[0]
        plugin = MathsPlugin()
        for typed in ('2x2x3x5', '5 × 3 × 2 × 2', '2, 2, 3, 5'):
            with self.subTest(typed=typed):
                self.assertTrue(
                    plugin.grade_answer(q.pk, {f'answer_{q.id}': typed})['is_correct'])
        for typed in ('2x3x5', '4x15', '60'):
            with self.subTest(typed=typed):
                self.assertFalse(
                    plugin.grade_answer(q.pk, {f'answer_{q.id}': typed})['is_correct'])

    def test_a_question_with_no_usable_number_is_skipped(self):
        for bad in (None, 0, 1, 'sixty'):
            with self.subTest(bad=bad):
                saved = self._save([self._question(
                    question_text=f'Broken factorisation {bad}.', target_number=bad)])
                self.assertEqual(saved, [])

    def test_it_never_carries_a_figure_image(self):
        """The app draws the ladder, so a cropped factor tree would be a second,
        conflicting figure."""
        q = self._save([self._question(has_image=True, image_ref='p1_fig1.png')])[0]
        self.assertFalse(q.image)


class PreviewKeepsTheTypeTests(_TeacherFixture):

    def _session(self):
        return HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 7, 'subject': 'Mathematics', 'topic': 'Number',
                'questions': [{
                    'question_text': QUESTION_TEXT,
                    'question_type': 'prime_factorization',
                    'target_number': 60,
                    'validation_type': 'auto', 'difficulty': 2, 'points': 1,
                    'answers': [], 'include': True,
                }],
            },
            extracted_images={},
        )

    def test_the_dropdown_offers_the_type_and_the_number_is_editable(self):
        s = self._session()
        self.client.force_login(self.user)
        html = self.client.get(reverse('homework:pdf_preview', args=[s.pk])).content.decode()
        self.assertIn('value="prime_factorization" selected', html)
        self.assertIn('q_0_target_number', html)
