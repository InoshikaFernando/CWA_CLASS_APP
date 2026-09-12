"""Progress art — a cartoon line drawing that draws itself as a student works.

A quiz, a homework paper and a worksheet all share the same reward: a hidden
picture that starts as a single dot and gains ink with every question the
student finishes. The last question completes it.

Why it lives here rather than in one of the three apps: quiz, homework and
worksheets each own a different "how far through are you" signal (a session
counter, a saved draft, a row count) but want the *same* picture library and
the *same* rules for choosing one. Putting the catalogue in a subject-agnostic
module keeps a picture from being invented twice and lets one test suite
validate every drawing.

How a picture is drawn
----------------------
A picture is an ordered tuple of SVG path ``d`` strings on a fixed
240x180 canvas. The browser (``static/js/progress_art.js``) measures the
total length of every path, then reveals ``done / total`` of that length using
``stroke-dashoffset``. Two consequences worth knowing:

* **The reveal is length-based, not stroke-based.** A 100-question homework and
  a 15-question quiz can use the same picture and both see steady progress —
  the long paths are simply revealed a bit at a time. Nothing has to divide
  evenly.
* **Stroke order is drawing order.** Every picture therefore opens with a tiny
  dot (``_dot``) so question one produces a visible mark rather than an
  invisible sliver of a long outline, and the recognisable outlines come before
  the decorative background.

Complexity tiers
----------------
Ink should be proportional to effort: finishing 120 homework questions and
being handed the same eight-stroke balloon a 10-question quiz gives would feel
cheap. ``tier_for()`` maps the exercise's question count onto a tier, and each
tier's pictures carry roughly that much detail — a balloon for a short quiz, a
whole city skyline for a 100-question paper.

Choosing, and keeping, a picture
--------------------------------
``pick()`` is deterministic in its seed so a page reload during a quiz shows
the same picture rather than restarting on a different one. For work that spans
days (homework drafts, worksheet sessions) the chosen key is *stored* on the
draft/submission and passed back through ``resolve()``: a stored key always
wins, so adding pictures to this catalogue can never swap the drawing a student
is half-way through.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

# The canvas every picture is drawn on. Fixed so the renderer can size itself
# from CSS alone, and so motifs (ground line, sky) line up between pictures.
CANVAS_WIDTH = 240
CANVAS_HEIGHT = 180
GROUND_Y = 168

TIER_SIMPLE = 'simple'
TIER_MEDIUM = 'medium'
TIER_RICH = 'rich'
TIER_EPIC = 'epic'

TIER_ORDER = (TIER_SIMPLE, TIER_MEDIUM, TIER_RICH, TIER_EPIC)

# Age band. The tier says how much detail the work has earned; the band says
# whether the subject suits the student. A Year 8 finishing a short quiz has
# earned a *simple* picture, but handing them the same balloon a Year 1 gets
# reads as babyish — so they get the mountain range instead. BAND_ANY is for
# subjects that land either way (a rocket, a castle, a city skyline).
BAND_JUNIOR = 'junior'      # Years 1-4
BAND_SENIOR = 'senior'      # Years 5-8
BAND_ANY = 'any'

#: Highest year still treated as junior.
JUNIOR_MAX_YEAR = 4

#: Upper bound (inclusive) of each tier, in questions. The last tier is open
#: ended. Chosen so the common shapes land where you'd expect: a 10-20 question
#: quiz is "simple", a 30-question worksheet "medium", a typical 40-60 question
#: homework "rich", and a 100+ question holiday paper "epic".
TIER_BOUNDS = (
    (12, TIER_SIMPLE),
    (30, TIER_MEDIUM),
    (79, TIER_RICH),
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _n(value: float) -> str:
    """Format a coordinate compactly (3 decimals max, no trailing zeros)."""
    return f'{round(float(value), 3):g}'


def _line(x1: float, y1: float, x2: float, y2: float) -> str:
    return f'M{_n(x1)} {_n(y1)} L{_n(x2)} {_n(y2)}'


def _poly(points: Sequence[tuple[float, float]], close: bool = True) -> str:
    head = f'M{_n(points[0][0])} {_n(points[0][1])}'
    rest = ''.join(f' L{_n(x)} {_n(y)}' for x, y in points[1:])
    return head + rest + (' Z' if close else '')


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> str:
    """An ellipse as two arcs — ``getTotalLength()`` works on paths only."""
    return (
        f'M{_n(cx - rx)} {_n(cy)} '
        f'a{_n(rx)} {_n(ry)} 0 1 0 {_n(2 * rx)} 0 '
        f'a{_n(rx)} {_n(ry)} 0 1 0 {_n(-2 * rx)} 0'
    )


def _circle(cx: float, cy: float, r: float) -> str:
    return _ellipse(cx, cy, r, r)


def _dot(cx: float, cy: float, r: float = 2.0) -> str:
    """The opening mark of every picture: small, but unmistakably *there*."""
    return _circle(cx, cy, r)


def _arc(x1: float, y1: float, x2: float, y2: float,
         rx: float, ry: float | None = None,
         large: int = 0, sweep: int = 1) -> str:
    ry = rx if ry is None else ry
    return (
        f'M{_n(x1)} {_n(y1)} '
        f'A{_n(rx)} {_n(ry)} 0 {large} {sweep} {_n(x2)} {_n(y2)}'
    )


def _quad(x1: float, y1: float, cx: float, cy: float, x2: float, y2: float) -> str:
    return f'M{_n(x1)} {_n(y1)} Q{_n(cx)} {_n(cy)} {_n(x2)} {_n(y2)}'


def _cubic(x1: float, y1: float, c1x: float, c1y: float,
           c2x: float, c2y: float, x2: float, y2: float) -> str:
    return (
        f'M{_n(x1)} {_n(y1)} '
        f'C{_n(c1x)} {_n(c1y)} {_n(c2x)} {_n(c2y)} {_n(x2)} {_n(y2)}'
    )


def _rect(x: float, y: float, w: float, h: float, close: bool = True) -> str:
    return _poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=close)


# ---------------------------------------------------------------------------
# Reusable motifs
#
# Scenes are composed from these rather than hand-plotted point by point: the
# rich and epic pictures need 50-100 strokes each, and a city skyline written
# out coordinate by coordinate would be unreadable *and* unverifiable.
# ---------------------------------------------------------------------------

def _star(cx: float, cy: float, r: float, points: int = 5) -> str:
    pts: list[tuple[float, float]] = []
    for i in range(points * 2):
        radius = r if i % 2 == 0 else r * 0.42
        angle = -math.pi / 2 + i * math.pi / points
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return _poly(pts, close=True)


def _cloud(cx: float, cy: float, s: float = 1.0) -> str:
    """A three-bump cloud with a flat base, closed back to its start."""
    return (
        f'M{_n(cx - 20 * s)} {_n(cy)} '
        f'a{_n(9 * s)} {_n(9 * s)} 0 0 1 {_n(8 * s)} {_n(-8 * s)} '
        f'a{_n(11 * s)} {_n(11 * s)} 0 0 1 {_n(20 * s)} {_n(-2 * s)} '
        f'a{_n(9 * s)} {_n(9 * s)} 0 0 1 {_n(12 * s)} {_n(10 * s)} Z'
    )


def _bird(cx: float, cy: float, s: float = 1.0) -> str:
    """The classic two-arc gull."""
    return (
        f'M{_n(cx - 10 * s)} {_n(cy)} '
        f'c{_n(3 * s)} {_n(-6 * s)} {_n(7 * s)} {_n(-6 * s)} {_n(10 * s)} 0 '
        f'c{_n(3 * s)} {_n(-6 * s)} {_n(7 * s)} {_n(-6 * s)} {_n(10 * s)} 0'
    )


def _sun(cx: float, cy: float, r: float, rays: int = 6) -> list[str]:
    strokes = [_circle(cx, cy, r)]
    for i in range(rays):
        angle = i * 2 * math.pi / rays + math.pi / 12
        x1 = cx + math.cos(angle) * (r + 3)
        y1 = cy + math.sin(angle) * (r + 3)
        x2 = cx + math.cos(angle) * (r + 9)
        y2 = cy + math.sin(angle) * (r + 9)
        strokes.append(_line(x1, y1, x2, y2))
    return strokes


def _wave(y: float, x0: float, x1: float, amp: float = 4.0, humps: int = 4) -> str:
    """One horizontal squiggle — water surface, a moat, a river."""
    step = (x1 - x0) / humps
    parts = [f'M{_n(x0)} {_n(y)}']
    for i in range(humps):
        sx = x0 + i * step
        direction = -amp if i % 2 == 0 else amp
        parts.append(
            f'Q{_n(sx + step / 2)} {_n(y + direction)} {_n(sx + step)} {_n(y)}'
        )
    return ' '.join(parts)


def _grass_tuft(x: float, y: float, s: float = 1.0) -> str:
    return (
        f'M{_n(x - 5 * s)} {_n(y)} Q{_n(x - 4 * s)} {_n(y - 8 * s)} {_n(x - 1 * s)} {_n(y - 9 * s)} '
        f'M{_n(x)} {_n(y)} Q{_n(x)} {_n(y - 11 * s)} {_n(x + 2 * s)} {_n(y - 12 * s)} '
        f'M{_n(x + 5 * s)} {_n(y)} Q{_n(x + 5 * s)} {_n(y - 8 * s)} {_n(x + 8 * s)} {_n(y - 9 * s)}'
    )


def _tree(x: float, base_y: float, h: float = 44.0) -> list[str]:
    trunk_w = h * 0.12
    canopy_r = h * 0.34
    top = base_y - h
    return [
        _line(x - trunk_w, base_y, x - trunk_w * 0.6, top + canopy_r),
        _line(x + trunk_w, base_y, x + trunk_w * 0.6, top + canopy_r),
        _circle(x, top + canopy_r, canopy_r),
        _arc(x - canopy_r * 0.8, top + canopy_r * 0.9,
             x + canopy_r * 0.2, top + canopy_r * 1.5, canopy_r),
    ]


def _bush(x: float, base_y: float, w: float = 26.0) -> str:
    h = w * 0.62
    return (
        f'M{_n(x - w / 2)} {_n(base_y)} '
        f'a{_n(w * 0.28)} {_n(h * 0.55)} 0 0 1 {_n(w * 0.3)} {_n(-h * 0.75)} '
        f'a{_n(w * 0.3)} {_n(h * 0.7)} 0 0 1 {_n(w * 0.42)} {_n(0)} '
        f'a{_n(w * 0.28)} {_n(h * 0.55)} 0 0 1 {_n(w * 0.28)} {_n(h * 0.75)} Z'
    )


def _window_grid(x: float, y: float, w: float, h: float,
                 cols: int, rows: int, gap: float = 3.0) -> list[str]:
    """One stroke per lit window — how the epic skyline earns its stroke count."""
    cell_w = (w - gap * (cols + 1)) / cols
    cell_h = (h - gap * (rows + 1)) / rows
    if cell_w <= 0 or cell_h <= 0:
        return []
    out = []
    for r in range(rows):
        for c in range(cols):
            out.append(_rect(
                x + gap + c * (cell_w + gap),
                y + gap + r * (cell_h + gap),
                cell_w, cell_h,
            ))
    return out


def _building(x: float, w: float, base_y: float, top_y: float,
              cols: int, rows: int) -> list[str]:
    return [
        _line(x, base_y, x, top_y),
        _line(x + w, base_y, x + w, top_y),
        _line(x, top_y, x + w, top_y),
    ] + _window_grid(x + 3, top_y + 5, w - 6, (base_y - top_y) - 12, cols, rows)


def _fish_motif(cx: float, cy: float, s: float = 1.0, flip: bool = False) -> list[str]:
    d = -1.0 if flip else 1.0
    body_rx, body_ry = 16 * s, 10 * s
    tail_x = cx + d * body_rx
    return [
        _ellipse(cx, cy, body_rx, body_ry),
        _poly([
            (tail_x, cy),
            (tail_x + d * 11 * s, cy - 8 * s),
            (tail_x + d * 11 * s, cy + 8 * s),
        ], close=True),
        _quad(cx - d * 3 * s, cy - body_ry, cx + d * 3 * s, cy - body_ry - 7 * s,
              cx + d * 9 * s, cy - body_ry + 1 * s),
        _quad(cx - d * 2 * s, cy + body_ry, cx + d * 2 * s, cy + body_ry + 6 * s,
              cx + d * 8 * s, cy + body_ry - 1 * s),
        _circle(cx - d * 9 * s, cy - 2 * s, 2.6 * s),
        _arc(cx - d * 3 * s, cy - 7 * s, cx - d * 3 * s, cy + 7 * s, 9 * s,
             sweep=0 if flip else 1),
    ]


def _bubbles(points: Iterable[tuple[float, float, float]]) -> list[str]:
    return [_circle(x, y, r) for x, y, r in points]


def _seaweed(x: float, base_y: float, h: float = 46.0, waves: int = 3) -> str:
    step = h / waves
    parts = [f'M{_n(x)} {_n(base_y)}']
    for i in range(waves):
        y = base_y - i * step
        direction = 9 if i % 2 == 0 else -9
        parts.append(
            f'Q{_n(x + direction)} {_n(y - step / 2)} {_n(x)} {_n(y - step)}'
        )
    return ' '.join(parts)


# ---------------------------------------------------------------------------
# The picture library
#
# Each builder returns strokes in DRAWING order: the opening dot, then the
# subject's outline, then its detail, then the background. A student who stops
# half way should still recognise what they are making.
# ---------------------------------------------------------------------------

def _picture_balloon() -> list[str]:
    return [
        _dot(120, 120),
        _ellipse(120, 78, 34, 42),
        _poly([(114, 122), (120, 114), (126, 122)], close=True),
        _line(100, 110, 105, 146),
        _line(140, 110, 135, 146),
        _line(102, 146, 138, 146),
        _poly([(104, 146), (108, 166), (132, 166), (136, 146)], close=False),
        _line(106, 156, 134, 156),
        _arc(102, 70, 111, 50, 22),
        _cloud(46, 46, 0.85),
        _cloud(196, 62, 0.7),
        *_sun(210, 28, 12, rays=6),
        _line(10, GROUND_Y, 230, GROUND_Y),
        _bird(64, 104, 0.8),
        _bird(86, 116, 0.6),
    ]


def _picture_fish() -> list[str]:
    return [
        _dot(88, 76, 1.8),
        _ellipse(118, 88, 42, 28),
        _poly([(160, 88), (192, 66), (192, 110)], close=True),
        _quad(106, 60, 124, 40, 142, 64),
        _quad(110, 116, 122, 130, 136, 118),
        _circle(88, 76, 7),
        _arc(100, 66, 100, 110, 26),
        _quad(76, 94, 84, 100, 94, 96),
        _arc(114, 64, 114, 112, 28),
        _arc(130, 66, 130, 110, 26),
        _arc(146, 70, 146, 106, 22),
        *_bubbles([(64, 52, 5), (52, 36, 3.5), (60, 24, 2.5)]),
        _wave(20, 10, 230, 4, 5),
        _wave(30, 10, 230, 3, 4),
        _seaweed(28, GROUND_Y, 40, 3),
        _seaweed(208, GROUND_Y, 52, 3),
        _line(6, GROUND_Y, 234, GROUND_Y),
    ]


def _picture_kite() -> list[str]:
    return [
        _dot(112, 74),
        _poly([(112, 26), (148, 74), (112, 124), (76, 74)], close=True),
        _line(112, 26, 112, 124),
        _line(76, 74, 148, 74),
        _cubic(112, 124, 126, 136, 134, 148, 150, 162),
        _poly([(120, 132), (127, 128), (127, 136)], close=True),
        _poly([(130, 146), (137, 142), (137, 150)], close=True),
        _poly([(141, 157), (148, 153), (148, 161)], close=True),
        _cubic(112, 124, 92, 140, 70, 146, 44, 160),
        _cloud(52, 40, 0.8),
        _cloud(192, 52, 0.7),
        *_sun(206, 24, 11, rays=6),
        _bird(70, 96, 0.7),
        _bird(88, 108, 0.55),
        _line(6, GROUND_Y, 234, GROUND_Y),
        _grass_tuft(30, GROUND_Y),
        _grass_tuft(210, GROUND_Y),
    ]


def _pine(x: float, base_y: float, h: float = 34.0) -> list[str]:
    """A three-tier conifer — the mountain scene's foreground."""
    w = h * 0.5
    return [
        _poly([(x - w * 0.5, base_y - h * 0.45), (x, base_y - h),
               (x + w * 0.5, base_y - h * 0.45)], close=True),
        _poly([(x - w * 0.75, base_y - h * 0.2), (x, base_y - h * 0.72),
               (x + w * 0.75, base_y - h * 0.2)], close=True),
        _poly([(x - w, base_y - h * 0.02), (x, base_y - h * 0.5),
               (x + w, base_y - h * 0.02)], close=True),
        _line(x, base_y, x, base_y - h * 0.1),
    ]


def _picture_mountain() -> list[str]:
    lake_y = 142
    return [
        _dot(120, 38),
        _poly([(58, lake_y), (120, 36), (182, lake_y)], close=False),
        _poly([(100, 70), (108, 79), (117, 70), (126, 79), (134, 70), (142, 79)],
              close=False),
        _poly([(120, 36), (134, 96), (126, lake_y)], close=False),
        _poly([(16, lake_y), (64, 64), (100, 116)], close=False),
        _poly([(54, 82), (61, 89), (68, 80), (75, 88)], close=False),
        _poly([(142, 118), (188, 72), (226, lake_y)], close=False),
        _poly([(178, 88), (185, 95), (192, 86), (199, 94)], close=False),
        *_sun(206, 34, 11, rays=6),
        _cloud(52, 36, 0.7),
        _cloud(150, 28, 0.6),
        _bird(84, 50, 0.7),
        _bird(104, 42, 0.55),
        _line(6, lake_y, 234, lake_y),
        _wave(152, 10, 230, 3, 6),
        _wave(162, 10, 230, 3, 5),
        _line(96, 148, 144, 148),
        _line(108, 156, 132, 156),
        *_pine(28, lake_y, 32),
        *_pine(210, lake_y, 28),
    ]


def _picture_sailboat() -> list[str]:
    deck_y = 118
    return [
        _dot(120, 30),
        _line(120, 32, 120, deck_y),
        _poly([(124, 40), (124, deck_y - 4), (174, deck_y - 4)], close=True),
        _poly([(116, 50), (116, deck_y - 4), (74, deck_y - 4)], close=True),
        _line(132, 72, 166, 72),
        _line(128, 94, 170, 94),
        _poly([(60, deck_y), (190, deck_y), (172, 146), (78, 146)], close=True),
        _line(64, 128, 186, 128),
        _rect(96, 100, 22, 18),
        _line(107, 100, 107, 118),
        _poly([(120, 30), (144, 36), (120, 42)], close=True),
        _circle(88, 137, 3.4),
        _circle(104, 137, 3.4),
        _circle(120, 137, 3.4),
        _wave(150, 6, 234, 5, 6),
        _wave(160, 6, 234, 4, 5),
        _wave(169, 6, 234, 3, 4),
        *_sun(34, 34, 12, rays=6),
        _cloud(176, 34, 0.7),
        _bird(84, 48, 0.7),
        _bird(104, 40, 0.55),
    ]


def _picture_rocket() -> list[str]:
    return [
        _dot(120, 32),
        _poly([(120, 28), (142, 74), (98, 74)], close=True),
        _line(98, 74, 98, 124),
        _line(142, 74, 142, 124),
        _line(98, 124, 142, 124),
        _circle(120, 92, 13),
        _circle(120, 92, 7),
        _poly([(98, 100), (78, 134), (98, 124)], close=True),
        _poly([(142, 100), (162, 134), (142, 124)], close=True),
        _line(98, 112, 142, 112),
        _quad(102, 124, 120, 172, 138, 124),
        _quad(110, 124, 120, 156, 130, 124),
        _circle(198, 44, 17),
        _ellipse(198, 44, 27, 7),
        _circle(38, 38, 13),
        _circle(32, 34, 3),
        _circle(43, 45, 2.4),
        _star(60, 92, 6),
        _star(182, 104, 7),
        _star(34, 128, 5),
        _star(206, 138, 5),
        _star(76, 26, 4.5),
        _star(160, 20, 4),
        _dot(50, 64, 1.6),
        _dot(190, 74, 1.6),
        _dot(84, 150, 1.6),
        _dot(168, 158, 1.6),
    ]


def _picture_robot() -> list[str]:
    return [
        _dot(120, 24),
        _circle(120, 24, 5),
        _line(120, 29, 120, 44),
        _rect(92, 44, 56, 40),
        _circle(108, 60, 7),
        _circle(132, 60, 7),
        _dot(108, 60, 2.4),
        _dot(132, 60, 2.4),
        _rect(104, 70, 32, 8),
        _line(112, 70, 112, 78),
        _line(120, 70, 120, 78),
        _line(128, 70, 128, 78),
        _line(110, 84, 110, 92),
        _line(130, 84, 130, 92),
        _rect(84, 92, 72, 54),
        _rect(98, 102, 44, 24),
        _line(102, 114, 138, 114),
        _circle(104, 136, 4),
        _circle(120, 136, 4),
        _circle(136, 136, 4),
        _line(84, 100, 64, 120),
        _circle(60, 124, 6),
        _line(156, 100, 176, 120),
        _circle(180, 124, 6),
        _rect(96, 146, 12, 20),
        _rect(132, 146, 12, 20),
        _quad(92, 166, 102, 172, 112, 166),
        _quad(128, 166, 138, 172, 148, 166),
        _dot(96, 48, 2),
        _dot(144, 48, 2),
        _line(6, GROUND_Y + 4, 234, GROUND_Y + 4),
    ]


def _picture_dino() -> list[str]:
    body_cx, body_cy, body_rx, body_ry = 126.0, 112.0, 46.0, 26.0

    def back_y(x: float) -> float:
        """Where the back is at *x* — spikes have to sit ON the body."""
        t = (x - body_cx) / body_rx
        return body_cy - body_ry * math.sqrt(max(0.0, 1 - t * t))

    spikes = [
        _poly([
            (x - 7, back_y(x - 7)),
            (x, back_y(x) - 15),
            (x + 7, back_y(x + 7)),
        ], close=True)
        for x in (104, 120, 136, 152)
    ]

    return [
        _dot(56, 55, 1.6),
        _ellipse(body_cx, body_cy, body_rx, body_ry),
        _cubic(94, 90, 84, 76, 80, 64, 70, 56),
        _cubic(86, 100, 80, 86, 78, 76, 72, 70),
        _ellipse(56, 60, 20, 13),
        _circle(56, 55, 3.6),
        _dot(56, 55, 1.4),
        _dot(41, 57, 1.4),
        _quad(38, 64, 46, 70, 58, 69),
        *spikes,
        _cubic(170, 108, 194, 100, 208, 110, 224, 126),
        _quad(224, 126, 216, 130, 212, 124),
        _rect(100, 130, 13, 34),
        _rect(122, 132, 13, 32),
        _rect(146, 130, 13, 34),
        _quad(96, 164, 106, 172, 117, 164),
        _quad(142, 164, 152, 172, 163, 164),
        _arc(98, 120, 156, 124, 48, sweep=0),
        _circle(124, 102, 4),
        _circle(142, 110, 3.4),
        _circle(156, 100, 3),
        _line(6, GROUND_Y, 234, GROUND_Y),
        _grass_tuft(24, GROUND_Y),
        _grass_tuft(216, GROUND_Y, 1.2),
        _cloud(48, 28, 0.7),
        *_sun(196, 26, 10, rays=5),
    ]


def _tower(x: float, w: float, top_y: float, base_y: float,
           merlons: int = 3, flag: bool = True) -> list[str]:
    """One castle tower: walls, crenellated top, an arched window and a flag."""
    merlon_w = w / (merlons * 2 - 1)
    crown: list[tuple[float, float]] = [(x, top_y + 8)]
    for i in range(merlons * 2 - 1):
        mx = x + i * merlon_w
        up = (i % 2 == 0)
        crown.append((mx, top_y if up else top_y + 8))
        crown.append((mx + merlon_w, top_y if up else top_y + 8))
    crown.append((x + w, top_y + 8))
    cx = x + w / 2
    strokes = [
        _line(x, base_y, x, top_y + 8),
        _line(x + w, base_y, x + w, top_y + 8),
        _poly(crown, close=False),
        _arc(cx - 5, top_y + 30, cx + 5, top_y + 30, 5, large=0, sweep=1),
        _poly([(cx - 5, top_y + 30), (cx - 5, top_y + 42),
               (cx + 5, top_y + 42), (cx + 5, top_y + 30)], close=False),
        _line(cx - 5, top_y + 36, cx + 5, top_y + 36),
    ]
    if flag:
        strokes += [
            _line(cx, top_y, cx, top_y - 18),
            _poly([(cx, top_y - 18), (cx + 16, top_y - 13), (cx, top_y - 8)], close=True),
        ]
    return strokes


def _picture_castle() -> list[str]:
    base = 148
    return [
        _dot(120, 60),
        *_tower(96, 48, 52, base, merlons=3, flag=True),
        *_tower(30, 34, 72, base, merlons=3, flag=True),
        *_tower(176, 34, 72, base, merlons=3, flag=True),
        _line(64, base, 64, 100),
        _line(96, base, 96, 100),
        _poly([(64, 100), (64, 94), (72, 94), (72, 100),
               (80, 100), (80, 94), (88, 94), (88, 100), (96, 100)], close=False),
        _line(144, base, 144, 100),
        _line(176, base, 176, 100),
        _poly([(144, 100), (144, 94), (152, 94), (152, 100),
               (160, 100), (160, 94), (168, 94), (168, 100), (176, 100)], close=False),
        _arc(108, 118, 132, 118, 12, large=0, sweep=1),
        _line(108, 118, 108, base),
        _line(132, 118, 132, base),
        _line(120, 106, 120, base),
        _line(110, 128, 130, 128),
        _line(110, 138, 130, 138),
        _line(64, 112, 96, 112),
        _line(64, 126, 96, 126),
        _line(144, 112, 176, 112),
        _line(144, 126, 176, 126),
        _line(72, 119, 72, 126),
        _line(88, 105, 88, 112),
        _line(152, 119, 152, 126),
        _line(168, 105, 168, 112),
        _line(14, base, 226, base),
        _wave(158, 10, 230, 3, 6),
        _wave(166, 10, 230, 3, 5),
        _cloud(44, 30, 0.75),
        _cloud(198, 26, 0.65),
        *_sun(22, 96, 10, rays=6),
        _bird(120, 32, 0.6),
        _bird(140, 24, 0.5),
        _bush(20, base, 22),
        _bush(220, base, 22),
    ]


def _picture_underwater() -> list[str]:
    return [
        _dot(78, 66, 1.8),
        *_fish_motif(88, 70, 1.15),
        *_fish_motif(170, 108, 0.9, flip=True),
        *_fish_motif(58, 126, 0.75),
        _seaweed(24, GROUND_Y, 56, 3),
        _seaweed(36, GROUND_Y, 40, 3),
        _seaweed(220, GROUND_Y, 50, 3),
        _quad(186, GROUND_Y, 186, 138, 176, 130),
        _quad(186, GROUND_Y, 192, 140, 202, 134),
        _quad(186, GROUND_Y, 188, 134, 186, 126),
        _quad(96, GROUND_Y, 111, GROUND_Y - 20, 126, GROUND_Y),
        _quad(126, GROUND_Y, 137, GROUND_Y - 14, 148, GROUND_Y),
        _star(146, 148, 11),
        *_bubbles([
            (112, 52, 4.5), (104, 38, 3), (118, 30, 2.2),
            (196, 74, 4), (204, 60, 2.8), (192, 48, 2),
            (44, 96, 3.2), (36, 84, 2.2),
        ]),
        _wave(18, 6, 234, 5, 6),
        _wave(28, 6, 234, 4, 5),
        _line(14, 36, 36, 60),
        _line(30, 34, 52, 58),
        _line(46, 34, 68, 58),
        _ellipse(206, 152, 18, 9),
        _line(198, 152, 194, 162),
        _line(206, 152, 206, 164),
        _line(214, 152, 218, 162),
        _line(196, 146, 192, 140),
        _line(216, 146, 220, 140),
        _dot(200, 148, 1.6),
        _dot(212, 148, 1.6),
        _line(6, GROUND_Y, 234, GROUND_Y),
    ]


def _picture_treehouse() -> list[str]:
    return [
        _dot(120, 156, 1.8),
        _cubic(104, GROUND_Y, 108, 140, 106, 120, 108, 96),
        _cubic(136, GROUND_Y, 132, 140, 134, 120, 132, 96),
        _quad(108, 112, 88, 106, 72, 92),
        _quad(132, 108, 154, 102, 170, 88),
        _quad(110, 96, 100, 84, 92, 74),
        _quad(130, 94, 142, 82, 150, 72),
        _circle(84, 62, 22),
        _circle(126, 48, 26),
        _circle(164, 66, 20),
        _arc(66, 70, 96, 76, 24),
        _arc(148, 72, 178, 70, 22),
        _line(72, 118, 168, 118),
        _line(78, 118, 78, 84),
        _line(162, 118, 162, 84),
        _poly([(70, 84), (120, 60), (170, 84)], close=False),
        _line(70, 84, 170, 84),
        _rect(88, 92, 18, 18),
        _line(97, 92, 97, 110),
        _line(88, 101, 106, 101),
        _poly([(134, 118), (134, 94), (152, 94), (152, 118)], close=False),
        _circle(148, 108, 2.4),
        _line(112, 118, 112, 146),
        _line(126, 118, 126, 146),
        _line(112, 126, 126, 126),
        _line(112, 133, 126, 133),
        _line(112, 140, 126, 140),
        _line(112, 146, 126, 146),
        _line(112, 152, 126, 152),
        _line(112, 158, 126, 158),
        _line(112, 164, 126, 164),
        _line(146, 118, 144, 148),
        _line(160, 118, 162, 148),
        _rect(140, 148, 26, 5),
        _line(6, GROUND_Y, 234, GROUND_Y),
        _grass_tuft(28, GROUND_Y),
        _grass_tuft(62, GROUND_Y, 0.8),
        _grass_tuft(206, GROUND_Y),
        _bush(42, GROUND_Y, 24),
        _bush(216, GROUND_Y, 20),
        _cloud(36, 24, 0.7),
        _cloud(206, 30, 0.6),
        *_sun(212, 96, 9, rays=5),
        _bird(56, 34, 0.6),
        _bird(78, 26, 0.5),
    ]


def _picture_city() -> list[str]:
    """The 100+ question picture: a whole skyline, one lit window at a time."""
    road_y = 150
    strokes: list[str] = [_dot(120, 146, 1.8)]
    # Buildings, tallest in the middle, drawn outward from the centre so the
    # skyline reads as a skyline early rather than growing left to right.
    for x, w, top, cols, rows in (
        (96, 48, 40, 3, 4),
        (146, 40, 62, 3, 3),
        (52, 42, 58, 3, 3),
        (188, 36, 84, 2, 3),
        (12, 38, 88, 2, 3),
    ):
        strokes += _building(x, w, road_y, top, cols, rows)
    strokes += [
        _poly([(96, 40), (120, 22), (144, 40)], close=False),
        _line(120, 22, 120, 10),
        _dot(120, 8, 2.2),
        _line(6, road_y, 234, road_y),
        _line(6, road_y + 22, 234, road_y + 22),
    ]
    for i in range(6):
        x = 16 + i * 38
        strokes.append(_line(x, road_y + 11, x + 18, road_y + 11))
    # Two cars on the road.
    for cx in (56, 168):
        strokes += [
            _poly([(cx - 18, road_y + 18), (cx - 18, road_y + 10),
                   (cx + 18, road_y + 10), (cx + 18, road_y + 18)], close=True),
            _poly([(cx - 11, road_y + 10), (cx - 7, road_y + 3),
                   (cx + 8, road_y + 3), (cx + 12, road_y + 10)], close=True),
            _circle(cx - 10, road_y + 18, 4),
            _circle(cx + 10, road_y + 18, 4),
        ]
    # Street lamps.
    for x in (30, 210):
        strokes += [
            _line(x, road_y, x, road_y - 26),
            _quad(x, road_y - 26, x + 6, road_y - 32, x + 12, road_y - 28),
            _circle(x + 13, road_y - 27, 3),
        ]
    strokes += [
        _circle(206, 30, 14),
        _circle(202, 26, 3.4),
        _circle(210, 35, 2.4),
        _circle(211, 23, 1.8),
    ]
    for x, y, r in (
        (24, 20, 5), (52, 34, 4), (76, 16, 4.5), (100, 30, 3.5),
        (140, 18, 4), (164, 34, 3.5), (180, 14, 4.5), (44, 60, 3),
        (232, 56, 3.5), (8, 44, 3),
    ):
        strokes.append(_star(x, y, r))
    strokes += [
        _cloud(70, 74, 0.6),
        _cloud(176, 60, 0.5),
    ]
    for x in (24, 120, 220):
        strokes += _tree(x, road_y + 22, 26)
    return strokes


def _picture_space() -> list[str]:
    """The other 100+ picture: a space station, its panels lit cell by cell."""
    strokes: list[str] = [_dot(120, 86, 1.8)]
    strokes += [
        _ellipse(120, 86, 26, 20),
        _circle(120, 86, 9),
        _line(94, 86, 78, 86),
        _line(146, 86, 162, 86),
        _rect(60, 70, 18, 32),
        _rect(162, 70, 18, 32),
        _line(102, 66, 102, 106),
        _line(138, 66, 138, 106),
        _line(120, 66, 120, 40),
        _circle(120, 34, 7),
        _line(120, 106, 120, 126),
        _rect(108, 126, 24, 16),
    ]
    strokes += _window_grid(58, 68, 22, 36, 2, 4)
    strokes += _window_grid(160, 68, 22, 36, 2, 4)
    strokes += [
        _circle(44, 138, 26),
        _circle(36, 130, 5),
        _circle(52, 146, 4),
        _circle(50, 128, 3),
        _circle(38, 148, 2.4),
        _arc(20, 132, 68, 132, 26, sweep=1),
        _circle(200, 44, 20),
        _ellipse(200, 44, 32, 8),
        _arc(186, 36, 208, 34, 14, sweep=1),
        _arc(190, 52, 212, 50, 14, sweep=1),
        _circle(206, 118, 10),
        _circle(206, 118, 4),
        _line(196, 118, 186, 118),
        _line(216, 118, 226, 118),
        _rect(180, 110, 8, 16),
        _rect(224, 110, 8, 16),
        _quad(24, 34, 44, 44, 64, 40),
        _quad(22, 40, 42, 50, 62, 46),
        _circle(20, 36, 5),
    ]
    for x, y, r in (
        (14, 74, 4), (34, 96, 3), (78, 24, 4.5), (96, 14, 3),
        (150, 20, 4), (172, 12, 3), (228, 74, 4), (214, 92, 3),
        (60, 156, 3.5), (92, 160, 3), (150, 156, 3.5), (176, 164, 3),
        (238, 26, 3), (8, 110, 3),
    ):
        strokes.append(_star(x, y, r))
    for x, y, r in (
        (48, 58, 1.6), (84, 118, 1.6), (158, 108, 1.6), (188, 82, 1.6),
        (110, 158, 1.6), (232, 140, 1.6), (14, 158, 1.6), (136, 150, 1.6),
    ):
        strokes.append(_dot(x, y, r))
    return strokes


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Picture:
    """One drawing: its identity, who it suits, and its strokes in order."""

    key: str
    title: str
    tier: str
    band: str
    strokes: tuple[str, ...]

    @property
    def stroke_count(self) -> int:
        return len(self.strokes)

    def payload(self) -> dict:
        """The JSON handed to the browser renderer.

        ``title`` is deliberately included even though the page keeps it hidden
        until the drawing is finished — the reveal is a client-side flourish,
        not a secret worth a second round trip.
        """
        return {
            'key': self.key,
            'title': self.title,
            'tier': self.tier,
            'band': self.band,
            'width': CANVAS_WIDTH,
            'height': CANVAS_HEIGHT,
            'strokes': list(self.strokes),
        }


def _build(key: str, title: str, tier: str, band: str, builder) -> Picture:
    return Picture(key=key, title=title, tier=tier, band=band,
                   strokes=tuple(builder()))


PICTURES: dict[str, Picture] = {
    p.key: p for p in (
        _build('balloon', 'Hot air balloon', TIER_SIMPLE, BAND_JUNIOR, _picture_balloon),
        _build('fish', 'A friendly fish', TIER_SIMPLE, BAND_JUNIOR, _picture_fish),
        _build('kite', 'Kite on a windy day', TIER_SIMPLE, BAND_JUNIOR, _picture_kite),
        _build('mountain', 'Mountain lake', TIER_SIMPLE, BAND_SENIOR, _picture_mountain),
        _build('sailboat', 'Sailing boat', TIER_SIMPLE, BAND_ANY, _picture_sailboat),
        _build('rocket', 'Rocket to the stars', TIER_MEDIUM, BAND_ANY, _picture_rocket),
        _build('robot', 'Wind-up robot', TIER_MEDIUM, BAND_ANY, _picture_robot),
        _build('dino', 'Spiky dinosaur', TIER_MEDIUM, BAND_JUNIOR, _picture_dino),
        _build('castle', 'Castle on the moat', TIER_RICH, BAND_ANY, _picture_castle),
        _build('underwater', 'Under the sea', TIER_RICH, BAND_ANY, _picture_underwater),
        _build('treehouse', 'The treehouse', TIER_RICH, BAND_JUNIOR, _picture_treehouse),
        _build('city', 'City at night', TIER_EPIC, BAND_ANY, _picture_city),
        _build('space', 'Space station', TIER_EPIC, BAND_ANY, _picture_space),
    )
}


def tier_for(total_questions: int) -> str:
    """The complexity tier an exercise of *total_questions* questions earns."""
    try:
        total = int(total_questions)
    except (TypeError, ValueError):
        total = 0
    for bound, tier in TIER_BOUNDS:
        if total <= bound:
            return tier
    return TIER_EPIC


def band_for(year_level) -> str | None:
    """The age band a year level falls in, or ``None`` if it is unknown.

    ``None`` means "do not filter" rather than "junior": the basic-facts and
    school-custom levels use ``level_number`` 100+ / 200+, which say nothing
    about the student's age, and a class can carry no level at all.
    """
    try:
        year = int(year_level)
    except (TypeError, ValueError):
        return None
    if year < 1 or year > 8:
        return None
    return BAND_JUNIOR if year <= JUNIOR_MAX_YEAR else BAND_SENIOR


def pictures_in_tier(tier: str, band: str | None = None) -> list[Picture]:
    """Pictures of *tier*, narrowed to those that suit *band* when given.

    Falls back to the whole tier if the band leaves nothing — a tier must never
    come up empty just because its pictures happen to be banded the other way.
    """
    rows = [p for p in PICTURES.values() if p.tier == tier]
    if band in (BAND_JUNIOR, BAND_SENIOR):
        suited = [p for p in rows if p.band in (band, BAND_ANY)]
        if suited:
            return suited
    return rows


def get(key: str) -> Picture | None:
    """The picture stored under *key*, or ``None`` if it is unknown.

    A ``None`` here is the retired-picture case: a homework draft can outlive a
    change to this catalogue, and callers are expected to fall back to
    :func:`pick` rather than render nothing.
    """
    if not key:
        return None
    return PICTURES.get(key)


def pick(total_questions: int, seed, year_level=None) -> Picture:
    """Choose a picture for an exercise of *total_questions* questions.

    Two dimensions, and they answer different questions. *total_questions*
    picks the tier — how much drawing the work is worth. *year_level* picks the
    band — whether the subject suits the student, so a Year 7 doing a short
    quiz gets the mountain range rather than the balloon a Year 2 gets for the
    same length of work. An unknown or non-year level (basic facts, a custom
    school level, a class with no level) simply does not narrow anything.

    Deterministic in *seed* so a reload mid-quiz redraws the same picture. Pass
    something stable and per-exercise-per-student (a session id, or the
    homework and student ids) — not ``time()``.
    """
    tier = tier_for(total_questions)
    choices = sorted(pictures_in_tier(tier, band_for(year_level)), key=lambda p: p.key)
    if not choices:
        # A tier emptied by an edit to PICTURES must not blank the panel out;
        # fall back to the whole catalogue rather than failing silently.
        choices = sorted(PICTURES.values(), key=lambda p: p.key)
    return random.Random(str(seed)).choice(choices)


def resolve(stored_key: str, total_questions: int, seed,
            year_level=None) -> Picture:
    """The picture to draw, preferring one already started.

    *stored_key* wins whenever it still exists, even if the exercise's question
    count would now choose a different tier. A student part-way through a
    100-question paper must not have their city skyline swapped for a balloon
    because a teacher removed some questions — or because this module gained a
    new picture overnight.
    """
    existing = get(stored_key)
    if existing is not None:
        return existing
    return pick(total_questions, seed, year_level)


def context(picture: Picture, done: int, total: int) -> dict:
    """The template context the shared ``_progress_art.html`` partial expects."""
    total = max(int(total or 0), 0)
    done = min(max(int(done or 0), 0), total)
    return {
        'picture': picture.payload(),
        'key': picture.key,
        'done': done,
        'total': total,
        'is_complete': total > 0 and done >= total,
    }


def year_level_for_classroom(classroom) -> int | None:
    """The teaching year of a class, for :func:`band_for`.

    The lowest curriculum year when a class spans several — a mixed Year 3/4
    class should get the junior pictures, not the senior ones. ``None`` when
    the class carries no curriculum level, or only basic-facts / school-custom
    levels (``level_number`` 100+ / 200+), which say nothing about age.
    """
    levels = getattr(classroom, 'levels', None)
    if levels is None:
        return None
    years = [
        lvl.level_number for lvl in levels.all()
        if 1 <= lvl.level_number <= 8
    ]
    return min(years) if years else None


def answer_is_present(value) -> bool:
    """Whether a saved answer value is an actual answer.

    The construction widgets (draw-on-grid, shape-select, number line) post an
    empty JSON skeleton — ``{"segments": []}`` — before the student has drawn
    anything, and a plain "is this field non-empty?" test would count those as
    answered and give away part of the picture on the very first autosave.

    ``static/js/progress_art.js`` mirrors this rule for its live count; the two
    have to agree or the drawing would jump when the page reloads.
    """
    import json

    text = str('' if value is None else value).strip()
    if not text:
        return False
    if text[0] in '{[':
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return True
        if isinstance(parsed, dict):
            return any(answer_is_present(v) for v in parsed.values())
        if isinstance(parsed, list):
            return any(answer_is_present(v) for v in parsed)
        return bool(parsed)
    return True
