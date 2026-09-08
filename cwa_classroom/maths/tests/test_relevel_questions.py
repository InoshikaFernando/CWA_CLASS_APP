"""Tests for ``relevel_questions`` — the class-driven year repair.

The command exists because every upload path defaults ``year_level`` to 1
(``homework/views.py``), so a worksheet whose year the extractor could not read
strands its whole batch at Year 1 — where ``_get_questions_for_level`` serves
it to actual Year 1 students. The class a homework was assigned to is set by a
human before any AI runs, so these tests pin that the class is what decides,
and that everything the class cannot decide is left alone rather than guessed.
"""
from datetime import timedelta

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from accounts.models import CustomUser
from classroom.models import ClassRoom, Level, School, Subject, Topic
from homework.models import Homework, HomeworkQuestion
from maths.models import Question


@pytest.fixture
def bank(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)

    # The curriculum ladder questions are filed against — stops at Year 10.
    curriculum = {n: Level.objects.create(level_number=n, display_name=f'Year {n}',
                                          school=None)
                  for n in range(1, 11)}
    # The separate ladder ClassRoom.levels points at, duplicate names and all.
    klass_levels = {
        303: Level.objects.create(level_number=303, display_name='Year 1', school=None),
        309: Level.objects.create(level_number=309, display_name='Year 7', school=None),
        311: Level.objects.create(level_number=311, display_name='Year 9', school=None),
        314: Level.objects.create(level_number=314, display_name='Year 12', school=None),
        316: Level.objects.create(level_number=316, display_name='VCE GM 1/2', school=None),
        318: Level.objects.create(level_number=318, display_name='Selective Enterance',
                                  school=None),
        319: Level.objects.create(level_number=319, display_name='JS', school=None),
    }

    admin = CustomUser.objects.create_user('rq_admin', 'rq@example.com', 'pass1234')
    teacher = CustomUser.objects.create_user('rq_t', 'rqt@example.com', 'pass1234')
    school = School.objects.create(name='MHM', slug='mhm-rq', admin=admin)

    number = Topic.objects.create(subject=subject, name='Number', slug='number-rq')
    indices = Topic.objects.create(subject=subject, name='Indices', slug='indices-rq',
                                   parent=number)

    def make_class(name, *level_numbers):
        cls = ClassRoom.objects.create(name=name, school=school, is_active=True)
        for n in level_numbers:
            cls.levels.add(klass_levels[n])
        return cls

    counter = {'n': 0}

    def question(*classes, level=1, topic=None, school_obj=None):
        """A question at *level*, assigned to each of *classes* via homework."""
        counter['n'] += 1
        q = Question.objects.create(
            school=school if school_obj is None else school_obj,
            level=curriculum[level], topic=topic or indices,
            question_text=f'q{counter["n"]}', question_type='short_answer',
            difficulty=1, points=1)
        for cls in classes:
            hw = Homework.objects.create(
                classroom=cls, created_by=teacher, title=f'HW {counter["n"]}',
                subject_slug='mathematics', num_questions=1,
                due_date=timezone.now() + timedelta(days=7))
            HomeworkQuestion.objects.create(
                homework=hw, question=q, subject_slug='mathematics',
                content_id=q.pk, order=1)
        return q

    return {'school': school, 'curriculum': curriculum, 'levels': klass_levels,
            'make_class': make_class, 'question': question, 'topic': indices,
            'number': number, 'teacher': teacher}


def relevel(**kwargs):
    kwargs.setdefault('year', 1)
    kwargs.setdefault('school_slug', 'mhm-rq')
    call_command('relevel_questions', **kwargs)


# ── the core behaviour ────────────────────────────────────────────────────
def test_moves_to_the_year_of_the_class_it_was_assigned_to(bank):
    y9 = bank['make_class']('Year 9', 311)
    stranded = bank['question'](y9)

    relevel()

    stranded.refresh_from_db()
    assert stranded.level.level_number == 9


def test_bridges_the_class_ladder_to_the_curriculum_ladder(bank):
    """A class on level_number 311 must land the question on level_number 9."""
    y9 = bank['make_class']('Year 9', 311)
    q = bank['question'](y9)

    relevel()

    q.refresh_from_db()
    assert q.level.level_number == 9
    assert q.level_id == bank['curriculum'][9].id
    assert q.level_id != bank['levels'][311].id


def test_class_already_at_the_source_year_is_left_alone(bank):
    y1 = bank['make_class']('Year 1', 303)
    genuine = bank['question'](y1)

    relevel()          # candidates exist, so it reports rather than errors

    genuine.refresh_from_db()
    assert genuine.level.level_number == 1


def test_a_second_class_level_that_resolves_decides_it(bank):
    """Class 'Year 8' + 'Selective Entrance': the year-ladder level wins."""
    bank['levels'][310] = Level.objects.create(
        level_number=310, display_name='Year 8', school=None)
    mixed = bank['make_class']('Year 8', 310, 318)
    q = bank['question'](mixed)

    relevel()

    q.refresh_from_db()
    assert q.level.level_number == 8


# ── the things it must refuse to guess ────────────────────────────────────
def test_never_assigned_is_left_alone(bank):
    orphan = bank['question']()          # no homework at all
    y9 = bank['make_class']('Year 9', 311)
    movable = bank['question'](y9)

    relevel()

    orphan.refresh_from_db(); movable.refresh_from_db()
    assert orphan.level.level_number == 1
    assert movable.level.level_number == 9


def test_a_tie_between_two_years_is_left_alone(bank):
    y7 = bank['make_class']('Year 7', 309)
    y9 = bank['make_class']('Year 9', 311)
    tied = bank['question'](y7, y9)      # one homework each -> 1 vs 1

    relevel()          # candidates exist, so it reports rather than errors

    tied.refresh_from_db()
    assert tied.level.level_number == 1


def test_the_majority_class_year_wins_when_there_is_one(bank):
    y7 = bank['make_class']('Year 7', 309)
    y7b = bank['make_class']('Year 7 B', 309)
    y9 = bank['make_class']('Year 9', 311)
    q = bank['question'](y7, y7b, y9)    # Y7 twice, Y9 once

    relevel()

    q.refresh_from_db()
    assert q.level.level_number == 7


def test_vce_is_skipped_not_squashed_into_year_10(bank):
    vce = bank['make_class']('VCE GM 1/2', 316)
    senior = bank['question'](vce)

    relevel()          # candidates exist, so it reports rather than errors

    senior.refresh_from_db()
    assert senior.level.level_number == 1


def test_a_class_above_the_ladder_is_skipped(bank):
    """'Year 12' parses as a year, but no Year 12 level exists — don't invent one."""
    y12 = bank['make_class']('Year 12', 314)
    senior = bank['question'](y12)

    relevel()          # candidates exist, so it reports rather than errors

    senior.refresh_from_db()
    assert senior.level.level_number == 1


# ── mapping the unmappable ────────────────────────────────────────────────
def test_built_in_override_resolves_junior_scholarship(bank):
    js = bank['make_class']('Junior Scholarship', 319)
    q = bank['question'](js)

    relevel()

    q.refresh_from_db()
    assert q.level.level_number == 5


def test_map_argument_resolves_an_unknown_class_level(bank):
    sel = bank['make_class']('Selective', 318)
    q = bank['question'](sel)

    relevel(map=['Selective Enterance=8'])

    q.refresh_from_db()
    assert q.level.level_number == 8


def test_map_argument_overrides_a_built_in(bank):
    js = bank['make_class']('Junior Scholarship', 319)
    q = bank['question'](js)

    relevel(map=['JS=6'])

    q.refresh_from_db()
    assert q.level.level_number == 6


def test_a_malformed_map_argument_is_rejected(bank):
    y9 = bank['make_class']('Year 9', 311)
    q = bank['question'](y9)

    with pytest.raises(CommandError):
        relevel(map=['JS'])

    q.refresh_from_db()
    assert q.level.level_number == 1


# ── safety ────────────────────────────────────────────────────────────────
def test_dry_run_writes_nothing(bank):
    y9 = bank['make_class']('Year 9', 311)
    q = bank['question'](y9)

    relevel(dry_run=True)

    q.refresh_from_db()
    assert q.level.level_number == 1


def test_rerunning_moves_nothing_further(bank):
    y9 = bank['make_class']('Year 9', 311)
    q = bank['question'](y9)

    relevel()
    q.refresh_from_db()
    assert q.level.level_number == 9

    with pytest.raises(CommandError):
        relevel()          # no Year 1 candidates left
    q.refresh_from_db()
    assert q.level.level_number == 9


def test_another_schools_questions_are_untouched(bank):
    other_admin = CustomUser.objects.create_user('rq_o', 'rqo@example.com', 'pass1234')
    other = School.objects.create(name='Other', slug='other-rq', admin=other_admin)
    y9 = bank['make_class']('Year 9', 311)
    theirs = bank['question'](y9, school_obj=other)
    ours = bank['question'](y9)

    relevel()

    theirs.refresh_from_db(); ours.refresh_from_db()
    assert theirs.level.level_number == 1
    assert ours.level.level_number == 9


def test_topic_filter_scopes_the_move(bank):
    y9 = bank['make_class']('Year 9', 311)
    indices = bank['question'](y9)
    other_topic = Topic.objects.create(subject=bank['topic'].subject, name='Fractions',
                                       slug='fr-rq', parent=bank['number'])
    fractions = bank['question'](y9, topic=other_topic)

    relevel(topic='Indices', exact_topic=True)

    indices.refresh_from_db(); fractions.refresh_from_db()
    assert indices.level.level_number == 9
    assert fractions.level.level_number == 1


def test_soft_deleted_homework_still_counts_as_evidence(bank):
    """A deleted homework is still a fact about which class the question is for."""
    y9 = bank['make_class']('Year 9', 311)
    q = bank['question'](y9)
    Homework.all_objects.update(deleted_at=timezone.now())

    relevel()

    q.refresh_from_db()
    assert q.level.level_number == 9


def test_assigned_homework_still_serves_the_same_questions(bank):
    """Re-levelling must not disturb homework already out with students.

    An assigned homework loads its items purely by
    ``HomeworkQuestion.objects.filter(homework=...)``
    (``homework/views_student.py:323``) with no level filter, so moving a
    question between years cannot change what a student is served. That is the
    behaviour this pins — a level filter introduced there later would silently
    empty every homework whose questions this command moved.
    """
    y9 = bank['make_class']('Year 9', 311)
    questions = [bank['question'](y9) for _ in range(3)]
    homework = Homework.objects.filter(classroom=y9).first()
    # One homework per question above; re-point them all at a single homework
    # so we can assert the served set as a whole.
    HomeworkQuestion.objects.update(homework=homework)
    before = list(HomeworkQuestion.objects.filter(homework=homework)
                  .order_by('order', 'id')
                  .values_list('content_id', 'question_id', 'order'))
    assert len(before) == 3

    relevel()

    after = list(HomeworkQuestion.objects.filter(homework=homework)
                 .order_by('order', 'id')
                 .values_list('content_id', 'question_id', 'order'))
    assert after == before
    for q in questions:
        q.refresh_from_db()
        assert q.level.level_number == 9      # the level did move
    assert Question.objects.filter(id__in=[q.id for q in questions]).count() == 3
