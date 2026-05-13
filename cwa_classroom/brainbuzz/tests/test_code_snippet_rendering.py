"""
test_code_snippet_rendering.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for fenced code-block rendering in BrainBuzz question text.

Coverage:
  render_question_html (unit tests — no DB):
    - prose-only question → no <pre> tag
    - question with a code block → both prose and <pre> present
    - code block preserves whitespace / indentation
    - multiple fences in one text
    - XSS: HTML in prose and in code is escaped
    - missing / empty language label defaults to 'python'
    - language label is sanitised (no injection via class attribute)
    - empty string → empty result

  _session_state_payload (integration):
    - question_html present in payload
    - prose-only text → no <pre> in question_html
    - text with fence → <pre class="bb-code"> in question_html

  teacher ingame template:
    - x-html binding references questionHtml
    - bb-code CSS class present in page source

  student play template:
    - x-html binding references question.question_html
"""
import json
import re

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Role
from classroom.models import Subject
from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_SHORT_ANSWER,
)
from brainbuzz.utils import render_question_html

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_teacher(username):
    u = User.objects.create_user(username=username, password='pass', email=f'{username}@t.com')
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _make_subject():
    return Subject.objects.get_or_create(slug='cs-snip', defaults={'name': 'CS Snippets'})[0]


def _make_session(teacher, subject, code, status=BrainBuzzSession.STATUS_ACTIVE):
    return BrainBuzzSession.objects.create(
        code=code, host=teacher, subject=subject,
        status=status, current_index=0, state_version=1,
        time_per_question_sec=20,
    )


def _make_question(session, order, text, qtype=QUESTION_TYPE_MCQ):
    return BrainBuzzSessionQuestion.objects.create(
        session=session, order=order, question_text=text,
        question_type=qtype,
        options_json=[
            {'label': 'A', 'text': 'Yes', 'is_correct': True},
            {'label': 'B', 'text': 'No',  'is_correct': False},
        ],
        time_limit_sec=20, points_base=1000,
        source_model='Test', source_id=order,
    )


# ---------------------------------------------------------------------------
# Unit tests: render_question_html (pure Python, no DB)
# ---------------------------------------------------------------------------

PROSE_ONLY = "Which keyword exits a for loop in Python?"

CODE_QUESTION = (
    "What is the output of:\n"
    "```python\n"
    "for i in range(3):\n"
    "    if i == 1:\n"
    "        break\n"
    "    print(i)\n"
    "```"
)

TWO_FENCES = (
    "Compare these two snippets:\n"
    "```python\n"
    "x = 1\n"
    "```\n"
    "and\n"
    "```python\n"
    "y = 2\n"
    "```"
)


class TestRenderQuestionHtmlUnit(TestCase):

    def test_prose_only_no_pre_tag(self):
        html = render_question_html(PROSE_ONLY)
        self.assertNotIn('<pre', html)

    def test_prose_only_contains_text(self):
        html = render_question_html(PROSE_ONLY)
        self.assertIn('for loop', html)

    def test_prose_only_no_raw_unescaped_html(self):
        html = render_question_html('<b>bold</b>')
        self.assertNotIn('<b>', html)
        self.assertIn('&lt;b&gt;', html)

    def test_code_question_has_pre_tag(self):
        html = render_question_html(CODE_QUESTION)
        self.assertIn('<pre', html)
        self.assertIn('<code', html)

    def test_code_question_prose_preserved(self):
        html = render_question_html(CODE_QUESTION)
        self.assertIn('What is the output of:', html)

    def test_code_block_preserves_indentation(self):
        html = render_question_html(CODE_QUESTION)
        # The indented line must appear literally (HTML-encoded spaces are fine,
        # but tabs/spaces must not be collapsed)
        self.assertIn('    if i == 1:', html)

    def test_code_block_preserves_newlines(self):
        html = render_question_html(CODE_QUESTION)
        # Newlines inside a <pre> are rendered literally
        self.assertIn('for i in range(3):', html)
        self.assertIn('print(i)', html)

    def test_language_class_set_on_code_element(self):
        html = render_question_html(CODE_QUESTION)
        self.assertIn('language-python', html)

    def test_default_language_python_when_omitted(self):
        text = "What prints?\n```\nprint('hi')\n```"
        html = render_question_html(text)
        self.assertIn('language-python', html)

    def test_language_label_sanitised_no_injection(self):
        text = "x\n```<script>alert(1)</script>\nx=1\n```"
        html = render_question_html(text)
        # The raw <script> must not appear unescaped in the class attribute
        self.assertNotIn('<script>', html)

    def test_html_inside_code_escaped(self):
        text = "x\n```python\nprint('<b>hi</b>')\n```"
        html = render_question_html(text)
        self.assertNotIn('<b>', html)
        self.assertIn('&lt;b&gt;', html)

    def test_multiple_fences(self):
        html = render_question_html(TWO_FENCES)
        self.assertEqual(html.count('<pre'), 2)
        self.assertIn('x = 1', html)
        self.assertIn('y = 2', html)

    def test_empty_string_returns_empty(self):
        html = render_question_html('')
        self.assertEqual(str(html), '')

    def test_result_is_safe_string(self):
        from django.utils.safestring import SafeData
        result = render_question_html(PROSE_ONLY)
        self.assertIsInstance(result, SafeData)

    def test_bb_code_class_on_pre(self):
        html = render_question_html(CODE_QUESTION)
        self.assertIn('class="bb-code"', html)

    def test_bb_prose_class_on_prose_span(self):
        html = render_question_html(CODE_QUESTION)
        self.assertIn('class="bb-prose"', html)


# ---------------------------------------------------------------------------
# Integration tests: _session_state_payload includes question_html
# ---------------------------------------------------------------------------

class TestPayloadIncludesQuestionHtml(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('snip_api_teacher')
        cls.subject = _make_subject()
        cls.session = _make_session(cls.teacher, cls.subject, 'SNPAPI')
        cls.q_prose = _make_question(cls.session, 0, PROSE_ONLY)
        cls.q_code  = _make_question(cls.session, 1, CODE_QUESTION)
        cls.url = reverse('brainbuzz:api_session_state', kwargs={'join_code': cls.session.code})

    def _state(self, index):
        self.session.current_index = index
        self.session.save()
        return Client().get(self.url).json()

    def test_payload_has_question_html_field(self):
        data = self._state(0)
        self.assertIn('question_html', data['question'])

    def test_prose_only_no_pre_in_payload(self):
        data = self._state(0)
        self.assertNotIn('<pre', data['question']['question_html'])

    def test_code_question_has_pre_in_payload(self):
        data = self._state(1)
        self.assertIn('<pre', data['question']['question_html'])

    def test_code_payload_preserves_indentation(self):
        data = self._state(1)
        self.assertIn('    if i == 1:', data['question']['question_html'])

    def test_code_payload_has_language_class(self):
        data = self._state(1)
        self.assertIn('language-python', data['question']['question_html'])


# ---------------------------------------------------------------------------
# Template markup tests: teacher_ingame and student_play
# ---------------------------------------------------------------------------

class TestTemplateQuestionRendering(TestCase):

    @classmethod
    def setUpTestData(cls):
        from unittest import mock
        cls.teacher = _make_teacher('snip_tmpl_teacher')
        cls.subject = _make_subject()
        cls.session = _make_session(cls.teacher, cls.subject, 'SNPTMP',
                                    status=BrainBuzzSession.STATUS_ACTIVE)
        _make_question(cls.session, 0, CODE_QUESTION)

    def setUp(self):
        from unittest import mock
        self.patcher = mock.patch('brainbuzz.views._require_teacher', return_value=True)
        self.patcher.start()
        self.client = Client()
        self.client.force_login(self.teacher)

    def tearDown(self):
        self.patcher.stop()

    def test_teacher_ingame_contains_x_html_binding(self):
        url = reverse('brainbuzz:teacher_ingame', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        html = resp.content.decode()
        self.assertIn('questionHtml', html)
        self.assertIn('x-html', html)

    def test_teacher_ingame_contains_bb_code_css(self):
        url = reverse('brainbuzz:teacher_ingame', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        self.assertContains(resp, 'bb-code')

    def test_teacher_ingame_initial_state_has_question_html(self):
        url = reverse('brainbuzz:teacher_ingame', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        m = re.search(r'id="bb-initial-state"[^>]*>(.*?)</script>',
                      resp.content.decode(), re.DOTALL)
        self.assertIsNotNone(m)
        state = json.loads(m.group(1))
        self.assertIn('question_html', state['question'])

    def test_teacher_ingame_initial_state_code_html_has_pre(self):
        url = reverse('brainbuzz:teacher_ingame', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        m = re.search(r'id="bb-initial-state"[^>]*>(.*?)</script>',
                      resp.content.decode(), re.DOTALL)
        state = json.loads(m.group(1))
        self.assertIn('<pre', state['question']['question_html'])

    def _student_client(self, nickname):
        from brainbuzz.models import BrainBuzzParticipant
        participant = BrainBuzzParticipant.objects.create(
            session=self.session, nickname=nickname
        )
        c = Client()
        # Inject participant ID into the Django session (mirrors what the join view does)
        session = c.session
        session[f'bb_pid_{self.session.code}'] = participant.id
        session.save()
        return c, participant

    def test_student_play_contains_question_html_binding(self):
        c, _ = self._student_client('TestStudent')
        url = reverse('brainbuzz:student_play', kwargs={'join_code': self.session.code})
        resp = c.get(url)
        html = resp.content.decode()
        self.assertIn('question.question_html', html)
        self.assertIn('x-html', html)

    def test_student_play_contains_bb_code_css(self):
        c, _ = self._student_client('TestStudent2')
        url = reverse('brainbuzz:student_play', kwargs={'join_code': self.session.code})
        resp = c.get(url)
        self.assertContains(resp, 'bb-code')
