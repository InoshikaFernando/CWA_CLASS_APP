"""``table_of_values`` through the homework PDF-upload pipeline.

The bug this pins: a "complete the chart" question came back from the extractor
as ``table_of_values`` with a ``table_spec`` — and the teacher's review page
showed it as **Multiple Choice with no answers to tick**. Two independent
silent rewrites did that:

  1. The review page's "Question Type" dropdown was a hand-kept list that had
     never gained ``table_of_values``. A ``<select>`` with no option matching
     its value renders showing its FIRST option ("Multiple Choice"), and the
     preview POST then saved that — losing the type and stranding the spec.
  2. The saver's ``type_map`` was a second hand-kept list, also missing
     ``table_of_values``, so even a preserved type fell through to
     ``short_answer`` — one text box for a whole chart — and the table_spec
     validation right below it was unreachable code.

Mirrors test_number_line_import.py.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher, Subject, Topic, Level
from homework.models import HomeworkUploadSession
from homework.views import _save_homework_pdf_questions
from maths.models import Question as MQ
from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL


_TABLE_SPEC = {
    'headers': ['Money value', 'Decimal form'],
    'rows': [
        [{'given': '56c'}, {'answer': '0.56'}],
        [{'given': '20c'}, {'answer': '0.20'}],
    ],
    'tolerance': 0,
}


class ExtractionSchemaTests(TestCase):
    def test_table_of_values_in_enum_with_its_spec(self):
        props = (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']
                 ['questions']['items']['properties'])
        self.assertIn('table_of_values', props['question_type']['enum'])
        self.assertIn('table_spec', props)


class _TeacherFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('tv_hw', 'tv_hw@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='TV School', slug='tv-school', admin=cls.user)
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.user, defaults={'role': 'teacher'})
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(name='Decimals', slug='decimals', subject=cls.subject)


class SaveTableOfValuesTests(_TeacherFixture):

    def _save(self, questions):
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )
        return _save_homework_pdf_questions(
            questions, {'year_level': 4, 'subject': 'Mathematics', 'topic': 'Decimals'},
            self.user, self.school, session, save_images=False,
        )

    def _question(self, **overrides):
        q = {
            'question_text': 'Complete the tenths and hundredths digits for 56c, 20c.',
            'question_type': 'table_of_values',
            'table_spec': _TABLE_SPEC,
            'validation_type': 'auto', 'difficulty': 2, 'points': 1,
            'has_image': False, 'answers': [],
        }
        q.update(overrides)
        return q

    def test_a_table_imports_as_a_table_not_a_short_answer(self):
        saved = self._save([self._question()])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.TABLE_OF_VALUES)
        self.assertEqual(q.table_spec['headers'], ['Money value', 'Decimal form'])
        self.assertEqual(q.answers.count(), 0)

    def test_the_imported_table_grades_through_the_maths_plugin(self):
        from maths.plugin import MathsPlugin
        q = self._save([self._question()])[0]
        plugin = MathsPlugin()
        good = plugin.grade_answer(q.pk, {f'answer_{q.id}': '{"cells": {"0,1": "0.56", "1,1": "0.20"}}'})
        bad = plugin.grade_answer(q.pk, {f'answer_{q.id}': '{"cells": {"0,1": "5.6", "1,1": "0.20"}}'})
        self.assertTrue(good['is_correct'])
        self.assertFalse(bad['is_correct'])

    def test_a_malformed_table_spec_is_skipped_not_imported_broken(self):
        saved = self._save([self._question(
            question_text='Broken table.',
            table_spec={'headers': ['x', 'y'], 'rows': [[{'given': '1'}, {'given': '2'}]]},
        )])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='Broken table.').exists())

    def test_a_choice_question_with_no_options_is_skipped(self):
        # What the old dropdown produced: type rewritten to multiple_choice,
        # nothing to tick. Unanswerable — never import it.
        saved = self._save([self._question(
            question_text='Complete the chart.', question_type='multiple_choice',
            table_spec=None, answers=[],
        )])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='Complete the chart.').exists())

    def test_an_ordinary_multiple_choice_still_imports(self):
        saved = self._save([self._question(
            question_text='Which is larger?', question_type='multiple_choice',
            table_spec=None,
            answers=[{'text': '0.56', 'is_correct': True}, {'text': '0.20', 'is_correct': False}],
        )])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].question_type, MQ.MULTIPLE_CHOICE)
        self.assertEqual(saved[0].answers.count(), 2)


class PreviewKeepsTheTypeTests(_TeacherFixture):
    """The review page must offer — and post back — the type it was given."""

    def _session(self, q_type='table_of_values'):
        return HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 4, 'subject': 'Mathematics', 'topic': 'Decimals',
                'questions': [{
                    'question_text': 'Complete the chart.',
                    'question_type': q_type,
                    'table_spec': _TABLE_SPEC,
                    'validation_type': 'auto', 'difficulty': 2, 'points': 1,
                    'answers': [], 'include': True,
                }],
            },
            extracted_images={},
        )

    def test_the_dropdown_offers_the_extracted_type_selected(self):
        s = self._session()
        self.client.force_login(self.user)
        html = self.client.get(reverse('homework:pdf_preview', args=[s.pk])).content.decode()
        self.assertIn('value="table_of_values" selected', html)
        # ...and the spec is editable rather than invisible.
        self.assertIn('q_0_table_spec', html)

    def test_a_type_the_list_has_never_heard_of_is_still_offered(self):
        # An older session, another extractor, a hand-authored import: whatever
        # the type is, the dropdown must contain it or the POST rewrites it.
        s = self._session(q_type='shape_select')
        self.client.force_login(self.user)
        html = self.client.get(reverse('homework:pdf_preview', args=[s.pk])).content.decode()
        self.assertIn('value="shape_select" selected', html)

    def test_posting_the_preview_keeps_the_table(self):
        s = self._session()
        self.client.force_login(self.user)
        self.client.post(reverse('homework:pdf_preview', args=[s.pk]), {
            'homework_title': 'Money', 'year_level': '4', 'topic': 'Decimals',
            'subject': 'Mathematics', 'strand': '',
            'q_0_include': 'on', 'q_0_text': 'Complete the chart.',
            'q_0_type': 'table_of_values', 'q_0_validation_type': 'auto',
            'q_0_difficulty': '2', 'q_0_points': '1', 'q_0_explanation': '',
            'q_0_year_level': '4', 'q_0_subject': 'Mathematics',
            'q_0_topic': 'Decimals', 'q_0_strand': '',
        })
        s.refresh_from_db()
        q = s.extracted_data['questions'][0]
        self.assertEqual(q['question_type'], 'table_of_values')
        self.assertEqual(q['table_spec'], _TABLE_SPEC)
