"""Tests for the ``import_global_questions`` management command.

Verifies that a rich JSON export is promoted into the global bank (school=NULL)
with the year→Level, title→Topic, sub-title→Subtopic hierarchy, images,
type-specific fields and answers preserved — and that re-running is idempotent.
"""
import json

import pytest
from django.core.management import call_command

from classroom.models import Subject, Level, Topic
from maths.models import Question, Answer


def _write(tmp_path, groups, meta=None):
    payload = {'meta': meta or {'question_count': sum(len(g['questions']) for g in groups),
                                'group_count': len(groups)},
               'groups': groups}
    path = tmp_path / 'export.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return str(path)


@pytest.fixture
def global_maths(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    Level.objects.create(level_number=8, display_name='Year 8', school=None)
    return subject


SAMPLE_GROUPS = [
    {
        'year': 'Year 8', 'level_number': 8, 'title': 'Algebra',
        'subtitle': 'Expanding Brackets',
        'questions': [{
            'question_text': 'Expand 2(x + 3)',
            'question_type': 'multiple_choice', 'difficulty': 2, 'points': 1,
            'explanation': 'Distribute the 2.',
            'image': 'questions/year8/expanding-brackets/q1.png',
            'answers': [
                {'answer_text': '2x + 6', 'is_correct': True, 'order': 0},
                {'answer_text': '2x + 3', 'is_correct': False, 'order': 1},
            ],
        }],
    },
    {
        'year': 'Year 8', 'level_number': 8, 'title': 'Number', 'subtitle': '',
        'questions': [{
            'question_text': '18 + 12 + 27',
            'question_type': 'column_operation', 'difficulty': 1, 'points': 1,
            'operands': [18, 12, 27], 'operator': '+',
            'answers': [{'answer_text': '57', 'is_correct': True, 'order': 0}],
        }],
    },
]


def test_import_creates_global_questions_with_hierarchy(global_maths, tmp_path):
    call_command('import_global_questions', _write(tmp_path, SAMPLE_GROUPS))

    assert Question.objects.filter(school__isnull=True).count() == 2

    # title → top-level topic, sub-title → child topic
    algebra = Topic.objects.get(subject=global_maths, slug='algebra')
    assert algebra.parent is None
    expanding = Topic.objects.get(subject=global_maths, slug='expanding-brackets')
    assert expanding.parent_id == algebra.id

    q1 = Question.objects.get(question_text='Expand 2(x + 3)')
    assert q1.school is None
    assert q1.topic_id == expanding.id           # subtopic when present
    assert q1.level.level_number == 8
    assert str(q1.image) == 'questions/year8/expanding-brackets/q1.png'
    assert q1.answers.count() == 2
    assert q1.answers.get(is_correct=True).answer_text == '2x + 6'

    # no sub-title → topic is mirrored as its own same-named sub-topic, so the
    # question still lands at the title › sub-title level. Type fields preserved.
    q2 = Question.objects.get(question_text='18 + 12 + 27')
    number_top = Topic.objects.get(subject=global_maths, name='Number', parent__isnull=True)
    assert q2.topic.name == 'Number'
    assert q2.topic_id != number_top.id          # not the top-level row
    assert q2.topic.parent_id == number_top.id   # mirrored beneath it
    assert q2.operands == [18, 12, 27]
    assert q2.operator == '+'


def test_import_is_idempotent(global_maths, tmp_path):
    path = _write(tmp_path, SAMPLE_GROUPS)
    call_command('import_global_questions', path)
    call_command('import_global_questions', path)        # second run

    assert Question.objects.filter(school__isnull=True).count() == 2
    # answers not duplicated on the skipped re-run
    assert Answer.objects.filter(question__question_text='Expand 2(x + 3)').count() == 2


def test_dry_run_writes_nothing(global_maths, tmp_path):
    call_command('import_global_questions', _write(tmp_path, SAMPLE_GROUPS), '--dry-run')
    assert Question.objects.filter(school__isnull=True).count() == 0
    assert Topic.objects.filter(subject=global_maths).count() == 0


def test_overwrite_updates_and_replaces_answers(global_maths, tmp_path):
    call_command('import_global_questions', _write(tmp_path, SAMPLE_GROUPS))

    changed = json.loads(json.dumps(SAMPLE_GROUPS))
    changed[0]['questions'][0]['explanation'] = 'Updated explanation'
    changed[0]['questions'][0]['answers'] = [
        {'answer_text': '2x + 6', 'is_correct': True, 'order': 0},
    ]
    call_command('import_global_questions', _write(tmp_path, changed), '--overwrite')

    q1 = Question.objects.get(question_text='Expand 2(x + 3)')
    assert q1.explanation == 'Updated explanation'
    assert q1.answers.count() == 1                       # replaced, not appended
    assert Question.objects.filter(school__isnull=True).count() == 2


# Many image questions share a generic stem; they must NOT collapse on import.
IMAGE_GROUP = [{
    'year': 'Year 8', 'level_number': 8, 'title': 'Geometry', 'subtitle': '2D Shapes',
    'questions': [
        {'question_text': 'What is the name of this shape?',
         'question_type': 'multiple_choice', 'difficulty': 1, 'points': 1,
         'image': f'questions/year8/2d-shapes/shape_{i}.png',
         'answers': [{'answer_text': 'Square', 'is_correct': True, 'order': 0}]}
        for i in range(3)
    ],
}]


def test_image_questions_same_text_not_collapsed(global_maths, tmp_path):
    # Three questions, identical text, distinct images → 3 global rows, not 1
    # (dedup must be by image path, not text).
    call_command('import_global_questions', _write(tmp_path, IMAGE_GROUP))

    qs = Question.objects.filter(school__isnull=True,
                                 question_text='What is the name of this shape?')
    assert qs.count() == 3
    assert sorted(str(q.image) for q in qs) == [
        'questions/year8/2d-shapes/shape_0.png',
        'questions/year8/2d-shapes/shape_1.png',
        'questions/year8/2d-shapes/shape_2.png',
    ]

    # Re-run is idempotent (dedup on image path finds them).
    call_command('import_global_questions', _write(tmp_path, IMAGE_GROUP))
    assert qs.count() == 3


def test_import_links_topic_to_level(global_maths, tmp_path):
    # The promoted topic (and its parent strand) must be registered for the
    # level via Topic.levels so it appears in that year's topic-quiz picker.
    call_command('import_global_questions', _write(tmp_path, IMAGE_GROUP))

    level = Level.objects.get(level_number=8)
    two_d = Topic.objects.get(subject=global_maths, slug='2d-shapes')
    geometry = Topic.objects.get(subject=global_maths, slug='geometry')
    assert two_d.levels.filter(pk=level.pk).exists()      # sub-topic linked
    assert geometry.levels.filter(pk=level.pk).exists()   # parent strand linked
    # And it surfaces via the reverse relation the picker uses.
    assert two_d in level.topics.all()
