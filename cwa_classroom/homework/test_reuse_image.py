"""Tests for the homework "Same image as previous" reuse control.

Several consecutive questions can share ONE figure (e.g. "use the diagram below
for questions 3-6"). When the extractor doesn't group them, the teacher clicks
"Same image as previous" and the current question is pointed at the earlier
question's ref — the picture is NOT copied. One figure therefore means one entry
in ``extracted_images`` and one stored file, however many questions use it.

The confirm step keeps the sharing questions apart by deduping image questions on
their image path AND their text, so "same image" is never read as "same
question".
"""
import base64
import json

from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher, Subject, Topic, Level
from maths.models import Question as MQ

from .models import HomeworkUploadSession
from .views import _save_homework_pdf_questions


_IN_MEMORY_STORAGE = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


_PNG_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9'
    'awAAAABJRU5ErkJggg=='
)


class HomeworkReuseImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(name='teacher', defaults={'display_name': 'Teacher'})
        cls.teacher = CustomUser.objects.create_user('t1', 't1@x.com', 'pw')
        cls.teacher.roles.add(role)
        cls.other = CustomUser.objects.create_user('t2', 't2@x.com', 'pw')
        cls.other.roles.add(role)
        admin = CustomUser.objects.create_user('a', 'a@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='s', admin=admin)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

    def _session(self):
        return HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='t.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            extracted_data={'questions': [
                {'question_text': 'Angle A?', 'question_type': 'short_answer',
                 'has_image': True, 'image_ref': 'orig.png', 'image_page': 1,
                 'image_bbox_frac': [0.2, 0.2, 0.8, 0.6]},
                {'question_text': 'Angle B?', 'question_type': 'short_answer'},
            ]},
            extracted_images={'orig.png': _PNG_B64},
        )

    def test_preview_shows_reuse_button_on_later_questions_only(self):
        s = self._session()
        self.client.force_login(self.teacher)
        html = self.client.get(reverse('homework:pdf_preview', args=[s.pk])).content.decode()
        self.assertNotIn('data-reuse="0"', html)   # first question — no "previous"
        self.assertIn('data-reuse="1"', html)
        self.assertIn('reuse-image/', html)         # endpoint wired into the page

    def test_reuse_points_at_source_ref_without_copying_bytes(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('homework:pdf_reuse_image', args=[s.pk]),
            data=json.dumps({'q_idx': 1, 'source_ref': 'orig.png', 'page': 1,
                             'bbox_frac': [0.2, 0.2, 0.8, 0.6]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['ref'], 'orig.png')

        s.refresh_from_db()
        # The figure is still stored exactly once — no duplicate blob.
        self.assertEqual(list(s.extracted_images), ['orig.png'])
        # Assigned to the target question, with the source's crop origin carried.
        q1 = s.extracted_data['questions'][1]
        self.assertEqual(q1['image_ref'], 'orig.png')
        self.assertTrue(q1['has_image'])
        self.assertEqual(q1['image_page'], 1)
        self.assertEqual(q1['image_bbox_frac'], [0.2, 0.2, 0.8, 0.6])
        # First question untouched.
        self.assertEqual(s.extracted_data['questions'][0]['image_ref'], 'orig.png')

    def test_reuse_rejects_unknown_source_ref(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('homework:pdf_reuse_image', args=[s.pk]),
            data=json.dumps({'q_idx': 1, 'source_ref': 'nope.png'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_other_teacher_cannot_reuse(self):
        s = self._session()
        self.client.force_login(self.other)
        r = self.client.post(
            reverse('homework:pdf_reuse_image', args=[s.pk]),
            data=json.dumps({'q_idx': 1, 'source_ref': 'orig.png'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 404)


class SharedFigureConfirmTests(TestCase):
    """What the confirm step does with several questions on ONE figure."""

    def setUp(self):
        # Per TEST, not per class: override_settings applied to the class enters
        # once, and InMemoryStorage would then carry files between tests —
        # storage uniquifies a repeat name, so a leaked file makes the next
        # test's stored path unpredictable.
        override = override_settings(STORAGES=_IN_MEMORY_STORAGE)
        override.enable()
        self.addCleanup(override.disable)

    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.teacher = CustomUser.objects.create_user('shr', 'shr@x.com', 'pw')
        cls.teacher.roles.add(role)
        admin = CustomUser.objects.create_user('shra', 'shra@x.com', 'pw')
        cls.school = School.objects.create(name='Shared', slug='shared', admin=admin)
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.teacher, role='teacher')
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(
            name='Statistics', slug='statistics', subject=cls.subject)

    _GLOBALS = {'year_level': 7, 'subject': 'Mathematics', 'topic': 'Statistics'}

    def _session(self, images):
        session = HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1,
        )
        session.extracted_images = images
        return session

    @staticmethod
    def _q(text, ref):
        return {'question_text': text, 'question_type': 'short_answer',
                'has_image': True, 'image_ref': ref, 'validation_type': 'auto',
                'difficulty': 1, 'points': 1, 'answers': []}

    def _confirm(self, questions, session):
        return _save_homework_pdf_questions(
            questions, self._GLOBALS, self.teacher, self.school, session)

    def test_questions_sharing_a_figure_both_survive_and_share_one_file(self):
        # The whole point of "Same image as previous": a pie chart used by two
        # questions must not collapse into one row (the old image-path-only
        # dedup dropped the second), and must not cost two files in Spaces.
        session = self._session({'chart.png': _PNG_B64})
        saved = self._confirm([
            self._q('How many chose chocolate?', 'chart.png'),
            self._q('How many chose chips?', 'chart.png'),
        ], session)

        self.assertEqual(len(saved), 2)
        self.assertNotEqual(saved[0].pk, saved[1].pk)
        # Both carry the picture...
        self.assertTrue(saved[0].image)
        self.assertTrue(saved[1].image)
        # ...and it is the SAME stored file, written once.
        self.assertEqual(saved[0].image.name, saved[1].image.name)
        self.assertEqual(saved[0].image.name, 'questions/year7/statistics/chart.png')
        self.assertTrue(default_storage.exists(saved[0].image.name))
        stored = [n for n in default_storage.listdir('questions/year7/statistics')[1]]
        self.assertEqual(stored, ['chart.png'])

    def test_shared_figure_reads_back_as_the_same_bytes_for_both(self):
        session = self._session({'chart.png': _PNG_B64})
        a, b = self._confirm([
            self._q('Chocolate?', 'chart.png'),
            self._q('Chips?', 'chart.png'),
        ], session)

        with a.image.open('rb') as fh:
            first = fh.read()
        with b.image.open('rb') as fh:
            second = fh.read()
        self.assertEqual(first, second)
        self.assertEqual(base64.b64encode(first).decode(), _PNG_B64)

    def test_same_stem_with_different_figures_still_makes_separate_rows(self):
        # The regression the image-path dedup was introduced for: 79 "Name this
        # shape" questions, one per figure, must not collapse onto one row.
        session = self._session({'a.png': _PNG_B64, 'b.png': _PNG_B64})
        saved = self._confirm([
            self._q('Name this shape', 'a.png'),
            self._q('Name this shape', 'b.png'),
        ], session)

        self.assertEqual(len(saved), 2)
        self.assertNotEqual(saved[0].pk, saved[1].pk)
        self.assertNotEqual(saved[0].image.name, saved[1].image.name)
        self.assertEqual(MQ.objects.filter(question_text='Name this shape').count(), 2)

    def test_confirming_the_same_questions_twice_is_idempotent(self):
        # The recovery command re-runs a confirmed session to refill missing
        # images and must match the existing rows rather than duplicate them.
        questions = [
            self._q('Chocolate?', 'chart.png'),
            self._q('Chips?', 'chart.png'),
        ]
        first = self._confirm(questions, self._session({'chart.png': _PNG_B64}))
        second = self._confirm(questions, self._session({'chart.png': _PNG_B64}))

        self.assertEqual([q.pk for q in first], [q.pk for q in second])
        self.assertEqual(MQ.objects.filter(level=self.level).count(), 2)
        # Still one stored object — the re-run neither re-uploaded nor uniquified.
        self.assertEqual(
            default_storage.listdir('questions/year7/statistics')[1], ['chart.png'])

    def test_identical_text_and_figure_is_treated_as_one_question(self):
        # Indistinguishable to a student — the same call the text-only dedup
        # makes. Pinned so the behaviour is a decision, not a surprise.
        session = self._session({'chart.png': _PNG_B64})
        saved = self._confirm([
            self._q('Read the chart', 'chart.png'),
            self._q('Read the chart', 'chart.png'),
        ], session)

        self.assertEqual(len({q.pk for q in saved}), 1)
