"""Integration tests for the worksheet "Adjust image" crop tool + the
image-ref preservation fix (previously the preview POST wiped every question
image because the template had no hidden image_ref field).
"""
import base64
import json

import fitz
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School

from worksheets.models import WorksheetUploadSession


def _pdf_bytes():
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(120, 150, 280, 260), fill=(0.6, 0.6, 0.6))
    data = doc.tobytes()
    doc.close()
    return data


_PNG_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9'
    'awAAAABJRU5ErkJggg=='
)


class WorksheetAdjustImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(name='teacher', defaults={'display_name': 'Teacher'})
        cls.teacher = CustomUser.objects.create_user('wt1', 'wt1@x.com', 'pw')
        cls.teacher.roles.add(role)
        admin = CustomUser.objects.create_user('wa', 'wa@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='ws', admin=admin)

    def _session(self):
        s = WorksheetUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='w.pdf',
            status=WorksheetUploadSession.STATUS_READY, page_count=1, is_confirmed=False,
            worksheet_name='WS',
            extracted_data={'year_level': 5, 'questions': [{
                'question_text': 'Area?', 'question_type': 'multiple_choice', 'include': True,
                'has_image': True, 'image_ref': 'orig.png', 'page_num': 1,
                'image_bbox_frac': [0.2, 0.2, 0.8, 0.6], 'difficulty': 1, 'points': 1,
            }]},
            extracted_images={'orig.png': _PNG_B64},
        )
        s.pdf_file.save('w.pdf', ContentFile(_pdf_bytes()), save=True)
        return s

    def test_preview_renders_adjust_control_and_modal(self):
        s = self._session()
        self.client.force_login(self.teacher)
        html = self.client.get(reverse('worksheets:preview', args=[s.pk])).content.decode()
        self.assertIn('data-adjust="0"', html)
        self.assertIn('id="adjust-modal"', html)
        self.assertIn('id="img-ref-0"', html)      # the hidden field that fixes the wipe bug

    def test_recrop_updates_session(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('worksheets:pdf_recrop', args=[s.pk]),
            data=json.dumps({'q_idx': 0, 'page': 1, 'box': [0.25, 0.25, 0.75, 0.6]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        ref = r.json()['ref']
        s.refresh_from_db()
        self.assertEqual(s.extracted_data['questions'][0]['image_ref'], ref)

    def test_preview_post_preserves_image_ref(self):
        """The hidden image_ref field must survive a preview save (regression:
        images were silently wiped when the field was absent)."""
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.post(reverse('worksheets:preview', args=[s.pk]), data={
            'worksheet_name': 'WS', 'year_level': '5',
            'q_0_include': 'on', 'q_0_text': 'Area?', 'q_0_type': 'multiple_choice',
            'q_0_difficulty': '1', 'q_0_points': '1',
            'q_0_image_ref': 'orig.png',
        })
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.extracted_data['questions'][0]['image_ref'], 'orig.png')


class WorksheetSkippedPagesNoticeTests(WorksheetAdjustImageTests):
    """The worksheet preview reports skipped answer sheets / keys too."""

    def test_preview_names_the_skipped_pages(self):
        s = self._session()
        data = s.extracted_data
        data['skipped_pages'] = [{'page': 1, 'reason': 'answer_sheet'}]
        s.extracted_data = data
        s.save(update_fields=['extracted_data'])

        self.client.force_login(self.teacher)
        html = self.client.get(reverse('worksheets:preview', args=[s.pk])).content.decode()

        self.assertIn('Skipped 1 page', html)
        self.assertIn('page 1 (multiple-choice answer sheet)', html)
