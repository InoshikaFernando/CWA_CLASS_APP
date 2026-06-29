"""
Unit tests for CPP-313: Spelling exercises (MCQ + Type-the-word).

Tests:
  TestSpellingNfcNormalization       — NFD-encoded input matches NFC stored prompt
  TestSpellingCaseInsensitiveLatin   — "CAT" matches "cat" for Latin script
  TestSpellingExactMatchNonLatin     — wrong Sinhala → is_correct=False
  TestSpellingTypeGetRendersTemplate — GET returns 200 + type area markup
  TestSpellingTypeCorrectAnswer      — POST correct → is_correct=True, full points
  TestSpellingTypeIncorrectAnswer    — POST wrong → is_correct=False, 0 points, correct_spelling in response
  TestSpellingTypeRetryUpdates       — second POST overwrites first
  TestSpellingMcqGetRendersTemplate  — GET returns 200 + answer-grid markup
  TestSpellingMcqCorrectAnswer       — POST correct answer_id → is_correct=True
  TestSpellingMcqIncorrectAnswer     — POST wrong answer_id → is_correct=False, reveals correct
  TestSpellingMcqRetryUpdates        — second POST overwrites first
  TestSpellingMcqInvalidAnswerId     — garbage id → 200, is_correct=False
  TestSpellingLangAttribute          — GET response contains lang attribute for non-Latin
  TestPhonicsRegressionAfter313      — phonics MCQ still dispatches after new routing
"""
import unicodedata

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


pytestmark = pytest.mark.cpp313


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username, password='TestPass313!'):
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


def _make_language(suffix, script_type='latin'):
    lang, _ = Language.objects.get_or_create(
        code=f'en{suffix}' if script_type == 'latin' else f'si{suffix}',
        defaults={
            'name': f'TestLang{suffix}',
            'script_type': script_type,
            'is_active': True,
            'order': 99,
        },
    )
    return lang


def _make_spelling_type_exercise(suffix, prompt='cat', lang_code=None, script_type='latin'):
    lang = _make_language(suffix, script_type) if lang_code is None else Language.objects.get(code=lang_code)
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'Spelling {suffix}',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    exercise = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.SPELLING_TYPE,
        prompt=prompt,
        points=5,
        is_active=True,
    )
    return exercise


def _make_spelling_mcq_exercise(suffix, prompt='cat', script_type='latin'):
    lang = _make_language(suffix, script_type)
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'SpellingMcq {suffix}',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    exercise = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.SPELLING_MCQ,
        prompt=prompt,
        points=3,
        is_active=True,
    )
    correct = LanguageAnswer.objects.create(
        exercise=exercise, answer_text=prompt, is_correct=True, display_order=0,
    )
    wrong1 = LanguageAnswer.objects.create(
        exercise=exercise, answer_text=prompt + 'x', is_correct=False, display_order=1,
    )
    wrong2 = LanguageAnswer.objects.create(
        exercise=exercise, answer_text=prompt + 'xx', is_correct=False, display_order=2,
    )
    wrong3 = LanguageAnswer.objects.create(
        exercise=exercise, answer_text=prompt + 'y', is_correct=False, display_order=3,
    )
    return exercise, correct, [wrong1, wrong2, wrong3]


# ---------------------------------------------------------------------------
# Test 1: NFC normalisation — NFD-encoded Sinhala matches NFC prompt
# ---------------------------------------------------------------------------

class TestSpellingNfcNormalization:
    """POST with NFD-encoded Sinhala should still match the NFC prompt."""

    @pytest.mark.django_db
    def test_nfd_sinhala_matches_nfc_prompt(self):
        # Sinhala letter "ක" (U+0D9A) precomposed NFC
        nfc_word = unicodedata.normalize('NFC', 'ක')
        nfd_word = unicodedata.normalize('NFD', nfc_word)

        student, pwd = _make_student('stu_nfc_313a')
        exercise = _make_spelling_type_exercise('313a', prompt=nfc_word, script_type='sinhala')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': nfd_word})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['is_correct'] is True

    @pytest.mark.django_db
    def test_nfc_sinhala_matches_nfc_prompt(self):
        nfc_word = unicodedata.normalize('NFC', 'ක')
        student, pwd = _make_student('stu_nfc_313b')
        exercise = _make_spelling_type_exercise('313b', prompt=nfc_word, script_type='sinhala')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': nfc_word})
        data = resp.json()
        assert data['is_correct'] is True


# ---------------------------------------------------------------------------
# Test 2: Case-insensitive comparison for Latin script
# ---------------------------------------------------------------------------

class TestSpellingCaseInsensitiveLatin:
    """Upper-case input should match lower-case prompt for Latin script."""

    @pytest.mark.django_db
    def test_uppercase_matches_lowercase_prompt(self):
        student, pwd = _make_student('stu_case_313c')
        exercise = _make_spelling_type_exercise('313c', prompt='cat')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': 'CAT'})
        data = resp.json()
        assert data['is_correct'] is True
        assert int(data['points_earned']) == exercise.points

    @pytest.mark.django_db
    def test_mixed_case_matches(self):
        student, pwd = _make_student('stu_case_313d')
        exercise = _make_spelling_type_exercise('313d', prompt='Elephant')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': 'eLEPHANT'})
        data = resp.json()
        assert data['is_correct'] is True

    @pytest.mark.django_db
    def test_wrong_latin_word_is_incorrect(self):
        student, pwd = _make_student('stu_case_313e')
        exercise = _make_spelling_type_exercise('313e', prompt='cat')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': 'dog'})
        data = resp.json()
        assert data['is_correct'] is False
        assert int(data['points_earned']) == 0


# ---------------------------------------------------------------------------
# Test 3: Exact match required for non-Latin script
# ---------------------------------------------------------------------------

class TestSpellingExactMatchNonLatin:
    """Wrong Sinhala spelling must return is_correct=False (no case folding)."""

    @pytest.mark.django_db
    def test_wrong_sinhala_is_incorrect(self):
        student, pwd = _make_student('stu_exact_313f')
        exercise = _make_spelling_type_exercise('313f', prompt='ක', script_type='sinhala')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': 'ග'})  # different letter
        data = resp.json()
        assert data['is_correct'] is False
        assert int(data['points_earned']) == 0

    @pytest.mark.django_db
    def test_wrong_sinhala_response_includes_correct_spelling(self):
        student, pwd = _make_student('stu_exact_313g')
        exercise = _make_spelling_type_exercise('313g', prompt='ක', script_type='sinhala')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': 'ග'})
        data = resp.json()
        assert data['correct_spelling'] == 'ක'


# ---------------------------------------------------------------------------
# Test 4: GET renders spelling_type template
# ---------------------------------------------------------------------------

class TestSpellingTypeGetRendersTemplate:

    @pytest.mark.django_db
    def test_get_returns_200_with_type_area(self):
        student, pwd = _make_student('stu_get_313h')
        exercise = _make_spelling_type_exercise('313h')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert resp.status_code == 200
        assert b'type-area' in resp.content
        assert b'spelling-input' in resp.content

    @pytest.mark.django_db
    def test_get_contains_play_btn(self):
        student, pwd = _make_student('stu_get_313i')
        exercise = _make_spelling_type_exercise('313i')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert b'play-btn' in resp.content
        assert b'data-tts-lang' in resp.content

    @pytest.mark.django_db
    def test_get_contains_tts_text_with_prompt(self):
        student, pwd = _make_student('stu_get_313j')
        exercise = _make_spelling_type_exercise('313j', prompt='banana')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert b'banana' in resp.content


# ---------------------------------------------------------------------------
# Test 5: POST correct spelling
# ---------------------------------------------------------------------------

class TestSpellingTypeCorrectAnswer:

    @pytest.mark.django_db
    def test_correct_answer_is_correct_true_and_full_points(self):
        student, pwd = _make_student('stu_correct_313k')
        exercise = _make_spelling_type_exercise('313k', prompt='apple')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': 'apple'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['is_correct'] is True
        assert int(data['points_earned']) == exercise.points

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is True
        assert int(ans.points_earned) == exercise.points

    @pytest.mark.django_db
    def test_correct_answer_score_is_100(self):
        student, pwd = _make_student('stu_correct_313l')
        exercise = _make_spelling_type_exercise('313l', prompt='mango')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        client.post(url, data={'answer': 'mango'})
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.score == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Test 6: POST incorrect spelling
# ---------------------------------------------------------------------------

class TestSpellingTypeIncorrectAnswer:

    @pytest.mark.django_db
    def test_wrong_answer_is_correct_false_zero_points(self):
        student, pwd = _make_student('stu_wrong_313m')
        exercise = _make_spelling_type_exercise('313m', prompt='orange')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': 'ornage'})
        data = resp.json()
        assert data['is_correct'] is False
        assert int(data['points_earned']) == 0

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is False
        assert ans.points_earned == 0
        assert ans.score == pytest.approx(0.0)

    @pytest.mark.django_db
    def test_wrong_answer_response_includes_correct_spelling(self):
        student, pwd = _make_student('stu_wrong_313n')
        exercise = _make_spelling_type_exercise('313n', prompt='grape')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'answer': 'graep'})
        data = resp.json()
        assert data['correct_spelling'] == 'grape'


# ---------------------------------------------------------------------------
# Test 7: Retry (second POST) overwrites first
# ---------------------------------------------------------------------------

class TestSpellingTypeRetryUpdates:

    @pytest.mark.django_db
    def test_second_post_overwrites_first(self):
        student, pwd = _make_student('stu_retry_313o')
        exercise = _make_spelling_type_exercise('313o', prompt='melon')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        client.post(url, data={'answer': 'melno'})   # wrong
        client.post(url, data={'answer': 'melon'})   # correct

        assert LanguageStudentAnswer.objects.filter(student=student, exercise=exercise).count() == 1
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is True
        assert ans.text_answer == 'melon'


# ---------------------------------------------------------------------------
# Test 8: GET renders spelling_mcq template
# ---------------------------------------------------------------------------

class TestSpellingMcqGetRendersTemplate:

    @pytest.mark.django_db
    def test_get_returns_200_with_answer_grid(self):
        student, pwd = _make_student('stu_mcqget_313p')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313p')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert resp.status_code == 200
        assert b'answer-grid' in resp.content
        assert b'answer-btn' in resp.content

    @pytest.mark.django_db
    def test_get_contains_all_4_answers(self):
        student, pwd = _make_student('stu_mcqget_313q')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313q', prompt='kite')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        for ans in [correct] + wrongs:
            assert ans.answer_text.encode() in resp.content

    @pytest.mark.django_db
    def test_get_contains_play_btn_and_tts_attrs(self):
        student, pwd = _make_student('stu_mcqget_313r')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313r')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert b'play-btn' in resp.content
        assert b'data-tts-lang' in resp.content


# ---------------------------------------------------------------------------
# Test 9: POST correct MCQ answer
# ---------------------------------------------------------------------------

class TestSpellingMcqCorrectAnswer:

    @pytest.mark.django_db
    def test_correct_answer_is_correct_true_full_points(self):
        student, pwd = _make_student('stu_mcqcorrect_313s')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313s')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'selected_answer_id': str(correct.pk)})
        data = resp.json()

        assert data['success'] is True
        assert data['is_correct'] is True
        assert int(data['points_earned']) == exercise.points

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is True
        assert ans.score == pytest.approx(100.0)

    @pytest.mark.django_db
    def test_correct_answer_response_has_correct_answer_id(self):
        student, pwd = _make_student('stu_mcqcorrect_313t')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313t')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'selected_answer_id': str(correct.pk)})
        data = resp.json()
        assert data['correct_answer_id'] == correct.pk


# ---------------------------------------------------------------------------
# Test 10: POST incorrect MCQ answer
# ---------------------------------------------------------------------------

class TestSpellingMcqIncorrectAnswer:

    @pytest.mark.django_db
    def test_wrong_answer_is_correct_false_zero_points(self):
        student, pwd = _make_student('stu_mcqwrong_313u')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313u')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'selected_answer_id': str(wrongs[0].pk)})
        data = resp.json()

        assert data['is_correct'] is False
        assert int(data['points_earned']) == 0

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is False
        assert ans.score == pytest.approx(0.0)

    @pytest.mark.django_db
    def test_wrong_answer_response_reveals_correct(self):
        student, pwd = _make_student('stu_mcqwrong_313v')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313v', prompt='fish')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'selected_answer_id': str(wrongs[0].pk)})
        data = resp.json()

        assert data['correct_answer_id'] == correct.pk
        assert data['correct_answer_text'] == 'fish'


# ---------------------------------------------------------------------------
# Test 11: MCQ retry overwrites DB record
# ---------------------------------------------------------------------------

class TestSpellingMcqRetryUpdates:

    @pytest.mark.django_db
    def test_second_post_overwrites_first(self):
        student, pwd = _make_student('stu_mcqretry_313w')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313w')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        client.post(url, data={'selected_answer_id': str(wrongs[0].pk)})
        client.post(url, data={'selected_answer_id': str(correct.pk)})

        assert LanguageStudentAnswer.objects.filter(student=student, exercise=exercise).count() == 1
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is True
        assert ans.selected_answer_id == correct.pk


# ---------------------------------------------------------------------------
# Test 12: Invalid MCQ answer id
# ---------------------------------------------------------------------------

class TestSpellingMcqInvalidAnswerId:

    @pytest.mark.django_db
    def test_garbage_id_does_not_crash(self):
        student, pwd = _make_student('stu_mcqinvalid_313x')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313x')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'selected_answer_id': 'not-a-number'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is False

    @pytest.mark.django_db
    def test_missing_id_does_not_crash(self):
        student, pwd = _make_student('stu_mcqinvalid_313y')
        exercise, correct, wrongs = _make_spelling_mcq_exercise('313y')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={})
        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is False


# ---------------------------------------------------------------------------
# Test 13: lang attribute present for non-Latin input
# ---------------------------------------------------------------------------

class TestSpellingLangAttribute:

    @pytest.mark.django_db
    def test_spelling_type_has_lang_attr_on_input(self):
        student, pwd = _make_student('stu_lang_313z')
        # Sinhala language
        lang = _make_language('313z', script_type='sinhala')
        lang.code = 'si313z'
        lang.save()
        topic, _ = LanguageTopic.objects.get_or_create(
            language=lang, name='SpellingLang313z',
            defaults={'order': 1, 'is_active': True},
        )
        level, _ = LanguageTopicLevel.objects.get_or_create(
            topic=topic, level_choice=LanguageTopicLevel.BEGINNER,
        )
        exercise = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='ක',
            points=3,
            is_active=True,
        )

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert resp.status_code == 200
        # lang attr should match language code
        assert lang.code.encode() in resp.content

    @pytest.mark.django_db
    def test_spelling_mcq_answer_btns_have_lang_attr(self):
        student, pwd = _make_student('stu_lang_313aa')
        lang = _make_language('313aa', script_type='sinhala')
        topic, _ = LanguageTopic.objects.get_or_create(
            language=lang, name='SpellingMcqLang313aa',
            defaults={'order': 1, 'is_active': True},
        )
        level, _ = LanguageTopicLevel.objects.get_or_create(
            topic=topic, level_choice=LanguageTopicLevel.BEGINNER,
        )
        exercise = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_MCQ,
            prompt='ක',
            points=3,
            is_active=True,
        )
        LanguageAnswer.objects.create(exercise=exercise, answer_text='ක', is_correct=True, display_order=0)
        LanguageAnswer.objects.create(exercise=exercise, answer_text='ග', is_correct=False, display_order=1)
        LanguageAnswer.objects.create(exercise=exercise, answer_text='ට', is_correct=False, display_order=2)
        LanguageAnswer.objects.create(exercise=exercise, answer_text='ත', is_correct=False, display_order=3)

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)

        assert resp.status_code == 200
        assert b'answer-btn' in resp.content
        assert lang.code.encode() in resp.content


# ---------------------------------------------------------------------------
# Test 14: Regression — phonics MCQ still dispatches after new routing
# ---------------------------------------------------------------------------

class TestPhonicsRegressionAfter313:

    @pytest.mark.django_db
    def test_phonics_mcq_still_works(self):
        student, pwd = _make_student('stu_phonics_reg_313bb')
        lang, _ = Language.objects.get_or_create(
            code='en313bb',
            defaults={'name': 'English313bb', 'script_type': 'latin', 'is_active': True, 'order': 99},
        )
        topic, _ = LanguageTopic.objects.get_or_create(
            language=lang, name='Phonics313bb',
            defaults={'order': 1, 'is_active': True},
        )
        level, _ = LanguageTopicLevel.objects.get_or_create(
            topic=topic, level_choice=LanguageTopicLevel.BEGINNER,
        )
        exercise = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.PHONICS_MCQ,
            prompt='A',
            points=3,
            is_active=True,
        )
        correct = LanguageAnswer.objects.create(exercise=exercise, answer_text='A', is_correct=True, display_order=0)
        LanguageAnswer.objects.create(exercise=exercise, answer_text='B', is_correct=False, display_order=1)
        LanguageAnswer.objects.create(exercise=exercise, answer_text='C', is_correct=False, display_order=2)
        LanguageAnswer.objects.create(exercise=exercise, answer_text='D', is_correct=False, display_order=3)

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp_get = client.get(url)
        assert resp_get.status_code == 200
        assert b'answer-grid' in resp_get.content

        resp_post = client.post(url, data={'selected_answer_id': str(correct.pk)})
        data = resp_post.json()
        assert data['is_correct'] is True
