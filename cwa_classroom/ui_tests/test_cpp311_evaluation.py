"""
Playwright UI tests for CPP-311: IoU-based handwriting evaluation.

Covers:
1. Score panel hidden before submit
2. Score panel displayed after submit
3. Retry clears canvas and hides score panel
4. Retry allows resubmit (submit enabled after new stroke)
"""

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp311


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student():
    from accounts.models import CustomUser, Role, UserRole
    uid = f'wb311_{_RUN_ID}'
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


def _make_exercise():
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel, LanguageExercise,
    )
    lang, _ = Language.objects.get_or_create(
        code='en311ui',
        defaults={'name': 'English311UI', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name='Alphabet 311 UI',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    return LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.LETTER_WRITING,
        prompt='A',
        points=2,
        is_active=True,
    )


def _wait_for_fabric(page, timeout=15_000):
    page.wait_for_selector('canvas.upper-canvas', state='visible', timeout=timeout)


def _draw_stroke(page):
    canvas = page.locator('canvas.upper-canvas')
    box = canvas.bounding_box()
    if not box:
        return
    sx = box['x'] + box['width'] * 0.6
    sy = box['y'] + box['height'] * 0.3
    ex = box['x'] + box['width'] * 0.85
    ey = box['y'] + box['height'] * 0.7

    page.mouse.move(sx, sy)
    page.mouse.down()
    for i in range(1, 11):
        t = i / 10
        page.mouse.move(sx + (ex - sx) * t, sy + (ey - sy) * t)
    page.mouse.up()
    page.wait_for_timeout(400)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestHandwritingEvaluation:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student()
        self.exercise = _make_exercise()
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        page.add_init_script("window.__E2E_TEST__ = true;")
        do_login(page, self.url, self.student)

    @pytest.mark.django_db(transaction=True)
    def test_score_panel_hidden_before_submit(self):
        """Score panel must not be visible on initial page load."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(self.page)

        score_panel = self.page.locator('#score-panel')
        expect(score_panel).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_score_panel_displayed_after_submit(self):
        """After drawing and submitting, score panel becomes visible with star elements."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(self.page)

        _draw_stroke(self.page)
        expect(self.page.locator('#btn-submit')).to_be_enabled()

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ):
            self.page.locator('#btn-submit').click()

        self.page.wait_for_timeout(500)

        score_panel = self.page.locator('#score-panel')
        expect(score_panel).to_be_visible()

        # Score percentage shown
        expect(self.page.locator('#score-pct')).not_to_have_text('')

        # Message shown
        expect(self.page.locator('#score-msg')).to_be_visible()

        # Best badge shown
        expect(self.page.locator('#best-badge')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_retry_clears_canvas_and_hides_score_panel(self):
        """Clicking Try Again hides the score panel and clears strokes."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(self.page)

        _draw_stroke(self.page)

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ):
            self.page.locator('#btn-submit').click()

        self.page.wait_for_timeout(500)

        expect(self.page.locator('#score-panel')).to_be_visible()

        # Click Retry
        self.page.locator('#btn-retry').click()
        self.page.wait_for_timeout(300)

        expect(self.page.locator('#score-panel')).to_be_hidden()

        # Canvas strokes cleared
        stroke_count = self.page.evaluate("""
            () => {
                const fc = window._fabricCanvas;
                if (!fc) return -1;
                return fc.getObjects().filter(o => o.type === 'path').length;
            }
        """)
        assert stroke_count == 0, f'Expected 0 strokes after retry, got {stroke_count}'

    @pytest.mark.django_db(transaction=True)
    def test_retry_allows_resubmit(self):
        """After Retry, drawing again and submitting succeeds."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(self.page)

        # First submit
        _draw_stroke(self.page)
        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ):
            self.page.locator('#btn-submit').click()

        self.page.wait_for_timeout(500)
        self.page.locator('#btn-retry').click()
        self.page.wait_for_timeout(300)

        # Second submit
        _draw_stroke(self.page)
        expect(self.page.locator('#btn-submit')).to_be_enabled()

        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ) as resp_info:
            self.page.locator('#btn-submit').click()

        resp = resp_info.value
        assert resp.status == 200
        data = resp.json()
        assert data['success'] is True

        self.page.wait_for_timeout(300)
        expect(self.page.locator('#score-panel')).to_be_visible()
