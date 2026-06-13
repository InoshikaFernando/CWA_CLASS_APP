"""Starter content for the geometry/measurement question types (CPP-340).

A small, self-contained seed: one ``draw_on_grid`` "draw all lines of symmetry"
question and one ``measure`` "measure angle a" question. Factored out of the
data migration so it is unit-testable and so the migration stays a thin wrapper.

``seed`` takes the model classes as arguments so it works identically when
called from a migration (``apps.get_model(...)`` — historical models) and from
a test (the real models). It is idempotent: ``get_or_create`` keyed on the
question text + type, so re-running never duplicates. The grid_spec is run
through ``validate_grid_spec`` first, so a bad seed fails loudly.

The symmetry shape is a non-square rectangle — exactly two lines of symmetry
(the vertical and horizontal mid-lines) — chosen so the correct answer set is
unambiguous, rather than reproducing copyrighted exam material.
"""
from decimal import Decimal

from django.utils.text import slugify

from maths.geometry_grading import validate_grid_spec

YEAR_LEVEL = 6

SYMMETRY_TEXT = 'Draw all lines of symmetry on this shape.'
MEASURE_TEXT = 'Measure angle a.'

# 11x9 dot grid; rectangle with corners (2,2)-(8,6). Lines of symmetry: the
# vertical mid-line (5,2)-(5,6) and the horizontal mid-line (2,4)-(8,4).
SYMMETRY_GRID_SPEC = {
    'grid': {'cols': 11, 'rows': 9},
    'shape': {'type': 'polygon', 'points': [[2, 2], [8, 2], [8, 6], [2, 6]]},
    'mode': 'segments',
    'target': {'segments': [
        {'x1': 5, 'y1': 2, 'x2': 5, 'y2': 6},
        {'x1': 2, 'y1': 4, 'x2': 8, 'y2': 4},
    ]},
    'allow_extra': False,
}

MEASURE_ANGLE = Decimal('135')
MEASURE_TOLERANCE = Decimal('2')
MEASURE_UNIT = '°'


def _get_topic(Topic, maths, name):
    # Key on the unique (subject, slug) so a pre-existing topic with the same
    # slug under a slightly different name doesn't trip the unique constraint.
    topic, _ = Topic.objects.get_or_create(
        subject=maths, slug=slugify(name),
        defaults={'name': name, 'order': 99, 'is_active': True},
    )
    return topic


def seed(Subject, Level, Topic, Question, Answer):
    """Create the starter geometry questions if the prerequisites exist."""
    maths = Subject.objects.filter(name='Mathematics', school__isnull=True).first()
    if maths is None:
        return  # No global Mathematics subject — nothing to seed.
    level = Level.objects.filter(level_number=YEAR_LEVEL).first()
    if level is None:
        return

    # Fail loudly if the bundled spec is ever broken by an edit.
    validate_grid_spec(SYMMETRY_GRID_SPEC)

    symmetry_topic = _get_topic(Topic, maths, 'Symmetry')
    symmetry_topic.levels.add(level)
    Question.objects.get_or_create(
        question_text=SYMMETRY_TEXT, question_type='draw_on_grid',
        level=level, topic=symmetry_topic,
        defaults={'difficulty': 2, 'points': 1, 'grid_spec': SYMMETRY_GRID_SPEC},
    )

    angles_topic = _get_topic(Topic, maths, 'Angles')
    angles_topic.levels.add(level)
    Question.objects.get_or_create(
        question_text=MEASURE_TEXT, question_type='measure',
        level=level, topic=angles_topic,
        defaults={
            'difficulty': 2, 'points': 1,
            'numeric_answer': MEASURE_ANGLE,
            'answer_tolerance': MEASURE_TOLERANCE,
            'answer_unit': MEASURE_UNIT,
        },
    )


def unseed(Subject, Level, Topic, Question, Answer):
    Question.objects.filter(question_type='draw_on_grid', question_text=SYMMETRY_TEXT).delete()
    Question.objects.filter(question_type='measure', question_text=MEASURE_TEXT).delete()
