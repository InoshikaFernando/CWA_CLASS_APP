"""Tests for measure-question grading (CPP-332).

``grade_measure`` is a pure function (reads only ``numeric_answer`` and
``answer_tolerance``), so most cases use a lightweight stub and need no DB.
One DB-backed test exercises the real ``MathsPlugin.grade_answer`` dispatch
to prove the ``measure`` branch is wired in.

Epic CPP-330; spec docs/specs/CPP-330_interactive_geometry_questions.md.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from maths.geometry_grading import grade_measure


def _q(numeric_answer, tolerance):
    """Minimal stand-in for a measure Question."""
    return SimpleNamespace(
        numeric_answer=numeric_answer,
        answer_tolerance=tolerance,
    )


# ── pure grade_measure tests (no DB) ─────────────────────────────────────

def test_within_tolerance_correct():
    assert grade_measure(_q(Decimal('135'), Decimal('2')), '134') is True


def test_boundary_inclusive():
    q = _q(Decimal('135'), Decimal('2'))
    assert grade_measure(q, '133') is True   # lower bound
    assert grade_measure(q, '137') is True   # upper bound


def test_outside_tolerance_wrong():
    q = _q(Decimal('135'), Decimal('2'))
    assert grade_measure(q, '132') is False
    assert grade_measure(q, '138') is False


def test_null_tolerance_is_exact():
    q = _q(Decimal('135'), None)
    assert grade_measure(q, '135') is True
    assert grade_measure(q, '134') is False


def test_unit_suffix_stripped():
    q = _q(Decimal('135'), Decimal('2'))
    assert grade_measure(q, '135°') is True
    assert grade_measure(q, '134 cm') is True
    assert grade_measure(q, '+136') is True


def test_decimal_value_within_tolerance():
    q = _q(Decimal('135.5'), Decimal('0.5'))
    assert grade_measure(q, '135.9') is True
    assert grade_measure(q, '136.1') is False


@pytest.mark.parametrize('bad', ['abc', '', '   ', None, '°', '--', '.'])
def test_non_numeric_returns_false(bad):
    assert grade_measure(_q(Decimal('135'), Decimal('2')), bad) is False


def test_missing_target_returns_false():
    # A misconfigured measure question (no numeric_answer) is never "correct".
    assert grade_measure(_q(None, Decimal('2')), '135') is False


# ── dispatch wiring through the plugin (DB-backed) ───────────────────────

@pytest.mark.django_db
def test_plugin_grade_answer_routes_measure():
    from classroom.models import Level
    from maths.models import Question
    from maths.plugin import MathsPlugin

    level, _ = Level.objects.get_or_create(
        level_number=993, defaults={'display_name': 'measure grading fixture'},
    )
    q = Question.objects.create(
        level=level,
        question_text='Measure angle a.',
        question_type=Question.MEASURE,
        difficulty=1,
        points=3,
        numeric_answer=Decimal('135'),
        answer_tolerance=Decimal('2'),
        answer_unit='°',
    )

    plugin = MathsPlugin()
    correct = plugin.grade_answer(q.pk, {f'answer_{q.id}': '134'})
    wrong = plugin.grade_answer(q.pk, {f'answer_{q.id}': '120'})

    assert correct['is_correct'] is True
    assert correct['points_earned'] == 3        # question.points on success
    assert wrong['is_correct'] is False
    assert wrong['points_earned'] == 0
