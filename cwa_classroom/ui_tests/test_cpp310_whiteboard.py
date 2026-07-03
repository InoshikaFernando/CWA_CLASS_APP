"""
Playwright UI tests for CPP-310: double-ruled canvas whiteboard for letter writing.

Covers:
1. Canvas renders with ruled lines and guide letter visible
2. Clear button removes drawn strokes
3. Submit saves stroke_data to LanguageStudentAnswer
"""

import pytest
from django.urls import reverse
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp310


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student():
    from accounts.models import CustomUser, Role, UserRole
    uid = f'wb310_{_RUN_ID}'
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


def _make_letter_exercise():
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel, LanguageExercise,
    )
    lang, _ = Language.objects.get_or_create(
        code='en310ui',
        defaults={'name': 'English310UI', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name='Alphabet 310 UI',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    exercise = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.LETTER_WRITING,
        prompt='A',
        points=2,
        is_active=True,
    )
    return exercise


def _wait_for_fabric(page, timeout=15_000):
    """Wait until Fabric.js upper-canvas is visible (confirms fabric loaded and init'd)."""
    page.wait_for_selector('canvas.upper-canvas', state='visible', timeout=timeout)


def _draw_stroke(page):
    """Simulate a freehand stroke on the Fabric upper-canvas.

    Tries real mouse events first; if headless CI canvas interaction doesn't
    trigger Fabric's path:created event, falls back to injecting a Path object
    directly via the Fabric JS API (requires window.__E2E_TEST__ = true so that
    window._fabricCanvas is exposed by whiteboard.js).
    """
    canvas_locator = page.locator('canvas.upper-canvas')
    box = canvas_locator.bounding_box()
    if box and box['width'] > 0:
        start_x = box['x'] + box['width'] * 0.6
        start_y = box['y'] + box['height'] * 0.3
        end_x   = box['x'] + box['width'] * 0.85
        end_y   = box['y'] + box['height'] * 0.7

        page.mouse.move(start_x, start_y)
        page.mouse.down()
        steps = 10
        for i in range(1, steps + 1):
            t = i / steps
            page.mouse.move(
                start_x + (end_x - start_x) * t,
                start_y + (end_y - start_y) * t,
            )
        page.mouse.up()
        page.wait_for_timeout(400)

    # Fallback: inject a Fabric Path if canvas mouse events did not register
    # (common in headless CI where offsetWidth may be 0 or Fabric misses events).
    page.evaluate("""
        () => {
            const fc = window._fabricCanvas;
            if (!fc) return;
            const already = fc.getObjects().filter(o => o.type === 'path').length;
            if (already > 0) return;
            try {
                const p = new fabric.Path('M 20 20 L 180 120 L 300 60', {
                    stroke: '#1a1a1a', fill: 'transparent', strokeWidth: 3
                });
                fc.add(p);
                fc.fire('path:created', { path: p });
            } catch (e) { /* Fabric not ready */ }
        }
    """)
    page.wait_for_timeout(200)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestWhiteboardCanvas:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        self.url = live_server.url
        self.page = page
        self.student = _make_student()
        self.exercise = _make_letter_exercise()
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        # Set E2E flag so whiteboard.js exposes window._fabricCanvas
        page.add_init_script("window.__E2E_TEST__ = true;")
        do_login(page, self.url, self.student)

    @pytest.mark.django_db(transaction=True)
    def test_canvas_renders_with_ruled_lines(self):
        """Canvas visible, Fabric.js initialises, guide char displayed, submit disabled."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        body = self.page.locator('body')
        expect(body).not_to_contain_text('Server Error')
        expect(body).not_to_contain_text('DoesNotExist')

        # Wait for Fabric.js to create the upper-canvas
        _wait_for_fabric(self.page)

        # Both canvases present
        expect(self.page.locator('#drawing-layer')).to_be_attached()
        expect(self.page.locator('canvas.upper-canvas')).to_be_visible()

        # Wrapper and controls
        expect(self.page.locator('#whiteboard-wrapper')).to_be_visible()
        expect(self.page.locator('#guide-char-label')).to_be_visible()
        expect(self.page.locator('#btn-clear')).to_be_visible()
        expect(self.page.locator('#btn-undo')).to_be_visible()
        expect(self.page.locator('#btn-submit')).to_be_visible()

        # Submit disabled until first stroke
        expect(self.page.locator('#btn-submit')).to_be_disabled()

    @pytest.mark.django_db(transaction=True)
    def test_clear_button_resets_drawing(self):
        """After drawing and clicking Clear, Fabric path count returns to 0."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(self.page)

        _draw_stroke(self.page)

        # After stroke: submit should be enabled
        expect(self.page.locator('#btn-submit')).to_be_enabled()

        # Click Clear
        self.page.locator('#btn-clear').click()
        self.page.wait_for_timeout(400)

        # Fabric canvas path count should be 0
        stroke_count = self.page.evaluate("""
            () => {
                const fc = window._fabricCanvas;
                if (!fc) return -1;
                return fc.getObjects().filter(o => o.type === 'path').length;
            }
        """)
        assert stroke_count == 0, f'Expected 0 strokes after clear, got {stroke_count}'

        # Submit disabled again
        expect(self.page.locator('#btn-submit')).to_be_disabled()

    @pytest.mark.django_db(transaction=True)
    def test_submit_saves_stroke_data(self):
        """Drawing and submitting creates a LanguageStudentAnswer with stroke_data."""
        from languages.models import LanguageStudentAnswer

        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(self.page)

        _draw_stroke(self.page)

        expect(self.page.locator('#btn-submit')).to_be_enabled()

        # Capture POST response
        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ) as resp_info:
            self.page.locator('#btn-submit').click()

        resp = resp_info.value
        assert resp.status == 200
        data = resp.json()
        assert data['success'] is True

        # DB record created (is_correct depends on IoU score — not asserted here)
        assert LanguageStudentAnswer.objects.filter(
            student=self.student,
            exercise=self.exercise,
        ).exists()

        # Score panel shown after submit
        score_panel = self.page.locator('#score-panel')
        expect(score_panel).to_be_visible()
