"""
Unit tests for CPP-348 senior tech-lead review fixes (round 2).

Covers every bug/security finding fixed in this review:
  Fix 1  — grammar_fill_blank NULL puzzle_data crash (GET + POST)
  Fix 2  — letter_writing client-score bypass (no strokes → score 0)
  Fix 3  — crossword float hints bypass hint penalty
  Fix 5  — MCQ re-submit wrong answer no longer downgrades stored correct score
  Fix 6  — _build_crossword_grid KeyError on malformed word entries
  Fix 7  — languages_index blocked for non-student roles
  Fix 8  — crossword oversized word_answers/hints_used POST size limit
  Fix 9  — grammar_fill_blank re-submit wrong answer no longer downgrades score
  Fix 10 — plugin grade_answer SPELLING_TYPE respects non-Latin script_type
  Auth   — unauthenticated GET /languages/ redirects to login
"""
import json

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language, LanguageAnswer, LanguageExercise,
    LanguageStudentAnswer, LanguageTopic, LanguageTopicLevel,
)


pytestmark = pytest.mark.cpp348


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(username, role_name):
    u = CustomUser.objects.create_user(
        username=username,
        password='CRPass348!',
        email=f'{username}@cr348.local',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=role_name, defaults={'display_name': role_name.title()})
    UserRole.objects.get_or_create(user=u, role=role)
    return u


def _make_student(username):
    return _make_user(username, Role.STUDENT)


def _make_teacher(username):
    return _make_user(username, 'teacher')


def _make_chain(suffix, script_type='latin'):
    lang, _ = Language.objects.get_or_create(
        code=f'cr{suffix}'[:10],
        defaults={'name': f'CRLang{suffix}', 'script_type': script_type, 'is_active': True, 'order': 97},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name=f'CRTopic{suffix}',
        defaults={'order': 0, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='beginner')
    return lang, topic, level


def _make_mcq_exercise(suffix, points=4):
    _, _, level = _make_chain(suffix)
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.PHONICS_MCQ,
        prompt='TestWord', points=points, is_active=True,
    )
    correct = LanguageAnswer.objects.create(exercise=ex, answer_text='right', is_correct=True, display_order=0)
    wrong   = LanguageAnswer.objects.create(exercise=ex, answer_text='wrong', is_correct=False, display_order=1)
    return ex, correct, wrong


def _make_grammar_exercise(suffix, puzzle_data_val=None):
    _, _, level = _make_chain(suffix)
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.GRAMMAR_FILL_BLANK,
        prompt='He ___ happy.', points=5, is_active=True,
        puzzle_data=puzzle_data_val,
    )
    correct = LanguageAnswer.objects.create(exercise=ex, answer_text='is', is_correct=True, display_order=0)
    wrong   = LanguageAnswer.objects.create(exercise=ex, answer_text='was', is_correct=False, display_order=1)
    return ex, correct, wrong


def _make_crossword_exercise(suffix, script_type='latin', puzzle_data=None):
    lang, _, level = _make_chain(suffix, script_type)
    if puzzle_data is None:
        puzzle_data = {
            'width': 5, 'height': 3,
            'words': [
                {'index': 0, 'number': 1, 'direction': 'across', 'row': 0, 'col': 0, 'answer': 'CAT', 'clue': 'Pet'},
                {'index': 1, 'number': 2, 'direction': 'across', 'row': 2, 'col': 0, 'answer': 'DOG', 'clue': 'Bark'},
            ],
        }
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.CROSSWORD,
        prompt='Crossword', points=10, is_active=True, puzzle_data=puzzle_data,
    )
    return ex


def _make_letter_exercise(suffix):
    _, _, level = _make_chain(suffix)
    return LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.LETTER_WRITING,
        prompt='A', points=3, is_active=True,
    )


def _make_spelling_type_exercise(suffix, script_type='latin', prompt='cat'):
    _, _, level = _make_chain(suffix, script_type)
    return LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.SPELLING_TYPE,
        prompt=prompt, points=3, is_active=True,
    )


# ---------------------------------------------------------------------------
# Auth — unauthenticated user redirected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUnauthenticatedAccess:

    def test_languages_index_redirects_anonymous(self):
        client = Client()
        resp = client.get(reverse('languages:index'))
        assert resp.status_code == 302
        assert '/accounts/login' in resp['Location']

    def test_exercise_detail_redirects_anonymous(self):
        ex = _make_letter_exercise('anon_ex')
        client = Client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})
        resp = client.get(url)
        assert resp.status_code == 302
        assert '/accounts/login' in resp['Location']


# ---------------------------------------------------------------------------
# Fix 7 — languages_index blocked for non-student (teacher) roles
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLanguagesIndexStudentRequired:

    def test_teacher_cannot_access_languages_index(self):
        teacher = _make_teacher('cr_teacher_fix7')
        client = Client()
        client.force_login(teacher)
        resp = client.get(reverse('languages:index'))
        assert resp.status_code in (302, 403), \
            f'Teacher must be blocked from /languages/ — got {resp.status_code}'

    def test_student_can_access_languages_index(self):
        student = _make_student('cr_student_fix7')
        client = Client()
        client.force_login(student)
        resp = client.get(reverse('languages:index'))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Fix 2 — letter_writing client-score bypass
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLetterWritingScoreBypass:

    def test_no_strokes_score_is_zero_despite_high_client_score(self):
        """POST score=100 with no stroke_data must store 0, not 100."""
        ex = _make_letter_exercise('fix2a')
        student = _make_student('cr_stu_fix2a')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.post(url, {'stroke_data': '{}', 'score': '100'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['score'] == 0.0, 'No strokes → score must be 0 regardless of client value'

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.score == 0.0
        assert ans.is_correct is False

    def test_no_strokes_zero_points_earned(self):
        ex = _make_letter_exercise('fix2b')
        student = _make_student('cr_stu_fix2b')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        client.post(url, {'stroke_data': '{}', 'score': '90'})
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.points_earned == 0

    def test_valid_strokes_accept_client_score(self):
        """POST with actual stroke objects must accept (and clamp) the client score."""
        ex = _make_letter_exercise('fix2c')
        student = _make_student('cr_stu_fix2c')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        stroke_data = json.dumps({'version': '5.3', 'objects': [{'type': 'path', 'path': 'M 0 0 L 10 10'}]})
        resp = client.post(url, {'stroke_data': stroke_data, 'score': '87'})
        data = resp.json()
        assert data['score'] == 87.0, 'Valid strokes → client score should be accepted'

    def test_client_score_clamped_to_100(self):
        ex = _make_letter_exercise('fix2d')
        student = _make_student('cr_stu_fix2d')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        stroke_data = json.dumps({'objects': [{'type': 'path'}]})
        resp = client.post(url, {'stroke_data': stroke_data, 'score': '150'})
        data = resp.json()
        assert data['score'] == 100.0


# ---------------------------------------------------------------------------
# Fix 5 — MCQ re-submit wrong answer does not downgrade correct score
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMCQBestScoreGuard:

    def test_correct_then_wrong_keeps_correct_score(self):
        """Submit correct MCQ → re-submit wrong → stored score stays 100."""
        ex, correct, wrong = _make_mcq_exercise('fix5a')
        student = _make_student('cr_stu_fix5a')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp1 = client.post(url, {'selected_answer_id': str(correct.pk)})
        assert resp1.json()['is_correct'] is True

        resp2 = client.post(url, {'selected_answer_id': str(wrong.pk)})
        assert resp2.json()['is_correct'] is False

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.score == 100.0, 'Best score must be preserved after wrong re-submission'
        assert ans.is_correct is True

    def test_wrong_then_correct_upgrades_score(self):
        """Submit wrong MCQ first → then correct → score upgrades to 100."""
        ex, correct, wrong = _make_mcq_exercise('fix5b')
        student = _make_student('cr_stu_fix5b')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        client.post(url, {'selected_answer_id': str(wrong.pk)})
        client.post(url, {'selected_answer_id': str(correct.pk)})

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.score == 100.0
        assert ans.is_correct is True

    def test_only_one_db_record_after_retry(self):
        ex, correct, wrong = _make_mcq_exercise('fix5c')
        student = _make_student('cr_stu_fix5c')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        client.post(url, {'selected_answer_id': str(correct.pk)})
        client.post(url, {'selected_answer_id': str(wrong.pk)})
        client.post(url, {'selected_answer_id': str(correct.pk)})

        count = LanguageStudentAnswer.objects.filter(student=student, exercise=ex).count()
        assert count == 1


# ---------------------------------------------------------------------------
# Fix 1 — grammar_fill_blank NULL puzzle_data crash
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGrammarFillBlankNullPuzzleData:

    def test_empty_puzzle_data_get_returns_200(self):
        """Exercise with empty puzzle_data ({}) must not crash on GET."""
        ex, correct, _ = _make_grammar_exercise('fix1a', puzzle_data_val={})
        student = _make_student('cr_stu_fix1a')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.get(url)
        assert resp.status_code == 200

    def test_empty_puzzle_data_post_returns_200_with_empty_explanation(self):
        """Exercise with empty puzzle_data ({}) must return empty grammar_explanation."""
        ex, correct, _ = _make_grammar_exercise('fix1b', puzzle_data_val={})
        student = _make_student('cr_stu_fix1b')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.post(url, {'selected_answer_id': str(correct.pk)})
        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is True
        assert data['grammar_explanation'] == ''

    def test_missing_grammar_explanation_key_returns_empty_string(self):
        """puzzle_data without 'grammar_explanation' key → empty string, no KeyError."""
        ex, correct, _ = _make_grammar_exercise('fix1c', puzzle_data_val={'other_key': 'value'})
        student = _make_student('cr_stu_fix1c')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.get(url)
        assert resp.status_code == 200

        resp_post = client.post(url, {'selected_answer_id': str(correct.pk)})
        assert resp_post.json()['grammar_explanation'] == ''


# ---------------------------------------------------------------------------
# Fix 9 — grammar_fill_blank re-submit wrong doesn't downgrade
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGrammarFillBlankBestScoreGuard:

    def test_correct_then_wrong_keeps_correct_score(self):
        ex, correct, wrong = _make_grammar_exercise('fix9a', puzzle_data_val={'grammar_explanation': 'test'})
        student = _make_student('cr_stu_fix9a')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        client.post(url, {'selected_answer_id': str(correct.pk)})
        client.post(url, {'selected_answer_id': str(wrong.pk)})

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.score == 100.0
        assert ans.is_correct is True

    def test_wrong_then_correct_upgrades_score(self):
        ex, correct, wrong = _make_grammar_exercise('fix9b', puzzle_data_val={})
        student = _make_student('cr_stu_fix9b')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        client.post(url, {'selected_answer_id': str(wrong.pk)})
        client.post(url, {'selected_answer_id': str(correct.pk)})

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.score == 100.0
        assert ans.is_correct is True


# ---------------------------------------------------------------------------
# Fix 3 — crossword float hints are now counted in penalty
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCrosswordFloatHintPenalty:

    def test_float_hints_are_penalised(self):
        """hints_used=[1.0, 2.0] must apply 20-point penalty (JSON floats are valid)."""
        ex = _make_crossword_exercise('fix3a')
        student = _make_student('cr_stu_fix3a')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.post(url, {
            'word_answers': json.dumps({'0': 'CAT', '1': 'DOG'}),
            'hints_used':   json.dumps([1.0, 2.0]),
        })
        assert resp.status_code == 200
        data = resp.json()
        # 2/2 correct = 100 base, 2 float hints = -20 penalty → 80
        assert data['score'] == 80.0, f'Float hints must penalise. Got {data["score"]}'

    def test_int_hints_still_penalised(self):
        ex = _make_crossword_exercise('fix3b')
        student = _make_student('cr_stu_fix3b')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.post(url, {
            'word_answers': json.dumps({'0': 'CAT', '1': 'DOG'}),
            'hints_used':   json.dumps([0, 1]),
        })
        data = resp.json()
        assert data['score'] == 80.0

    def test_bool_not_counted_as_hint(self):
        """True/False in hints_used must NOT be counted (bool is subclass of int)."""
        ex = _make_crossword_exercise('fix3c')
        student = _make_student('cr_stu_fix3c')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.post(url, {
            'word_answers': json.dumps({'0': 'CAT', '1': 'DOG'}),
            'hints_used':   json.dumps([True, False]),
        })
        data = resp.json()
        assert data['score'] == 100.0, 'Boolean values must not count as hint indices'


# ---------------------------------------------------------------------------
# Fix 8 — crossword oversized POST fields are truncated
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCrosswordOversizedPostFields:

    def test_oversized_word_answers_returns_zero_correct(self):
        """word_answers > 500 KB → treated as empty dict → 0 correct."""
        ex = _make_crossword_exercise('fix8a')
        student = _make_student('cr_stu_fix8a')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.post(url, {
            'word_answers': 'x' * 600_000,
            'hints_used':   '[]',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['correct_count'] == 0

    def test_oversized_hints_are_capped(self):
        """hints_used > 10 KB → treated as empty list → no penalty."""
        ex = _make_crossword_exercise('fix8b')
        student = _make_student('cr_stu_fix8b')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.post(url, {
            'word_answers': json.dumps({'0': 'CAT', '1': 'DOG'}),
            'hints_used':   'x' * 15_000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['score'] == 100.0, 'Oversized hints_used → treat as empty → no penalty'


# ---------------------------------------------------------------------------
# Fix 6 — _build_crossword_grid KeyError on malformed puzzle_data
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCrosswordMalformedPuzzleData:

    def test_missing_answer_key_get_returns_200(self):
        """Word with missing 'answer' key must be skipped, not raise KeyError."""
        bad_puzzle = {
            'width': 5, 'height': 3,
            'words': [
                {'index': 0, 'number': 1, 'direction': 'across', 'row': 0, 'col': 0, 'clue': 'No answer'},
                {'index': 1, 'number': 2, 'direction': 'across', 'row': 2, 'col': 0, 'answer': 'DOG', 'clue': 'Bark'},
            ],
        }
        ex = _make_crossword_exercise('fix6a', puzzle_data=bad_puzzle)
        student = _make_student('cr_stu_fix6a')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.get(url)
        assert resp.status_code == 200

    def test_missing_row_key_get_returns_200(self):
        bad_puzzle = {
            'width': 5, 'height': 3,
            'words': [
                {'index': 0, 'number': 1, 'direction': 'across', 'col': 0, 'answer': 'CAT'},
            ],
        }
        ex = _make_crossword_exercise('fix6b', puzzle_data=bad_puzzle)
        student = _make_student('cr_stu_fix6b')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})

        resp = client.get(url)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Fix 10 — plugin grade_answer SPELLING_TYPE respects non-Latin script_type
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPluginSpellingTypeScriptType:

    def test_non_latin_wrong_case_fold_is_incorrect(self):
        """Sinhala text: grade_answer must NOT lower() — wrong letter is wrong."""
        from languages.plugin import LanguagesPlugin

        ex = _make_spelling_type_exercise('fix10a', script_type='sinhala', prompt='ක')
        plugin = LanguagesPlugin()
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.pk}': 'ග'})
        assert result['is_correct'] is False

    def test_non_latin_correct_exact_match_is_correct(self):
        from languages.plugin import LanguagesPlugin

        ex = _make_spelling_type_exercise('fix10b', script_type='sinhala', prompt='ක')
        plugin = LanguagesPlugin()
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.pk}': 'ක'})
        assert result['is_correct'] is True

    def test_latin_still_case_insensitive(self):
        """Latin script must still do case-insensitive comparison."""
        from languages.plugin import LanguagesPlugin

        ex = _make_spelling_type_exercise('fix10c', script_type='latin', prompt='cat')
        plugin = LanguagesPlugin()
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.pk}': 'CAT'})
        assert result['is_correct'] is True

    def test_non_latin_plugin_spelling_type_does_not_lowercase(self):
        """A wrong Sinhala ending character must not match — no case-folding applied."""
        from languages.plugin import LanguagesPlugin

        ex = _make_spelling_type_exercise('fix10d', script_type='sinhala', prompt='ගස')
        plugin = LanguagesPlugin()
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.pk}': 'ගත'})  # ත ≠ ස
        assert result['is_correct'] is False, 'Different Sinhala letters must not match'
