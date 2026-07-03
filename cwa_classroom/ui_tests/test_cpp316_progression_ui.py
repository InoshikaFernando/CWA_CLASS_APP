"""
Playwright UI tests for CPP-316: Stage progression tracking and homework integration.

1. Student sees stage indicators (locked/unlocked chips) on language index
2. Locked stage shows lock icon — content replaced with locked placeholder
3. Visiting a locked exercise shows the locked banner page
4. Stage unlocks after achieving 80% mastery (chip changes to unlocked)
5. Teacher can create homework with Languages subject and see topic tree
"""

import re
import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp316

_LANG_CODE = 'prog316'[:10]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(suffix=''):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'p316{suffix}_{_RUN_ID}'
    user = CustomUser.objects.create_user(
        username=f'stu_{uid}',
        password=TEST_PASSWORD,
        email=f'stu_{uid}@cpp316.com',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _make_teacher(suffix=''):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'tea316{suffix}_{_RUN_ID}'
    user = CustomUser.objects.create_user(
        username=f'tea_{uid}',
        password=TEST_PASSWORD,
        email=f'tea_{uid}@cpp316.com',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _setup_two_level_lang(suffix=''):
    from languages.models import Language, LanguageTopic, LanguageTopicLevel, LanguageExercise, LanguageAnswer
    code = f'pr{suffix}'[:10]
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': f'ProgLang{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name='Prog Grammar',
        defaults={'order': 0, 'is_active': True},
    )
    beg, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='beginner')
    inter, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='intermediate')

    # 3 beginner exercises
    beg_exs = []
    for i in range(3):
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.SPELLING_MCQ,
            prompt=f'word{i}',
            points=5,
            is_active=True,
        )
        LanguageAnswer.objects.create(exercise=ex, answer_text='correct', is_correct=True, display_order=0)
        LanguageAnswer.objects.create(exercise=ex, answer_text='wrong', is_correct=False, display_order=1)
        beg_exs.append(ex)

    # 2 intermediate exercises
    inter_exs = []
    for i in range(2):
        ex = LanguageExercise.objects.create(
            topic_level=inter,
            exercise_type=LanguageExercise.SPELLING_MCQ,
            prompt=f'inter{i}',
            points=5,
            is_active=True,
        )
        LanguageAnswer.objects.create(exercise=ex, answer_text='correct', is_correct=True, display_order=0)
        LanguageAnswer.objects.create(exercise=ex, answer_text='wrong', is_correct=False, display_order=1)
        inter_exs.append(ex)

    return lang, topic, beg, inter, beg_exs, inter_exs


def _url(live_server, path):
    return f'{live_server.url}{path}'


# ===========================================================================
# Tests
# ===========================================================================

@pytest.mark.django_db(transaction=True)
class TestStageIndicatorsOnIndex:

    def test_beginner_stage_shows_unlocked_chip(self, page, live_server):
        user = _make_student('idx')
        lang, _, beg, inter, _, _ = _setup_two_level_lang('idx')

        do_login(page, live_server.url, user)
        page.goto(_url(live_server, '/languages/'))

        # Click the language tab to make this language's panel visible
        page.locator(f'button[data-lang="{lang.code}"]').click()

        # Beginner chip should be visible (not locked)
        beg_chip = page.locator(f'#lang-{lang.code}').get_by_text('Beginner').first
        expect(beg_chip).to_be_visible()
        # Beginner chip should NOT contain lock emoji
        expect(beg_chip).not_to_contain_text('🔒')

    def test_intermediate_stage_shows_locked_chip(self, page, live_server):
        user = _make_student('locked')
        lang, _, beg, inter, _, _ = _setup_two_level_lang('locked')

        do_login(page, live_server.url, user)
        page.goto(_url(live_server, '/languages/'))
        page.locator(f'button[data-lang="{lang.code}"]').click()

        # Intermediate chip shows lock icon
        inter_chip = page.locator(f'#lang-{lang.code}').get_by_text('Intermediate').first
        expect(inter_chip).to_be_visible()
        expect(inter_chip).to_contain_text('🔒')

    def test_locked_level_shows_placeholder_card(self, page, live_server):
        user = _make_student('ph')
        lang, _, beg, inter, _, _ = _setup_two_level_lang('ph')

        do_login(page, live_server.url, user)
        page.goto(_url(live_server, '/languages/'))
        page.locator(f'button[data-lang="{lang.code}"]').click()

        # The locked placeholder card should be visible instead of exercise links
        lang_panel = page.locator(f'#lang-{lang.code}')
        expect(lang_panel.get_by_text('Locked')).to_be_visible()
        expect(lang_panel.get_by_text('Complete Beginner to unlock')).to_be_visible()


@pytest.mark.django_db(transaction=True)
class TestLockedExerciseAccess:

    def test_visiting_locked_exercise_shows_banner(self, page, live_server):
        user = _make_student('ban')
        _, _, _, inter, _, inter_exs = _setup_two_level_lang('ban')
        ex = inter_exs[0]

        do_login(page, live_server.url, user)
        page.goto(_url(live_server, f'/languages/exercise/{ex.id}/'))

        # Should show locked banner, not the exercise form
        expect(page.locator('h1')).to_contain_text('Stage Locked')
        expect(page.get_by_text('Back to Language Hub')).to_be_visible()

    def test_locked_exercise_shows_blocking_progress(self, page, live_server):
        user = _make_student('blk')
        _, _, beg, inter, beg_exs, inter_exs = _setup_two_level_lang('blk')

        # Give student some (insufficient) beginner progress
        from languages.models import LanguageStudentAnswer, LanguageProgress
        from languages.views import _recalculate_progress
        LanguageStudentAnswer.objects.create(
            student=user, exercise=beg_exs[0],
            score=60.0, is_correct=False, points_earned=0,
        )
        _recalculate_progress(user, beg)

        ex = inter_exs[0]
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, f'/languages/exercise/{ex.id}/'))

        expect(page.locator('h1')).to_contain_text('Stage Locked')
        # Should show blocking level name (use first to avoid strict-mode with "Practice Beginner" link)
        expect(page.locator('strong').filter(has_text='Beginner').first).to_be_visible()


@pytest.mark.django_db(transaction=True)
class TestStageUnlockAfterMastery:

    def test_intermediate_chip_unlocks_after_mastery(self, page, live_server):
        user = _make_student('unl')
        lang, _, beg, inter, beg_exs, _ = _setup_two_level_lang('unl')

        # Grant full mastery on beginner via DB (simulating correct answers)
        from languages.models import LanguageStudentAnswer, LanguageProgress
        from languages.views import _recalculate_progress
        for ex in beg_exs:
            LanguageStudentAnswer.objects.create(
                student=user, exercise=ex,
                score=100.0, is_correct=True, points_earned=ex.points,
            )
        _recalculate_progress(user, beg)

        do_login(page, live_server.url, user)
        page.goto(_url(live_server, '/languages/'))
        page.locator(f'button[data-lang="{lang.code}"]').click()

        # Intermediate chip should now NOT show lock icon
        inter_chip = page.locator(f'#lang-{lang.code}').get_by_text('Intermediate').first
        expect(inter_chip).to_be_visible()
        expect(inter_chip).not_to_contain_text('🔒')

        # Intermediate exercises should be accessible (not locked placeholder)
        lang_panel = page.locator(f'#lang-{lang.code}')
        # Should not show "Locked" for intermediate once unlocked
        locked_cards = lang_panel.locator('text=Intermediate — Locked')
        expect(locked_cards).to_have_count(0)


@pytest.mark.django_db(transaction=True)
class TestTeacherCreatesLanguageHomework:

    def test_teacher_sees_languages_in_homework_creator(self, page, live_server):
        from classroom.models import ClassRoom, ClassTeacher, School

        teacher = _make_teacher('hw')
        school, _ = School.objects.get_or_create(
            name='HW School 316',
            defaults={'email': 'hws@test.com'},
        )
        classroom, _ = ClassRoom.objects.get_or_create(
            name='HW Class 316', school=school,
        )

        # Link teacher to classroom so _check_teacher_owns_class passes
        ClassTeacher.objects.get_or_create(teacher=teacher, classroom=classroom)

        lang, _, beg, _, beg_exs, _ = _setup_two_level_lang('hwt')

        do_login(page, live_server.url, teacher)

        # Navigate to homework creation with languages subject
        page.goto(_url(live_server, f'/homework/class/{classroom.id}/create/?subject_slug=languages'))

        # Should show the Languages topic tree
        expect(page.locator('body')).to_contain_text('Languages')
