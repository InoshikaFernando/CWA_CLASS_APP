"""The maths homework generator must not draw on other schools' questions.

``MathsPlugin.pick_homework_items`` and ``_topics_with_questions`` build a
homework for a *classroom*. Both used a bare ``Question.objects.filter(...)``,
and ``Question.objects`` is not scoped by default — ``visible_to()`` is opt-in
— so the pool was every school's questions plus global.
"""
import pytest

from accounts.models import CustomUser
from classroom.models import ClassRoom, Level, School, Subject, Topic
from maths.models import Question
from maths.plugin import MathsPlugin


@pytest.fixture
def two_schools(db):
    admin = CustomUser.objects.create_user('hwscope_admin', 'hw@a.com', 'pass1234')
    school_a = School.objects.create(name='HW School A', slug='hw-school-a', admin=admin)
    school_b = School.objects.create(name='HW School B', slug='hw-school-b', admin=admin)

    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    topic = Topic.objects.create(subject=subject, name='Fractions', slug='fractions-hw')
    level = Level.objects.create(level_number=902, display_name='Year 902', school=None)
    topic.levels.add(level)

    classroom = ClassRoom.objects.create(name='A1', school=school_a)
    classroom.levels.add(level)

    def q(text, **scope):
        return Question.objects.create(
            level=level, topic=topic, question_text=text,
            question_type='short_answer', **scope
        )

    return {
        'classroom': classroom,
        'topic': topic,
        'q_global': q('global fraction q'),
        'q_mine': q('school A fraction q', school=school_a),
        'q_theirs': q('school B fraction q', school=school_b),
    }


def test_pick_homework_items_excludes_other_schools_questions(two_schools):
    picks = MathsPlugin().pick_homework_items(
        two_schools['classroom'], [two_schools['topic'].pk], n=50,
    )

    assert two_schools['q_theirs'].pk not in picks, \
        "another school's private question leaked into this class's homework"
    assert two_schools['q_global'].pk in picks
    assert two_schools['q_mine'].pk in picks


def test_topic_picker_hides_topics_only_other_schools_have(db):
    """A topic whose only questions belong to another school must not be offered."""
    admin = CustomUser.objects.create_user('hwscope2', 'hw2@a.com', 'pass1234')
    mine = School.objects.create(name='Mine', slug='mine-hw', admin=admin)
    theirs = School.objects.create(name='Theirs', slug='theirs-hw', admin=admin)

    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    level = Level.objects.create(level_number=903, display_name='Year 903', school=None)
    their_topic = Topic.objects.create(
        subject=subject, name='Their Topic', slug='their-topic-hw')
    my_topic = Topic.objects.create(subject=subject, name='My Topic', slug='my-topic-hw')

    classroom = ClassRoom.objects.create(name='B1', school=mine)
    classroom.levels.add(level)

    Question.objects.create(
        level=level, topic=their_topic, question_text='theirs',
        question_type='short_answer', school=theirs,
    )
    Question.objects.create(
        level=level, topic=my_topic, question_text='mine',
        question_type='short_answer', school=mine,
    )

    offered = {t.pk for t in MathsPlugin._topics_with_questions(classroom)}
    assert their_topic.pk not in offered
    assert my_topic.pk in offered
