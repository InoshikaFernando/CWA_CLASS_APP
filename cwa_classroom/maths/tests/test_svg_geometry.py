"""Tests for the generated angle SVG (CPP-333).

Pure-function tests — no DB. The key property is correctness of the angle
*between the two rays*: that is what a pupil measures with a protractor, so
it must equal the requested degrees regardless of render size.

Epic CPP-330; spec docs/specs/CPP-330_interactive_geometry_questions.md.
"""
import math
from decimal import Decimal

import pytest

from maths.svg_geometry import angle_ray_points, angle_svg


def _angle_between(vertex, p_base, p_ray):
    """Interior angle (degrees) at ``vertex`` between the two rays."""
    vx, vy = vertex
    a = math.atan2(p_base[1] - vy, p_base[0] - vx)
    b = math.atan2(p_ray[1] - vy, p_ray[0] - vx)
    diff = math.degrees(abs(a - b)) % 360
    return min(diff, 360 - diff)


@pytest.mark.parametrize('deg', [10, 30, 45, 90, 135, 170])
def test_angle_svg_geometry(deg):
    vertex, base_end, ray_end = angle_ray_points(deg)
    assert _angle_between(vertex, base_end, ray_end) == pytest.approx(deg, abs=0.01)


def test_extreme_angles():
    for deg in (10, 170):
        vertex, base_end, ray_end = angle_ray_points(deg)
        assert _angle_between(vertex, base_end, ray_end) == pytest.approx(deg, abs=0.01)


def test_angle_svg_scale_independent():
    # Same angle, different size → same measured angle (true-to-scale).
    for size in (120, 240, 480):
        vertex, base_end, ray_end = angle_ray_points(135, size=size)
        assert _angle_between(vertex, base_end, ray_end) == pytest.approx(135, abs=0.01)


def test_angle_svg_viewbox_present():
    svg = angle_svg(135)
    assert svg.startswith('<svg')
    assert 'viewBox="0 0 240 240"' in svg
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_angle_svg_label_rendered():
    assert '>a</text>' in angle_svg(135, label='a')
    assert '>x</text>' in angle_svg(60, label='x')


def test_angle_svg_accepts_decimal():
    # numeric_answer is a DecimalField — angle_svg must accept it.
    svg = angle_svg(Decimal('135.5'))
    assert svg.startswith('<svg')


def test_large_arc_flag_for_reflex_angle():
    # > 180° must set the large-arc flag so the arc reads as reflex.
    assert ' 1 0 ' in angle_svg(200)   # large_arc=1, sweep=0
    assert ' 0 0 ' in angle_svg(120)   # large_arc=0, sweep=0
