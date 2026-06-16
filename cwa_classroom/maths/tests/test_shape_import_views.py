"""Tests for the shape-import teacher UI (upload → review → save).

Upload runs real OpenCV detection on a Pillow-drawn sheet; save is tested by
posting a hand-built spec directly (no image needed), including a per-shape type
correction. Permission gating is covered too. No AI calls — zero tokens.
"""
import io
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from classroom.models import Level
from maths.models import Question

User = get_user_model()


def _png():
    from PIL import Image, ImageDraw

    img = Image.new('RGB', (600, 400), 'white')
    d = ImageDraw.Draw(img)
    d.polygon([(60, 40), (140, 40), (100, 120)], outline='black', width=3)    # triangle
    d.rectangle([(220, 40), (320, 140)], outline='black', width=3)            # square
    d.ellipse([(400, 40), (500, 140)], outline='black', width=3)             # circle
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _spec():
    return {
        'target_type': 'triangle',
        'viewbox': [680, 400],
        'shapes': [
            {'id': 's0', 'type': 'circle', 'points': [[10, 10], [50, 10], [30, 50]]},
            {'id': 's1', 'type': 'circle', 'cx': 100, 'cy': 100, 'rx': 20, 'ry': 20},
        ],
    }


class ShapeImportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=8, defaults={'display_name': 'shape import fixture'},
        )
        role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        cls.teacher = User.objects.create_user(
            username='t_shape', email='t_shape@example.com', password='pw')
        cls.teacher.roles.add(role)
        cls.student = User.objects.create_user(
            username='s_shape', email='s_shape@example.com', password='pw')

    def test_non_teacher_redirected(self):
        self.client.force_login(self.student)
        resp = self.client.get(reverse('maths:shape_import'))
        self.assertEqual(resp.status_code, 302)

    def test_upload_renders_review(self):
        self.client.force_login(self.teacher)
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile('sheet.png', _png(), content_type='image/png')
        resp = self.client.post(reverse('maths:shape_import'), {
            'image': upload, 'target_type': 'triangle', 'level': str(self.level.pk),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'spec_json')
        self.assertContains(resp, 'cwa-shape')          # traced SVG rendered
        self.assertContains(resp, 'data-shape-type="triangle"')

    def test_save_creates_question_with_type_correction(self):
        self.client.force_login(self.teacher)
        before = Question.objects.filter(question_type=Question.SHAPE_SELECT).count()
        resp = self.client.post(reverse('maths:shape_import_save'), {
            'spec_json': json.dumps(_spec()),
            'level': str(self.level.pk),
            'target_type': 'triangle',
            'question_text': 'Colour all the triangles.',
            'type_s0': 'triangle',     # correct s0 from circle → triangle
            'type_s1': 'circle',
        })
        self.assertEqual(resp.status_code, 302)
        q = Question.objects.filter(question_type=Question.SHAPE_SELECT).order_by('-id').first()
        self.assertEqual(
            Question.objects.filter(question_type=Question.SHAPE_SELECT).count(), before + 1
        )
        # The correction took effect → s0 is now the (only) triangle target.
        s0 = next(s for s in q.shape_spec['shapes'] if s['id'] == 's0')
        self.assertEqual(s0['type'], 'triangle')

    def test_save_with_no_target_reshows_review(self):
        self.client.force_login(self.teacher)
        # Target square, but no shape is a square → can't save → review re-shown (200).
        resp = self.client.post(reverse('maths:shape_import_save'), {
            'spec_json': json.dumps(_spec()),
            'level': str(self.level.pk),
            'target_type': 'square',
            'type_s0': 'triangle', 'type_s1': 'circle',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "no shape of target_type")
