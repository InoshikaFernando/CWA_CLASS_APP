"""Worksheet support for the number_line question type.

Covers the extraction enum, the answer-partial dispatch entry, the interactive
session partial (mark mode taps ticks; read mode types a value), and the
printable detail view (drawn scale + the correct value shown to the teacher).
Grading reuses the pure ``maths.geometry_grading.grade_number_line`` (separately
unit-tested), wired into ``WorksheetAnswerView`` alongside the other maths
branches. Mirrors test_measure_worksheet.py.
"""
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, Subject, Topic
from maths.models import Question
from worksheets.models import Worksheet, WorksheetQuestion
from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL
from worksheets.views import ANSWER_PARTIAL_MAP


def _number_line_question(level, topic, **spec_over):
    spec = {'min': -3, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [2]}
    spec.update(spec_over)
    return Question.objects.create(
        level=level, topic=topic,
        question_text='Mark 2 on the number line.',
        question_type=Question.NUMBER_LINE, difficulty=1, points=1,
        number_line_spec=spec,
    )


class NumberLineWorksheetConfigTests(TestCase):
    def test_in_extraction_enum(self):
        enum = (WORKSHEET_CLASSIFICATION_TOOL["input_schema"]["properties"]
                ["questions"]["items"]["properties"]["question_type"]["enum"])
        self.assertIn('number_line', enum)

    def test_in_answer_partial_map(self):
        self.assertTrue(ANSWER_PARTIAL_MAP['number_line'].endswith('_answer_number_line.html'))

    def _topic(self):
        level, _ = Level.objects.get_or_create(
            level_number=987, defaults={'display_name': 'ws nl fixture'})
        subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})[0]
        topic = Topic.objects.get_or_create(
            subject=subject, name='WS Number Line',
            defaults={'slug': 'ws-number-line', 'is_active': True})[0]
        return level, topic

    def test_answer_partial_mark_mode_renders_interactive(self):
        level, topic = self._topic()
        q = _number_line_question(level, topic)
        html = render_to_string('worksheets/partials/_answer_number_line.html', {'question': q})
        self.assertIn('data-nl-stage', html)          # interactive stage
        self.assertIn('data-nl-dot', html)            # tappable ticks
        self.assertIn('name="text_answer"', html)     # hidden marks field posts text_answer

    def test_answer_partial_read_mode_renders_text_box(self):
        level, topic = self._topic()
        q = _number_line_question(level, topic, mode='read', given=[6], target=None)
        html = render_to_string('worksheets/partials/_answer_number_line.html', {'question': q})
        self.assertIn('data-nl-mode="read"', html)
        self.assertIn('name="text_answer"', html)     # typed value posts text_answer


class NumberLineWorksheetDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})
        cls.owner = CustomUser.objects.create_user(
            'ws_nl_owner', 'ws_nl_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='WS NL School', slug='ws-nl-school', admin=cls.owner)
        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})[0]
        cls.level = Level.objects.get_or_create(
            level_number=986, defaults={'display_name': 'Year 6 nl'})[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='WS NL Detail',
            defaults={'slug': 'ws-nl-detail', 'is_active': True})[0]
        cls.question = _number_line_question(cls.level, cls.topic)
        cls.worksheet = Worksheet.objects.create(
            school=cls.school, name='Number Line Worksheet',
            original_filename='nl.pdf', created_by=cls.owner)
        WorksheetQuestion.objects.create(
            worksheet=cls.worksheet, question=cls.question, order=0)

    def setUp(self):
        self.client.force_login(self.owner)

    def test_detail_view_renders_number_line_and_answer(self):
        url = reverse('worksheets:detail', kwargs={'pk': self.worksheet.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('<svg', body)        # drawn scale on the printable
        self.assertIn('Mark: 2', body)     # correct value shown to the teacher
