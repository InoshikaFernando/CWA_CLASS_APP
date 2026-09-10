"""The AI-import review page must survive its own "Save & Continue" button.

Same shape, same failure as the homework PDF review page: every review card
renders all eight structured-spec panels (column arithmetic, long division,
prime factorisation, plane, graph, measure, number line, sketch) hidden so the
type dropdown can reveal one without a reload — and a browser posts every
ENABLED field, shown or not. A long import therefore crossed Django's
DATA_UPLOAD_MAX_NUMBER_FIELDS in the request parser, before any view ran, and
came back as a bare ``Bad Request (400)`` on the review URL.

This form is urlencoded rather than multipart, so it takes the
``limited_parse_qsl`` path instead of the multipart parser — same
``TooManyFieldsSent``, same bare 400.

Disabling the panels that don't apply fixes a second, quieter fault at the same
time: the graph and measure panels post the SAME three names
(``numeric_answer``, ``answer_tolerance``, ``answer_unit``), both enabled and
both pre-filled from the same stored value. A QueryDict returns the LAST value
for a repeated key, so the measure panel — rendered second, and hidden on a
read_graph question — overwrote what the teacher typed into the graph panel.
Their correction was dropped without a word.

Like the homework suite, these drive the RENDERED form rather than a
hand-written dict, because a hand-written dict is what let this ship.
"""
from urllib.parse import urlencode

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from ai_import.models import AIImportSession
from classroom.models import Level
from homework.tests_preview_form_size import SubmittedForm


# The 8 panels this page renders, and the field names each one posts.
SPEC_FIELDS_BY_PANEL = {
    'column': {'operands', 'operator'},
    'longdiv': {'dividend', 'divisor'},
    'primefactor': {'target_number'},
    'plane': {'plane_spec'},
    'graph': {'numeric_answer', 'answer_tolerance', 'answer_unit', 'graph_spec'},
    'measure': {'numeric_answer', 'answer_tolerance', 'answer_unit'},
    'numberline': {'number_line_spec'},
    'sketch': {'sketch_spec'},
}
ALL_SPEC_FIELDS = {f'q_0_{name}'
                   for names in SPEC_FIELDS_BY_PANEL.values() for name in names}

# What one review card is allowed to post. It sits at 13 (was 28, all eight
# panels), which puts the wall at ~1500 questions. Raising this lowers how long
# an import can be before "Save & Continue" 400s again — the wall is
# DATA_UPLOAD_MAX_NUMBER_FIELDS // this.
MAX_FIELDS_PER_QUESTION = 20


class PreviewFormBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'aiprev_super', 'aiprev_super@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=4,
                                    defaults={'display_name': 'Year 4'})

    def make_session(self, questions):
        return AIImportSession.objects.create(
            user=self.user, pdf_filename='workbook.pdf',
            status=AIImportSession.STATUS_READY, is_confirmed=False,
            extracted_data={
                'year_level': 4, 'subject': 'Mathematics', 'strand': 'Number',
                'topic': 'Mixed', 'questions': questions,
            },
            extracted_images={},
        )

    def render_form(self, session):
        self.client.force_login(self.user)
        url = reverse('ai_import:preview', kwargs={'session_id': session.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        form = SubmittedForm()
        form.feed(response.content.decode())
        return url, form


class PreviewSubmitSurvivesALongImportTest(PreviewFormBase):

    def test_a_review_card_posts_only_the_fields_it_is_editing(self):
        one = self.render_form(self.make_session([
            {'question_text': 'Q0', 'question_type': 'short_answer',
             'difficulty': 1, 'points': 1,
             'answers': [{'text': 'a', 'is_correct': True}]},
        ]))[1]
        three = self.render_form(self.make_session([
            {'question_text': f'Q{i}', 'question_type': 'short_answer',
             'difficulty': 1, 'points': 1,
             'answers': [{'text': 'a', 'is_correct': True}]}
            for i in range(3)
        ]))[1]

        per_question = (three.part_count - one.part_count) // 2
        self.assertLessEqual(
            per_question, MAX_FIELDS_PER_QUESTION,
            f'each question now posts {per_question} fields, so the review page '
            f'400s past {settings.DATA_UPLOAD_MAX_NUMBER_FIELDS // per_question} '
            f'questions',
        )

    def test_a_plain_question_posts_no_spec_fields_at_all(self):
        session = self.make_session([
            {'question_text': 'How many?', 'question_type': 'short_answer',
             'difficulty': 1, 'points': 1,
             'answers': [{'text': '4', 'is_correct': True}]},
        ])
        names = self.render_form(session)[1].names()

        self.assertEqual(names & ALL_SPEC_FIELDS, set())
        self.assertIn('q_0_text', names)
        self.assertIn('q_0_type', names)

    def test_each_structured_type_posts_its_own_panel_and_nothing_else(self):
        for question_type, panel in (
            ('column_operation', 'column'),
            ('long_division', 'longdiv'),
            ('prime_factorization', 'primefactor'),
            ('plot_points', 'plane'),
            ('plot_line', 'plane'),
            ('identify_coords', 'plane'),
            ('read_graph', 'graph'),
            ('measure', 'measure'),
            ('number_line', 'numberline'),
            ('sketch_graph', 'sketch'),
        ):
            with self.subTest(question_type=question_type):
                session = self.make_session([
                    {'question_text': 'Q', 'question_type': question_type,
                     'difficulty': 1, 'points': 1, 'answers': []},
                ])
                names = self.render_form(session)[1].names()
                expected = {f'q_0_{name}'
                            for name in SPEC_FIELDS_BY_PANEL[panel]}
                self.assertEqual(names & ALL_SPEC_FIELDS, expected)


class SharedFieldNamesDoNotOverwriteEachOtherTest(PreviewFormBase):
    """The graph and measure panels share three field names.

    Both were enabled and both pre-filled from the same stored value, so the
    POST carried each name twice. A QueryDict returns the LAST value for a
    repeated key, and the measure panel renders second — so on a read_graph
    question the hidden measure panel's stale copy beat what the teacher had
    just typed. Only one of the pair is ever enabled now.

    (The homework page dodged this by prefixing its measure fields with
    ``measure_``; this page never did.)
    """

    def test_a_read_graph_correction_is_saved_not_dropped(self):
        session = self.make_session([
            {'question_text': 'Read the distance off the graph.',
             'question_type': 'read_graph',
             'difficulty': 1, 'points': 1, 'answers': [],
             'numeric_answer': '90', 'answer_tolerance': '2', 'answer_unit': 'km'},
        ])
        url, form = self.render_form(session)

        # The graph panel renders BEFORE the measure panel, so the teacher edits
        # the first occurrence of each shared name and the hidden measure panel
        # keeps whatever was rendered into it. Posted as a real urlencoded body,
        # in document order, keeping every repeat: collapsing the fields into a
        # dict first would hide the very duplicate this is about.
        corrected = {'q_0_numeric_answer': '135', 'q_0_answer_tolerance': '3'}
        fields = list(form.fields)
        for name, edited in corrected.items():
            positions = [i for i, (field, _) in enumerate(fields) if field == name]
            self.assertTrue(positions, f'{name} was not rendered at all')
            fields[positions[0]] = (name, edited)
        body = urlencode(fields)

        response = self.client.post(
            url, data=body, content_type='application/x-www-form-urlencoded')
        self.assertEqual(response.status_code, 302, 'submit came back as a 400')

        session.refresh_from_db()
        saved = session.extracted_data['questions'][0]
        self.assertEqual(saved['numeric_answer'], '135')
        self.assertEqual(saved['answer_tolerance'], '3')
