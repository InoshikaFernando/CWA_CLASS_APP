"""Tests for ``export_school_questions``, focused on the --year / --topic scoping.

The filters exist so a promotion can be scoped to the gap that was found —
"Year 4 Number Patterns has 30 school questions and 1 global one" — instead of
publishing a school's entire private bank in one go.
"""
import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from accounts.models import CustomUser
from classroom.models import Level, School, Subject, Topic
from maths.models import Answer, Question


@pytest.fixture
def bank(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    levels = {n: Level.objects.create(level_number=n, display_name=f'Year {n}')
              for n in (3, 4)}
    admin = CustomUser.objects.create_user('ex_admin', 'ex@example.com', 'pass1234')
    school = School.objects.create(name='Maths Hub', slug='maths-hub-ex', admin=admin)
    other = School.objects.create(name='Other School', slug='other-ex', admin=admin)

    number = Topic.objects.create(subject=subject, name='Number', slug='number-ex')
    patterns = Topic.objects.create(subject=subject, name='Number Patterns',
                                    slug='number-patterns-ex', parent=number)
    sequences = Topic.objects.create(subject=subject, name='Sequences',
                                     slug='sequences-ex', parent=patterns)
    fractions = Topic.objects.create(subject=subject, name='Fractions',
                                     slug='fractions-ex', parent=number)

    def q(level, topic, text, school_obj=None):
        obj = Question.objects.create(
            school=school_obj or school, level=levels[level], topic=topic,
            question_text=text, question_type='short_answer', difficulty=1, points=1)
        Answer.objects.create(question=obj, answer_text='42', is_correct=True)
        return obj

    q(4, patterns, 'Y4 pattern: 14, 18, 22, __')
    q(4, sequences, 'Y4 sequence: 5, 10, 15, __')
    q(3, patterns, 'Y3 pattern: 2, 4, 6, __')
    q(4, fractions, 'Y4 fraction: 1/2 + 1/4')
    q(4, patterns, 'Other school pattern', school_obj=other)

    return {'school': school, 'levels': levels, 'patterns': patterns}


def export(tmp_path, **kwargs):
    out = StringIO()
    path = tmp_path / 'out.json'
    call_command('export_school_questions', output=str(path), stdout=out, **kwargs)
    return json.loads(path.read_text(encoding='utf-8')), out.getvalue()


def texts(payload):
    return {q['question_text'] for g in payload['groups'] for q in g['questions']}


def test_unfiltered_export_takes_the_whole_school(bank, tmp_path):
    payload, _ = export(tmp_path, school=bank['school'].id)
    assert payload['meta']['question_count'] == 4
    assert 'Other school pattern' not in texts(payload)


def test_year_and_topic_narrow_the_export(bank, tmp_path):
    payload, out = export(tmp_path, school=bank['school'].id, year=4,
                          topic='Number Patterns')

    # The sub-topic under "Number Patterns" comes too — questions hang off it.
    assert texts(payload) == {'Y4 pattern: 14, 18, 22, __',
                              'Y4 sequence: 5, 10, 15, __'}
    assert payload['meta']['filter_year'] == 4
    assert payload['meta']['filter_topic'] == 'Number Patterns'
    assert 'matches 2 topic row(s)' in out


def test_year_filter_alone(bank, tmp_path):
    payload, _ = export(tmp_path, school=bank['school'].id, year=3)
    assert texts(payload) == {'Y3 pattern: 2, 4, 6, __'}


def test_exact_topic_excludes_the_strand_siblings(bank, tmp_path):
    loose, _ = export(tmp_path, school=bank['school'].id, topic='Number')
    exact, _ = export(tmp_path, school=bank['school'].id, topic='Number Patterns',
                      exact_topic=True)

    assert 'Y4 fraction: 1/2 + 1/4' in texts(loose)      # strand match
    assert 'Y4 fraction: 1/2 + 1/4' not in texts(exact)


def test_school_slug_works_with_filters(bank, tmp_path):
    payload, _ = export(tmp_path, school_slug=bank['school'].slug, year=4,
                        topic='Number Patterns')
    assert payload['meta']['question_count'] == 2


def test_unknown_topic_is_an_error(bank, tmp_path):
    with pytest.raises(CommandError, match='No topic matches'):
        export(tmp_path, school=bank['school'].id, topic='zzz nothing')


def test_empty_slice_is_an_error_not_an_empty_export(bank, tmp_path):
    """An export of nothing would import as nothing and look like success."""
    with pytest.raises(CommandError, match='nothing to export'):
        export(tmp_path, school=bank['school'].id, year=3, topic='Fractions')
