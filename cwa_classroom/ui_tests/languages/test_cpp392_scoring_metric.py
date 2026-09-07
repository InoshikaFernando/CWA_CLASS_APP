"""
Playwright UI tests for CPP-392: skeleton-corridor handwriting scoring metric.

CPP-311's original evaluation test only checked that the score panel
becomes visible after submit — it never asserted on the actual star count,
because under the old raw pixel-IoU metric even a well-formed character
couldn't reliably reach 3 stars (that was the bug). This file specifically
covers the fixed behaviour end-to-end through a real browser + the real
server-side scorer (languages/scoring.py):

1. A trace that actually follows the target glyph's shape renders the
   3-star result (the AC's core "no longer demotivating" requirement).
2. The feedback tip reflects the real outcome, not the old canned
   "fill the canvas height" message.
"""

import pytest
from playwright.sync_api import expect

from ..conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp392


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student():
    from accounts.models import CustomUser, Role, UserRole
    uid = f'wb392_{_RUN_ID}'
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


def _make_exercise(prompt='A'):
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel, LanguageExercise,
    )
    lang, _ = Language.objects.get_or_create(
        code='en392ui',
        defaults={'name': 'English392UI', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name='Alphabet 392 UI',
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


def _wait_for_fabric(page, timeout=15_000):
    page.wait_for_selector('canvas.upper-canvas', state='visible', timeout=timeout)


# Traces the actual on-screen guide glyph's skeleton and injects it as a
# single fabric.Path — a synthetic but *shape-accurate* "correct" stroke,
# so the test's pass/fail genuinely depends on the scorer recognising a
# well-formed letter rather than on a real mouse being able to draw one
# pixel-perfectly. Self-contained (doesn't reach into whiteboard.js
# internals) so it can't silently drift out of sync with production code
# without the assertion catching it.
_TRACE_GUIDE_JS = """
async () => {
    const wrapper = document.getElementById('whiteboard-wrapper');
    const fc = window._fabricCanvas;
    if (!wrapper || !fc) return false;

    const lineHeight = parseInt(wrapper.dataset.lineHeight, 10);
    const descender  = parseInt(wrapper.dataset.descender, 10);
    const guideChar  = wrapper.dataset.guideChar;
    const fontFamily = wrapper.dataset.fontFamily || 'sans-serif';
    const TOP_PAD = 24;
    const W = wrapper.offsetWidth || 600;
    const H = TOP_PAD + lineHeight + descender + TOP_PAD;
    const FONT_SIZE = Math.floor(lineHeight * 0.9);
    const BASE_Y = TOP_PAD + lineHeight;
    const fontSpec = 'bold ' + FONT_SIZE + 'px ' + fontFamily + ', sans-serif';

    // Must match the same font whiteboard.js's guide render (and the
    // server's vendored font) actually use — without this, the trace can
    // be built against a system sans-serif fallback that hasn't finished
    // swapping for the real webfont yet, shape-mismatching the server's
    // template and scoring low for reasons unrelated to the metric itself.
    if (document.fonts) {
        try { await document.fonts.load(fontSpec, guideChar); } catch (e) {}
        try { await document.fonts.ready; } catch (e) {}
    }

    const off = document.createElement('canvas');
    off.width = W; off.height = H;
    const ctx = off.getContext('2d');
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);
    ctx.font = fontSpec;
    ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = '#000000';
    ctx.fillText(guideChar, W / 2, BASE_Y);

    const data = ctx.getImageData(0, 0, W, H).data;
    const mask = new Uint8Array(W * H);
    for (let i = 0; i < W * H; i++) {
        const lum = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
        mask[i] = lum < 128 ? 1 : 0;
    }

    function thin(src, w, h) {
        const px = Uint8Array.from(src);
        let changed = true;
        while (changed) {
            changed = false;
            for (let pass = 0; pass < 2; pass++) {
                const rem = [];
                for (let y = 1; y < h - 1; y++) {
                    for (let x = 1; x < w - 1; x++) {
                        if (!px[y * w + x]) continue;
                        const p2 = px[(y-1)*w+x],   p3 = px[(y-1)*w+x+1];
                        const p4 = px[ y   *w+x+1], p5 = px[(y+1)*w+x+1];
                        const p6 = px[(y+1)*w+x],   p7 = px[(y+1)*w+x-1];
                        const p8 = px[ y   *w+x-1], p9 = px[(y-1)*w+x-1];
                        const B = p2+p3+p4+p5+p6+p7+p8+p9;
                        if (B < 2 || B > 6) continue;
                        const A = (!p2&&p3?1:0)+(!p3&&p4?1:0)+(!p4&&p5?1:0)+(!p5&&p6?1:0)+
                                  (!p6&&p7?1:0)+(!p7&&p8?1:0)+(!p8&&p9?1:0)+(!p9&&p2?1:0);
                        if (A !== 1) continue;
                        if (pass === 0 && (p2*p4*p6 || p4*p6*p8)) continue;
                        if (pass === 1 && (p2*p4*p8 || p2*p6*p8)) continue;
                        rem.push(y * w + x);
                    }
                }
                rem.forEach(i => { px[i] = 0; changed = true; });
            }
        }
        return px;
    }

    const skel = thin(mask, W, H);

    // Walk the skeleton via actual 8-connectivity adjacency (same approach
    // as whiteboard.js's own guide-animation traceSkeleton()) rather than
    // nearest-any-point ordering — a global nearest-neighbour chain can
    // jump between unrelated branches at junctions (e.g. "A"'s apex/
    // crossbar), drawing spurious straight lines across empty space that
    // the real algorithm correctly penalises as ink outside the shape.
    const ptMap = {};
    const pts = [];
    for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
            if (skel[y * W + x]) { ptMap[y + '_' + x] = 1; pts.push({ x, y }); }
        }
    }
    if (!pts.length) return false;

    function neighbours(p) {
        const n = [];
        for (let dy = -1; dy <= 1; dy++)
            for (let dx = -1; dx <= 1; dx++)
                if ((dx || dy) && ptMap[(p.y + dy) + '_' + (p.x + dx)]) n.push({ x: p.x + dx, y: p.y + dy });
        return n;
    }

    const visited = {};
    const segments = []; // each: array of {x,y} forming one continuous stroke
    let current = null;

    function key(p) { return p.y + '_' + p.x; }

    // DFS from an endpoint when available (cleaner traversal order), else
    // any unvisited point — starting a new segment (pen lift) whenever the
    // walk has to jump to a non-adjacent point.
    const endpoints = pts.filter(p => !visited[key(p)] && neighbours(p).length === 1);
    const startOrder = endpoints.length ? endpoints.concat(pts) : pts;

    for (const startCandidate of startOrder) {
        if (visited[key(startCandidate)]) continue;
        let p = startCandidate;
        current = [p];
        visited[key(p)] = 1;
        while (true) {
            const next = neighbours(p).find(n => !visited[key(n)]);
            if (!next) break;
            visited[key(next)] = 1;
            current.push(next);
            p = next;
        }
        if (current.length > 1) segments.push(current);
    }
    if (!segments.length) return false;

    let d = '';
    for (const seg of segments) {
        d += (d ? ' ' : '') + 'M ' + seg[0].x + ' ' + seg[0].y;
        for (let k = 1; k < seg.length; k++) d += ' L ' + seg[k].x + ' ' + seg[k].y;
    }

    const tracedPath = new fabric.Path(d, { stroke: '#1a1a1a', fill: 'transparent', strokeWidth: 4 });
    fc.add(tracedPath);
    fc.fire('path:created', { path: tracedPath });
    return true;
}
"""


def _draw_correct_trace(page):
    ok = page.evaluate(_TRACE_GUIDE_JS)
    assert ok, 'failed to build a shape-accurate trace of the guide glyph in-browser'
    page.wait_for_timeout(200)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestScoringMetric:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student()
        self.exercise = _make_exercise('A')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        page.add_init_script("window.__E2E_TEST__ = true;")
        do_login(page, self.url, self.student)

    @pytest.mark.django_db(transaction=True)
    def test_correct_trace_renders_3_star_result(self):
        """A trace that actually follows the guide glyph's shape must render
        the full 3-star result — the exact behaviour CPP-392 was filed over
        (correct characters were stuck at 1 star / ~50-60%)."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(self.page)

        _draw_correct_trace(self.page)
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
        assert data['score'] >= 85, f"expected >=85, got {data['score']} (reason={data.get('reason')})"
        assert data['stars'] == 3
        assert data['reason'] == 'excellent_match'

        self.page.wait_for_timeout(900)

        expect(self.page.locator('#score-panel')).to_be_visible()
        expect(self.page.locator('#score-pct')).to_have_text('%'.join([str(data['score']), '']))

        stars = self.page.locator('.wb-star')
        for i in range(3):
            color = stars.nth(i).evaluate('el => el.style.color')
            assert color in ('rgb(245, 158, 11)', '#f59e0b'), f'star {i} not gold: {color}'

    @pytest.mark.django_db(transaction=True)
    def test_feedback_tip_is_not_the_old_canned_canvas_height_message(self):
        """The pre-fix bug: every 1-star result showed the same canned 'fill
        the canvas height' tip regardless of cause, contradicting the
        instructions' promise that size is adjusted automatically."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(self.page)

        _draw_correct_trace(self.page)
        with self.page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST',
            timeout=15_000,
        ):
            self.page.locator('#btn-submit').click()

        self.page.wait_for_timeout(900)

        tip_text = self.page.locator('#score-tip').inner_text()
        assert 'fill the canvas height' not in tip_text.lower()
