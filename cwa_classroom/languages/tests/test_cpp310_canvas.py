"""
Unit tests for CPP-310: canvas config utility + stroke_data persistence.

Tests:
  test_canvas_config_per_script_type  — get_canvas_config returns correct spacing per script
  test_stroke_data_saved_to_student_answer — POST saves stroke_data, sets is_correct + points
"""
import json

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
        cfg = get_canvas_config('sinhala')
        assert cfg['line_height'] == 130
        assert cfg['descender'] == 0
        assert cfg['lines'] == 3

    def test_tamil_config(self):
        cfg = get_canvas_config('tamil')
        assert cfg['line_height'] == 120
        assert cfg['descender'] == 0
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
        resp = client.post(url, data={'stroke_data': json.dumps(stroke_payload)})

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
        client.post(url, data={'stroke_data': json.dumps(payload2)})

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
