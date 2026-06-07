"""
Playwright UI tests for CPP-312: Phonics MCQ exercises with audio playback.

Covers:
1. Play button visible on page load
2. Correct answer shows green highlight + success result panel
3. Incorrect answer shows red highlight + correct answer revealed in blue
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp312


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student():
    from accounts.models import CustomUser, Role, UserRole
    uid = f'ph312_{_RUN_ID}'
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


def _make_phonics_exercise():
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel,
        LanguageExercise, LanguageAnswer,
    )
    lang, _ = Language.objects.get_or_create(
        code='en312ui',
        defaults={'name': 'English312UI', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name='Phonics 312 UI',
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
        points=2,
        is_active=True,
    )
    correct = LanguageAnswer.objects.create(
        exercise=exercise, answer_text='A', is_correct=True, display_order=0,
    )
    LanguageAnswer.objects.create(
        exercise=exercise, answer_text='B', is_correct=False, display_order=1,
    )
    LanguageAnswer.objects.create(
        exercise=exercise, answer_text='C', is_correct=False, display_order=2,
    )
    LanguageAnswer.objects.create(
        exercise=exercise, answer_text='D', is_correct=False, display_order=3,
    )
    return exercise, correct


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestPhonicsMcqUI:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student()
        self.exercise, self.correct = _make_phonics_exercise()
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        do_login(page, self.url, self.student)

    @pytest.mark.django_db(transaction=True)
    def test_play_button_visible_on_load(self):
        """Play button is visible and answer grid rendered on page load."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        body = self.page.locator('body')
        expect(body).not_to_contain_text('Server Error')
        expect(body).not_to_contain_text('DoesNotExist')

        expect(self.page.locator('#play-btn')).to_be_visible()
        expect(self.page.locator('#answer-grid')).to_be_visible()

        # All 4 answer buttons rendered
        answer_btns = self.page.locator('.answer-btn')
        expect(answer_btns).to_have_count(4)

        # Result panel hidden before answering
        expect(self.page.locator('#result-panel')).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_correct_answer_shows_green(self):
        """Clicking the correct answer adds green class and shows success result panel."""
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

        # Correct button has green class
        expect(correct_btn).to_have_class(re.compile(r'correct'))

        # Result panel visible with success content
        expect(self.page.locator('#result-panel')).to_be_visible()
        expect(self.page.locator('#result-msg')).to_contain_text('Correct')

    @pytest.mark.django_db(transaction=True)
    def test_incorrect_answer_shows_red_and_reveals_correct(self):
        """Clicking a wrong answer: selected button goes red, correct button goes blue."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)

        # Pick any wrong answer (one that is NOT the correct one)
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

        # Wrong button has incorrect (red) class
        expect(wrong_btn).to_have_class(re.compile(r'incorrect'))

        # Correct button has correct (green) class — revealed
        correct_btn = self.page.locator(f'.answer-btn[data-answer-id="{self.correct.pk}"]')
        expect(correct_btn).to_have_class(re.compile(r'correct'))

        # Result panel shows failure message
        expect(self.page.locator('#result-panel')).to_be_visible()
        expect(self.page.locator('#result-msg')).to_contain_text('Not quite')
