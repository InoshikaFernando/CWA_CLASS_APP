"""
End-to-end tests for the Languages app — CPP-348.

Full student-journey flows using Django's test client:
  1. Browse languages hub → see language cards and progress
  2. Complete phonics MCQ exercise → progress updated
  3. Complete spelling type exercise → feedback and score stored
  4. Complete crossword with hints → penalty applied
  5. Locked level blocks access with 403 for POST
  6. Unlock flow: complete beginner mastery → intermediate unlocked
  7. Re-attempt improves score but can't degrade previous best
  8. Grammar fill-blank end-to-end with explanation
  9. Sentence order end-to-end with partial credit
  10. Teacher blocked from student exercise submissions
"""
import json
from decimal import Decimal

import pytest
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language, LanguageAnswer, LanguageExercise,
    LanguageProgress, LanguageStudentAnswer,
    LanguageTopic, LanguageTopicLevel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_user(username, role_name, password='E2EPass348!'):
    u = CustomUser.objects.create_user(
        username=username, password=password,
        email=f'{username}@e2e348.local',
        profile_completed=True, must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=role_name, defaults={'display_name': role_name.title()})
    UserRole.objects.get_or_create(user=u, role=role)
    return u, password


def _make_language(suffix, script_type='latin'):
    lang, _ = Language.objects.get_or_create(
        code=f'e2e{suffix}'[:10],
        defaults={'name': f'E2ELang{suffix}', 'script_type': script_type, 'is_active': True, 'order': 90},
    )
    return lang


def _make_full_chain(suffix, script_type='latin'):
    lang = _make_language(suffix, script_type)
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name=f'E2ETopic{suffix}',
        defaults={'order': 0, 'is_active': True},
    )
    beg, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='beginner')
    inter, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='intermediate')
    return lang, topic, beg, inter


def _make_mcq(level, prompt='A', points=4):
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.PHONICS_MCQ,
        prompt=prompt, points=points, is_active=True,
    )
    correct = LanguageAnswer.objects.create(exercise=ex, answer_text='ay', is_correct=True, display_order=0)
    LanguageAnswer.objects.create(exercise=ex, answer_text='ee', is_correct=False, display_order=1)
    LanguageAnswer.objects.create(exercise=ex, answer_text='oo', is_correct=False, display_order=2)
    LanguageAnswer.objects.create(exercise=ex, answer_text='uh', is_correct=False, display_order=3)
    return ex, correct


def _make_spelling_type(level, prompt='cat', script_type='latin'):
    return LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.SPELLING_TYPE,
        prompt=prompt, points=3, is_active=True,
    )


def _make_grammar(level, prompt='He ___ happy.', explanation='is = present be'):
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.GRAMMAR_FILL_BLANK,
        prompt=prompt, points=5, is_active=True,
        puzzle_data={'grammar_explanation': explanation},
    )
    correct = LanguageAnswer.objects.create(exercise=ex, answer_text='is', is_correct=True, display_order=0)
    LanguageAnswer.objects.create(exercise=ex, answer_text='was', is_correct=False, display_order=1)
    return ex, correct


def _make_crossword(level, points=10):
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.CROSSWORD,
        prompt='Crossword', points=points, is_active=True,
        puzzle_data={
            'width': 5, 'height': 3,
            'words': [
                {'index': 0, 'number': 1, 'direction': 'across', 'row': 0, 'col': 0, 'answer': 'CAT', 'clue': 'Pet'},
                {'index': 1, 'number': 2, 'direction': 'across', 'row': 2, 'col': 0, 'answer': 'DOG', 'clue': 'Bark'},
            ],
        },
    )
    return ex


def _make_sentence_order(level, words=None, points=5):
    word_order = words or ['The', 'cat', 'sat', 'down']
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.SENTENCE_ORDER,
        prompt=' '.join(word_order), points=points, is_active=True,
        puzzle_data={'word_order': word_order},
    )
    return ex


# ---------------------------------------------------------------------------
# 1. Browse languages hub
# ---------------------------------------------------------------------------

class TestBrowseLanguagesHub(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.pwd = _create_user('e2e_hub_stu', Role.STUDENT)
        cls.lang, cls.topic, cls.beg, cls.inter = _make_full_chain('hub')
        cls.ex, _ = _make_mcq(cls.beg)

    def test_student_sees_language_cards(self):
        client = Client()
        client.login(username=self.student.username, password=self.pwd)
        resp = client.get(reverse('languages:index'))
        assert resp.status_code == 200
        assert self.lang.name.encode() in resp.content

    def test_student_sees_beginner_level(self):
        client = Client()
        client.login(username=self.student.username, password=self.pwd)
        resp = client.get(reverse('languages:index'))
        assert b'Beginner' in resp.content

    def test_hub_shows_no_progress_initially(self):
        client = Client()
        client.login(username=self.student.username, password=self.pwd)
        resp = client.get(reverse('languages:index'))
        ctx = resp.context
        assert ctx['total_correct'] == 0
        assert ctx['overall_pct'] == 0

    def test_hub_shows_progress_after_answering(self):
        client = Client()
        client.login(username=self.student.username, password=self.pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        correct = self.ex.answers.filter(is_correct=True).first()
        client.post(url, {'selected_answer_id': str(correct.pk)})

        resp = client.get(reverse('languages:index'))
        assert resp.context['total_correct'] == 1

    def test_hub_shows_teacher_blocked(self):
        teacher, pwd = _create_user('e2e_hub_tch', 'teacher')
        client = Client()
        client.login(username=teacher.username, password=pwd)
        resp = client.get(reverse('languages:index'))
        assert resp.status_code in (302, 403)


# ---------------------------------------------------------------------------
# 2. Full phonics MCQ exercise flow
# ---------------------------------------------------------------------------

class TestPhonicsMCQFlow(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.pwd = _create_user('e2e_mcq_stu', Role.STUDENT)
        _, _, cls.beg, _ = _make_full_chain('mcq')
        cls.ex, cls.correct = _make_mcq(cls.beg)

    def _login_client(self):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        return c

    def test_get_renders_exercise_page(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.get(url)
        assert resp.status_code == 200
        assert b'answer-btn' in resp.content

    def test_correct_answer_stores_is_correct_true(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.post(url, {'selected_answer_id': str(self.correct.pk)})
        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is True
        assert data['success'] is True

    def test_correct_answer_creates_db_record(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        client.post(url, {'selected_answer_id': str(self.correct.pk)})
        ans = LanguageStudentAnswer.objects.get(student=self.student, exercise=self.ex)
        assert ans.score == 100.0
        assert ans.is_correct is True
        assert ans.points_earned == self.ex.points

    def test_correct_answer_updates_progress(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        client.post(url, {'selected_answer_id': str(self.correct.pk)})
        prog = LanguageProgress.objects.filter(student=self.student, topic_level=self.beg).first()
        assert prog is not None
        assert prog.exercises_completed == 1

    def test_wrong_answer_returns_correct_answer_id(self):
        client = self._login_client()
        wrong = self.ex.answers.filter(is_correct=False).first()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.post(url, {'selected_answer_id': str(wrong.pk)})
        data = resp.json()
        assert data['is_correct'] is False
        assert data['correct_answer_id'] == self.correct.pk

    def test_best_score_not_downgraded_on_retry(self):
        """correct → wrong must keep score at 100."""
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        wrong = self.ex.answers.filter(is_correct=False).first()
        client.post(url, {'selected_answer_id': str(self.correct.pk)})
        client.post(url, {'selected_answer_id': str(wrong.pk)})
        ans = LanguageStudentAnswer.objects.get(student=self.student, exercise=self.ex)
        assert ans.score == 100.0
        assert ans.is_correct is True


# ---------------------------------------------------------------------------
# 3. Spelling type exercise flow
# ---------------------------------------------------------------------------

class TestSpellingTypeFlow(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.pwd = _create_user('e2e_sptype_stu', Role.STUDENT)
        _, _, cls.beg, _ = _make_full_chain('sptype')
        cls.ex = _make_spelling_type(cls.beg, prompt='banana')

    def _login_client(self):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        return c

    def test_correct_spelling_is_correct_true(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.post(url, {'answer': 'banana'})
        assert resp.json()['is_correct'] is True

    def test_case_insensitive_latin(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.post(url, {'answer': 'BANANA'})
        assert resp.json()['is_correct'] is True

    def test_wrong_spelling_returns_correct_spelling(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.post(url, {'answer': 'bananaa'})
        data = resp.json()
        assert data['is_correct'] is False
        assert data['correct_spelling'] == 'banana'

    def test_only_one_db_record_on_retry(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        client.post(url, {'answer': 'bananaa'})
        client.post(url, {'answer': 'banana'})
        count = LanguageStudentAnswer.objects.filter(student=self.student, exercise=self.ex).count()
        assert count == 1


# ---------------------------------------------------------------------------
# 4. Crossword exercise flow
# ---------------------------------------------------------------------------

class TestCrosswordFlow(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.pwd = _create_user('e2e_cw_stu', Role.STUDENT)
        _, _, cls.beg, _ = _make_full_chain('cw')
        cls.ex = _make_crossword(cls.beg, points=10)

    def _post(self, word_answers, hints_used=None):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        return c.post(url, {
            'word_answers': json.dumps(word_answers),
            'hints_used':   json.dumps(hints_used or []),
        })

    def test_all_correct_gives_full_score(self):
        resp = self._post({'0': 'CAT', '1': 'DOG'})
        data = resp.json()
        assert data['score'] == 100.0
        assert data['correct_count'] == 2

    def test_partial_correct_proportional_score(self):
        resp = self._post({'0': 'CAT', '1': 'FISH'})
        data = resp.json()
        assert data['score'] == 50.0
        assert data['correct_count'] == 1

    def test_hints_reduce_score(self):
        resp = self._post({'0': 'CAT', '1': 'DOG'}, hints_used=[0])
        data = resp.json()
        assert data['score'] == 90.0

    def test_float_hints_penalised(self):
        resp = self._post({'0': 'CAT', '1': 'DOG'}, hints_used=[0.0, 1.0])
        data = resp.json()
        assert data['score'] == 80.0

    def test_get_renders_grid(self):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = c.get(url)
        assert resp.status_code == 200
        assert b'cw-table' in resp.content


# ---------------------------------------------------------------------------
# 5. Locked level blocks POST
# ---------------------------------------------------------------------------

class TestLockedLevelFlow(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.pwd = _create_user('e2e_lock_stu', Role.STUDENT)
        _, _, cls.beg, cls.inter = _make_full_chain('lock')
        # Create an exercise in the locked intermediate level
        cls.inter_ex = LanguageExercise.objects.create(
            topic_level=cls.inter, exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='word', points=3, is_active=True,
        )

    def test_locked_level_post_returns_403(self):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.inter_ex.pk})
        resp = c.post(url, {'answer': 'word'})
        assert resp.status_code == 403
        data = resp.json()
        assert 'locked' in data.get('error', '').lower()

    def test_locked_level_get_returns_locked_template(self):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.inter_ex.pk})
        resp = c.get(url)
        assert resp.status_code == 200
        assert b'locked' in resp.content.lower()


# ---------------------------------------------------------------------------
# 6. Unlock flow — beginner mastery → intermediate unlocked
# ---------------------------------------------------------------------------

class TestUnlockFlow(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.pwd = _create_user('e2e_unlock_stu', Role.STUDENT)
        _, _, cls.beg, cls.inter = _make_full_chain('unlock')
        # 5 exercises needed for mastery (80% avg + 80% completed)
        cls.exercises = []
        for i in range(5):
            ex, correct = _make_mcq(cls.beg, prompt=f'Letter{i}', points=2)
            cls.exercises.append((ex, correct))
        # Add intermediate exercise so we can test it's accessible after unlock
        cls.inter_ex = LanguageExercise.objects.create(
            topic_level=cls.inter, exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='word', points=3, is_active=True,
        )

    def test_intermediate_unlocked_after_mastery(self):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        for ex, correct in self.exercises:
            url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})
            c.post(url, {'selected_answer_id': str(correct.pk)})

        prog = LanguageProgress.objects.filter(student=self.student, topic_level=self.inter).first()
        assert prog is not None, 'Intermediate LanguageProgress must exist after mastery'
        assert prog.is_unlocked is True

    def test_intermediate_accessible_after_unlock(self):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        for ex, correct in self.exercises:
            url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.pk})
            c.post(url, {'selected_answer_id': str(correct.pk)})

        inter_url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.inter_ex.pk})
        resp = c.post(inter_url, {'answer': 'word'})
        assert resp.status_code == 200
        assert resp.json()['is_correct'] is True


# ---------------------------------------------------------------------------
# 7. Grammar fill-blank end-to-end
# ---------------------------------------------------------------------------

class TestGrammarFillBlankFlow(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.pwd = _create_user('e2e_gfb_stu', Role.STUDENT)
        _, _, cls.beg, _ = _make_full_chain('gfb')
        cls.ex, cls.correct = _make_grammar(cls.beg)

    def _login_client(self):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        return c

    def test_get_renders_fill_blank_template(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.get(url)
        assert resp.status_code == 200
        assert b'He ' in resp.content
        assert b'happy.' in resp.content

    def test_correct_answer_returns_explanation(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.post(url, {'selected_answer_id': str(self.correct.pk)})
        data = resp.json()
        assert data['is_correct'] is True
        assert 'is = present be' in data['grammar_explanation']

    def test_wrong_answer_still_returns_explanation(self):
        client = self._login_client()
        wrong = self.ex.answers.filter(is_correct=False).first()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = client.post(url, {'selected_answer_id': str(wrong.pk)})
        data = resp.json()
        assert data['is_correct'] is False
        assert data['grammar_explanation'] == 'is = present be'

    def test_best_score_preserved_on_wrong_retry(self):
        client = self._login_client()
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        wrong = self.ex.answers.filter(is_correct=False).first()
        client.post(url, {'selected_answer_id': str(self.correct.pk)})
        client.post(url, {'selected_answer_id': str(wrong.pk)})
        ans = LanguageStudentAnswer.objects.get(student=self.student, exercise=self.ex)
        assert ans.score == 100.0
        assert ans.is_correct is True


# ---------------------------------------------------------------------------
# 8. Sentence order partial credit flow
# ---------------------------------------------------------------------------

class TestSentenceOrderFlow(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.pwd = _create_user('e2e_so_stu', Role.STUDENT)
        _, _, cls.beg, _ = _make_full_chain('so')
        cls.ex = _make_sentence_order(cls.beg, words=['The', 'cat', 'sat', 'down'], points=8)

    def _post(self, order):
        c = Client()
        c.login(username=self.student.username, password=self.pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        return c.post(url, {'submitted_order': json.dumps(order)})

    def test_perfect_order_gives_100(self):
        resp = self._post(['The', 'cat', 'sat', 'down'])
        data = resp.json()
        assert data['score'] == 100.0
        assert data['is_correct'] is True

    def test_partial_order_gives_partial_score(self):
        resp = self._post(['The', 'cat', 'down', 'sat'])
        data = resp.json()
        # 2/4 correct positions = 50%
        assert data['score'] == 50.0
        assert data['is_correct'] is False

    def test_correct_sentence_in_response(self):
        resp = self._post(['The', 'cat', 'sat', 'down'])
        data = resp.json()
        assert data['correct_sentence'] == 'The cat sat down'

    def test_partial_points_earned(self):
        resp = self._post(['The', 'cat', 'down', 'sat'])  # 50%
        data = resp.json()
        # points_earned = 8 * 50/100 = 4.00
        assert float(data['points_earned']) == pytest.approx(4.0)

    def test_best_score_kept_on_retry(self):
        self._post(['The', 'cat', 'sat', 'down'])   # 100%
        self._post(['The', 'down', 'cat', 'sat'])   # 25% — should not downgrade
        ans = LanguageStudentAnswer.objects.get(student=self.student, exercise=self.ex)
        assert ans.score == 100.0


# ---------------------------------------------------------------------------
# 9. Teacher blocked from exercise submissions
# ---------------------------------------------------------------------------

class TestTeacherBlockedFromExercises(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher, cls.pwd = _create_user('e2e_tch_exc', 'teacher')
        _, _, cls.beg, _ = _make_full_chain('tch')
        cls.ex, cls.correct = _make_mcq(cls.beg)

    def test_teacher_cannot_post_exercise_answer(self):
        c = Client()
        c.login(username=self.teacher.username, password=self.pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = c.post(url, {'selected_answer_id': str(self.correct.pk)})
        assert resp.status_code in (302, 403), \
            f'Teacher must be blocked from exercise submissions — got {resp.status_code}'

    def test_teacher_cannot_get_exercise_page(self):
        c = Client()
        c.login(username=self.teacher.username, password=self.pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': self.ex.pk})
        resp = c.get(url)
        assert resp.status_code in (302, 403)
