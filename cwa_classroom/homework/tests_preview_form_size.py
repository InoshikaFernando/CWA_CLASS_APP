"""The PDF review page must survive its own Continue button — CPP bug: 400 on submit.

A teacher uploaded a workbook, reviewed the extracted questions and pressed
"Continue to Confirm". The browser came back on the same URL showing Django's
bare ``Bad Request (400)`` (prod session 134, DEBUG=False). Nothing reached the
view: Django's multipart parser raised ``TooManyFieldsSent`` while
``CsrfViewMiddleware`` was reading ``request.POST``, so the exception became a
400 before any of our code ran.

The cause was the shape of the form, not the ceiling. Every review card renders
all nine structured-spec panels (long division, prime factorisation, column
arithmetic, plane, graph, measure, number line, table, sketch) so the type
dropdown can reveal one without a reload — and a browser posts every enabled
field, shown or not. That made each question ~29 parts, sixteen of which the
view ignores for that question's type, and put the wall at 690 questions.

The panels that don't apply are now disabled, so a card posts only what it is
editing. These tests drive the form the way a browser does — including the empty
file part an untouched ``<input type="file">`` still sends, which counts toward
the same ceiling — rather than posting a hand-written dict, because a
hand-written dict is exactly what let this ship twice.
"""
from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from homework.models import HomeworkUploadSession
from homework.tests import HomeworkTestBase


# ---------------------------------------------------------------------------
# A browser, near enough: what the rendered form actually submits
# ---------------------------------------------------------------------------

class SubmittedForm(HTMLParser):
    """Collect what a browser would send for the rendered ``#preview-form``.

    Follows the rules that matter here: a disabled field is never submitted, an
    unchecked box is not submitted, a select submits its selected option (its
    first when none is marked), and an untouched file input is still submitted
    as an empty part.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_form = False
        self.fields = []          # [(name, value)] — the non-file parts
        self.files = []           # [name] — one part each, empty or not
        self._textarea = None
        self._textarea_value = ''
        self._select = None
        self._options = None

    @property
    def part_count(self):
        """Parts on the wire. Django counts file parts toward the field ceiling
        too, so this — not ``len(self.fields)`` — is what hits the limit."""
        return len(self.fields) + len(self.files)

    def names(self):
        return {name for name, _ in self.fields} | set(self.files)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'form':
            self.in_form = True
            return
        if not self.in_form or 'disabled' in attributes:
            return
        if tag == 'input':
            name = attributes.get('name')
            if not name:
                return
            input_type = (attributes.get('type') or 'text').lower()
            if input_type == 'file':
                self.files.append(name)
            elif input_type in ('checkbox', 'radio'):
                if 'checked' in attributes:
                    self.fields.append((name, attributes.get('value', 'on')))
            else:
                self.fields.append((name, attributes.get('value', '')))
        elif tag == 'textarea':
            self._textarea = attributes.get('name')
            self._textarea_value = ''
        elif tag == 'select':
            self._select = attributes.get('name')
            self._options = []
        elif tag == 'option' and self._select:
            self._options.append((attributes.get('value', ''), 'selected' in attributes))

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea_value += data

    def handle_endtag(self, tag):
        if tag == 'form':
            self.in_form = False
        elif tag == 'textarea' and self._textarea is not None:
            self.fields.append((self._textarea, self._textarea_value))
            self._textarea = None
        elif tag == 'select' and self._select:
            chosen = [value for value, selected in self._options if selected]
            if not chosen and self._options:
                chosen = [self._options[0][0]]
            for value in chosen:
                self.fields.append((self._select, value))
            self._select = None
            self._options = None


BOUNDARY = 'PreviewFormBoundary'
CONTENT_TYPE = f'multipart/form-data; boundary={BOUNDARY}'


def encode_like_a_browser(form):
    """The multipart body a browser builds from a parsed ``SubmittedForm``."""
    parts = []
    for name, value in form.fields:
        parts.append(
            f'--{BOUNDARY}\r\n'
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        )
    for name in form.files:
        # An untouched file input is still a part: filename="" with no body.
        parts.append(
            f'--{BOUNDARY}\r\n'
            f'Content-Disposition: form-data; name="{name}"; filename=""\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n\r\n'
        )
    parts.append(f'--{BOUNDARY}--\r\n')
    return ''.join(parts).encode('utf-8')


# The wall this bug hit. 690 questions × ~29 parts crossed
# DATA_UPLOAD_MAX_NUMBER_FIELDS (20000) and returned a bare 400 on submit.
QUESTIONS_THAT_USED_TO_400 = 690

# What one review card is allowed to post. Ten always-on fields (include,
# image_ref, text, type, validation_type, difficulty, points, rubric,
# explanation, plus the file input) and the answer rows. Nine structured-spec
# panels ride along disabled and must stay off the wire. Raising this number
# lowers how long a workbook can be before the submit 400s again — at 20000
# parts the ceiling is DATA_UPLOAD_MAX_NUMBER_FIELDS // this.
MAX_PARTS_PER_QUESTION = 16


class PreviewFormBase(HomeworkTestBase):

    def make_session(self, questions, **extra):
        return HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='workbook.pdf',
            homework_title='Term 3 workbook',
            status=HomeworkUploadSession.STATUS_DONE,
            extracted_data={
                'year_level': 5, 'subject': 'Mathematics', 'topic': 'Mixed',
                'questions': questions,
            },
            extracted_images={},
            **extra,
        )

    def render_form(self, session):
        """GET the review page and parse what its form would submit."""
        self.client.force_login(self.teacher)
        url = reverse('homework:pdf_preview', kwargs={'session_id': session.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        form = SubmittedForm()
        form.feed(response.content.decode())
        return url, form


class PreviewSubmitSurvivesALongWorkbookTest(PreviewFormBase):

    def test_the_workbook_size_that_returned_400_now_reaches_the_confirm_step(self):
        questions = [
            {'question_text': f'Q{i}', 'include': True,
             'question_type': 'short_answer',
             'answers': [{'text': 'a', 'is_correct': True},
                         {'text': 'b', 'is_correct': False}]}
            for i in range(QUESTIONS_THAT_USED_TO_400)
        ]
        session = self.make_session(questions)
        url, form = self.render_form(session)

        response = self.client.post(
            url, data=encode_like_a_browser(form), content_type=CONTENT_TYPE)

        # 400 here is the bug: TooManyFieldsSent, raised before the view ran.
        self.assertEqual(response.status_code, 302, 'submit came back as a 400')
        self.assertEqual(
            response['Location'],
            reverse('homework:pdf_confirm', kwargs={'session_id': session.pk}),
        )
        session.refresh_from_db()
        self.assertEqual(len(session.extracted_data['questions']),
                         QUESTIONS_THAT_USED_TO_400)

    def test_a_review_card_posts_only_the_fields_it_is_editing(self):
        """The parts budget — the thing that actually sets the ceiling.

        Measured per question rather than asserted once at 690, so a new
        always-posted field is caught here (with the arithmetic in the failure
        message) instead of in production on a long workbook.
        """
        one = self.render_form(self.make_session([
            {'question_text': 'Q0', 'include': True,
             'question_type': 'short_answer',
             'answers': [{'text': 'a', 'is_correct': True},
                         {'text': 'b', 'is_correct': False}]},
        ]))[1]
        two = self.render_form(self.make_session([
            {'question_text': f'Q{i}', 'include': True,
             'question_type': 'short_answer',
             'answers': [{'text': 'a', 'is_correct': True},
                         {'text': 'b', 'is_correct': False}]}
            for i in range(3)
        ]))[1]

        per_question = (two.part_count - one.part_count) // 2
        from django.conf import settings
        self.assertLessEqual(
            per_question, MAX_PARTS_PER_QUESTION,
            f'each question now posts {per_question} parts, so the review page '
            f'400s past {settings.DATA_UPLOAD_MAX_NUMBER_FIELDS // per_question} '
            f'questions',
        )


class PreviewFormPostsTheRightSpecFieldsTest(PreviewFormBase):
    """The mechanism: a panel is on the wire when — and only when — it applies."""

    SPEC_FIELDS = {
        'q_0_dividend', 'q_0_divisor', 'q_0_target_number', 'q_0_operands',
        'q_0_operator', 'q_0_plane_spec', 'q_0_numeric_answer',
        'q_0_answer_tolerance', 'q_0_answer_unit', 'q_0_graph_spec',
        'q_0_measure_numeric_answer', 'q_0_measure_answer_tolerance',
        'q_0_measure_answer_unit', 'q_0_number_line_spec', 'q_0_table_spec',
        'q_0_sketch_spec',
    }

    def submitted_names(self, question_type, **extra):
        session = self.make_session([
            dict({'question_text': 'Q', 'include': True,
                  'question_type': question_type, 'answers': []}, **extra),
        ])
        return self.render_form(session)[1].names()

    def test_a_plain_question_posts_no_spec_fields_at_all(self):
        names = self.submitted_names('short_answer')
        self.assertEqual(names & self.SPEC_FIELDS, set())
        # …while still posting what the card really edits.
        self.assertIn('q_0_text', names)
        self.assertIn('q_0_type', names)
        self.assertIn('q_0_image_upload', names)

    def test_each_structured_type_posts_its_own_panel_and_nothing_else(self):
        expected = {
            'long_division': {'q_0_dividend', 'q_0_divisor'},
            'prime_factorization': {'q_0_target_number'},
            'column_operation': {'q_0_operands', 'q_0_operator'},
            # All three plane types share one panel. plot_line and
            # identify_coords used to lose it to an `{% if not a == x or ... %}`
            # that Django reads as `(not a == x) or …` — so the panel their
            # question is graded from was hidden AND disabled.
            'plot_points': {'q_0_plane_spec'},
            'plot_line': {'q_0_plane_spec'},
            'identify_coords': {'q_0_plane_spec'},
            'read_graph': {'q_0_numeric_answer', 'q_0_answer_tolerance',
                           'q_0_answer_unit', 'q_0_graph_spec'},
            'measure': {'q_0_measure_numeric_answer',
                        'q_0_measure_answer_tolerance',
                        'q_0_measure_answer_unit'},
            'number_line': {'q_0_number_line_spec'},
            'table_of_values': {'q_0_table_spec'},
            'sketch_graph': {'q_0_sketch_spec'},
        }
        for question_type, panel_fields in expected.items():
            with self.subTest(question_type=question_type):
                names = self.submitted_names(question_type)
                self.assertEqual(names & self.SPEC_FIELDS, panel_fields)

    def test_an_edited_spec_still_saves(self):
        """The disabling must not cost the panel that IS active its edit."""
        session = self.make_session([
            {'question_text': 'Complete the table.', 'include': True,
             'question_type': 'table_of_values', 'answers': [],
             'table_spec': {'headers': ['a', 'b'],
                            'rows': [[{'given': '1'}, {'answer': '2'}]]}},
        ])
        url, form = self.render_form(session)
        edited = '{"headers": ["a", "b"], "rows": [[{"given": "9"}, {"answer": "10"}]]}'
        form.fields = [(name, edited if name == 'q_0_table_spec' else value)
                       for name, value in form.fields]

        response = self.client.post(
            url, data=encode_like_a_browser(form), content_type=CONTENT_TYPE)

        self.assertEqual(response.status_code, 302)
        session.refresh_from_db()
        saved = session.extracted_data['questions'][0]
        self.assertEqual(saved['question_type'], 'table_of_values')
        self.assertEqual(saved['table_spec']['rows'][0][0]['given'], '9')
