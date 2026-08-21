"""Tests for the homework "Same image as previous" reuse control.

Several consecutive questions can share ONE figure (e.g. "use the diagram below
for questions 3-6"). When the extractor doesn't group them, the teacher clicks
"Same image as previous" and the picture is copied onto the current question
under a *fresh* ref — distinct refs are essential because the confirm step dedups
image questions by their image path, so a shared ref would collapse two questions
into one.
"""
import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher

from .models import HomeworkUploadSession


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

    def test_reuse_copies_image_under_fresh_ref(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('homework:pdf_reuse_image', args=[s.pk]),
            data=json.dumps({'q_idx': 1, 'source_ref': 'orig.png', 'page': 1,
                             'bbox_frac': [0.2, 0.2, 0.8, 0.6]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        new_ref = r.json()['ref']

        # A brand-new ref, NOT the source ref (so confirm won't collapse the two).
        self.assertNotEqual(new_ref, 'orig.png')
        s.refresh_from_db()
        self.assertIn(new_ref, s.extracted_images)
        # Same bytes as the source.
        self.assertEqual(s.extracted_images[new_ref], s.extracted_images['orig.png'])
        # Assigned to the target question, with the source's crop origin carried.
        q1 = s.extracted_data['questions'][1]
        self.assertEqual(q1['image_ref'], new_ref)
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
