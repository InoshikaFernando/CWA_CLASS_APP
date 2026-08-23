"""Worksheet support for fill-in-the-blank questions.

Covers the answer-partial dispatch entry, the interactive session partial (the
shared sentence widget posting to text_answer), the fallback for a fill_blank
question that has no spec, and the printable detail view (the answer key for the
teacher). Grading reuses ``Question.grade_text_answer``, which routes a blanks
payload to ``maths.blank_grading.grade_fill_blank`` (separately unit-tested), so
every surface grades identically. Mirrors test_table_of_values_worksheet.py.
"""
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, Subject, Topic
from maths.models import Answer, Question
from worksheets.models import Worksheet, WorksheetQuestion
from worksheets.views import ANSWER_PARTIAL_MAP

SENTENCE = (
    'Out of 100 000 births, 99 231 females are expected to survive to the age '
    'of ___. From that age, the survivors are expected to ___ for another '
    '67.0 years.'
)


_DEFAULT_SPEC = {'blanks': [{'answers': ['15']}, {'answers': ['live', 'survive']}]}
_UNSET = object()


def _blank_question(level, topic, blank_spec=_UNSET):
    return Question.objects.create(
        level=level, topic=topic,
        question_text=SENTENCE,
        question_type=Question.FILL_BLANK, difficulty=1, points=1,
        blank_spec=_DEFAULT_SPEC if blank_spec is _UNSET else blank_spec,
    )


class FillBlankWorksheetConfigTests(TestCase):
    def test_in_answer_partial_map(self):
        self.assertTrue(
            ANSWER_PARTIAL_MAP['fill_blank'].endswith('_answer_fill_blank.html'))

    def _topic(self):
        level, _ = Level.objects.get_or_create(
            level_number=983, defaults={'display_name': 'ws fb fixture'})
        subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})[0]
        topic = Topic.objects.get_or_create(
            subject=subject, name='WS Fill Blank',
            defaults={'slug': 'ws-fill-blank', 'is_active': True})[0]
        return level, topic

    def test_answer_partial_renders_the_sentence_with_inputs(self):
        level, topic = self._topic()
        q = _blank_question(level, topic)
        html = render_to_string(
            'worksheets/partials/_answer_fill_blank.html', {'question': q})
        self.assertIn('data-fb-stage', html)          # interactive stage
        self.assertEqual(html.count('data-fb-input'), 2)  # one input per gap
        self.assertIn('name="text_answer"', html)     # gaps serialise to text_answer
        # The sentence itself is rendered around the gaps, so the student reads
        # it as a sentence rather than answering a detached box.
        self.assertIn('Out of 100 000 births', html)
        self.assertIn('for another', html)
        # The correct answers must never leak into the student widget. ("survive"
        # itself appears in the sentence, so the check is on the answer-key form
        # blank_data carries for the teacher surface.)
        self.assertNotIn('value="15"', html)
        self.assertNotIn('live or survive', html)

    def test_a_question_with_no_spec_falls_back_to_the_single_box(self):
        level, topic = self._topic()
        q = _blank_question(level, topic, blank_spec=None)
        html = render_to_string(
            'worksheets/partials/_answer_fill_blank.html', {'question': q})
        self.assertNotIn('data-fb-stage', html)
        self.assertIn('name="text_answer"', html)


class FillBlankWorksheetDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})
        cls.owner = CustomUser.objects.create_user(
            'ws_fb_owner', 'ws_fb_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='WS FB School', slug='ws-fb-school', admin=cls.owner)
        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})[0]
        cls.level = Level.objects.get_or_create(
            level_number=982, defaults={'display_name': 'Year 10 fb'})[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='WS FB Detail',
            defaults={'slug': 'ws-fb-detail', 'is_active': True})[0]
        cls.question = _blank_question(cls.level, cls.topic)
        cls.worksheet = Worksheet.objects.create(
            school=cls.school, name='Fill Blank Worksheet',
            original_filename='fb.pdf', created_by=cls.owner)
        WorksheetQuestion.objects.create(
            worksheet=cls.worksheet, question=cls.question, order=0)

    def setUp(self):
        self.client.force_login(self.owner)

    def test_detail_view_shows_answer_key(self):
        url = reverse('worksheets:detail', kwargs={'pk': self.worksheet.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The sentence keeps its gaps; the key lists what goes in each one.
        self.assertIn('15', body)
        self.assertIn('live or survive', body)
        self.assertIn('text-emerald-700', body)  # answers highlighted for the teacher


class FillBlankWorksheetGradingTests(TestCase):
    """The blanks payload posted from the session page grades on the model."""

    @classmethod
    def setUpTestData(cls):
        cls.level = Level.objects.get_or_create(
            level_number=981, defaults={'display_name': 'Year 10 fb grade'})[0]
        cls.question = Question.objects.create(
            level=cls.level, question_text=SENTENCE,
            question_type=Question.FILL_BLANK, difficulty=1, points=1,
            blank_spec={'blanks': [{'answers': ['15']},
                                   {'answers': ['live', 'survive']}]},
        )
        Answer.objects.create(
            question=cls.question, answer_text='15; live', is_correct=True)

    def test_correct_payload(self):
        self.assertTrue(
            self.question.grade_text_answer('{"blanks": ["15", "survive"]}'))

    def test_one_wrong_gap_fails_the_whole_sentence(self):
        self.assertFalse(
            self.question.grade_text_answer('{"blanks": ["15", "die"]}'))

    def test_the_pre_conversion_answer_row_is_not_what_grades(self):
        # The row survives for BrainBuzz/exports, but the spec is the authority.
        self.assertFalse(self.question.grade_text_answer('15; live'))
