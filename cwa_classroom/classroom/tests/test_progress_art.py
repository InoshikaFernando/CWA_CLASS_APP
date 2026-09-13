"""Tests for the progress-art picture catalogue (``classroom/progress_art.py``).

Two things are worth guarding here and nothing else really is:

* **The invariants every picture must hold.** A picture is a hand-written list
  of SVG paths. A typo puts a stroke off the canvas, or drops the opening dot,
  and nothing complains — the drawing just renders wrong for whichever students
  happen to be given it. These tests are the only thing that would notice.
* **The selection rules.** Tier by question count, band by year, stored key
  always wins. Each of those exists to stop a specific bad outcome, spelled out
  in the test that covers it.
"""

import re
from unittest import TestCase

from classroom import progress_art as art


# One "M<x> <y>" or "L<x> <y>" etc. — the absolute commands whose coordinates
# can be read without tracing the pen. Relative commands (arcs in the circle
# helper) are skipped rather than half-parsed.
_ABS_COORD = re.compile(r'[MLCQ]((?:\s*-?\d+(?:\.\d+)?){2,})')

# The opening dot is ``_dot()`` — a two-arc circle whose radius is the first
# number after the "a". Anything bigger than this is not a dot.
_LEADING_ARC_RADIUS = re.compile(r'a(-?\d+(?:\.\d+)?)\s')

MAX_DOT_RADIUS = 3.0


def _absolute_points(d):
    points = []
    for match in _ABS_COORD.finditer(d):
        nums = [float(n) for n in match.group(1).split()]
        for i in range(0, len(nums) - 1, 2):
            points.append((nums[i], nums[i + 1]))
    return points


class PictureInvariantsTest(TestCase):
    """Rules that hold for every picture, checked for every picture."""

    def test_the_catalogue_is_not_empty(self):
        self.assertTrue(art.PICTURES)

    def test_keys_match_their_entries(self):
        for key, picture in art.PICTURES.items():
            self.assertEqual(key, picture.key)

    def test_every_picture_has_a_title_and_known_tier_and_band(self):
        for picture in art.PICTURES.values():
            with self.subTest(picture=picture.key):
                self.assertTrue(picture.title.strip())
                self.assertIn(picture.tier, art.TIER_ORDER)
                self.assertIn(
                    picture.band,
                    (art.BAND_JUNIOR, art.BAND_SENIOR, art.BAND_ANY),
                )

    def test_every_stroke_is_a_path_starting_with_a_move(self):
        for picture in art.PICTURES.values():
            for index, d in enumerate(picture.strokes):
                with self.subTest(picture=picture.key, stroke=index):
                    self.assertTrue(d.strip())
                    self.assertTrue(d.startswith('M'), d[:20])

    def test_every_picture_opens_with_a_small_dot(self):
        """The feature's first promise: question one leaves a visible mark.

        The renderer also reveals stroke zero for free, before any question is
        answered, so that an untouched panel reads as "your picture starts
        here" rather than as an empty box. Both only work if stroke zero really
        is a dot — a picture that opened with a long outline would either show
        that whole outline for nothing or produce an invisible sliver.
        """
        for picture in art.PICTURES.values():
            with self.subTest(picture=picture.key):
                match = _LEADING_ARC_RADIUS.search(picture.strokes[0])
                self.assertIsNotNone(
                    match,
                    f'{picture.key} does not open with a _dot() circle',
                )
                self.assertLessEqual(float(match.group(1)), MAX_DOT_RADIUS)

    def test_no_stroke_wanders_off_the_canvas(self):
        """A stray coordinate is invisible in code and obvious on screen."""
        margin = 12
        for picture in art.PICTURES.values():
            for index, d in enumerate(picture.strokes):
                for x, y in _absolute_points(d):
                    with self.subTest(picture=picture.key, stroke=index):
                        self.assertGreaterEqual(x, -margin)
                        self.assertLessEqual(x, art.CANVAS_WIDTH + margin)
                        self.assertGreaterEqual(y, -margin)
                        self.assertLessEqual(y, art.CANVAS_HEIGHT + margin)

    def test_detail_grows_with_the_tier(self):
        """Ink has to be proportional to effort.

        The whole point of tiering is that 100 questions buys more drawing than
        10. If a "rich" picture were no more detailed than a "simple" one, the
        tier would be a label with nothing behind it.
        """
        floors = {
            art.TIER_SIMPLE: 12,
            art.TIER_MEDIUM: 22,
            art.TIER_RICH: 40,
            art.TIER_EPIC: 60,
        }
        for picture in art.PICTURES.values():
            with self.subTest(picture=picture.key):
                self.assertGreaterEqual(picture.stroke_count, floors[picture.tier])

    def test_payload_carries_what_the_renderer_needs(self):
        payload = art.PICTURES['balloon'].payload()
        self.assertEqual(payload['key'], 'balloon')
        self.assertEqual(payload['width'], art.CANVAS_WIDTH)
        self.assertEqual(payload['height'], art.CANVAS_HEIGHT)
        self.assertEqual(len(payload['strokes']), art.PICTURES['balloon'].stroke_count)


class TierTest(TestCase):
    def test_question_count_maps_to_tier(self):
        self.assertEqual(art.tier_for(1), art.TIER_SIMPLE)
        self.assertEqual(art.tier_for(12), art.TIER_SIMPLE)
        self.assertEqual(art.tier_for(13), art.TIER_MEDIUM)
        self.assertEqual(art.tier_for(30), art.TIER_MEDIUM)
        self.assertEqual(art.tier_for(31), art.TIER_RICH)
        self.assertEqual(art.tier_for(79), art.TIER_RICH)
        self.assertEqual(art.tier_for(80), art.TIER_EPIC)
        self.assertEqual(art.tier_for(500), art.TIER_EPIC)

    def test_a_junk_question_count_does_not_raise(self):
        self.assertEqual(art.tier_for(None), art.TIER_SIMPLE)
        self.assertEqual(art.tier_for('nope'), art.TIER_SIMPLE)

    def test_every_tier_has_pictures(self):
        for tier in art.TIER_ORDER:
            with self.subTest(tier=tier):
                self.assertTrue(art.pictures_in_tier(tier))


class BandTest(TestCase):
    def test_years_map_to_bands(self):
        for year in (1, 2, 3, 4):
            self.assertEqual(art.band_for(year), art.BAND_JUNIOR)
        for year in (5, 6, 7, 8):
            self.assertEqual(art.band_for(year), art.BAND_SENIOR)

    def test_a_non_curriculum_level_does_not_narrow_anything(self):
        """Basic-facts (100+) and school-custom (200+) levels say nothing about
        a student's age, so they must not be read as "junior"."""
        for level in (None, '', 0, 101, 205, 'x'):
            with self.subTest(level=level):
                self.assertIsNone(art.band_for(level))

    def test_every_tier_can_serve_both_bands(self):
        """The rule that stops a Year 8 being handed a balloon.

        A senior doing a short quiz has earned a *simple* picture — but if the
        simple tier held only junior subjects, the band filter would fall back
        to the whole tier and hand them one anyway. Each tier therefore needs at
        least one picture that suits each band.
        """
        for tier in art.TIER_ORDER:
            for band in (art.BAND_JUNIOR, art.BAND_SENIOR):
                with self.subTest(tier=tier, band=band):
                    suited = [
                        p for p in art.pictures_in_tier(tier)
                        if p.band in (band, art.BAND_ANY)
                    ]
                    self.assertTrue(suited, f'{tier} has nothing for {band}')

    def test_band_filter_falls_back_rather_than_returning_nothing(self):
        rows = art.pictures_in_tier(art.TIER_SIMPLE, band='not-a-band')
        self.assertEqual(
            {p.key for p in rows},
            {p.key for p in art.pictures_in_tier(art.TIER_SIMPLE)},
        )


class PickTest(TestCase):
    def test_pick_is_deterministic_in_its_seed(self):
        """A page reload mid-quiz must not reroll the drawing."""
        first = art.pick(20, 'seed-a')
        for _ in range(5):
            self.assertEqual(art.pick(20, 'seed-a').key, first.key)

    def test_different_seeds_spread_across_the_tier(self):
        keys = {art.pick(20, f'seed-{i}').key for i in range(40)}
        self.assertGreater(len(keys), 1)

    def test_pick_respects_the_tier(self):
        self.assertEqual(art.pick(10, 's').tier, art.TIER_SIMPLE)
        self.assertEqual(art.pick(100, 's').tier, art.TIER_EPIC)

    def test_pick_respects_the_band(self):
        for i in range(25):
            with self.subTest(seed=i):
                self.assertIn(
                    art.pick(10, f'seed-{i}', year_level=7).band,
                    (art.BAND_SENIOR, art.BAND_ANY),
                )
                self.assertIn(
                    art.pick(10, f'seed-{i}', year_level=2).band,
                    (art.BAND_JUNIOR, art.BAND_ANY),
                )

    def test_year_changes_the_pick_for_at_least_some_seeds(self):
        differing = [
            i for i in range(25)
            if art.pick(10, f'seed-{i}', year_level=2).key
            != art.pick(10, f'seed-{i}', year_level=7).key
        ]
        self.assertTrue(differing, 'the year level never affects the choice')


class ResolveTest(TestCase):
    def test_a_stored_key_wins_over_a_fresh_pick(self):
        """Half-way through a paper, the picture must not change under you."""
        picture = art.resolve('kite', total_questions=100, seed='anything')
        self.assertEqual(picture.key, 'kite')

    def test_a_stored_key_wins_even_across_tiers_and_bands(self):
        picture = art.resolve('balloon', total_questions=100, seed='x', year_level=8)
        self.assertEqual(picture.key, 'balloon')

    def test_an_unknown_stored_key_falls_back_to_a_pick(self):
        """A picture retired from the catalogue must not blank the panel."""
        picture = art.resolve('retired-picture', total_questions=20, seed='s')
        self.assertEqual(picture.key, art.pick(20, 's').key)

    def test_no_stored_key_picks(self):
        self.assertEqual(
            art.resolve('', total_questions=20, seed='s').key,
            art.pick(20, 's').key,
        )


class ContextTest(TestCase):
    def test_done_is_clamped_to_the_total(self):
        ctx = art.context(art.PICTURES['fish'], done=99, total=10)
        self.assertEqual(ctx['done'], 10)
        self.assertTrue(ctx['is_complete'])

    def test_negative_done_is_clamped_to_zero(self):
        ctx = art.context(art.PICTURES['fish'], done=-4, total=10)
        self.assertEqual(ctx['done'], 0)
        self.assertFalse(ctx['is_complete'])

    def test_an_empty_exercise_is_never_complete(self):
        ctx = art.context(art.PICTURES['fish'], done=0, total=0)
        self.assertFalse(ctx['is_complete'])


class AnswerIsPresentTest(TestCase):
    """The rule that decides whether a saved field counts as an answer.

    ``static/js/progress_art.js`` mirrors this for its live count. If the two
    ever disagree, the drawing jumps the moment the page is reloaded.
    """

    def test_plain_answers_count(self):
        for value in ('4', 'x = 2', '0', 0, ' 7 '):
            with self.subTest(value=value):
                self.assertTrue(art.answer_is_present(value))

    def test_blank_values_do_not(self):
        for value in ('', '   ', None):
            with self.subTest(value=value):
                self.assertFalse(art.answer_is_present(value))

    def test_an_untouched_widget_skeleton_does_not(self):
        """draw-on-grid, shape-select and the number line all post an empty JSON
        skeleton before the student has drawn anything. Counting those would
        hand out a chunk of the picture on the very first autosave."""
        for value in ('{"segments": []}', '{"selected":[]}', '{"marks": []}',
                      '{}', '[]', '{"a": "", "b": []}'):
            with self.subTest(value=value):
                self.assertFalse(art.answer_is_present(value))

    def test_a_widget_with_real_working_does(self):
        for value in ('{"segments": [[1,2]]}', '{"selected":[3]}',
                      '{"marks": [0]}', '["4"]'):
            with self.subTest(value=value):
                self.assertTrue(art.answer_is_present(value))

    def test_malformed_json_is_treated_as_an_answer(self):
        # Better to over-count one odd value than to silently ignore something
        # a student actually typed.
        self.assertTrue(art.answer_is_present('{not json'))
