"""Tests for the ``promote_school_questions`` one-step pipeline command.

It chains export → import (and optional recovery); here we verify the core
weekly path promotes a school's questions into the global bank, with the topic
registered for its level, and that --dry-run writes nothing.
"""
import pytest
from django.core.management import call_command

from accounts.models import CustomUser
from classroom.models import Subject, Level, Topic, School
from maths.models import Question, Answer


@pytest.fixture
def setup(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    level = Level.objects.create(level_number=8, display_name='Year 8', school=None)
    algebra = Topic.objects.create(subject=subject, name='Algebra', slug='algebra')
    eb = Topic.objects.create(subject=subject, name='Expanding Brackets',
                              slug='expanding-brackets', parent=algebra)
    admin = CustomUser.objects.create_user('promo_admin', 'a@a.com', 'pass1234')
    school = School.objects.create(name='Promo School', slug='promo-school', admin=admin)
    q = Question.objects.create(
        school=school, level=level, topic=eb,
        question_text='Expand 3(x + 2)', question_type='short_answer',
        difficulty=1, points=1,
    )
    Answer.objects.create(question=q, answer_text='3x + 6', is_correct=True)
    return {'level': level, 'school': school}


def test_promote_creates_global_copy_linked_to_level(setup):
    call_command('promote_school_questions', school=setup['school'].id)

    g = Question.objects.filter(school__isnull=True, question_text='Expand 3(x + 2)')
    assert g.count() == 1
    gq = g.first()
    assert gq.topic.slug == 'expanding-brackets'
    assert gq.topic.parent.slug == 'algebra'
    # Registered for the level so it shows in the year's topic-quiz picker.
    assert gq.topic.levels.filter(pk=setup['level'].pk).exists()
    assert gq.answers.filter(is_correct=True, answer_text='3x + 6').exists()


def test_promote_is_idempotent(setup):
    call_command('promote_school_questions', school=setup['school'].id)
    call_command('promote_school_questions', school=setup['school'].id)
    assert Question.objects.filter(school__isnull=True,
                                   question_text='Expand 3(x + 2)').count() == 1


def test_promote_dry_run_writes_nothing(setup):
    call_command('promote_school_questions', school=setup['school'].id, dry_run=True)
    assert Question.objects.filter(school__isnull=True).count() == 0


# The four self-drawing types whose figure lives entirely in a JSON spec column.
# A promoted copy that loses its spec can't be rendered OR graded, and the
# import's dedup then skips the broken row on every later run — so the
# export → import round trip must carry every one of them.
SPEC_QUESTIONS = [
    {
        'question_text': 'Plot the points (1, 2) and (-3, 4).',
        'question_type': Question.PLOT_POINTS,
        'plane_spec': {'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
                       'mode': 'points', 'target': {'points': [[1, 2], [-3, 4]]}},
    },
    {
        'question_text': 'Read the temperature at 3 hours.',
        'question_type': Question.READ_GRAPH,
        'graph_spec': {'title': 'Cooling', 'x_axis': {'label': 'Hours', 'min': 0, 'max': 6},
                       'y_axis': {'label': 'Temp', 'min': 0, 'max': 100},
                       'series': [{'points': [[0, 90], [3, 45], [6, 20]]}]},
        'numeric_answer': 45, 'answer_tolerance': 2, 'answer_unit': '°C',
    },
    {
        'question_text': 'Mark 2 on the number line.',
        'question_type': Question.NUMBER_LINE,
        'number_line_spec': {'min': -3, 'max': 7, 'step': 1,
                             'mode': 'mark', 'target': [2]},
    },
    {
        'question_text': 'Complete the table for y = 2x - 2.',
        'question_type': Question.TABLE_OF_VALUES,
        'table_spec': {'headers': ['x', 'y'],
                       'rows': [[{'given': '-1'}, {'answer': '-4'}],
                                [{'given': '0'}, {'answer': '-2'}],
                                [{'given': '2'}, {'answer': '2'}]]},
    },
]

SPEC_FIELDS = ('plane_spec', 'graph_spec', 'number_line_spec', 'table_spec')


@pytest.fixture
def spec_setup(setup):
    topic = Topic.objects.get(slug='expanding-brackets')
    for spec in SPEC_QUESTIONS:
        Question.objects.create(
            school=setup['school'], level=setup['level'], topic=topic,
            difficulty=1, points=1, **spec,
        )
    return setup


def test_promote_carries_self_drawing_specs(spec_setup):
    """plane / graph / number-line / table specs survive export → import."""
    call_command('promote_school_questions', school=spec_setup['school'].id)

    for spec in SPEC_QUESTIONS:
        gq = Question.objects.get(school__isnull=True,
                                  question_text=spec['question_text'])
        assert gq.question_type == spec['question_type']
        for field in SPEC_FIELDS:
            if field in spec:
                assert getattr(gq, field) == spec[field], (
                    f'{field} lost promoting {spec["question_text"]!r}')
        # read_graph grades off the measure fields — those ride along too.
        if 'numeric_answer' in spec:
            assert float(gq.numeric_answer) == float(spec['numeric_answer'])
            assert float(gq.answer_tolerance) == float(spec['answer_tolerance'])
            assert gq.answer_unit == spec['answer_unit']


def test_every_type_specific_spec_column_is_exported():
    """Guard: a new ``*_spec`` column must be added to BOTH command field lists.

    The four above were missed for a month exactly this way — the column landed,
    the two SCALAR_FIELDS tuples didn't move, and promoted copies came out blank.
    """
    from maths.management.commands import export_school_questions, import_global_questions

    model_specs = {f.name for f in Question._meta.get_fields()
                   if f.name.endswith('_spec')}
    assert model_specs, 'expected maths.Question to carry *_spec columns'
    assert model_specs <= set(export_school_questions.SCALAR_FIELDS)
    assert model_specs <= set(import_global_questions.SCALAR_FIELDS)
    # The two lists must stay in step — the export writes what the import reads.
    assert (set(export_school_questions.SCALAR_FIELDS)
            == set(import_global_questions.SCALAR_FIELDS))
