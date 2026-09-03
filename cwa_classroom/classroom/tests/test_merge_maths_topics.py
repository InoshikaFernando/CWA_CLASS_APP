"""Tests for ``merge_maths_topics`` — the agreed plan, applied by path.

The plan was decided against one database and has to run on another, where the
ids differ. Resolving by path is what makes that safe, and it is also the only
thing that separates the two times-table sets: both are called "Division (3×)",
one under ``Number > Division`` and one under the ``Division`` strand.
"""
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from classroom.models import Level, Subject, Topic
from classroom.management.commands.merge_maths_topics import PLAN
from maths.models import Question


@pytest.fixture
def maths(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics')
    level = Level.objects.create(level_number=4, display_name='Year 4')
    return {'subject': subject, 'level': level}


def topic(maths, name, parent=None, slug=None):
    return Topic.objects.create(
        subject=maths['subject'], name=name, parent=parent,
        slug=slug or f'{name.lower().replace(" ", "-")}-{Topic.objects.count()}')


def question(maths, t, text='x'):
    return Question.objects.create(level=maths['level'], topic=t,
                                   question_text=text, question_type='short_answer')


def run(**kwargs):
    out = StringIO()
    call_command('merge_maths_topics', stdout=out, stderr=out, **kwargs)
    return out.getvalue()


# ── the plan itself ───────────────────────────────────────────────────────
def test_no_topic_is_both_kept_and_absorbed():
    """A path on both sides would delete the row another merge merges into."""
    keepers = {row[1] for row in PLAN}
    absorbed = {p for row in PLAN for p in row[2]}
    assert not (keepers & absorbed), keepers & absorbed


def test_no_topic_is_absorbed_twice():
    seen, twice = set(), set()
    for _group, _keep, paths in PLAN:
        for p in paths:
            (twice if p in seen else seen).add(p)
    assert not twice, twice


def test_every_path_starts_at_a_strand_in_the_plan():
    """Every path is 2 or 3 deep — the tree is two levels plus times tables."""
    for _group, keep, paths in PLAN:
        for p in [keep] + list(paths):
            assert 2 <= len(p) <= 3, p


# ── resolution ────────────────────────────────────────────────────────────
def test_the_two_times_tables_are_told_apart(maths):
    number = topic(maths, 'Number')
    deep_parent = topic(maths, 'Division', parent=number)
    deep = topic(maths, 'Division (3×)', parent=deep_parent)
    strand = topic(maths, 'Division')
    shallow = topic(maths, 'Division (3×)', parent=strand)
    question(maths, deep, 'deep')
    question(maths, shallow, 'shallow')

    run(only='times-tables')

    deep.refresh_from_db()
    assert not Topic.objects.filter(pk=shallow.pk).exists()
    assert Question.objects.filter(topic=deep).count() == 2


def test_a_missing_absorbed_row_is_skipped_not_fatal(maths):
    number = topic(maths, 'Number')
    topic(maths, 'Place Value', parent=number)

    out = run(only='near-duplicates')

    assert 'not found' in out
    assert 'Place Values' in out


def test_a_missing_survivor_skips_that_merge_and_says_so(maths):
    """Not fatal: nothing is deleted when the survivor is absent.

    But the plan has then done less than it claims, so it must be reported
    rather than left for the operator to notice from a topic count.
    """
    number = topic(maths, 'Number')
    orphan = topic(maths, 'Place Values', parent=number)

    out = run(only='near-duplicates')

    assert 'did NOT run' in out
    assert 'Place Value' in out
    assert Topic.objects.filter(pk=orphan.pk).exists()


def test_a_missing_survivor_leaves_its_questions_alone(maths):
    number = topic(maths, 'Number')
    orphan = topic(maths, 'Place Values', parent=number)
    question(maths, orphan)

    run(only='near-duplicates')

    assert Question.objects.filter(topic=orphan).count() == 1


def test_two_topics_with_one_path_are_refused_rather_than_guessed(maths):
    number = topic(maths, 'Number')
    topic(maths, 'Place Value', parent=number, slug='pv-a')
    topic(maths, 'Place Value', parent=number, slug='pv-b')
    topic(maths, 'Place Values', parent=number)

    with pytest.raises(CommandError) as err:
        run(only='near-duplicates')
    assert 'Refusing to guess' in str(err.value)


def test_a_topic_of_the_same_name_under_another_strand_is_not_touched(maths):
    number = topic(maths, 'Number')
    keep = topic(maths, 'Place Value', parent=number)
    topic(maths, 'Place Values', parent=number)
    algebra = topic(maths, 'Algebra')
    bystander = topic(maths, 'Place Values', parent=algebra)

    run(only='near-duplicates')

    assert Topic.objects.filter(pk=bystander.pk).exists()
    assert Topic.objects.filter(pk=keep.pk).exists()


# ── behaviour ─────────────────────────────────────────────────────────────
def test_dry_run_writes_nothing(maths):
    number = topic(maths, 'Number')
    topic(maths, 'Place Value', parent=number)
    gone = topic(maths, 'Place Values', parent=number)
    before = Topic.objects.count()

    out = run(only='near-duplicates', dry_run=True)

    assert Topic.objects.count() == before
    assert Topic.objects.filter(pk=gone.pk).exists()
    assert 'DRY RUN' in out


def test_questions_move_to_the_survivor(maths):
    number = topic(maths, 'Number')
    keep = topic(maths, 'Place Value', parent=number)
    gone = topic(maths, 'Place Values', parent=number)
    question(maths, gone)

    run(only='near-duplicates')

    assert Question.objects.filter(topic=keep).count() == 1


def test_year_links_are_carried(maths):
    number = topic(maths, 'Number')
    keep = topic(maths, 'Place Value', parent=number)
    gone = topic(maths, 'Place Values', parent=number)
    gone.levels.add(maths['level'])

    run(only='near-duplicates')

    keep.refresh_from_db()
    assert list(keep.levels.values_list('level_number', flat=True)) == [4]


def test_running_twice_is_a_no_op_rather_than_an_error(maths):
    number = topic(maths, 'Number')
    topic(maths, 'Place Value', parent=number)
    topic(maths, 'Place Values', parent=number)

    run(only='near-duplicates')
    out = run(only='near-duplicates')

    assert 'nothing left to absorb' in out


def test_an_unknown_group_is_rejected(maths):
    with pytest.raises(CommandError):
        run(only='nonsense')


def test_no_maths_subject_is_rejected(db):
    with pytest.raises(CommandError):
        run()
