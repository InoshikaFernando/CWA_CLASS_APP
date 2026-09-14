"""Bulk question upload: multi-group files and self-graded question types.

``MathsQuestionParser`` is the Upload-Questions door (JSON / ZIP). Two things it
did not do, both of which this covers:

  * one file, several years — Year 4 and Year 5 banks in a single upload, via
    a "groups" list, without breaking the original one-topic-per-file shape;
  * column_operation (and every other type whose answer the app computes from
    the question) — its operands/operator used to be dropped on the way in and
    its empty ``answers`` list rejected, so the type could not be uploaded at
    all, and a question that did get through carried nothing to render.
"""
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.models import CustomUser
from classroom.models import Level, Subject, Topic
from classroom.upload_services import MathsQuestionParser
from maths.models import Question


def _file(payload):
    return SimpleUploadedFile(
        'questions.json', json.dumps(payload).encode(),
        content_type='application/json')


def _column(a, b):
    return {
        'question_text': f'Work out {a} × {b} using column multiplication.',
        'question_type': 'column_operation',
        'operands': [a, b], 'operator': '*',
        'difficulty': 1, 'points': 1,
        'explanation': f'{a} × {b} = {a * b}',
        'answers': [],
    }


class ColumnOperationUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'col_upload_super', 'col_upload@test.internal', 'pw1!')
        for n in (4, 5):
            Level.objects.get_or_create(
                level_number=n, defaults={'display_name': f'Year {n}'})
        Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})

    def _run(self, payload):
        return MathsQuestionParser().process(
            _file(payload), self.user, {},
            school_id=None, dept_id=None, selected_classroom_id=None,
        )

    # ── self-graded types ──────────────────────────────────────────────────
    def test_column_operation_uploads_with_no_answer_rows(self):
        result = self._run({
            'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
            'questions': [_column(347, 8)],
        })
        self.assertEqual(result['failed'], 0, result['errors'])
        self.assertEqual(result['inserted'], 1)

    def test_operands_and_operator_survive_the_upload(self):
        self._run({
            'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
            'questions': [_column(347, 8)],
        })
        q = Question.objects.get(question_type='column_operation')
        self.assertEqual(q.operands, [347, 8])
        self.assertEqual(q.operator, '*')
        # The widget can only draw the grid once both are set.
        self.assertEqual(q.column_result, 2776)
        self.assertIsNotNone(q.column_arithmetic)

    def test_column_operation_without_operands_is_reported_not_saved(self):
        broken = _column(347, 8)
        del broken['operands']
        result = self._run({
            'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
            'questions': [broken],
        })
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertIn('column_result', ' '.join(result['errors']))
        self.assertFalse(Question.objects.filter(question_type='column_operation').exists())

    def test_a_normal_type_still_needs_answers(self):
        result = self._run({
            'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
            'questions': [{
                'question_text': 'What is 2 + 2?',
                'question_type': 'multiple_choice',
                'difficulty': 1, 'points': 1, 'answers': [],
            }],
        })
        self.assertEqual(result['failed'], 1)
        self.assertIn('no answers provided', ' '.join(result['errors']))

    # ── multi-group files ──────────────────────────────────────────────────
    def test_one_file_uploads_year_4_and_year_5(self):
        result = self._run({'groups': [
            {'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
             'questions': [_column(347, 8), _column(2681, 7)]},
            {'strand': 'Number', 'topic': 'Multiplication', 'year_level': 5,
             'questions': [_column(347, 68)]},
        ]})
        self.assertEqual(result['failed'], 0, result['errors'])
        self.assertEqual(result['inserted'], 3)
        self.assertEqual(
            Question.objects.filter(level__level_number=4).count(), 2)
        self.assertEqual(
            Question.objects.filter(level__level_number=5).count(), 1)
        # Both land under the same Number > Multiplication sub-topic.
        topic = Topic.objects.get(name='Multiplication')
        self.assertEqual(topic.parent.name, 'Number')
        self.assertEqual(
            sorted(topic.levels.values_list('level_number', flat=True)), [4, 5])

    def test_groups_inherit_top_level_strand_and_topic(self):
        result = self._run({
            'strand': 'Number', 'topic': 'Multiplication',
            'groups': [
                {'year_level': 4, 'questions': [_column(347, 8)]},
                {'year_level': 5, 'questions': [_column(347, 68)]},
            ],
        })
        self.assertEqual(result['failed'], 0, result['errors'])
        self.assertEqual(result['inserted'], 2)
        self.assertEqual(Topic.objects.filter(name='Multiplication').count(), 1)

    def test_top_level_questions_are_not_dropped_when_groups_present(self):
        result = self._run({
            'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
            'questions': [_column(347, 8)],
            'groups': [
                {'strand': 'Number', 'topic': 'Multiplication',
                 'year_level': 5, 'questions': [_column(347, 68)]},
            ],
        })
        self.assertEqual(result['failed'], 0, result['errors'])
        self.assertEqual(result['inserted'], 2)

    def test_one_bad_group_does_not_sink_the_others(self):
        result = self._run({'groups': [
            {'strand': 'Number', 'year_level': 4,
             'questions': [_column(347, 8)]},                     # no topic
            {'strand': 'Number', 'topic': 'Multiplication',
             'year_level': 5, 'questions': [_column(347, 68)]},
        ]})
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 1)
        self.assertIn('Group 1 Missing "topic"', ' '.join(result['errors']))

    def test_detail_lists_every_group(self):
        result = self._run({'groups': [
            {'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
             'questions': [_column(347, 8)]},
            {'strand': 'Number', 'topic': 'Multiplication', 'year_level': 5,
             'questions': [_column(347, 68)]},
        ]})
        self.assertEqual(result['detail']['groups'], [
            {'topic': 'Multiplication', 'year_level': 4, 'questions': 1},
            {'topic': 'Multiplication', 'year_level': 5, 'questions': 1},
        ])

    def test_single_group_file_keeps_its_original_detail_shape(self):
        result = self._run({
            'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
            'questions': [_column(347, 8)],
        })
        self.assertEqual(result['detail'],
                         {'topic': 'Multiplication', 'year_level': 4})

    def test_the_shipped_bank_uploads(self):
        """The generated Year 4 + Year 5 bank goes in as one file."""
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            'maths', 'seed_data', 'column_multiplication_year4_year5.json')
        with open(path, encoding='utf-8') as f:
            bank = json.load(f)
        result = self._run(bank)
        self.assertEqual(result['failed'], 0, result['errors'][:5])
        self.assertEqual(result['inserted'], 200)
        self.assertEqual(Question.objects.filter(level__level_number=4).count(), 100)
        self.assertEqual(Question.objects.filter(level__level_number=5).count(), 100)
        # Every one renders.
        self.assertTrue(all(q.column_arithmetic is not None
                            for q in Question.objects.all()))


class MultiGroupResultsPageTests(TestCase):
    """The Upload Results header names every group, instead of "Year  › "."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'col_page_super', 'col_page@test.internal', 'pw1!')
        for n in (4, 5):
            Level.objects.get_or_create(
                level_number=n, defaults={'display_name': f'Year {n}'})
        Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})

    def test_results_header_lists_each_group(self):
        from django.template.loader import render_to_string

        result = MathsQuestionParser().process(
            _file({'groups': [
                {'strand': 'Number', 'topic': 'Multiplication', 'year_level': 4,
                 'questions': [_column(347, 8)]},
                {'strand': 'Number', 'topic': 'Multiplication', 'year_level': 5,
                 'questions': [_column(347, 68)]},
            ]}),
            self.user, {}, school_id=None, dept_id=None, selected_classroom_id=None)

        html = render_to_string('teacher/upload_questions.html', {
            'upload_results_list': [dict(result, filename='bank.json')],
            'user': self.user,
        })
        self.assertIn('Year 4 › Multiplication (1)', html)
        self.assertIn('Year 5 › Multiplication (1)', html)


class UploadQuestionsViewTests(TestCase):
    """End-to-end through the real Upload Questions view, not just the parser.

    The parser tests above call process() directly; this posts the shipped file
    to the URL a teacher actually uses, so nothing in the view layer (scope
    resolution, the multi-file loop, the results render) can quietly reject it.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'col_view_super', 'col_view@test.internal', 'pw1!')
        for n in (4, 5):
            Level.objects.get_or_create(
                level_number=n, defaults={'display_name': f'Year {n}'})
        Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})

    def test_posting_the_shipped_bank_uploads_both_years(self):
        import os

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            'maths', 'seed_data', 'column_multiplication_year4_year5.json')
        with open(path, 'rb') as fh:
            payload = fh.read()

        self.client.force_login(self.user)
        response = self.client.post('/upload-questions/', {
            'subject': 'mathematics',
            'upload_file': SimpleUploadedFile(
                'column_multiplication_year4_year5.json', payload,
                content_type='application/json'),
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        results = response.context['upload_results_list']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['failed'], 0, results[0]['errors'][:5])
        self.assertEqual(results[0]['inserted'], 200)

        # The page reports both years rather than a blank "Year  › ".
        self.assertContains(response, 'Year 4 › Multiplication (100)')
        self.assertContains(response, 'Year 5 › Multiplication (100)')

        self.assertEqual(Question.objects.filter(level__level_number=4).count(), 100)
        self.assertEqual(Question.objects.filter(level__level_number=5).count(), 100)
        self.assertTrue(all(q.column_arithmetic is not None
                            for q in Question.objects.all()))

    def test_downloadable_template_round_trips_through_the_uploader(self):
        """The sample template teachers download must itself be uploadable."""
        import json as json_mod

        self.client.force_login(self.user)
        tpl = self.client.get('/upload-questions/template/?subject=mathematics')
        self.assertEqual(tpl.status_code, 200)
        template = json_mod.loads(b''.join(tpl.streaming_content)
                                  if tpl.streaming else tpl.content)
        self.assertIn('groups', template)

        response = self.client.post('/upload-questions/', {
            'subject': 'mathematics',
            'upload_file': SimpleUploadedFile(
                'template_mathematics.json',
                json_mod.dumps(template).encode(),
                content_type='application/json'),
        }, follow=True)
        result = response.context['upload_results_list'][0]
        self.assertEqual(result['failed'], 0, result['errors'])
        # 1 fractions MCQ at the top level + 1 Year 4 and 1 Year 5 column sum.
        self.assertEqual(result['inserted'], 3)
