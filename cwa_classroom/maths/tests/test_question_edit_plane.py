"""The global question editor, opened on a Cartesian-plane question.

Before this, opening an identify_coords question in the editor showed exactly
one editable thing — the multiple-choice options list — above the red warning
"This question has no answers stored — nothing can be marked correct". Both were
wrong. These questions are graded from ``plane_spec`` and have no ``Answer``
rows by design, so the warning cried wolf; and the field that WAS wrong on the
reported question — a plane drawing the answer, D, and none of the points A, B
and C the question names — had no input anywhere in the modal.
"""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question

User = get_user_model()

MIDPOINT_TEXT = (
    'A is the point (2, 2), B is the point (8, 2) and C is the point (5, 8). '
    'D is the mid point of the line AB. Write down the co-ordinates of the '
    'point D.'
)

# What the AI import stored: the ANSWER drawn, the named points missing.
BROKEN_SPEC = {
    'bounds': {'xmin': 0, 'xmax': 10, 'ymin': 0, 'ymax': 10},
    'mode': 'points',
    'given_points': [[5, 2]],
    'target': {'points': [[5, 2]]},
}

# What a teacher should be able to correct it to.
FIXED_SPEC = {
    'bounds': {'xmin': 0, 'xmax': 10, 'ymin': 0, 'ymax': 10},
    'mode': 'points',
    'given_points': [[2, 2, 'A'], [8, 2, 'B'], [5, 8, 'C']],
    'target': {'points': [[5, 2]]},
}


class PlaneQuestionEditorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import Role as R

        cls.admin = User.objects.create_superuser(
            username='planeadmin', email='plane@test.com', password='pass1234')
        role, _ = R.objects.get_or_create(
            name=R.ADMIN, defaults={'display_name': 'Admin'})
        cls.admin.roles.add(role)

        cls.subject = Subject.objects.create(name='Maths Plane', slug='maths-plane')
        cls.level = Level.objects.create(level_number=5, display_name='Year 5')
        cls.topic = Topic.objects.create(
            name='Coordinate Geometry', slug='coordinate-geometry',
            subject=cls.subject)

    def setUp(self):
        self.client = Client()
        self.client.login(username='planeadmin', password='pass1234')
        self.question = Question.objects.create(
            level=self.level, topic=self.topic, question_text=MIDPOINT_TEXT,
            question_type=Question.IDENTIFY_COORDS, plane_spec=BROKEN_SPEC)
        self.url = reverse('admin_global_question_edit', args=[self.question.id])

    def _payload(self, spec=FIXED_SPEC, **over):
        data = {'question_text': MIDPOINT_TEXT,
                'question_type': Question.IDENTIFY_COORDS,
                'plane_spec': json.dumps(spec)}
        data.update(over)
        return data

    # ── what the form offers ────────────────────────────────────────────

    def test_the_editor_offers_the_plane(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="plane_spec"', html)
        self.assertIn('given_points', html)

    def test_the_stored_plane_is_shown_to_edit(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('&quot;xmax&quot;: 10', html)

    def test_the_options_editor_is_not_offered(self):
        """These questions have no Answer rows; an options list is meaningless."""
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('+ Add answer', html)

    def test_no_answers_stored_is_not_reported_as_a_fault(self):
        """Having no options is how this type is built, not something to fix."""
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('This question has no answers stored', html)

    def test_a_choice_question_still_gets_its_options_editor(self):
        mcq = Question.objects.create(
            level=self.level, topic=self.topic, question_text='What is 7 + 8?',
            question_type='multiple_choice')
        Answer.objects.create(question=mcq, answer_text='15', is_correct=True)
        html = self.client.get(
            reverse('admin_global_question_edit', args=[mcq.id])).content.decode()
        self.assertIn('+ Add answer', html)
        self.assertNotIn('name="plane_spec"', html)

    # ── saving ──────────────────────────────────────────────────────────

    def test_saving_a_corrected_plane_persists_it(self):
        response = self.client.post(self.url, self._payload())

        self.assertEqual(response.status_code, 200)
        self.question.refresh_from_db()
        self.assertEqual(self.question.plane_spec['given_points'],
                         [[2, 2, 'A'], [8, 2, 'B'], [5, 8, 'C']])
        # The answer is untouched — the fix was to the figure, not the marking.
        self.assertEqual(self.question.plane_spec['target']['points'], [[5, 2]])

    def test_saving_does_not_warn_that_nothing_is_marked_correct(self):
        """The old warning fired on every save of a question with no options."""
        html = self.client.post(self.url, self._payload()).content.decode()
        self.assertIn('Saved.', html)
        self.assertNotIn('No option is marked correct', html)

    def test_an_unusable_plane_is_refused_not_stored(self):
        """A spec that cannot be drawn leaves the child a blank space."""
        bad = {**FIXED_SPEC, 'given_points': [[99, 99, 'A']]}
        html = self.client.post(self.url, self._payload(bad)).content.decode()

        self.assertIn('not usable', html)
        self.question.refresh_from_db()
        self.assertEqual(self.question.plane_spec, BROKEN_SPEC)

    def test_broken_json_is_refused_and_handed_back_to_be_fixed(self):
        html = self.client.post(
            self.url, self._payload(plane_spec='{"bounds": ')).content.decode()

        self.assertIn('not valid JSON', html)
        # What they typed comes back — replacing it with the stored spec would
        # throw the edit away and leave them re-typing it.
        self.assertIn('{&quot;bounds&quot;: ', html)
        self.question.refresh_from_db()
        self.assertEqual(self.question.plane_spec, BROKEN_SPEC)

    def test_an_empty_plane_is_refused(self):
        html = self.client.post(
            self.url, self._payload(plane_spec='')).content.decode()

        self.assertIn('needs a plane', html)
        self.question.refresh_from_db()
        self.assertEqual(self.question.plane_spec, BROKEN_SPEC)

    def test_a_save_that_carries_no_plane_field_leaves_the_spec_alone(self):
        """Only a form that offered the field may change it."""
        data = self._payload()
        del data['plane_spec']
        self.client.post(self.url, data)

        self.question.refresh_from_db()
        self.assertEqual(self.question.plane_spec, BROKEN_SPEC)

    # ── preview ─────────────────────────────────────────────────────────

    def test_the_preview_draws_the_plane_being_typed_not_the_stored_one(self):
        response = self.client.post(
            reverse('admin_global_question_preview', args=[self.question.id]),
            self._payload())
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        for name in ('>A<', '>B<', '>C<'):
            self.assertIn(name, html)

        # Previewing writes nothing.
        self.question.refresh_from_db()
        self.assertEqual(self.question.plane_spec, BROKEN_SPEC)
