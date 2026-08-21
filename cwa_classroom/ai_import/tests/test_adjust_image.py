"""Integration tests for the ai_import "Adjust image" crop tool through the real
stack (superuser bypasses the module gate). Covers preview rendering, the
page-image + recrop endpoints, and session update.
"""
import base64
import json

import fitz
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import School

from ai_import.models import AIImportSession


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


class AIImportAdjustImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser('sup', 'sup@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='ais', admin=cls.user)

    def _session(self):
        s = AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='a.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 5, 'subject': 'Mathematics', 'strand': '', 'topic': '',
                'questions': [{
                    'question_text': 'Area?', 'question_type': 'multiple_choice',
                    'image_ref': 'page1_figure1.png', 'image_page': 1,
                    'image_bbox_frac': [0.2, 0.2, 0.8, 0.6],
                }],
            },
            extracted_images={'page1_figure1.png': _PNG_B64},
        )
        s.pdf_file.save('a.pdf', ContentFile(_pdf_bytes()), save=True)
        return s

    def test_preview_renders_adjust_control_and_modal(self):
        s = self._session()
        self.client.force_login(self.user)
        html = self.client.get(reverse('ai_import:preview', args=[s.pk])).content.decode()
        self.assertIn('data-adjust="0"', html)
        self.assertIn('id="adjust-modal"', html)
        self.assertIn('id="img-ref-0"', html)

    def test_page_image_and_recrop(self):
        s = self._session()
        self.client.force_login(self.user)
        pr = self.client.get(reverse('ai_import:pdf_page_image', args=[s.pk]) + '?page=1')
        self.assertEqual(pr.status_code, 200)
        self.assertEqual(base64.b64decode(pr.json()['image_b64'])[:8], b'\x89PNG\r\n\x1a\n')

        rr = self.client.post(
            reverse('ai_import:pdf_recrop', args=[s.pk]),
            data=json.dumps({'q_idx': 0, 'page': 1, 'box': [0.25, 0.25, 0.75, 0.6]}),
            content_type='application/json',
        )
        self.assertEqual(rr.status_code, 200)
        ref = rr.json()['ref']
        s.refresh_from_db()
        self.assertIn(ref, s.extracted_images)
        self.assertEqual(s.extracted_data['questions'][0]['image_ref'], ref)


class AIImportAdjustImageJsonErrorTests(AIImportAdjustImageTests):
    """Guard rejections on the crop endpoints come back as JSON, not as the HTML
    login / tier-select page the modal choked on.
    """

    def test_signed_out_recrop_returns_json_403(self):
        s = self._session()
        r = self.client.post(
            reverse('ai_import:pdf_recrop', args=[s.pk]),
            data=json.dumps({'q_idx': 0, 'page': 1, 'box': [0.25, 0.25, 0.75, 0.6]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertIn('sign-in', r.json()['error'].lower())

    def test_signed_out_page_image_returns_json_403(self):
        s = self._session()
        r = self.client.get(reverse('ai_import:pdf_page_image', args=[s.pk]) + '?page=1')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r['Content-Type'], 'application/json')
