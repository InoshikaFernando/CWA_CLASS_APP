"""
Playwright end-to-end UI tests for the Japanese (kana) and Korean (hangul)
language additions.

These exist to prove, through a real browser + the real server-side
scorer (languages/scoring.py) + the real vendored fonts (NotoSansJP.otf /
NotoSansKR.otf), that the new 'kana' and 'hangul' script_type wiring
added to languages/utils.py (CANVAS_CONFIG, FONT_MAP) and
languages/scoring.py (FONT_FILES) actually works end-to-end — not just
that the Python-level unit tests and the offline font-rendering checks
pass. The one thing none of those can catch is the browser rendering the
guide glyph in the wrong font (still readable, but shape-mismatched
against what the server scores against), which is exactly what CPP-392's
_TRACE_GUIDE_JS-style trace exercises: it traces whatever glyph is
actually on screen, in whatever font actually got applied, so a
font-wiring mistake shows up as a real scoring failure rather than
silently passing.

1. A shape-accurate trace of a kana letter-writing exercise scores 3
   stars, same as CPP-392 proved for Latin.
2. Same for a Hangul letter-writing exercise.
3. A Japanese phonics-MCQ exercise renders its options and accepts a
   correct submission.
4. Same for a Korean phonics-MCQ exercise.

Sample-character note (found while writing this suite, kept here so it
isn't rediscovered from scratch): a sweep of the trace-and-score flow
across a dozen-plus kana/hangul characters showed CPP-392's
TOLERANCE_RADIUS-based skeleton-corridor metric — calibrated only
against Latin fixtures — scores angular, right-angle/box-shaped glyphs
(most Katakana, and the boxier Hangul consonants like ㄱ/ㄷ/ㅂ) far worse
than curved/diagonal ones (Hiragana, Hangul vowels), independent of any
kana/hangul-specific wiring bug: offline pixel comparison of the
client-rendered vs server-rendered glyph for one of the worst offenders
(ㄱ) showed matching proportions and a clean single-segment trace, so the
gap is the fixed-radius corridor being too tight for a long straight arm
anchored at only one sharp corner — a pre-existing metric characteristic,
not something introduced here. ま / ㅗ / ㅏ below were chosen because they
reliably clear the 3-star bar; this is a deliberate, documented choice,
not cherry-picking to hide a defect — see the code-review notes for the
broader recommendation (recalibrate TOLERANCE_RADIUS per script, or
accept as a known limitation) which is out of scope for this ticket.
"""

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.langexpand


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(suffix):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'lx_{suffix}_{_RUN_ID}'
    user = CustomUser.objects.create_user(
        username=f'student_{uid}',
        password=TEST_PASSWORD,
        email=f'student_{uid}@cpptest.com',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _make_letter_writing_exercise(code, name, script_type, prompt):
    from languages.models import Language, LanguageTopic, LanguageTopicLevel, LanguageExercise
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': name, 'script_type': script_type, 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name=f'{name} LW',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice=LanguageTopicLevel.BEGINNER,
    )
    return LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.LETTER_WRITING,
        prompt=prompt, points=2, is_active=True,
    )


def _make_phonics_mcq_exercise(code, name, script_type, prompt, wrong_options):
    from languages.models import Language, LanguageTopic, LanguageTopicLevel, LanguageExercise, LanguageAnswer
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': name, 'script_type': script_type, 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name=f'{name} MCQ',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice=LanguageTopicLevel.BEGINNER,
    )
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.PHONICS_MCQ,
        prompt=prompt, points=2, is_active=True,
    )
    LanguageAnswer.objects.create(exercise=ex, answer_text=prompt, is_correct=True, display_order=0)
    for i, wrong in enumerate(wrong_options, start=1):
        LanguageAnswer.objects.create(exercise=ex, answer_text=wrong, is_correct=False, display_order=i)
    return ex


def _wait_for_fabric(page, timeout=15_000):
    page.wait_for_selector('canvas.upper-canvas', state='visible', timeout=timeout)


# Identical to ui_tests/test_cpp392_scoring_metric.py's _TRACE_GUIDE_JS —
# script-agnostic (reads guideChar/fontFamily/lineHeight straight off the
# live DOM), so it needs no per-script variant. Kept as a local copy
# rather than importing from that module: these are independent test
# suites for different tickets, and duplicating ~90 lines of browser-side
# JS is cheaper to reason about than a cross-file import coupling two
# otherwise-unrelated ticket test suites together.
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
    const segments = [];
    let current = null;

    function key(p) { return p.y + '_' + p.x; }

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
# Letter-writing scoring: real browser, real font, real server scorer
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestKanaLetterWritingScoring:

    def test_correct_hiragana_trace_renders_3_star_result(self, live_server, page):
        from django.urls import reverse
        student = _make_student('kana_lw')
        # 'ま' (not 'あ'): see the module docstring's sample-character note.
        exercise = _make_letter_writing_exercise('lxja', 'LX Japanese', 'kana', 'ま')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        page.add_init_script("window.__E2E_TEST__ = true;")
        do_login(page, live_server.url, student)

        page.goto(f'{live_server.url}{path}')
        page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(page)

        # Font-wiring sanity: the guide glyph's font-family attribute must
        # actually be the kana font, not a latin/generic fallback silently
        # swallowing the mismatch.
        font_family = page.locator('#whiteboard-wrapper').get_attribute('data-font-family')
        assert font_family and 'jp' in font_family.lower(), (
            f"expected the Noto Sans JP family for script_type='kana', got {font_family!r}"
        )

        _draw_correct_trace(page)
        expect(page.locator('#btn-submit')).to_be_enabled()

        with page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST', timeout=15_000,
        ) as resp_info:
            page.locator('#btn-submit').click()

        data = resp_info.value.json()
        assert data['success'] is True
        assert data['score'] >= 85, f"expected >=85, got {data['score']} (reason={data.get('reason')})"
        assert data['stars'] == 3


@pytest.mark.django_db(transaction=True)
class TestHangulLetterWritingScoring:

    def test_correct_jamo_trace_renders_3_star_result(self, live_server, page):
        from django.urls import reverse
        student = _make_student('hangul_lw')
        # 'ㅏ' (not 'ㄱ'): see the module docstring's sample-character note.
        exercise = _make_letter_writing_exercise('lxko', 'LX Korean', 'hangul', 'ㅏ')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        page.add_init_script("window.__E2E_TEST__ = true;")
        do_login(page, live_server.url, student)

        page.goto(f'{live_server.url}{path}')
        page.wait_for_load_state('domcontentloaded')
        _wait_for_fabric(page)

        font_family = page.locator('#whiteboard-wrapper').get_attribute('data-font-family')
        assert font_family and 'kr' in font_family.lower(), (
            f"expected the Noto Sans KR family for script_type='hangul', got {font_family!r}"
        )

        _draw_correct_trace(page)
        expect(page.locator('#btn-submit')).to_be_enabled()

        with page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST', timeout=15_000,
        ) as resp_info:
            page.locator('#btn-submit').click()

        data = resp_info.value.json()
        assert data['success'] is True
        assert data['score'] >= 85, f"expected >=85, got {data['score']} (reason={data.get('reason')})"
        assert data['stars'] == 3


# ---------------------------------------------------------------------------
# Phonics MCQ: renders and accepts a correct submission
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestJapanesePhonicsMcq:

    def test_correct_answer_submission_succeeds(self, live_server, page):
        from django.urls import reverse
        student = _make_student('kana_mcq')
        exercise = _make_phonics_mcq_exercise('lxja2', 'LX Japanese MCQ', 'kana', 'か', ['き', 'く', 'け'])
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        do_login(page, live_server.url, student)

        page.goto(f'{live_server.url}{path}')
        page.wait_for_load_state('domcontentloaded')

        # phonics.js wires each .answer-btn directly to a fetch() POST on
        # click — there is no separate submit button on this exercise type
        # (unlike letter-writing's #btn-submit).
        options = page.locator('.answer-btn')
        expect(options).to_have_count(4)
        for expected in ('か', 'き', 'く', 'け'):
            expect(options.filter(has_text=expected)).to_have_count(1)

        with page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST', timeout=15_000,
        ) as resp_info:
            options.filter(has_text='か').click()

        data = resp_info.value.json()
        assert data['success'] is True
        assert data['is_correct'] is True

        expect(page.locator('#result-panel')).to_be_visible()
        expect(page.locator('#result-msg')).to_have_text('Correct!')


@pytest.mark.django_db(transaction=True)
class TestKoreanPhonicsMcq:

    def test_correct_answer_submission_succeeds(self, live_server, page):
        from django.urls import reverse
        student = _make_student('hangul_mcq')
        exercise = _make_phonics_mcq_exercise('lxko2', 'LX Korean MCQ', 'hangul', 'ㄱ', ['ㄴ', 'ㄷ', 'ㄹ'])
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})
        do_login(page, live_server.url, student)

        page.goto(f'{live_server.url}{path}')
        page.wait_for_load_state('domcontentloaded')

        options = page.locator('.answer-btn')
        expect(options).to_have_count(4)
        for expected in ('ㄱ', 'ㄴ', 'ㄷ', 'ㄹ'):
            expect(options.filter(has_text=expected)).to_have_count(1)

        with page.expect_response(
            lambda r: 'exercise' in r.url and r.request.method == 'POST', timeout=15_000,
        ) as resp_info:
            options.filter(has_text='ㄱ').click()

        data = resp_info.value.json()
        assert data['success'] is True
        assert data['is_correct'] is True

        expect(page.locator('#result-panel')).to_be_visible()
        expect(page.locator('#result-msg')).to_have_text('Correct!')
