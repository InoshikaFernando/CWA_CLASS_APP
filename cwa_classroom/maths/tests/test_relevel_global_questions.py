"""Tests for the ``relevel_global_questions`` command."""
import pytest
from django.core.management import call_command

from accounts.models import CustomUser
from classroom.models import Subject, Level, Topic, School
from maths.models import Question


@pytest.fixture
def setup(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    for n, name in [(1, 'Year 1'), (6, 'Year 6'), (7, 'Year 7'),
                    (9, 'Year 9'), (105, 'Basic Facts')]:
        Level.objects.create(level_number=n, display_name=name, school=None)
    trig = Topic.objects.create(subject=subject, name='Trigonometry', slug='trig')
    quad = Topic.objects.create(subject=subject, name='Quadratics', slug='quad')  # not mapped
    admin = CustomUser.objects.create_user('rl_admin', 'r@r.com', 'pass1234')
    school = School.objects.create(name='S', slug='s-rl', admin=admin)

    def q(level_num, topic, school_obj=None, text='x'):
        return Question.objects.create(
            school=school_obj, level=Level.objects.get(level_number=level_num),
            topic=topic, question_text=text, question_type='multiple_choice',
            difficulty=1, points=1)

    return {'subject': subject, 'school': school, 'trig': trig, 'quad': quad, 'q': q}


def test_relevel_moves_below_target_only(setup):
    q = setup['q']
    low = q(1, setup['trig'], text='trig at Y1')      # -> should move to Y9
    ok = q(9, setup['trig'], text='trig at Y9')       # already Y9 -> stays
    unmapped = q(1, setup['quad'], text='quad at Y1')  # topic not mapped -> stays
    local = q(1, setup['trig'], school_obj=setup['school'], text='local')  # school -> stays
    bf = q(105, setup['trig'], text='basic facts')    # >=100 -> stays

    call_command('relevel_global_questions')

    low.refresh_from_db(); ok.refresh_from_db(); unmapped.refresh_from_db()
    local.refresh_from_db(); bf.refresh_from_db()
    assert low.level.level_number == 9        # moved up
    assert ok.level.level_number == 9         # unchanged
    assert unmapped.level.level_number == 1   # not in mapping
    assert local.level.level_number == 1      # school-scoped untouched
    assert bf.level.level_number == 105       # basic-facts untouched


def test_relevel_dry_run_changes_nothing(setup):
    q = setup['q']
    low = q(1, setup['trig'])
    call_command('relevel_global_questions', '--dry-run')
    low.refresh_from_db()
    assert low.level.level_number == 1


def test_relevel_is_idempotent(setup):
    q = setup['q']
    low = q(1, setup['trig'])
    call_command('relevel_global_questions')
    call_command('relevel_global_questions')
    low.refresh_from_db()
    assert low.level.level_number == 9
    # nothing left below target
    assert not Question.objects.filter(
        school__isnull=True, topic=setup['trig'], level__level_number__lt=9).exists()


def test_relevel_syncs_topic_levels(setup):
    # After moving questions, the topic's level-links must follow so the
    # questions show in the picker at their new year.
    q = setup['q']
    trig = setup['trig']
    trig.levels.add(Level.objects.get(level_number=1))   # stale link at old year
    q(1, trig)  # will move Y1 -> Y9

    call_command('relevel_global_questions')

    linked = set(trig.levels.values_list('level_number', flat=True))
    assert 9 in linked       # linked to the new year (picker shows it)
    assert 1 not in linked   # stale empty old-year link removed
