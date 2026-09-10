"""The worksheet review page's per-question field budget.

The homework and AI-import review pages both hit a bare ``Bad Request (400)``
on submit: every card posted all of its structured-spec panels, ~29 and ~28
fields per question, and a long upload crossed Django's
DATA_UPLOAD_MAX_NUMBER_FIELDS in the request parser before any view ran.

This page never grew those panels — it posts 11 fields per question, so its
wall sits around 1800 questions and it was never exposed. That is worth a test
rather than a note: the three review pages are edited in step (they share the
extractor, the type list and the crop modal), and the field that lands here
next is the one that puts this page where the other two were.
"""
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School
from homework.tests_preview_form_size import SubmittedForm
from worksheets.models import WorksheetUploadSession


# What one review card is allowed to post. It sits at 11. Raising it lowers how
# long a worksheet can be before "Save" 400s — the wall is
# DATA_UPLOAD_MAX_NUMBER_FIELDS // this.
MAX_FIELDS_PER_QUESTION = 14

# The structured-spec fields the other two review pages carry. If one arrives
# here it must arrive disabled-unless-it-applies, the way they now do — see
# worksheets.services.spec_panel_for_type.
SPEC_FIELD_NAMES = {
    'dividend', 'divisor', 'operands', 'operator', 'target_number',
    'plane_spec', 'graph_spec', 'number_line_spec', 'table_spec',
    'sketch_spec', 'numeric_answer', 'answer_tolerance', 'answer_unit',
    'measure_numeric_answer', 'measure_answer_tolerance',
    'measure_answer_unit',
}


class WorksheetPreviewFormSizeTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})
        cls.owner = CustomUser.objects.create_user(
            'ws_form_owner', 'ws_form_owner@test.internal', 'pass1!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(role)
        cls.school = School.objects.create(
            name='WS Form School', slug='ws-form-school', admin=cls.owner)

    def render_form(self, count):
        session = WorksheetUploadSession.objects.create(
            user=self.owner, school=self.school, pdf_filename='w.pdf',
            worksheet_name='Worksheet', is_confirmed=False,
            status=WorksheetUploadSession.STATUS_READY,
            extracted_data={
                'year_level': 6, 'subject': 'Mathematics',
                'questions': [
                    {'question_text': f'Q{i}', 'question_type': 'short_answer',
                     'validation_type': 'auto', 'include': True,
                     'difficulty': 1, 'points': 1,
                     'answers': [{'text': 'a', 'is_correct': True}]}
                    for i in range(count)
                ],
            },
            extracted_images={},
        )
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse('worksheets:preview', kwargs={'session_id': session.pk}))
        self.assertEqual(response.status_code, 200)
        form = SubmittedForm()
        form.feed(response.content.decode())
        return form

    def test_a_review_card_stays_within_the_budget(self):
        one, three = self.render_form(1), self.render_form(3)

        per_question = (three.part_count - one.part_count) // 2
        self.assertLessEqual(
            per_question, MAX_FIELDS_PER_QUESTION,
            f'each question now posts {per_question} fields, so the review page '
            f'400s past {settings.DATA_UPLOAD_MAX_NUMBER_FIELDS // per_question} '
            f'questions',
        )

    def test_no_spec_field_is_posted_unconditionally(self):
        posted = self.render_form(1).names()
        arrived = {name for name in SPEC_FIELD_NAMES if f'q_0_{name}' in posted}
        self.assertEqual(
            arrived, set(),
            'a structured-spec field reached this page and posts on every '
            'question regardless of its type — render it disabled unless '
            'q.spec_panel says it applies, as the homework and AI-import '
            'review pages do',
        )
