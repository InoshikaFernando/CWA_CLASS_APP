"""Worksheet support for the measure question type (CPP-335).

Covers the answer-partial dispatch entry, the interactive session partial,
and the printable detail view (the true-scale figure + answer box a pupil
measures with a real protractor). Grading reuses the pure
``maths.geometry_grading.grade_measure`` (CPP-332, separately unit-tested),
wired into ``WorksheetAnswerView`` alongside the other maths branches.

Epic CPP-330.
"""
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, Subject, Topic
from maths.models import Question
from worksheets.models import Worksheet, WorksheetQuestion
from worksheets.views import ANSWER_PARTIAL_MAP


def _measure_question(level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text='Measure angle a.',
        question_type=Question.MEASURE, difficulty=1, points=1,
        numeric_answer=Decimal('135'), answer_tolerance=Decimal('2'),
        answer_unit='°',
    )


class MeasureWorksheetConfigTests(TestCase):
    def test_measure_in_answer_partial_map(self):
        assert ANSWER_PARTIAL_MAP['measure'].endswith('_answer_measure.html')

    def test_answer_measure_partial_renders(self):
        level, _ = Level.objects.get_or_create(
            level_number=989, defaults={'display_name': 'ws measure fixture'},
        )
        subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        topic = Topic.objects.get_or_create(
            subject=subject, name='WS Measure',
            defaults={'slug': 'ws-measure', 'is_active': True},
        )[0]
        q = _measure_question(level, topic)
        html = render_to_string('worksheets/partials/_answer_measure.html', {'question': q})
        assert '<svg' in html                  # generated figure
        assert 'name="text_answer"' in html    # numeric box posts text_answer
        assert '°' in html                      # unit suffix


class MeasureWorksheetDetailTests(TestCase):
    """The printable teacher detail view shows the true-scale figure."""

    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.owner = CustomUser.objects.create_user(
            'ws_measure_owner', 'ws_measure_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='WS Measure School', slug='ws-measure-school', admin=cls.owner,
        )
        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.level = Level.objects.get_or_create(
            level_number=988, defaults={'display_name': 'Year 6 measure'},
        )[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='WS Measure Detail',
            defaults={'slug': 'ws-measure-detail', 'is_active': True},
        )[0]
        cls.question = _measure_question(cls.level, cls.topic)
        cls.worksheet = Worksheet.objects.create(
            school=cls.school, name='Measure Worksheet',
            original_filename='m.pdf', created_by=cls.owner,
        )
        WorksheetQuestion.objects.create(
            worksheet=cls.worksheet, question=cls.question, order=0,
        )

    def setUp(self):
        self.client.force_login(self.owner)

    def test_detail_view_renders_measure_figure_and_answer(self):
        url = reverse('worksheets:detail', kwargs={'pk': self.worksheet.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('<svg', body)              # true-scale figure on the printable
        self.assertIn('Answer: 135', body)       # answer + tolerance shown to teacher
