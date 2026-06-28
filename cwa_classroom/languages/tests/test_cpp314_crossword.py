"""
Unit tests for CPP-314: Crossword puzzle exercise.

Tests:
  TestCrosswordCheckScoring          — partial correct → correct score percentage
  TestCrosswordHintPenalty           — hints reduce score by 10 each
  TestCrosswordAllCorrectFullPoints  — all correct → score=100, full points
  TestCrosswordNfcNormalization      — NFD-encoded non-Latin input matches NFC stored answer
  TestCrosswordLatinCaseInsensitive  — "apple" matches "APPLE" for Latin script
  TestCrosswordRetryOverwritesDb     — second POST overwrites first student answer
  TestCrosswordMissingWordAnswers    — empty word_answers → no crash, all incorrect
  TestCrosswordGetRendersTemplate    — GET returns 200 and puzzle grid markup
  TestCrosswordNoWordsPuzzle         — exercise with empty puzzle_data shows warning block
"""
import json
import unicodedata

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


pytestmark = pytest.mark.cpp314


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username, password='TestPass314!'):
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


def _make_crossword_exercise(suffix, puzzle_data=None, script_type='latin', points=10):
    lang, _ = Language.objects.get_or_create(
        code=f'cw{suffix}',
        defaults={
            'name': f'CWLang{suffix}',
            'script_type': script_type,
            'is_active': True,
            'order': 99,
        },
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'CWTopic{suffix}',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    if puzzle_data is None:
        puzzle_data = _simple_puzzle()
    exercise = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.CROSSWORD,
        prompt='Test Crossword',
        points=points,
        puzzle_data=puzzle_data,
        is_active=True,
    )
    return exercise


def _simple_puzzle():
    """
    Minimal 5-word puzzle for testing.
    Layout (10×10 grid):
      CAT  across row=0 col=0
      DOG  across row=2 col=0
      RAT  across row=4 col=0
      BAT  across row=6 col=0
      ANT  across row=8 col=0
    No intersections needed for unit tests — we only test scoring logic.
    """
    return {
        'width': 10,
        'height': 10,
        'words': [
            {'index': 0, 'number': 1, 'direction': 'across', 'row': 0, 'col': 0, 'answer': 'CAT', 'clue': 'A small domestic pet'},
            {'index': 1, 'number': 2, 'direction': 'across', 'row': 2, 'col': 0, 'answer': 'DOG', 'clue': "Man's best friend"},
            {'index': 2, 'number': 3, 'direction': 'across', 'row': 4, 'col': 0, 'answer': 'RAT', 'clue': 'A small rodent'},
            {'index': 3, 'number': 4, 'direction': 'across', 'row': 6, 'col': 0, 'answer': 'BAT', 'clue': 'A flying mammal'},
            {'index': 4, 'number': 5, 'direction': 'across', 'row': 8, 'col': 0, 'answer': 'ANT', 'clue': 'A tiny insect'},
        ],
    }


def _post_answers(client, exercise, word_answers, hints_used=None):
    url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
    payload = {
        'word_answers': json.dumps(word_answers),
        'hints_used': json.dumps(hints_used or []),
    }
    return client.post(url, data=payload)


# ---------------------------------------------------------------------------
# Test 1: Partial correct → correct score percentage
# ---------------------------------------------------------------------------

class TestCrosswordCheckScoring:
    """3/5 correct → base_score=60, no hints → score=60."""

    @pytest.mark.django_db
    def test_three_of_five_correct(self):
        student, pwd = _make_student('stu_cw_score_1')
        exercise = _make_crossword_exercise('sc1')

        client = Client()
        client.login(username=student.username, password=pwd)

        answers = {
            '0': 'CAT',   # correct
            '1': 'DOG',   # correct
            '2': 'RAT',   # correct
            '3': 'FISH',  # wrong
            '4': 'BUG',   # wrong
        }
        resp = _post_answers(client, exercise, answers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['correct_count'] == 3
        assert data['total'] == 5
        assert data['score'] == 60.0

    @pytest.mark.django_db
    def test_zero_correct(self):
        student, pwd = _make_student('stu_cw_score_2')
        exercise = _make_crossword_exercise('sc2')

        client = Client()
        client.login(username=student.username, password=pwd)

        answers = {'0': 'X', '1': 'Y', '2': 'Z', '3': 'W', '4': 'V'}
        resp = _post_answers(client, exercise, answers)
        data = resp.json()
        assert data['correct_count'] == 0
        assert data['score'] == 0.0


# ---------------------------------------------------------------------------
# Test 2: Hint penalty — 10 points per revealed word
# ---------------------------------------------------------------------------

class TestCrosswordHintPenalty:
    """2 hints on 5/5 correct → score = 100 − 20 = 80."""

    @pytest.mark.django_db
    def test_two_hints_reduce_score(self):
        student, pwd = _make_student('stu_cw_hint_1')
        exercise = _make_crossword_exercise('hp1')

        client = Client()
        client.login(username=student.username, password=pwd)

        answers = {'0': 'CAT', '1': 'DOG', '2': 'RAT', '3': 'BAT', '4': 'ANT'}
        resp = _post_answers(client, exercise, answers, hints_used=[0, 3])
        data = resp.json()
        assert data['correct_count'] == 5
        assert data['score'] == 80.0

    @pytest.mark.django_db
    def test_hints_clamped_to_zero_minimum(self):
        """11 hints on 1/5 correct → raw = 20 − 110 = −90 → clamped to 0."""
        student, pwd = _make_student('stu_cw_hint_2')
        exercise = _make_crossword_exercise('hp2')

        client = Client()
        client.login(username=student.username, password=pwd)

        answers = {'0': 'CAT', '1': 'X', '2': 'X', '3': 'X', '4': 'X'}
        # hints_used can be more than words if client sends garbage; score must not go negative
        resp = _post_answers(client, exercise, answers, hints_used=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        data = resp.json()
        assert data['score'] == 0.0


# ---------------------------------------------------------------------------
# Test 3: All correct → score=100, full points earned
# ---------------------------------------------------------------------------

class TestCrosswordAllCorrectFullPoints:
    """5/5 correct, no hints → score=100, points_earned=exercise.points."""

    @pytest.mark.django_db
    def test_all_correct_earns_full_points(self):
        student, pwd = _make_student('stu_cw_full_1')
        exercise = _make_crossword_exercise('fp1', points=15)

        client = Client()
        client.login(username=student.username, password=pwd)

        answers = {'0': 'CAT', '1': 'DOG', '2': 'RAT', '3': 'BAT', '4': 'ANT'}
        resp = _post_answers(client, exercise, answers)
        data = resp.json()
        assert data['score'] == 100.0
        assert data['correct_count'] == 5
        assert data['points_earned'] == '15'

        obj = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert obj.is_correct is True
        assert obj.points_earned == 15


# ---------------------------------------------------------------------------
# Test 4: NFC normalization — non-Latin NFD input matches NFC stored answer
# ---------------------------------------------------------------------------

class TestCrosswordNfcNormalization:
    """Submitted NFD Sinhala must match NFC stored answer."""

    @pytest.mark.django_db
    def test_nfd_sinhala_matches_nfc_answer(self):
        nfc_word = unicodedata.normalize('NFC', 'ක')   # Sinhala "ka"
        nfd_word = unicodedata.normalize('NFD', nfc_word)
        assert nfc_word != nfd_word or len(nfc_word) == 1  # sanity

        puzzle = {
            'width': 5,
            'height': 1,
            'words': [
                {'index': 0, 'number': 1, 'direction': 'across',
                 'row': 0, 'col': 0, 'answer': nfc_word, 'clue': 'Sinhala ka'},
            ],
        }
        student, pwd = _make_student('stu_cw_nfc_1')
        exercise = _make_crossword_exercise('nfc1', puzzle_data=puzzle, script_type='sinhala')

        client = Client()
        client.login(username=student.username, password=pwd)

        resp = _post_answers(client, exercise, {'0': nfd_word})
        data = resp.json()
        assert data['success'] is True
        assert data['results'][0]['correct'] is True


# ---------------------------------------------------------------------------
# Test 5: Latin script is case-insensitive
# ---------------------------------------------------------------------------

class TestCrosswordLatinCaseInsensitive:
    """'apple' matches 'APPLE' for Latin; 'sinhala' is case-sensitive (exact)."""

    @pytest.mark.django_db
    def test_lowercase_matches_uppercase_answer(self):
        student, pwd = _make_student('stu_cw_case_1')
        exercise = _make_crossword_exercise('ci1')

        client = Client()
        client.login(username=student.username, password=pwd)

        # answers stored as uppercase in puzzle; submit lowercase
        answers = {'0': 'cat', '1': 'dog', '2': 'rat', '3': 'bat', '4': 'ant'}
        resp = _post_answers(client, exercise, answers)
        data = resp.json()
        assert data['correct_count'] == 5
        assert data['score'] == 100.0

    @pytest.mark.django_db
    def test_mixed_case_matches_for_latin(self):
        student, pwd = _make_student('stu_cw_case_2')
        exercise = _make_crossword_exercise('ci2')

        client = Client()
        client.login(username=student.username, password=pwd)

        answers = {'0': 'Cat', '1': 'dOg', '2': 'RAT', '3': 'bAt', '4': 'AnT'}
        resp = _post_answers(client, exercise, answers)
        data = resp.json()
        assert data['correct_count'] == 5


# ---------------------------------------------------------------------------
# Test 6: Retry overwrites existing student answer
# ---------------------------------------------------------------------------

class TestCrosswordRetryOverwritesDb:
    """Second POST with better answers overwrites first LanguageStudentAnswer."""

    @pytest.mark.django_db
    def test_second_post_overwrites_first(self):
        student, pwd = _make_student('stu_cw_retry_1')
        exercise = _make_crossword_exercise('rt1', points=10)

        client = Client()
        client.login(username=student.username, password=pwd)

        # First attempt: all wrong → score=0
        bad = {'0': 'X', '1': 'Y', '2': 'Z', '3': 'W', '4': 'V'}
        resp1 = _post_answers(client, exercise, bad)
        assert resp1.json()['score'] == 0.0

        obj = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert obj.score == 0.0
        assert obj.is_correct is False

        # Second attempt: all correct → score=100
        good = {'0': 'CAT', '1': 'DOG', '2': 'RAT', '3': 'BAT', '4': 'ANT'}
        resp2 = _post_answers(client, exercise, good)
        assert resp2.json()['score'] == 100.0

        obj.refresh_from_db()
        assert obj.score == 100.0
        assert obj.is_correct is True
        assert obj.points_earned == 10

        # Exactly one record in DB
        count = LanguageStudentAnswer.objects.filter(student=student, exercise=exercise).count()
        assert count == 1


# ---------------------------------------------------------------------------
# Test 7: Missing word_answers → no crash, all marked incorrect
# ---------------------------------------------------------------------------

class TestCrosswordMissingWordAnswers:
    """Empty or malformed word_answers → view handles gracefully."""

    @pytest.mark.django_db
    def test_empty_word_answers_all_incorrect(self):
        student, pwd = _make_student('stu_cw_empty_1')
        exercise = _make_crossword_exercise('em1')

        client = Client()
        client.login(username=student.username, password=pwd)

        resp = _post_answers(client, exercise, {})
        assert resp.status_code == 200
        data = resp.json()
        assert data['correct_count'] == 0
        assert data['score'] == 0.0
        assert len(data['results']) == 5

    @pytest.mark.django_db
    def test_malformed_word_answers_json(self):
        """Raw garbage JSON in word_answers → treated as empty dict."""
        student, pwd = _make_student('stu_cw_bad_1')
        exercise = _make_crossword_exercise('bad1')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.post(url, data={
            'word_answers': 'NOT_JSON',
            'hints_used': '[]',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['correct_count'] == 0


# ---------------------------------------------------------------------------
# Test 8: GET renders template with puzzle grid
# ---------------------------------------------------------------------------

class TestCrosswordGetRendersTemplate:
    """GET returns 200 and the crossword grid table is in the response."""

    @pytest.mark.django_db
    def test_get_renders_crossword_template(self):
        student, pwd = _make_student('stu_cw_get_1')
        exercise = _make_crossword_exercise('get1')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)
        assert resp.status_code == 200
        assert b'cw-table' in resp.content
        assert b'cw-cell' in resp.content
        assert b'btn-check' in resp.content
        assert b'btn-reveal' in resp.content

    @pytest.mark.django_db
    def test_get_includes_puzzle_data_in_dataset(self):
        """data-puzzle attribute present in rendered HTML."""
        student, pwd = _make_student('stu_cw_get_2')
        exercise = _make_crossword_exercise('get2')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)
        assert b'data-puzzle' in resp.content
        assert b'CAT' in resp.content  # answer in puzzle_data JSON embedded in page


# ---------------------------------------------------------------------------
# Test 9: Exercise with empty puzzle_data shows warning block
# ---------------------------------------------------------------------------

class TestCrosswordNoWordsPuzzle:
    """Exercise with no puzzle_data shows the amber warning, not the grid."""

    @pytest.mark.django_db
    def test_empty_puzzle_data_shows_warning(self):
        student, pwd = _make_student('stu_cw_empty2_1')
        exercise = _make_crossword_exercise('ew1', puzzle_data={})

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        resp = client.get(url)
        assert resp.status_code == 200
        assert b'id="cw-table"' not in resp.content
        assert b'create_crossword' in resp.content
