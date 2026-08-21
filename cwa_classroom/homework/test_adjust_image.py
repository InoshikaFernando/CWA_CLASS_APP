"""Integration tests for the homework "Adjust image" crop tool through the real
auth / CBV / template stack: the preview page renders the control + modal, the
page-image endpoint serves a page, and re-crop updates the session. Ownership is
enforced.
"""
import base64
import json

import fitz
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher

from .models import HomeworkUploadSession


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


class AdjustImageTests(TestCase):
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
        s = HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='t.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            extracted_data={'questions': [{
                'question_text': 'Area of the rectangle?', 'question_type': 'multiple_choice',
                'has_image': True, 'image_ref': 'orig.png', 'page_num': 1,
                'image_bbox_frac': [0.2, 0.2, 0.8, 0.6],
            }]},
            extracted_images={'orig.png': _PNG_B64},
        )
        s.pdf_file.save('t.pdf', ContentFile(_pdf_bytes()), save=True)
        return s

    def test_preview_renders_adjust_control_and_modal(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('homework:pdf_preview', args=[s.pk]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('data-adjust="0"', html)        # per-question trigger
        self.assertIn('id="adjust-modal"', html)       # the crop modal
        self.assertIn('page-image/', html)             # endpoint wired into modal
        self.assertIn('recrop/', html)

    def test_page_image_endpoint(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('homework:pdf_page_image', args=[s.pk]) + '?page=1')
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(round(j['page_w']), 400)
        self.assertEqual(base64.b64decode(j['image_b64'])[:8], b'\x89PNG\r\n\x1a\n')

    def test_recrop_updates_session_image(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('homework:pdf_recrop', args=[s.pk]),
            data=json.dumps({'q_idx': 0, 'page': 1, 'box': [0.25, 0.25, 0.75, 0.6]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        ref = r.json()['ref']
        s.refresh_from_db()
        self.assertIn(ref, s.extracted_images)
        self.assertEqual(s.extracted_data['questions'][0]['image_ref'], ref)

    def test_other_teacher_cannot_recrop(self):
        s = self._session()
        self.client.force_login(self.other)
        r = self.client.post(
            reverse('homework:pdf_recrop', args=[s.pk]),
            data=json.dumps({'q_idx': 0, 'page': 1, 'box': [0.2, 0.2, 0.7, 0.6]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 404)


class AdjustImageJsonErrorTests(AdjustImageTests):
    """The crop modal only speaks JSON, so its endpoints must never answer with
    Django's HTML login page or HTML 404 — that reached the teacher as the
    useless "Unexpected token '<', "<!DOCTYPE "... is not valid JSON".
    """

    def _recrop(self, session):
        return self.client.post(
            reverse('homework:pdf_recrop', args=[session.pk]),
            data=json.dumps({'q_idx': 0, 'page': 1, 'box': [0.2, 0.2, 0.7, 0.6]}),
            content_type='application/json',
        )

    def test_signed_out_recrop_returns_json_not_a_login_redirect(self):
        s = self._session()
        r = self._recrop(s)                      # no force_login: session expired
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertIn('sign-in', r.json()['error'].lower())

    def test_missing_session_returns_json_not_an_html_404(self):
        self.client.force_login(self.other)
        s = self._session()
        r = self._recrop(s)                      # not this teacher's upload
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertIn('error', r.json())

    def test_page_image_endpoint_is_json_when_signed_out(self):
        s = self._session()
        r = self.client.get(reverse('homework:pdf_page_image', args=[s.pk]) + '?page=1')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r['Content-Type'], 'application/json')

    def test_modal_parses_replies_defensively(self):
        """The modal must read responses through the guarded reader, not a bare
        r.json() that blows up on an HTML page."""
        s = self._session()
        self.client.force_login(self.teacher)
        html = self.client.get(reverse('homework:pdf_preview', args=[s.pk])).content.decode()
        self.assertIn('async function readJson(r)', html)
        # both modal calls — loading a page and applying the crop
        self.assertGreaterEqual(html.count('await readJson(r)'), 2)
