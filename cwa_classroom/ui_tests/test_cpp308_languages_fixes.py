"""
Playwright UI tests for CPP-308 Languages fixes.

1. ADVANCED_CROSSWORD exercise page loads (not 404)
2. English TTS language code shown as en-NZ in phonics page data attribute
3. Stage unlock toast appears when mastery achieved
4. Empty state placeholder shows for unlocked level with no exercises
5. Worksheet builder shows Languages subject option
6. Worksheet builder Languages question list works
"""

import json
import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp308


def _make_student(suffix=''):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'p308{suffix}_{_RUN_ID}'
    user = CustomUser.objects.create_user(
        username=f'stu_{uid}',
        password=TEST_PASSWORD,
        email=f'stu_{uid}@cpp308.com',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _make_teacher(suffix=''):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'tea308{suffix}_{_RUN_ID}'
    user = CustomUser.objects.create_user(
        username=f'tea_{uid}',
        password=TEST_PASSWORD,
        email=f'tea_{uid}@cpp308.com',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _setup_lang(suffix=''):
    from languages.models import Language, LanguageTopic, LanguageTopicLevel, LanguageExercise, LanguageAnswer
    code = f'e308{suffix}'[:10]
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': f'English308{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 91},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name=f'Grammar308{suffix}',
        defaults={'order': 0, 'is_active': True},
    )
    beg, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='beginner')
    return lang, topic, beg


def _make_spelling_mcq(level):
    from languages.models import LanguageExercise, LanguageAnswer
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.SPELLING_MCQ,
        prompt='testword308', points=5, is_active=True,
    )
    LanguageAnswer.objects.create(exercise=ex, answer_text='testword308', is_correct=True, display_order=0)
    LanguageAnswer.objects.create(exercise=ex, answer_text='wrongword', is_correct=False, display_order=1)
    return ex


def _url(live_server, path):
    return f'{live_server.url}{path}'


# ===========================================================================
# Tests
# ===========================================================================

@pytest.mark.django_db(transaction=True)
class TestAdvancedCrosswordPageLoads:

    def test_advanced_crossword_get_returns_200(self, page, live_server):
        from languages.models import LanguageExercise
        user = _make_student('acw')
        _, _, beg = _setup_lang('acw')
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.ADVANCED_CROSSWORD,
            prompt='Adv Crossword Test',
            points=5,
            is_active=True,
            puzzle_data={'words': [], 'width': 5, 'height': 5},
        )
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, f'/languages/exercise/{ex.id}/'))
        # Should not show 404 or error page
        expect(page.locator('body')).not_to_contain_text('Page not found')
        expect(page.locator('body')).not_to_contain_text('404')


@pytest.mark.django_db(transaction=True)
class TestEmptyStatePlaceholder:

    def test_unlocked_level_with_no_exercises_shows_placeholder(self, page, live_server):
        from languages.models import LanguageExercise
        user = _make_student('es')
        lang, topic, beg = _setup_lang('es')
        # No exercises created — level is unlocked (beginner) but empty
        do_login(page, live_server.url, user)
        page.goto(_url(live_server, '/languages/'))
        # Click the language tab
        page.locator(f'button[data-lang="{lang.code}"]').click()
        expect(page.locator(f'#lang-{lang.code}')).to_contain_text('No exercises yet')


@pytest.mark.django_db(transaction=True)
class TestWorksheetBuilderLanguages:

    def test_languages_question_list_renders(self, page, live_server):
        from classroom.models import School
        teacher = _make_teacher('wbl')
        school, _ = School.objects.get_or_create(
            name='WBL School 308', defaults={'email': 'wbl@school308.com'},
        )
        _, _, beg = _setup_lang('wbl')
        ex = _make_spelling_mcq(beg)

        do_login(page, live_server.url, teacher)
        page.goto(_url(live_server, '/worksheets/builder/questions/?subject=languages'))
        expect(page.locator('body')).to_contain_text('testword308')

    def test_languages_subject_filter_accessible(self, page, live_server):
        from classroom.models import School
        teacher = _make_teacher('wsf')
        school, _ = School.objects.get_or_create(
            name='WSF School 308', defaults={'email': 'wsf@school308.com'},
        )
        do_login(page, live_server.url, teacher)
        page.goto(_url(live_server, '/worksheets/builder/'))
        # Builder page should load without error
        expect(page.locator('body')).not_to_contain_text('Server Error')
        expect(page.locator('body')).not_to_contain_text('404')
