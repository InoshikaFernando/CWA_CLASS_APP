"""The coding homework generator must not draw on other schools' exercises.

Same gap as the maths plugin: ``CodingExercise.objects`` is unscoped by
default, so ``pick_homework_items`` and ``homework_topic_tree`` offered every
school's private exercises to every class.
"""
import pytest

from accounts.models import CustomUser
from classroom.models import ClassRoom, School
from coding.models import CodingExercise, CodingLanguage, CodingTopic, TopicLevel
from coding.plugin import CodingExercisePlugin


@pytest.fixture
def two_schools(db):
    admin = CustomUser.objects.create_user('cd_admin', 'cd@a.com', 'pass1234')
    mine = School.objects.create(name='CD Mine', slug='cd-mine', admin=admin)
    theirs = School.objects.create(name='CD Theirs', slug='cd-theirs', admin=admin)

    lang = CodingLanguage.objects.create(name='Python', slug='python-cdscope')
    topic = CodingTopic.objects.create(language=lang, name='Loops', slug='loops-cdscope')
    tl = TopicLevel.objects.create(topic=topic, level_choice=TopicLevel.BEGINNER)

    def ex(title, **scope):
        return CodingExercise.objects.create(
            topic_level=tl, title=title, description='d', is_active=True, **scope,
        )

    return {
        'classroom': ClassRoom.objects.create(name='C1', school=mine),
        'topic_level': tl,
        'ex_global': ex('global ex'),
        'ex_mine': ex('my school ex', school=mine),
        'ex_theirs': ex('their school ex', school=theirs),
    }


def test_pick_homework_items_excludes_other_schools_exercises(two_schools):
    picks = CodingExercisePlugin().pick_homework_items(
        two_schools['classroom'], [two_schools['topic_level'].pk], n=50,
    )

    assert two_schools['ex_theirs'].pk not in picks, \
        "another school's private exercise leaked into this class's homework"
    assert two_schools['ex_global'].pk in picks
    assert two_schools['ex_mine'].pk in picks


def test_topic_tree_hides_levels_only_other_schools_populate(db):
    admin = CustomUser.objects.create_user('cd_admin2', 'cd2@a.com', 'pass1234')
    mine = School.objects.create(name='CD Mine 2', slug='cd-mine-2', admin=admin)
    theirs = School.objects.create(name='CD Theirs 2', slug='cd-theirs-2', admin=admin)

    lang = CodingLanguage.objects.create(name='Ruby', slug='ruby-cdscope')
    topic = CodingTopic.objects.create(language=lang, name='Blocks', slug='blocks-cdscope')
    tl = TopicLevel.objects.create(topic=topic, level_choice=TopicLevel.BEGINNER)
    CodingExercise.objects.create(
        topic_level=tl, title='theirs only', description='d',
        is_active=True, school=theirs,
    )

    classroom = ClassRoom.objects.create(name='C2', school=mine)
    tree = CodingExercisePlugin().homework_topic_tree(classroom)

    offered_levels = {
        leaf.pk for _, mids in tree for _, leaves in mids for leaf in leaves
    }
    assert tl.pk not in offered_levels, \
        'a level populated only by another school was offered in the picker'
