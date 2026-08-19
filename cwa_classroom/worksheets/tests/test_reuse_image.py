"""Tests for the worksheet "Same image as previous" reuse control — copies an
earlier question's figure onto the current question under a fresh ref, for
consecutive questions that share one diagram the extractor didn't group.
"""
import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School

from worksheets.models import WorksheetUploadSession


_PNG_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9'
    'awAAAABJRU5ErkJggg=='
)


class WorksheetReuseImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(name='teacher', defaults={'display_name': 'Teacher'})
        cls.teacher = CustomUser.objects.create_user('wrt1', 'wrt1@x.com', 'pw')
        cls.teacher.roles.add(role)
        cls.other = CustomUser.objects.create_user('wrt2', 'wrt2@x.com', 'pw')
        cls.other.roles.add(role)
        admin = CustomUser.objects.create_user('wra', 'wra@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='wrs', admin=admin)

    def _session(self):
        return WorksheetUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='w.pdf',
            status=WorksheetUploadSession.STATUS_READY, page_count=1, is_confirmed=False,
            worksheet_name='WS',
            extracted_data={'year_level': 5, 'questions': [
                {'question_text': 'Angle A?', 'question_type': 'short_answer', 'include': True,
                 'has_image': True, 'image_ref': 'orig.png', 'image_page': 1,
                 'image_bbox_frac': [0.2, 0.2, 0.8, 0.6], 'difficulty': 1, 'points': 1},
                {'question_text': 'Angle B?', 'question_type': 'short_answer', 'include': True,
                 'difficulty': 1, 'points': 1},
            ]},
            extracted_images={'orig.png': _PNG_B64},
        )

    def test_preview_shows_reuse_button_on_later_questions_only(self):
        s = self._session()
        self.client.force_login(self.teacher)
        html = self.client.get(reverse('worksheets:preview', args=[s.pk])).content.decode()
        self.assertNotIn('data-reuse="0"', html)
        self.assertIn('data-reuse="1"', html)
        self.assertIn('reuse-image/', html)

    def test_reuse_copies_image_under_fresh_ref(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('worksheets:pdf_reuse_image', args=[s.pk]),
            data=json.dumps({'q_idx': 1, 'source_ref': 'orig.png', 'page': 1,
                             'bbox_frac': [0.2, 0.2, 0.8, 0.6]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        new_ref = r.json()['ref']
        self.assertNotEqual(new_ref, 'orig.png')
        s.refresh_from_db()
        self.assertEqual(s.extracted_images[new_ref], s.extracted_images['orig.png'])
        q1 = s.extracted_data['questions'][1]
        self.assertEqual(q1['image_ref'], new_ref)
        self.assertTrue(q1['has_image'])
        self.assertEqual(q1['image_bbox_frac'], [0.2, 0.2, 0.8, 0.6])

    def test_other_teacher_cannot_reuse(self):
        s = self._session()
        self.client.force_login(self.other)
        r = self.client.post(
            reverse('worksheets:pdf_reuse_image', args=[s.pk]),
            data=json.dumps({'q_idx': 1, 'source_ref': 'orig.png'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 404)
