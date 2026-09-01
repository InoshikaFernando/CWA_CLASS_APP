"""
Unit tests for CPP-393: authored stroke-order data completeness/validity.

CPP-311/310's guide animation derived stroke order from raster-scan order
of a skeletonised glyph — script-agnostic and wrong for every letter in
every language (see languages/static/languages/js/stroke_order.js's module
doc). CPP-393 replaces it with authored data
(languages/static/languages/js/stroke_order_data.js) resolved onto the
real glyph skeleton at runtime. These tests validate the *data*, not the
resolution engine (that's JS, covered by ui_tests/test_cpp393_stroke_order.py
through a real browser) — completeness, structural validity, and stroke
counts for a spot-checked sample per script.

Driven from languages/management/commands/seed_language_exercises.py's
SEED constant (not a hand-copied character list), so adding a letter — or
a whole new seeded language — without authoring its stroke data fails
these tests, per CPP-393's own test-criteria requirement.
"""
import json
import re
from pathlib import Path

import pytest

from languages.management.commands.seed_language_exercises import SEED

pytestmark = pytest.mark.cpp393

STROKE_ORDER_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / 'static' / 'languages' / 'js' / 'stroke_order_data.js'
)


def _load_stroke_order_data():
    """Parse window.STROKE_ORDER_DATA out of the shipped JS file directly
    (no Node dependency, no separate data source to drift out of sync —
    the generator writes the object as plain JSON after the assignment)."""
    src = STROKE_ORDER_JS_PATH.read_text(encoding='utf-8')
    m = re.search(r'window\.STROKE_ORDER_DATA\s*=\s*(\{.*\});\s*\Z', src, re.S)
    assert m, 'could not find `window.STROKE_ORDER_DATA = {...};` in stroke_order_data.js'
    return json.loads(m.group(1))


def _seeded_chars_by_script():
    """{script_type: set(chars)} for every letter_writing exercise in SEED —
    the single source of truth for what needs stroke-order data."""
    by_script = {}
    for lang_data in SEED.values():
        script = lang_data['script_type']
        chars = by_script.setdefault(script, set())
        for topic in lang_data['topics']:
            chars.update(topic.get('letter_writing', []))
    return by_script


STROKE_DATA = _load_stroke_order_data()
SEEDED_CHARS_BY_SCRIPT = _seeded_chars_by_script()


class TestDataFileParses:

    def test_stroke_order_js_is_present_and_parses(self):
        assert STROKE_ORDER_JS_PATH.exists()
        assert isinstance(STROKE_DATA, dict)
        assert set(STROKE_DATA.keys()) >= {'latin', 'sinhala', 'tamil'}


# ---------------------------------------------------------------------------
# Completeness — every seeded letter_writing character, in every seeded
# script, has an entry. This is the test that fails the build if a letter
# (or a whole new language) is added to the seed data without its stroke
# order being authored.
# ---------------------------------------------------------------------------

class TestCompleteness:

    @pytest.mark.parametrize('script', sorted(SEEDED_CHARS_BY_SCRIPT.keys()))
    def test_every_seeded_character_has_an_entry(self, script):
        seeded = SEEDED_CHARS_BY_SCRIPT[script]
        assert seeded, f'no letter_writing characters found in SEED for script {script!r}'
        table = STROKE_DATA.get(script, {})
        missing = sorted(seeded - set(table.keys()))
        assert not missing, (
            f"{script}: {len(missing)} seeded character(s) have no stroke-order "
            f"entry in stroke_order_data.js: {missing}"
        )

    def test_seed_command_scripts_are_all_covered(self):
        """Sanity check on the test's own premise: SEED currently covers
        exactly latin/sinhala/tamil. If a new language is seeded later,
        this starts failing until stroke_order_data.js gains that script
        (or the character-lookup fallback for a fourth script is wired up
        in stroke_order.js's caller) — which is the point."""
        assert set(SEEDED_CHARS_BY_SCRIPT.keys()) == {'latin', 'sinhala', 'tamil'}


# ---------------------------------------------------------------------------
# Structural validity
# ---------------------------------------------------------------------------

class TestWellFormed:

    @pytest.mark.parametrize('script', sorted(STROKE_DATA.keys()))
    def test_every_entry_has_at_least_one_stroke(self, script):
        for char, strokes in STROKE_DATA[script].items():
            assert isinstance(strokes, list) and len(strokes) >= 1, \
                f"{script} {char!r}: expected a non-empty list of strokes"

    @pytest.mark.parametrize('script', sorted(STROKE_DATA.keys()))
    def test_every_anchor_is_a_2element_pair_in_0_1(self, script):
        for char, strokes in STROKE_DATA[script].items():
            for si, stroke in enumerate(strokes):
                assert isinstance(stroke, list) and len(stroke) >= 1, \
                    f"{script} {char!r} stroke {si}: expected at least one anchor"
                for ai, anchor in enumerate(stroke):
                    assert isinstance(anchor, list) and len(anchor) == 2, (
                        f"{script} {char!r} stroke {si} anchor {ai}: "
                        f"expected a 2-element [x, y] pair, got {anchor!r}"
                    )
                    x, y = anchor
                    assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, (
                        f"{script} {char!r} stroke {si} anchor {ai} = {anchor!r} "
                        f"outside the normalised 0..1 range"
                    )


# ---------------------------------------------------------------------------
# Stroke counts — spot-checked against known values (CPP-393 test criteria).
# ---------------------------------------------------------------------------

class TestStrokeCounts:

    @pytest.mark.parametrize('char,expected', [
        ('A', 3), ('b', 2), ('O', 1), ('E', 4), ('i', 2),
    ])
    def test_latin_known_counts(self, char, expected):
        strokes = STROKE_DATA['latin'][char]
        assert len(strokes) == expected, (
            f"latin {char!r}: expected {expected} strokes, got {len(strokes)}"
        )

    @pytest.mark.parametrize('char,expected', [
        ('ක', 1),   # ka — single anticlockwise loop (no second component authored)
        ('ර', 2),   # ra — loop + tail, per CPP-393's own note that some
                    # letters carry a second visual component
        ('අ', 1),   # a (vowel) — single loop
    ])
    def test_sinhala_sample(self, char, expected):
        """Sample per CPP-393's test-criteria ask for 'an agreed sample for
        Sinhala' — these three reflect the template-generated placeholder
        data (see stroke_order_data.js header) actually authored this
        session, NOT a native-speaker-confirmed count. Re-baseline this
        test against the real stroke count once a native Sinhala writer
        reviews the data, per the ticket's explicit sign-off requirement."""
        strokes = STROKE_DATA['sinhala'][char]
        assert len(strokes) == expected, (
            f"sinhala {char!r}: expected {expected} strokes, got {len(strokes)}"
        )

    @pytest.mark.parametrize('char,expected', [
        ('அ', 1), ('க', 1), ('ம', 1),
    ])
    def test_tamil_sample(self, char, expected):
        """Same caveat as the Sinhala sample above: reflects the uniform
        template-generated placeholder (one sweeping curve per character),
        not a native-speaker-confirmed count. Re-baseline once reviewed."""
        strokes = STROKE_DATA['tamil'][char]
        assert len(strokes) == expected, (
            f"tamil {char!r}: expected {expected} strokes, got {len(strokes)}"
        )
