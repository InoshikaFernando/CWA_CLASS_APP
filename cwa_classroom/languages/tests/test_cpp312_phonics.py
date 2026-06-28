"""
Unit tests for CPP-312: Phonics MCQ exercises with audio playback.

Tests:
  test_tts_lang_code_mapping          — pure function, no DB
  test_audio_file_field_exists        — model field introspection
  test_get_renders_phonics_template   — GET returns 200 + phonics markup
  test_phonics_correct_answer_saved   — POST correct → is_correct=True, full points
  test_phonics_incorrect_answer_saved — POST wrong → is_correct=False, 0 points
  test_phonics_invalid_answer_id      — POST garbage → is_correct=False, no crash
  test_response_includes_correct_id   — POST wrong → response reveals correct_answer_id
  test_phonics_retry_updates_answer   — second POST overwrites first
  test_letter_writing_still_works     — regression: CPP-311 view still dispatches correctly
"""
import json

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language,
    LanguageAnswer,
    LanguageExercise,
    LanguageStudentAnswer,
    LanguageTopic,
    LanguageTopicLevel,
)
from languages.utils import TTS_LANG_MAP, get_tts_lang_code


pytestmark = pytest.mark.cpp312


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username, password='TestPass312!'):
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


def _make_phonics_exercise(suffix='312', lang_code='en'):
    lang, _ = Language.objects.get_or_create(
        code=lang_code if suffix == '312' else f'{lang_code}{suffix}',
        defaults={
            'name': f'English{suffix}',
            'script_type': 'latin',
            'is_active': True,
            'order': 99,
        },
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'Phonics {suffix}',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    exercise = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.PHONICS_MCQ,
        prompt='A',
        points=3,
        is_active=True,
    )
    correct = LanguageAnswer.objects.create(
        exercise=exercise,
        answer_text='A',
        is_correct=True,
        display_order=0,
    )
    wrong1 = LanguageAnswer.objects.create(
        exercise=exercise,
        answer_text='B',
        is_correct=False,
        display_order=1,
    )
    wrong2 = LanguageAnswer.objects.create(
        exercise=exercise,
        answer_text='C',
        is_correct=False,
        display_order=2,
    )
    wrong3 = LanguageAnswer.objects.create(
        exercise=exercise,
        answer_text='D',
        is_correct=False,
        display_order=3,
    )
    return exercise, correct, [wrong1, wrong2, wrong3]


# ---------------------------------------------------------------------------
# Test 1: TTS lang code mapping — pure function
# ---------------------------------------------------------------------------

class TestTtsLangCodeMapping:

    def test_english_maps_to_en_nz(self):
        assert get_tts_lang_code('en') == 'en-NZ'

    def test_sinhala_maps_to_si_lk(self):
        assert get_tts_lang_code('si') == 'si-LK'

    def test_tamil_maps_to_ta_in(self):
        assert get_tts_lang_code('ta') == 'ta-IN'

    def test_unknown_defaults_to_en_nz(self):
        assert get_tts_lang_code('xx') == 'en-NZ'

    def test_all_mapped_codes_are_bcp47(self):
        for code, bcp47 in TTS_LANG_MAP.items():
            assert '-' in bcp47, f'{code} → {bcp47} is not a BCP-47 tag'


# ---------------------------------------------------------------------------
# Test 2: audio_file field exists on model
# ---------------------------------------------------------------------------

class TestAudioFileField:

    def test_audio_file_field_exists(self):
        field = LanguageExercise._meta.get_field('audio_file')
        assert field is not None
        assert field.blank is True

    def test_audio_file_upload_to(self):
        field = LanguageExercise._meta.get_field('audio_file')
        assert field.upload_to == 'languages/audio/'


# ---------------------------------------------------------------------------
# Test 3: GET renders phonics template
# ---------------------------------------------------------------------------

class TestGetRendersPhonicsMcqTemplate:

    @pytest.mark.django_db
    def test_get_returns_200_with_play_btn(self):
        student, pwd = _make_student('stu_get_312a')
        exercise, correct, wrongs = _make_phonics_exercise('312a')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert resp.status_code == 200
        assert b'play-btn' in resp.content
        assert b'answer-grid' in resp.content

    @pytest.mark.django_db
    def test_get_contains_all_4_answers(self):
        student, pwd = _make_student('stu_get_312b')
        exercise, correct, wrongs = _make_phonics_exercise('312b')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert resp.status_code == 200
        for ans in [correct] + wrongs:
            assert ans.answer_text.encode() in resp.content

    @pytest.mark.django_db
    def test_get_contains_tts_lang_attribute(self):
        student, pwd = _make_student('stu_get_312c')
        exercise, correct, wrongs = _make_phonics_exercise('312c')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert b'data-tts-lang' in resp.content
        assert b'en-NZ' in resp.content


# ---------------------------------------------------------------------------
# Test 4: POST correct answer
# ---------------------------------------------------------------------------

class TestPhonicsCorrectAnswerSaved:

    @pytest.mark.django_db
    def test_correct_answer_is_correct_true(self):
        student, pwd = _make_student('stu_correct_312d')
        exercise, correct, wrongs = _make_phonics_exercise('312d')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.post(url, data={'selected_answer_id': str(correct.pk)})

        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['is_correct'] is True
        assert int(data['points_earned']) == exercise.points

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is True
        assert ans.selected_answer_id == correct.pk
        assert int(ans.points_earned) == exercise.points


# ---------------------------------------------------------------------------
# Test 5: POST incorrect answer
# ---------------------------------------------------------------------------

class TestPhonicsIncorrectAnswerSaved:

    @pytest.mark.django_db
    def test_wrong_answer_is_correct_false(self):
        student, pwd = _make_student('stu_wrong_312e')
        exercise, correct, wrongs = _make_phonics_exercise('312e')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.post(url, data={'selected_answer_id': str(wrongs[0].pk)})

        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is False
        assert int(data['points_earned']) == 0

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is False
        assert ans.points_earned == 0


# ---------------------------------------------------------------------------
# Test 6: POST invalid answer id
# ---------------------------------------------------------------------------

class TestPhonicsInvalidAnswerId:

    @pytest.mark.django_db
    def test_garbage_answer_id_does_not_crash(self):
        student, pwd = _make_student('stu_invalid_312f')
        exercise, correct, wrongs = _make_phonics_exercise('312f')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.post(url, data={'selected_answer_id': 'not-a-number'})

        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['is_correct'] is False

    @pytest.mark.django_db
    def test_missing_answer_id_does_not_crash(self):
        student, pwd = _make_student('stu_missing_312g')
        exercise, correct, wrongs = _make_phonics_exercise('312g')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.post(url, data={})

        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is False


# ---------------------------------------------------------------------------
# Test 7: Response includes correct_answer_id
# ---------------------------------------------------------------------------

class TestResponseIncludesCorrectAnswerId:

    @pytest.mark.django_db
    def test_wrong_answer_response_reveals_correct_id(self):
        student, pwd = _make_student('stu_reveal_312h')
        exercise, correct, wrongs = _make_phonics_exercise('312h')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.post(url, data={'selected_answer_id': str(wrongs[0].pk)})

        data = resp.json()
        assert data['correct_answer_id'] == correct.pk
        assert data['correct_answer_text'] == correct.answer_text


# ---------------------------------------------------------------------------
# Test 8: Retry updates DB answer
# ---------------------------------------------------------------------------

class TestPhonicsRetryUpdatesAnswer:

    @pytest.mark.django_db
    def test_second_post_overwrites_first(self):
        student, pwd = _make_student('stu_retry_312i')
        exercise, correct, wrongs = _make_phonics_exercise('312i')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        # First attempt — wrong
        client.post(url, data={'selected_answer_id': str(wrongs[0].pk)})
        # Second attempt — correct
        client.post(url, data={'selected_answer_id': str(correct.pk)})

        assert LanguageStudentAnswer.objects.filter(student=student, exercise=exercise).count() == 1
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is True
        assert ans.selected_answer_id == correct.pk


# ---------------------------------------------------------------------------
# Test 9: Regression — letter writing still dispatches correctly
# ---------------------------------------------------------------------------

class TestLetterWritingRegression:

    @pytest.mark.django_db
    def test_letter_writing_still_works_after_refactor(self):
        from languages.models import Language, LanguageTopic, LanguageTopicLevel, LanguageExercise

        student, pwd = _make_student('stu_lw_reg_312j')
        lang, _ = Language.objects.get_or_create(
            code='en312j',
            defaults={'name': 'English312j', 'script_type': 'latin', 'is_active': True, 'order': 99},
        )
        topic, _ = LanguageTopic.objects.get_or_create(
            language=lang, name='Alphabet 312j',
            defaults={'order': 1, 'is_active': True},
        )
        level, _ = LanguageTopicLevel.objects.get_or_create(
            topic=topic, level_choice=LanguageTopicLevel.BEGINNER,
        )
        exercise = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.LETTER_WRITING,
            prompt='A',
            points=2,
            is_active=True,
        )

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp_get = client.get(url)
        assert resp_get.status_code == 200
        assert b'drawing-layer' in resp_get.content

        stroke = json.dumps({'version': '5.3.1', 'objects': [{'type': 'path'}]})
        resp_post = client.post(url, data={'stroke_data': stroke, 'score': '75'})
        assert resp_post.status_code == 200
        data = resp_post.json()
        assert data['success'] is True
        assert data['stars'] == 2
