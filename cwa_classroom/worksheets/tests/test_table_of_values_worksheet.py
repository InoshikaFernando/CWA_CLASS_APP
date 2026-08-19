"""Worksheet support for the table_of_values question type.

Covers the answer-partial dispatch entry, the interactive session partial (the
shared table widget posting to text_answer), and the printable detail view (the
table with the correct cells filled in for the teacher). Grading reuses the pure
``maths.geometry_grading.grade_table`` (separately unit-tested), wired into
``WorksheetAnswerView`` alongside the other maths branches. Mirrors
test_number_line_worksheet.py.
"""
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, Subject, Topic
from maths.models import Question
from worksheets.models import Worksheet, WorksheetQuestion
from worksheets.views import ANSWER_PARTIAL_MAP


def _table_question(level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text='Complete the table for y = x² - 5.',
        question_type=Question.TABLE_OF_VALUES, difficulty=1, points=1,
        table_spec={
            'headers': ['x', 'y'],
            'rows': [
                [{'given': '0'}, {'answer': '-5'}],
                [{'given': '3'}, {'answer': '4'}],
            ],
        },
    )


class TableOfValuesWorksheetConfigTests(TestCase):
    def test_in_answer_partial_map(self):
        self.assertTrue(
            ANSWER_PARTIAL_MAP['table_of_values'].endswith('_answer_table_of_values.html'))

    def _topic(self):
        level, _ = Level.objects.get_or_create(
            level_number=985, defaults={'display_name': 'ws tov fixture'})
        subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})[0]
        topic = Topic.objects.get_or_create(
            subject=subject, name='WS Table Of Values',
            defaults={'slug': 'ws-table-of-values', 'is_active': True})[0]
        return level, topic

    def test_answer_partial_renders_interactive(self):
        level, topic = self._topic()
        q = _table_question(level, topic)
        html = render_to_string(
            'worksheets/partials/_answer_table_of_values.html', {'question': q})
        self.assertIn('data-tv-stage', html)          # interactive stage
        self.assertIn('data-tv-cell', html)           # blank inputs
        self.assertIn('name="text_answer"', html)     # cells serialise to text_answer
        # The correct answers must never leak into the student widget.
        self.assertNotIn('value="-5"', html)
        self.assertNotIn('value="4"', html)


class TableOfValuesWorksheetDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})
        cls.owner = CustomUser.objects.create_user(
            'ws_tov_owner', 'ws_tov_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='WS TOV School', slug='ws-tov-school', admin=cls.owner)
        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})[0]
        cls.level = Level.objects.get_or_create(
            level_number=984, defaults={'display_name': 'Year 6 tov'})[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='WS TOV Detail',
            defaults={'slug': 'ws-tov-detail', 'is_active': True})[0]
        cls.question = _table_question(cls.level, cls.topic)
        cls.worksheet = Worksheet.objects.create(
            school=cls.school, name='Table Of Values Worksheet',
            original_filename='tov.pdf', created_by=cls.owner)
        WorksheetQuestion.objects.create(
            worksheet=cls.worksheet, question=cls.question, order=0)

    def setUp(self):
        self.client.force_login(self.owner)

    def test_detail_view_shows_answer_key(self):
        url = reverse('worksheets:detail', kwargs={'pk': self.worksheet.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('<table', body)          # the answer-key table renders
        self.assertIn('-5', body)              # correct answer cells shown
        self.assertIn('text-emerald-700', body)  # answers highlighted for the teacher
