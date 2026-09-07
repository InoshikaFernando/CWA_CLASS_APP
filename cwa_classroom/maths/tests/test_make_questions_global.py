"""Tests for ``make_questions_global`` — the in-place school → global move.

The command exists because the copy-based promotion leaves two rows carrying
one question, and the homework and practice pools (which union global with a
school's own rows) then serve it twice. Moving keeps one row, so the cases
below pin: the row count never grows, ids survive, and the things pointing at
those ids — answers, assigned homework — keep working.
"""
from datetime import timedelta

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from accounts.models import CustomUser
from classroom.models import (ClassRoom, Department, Level, School, Subject,
                              Topic)
from homework.models import Homework, HomeworkQuestion
from maths.models import Answer, Question

_UNSET = object()      # so school=None can mean "global", not "defaulted"


@pytest.fixture
def bank(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    levels = {n: Level.objects.create(level_number=n, display_name=f'Year {n}')
              for n in (3, 4)}
    admin = CustomUser.objects.create_user('mg_admin', 'mg@example.com', 'pass1234')
    mhm = School.objects.create(name='MHM', slug='mhm-mg', admin=admin)
    other = School.objects.create(name='Other', slug='other-mg', admin=admin)

    number = Topic.objects.create(subject=subject, name='Number', slug='number-mg')
    patterns = Topic.objects.create(subject=subject, name='Number Patterns',
                                    slug='np-mg', parent=number)
    sequences = Topic.objects.create(subject=subject, name='Sequences',
                                     slug='seq-mg', parent=patterns)
    fractions = Topic.objects.create(subject=subject, name='Fractions',
                                     slug='fr-mg', parent=number)
    for t in (patterns, sequences, fractions):
        t.levels.add(levels[4])

    def q(text, level=4, topic=None, school=_UNSET, **extra):
        obj = Question.objects.create(
            school=mhm if school is _UNSET else school,
            level=levels[level], topic=topic or patterns, question_text=text,
            question_type='short_answer', difficulty=1, points=1, **extra)
        Answer.objects.create(question=obj, answer_text='42', is_correct=True)
        return obj

    return {'mhm': mhm, 'other': other, 'levels': levels, 'patterns': patterns,
            'sequences': sequences, 'fractions': fractions, 'q': q,
            'subject': subject}


def move(**kwargs):
    kwargs.setdefault('school_slug', 'mhm-mg')
    call_command('make_questions_global', **kwargs)


def test_moves_the_slice_without_creating_rows(bank):
    q = bank['q']
    a = q('Complete: 14, 18, 22, __')
    b = q('Complete: 5, 10, 15, __', topic=bank['sequences'])
    elsewhere = q('A fraction', topic=bank['fractions'])
    other_year = q('Year 3 pattern', level=3)
    total_before = Question.objects.count()

    move(year=4, topic='Number Patterns')

    assert Question.objects.count() == total_before      # nothing created
    for moved in (a, b):
        moved.refresh_from_db()
        assert moved.school_id is None
        assert moved.answers.count() == 1                # answers ride along
    for untouched in (elsewhere, other_year):
        untouched.refresh_from_db()
        assert untouched.school_id == bank['mhm'].id


def test_skips_a_question_already_global_under_the_same_text(bank):
    """Moving it would put two identical questions in the global bank."""
    q = bank['q']
    q('75, 50, 25 — next two?', school=None)              # already global
    twin = q('75, 50, 25 — next two?')                    # MHM's copy
    fresh = q('Complete: 14, 18, 22, __')

    move(year=4, topic='Number Patterns')

    twin.refresh_from_db(); fresh.refresh_from_db()
    assert twin.school_id == bank['mhm'].id               # left school-private
    assert fresh.school_id is None
    assert Question.objects.filter(school__isnull=True,
                                   question_text='75, 50, 25 — next two?').count() == 1


def test_clears_department_and_class_markers(bank):
    """A global row is visible to everyone — a stale department marker would
    claim otherwise."""
    dept = Department.objects.create(school=bank['mhm'], name='Maths', slug='maths-mg')
    cls = ClassRoom.objects.create(name='Y4A', school=bank['mhm'], is_active=True)
    scoped = bank['q']('Dept-scoped pattern', department=dept, classroom=cls)

    move(year=4, topic='Number Patterns')

    scoped.refresh_from_db()
    assert scoped.school_id is None
    assert scoped.department_id is None
    assert scoped.classroom_id is None


def test_dry_run_writes_nothing(bank):
    target = bank['q']('Complete: 14, 18, 22, __')
    move(year=4, topic='Number Patterns', dry_run=True)
    target.refresh_from_db()
    assert target.school_id == bank['mhm'].id


def test_second_run_is_a_no_op(bank):
    bank['q']('Complete: 14, 18, 22, __')
    move(year=4, topic='Number Patterns')
    with pytest.raises(CommandError, match='nothing to move'):
        move(year=4, topic='Number Patterns')


def test_other_schools_are_untouched(bank):
    theirs = bank['q']('Their pattern', school=bank['other'])
    bank['q']('Our pattern')

    move(year=4, topic='Number Patterns')

    theirs.refresh_from_db()
    assert theirs.school_id == bank['other'].id


def test_refuses_to_move_a_whole_school_unasked(bank):
    bank['q']('Complete: 14, 18, 22, __')
    with pytest.raises(CommandError, match='Refusing to move a whole school'):
        move()


def test_all_flag_moves_everything(bank):
    q = bank['q']
    a = q('Complete: 14, 18, 22, __')
    b = q('A fraction', topic=bank['fractions'])
    c = q('Year 3 pattern', level=3)

    move(all=True)

    for moved in (a, b, c):
        moved.refresh_from_db()
        assert moved.school_id is None


def test_unknown_topic_and_school_are_errors(bank):
    with pytest.raises(CommandError, match='No topic matches'):
        move(year=4, topic='zzz nothing')
    with pytest.raises(CommandError, match='not found'):
        call_command('make_questions_global', school_slug='no-such-school', year=4)


def test_assigned_homework_still_serves_the_moved_questions(bank):
    """The move must not disturb homework that is already out with students."""
    q = bank['q']
    for i in range(3):
        q(f'Complete the pattern {i}')

    cls = ClassRoom.objects.create(name='Y4A', school=bank['mhm'], is_active=True)
    cls.levels.add(bank['levels'][4])
    teacher = CustomUser.objects.create_user('mg_t', 'mgt@example.com', 'pass1234')
    homework = Homework.objects.create(
        classroom=cls, created_by=teacher, title='Week 3', subject_slug='mathematics',
        num_questions=3, due_date=timezone.now() + timedelta(days=7),
        published_at=timezone.now())

    from homework.views import _select_and_save_questions
    _select_and_save_questions(homework, [bank['patterns'].id], 3)
    before = list(HomeworkQuestion.objects.filter(homework=homework)
                  .order_by('order').values_list('content_id', 'question_id'))
    assert len(before) == 3

    move(year=4, topic='Number Patterns')

    after = list(HomeworkQuestion.objects.filter(homework=homework)
                 .order_by('order').values_list('content_id', 'question_id'))
    assert before == after
    assert Question.objects.filter(id__in=[c for c, _ in after]).count() == 3


def test_homework_pool_does_not_double(bank):
    """The whole point of moving rather than copying."""
    q = bank['q']
    for i in range(3):
        q(f'Complete the pattern {i}')
    cls = ClassRoom.objects.create(name='Y4B', school=bank['mhm'], is_active=True)
    cls.levels.add(bank['levels'][4])

    from maths.plugin import MathsPlugin
    plugin = MathsPlugin()
    before = plugin.pick_homework_items(cls, [bank['patterns'].id], n=20)

    move(year=4, topic='Number Patterns')

    after = plugin.pick_homework_items(cls, [bank['patterns'].id], n=20)
    assert len(before) == len(after) == 3
