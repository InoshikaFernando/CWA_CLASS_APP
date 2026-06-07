"""
Playwright UI tests for CPP-313: Spelling MCQ and type-the-word exercises.

Covers:
1. Spelling MCQ — play button + answer grid visible on load
2. Spelling MCQ — correct answer shows green + success result panel
3. Spelling MCQ — incorrect answer shows red + correct answer revealed, correct_answer_text shown
4. Spelling type — play button + text input + disabled submit on load
5. Spelling type — correct submission shows success panel
6. Spelling type — incorrect submission shows failure + correct_spelling in result-word
7. Spelling type — lang attribute is present on input for non-Latin language
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp313


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(suffix=''):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'sp313{suffix}_{_RUN_ID}'
    user = CustomUser.objects.create_user(
        username=f'student_{uid}',
        password=TEST_PASSWORD,
        email=f'student_{uid}@cpptest.com',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT,
        defaults={'display_name': 'Student'},
    )
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _make_spelling_mcq(suffix='', prompt='cat'):
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel,
        LanguageExercise, LanguageAnswer,
    )
    lang, _ = Language.objects.get_or_create(
        code=f'en313mcq{suffix}',
        defaults={'name': f'English313MCQ{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'Spelling MCQ {suffix}',
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
    LanguageAnswer.objects.create(
        exercise=exercise, answer_text=prompt + 'x', is_correct=False, display_order=1,
    )
    LanguageAnswer.objects.create(
        exercise=exercise, answer_text=prompt + 'xx', is_correct=False, display_order=2,
    )
    LanguageAnswer.objects.create(
        exercise=exercise, answer_text=prompt + 'y', is_correct=False, display_order=3,
    )
    return exercise, correct


def _make_spelling_type(suffix='', prompt='cat', script_type='latin'):
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel, LanguageExercise,
    )
    code = f'en313typ{suffix}' if script_type == 'latin' else f'si313typ{suffix}'
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={
            'name': f'Lang313Type{suffix}',
            'script_type': script_type,
            'is_active': True,
            'order': 99,
        },
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'Spelling Type {suffix}',
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
    return exercise, lang


# ---------------------------------------------------------------------------
# Test class: Spelling MCQ UI
# ---------------------------------------------------------------------------

class TestSpellingMcqUI:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student('mcq')
        self.exercise, self.correct = _make_spelling_mcq('ui', prompt='fish')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        do_login(page, self.url, self.student)

    @pytest.mark.django_db(transaction=True)
    def test_play_button_and_answer_grid_visible_on_load(self):
        """Play button and 4 answer buttons rendered on load; result panel hidden."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        body = self.page.locator('body')
        expect(body).not_to_contain_text('Server Error')
        expect(body).not_to_contain_text('DoesNotExist')

        expect(self.page.locator('#play-btn')).to_be_visible()
        expect(self.page.locator('#answer-grid')).to_be_visible()

        answer_btns = self.page.locator('.answer-btn')
        expect(answer_btns).to_have_count(4)

        expect(self.page.locator('#result-panel')).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_correct_answer_shows_green_and_success_panel(self):
        """Clicking the correct option adds green class and shows Correct! panel."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)

        correct_btn = self.page.locator(f'.answer-btn[data-answer-id="{self.correct.pk}"]')
        expect(correct_btn).to_be_visible()

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ) as resp_info:
            correct_btn.click()

        resp = resp_info.value
        assert resp.status == 200
        data = resp.json()
        assert data['is_correct'] is True

        self.page.wait_for_timeout(300)

        expect(correct_btn).to_have_class(re.compile(r'correct'))
        expect(self.page.locator('#result-panel')).to_be_visible()
        expect(self.page.locator('#result-msg')).to_contain_text('Correct')

    @pytest.mark.django_db(transaction=True)
    def test_incorrect_answer_shows_red_and_reveals_correct(self):
        """Wrong option goes red; correct option revealed green; correct_answer_text shown in result-word."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)

        wrong_btn = self.page.locator(
            f'.answer-btn:not([data-answer-id="{self.correct.pk}"])'
        ).first

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ) as resp_info:
            wrong_btn.click()

        resp = resp_info.value
        assert resp.status == 200
        data = resp.json()
        assert data['is_correct'] is False
        assert data['correct_answer_id'] == self.correct.pk

        self.page.wait_for_timeout(300)

        expect(wrong_btn).to_have_class(re.compile(r'incorrect'))

        correct_btn = self.page.locator(f'.answer-btn[data-answer-id="{self.correct.pk}"]')
        expect(correct_btn).to_have_class(re.compile(r'correct'))

        expect(self.page.locator('#result-panel')).to_be_visible()
        expect(self.page.locator('#result-msg')).to_contain_text('Not quite')
        # correct_answer_text shown in result-word
        expect(self.page.locator('#result-word')).to_contain_text('fish')

    @pytest.mark.django_db(transaction=True)
    def test_try_again_resets_answer_grid(self):
        """Try Again clears correct/incorrect classes and hides result panel."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)

        wrong_btn = self.page.locator(
            f'.answer-btn:not([data-answer-id="{self.correct.pk}"])'
        ).first

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ):
            wrong_btn.click()

        self.page.wait_for_timeout(300)
        expect(self.page.locator('#result-panel')).to_be_visible()

        self.page.locator('#btn-try-again').click()
        self.page.wait_for_timeout(300)

        expect(self.page.locator('#result-panel')).to_be_hidden()
        # All buttons re-enabled and have no correct/incorrect classes
        for btn in self.page.locator('.answer-btn').all():
            expect(btn).to_be_enabled()
            classes = btn.get_attribute('class') or ''
            assert 'correct' not in classes
            assert 'incorrect' not in classes


# ---------------------------------------------------------------------------
# Test class: Spelling Type UI
# ---------------------------------------------------------------------------

class TestSpellingTypeUI:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student('type')
        self.exercise, self.lang = _make_spelling_type('ui', prompt='mango')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        do_login(page, self.url, self.student)

    @pytest.mark.django_db(transaction=True)
    def test_play_button_input_and_disabled_submit_on_load(self):
        """Play button visible, input present, submit disabled until text entered."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        body = self.page.locator('body')
        expect(body).not_to_contain_text('Server Error')

        expect(self.page.locator('#play-btn')).to_be_visible()
        expect(self.page.locator('#spelling-input')).to_be_visible()

        submit_btn = self.page.locator('#btn-submit')
        expect(submit_btn).to_be_disabled()

        expect(self.page.locator('#result-panel')).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_input_enables_submit_button(self):
        """Typing in the input enables the Submit button."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        inp = self.page.locator('#spelling-input')
        submit_btn = self.page.locator('#btn-submit')

        expect(submit_btn).to_be_disabled()
        inp.fill('m')
        expect(submit_btn).to_be_enabled()

    @pytest.mark.django_db(transaction=True)
    def test_correct_submission_shows_success_panel(self):
        """Correct spelling shows Correct! panel with no result-word."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)

        self.page.locator('#spelling-input').fill('mango')

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ) as resp_info:
            self.page.locator('#btn-submit').click()

        resp = resp_info.value
        assert resp.status == 200
        data = resp.json()
        assert data['is_correct'] is True

        self.page.wait_for_timeout(300)

        expect(self.page.locator('#result-panel')).to_be_visible()
        expect(self.page.locator('#result-msg')).to_contain_text('Correct')
        # result-word should be empty on correct answer
        result_word = self.page.locator('#result-word')
        assert (result_word.inner_text() or '').strip() == ''

    @pytest.mark.django_db(transaction=True)
    def test_incorrect_submission_shows_failure_and_correct_spelling(self):
        """Wrong spelling shows Not quite! and displays correct_spelling in result-word."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)

        self.page.locator('#spelling-input').fill('mangoo')

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ) as resp_info:
            self.page.locator('#btn-submit').click()

        resp = resp_info.value
        assert resp.status == 200
        data = resp.json()
        assert data['is_correct'] is False
        assert data['correct_spelling'] == 'mango'

        self.page.wait_for_timeout(300)

        expect(self.page.locator('#result-panel')).to_be_visible()
        expect(self.page.locator('#result-msg')).to_contain_text('Not quite')
        expect(self.page.locator('#result-word')).to_contain_text('mango')

    @pytest.mark.django_db(transaction=True)
    def test_enter_key_submits(self):
        """Pressing Enter in the input triggers the submit."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)

        inp = self.page.locator('#spelling-input')
        inp.fill('mango')

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ) as resp_info:
            inp.press('Enter')

        resp = resp_info.value
        assert resp.status == 200
        data = resp.json()
        assert data['is_correct'] is True

    @pytest.mark.django_db(transaction=True)
    def test_try_again_resets_input_and_hides_result(self):
        """Try Again clears input, re-enables it, and hides result panel."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)

        self.page.locator('#spelling-input').fill('wrong')

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ):
            self.page.locator('#btn-submit').click()

        self.page.wait_for_timeout(300)
        expect(self.page.locator('#result-panel')).to_be_visible()

        self.page.locator('#btn-try-again').click()
        self.page.wait_for_timeout(300)

        expect(self.page.locator('#result-panel')).to_be_hidden()
        inp = self.page.locator('#spelling-input')
        expect(inp).to_be_enabled()
        assert inp.input_value() == ''
        expect(self.page.locator('#btn-submit')).to_be_disabled()


# ---------------------------------------------------------------------------
# Test class: lang attribute present for non-Latin
# ---------------------------------------------------------------------------

class TestSpellingLangAttributeUI:

    @pytest.mark.django_db(transaction=True)
    def test_spelling_type_input_lang_attr_matches_language_code(self, live_server, page, db):
        """lang attribute on #spelling-input matches the language code."""
        from django.urls import reverse
        student = _make_student('lang')
        exercise, lang = _make_spelling_type('si', prompt='ක', script_type='sinhala')

        path = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        do_login(page, live_server.url, student)
        page.goto(f'{live_server.url}{path}')
        page.wait_for_load_state('domcontentloaded')

        inp = page.locator('#spelling-input')
        expect(inp).to_be_visible()
        lang_attr = inp.get_attribute('lang')
        assert lang_attr == lang.code, f"Expected lang='{lang.code}', got '{lang_attr}'"
