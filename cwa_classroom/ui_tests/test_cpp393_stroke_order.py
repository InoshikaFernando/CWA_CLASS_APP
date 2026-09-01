"""
Playwright UI tests for CPP-393: authored stroke-order guide animation.

CPP-311/310's guide animation derived stroke order from raster-scan order
of a skeletonised glyph — script-agnostic and wrong for every letter (see
languages/static/languages/js/stroke_order.js's module doc). This file
drives the real browser engine (window.StrokeOrder, loaded from
stroke_order.js/stroke_order_data.js by the actual exercise page) to
verify:

1. The engine resolves an authored path for the guide character in each
   of the three seeded languages — i.e. driven by data, not a fallback.
2. The first stroke of "A" starts in the lower-left quadrant and ends near
   the apex (catches a reversed or reordered first stroke — CPP-393 AC).
3. Coverage: every part of the glyph skeleton is within tolerance of some
   authored stroke, so no part of the letter is left undrawn.
"""
import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp393


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(suffix):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'wb393{suffix}_{_RUN_ID}'
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


def _make_exercise(prompt, script_type, suffix):
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel, LanguageExercise,
    )
    lang, _ = Language.objects.get_or_create(
        code=f'lw393{suffix}',
        defaults={'name': f'LW393{suffix}', 'script_type': script_type, 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'Alphabet 393 {suffix}',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    return LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.LETTER_WRITING,
        prompt=prompt,
        points=2,
        is_active=True,
    )


# Resolves the guide character's stroke order in-browser using the same
# parameters whiteboard.js's own animation IIFE derives from the wrapper's
# dataset — small, acceptable duplication (arithmetic only) rather than
# reaching into whiteboard.js's closure, which exposes nothing for tests.
_RESOLVE_GUIDE_JS = """
async () => {
    const wrapper = document.getElementById('whiteboard-wrapper');
    if (!wrapper || !window.StrokeOrder || !window.STROKE_ORDER_DATA) return null;

    const lineHeight = parseInt(wrapper.dataset.lineHeight, 10);
    const guideChar   = wrapper.dataset.guideChar;
    const fontFamily  = wrapper.dataset.fontFamily || 'sans-serif';
    const scriptType  = wrapper.dataset.scriptType || 'latin';

    const AW = 240, AH = 160;
    const A_TOP_PAD = 18;
    const A_LH = AH - A_TOP_PAD * 2 - 20;
    const A_BASE_Y = A_TOP_PAD + A_LH;
    const fSize = Math.floor(A_LH * 0.88);
    const fontSpec = 'bold ' + fSize + 'px ' + fontFamily + ', sans-serif';

    if (document.fonts) {
        try { await document.fonts.load(fontSpec, guideChar); } catch (e) {}
        try { await document.fonts.ready; } catch (e) {}
    }

    const strokeData = window.STROKE_ORDER_DATA[scriptType] && window.STROKE_ORDER_DATA[scriptType][guideChar];
    if (!strokeData) return { resolved: false, reason: 'no_stroke_data' };

    const resolved = window.StrokeOrder.resolve({
        strokes: strokeData, char: guideChar, fontSpec,
        w: AW, h: AH, baseX: AW / 2, baseY: A_BASE_Y,
    });
    if (!resolved) return { resolved: false, reason: 'engine_returned_null' };

    return {
        resolved: true,
        strokeCount: resolved.strokes.length,
        strokes: resolved.strokes,
        w: resolved.w,
        h: resolved.h,
        bbox: resolved.bbox,
        coverage: window.StrokeOrder.coverageRatio(resolved, 6),
    };
}
"""


def _goto_exercise(page, url):
    page.goto(url)
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_selector('#guide-anim', state='attached', timeout=15_000)


# ---------------------------------------------------------------------------
# 1. Engine resolves a path (not the fallback) for each seeded language
# ---------------------------------------------------------------------------

class TestEngineResolvesAuthoredPath:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page):
        self.url = live_server.url
        self.page = page

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize('prompt,script_type,suffix', [
        ('A', 'latin', '393a'),
        ('ක', 'sinhala', '393b'),
        ('அ', 'tamil', '393c'),
    ])
    def test_resolves_for_each_language(self, prompt, script_type, suffix):
        from django.urls import reverse

        student = _make_student(suffix)
        exercise = _make_exercise(prompt, script_type, suffix)
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        do_login(self.page, self.url, student)

        _goto_exercise(self.page, f'{self.url}{path}')
        result = self.page.evaluate(_RESOLVE_GUIDE_JS)

        assert result is not None, 'StrokeOrder / STROKE_ORDER_DATA not loaded on the page'
        assert result['resolved'] is True, (
            f"expected the stroke-order engine to resolve a path for "
            f"{prompt!r} ({script_type}), got: {result}"
        )
        assert result['strokeCount'] >= 1


# ---------------------------------------------------------------------------
# 2. First stroke of "A": lower-left quadrant -> near the apex
# ---------------------------------------------------------------------------

class TestFirstStrokeOfA:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student('393d')
        self.exercise = _make_exercise('A', 'latin', '393d')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        do_login(self.page, self.url, self.student)
        _goto_exercise(self.page, f'{self.url}{path}')

    @pytest.mark.django_db(transaction=True)
    def test_first_stroke_starts_lower_left_ends_near_apex(self):
        result = self.page.evaluate(_RESOLVE_GUIDE_JS)
        assert result['resolved'] is True

        # Judge "lower-left" / "near the apex" against the glyph's own ink
        # bounding box, not the full animation canvas — the canvas has
        # padding above/below the letterform (room for a baseline, a
        # descender band a capital "A" doesn't use, etc.), so a fraction
        # of canvas height doesn't correspond to a fraction of the letter.
        bbox = result['bbox']
        bw = bbox['maxX'] - bbox['minX']
        bh = bbox['maxY'] - bbox['minY']
        mid_x = bbox['minX'] + bw * 0.5
        low_y = bbox['minY'] + bh * 0.5
        apex_y = bbox['minY'] + bh * 0.35

        first_stroke = result['strokes'][0]
        start, end = first_stroke[0], first_stroke[-1]

        # Lower-left quadrant: left half of the glyph box, bottom half.
        assert start['x'] < mid_x, f"first stroke should start on the left, got x={start['x']} (mid={mid_x})"
        assert start['y'] > low_y, f"first stroke should start low, got y={start['y']} (mid={low_y})"

        # Near the apex: top ~35% of the glyph's own height, roughly centred.
        assert end['y'] < apex_y, f"first stroke should end near the top (apex), got y={end['y']} (threshold={apex_y})"
        assert bbox['minX'] + bw * 0.2 < end['x'] < bbox['minX'] + bw * 0.8, \
            f"first stroke should end near horizontal centre, got x={end['x']}"


# ---------------------------------------------------------------------------
# 3. Coverage: authored strokes leave no part of the glyph undrawn
# ---------------------------------------------------------------------------

class TestCoverage:
    """
    Coverage bar differs by script:

    - latin: 0.9 — data is hand-authored, so a real letter (with genuine
      shape complexity — "E" has 4 strokes and sharp corners) should
      leave very little of the skeleton undrawn.
    - sinhala/tamil: 0.4 — data is a uniform TEMPLATE-GENERATED placeholder
      (see stroke_order_data.js's header), not tuned per letter, so
      coverage genuinely varies by how well a generic loop/curve happens
      to fit each specific glyph (observed 53-99% across a few characters
      sampled during development). A low bar here still catches the
      real regressions this test exists for — no data at all (coverage 0)
      or the engine failing outright — without pretending untuned
      placeholder data is as complete as the hand-authored English set.
      RAISE THIS to 0.9, matching latin, once a native writer has
      corrected the Sinhala/Tamil entries per CPP-393's AC.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page):
        self.url = live_server.url
        self.page = page

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize('prompt,script_type,suffix,min_coverage', [
        ('E', 'latin', '393e', 0.9),
        ('ම', 'sinhala', '393f', 0.4),
        ('க', 'tamil', '393g', 0.4),
    ])
    def test_coverage_ratio(self, prompt, script_type, suffix, min_coverage):
        from django.urls import reverse

        student = _make_student(suffix)
        exercise = _make_exercise(prompt, script_type, suffix)
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        do_login(self.page, self.url, student)

        _goto_exercise(self.page, f'{self.url}{path}')
        result = self.page.evaluate(_RESOLVE_GUIDE_JS)

        assert result['resolved'] is True
        assert result['coverage'] >= min_coverage, (
            f"{prompt!r} ({script_type}): only {result['coverage']:.0%} of the glyph "
            f"skeleton is within tolerance of an authored stroke (need >= {min_coverage:.0%}) "
            f"— part of the letter would be left undrawn by the animation"
        )
