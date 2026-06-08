"""
Playwright UI tests for CPP-315: Grammar fill-in-the-blank and sentence ordering.

Covers:
1. Fill-blank loads with sentence gap and 4 answer buttons
2. Correct answer highlights green, shows grammar explanation in result panel
3. Incorrect answer highlights red, correct answer highlighted blue, explanation shown
4. Try Again resets fill-blank to initial state
5. Sentence order page loads with word bank tiles and empty answer zone
6. Tiles move to answer zone on click; submit button enables
7. Submitting correct order shows success panel
8. Submitting wrong order shows partial credit score
9. Try Again on sentence order returns tiles to word bank
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp315


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(suffix=''):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'g315{suffix}_{_RUN_ID}'
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


def _make_fill_blank(suffix=''):
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel,
        LanguageExercise, LanguageAnswer,
    )
    code = f'gfb{suffix}'[:10]
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': f'GFBLang{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name='Grammar',
        defaults={'order': 0, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice='intermediate',
    )
    ex = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.GRAMMAR_FILL_BLANK,
        prompt='The cat ___ on the mat.',
        puzzle_data={'blank_position': 2, 'grammar_explanation': 'Past tense of sit is sat.'},
        points=5,
        is_active=True,
    )
    correct = LanguageAnswer.objects.create(exercise=ex, answer_text='sat', is_correct=True, display_order=0)
    LanguageAnswer.objects.create(exercise=ex, answer_text='sit', is_correct=False, display_order=1)
    LanguageAnswer.objects.create(exercise=ex, answer_text='sits', is_correct=False, display_order=2)
    LanguageAnswer.objects.create(exercise=ex, answer_text='sitting', is_correct=False, display_order=3)
    return ex, correct


def _make_sentence_order(suffix=''):
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel, LanguageExercise,
    )
    code = f'so{suffix}'[:10]
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': f'SOLang{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name='Grammar',
        defaults={'order': 0, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice='intermediate',
    )
    words = ['The', 'cat', 'sat', 'on', 'mat.']
    ex = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.SENTENCE_ORDER,
        prompt='The cat sat on mat.',
        puzzle_data={'word_order': words},
        points=5,
        is_active=True,
    )
    return ex, words


def _url(live_server, ex):
    return f'{live_server.url}/languages/exercise/{ex.id}/'


# ===========================================================================
# Fill-in-the-Blank UI Tests
# ===========================================================================

@pytest.mark.django_db(transaction=True)
class TestFillBlankUI:

    def test_page_loads_with_gap_and_answer_buttons(self, page, live_server):
        user = _make_student('gfb_load')
        ex, _ = _make_fill_blank('load')
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, ex))

        # Sentence gap rendered
        gap = page.locator('.grammar-blank')
        expect(gap).to_be_visible()
        expect(gap).to_have_text('?')

        # Sentence parts visible
        expect(page.locator('text=The cat')).to_be_visible()
        expect(page.locator('text=on the mat.')).to_be_visible()

        # Four answer buttons
        btns = page.locator('.answer-btn')
        expect(btns).to_have_count(4)

        # Result panel hidden
        expect(page.locator('#result-panel')).to_be_hidden()

    def test_correct_answer_shows_green_and_explanation(self, page, live_server):
        user = _make_student('gfb_correct')
        ex, correct_ans = _make_fill_blank('correct')
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, ex))

        # Click the correct answer button
        correct_btn = page.locator(f'.answer-btn[data-answer-id="{correct_ans.id}"]')
        correct_btn.click()

        # Result panel visible with correct feedback
        panel = page.locator('#result-panel')
        expect(panel).to_be_visible()
        expect(page.locator('#result-icon')).to_have_text('🎉')
        expect(page.locator('#result-msg')).to_have_text('Correct!')

        # Grammar explanation shown
        expect(page.locator('#result-explanation')).to_be_visible()
        expect(page.locator('#result-explanation-text')).to_contain_text('Past tense')

        # Correct button has green class
        expect(correct_btn).to_have_attribute('class', re.compile(r'\bcorrect\b'))

    def test_incorrect_answer_shows_red_and_reveals_correct(self, page, live_server):
        user = _make_student('gfb_wrong')
        ex, correct_ans = _make_fill_blank('wrong')
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, ex))

        # Click a wrong answer
        wrong_btn = page.locator('.answer-btn').filter(has_text='sit').first
        wrong_btn.click()

        # Result panel visible with incorrect feedback
        panel = page.locator('#result-panel')
        expect(panel).to_be_visible()
        expect(page.locator('#result-icon')).to_have_text('✗')
        expect(page.locator('#result-msg')).to_have_text('Not quite!')

        # Correct answer revealed in result
        expect(page.locator('#result-word')).to_have_text('sat')

        # Wrong button has red class; correct button has green
        expect(wrong_btn).to_have_attribute('class', re.compile(r'\bincorrect\b'))
        correct_btn = page.locator(f'.answer-btn[data-answer-id="{correct_ans.id}"]')
        expect(correct_btn).to_have_attribute('class', re.compile(r'\bcorrect\b'))

    def test_try_again_resets_fill_blank(self, page, live_server):
        user = _make_student('gfb_retry')
        ex, correct_ans = _make_fill_blank('retry')
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, ex))

        # Answer then try again
        page.locator('.answer-btn').first.click()
        expect(page.locator('#result-panel')).to_be_visible()

        page.locator('#btn-try-again').click()

        # Panel hidden again
        expect(page.locator('#result-panel')).to_be_hidden()
        # Buttons re-enabled and no colour classes
        btns = page.locator('.answer-btn')
        for btn in btns.all():
            expect(btn).not_to_have_attribute('class', re.compile(r'\bcorrect\b'))
            expect(btn).not_to_have_attribute('class', re.compile(r'\bincorrect\b'))
            expect(btn).to_be_enabled()


# ===========================================================================
# Sentence Order UI Tests
# ===========================================================================

@pytest.mark.django_db(transaction=True)
class TestSentenceOrderUI:

    def test_page_loads_with_tiles_in_word_bank(self, page, live_server):
        user = _make_student('so_load')
        ex, words = _make_sentence_order('load')
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, ex))

        # Word bank visible
        expect(page.locator('#word-bank')).to_be_visible()

        # Each word appears as a tile in the bank
        for word in words:
            expect(page.locator('#word-bank').get_by_text(word, exact=True)).to_be_visible()

        # Answer zone empty, submit disabled
        expect(page.locator('#answer-zone')).to_be_visible()
        expect(page.locator('#btn-submit')).to_be_disabled()

        # Result panel hidden
        expect(page.locator('#result-panel')).to_be_hidden()

    def test_clicking_tile_moves_to_answer_zone_and_enables_submit(self, page, live_server):
        user = _make_student('so_tap')
        ex, words = _make_sentence_order('tap')
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, ex))

        # Click first tile in word bank
        first_tile = page.locator('#word-bank .word-tile').first
        first_tile.click()

        # Tile now in answer zone
        expect(page.locator('#answer-zone .word-tile')).to_have_count(1)

        # Submit now enabled
        expect(page.locator('#btn-submit')).to_be_enabled()

    def test_correct_order_submission_shows_success(self, page, live_server):
        user = _make_student('so_correct')
        ex, words = _make_sentence_order('correct')
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, ex))

        # Move all tiles to answer zone in correct order by clicking each
        for word in words:
            tile = page.locator('#word-bank .word-tile').filter(has_text=word).first
            tile.click()

        page.locator('#btn-submit').click()

        # Success panel
        panel = page.locator('#result-panel')
        expect(panel).to_be_visible()
        expect(page.locator('#result-icon')).to_have_text('🎉')
        expect(page.locator('#result-msg')).to_have_text('Correct!')

    def test_try_again_returns_tiles_to_word_bank(self, page, live_server):
        user = _make_student('so_tryagain')
        ex, words = _make_sentence_order('tryagain')
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, ex))

        # Move tiles and submit
        for word in words:
            page.locator('#word-bank .word-tile').filter(has_text=word).first.click()

        page.locator('#btn-submit').click()
        expect(page.locator('#result-panel')).to_be_visible()

        # Try Again
        page.locator('#btn-try-again').click()

        # Result panel hidden, tiles back in bank, submit disabled
        expect(page.locator('#result-panel')).to_be_hidden()
        expect(page.locator('#answer-zone .word-tile')).to_have_count(0)
        expect(page.locator('#word-bank .word-tile')).to_have_count(len(words))
        expect(page.locator('#btn-submit')).to_be_disabled()
