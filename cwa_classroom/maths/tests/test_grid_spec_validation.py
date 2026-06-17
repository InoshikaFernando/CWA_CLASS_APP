"""Tests for grid_spec schema validation (CPP-338).

The pure ``validate_grid_spec`` helper (reused by Model.clean() and the JSON
importer) raises ValueError on a malformed spec; ``Question.clean()`` surfaces
it as a field ValidationError and forbids answer options. Epic CPP-330.
"""
import pytest
from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import Level
from maths.geometry_grading import validate_grid_spec
from maths.models import Answer, Question


def _valid_spec(**over):
    spec = {
        'grid': {'cols': 11, 'rows': 9},
        'shape': {'type': 'polygon', 'points': [[2, 3], [5, 2], [5, 5], [2, 5]]},
        'mode': 'segments',
        'target': {'segments': [{'x1': 4, 'y1': 0, 'x2': 4, 'y2': 8}]},
        'allow_extra': False,
    }
    spec.update(over)
    return spec


# ── pure validator (no DB) ───────────────────────────────────────────────

def test_accepts_valid_segments_spec():
    validate_grid_spec(_valid_spec())  # must not raise


def test_accepts_valid_points_spec():
    validate_grid_spec(_valid_spec(mode='points', target={'points': [[3, 3], [7, 5]]}))


@pytest.mark.parametrize('spec,fragment', [
    ('not a dict', 'JSON object'),
    ({'grid': {'cols': 11, 'rows': 9}, 'shape': {}, 'mode': 'segments',
      'target': {'segments': []}}, 'non-empty'),
    ({'grid': {'cols': 0, 'rows': 9}, 'shape': {}, 'mode': 'segments',
      'target': {'segments': [{'x1': 1, 'y1': 1, 'x2': 2, 'y2': 2}]}}, 'positive integers'),
    ({'grid': {'cols': 11, 'rows': 9}, 'shape': {}, 'mode': 'bogus',
      'target': {}}, 'mode'),
])
def test_rejects_invalid_specs(spec, fragment):
    with pytest.raises(ValueError) as exc:
        validate_grid_spec(spec)
    assert fragment in str(exc.value)


def test_rejects_missing_target():
    spec = _valid_spec()
    del spec['target']
    with pytest.raises(ValueError):
        validate_grid_spec(spec)


def test_rejects_out_of_range_coords():
    # x=20 exceeds an 11-col grid (valid x is 0..10).
    spec = _valid_spec(target={'segments': [{'x1': 20, 'y1': 0, 'x2': 4, 'y2': 8}]})
    with pytest.raises(ValueError) as exc:
        validate_grid_spec(spec)
    assert 'outside' in str(exc.value)


def test_rejects_zero_length_segment():
    spec = _valid_spec(target={'segments': [{'x1': 4, 'y1': 4, 'x2': 4, 'y2': 4}]})
    with pytest.raises(ValueError) as exc:
        validate_grid_spec(spec)
    assert 'differ' in str(exc.value)


def test_rejects_out_of_range_shape_point():
    spec = _valid_spec(shape={'type': 'polygon', 'points': [[99, 0]]})
    with pytest.raises(ValueError):
        validate_grid_spec(spec)


# ── Question.clean() integration ─────────────────────────────────────────

class DrawOnGridCleanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=985, defaults={'display_name': 'grid clean fixture'},
        )

    def _build(self, **over):
        fields = dict(
            level=self.level, question_text='Draw all lines of symmetry.',
            question_type=Question.DRAW_ON_GRID, difficulty=1, points=1,
            grid_spec=_valid_spec(),
        )
        fields.update(over)
        return Question(**fields)

    def test_clean_requires_grid_spec(self):
        with self.assertRaises(ValidationError) as ctx:
            self._build(grid_spec=None).full_clean()
        self.assertIn('grid_spec', ctx.exception.error_dict)

    def test_clean_rejects_invalid_grid_spec(self):
        bad = _valid_spec(target={'segments': [{'x1': 99, 'y1': 0, 'x2': 4, 'y2': 8}]})
        with self.assertRaises(ValidationError) as ctx:
            self._build(grid_spec=bad).full_clean()
        self.assertIn('grid_spec', ctx.exception.error_dict)

    def test_clean_accepts_valid(self):
        self._build().full_clean()  # must not raise

    def test_clean_rejects_answer_rows(self):
        q = self._build()
        q.save()
        Answer.objects.create(question=q, answer_text='x', is_correct=True)
        with self.assertRaises(ValidationError) as ctx:
            q.clean()
        self.assertIn('question_type', ctx.exception.error_dict)
