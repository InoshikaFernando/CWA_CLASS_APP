"""Tests for the traced-geometry shape forms (image-import support).

Phase 1 stored parametric shapes (centre + size); the image importer stores
explicit ``points`` polygons and ``rx``/``ry`` ellipses. These cover validation,
the SVG builder, and grading for those forms. The parametric form is covered by
test_shape_select_grading.py / _render.py.
"""
import json

import pytest

from maths.geometry_grading import (
    grade_shape_select,
    shape_geometry_form,
    validate_shape_spec,
)
from maths.svg_geometry import shape_select_svg


def _poly(sid, stype, points):
    return {'id': sid, 'type': stype, 'points': points}


def _ellipse(sid, stype, cx, cy, rx, ry, rot=0):
    return {'id': sid, 'type': stype, 'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry, 'rot': rot}


TRI = _poly('s0', 'triangle', [[10, 10], [50, 10], [30, 50]])
CIR = _ellipse('s1', 'circle', 100, 100, 20, 20)
ELL = _ellipse('s2', 'ellipse', 200, 100, 40, 20, rot=15)


def _spec(shapes, target='triangle'):
    return {'target_type': target, 'viewbox': [680, 400], 'shapes': shapes}


def test_geometry_form_detection():
    assert shape_geometry_form(TRI) == 'polygon'
    assert shape_geometry_form(CIR) == 'ellipse'
    assert shape_geometry_form({'cx': 1, 'cy': 1, 'size': 2}) == 'parametric'


def test_validate_accepts_traced_forms():
    validate_shape_spec(_spec([TRI, CIR, ELL]))  # must not raise


@pytest.mark.parametrize('bad', [
    {'id': 's0', 'type': 'triangle', 'points': [[1, 1], [2, 2]]},          # < 3 points
    {'id': 's0', 'type': 'triangle', 'points': [[1, 1], [2, 'x'], [3, 3]]},  # bad coord
    {'id': 's0', 'type': 'triangle', 'points': 'nope'},                    # not a list
])
def test_validate_rejects_bad_polygon(bad):
    with pytest.raises(ValueError):
        validate_shape_spec(_spec([bad]))


def test_validate_rejects_nonpositive_ellipse():
    bad = {'id': 's0', 'type': 'circle', 'cx': 1, 'cy': 1, 'rx': 0, 'ry': 5}
    with pytest.raises(ValueError, match='rx/ry'):
        validate_shape_spec(_spec([bad], target='circle'))


def test_svg_renders_polygon_and_ellipse():
    svg = shape_select_svg(_spec([TRI, CIR, ELL]))
    assert '<polygon' in svg
    assert svg.count('<ellipse') == 2
    assert svg.count('class="cwa-shape"') == 3
    assert 'data-shape-id="s0"' in svg
    assert 'data-shape-type="ellipse"' in svg


def test_grade_traced_set_equality():
    spec = _spec([TRI, CIR, ELL])   # exactly one triangle (s0)
    assert grade_shape_select(spec, json.dumps({'selected': ['s0']})) is True
    assert grade_shape_select(spec, json.dumps({'selected': ['s0', 's1']})) is False
    assert grade_shape_select(spec, json.dumps({'selected': []})) is False
