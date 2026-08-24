"""CPP-389 — the preview and the import must read a review form the same way.

The preview reads one question card out of the POST with
``worksheets.question_preview.draft_from_post``; confirming the upload reads the
whole form with ``HomeworkPDFPreviewView``'s own ``_apply_question_fields``. Two
readers of one form is exactly how a preview starts quietly lying — it shows the
teacher a question that is not the one that gets imported.

So this posts a real review form through the real import handler, then reads the
same POST with the preview's parser and demands they agree on every field the
preview claims to know. If someone changes one reader and not the other, this
fails rather than the teacher finding out from a student.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, SchoolTeacher, Subject, Topic
from worksheets.question_preview import draft_from_post

from .models import HomeworkUploadSession

# One card per shape of question the review form can carry: a typed answer, a
# pick-an-option, a tolerance-graded measurement, computed column arithmetic and
# a structured table. Each is (stored draft, posted fields for card 0).
CASES = {
    'short_answer': (
        {'question_text': 'old text', 'question_type': 'short_answer'},
        {
            'q_0_text': '20c is ______ of a dollar.',
            'q_0_type': 'short_answer',
            'q_0_validation_type': 'auto',
            'q_0_difficulty': '2',
            'q_0_points': '3',
            'q_0_explanation': 'Twenty out of a hundred.',
            'q_0_answer_0_text': 'twenty hundredths',
            'q_0_answer_0_correct': 'on',
            'q_0_answer_1_text': '0.20',
        },
    ),
    'multiple_choice': (
        {'question_text': 'old text', 'question_type': 'multiple_choice'},
        {
            'q_0_text': 'Which is largest?',
            'q_0_type': 'multiple_choice',
            'q_0_validation_type': 'auto',
            'q_0_difficulty': '1',
            'q_0_points': '1',
            'q_0_answer_0_text': '0.5',
            'q_0_answer_1_text': '0.75',
            'q_0_answer_1_correct': 'on',
        },
    ),
    'measure': (
        {'question_text': 'old text', 'question_type': 'measure'},
        {
            'q_0_text': 'Measure angle a.',
            'q_0_type': 'measure',
            'q_0_validation_type': 'auto',
            'q_0_difficulty': '1',
            'q_0_points': '1',
            'q_0_measure_numeric_answer': '135',
            'q_0_measure_answer_tolerance': '2',
            'q_0_measure_answer_unit': '°',
        },
    ),
    'column_operation': (
        {'question_text': 'old text', 'question_type': 'column_operation'},
        {
            'q_0_text': 'Add these numbers.',
            'q_0_type': 'column_operation',
            'q_0_validation_type': 'auto',
            'q_0_difficulty': '1',
            'q_0_points': '1',
            'q_0_operands': '23, 25',
            'q_0_operator': '+',
        },
    ),
    'table_of_values': (
        {'question_text': 'old text', 'question_type': 'table_of_values'},
        {
            'q_0_text': 'Complete the table.',
            'q_0_type': 'table_of_values',
            'q_0_validation_type': 'auto',
            'q_0_difficulty': '1',
            'q_0_points': '1',
            'q_0_table_spec': (
                '{"headers": ["Money value", "Decimal form"], '
                '"rows": [[{"given": "56c"}, {"answer": "0.56"}]], "tolerance": 0}'
            ),
        },
    ),
}

# Set by the import handler but not claimed by the preview parser (they describe
# where a question is filed, not how it looks or marks).
NOT_CLAIMED = {'include', 'subject', 'strand', 'topic'}


class PreviewMatchesImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'})
        cls.teacher = CustomUser.objects.create_user('t1', 't1@x.com', 'pw')
        cls.teacher.roles.add(role)
        admin = CustomUser.objects.create_user('a', 'a@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='s', admin=admin)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')
        Level.objects.create(level_number=5, display_name='Year 5')
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        Topic.objects.create(subject=subject, name='Decimals', slug='decimals')

    def _session(self, stored):
        return HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='t.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 5, 'topic': 'Decimals', 'subject': 'Mathematics',
                'strand': '', 'questions': [dict(stored)],
            },
            extracted_images={},
        )

    def test_preview_reads_every_card_the_way_the_import_does(self):
        for name, (stored, posted) in CASES.items():
            with self.subTest(question_type=name):
                session = self._session(stored)
                self.client.force_login(self.teacher)

                form = {
                    'homework_title': 'Term 3 sheet',
                    'year_level': '5',
                    'topic': 'Decimals',
                    'subject': 'Mathematics',
                    'q_0_include': 'on',
                    **posted,
                }
                response = self.client.post(
                    reverse('homework:pdf_preview', args=[session.pk]), form)
                self.assertEqual(response.status_code, 302)

                session.refresh_from_db()
                imported = session.extracted_data['questions'][0]

                previewed = draft_from_post(
                    form, 0, base=dict(stored),
                    defaults={'year_level': 5, 'topic': 'Decimals',
                              'subject': 'Mathematics', 'strand': ''},
                )

                for field, value in previewed.items():
                    if field in NOT_CLAIMED:
                        continue
                    self.assertEqual(
                        value, imported.get(field),
                        f'{name}: the preview reads {field!r} as {value!r} but '
                        f'importing stores {imported.get(field)!r}',
                    )
