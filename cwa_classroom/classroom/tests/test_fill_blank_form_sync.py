"""``_sync_blank_spec`` — keeping a fill-in-the-blank question's spec in step.

The teacher create/edit form derives ``blank_spec`` from the question's text and
answer rows after saving them. What matters here is that the spec never goes
stale: editing the sentence, changing the answers, or switching the question to
another type must all leave the question in a state that renders and grades
correctly, and a question whose answers cannot be mapped must save anyway — as a
working single box — with the teacher told why.
"""
from django.contrib.messages import get_messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from classroom.models import Level
from classroom.views import _sync_blank_spec
from maths.models import Answer, Question

SENTENCE = 'A triangle has ___ sides and ___ angles.'
SPEC = {'blanks': [{'answers': ['3']}, {'answers': ['3']}]}


def _request():
    """A request that can carry messages (the helper warns through them)."""
    request = RequestFactory().post('/')
    SessionMiddleware(lambda r: None).process_request(request)
    MessageMiddleware(lambda r: None).process_request(request)
    return request


class SyncBlankSpecTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=980, defaults={'display_name': 'form sync fixture'})

    def _question(self, text=SENTENCE, answers=('3; 3',),
                  question_type=Question.FILL_BLANK, blank_spec=None):
        q = Question.objects.create(
            level=self.level, question_text=text, question_type=question_type,
            difficulty=1, points=1, blank_spec=blank_spec,
        )
        for order, text_ in enumerate(answers, start=1):
            Answer.objects.create(question=q, answer_text=text_,
                                  is_correct=True, order=order)
        return q

    def _sync(self, q):
        # The view saves the question and rewrites its answers before calling the
        # helper, so mirror that ordering here — the helper only writes
        # blank_spec.
        q.save()
        request = _request()
        _sync_blank_spec(q, request)
        q.refresh_from_db()
        return [str(m) for m in get_messages(request)]

    def test_builds_the_spec_on_a_new_question(self):
        q = self._question()
        self.assertEqual(self._sync(q), [])
        self.assertEqual(q.blank_spec, SPEC)

    def test_rebuilds_after_the_sentence_gains_a_blank(self):
        q = self._question(blank_spec=SPEC)
        q.question_text = 'A triangle has ___ sides, ___ angles and ___ vertices.'
        q.answers.all().delete()
        Answer.objects.create(question=q, answer_text='3; 3; 3',
                              is_correct=True, order=1)
        self.assertEqual(self._sync(q), [])
        self.assertEqual(len(q.blank_spec['blanks']), 3)
        # The spec matches its sentence again, so the gaps still render.
        self.assertIsNotNone(q.blank_data)

    def test_clears_the_spec_when_the_blanks_are_removed(self):
        q = self._question(blank_spec=SPEC)
        q.question_text = 'How many sides does a triangle have?'
        self._sync(q)
        self.assertIsNone(q.blank_spec)

    def test_clears_the_spec_when_the_type_changes(self):
        # Mirrors how the measure fields are cleared on a type switch — a spec
        # left behind would be rejected by clean() on the next save.
        q = self._question(blank_spec=SPEC)
        q.question_type = Question.SHORT_ANSWER
        self._sync(q)
        self.assertIsNone(q.blank_spec)

    def test_an_unmappable_answer_saves_as_a_single_box_and_warns(self):
        q = self._question(answers=('three sides and three angles',))
        messages = self._sync(q)
        self.assertIsNone(q.blank_spec)
        self.assertEqual(len(messages), 1)
        self.assertIn('one answer box', messages[0])
        self.assertIn('does not split', messages[0])
        # Still a working question — it grades the way a short answer does.
        self.assertTrue(q.grade_text_answer('three sides and three angles'))

    def test_a_newly_unmappable_edit_clears_the_stale_spec(self):
        # The dangerous case: the old spec must not survive an edit it no longer
        # describes, or the question would grade against the wrong gaps.
        q = self._question(blank_spec=SPEC)
        q.answers.all().delete()
        Answer.objects.create(question=q, answer_text='three sides and three angles',
                              is_correct=True, order=1)
        self._sync(q)
        self.assertIsNone(q.blank_spec)

    def test_the_synced_question_passes_validation(self):
        q = self._question()
        self._sync(q)
        q.full_clean()  # must not raise
