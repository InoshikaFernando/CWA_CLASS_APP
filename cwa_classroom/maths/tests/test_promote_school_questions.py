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


@pytest.fixture
def wider_bank(setup):
    """A second year + topic, so the --year / --topic scoping has something to
    leave behind."""
    from classroom.models import Subject
    subject = Subject.objects.get(slug='mathematics')
    y4 = Level.objects.create(level_number=4, display_name='Year 4', school=None)
    number = Topic.objects.create(subject=subject, name='Number', slug='number')
    patterns = Topic.objects.create(subject=subject, name='Number Patterns',
                                    slug='number-patterns', parent=number)
    fractions = Topic.objects.create(subject=subject, name='Fractions',
                                     slug='fractions', parent=number)
    for topic, text in ((patterns, 'Complete: 14, 18, 22, __'),
                        (fractions, 'Add 1/2 + 1/4')):
        q = Question.objects.create(
            school=setup['school'], level=y4, topic=topic, question_text=text,
            question_type='short_answer', difficulty=1, points=1)
        Answer.objects.create(question=q, answer_text='x', is_correct=True)
    return setup


def test_promote_scoped_to_one_year_and_topic(wider_bank):
    """The whole point: fill the Y4 Number Patterns gap without publishing the
    school's entire private bank."""
    call_command('promote_school_questions', school=wider_bank['school'].id,
                 year=4, topic='Number Patterns')

    promoted = set(Question.objects.filter(school__isnull=True)
                   .values_list('question_text', flat=True))
    assert promoted == {'Complete: 14, 18, 22, __'}


def test_promote_accepts_a_school_slug(wider_bank):
    call_command('promote_school_questions', school_slug='promo-school',
                 year=4, topic='Number Patterns')
    assert Question.objects.filter(school__isnull=True).count() == 1


def test_promote_without_a_school_is_an_error(wider_bank):
    from django.core.management.base import CommandError
    with pytest.raises(CommandError, match='--school'):
        call_command('promote_school_questions', year=4)
