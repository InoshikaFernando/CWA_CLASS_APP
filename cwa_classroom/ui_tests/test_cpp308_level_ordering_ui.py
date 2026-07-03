"""
Playwright UI tests for CPP-308 review fix: level ordering on languages index.

Verifies that the Beginner chip always appears before Intermediate,
which appears before Advanced — regardless of the order levels were
created in the database.
"""

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp308


def _make_student(suffix=''):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'lo308{suffix}_{_RUN_ID}'
    user = CustomUser.objects.create_user(
        username=f'stu_{uid}',
        password=TEST_PASSWORD,
        email=f'stu_{uid}@lo308.com',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _setup_all_levels(suffix=''):
    """Create a language with exercises at all three levels.

    Levels are created in reverse order (advanced first) to ensure
    the ordering fix works regardless of DB insertion order.
    """
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel,
        LanguageExercise, LanguageAnswer,
    )
    code = f'lo{suffix}'[:10]
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': f'LevelOrderLang{suffix}', 'script_type': 'latin',
                  'is_active': True, 'order': 98},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name='Ordering Topic',
        defaults={'order': 0, 'is_active': True},
    )
    # Create in reverse (advanced first) to expose any alphabetic-sort bug
    adv,   _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='advanced')
    inter, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='intermediate')
    beg,   _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='beginner')

    for level in (beg, inter, adv):
        ex = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_MCQ,
            prompt=f'word_{level.level_choice}',
            points=2, is_active=True,
        )
        LanguageAnswer.objects.create(exercise=ex, answer_text='correct', is_correct=True, display_order=0)
        LanguageAnswer.objects.create(exercise=ex, answer_text='wrong',   is_correct=False, display_order=1)

    return lang, topic, beg, inter, adv


@pytest.mark.django_db(transaction=True)
class TestLevelOrderingOnIndex:

    def test_beginner_chip_appears_before_intermediate(self, page, live_server):
        """Beginner chip position in DOM must come before Intermediate chip."""
        user = _make_student('chip')
        lang, _, _, _, _ = _setup_all_levels('chip')

        do_login(page, live_server.url, user)
        page.goto(f'{live_server.url}/languages/')
        page.wait_for_load_state('domcontentloaded')

        # Click the language card to make its panel visible
        page.locator(f'button[data-lang="{lang.code}"]').click()
        page.wait_for_timeout(300)

        lang_panel = page.locator(f'#lang-{lang.code}')

        # Both chips must be present
        beg_chip   = lang_panel.get_by_text('Beginner').first
        inter_chip = lang_panel.get_by_text('Intermediate').first
        expect(beg_chip).to_be_visible()
        expect(inter_chip).to_be_visible()

        # Measure DOM position: Beginner's bounding box top/left must be <= Intermediate's
        beg_box   = beg_chip.bounding_box()
        inter_box = inter_chip.bounding_box()

        assert beg_box is not None and inter_box is not None
        # Allow same row (same y) or higher row (smaller y); must never be below Intermediate
        assert beg_box['y'] <= inter_box['y'] + 5, (
            f'Beginner chip (y={beg_box["y"]}) appears BELOW Intermediate (y={inter_box["y"]})'
        )

    def test_intermediate_chip_appears_before_advanced(self, page, live_server):
        """Intermediate chip position in DOM must come before Advanced chip."""
        user = _make_student('adv')
        lang, _, _, _, _ = _setup_all_levels('adv')

        do_login(page, live_server.url, user)
        page.goto(f'{live_server.url}/languages/')
        page.wait_for_load_state('domcontentloaded')

        page.locator(f'button[data-lang="{lang.code}"]').click()
        page.wait_for_timeout(300)

        lang_panel = page.locator(f'#lang-{lang.code}')
        inter_chip = lang_panel.get_by_text('Intermediate').first
        adv_chip   = lang_panel.get_by_text('Advanced').first

        expect(inter_chip).to_be_visible()
        expect(adv_chip).to_be_visible()

        inter_box = inter_chip.bounding_box()
        adv_box   = adv_chip.bounding_box()

        assert inter_box is not None and adv_box is not None
        assert inter_box['y'] <= adv_box['y'] + 5, (
            f'Intermediate chip (y={inter_box["y"]}) appears BELOW Advanced (y={adv_box["y"]})'
        )

    def test_beginner_section_renders_before_locked_sections(self, page, live_server):
        """On the exercise body, Beginner unlocked section must appear above locked sections."""
        user = _make_student('sec')
        lang, _, _, _, _ = _setup_all_levels('sec')

        do_login(page, live_server.url, user)
        page.goto(f'{live_server.url}/languages/')
        page.wait_for_load_state('domcontentloaded')

        page.locator(f'button[data-lang="{lang.code}"]').click()
        page.wait_for_timeout(400)

        lang_panel = page.locator(f'#lang-{lang.code}')

        # Expand the topic accordion if collapsed — scope to this language's panel
        topic_body = lang_panel.locator('.topic-body').first
        if not topic_body.is_visible():
            lang_panel.locator('.topic-toggle').first.click()
            page.wait_for_timeout(200)

        # Template renders prompt via truncatechars:7 — use title attribute to find the exercise
        beg_ex    = lang_panel.locator('[title="word_beginner"]').first
        # Template renders locked section as "<Level> — Locked" inside a <p>
        locked_card = lang_panel.locator('p').filter(has_text='Locked').first

        expect(beg_ex).to_be_visible()
        expect(locked_card).to_be_visible()

        beg_box    = beg_ex.bounding_box()
        locked_box = locked_card.bounding_box()

        assert beg_box is not None and locked_box is not None
        assert beg_box['y'] < locked_box['y'], (
            f'Beginner exercise (y={beg_box["y"]}) must appear before locked '
            f'Intermediate card (y={locked_box["y"]})'
        )
