"""
Unit tests for CPP-392: skeleton-corridor handwriting scoring metric.

CPP-311's raw pixel-IoU metric compared a thin pen stroke against a
solid-filled font glyph, so even a perfectly traced letter topped out around
50-60% IoU (the fill area vastly outweighs the stroke area) — every
character, every script. These tests exercise the replacement metric
(languages/scoring.py) directly against synthetic ink so they don't depend
on a browser: a "correct" trace is built by skeletonising the target glyph
itself and dilating it back out to pen width, which is exactly what a
well-formed handwritten trace looks like once digitised.

Tests:
  TestCorrectCharacterScoresHigh  — straight/curved/complex glyphs, 3 scripts
  TestSizeAndPositionInvariance   — same correct trace, small/large/off-centre
  TestWrongCharacterScoresLow     — drew a different letter than the target
  TestScribbleScoresLow           — random strokes, not a letter at all
  TestReasonCodes                 — reason reflects the actual deduction cause
  TestViewIntegration             — POST a real PNG through the Django view
"""
import base64
import io

import numpy as np
import pytest
from django.test import Client
from django.urls import reverse
from PIL import Image, ImageDraw

from accounts.models import CustomUser, Role, UserRole
from languages import scoring
from languages.models import (
    Language,
    LanguageExercise,
    LanguageStudentAnswer,
    LanguageTopic,
    LanguageTopicLevel,
)

pytestmark = pytest.mark.cpp392

# Imported rather than hand-copied: a hand-copied config here previously
# drifted from the real CANVAS_CONFIG (still said Sinhala/Tamil descender=0
# after the real config was fixed to 36/39 to stop clipping tall glyphs),
# so these tests kept exercising a canvas shape production no longer uses.
from languages.utils import CANVAS_CONFIG

LATIN_CONFIG   = CANVAS_CONFIG['latin']
SINHALA_CONFIG = CANVAS_CONFIG['sinhala']
TAMIL_CONFIG   = CANVAS_CONFIG['tamil']

CONFIG_FOR_SCRIPT = {
    'latin':   LATIN_CONFIG,
    'sinhala': SINHALA_CONFIG,
    'tamil':   TAMIL_CONFIG,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _template(char, script_type='latin'):
    return scoring.render_glyph_mask(char, script_type, CONFIG_FOR_SCRIPT[script_type])


def _clean_trace_normalized(char, script_type='latin', pen_r=3):
    """A digitised 'well-formed' trace, built at the *same* resolution
    score_masks() itself skeletonises at: normalize the template once
    (matching what score_masks does internally for the template side),
    skeletonise that, then dilate back out to a plausible pen width.

    Returns (student_n, template_n) — both already normalized, for use
    with scoring._score_normalized() directly.

    Building the trace by skeletonising the *raw*, low-resolution glyph
    render instead (or by normalizing into a second, separate box and
    handing the result to score_masks(), which would normalize it again)
    both distort the result: Zhang-Suen thinning needs enough resolution
    to fully collapse a moderately-thick diagonal stroke to a true 1px
    centreline, and each independent crop-to-bbox+rescale pass shifts a
    dilated shape's effective bounding box slightly, which compounds into
    real misalignment for narrow-bbox glyphs (e.g. "L") across two passes.
    """
    template_n = scoring._normalize(_template(char, script_type))
    skeleton = scoring._skeletonize(template_n)
    student_n = scoring._dilate(skeleton, pen_r)
    return student_n, template_n


def _correct_trace_raw(char, script_type='latin', pen_r=3, scale=1.0, offset=(0, 0), canvas=600):
    """A raw (un-normalized) canvas placement of a clean correct trace, for
    exercising score_masks()'s own single normalize call at a given scale/
    position — i.e. this is what a real posted ink image would look like,
    not a pre-normalized fixture."""
    student_n, _ = _clean_trace_normalized(char, script_type, pen_r)
    img = Image.fromarray(student_n.astype(np.uint8) * 255)
    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    resized = img.resize(new_size, Image.NEAREST)
    out = Image.new('L', (canvas, canvas), 0)
    ox = canvas // 2 - new_size[0] // 2 + offset[0]
    oy = canvas // 2 - new_size[1] // 2 + offset[1]
    out.paste(resized, (ox, oy))
    return np.asarray(out) > 127


def _scribble(seed, w=600, h=600, n_lines=40):
    rng = np.random.default_rng(seed)
    img = Image.new('L', (w, h), 0)
    draw = ImageDraw.Draw(img)
    for _ in range(n_lines):
        x0, y0 = rng.integers(0, w), rng.integers(0, h)
        x1, y1 = rng.integers(0, w), rng.integers(0, h)
        draw.line([(x0, y0), (x1, y1)], fill=255, width=3)
    return np.asarray(img) > 127


def _mask_to_png_b64(mask):
    img = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8), mode='L').convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('ascii')


# ---------------------------------------------------------------------------
# Correct character → high score, across shape families and scripts
# ---------------------------------------------------------------------------

class TestCorrectCharacterScoresHigh:

    @pytest.mark.parametrize('char', ['A', 'L', 'C', 'O', 'R', 'g'])
    def test_latin_shape_families(self, char):
        student_n, template_n = _clean_trace_normalized(char, 'latin')
        score, reason = scoring._score_normalized(student_n, template_n)
        assert score >= 85, f"'{char}' scored {score} (reason={reason}), expected >=85"

    @pytest.mark.parametrize('char', ['අ', 'ක', 'ම'])  # a, ka, ma
    def test_sinhala(self, char):
        student_n, template_n = _clean_trace_normalized(char, 'sinhala')
        score, reason = scoring._score_normalized(student_n, template_n)
        assert score >= 85, f"sinhala '{char}' scored {score} (reason={reason})"

    @pytest.mark.parametrize('char', ['அ', 'க', 'ம'])  # a, ka, ma
    def test_tamil(self, char):
        student_n, template_n = _clean_trace_normalized(char, 'tamil')
        score, reason = scoring._score_normalized(student_n, template_n)
        assert score >= 85, f"tamil '{char}' scored {score} (reason={reason})"

    @pytest.mark.parametrize('char,script_type', [
        ('l', 'latin'), ('一', 'cjk'), ('丨', 'cjk'), ('ㅡ', 'hangul'), ('ㅣ', 'hangul'),
    ])
    def test_bare_single_straight_stroke_letters(self, char, script_type):
        """Regression: a real student submission of correctly-drawn Hangul
        ㅣ scored 0% ('too_little_ink'). The degenerate-ink guard in
        _score_normalized() rejected anything filling >40% of its own
        bounding box as a dot/tap, on the assumption a real stroke never
        fills that much of its bbox -- true for bent/curved letters, but a
        single straight, unbent stroke's bbox IS essentially just the
        stroke, so it legitimately fills 88-100% of its own bbox exactly
        like a dot does. Swept every seeded character across every
        language and found exactly these 5 (l/一/丨/ㅡ/ㅣ, all bare single
        straight lines) hit the same false rejection."""
        cfg = CANVAS_CONFIG[script_type]
        template = scoring.render_glyph_mask(char, script_type, cfg)
        template_n = scoring._normalize(template)
        skeleton = scoring._skeletonize(template_n)
        student_n = scoring._dilate(skeleton, 3)
        score, reason = scoring._score_normalized(student_n, template_n)
        assert score >= 85, f"{script_type} {char!r} scored {score} (reason={reason}), expected >=85"

    def test_every_seeded_character_in_every_language_scores_high(self):
        """Broader sweep than the shape-family samples above: every single
        letter_writing character across every SEED language, not just a
        hand-picked few per script. This is what actually caught the
        single-straight-stroke bug above -- the hand-picked samples never
        included a bare, unbent stroke. Kept as a permanent regression
        rather than a one-off check so a future SEED addition (a new
        language, or a character shape nobody thought to hand-pick) that
        hits the same class of degenerate-ink false-positive fails a test
        instead of shipping silently broken."""
        from languages.management.commands.seed_language_exercises import SEED
        from languages.utils import CANVAS_CONFIG

        failures = []
        checked = 0
        for lang_code, data in SEED.items():
            script_type = data['script_type']
            cfg = CANVAS_CONFIG.get(script_type)
            if cfg is None:
                continue
            chars = set()
            for topic in data['topics']:
                chars.update(topic.get('letter_writing', []))
            for ch in sorted(chars):
                checked += 1
                template = scoring.render_glyph_mask(ch, script_type, cfg)
                template_n = scoring._normalize(template)
                skeleton = scoring._skeletonize(template_n)
                student_n = scoring._dilate(skeleton, 3)
                score, reason = scoring._score_normalized(student_n, template_n)
                if score < 85:
                    failures.append(f'{lang_code}/{script_type} {ch!r}: score={score} reason={reason}')

        assert checked > 0, 'no seeded characters found to check -- SEED or CANVAS_CONFIG changed shape'
        assert not failures, (
            f'{len(failures)}/{checked} seeded characters score <85 with a '
            f'correctly-formed trace:\n  ' + '\n  '.join(failures)
        )


# ---------------------------------------------------------------------------
# Size / position invariance
# ---------------------------------------------------------------------------

class TestSizeAndPositionInvariance:

    def test_small_large_offcentre_score_alike(self):
        template = _template('A', 'latin')
        variants = {
            'baseline':        _correct_trace_raw('A', 'latin', scale=1.0, offset=(0, 0)),
            'small_centred':   _correct_trace_raw('A', 'latin', scale=0.4, offset=(0, 0)),
            'small_offcentre': _correct_trace_raw('A', 'latin', scale=0.4, offset=(-150, 100)),
            'large_centred':   _correct_trace_raw('A', 'latin', scale=1.6, offset=(0, 0)),
        }
        scores = {name: scoring.score_masks(mask, template)[0] for name, mask in variants.items()}

        for name, score in scores.items():
            assert score >= 85, f'{name} scored {score}, expected >=85'

        spread = max(scores.values()) - min(scores.values())
        assert spread <= 5, f'scores should be within a small tolerance of each other, got {scores}'


# ---------------------------------------------------------------------------
# Wrong character → low score
# ---------------------------------------------------------------------------

class TestWrongCharacterScoresLow:

    def test_drew_b_target_was_a(self):
        student = _correct_trace_raw('B', 'latin')
        template = _template('A', 'latin')
        score, reason = scoring.score_masks(student, template)
        assert score < 50, f'wrong letter scored {score} (reason={reason}), expected <50'

    def test_drew_o_target_was_c(self):
        student = _correct_trace_raw('O', 'latin')
        template = _template('C', 'latin')
        score, _ = scoring.score_masks(student, template)
        assert score < 50


# ---------------------------------------------------------------------------
# Scribble → low score
# ---------------------------------------------------------------------------

class TestScribbleScoresLow:

    @pytest.mark.parametrize('seed', [0, 1, 2])
    def test_random_strokes_score_low(self, seed):
        student = _scribble(seed)
        template = _template('A', 'latin')
        score, reason = scoring.score_masks(student, template)
        assert score < 50, f'scribble seed={seed} scored {score} (reason={reason})'

    def test_blank_canvas_scores_zero(self):
        student = np.zeros((600, 600), dtype=bool)
        template = _template('A', 'latin')
        score, reason = scoring.score_masks(student, template)
        assert score == 0
        assert reason == 'no_ink'


# ---------------------------------------------------------------------------
# Reason codes reflect the actual deduction cause
# ---------------------------------------------------------------------------

class TestReasonCodes:

    def test_excellent_match_reason(self):
        student = _correct_trace_raw('A', 'latin')
        template = _template('A', 'latin')
        score, reason = scoring.score_masks(student, template)
        assert score >= 85
        assert reason == 'excellent_match'

    def test_wrong_letter_reason_is_not_canned_canvas_height_tip(self):
        student = _correct_trace_raw('B', 'latin')
        template = _template('A', 'latin')
        _, reason = scoring.score_masks(student, template)
        assert reason in ('shape_mismatch', 'strokes_outside_shape', 'shape_incomplete')

    def test_score_and_reason_agree_on_the_same_rounded_value(self):
        """Regression: _reason() used to branch on the un-rounded score
        while the returned score was rounded, so a raw score like 84.96
        could round up to a displayed 85.0%/3-star result next to a
        'close_match' tip that contradicts it. score_masks() must round
        once and use that same value for both."""
        student = _correct_trace_raw('A', 'latin')
        template = _template('A', 'latin')
        score, reason = scoring.score_masks(student, template)
        assert (reason == 'excellent_match') == (score >= 85)
        assert (reason == 'close_match') == (70 <= score < 85)


# ---------------------------------------------------------------------------
# Degenerate ink: too sparse to normalize, or a filled blob/dot rather
# than a stroke — a shape comparison alone can score these unreasonably
# (even crash), since normalization's aspect-preserving upscale can turn
# a handful of ink pixels into either nothing or a filled blob.
# ---------------------------------------------------------------------------

class TestDegenerateInk:

    def test_sparse_far_apart_pixels_do_not_crash(self):
        """A couple of isolated, far-apart ink pixels give _normalize() a
        huge bounding box; NEAREST-resampling that crop can drop every ink
        pixel, leaving an empty normalized mask — score_masks() must not
        divide by zero in that case."""
        student = np.zeros((178, 600), dtype=bool)
        student[5, 5] = True
        student[173, 595] = True
        template = _template('e', 'latin')
        score, reason = scoring.score_masks(student, template)
        assert score == 0
        assert reason == 'no_ink'

    @pytest.mark.parametrize('char', ['e', 'O', 'A', 'g', 'C'])
    def test_single_dot_scores_below_50_not_a_real_stroke(self, char):
        """A single accidental tap/dot, blown up by the aspect-preserving
        normalize, can coincidentally overlap a rounded letter's corridor
        by sheer filled area even though it was never a stroke at all —
        must not be scoreable as 'correct' (score >= 50 == is_correct)."""
        img = Image.new('L', (600, 178), 0)
        ImageDraw.Draw(img).ellipse((290, 80, 306, 96), fill=255)  # r=8 dot
        dot = np.asarray(img) > 127
        template = _template(char, 'latin')
        score, reason = scoring.score_masks(dot, template)
        assert score < 50, f"dot vs '{char}' scored {score} (reason={reason})"
        assert reason == 'too_little_ink'


# ---------------------------------------------------------------------------
# Unsupported script (font not vendored) — degrade gracefully rather than
# permanently failing every submission for that language.
# ---------------------------------------------------------------------------

class TestUnsupportedScriptFallback:

    def test_devanagari_falls_back_instead_of_erroring(self):
        """devanagari/arabic are valid Language.script_type choices but no
        font is vendored for them (FONT_FILES covers latin/sinhala/tamil/
        cjk; cjk's is a subset covering only the curated Mandarin
        character set — see its comment in scoring.py) — compute_score()
        must degrade to the same generous ink-presence heuristic CPP-311
        used for this case, not raise ScoringError on every single
        submission for that language."""
        png_b64 = _mask_to_png_b64(_correct_trace_raw('A', 'latin'))
        score, reason = scoring.compute_score(png_b64, 'क', 'devanagari', LATIN_CONFIG)
        assert score == 72.0
        assert reason == 'unscored_fallback'

    def test_devanagari_with_no_ink_still_scores_zero(self):
        blank = np.zeros((178, 600), dtype=bool)
        png_b64 = _mask_to_png_b64(blank)
        score, reason = scoring.compute_score(png_b64, 'क', 'devanagari', LATIN_CONFIG)
        assert score == 0.0
        assert reason == 'no_ink'


# ---------------------------------------------------------------------------
# View integration — real PNG through the Django POST handler
# ---------------------------------------------------------------------------

def _make_student(username, password='TestPass392!'):
    u = CustomUser.objects.create_user(
        username=username,
        password=password,
        email=f'{username}@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
    UserRole.objects.get_or_create(user=u, role=role)
    return u, password


def _make_exercise(prompt, script_type='latin', suffix='392'):
    lang, _ = Language.objects.get_or_create(
        code=f'lw392{suffix}',
        defaults={'name': f'LW392{suffix}', 'script_type': script_type, 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name=f'Alphabet {suffix}', defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice=LanguageTopicLevel.BEGINNER,
    )
    return LanguageExercise.objects.create(
        topic_level=level, exercise_type=LanguageExercise.LETTER_WRITING,
        prompt=prompt, points=5, is_active=True,
    )


def _post_ink(client, url, mask, stroke_objects=1):
    stroke = '{"version":"5.3.1","objects":[' + ','.join(['{"type":"path"}'] * stroke_objects) + ']}'
    return client.post(url, data={
        'stroke_data': stroke,
        'ink_image': _mask_to_png_b64(mask),
    })


class TestViewIntegration:

    @pytest.mark.django_db
    def test_correct_trace_scores_3_stars(self):
        student, pwd = _make_student('stu_392_correct')
        exercise = _make_exercise('A', suffix='392a')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        mask = _correct_trace_raw('A', 'latin')
        resp = _post_ink(client, url, mask)
        data = resp.json()

        assert resp.status_code == 200
        assert data['success'] is True
        assert data['score'] >= 85
        assert data['stars'] == 3
        assert data['reason'] == 'excellent_match'
        assert data['is_correct'] is True

    @pytest.mark.django_db
    def test_wrong_letter_scores_below_50_and_not_correct(self):
        student, pwd = _make_student('stu_392_wrong')
        exercise = _make_exercise('A', suffix='392b')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        mask = _correct_trace_raw('B', 'latin')
        resp = _post_ink(client, url, mask)
        data = resp.json()

        assert data['score'] < 50
        assert data['is_correct'] is False
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.points_earned == 0

    @pytest.mark.django_db
    def test_no_strokes_scores_zero_without_calling_scorer(self):
        student, pwd = _make_student('stu_392_empty')
        exercise = _make_exercise('A', suffix='392c')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = client.post(url, data={'stroke_data': '{}', 'ink_image': ''})
        data = resp.json()

        assert data['score'] == 0
        assert data['reason'] == 'no_ink'

    @pytest.mark.django_db
    def test_malformed_ink_image_returns_explicit_error_not_fabricated_score(self):
        student, pwd = _make_student('stu_392_badimg')
        exercise = _make_exercise('A', suffix='392d')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        stroke = '{"version":"5.3.1","objects":[{"type":"path"}]}'
        resp = client.post(url, data={'stroke_data': stroke, 'ink_image': 'not-valid-base64!!'})
        data = resp.json()

        assert resp.status_code == 422
        assert data['success'] is False
        assert 'error' in data

    @pytest.mark.django_db
    def test_sinhala_correct_trace_scores_high(self):
        student, pwd = _make_student('stu_392_sinhala')
        exercise = _make_exercise('අ', script_type='sinhala', suffix='392e')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        mask = _correct_trace_raw('අ', 'sinhala')
        resp = _post_ink(client, url, mask)
        data = resp.json()

        assert data['score'] >= 85
        assert data['stars'] == 3
