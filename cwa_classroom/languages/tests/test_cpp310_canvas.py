"""
Unit tests for CPP-310: canvas config utility + stroke_data persistence.

Tests:
  test_canvas_config_per_script_type  — get_canvas_config returns correct spacing per script
  test_stroke_data_saved_to_student_answer — POST saves stroke_data, sets is_correct + points
"""
import json
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language,
    LanguageExercise,
    LanguageStudentAnswer,
    LanguageTopic,
    LanguageTopicLevel,
)
from languages.utils import DEFAULT_CONFIG, CANVAS_CONFIG, get_canvas_config


pytestmark = pytest.mark.cpp310


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username='stu310', password='TestPass310!'):
    from accounts.models import Role, UserRole
    u = CustomUser.objects.create_user(
        username=username,
        password=password,
        email=f'{username}@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT,
        defaults={'display_name': 'Student'},
    )
    UserRole.objects.get_or_create(user=u, role=role)
    return u, password


def _make_letter_exercise():
    lang, _ = Language.objects.get_or_create(
        code='en310',
        defaults={'name': 'English310', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name='Alphabet 310',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    exercise = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.LETTER_WRITING,
        prompt='A',
        points=2,
        is_active=True,
    )
    return exercise


# ---------------------------------------------------------------------------
# Test 1: canvas config per script type
# ---------------------------------------------------------------------------

class TestCanvasConfigPerScriptType:

    def test_latin_config(self):
        cfg = get_canvas_config('latin')
        assert cfg['line_height'] == 100
        assert cfg['descender'] == 30
        assert cfg['lines'] == 4

    def test_sinhala_config(self):
        # descender=36, not 0: measured against every seeded letter_writing
        # character, some (e.g. ඤ) render up to 31px below the
        # baseline -- 0 was silently clipping them against the canvas edge.
        cfg = get_canvas_config('sinhala')
        assert cfg['line_height'] == 130
        assert cfg['descender'] == 36
        assert cfg['lines'] == 3

    def test_tamil_config(self):
        # descender=39, not 0: measured max is 34px below baseline
        # (e.g. ஆ) -- same clipping bug as Sinhala.
        cfg = get_canvas_config('tamil')
        assert cfg['line_height'] == 120
        assert cfg['descender'] == 39
        assert cfg['lines'] == 3

    def test_unknown_script_returns_default(self):
        cfg = get_canvas_config('klingon')
        assert cfg == DEFAULT_CONFIG

    def test_all_configured_scripts_have_required_keys(self):
        required = {'line_height', 'descender', 'lines'}
        for script, cfg in CANVAS_CONFIG.items():
            assert required.issubset(cfg.keys()), f'{script} config missing keys'

    def test_default_config_has_required_keys(self):
        assert {'line_height', 'descender', 'lines'}.issubset(DEFAULT_CONFIG.keys())


# ---------------------------------------------------------------------------
# Test 2: stroke_data saved to LanguageStudentAnswer via POST
# ---------------------------------------------------------------------------

class TestStrokeDataSavedToStudentAnswer:

    @pytest.mark.django_db
    def test_post_with_stroke_creates_answer(self):
        student, pwd = _make_student('stu_stroke_310')
        exercise = _make_letter_exercise()

        stroke_payload = {
            'version': '5.3.1',
            'objects': [{'type': 'path', 'path': [['M', 10, 10], ['L', 50, 50]]}],
        }

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        # Use default multipart encoding — matches how FormData sends from whiteboard.js
        # CPP-392: score is server-computed from ink_image — mock the scorer,
        # this test is about stroke_data persistence, not the scoring algorithm.
        with patch('languages.views.scoring.compute_score', return_value=(90.0, 'excellent_match')):
            resp = client.post(url, data={'stroke_data': json.dumps(stroke_payload), 'ink_image': 'dummy'})

        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['is_correct'] is True

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.stroke_data == stroke_payload
        assert ans.is_correct is True
        assert ans.points_earned == exercise.points

    @pytest.mark.django_db
    def test_post_empty_canvas_is_not_correct(self):
        student, pwd = _make_student('stu_empty_310')
        exercise = _make_letter_exercise()

        empty_payload = {'version': '5.3.1', 'objects': []}

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.post(url, data={'stroke_data': json.dumps(empty_payload)})

        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is False

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is False
        assert ans.points_earned == 0

    @pytest.mark.django_db
    def test_post_invalid_json_does_not_crash(self):
        student, pwd = _make_student('stu_invalid_310')
        exercise = _make_letter_exercise()

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.post(url, data={'stroke_data': 'not-valid-json{{{{'})

        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is False

    @pytest.mark.django_db
    def test_post_updates_existing_answer(self):
        """Second submit overwrites the first."""
        student, pwd = _make_student('stu_update_310')
        exercise = _make_letter_exercise()

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        # First submit — empty
        client.post(url, data={'stroke_data': json.dumps({'objects': []})})

        # Second submit — with strokes
        payload2 = {'version': '5.3.1', 'objects': [{'type': 'path'}]}
        with patch('languages.views.scoring.compute_score', return_value=(90.0, 'excellent_match')):
            client.post(url, data={'stroke_data': json.dumps(payload2), 'ink_image': 'dummy'})

        assert LanguageStudentAnswer.objects.filter(student=student, exercise=exercise).count() == 1
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is True

    @pytest.mark.django_db
    def test_get_renders_template(self):
        student, pwd = _make_student('stu_get_310')
        exercise = _make_letter_exercise()

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert resp.status_code == 200
        assert b'drawing-layer' in resp.content
        assert b'whiteboard-wrapper' in resp.content

    @pytest.mark.django_db
    def test_unauthenticated_redirects_to_login(self):
        exercise = _make_letter_exercise()

        client = Client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert resp.status_code == 302
        assert '/accounts/login' in resp['Location']


# ---------------------------------------------------------------------------
# Regression: a script's 'descender' must leave enough room for every
# seeded character's actual below-baseline ink, or the glyph (and, since
# scoring.render_glyph_mask() uses this same config, the server's scoring
# template) gets silently clipped at the canvas edge. Caught via a
# screenshot of ஆ/ඤ sitting flush against the bottom of the canvas with no
# room to spare -- Sinhala and Tamil both had descender=0, which happened
# to be exactly enough for most letters and not enough for their tallest
# ones (ஆ needs 34px, ඤ needs 31px; the generic 24px TOP_PAD used as the
# only bottom margin covered neither).
# ---------------------------------------------------------------------------

class TestNoScriptClipsItsOwnSeededCharacters:

    TOP_PAD = 24  # mirrors whiteboard.js's TOP_PAD / scoring.py's TOP_PAD

    def _max_below_baseline(self, char, script_type, cfg):
        """Render at a generously tall canvas (independent of cfg['descender'],
        which is exactly the value under test) to find the *true* ink extent,
        not one already clamped by whatever margin is currently configured."""
        import numpy as np
        from PIL import Image, ImageDraw
        from languages import scoring

        w = 400
        line_height = cfg['line_height']
        h = self.TOP_PAD + line_height + 300 + self.TOP_PAD  # 300px of slack
        font_size = int(line_height * 0.9)
        base_y = self.TOP_PAD + line_height

        img = Image.new('L', (w, h), color=255)
        font = scoring._load_font(script_type, font_size)
        ImageDraw.Draw(img).text((w / 2, base_y), char, font=font, fill=0, anchor='ms')
        mask = np.asarray(img, dtype=np.uint8) < 128
        ys, _ = mask.nonzero()
        if len(ys) == 0:
            return 0
        return int(ys.max()) - base_y

    @pytest.mark.parametrize('lang_code,script_type', [('si', 'sinhala'), ('ta', 'tamil')])
    def test_every_seeded_character_fits_within_its_script_descender(self, lang_code, script_type):
        from languages.management.commands.seed_language_exercises import SEED

        cfg = CANVAS_CONFIG[script_type]
        margin = cfg['descender'] + self.TOP_PAD

        chars = set()
        for topic in SEED[lang_code]['topics']:
            chars.update(topic.get('letter_writing', []))
        assert chars, f'no letter_writing characters found for {lang_code}'

        clipped = {
            ch: needed for ch in sorted(chars)
            if (needed := self._max_below_baseline(ch, script_type, cfg)) > margin
        }
        assert not clipped, (
            f"{script_type}: characters whose ink needs more room below the "
            f"baseline than CANVAS_CONFIG['{script_type}']['descender'] "
            f"({cfg['descender']}px, {margin}px total margin) provides -- "
            f"they get silently cut off at the canvas edge on both the "
            f"student's whiteboard and the server's scoring template: "
            f"{clipped}"
        )
