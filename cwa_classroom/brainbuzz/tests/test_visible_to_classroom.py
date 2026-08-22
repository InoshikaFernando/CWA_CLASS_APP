"""Tests for ``visible_to_classroom`` — the class-scoped visibility filter.

``visible_to(user)`` answers "what may this PERSON see?". The homework
generators need "what may this CLASS draw on?", which is a different question:
a teacher with rights over several classes must not pull class B's private
questions into class A's homework.

The filter lives on the queryset shared by ``maths.Question`` and
``coding.CodingExercise``, so both are exercised here.
"""
import pytest

from accounts.models import CustomUser
from classroom.models import ClassRoom, Department, Level, School
from coding.models import CodingExercise, CodingLanguage, CodingTopic, TopicLevel
from maths.models import Question


@pytest.fixture
def scoped(db):
    """Two schools, two departments, two classes — and a question for each scope."""
    admin = CustomUser.objects.create_user('vtc_admin', 'vtc@a.com', 'pass1234')
    school_a = School.objects.create(name='School A', slug='school-a', admin=admin)
    school_b = School.objects.create(name='School B', slug='school-b', admin=admin)

    dept_a = Department.objects.create(
        school=school_a, name='Maths Dept', slug='maths-dept')
    dept_other = Department.objects.create(
        school=school_a, name='Science Dept', slug='science-dept')

    class_a = ClassRoom.objects.create(name='Class A', school=school_a, department=dept_a)
    class_other = ClassRoom.objects.create(
        name='Class Other', school=school_a, department=dept_a,
    )
    # A class with no department at all.
    class_no_dept = ClassRoom.objects.create(name='Class ND', school=school_a)

    level = Level.objects.create(level_number=901, display_name='Year 901', school=None)

    def q(text, **scope):
        return Question.objects.create(
            level=level, question_text=text, question_type='short_answer', **scope
        )

    return {
        'class_a': class_a,
        'class_other': class_other,
        'class_no_dept': class_no_dept,
        'school_a': school_a,
        'level': level,
        'q_global': q('global q'),
        'q_school_a': q('school A q', school=school_a),
        'q_school_b': q('school B q', school=school_b),
        'q_dept_a': q('dept A q', school=school_a, department=dept_a),
        'q_dept_other': q('other dept q', school=school_a, department=dept_other),
        'q_class_a': q('class A q', school=school_a, classroom=class_a),
        'q_class_other': q('other class q', school=school_a, classroom=class_other),
    }


def _texts(classroom):
    return set(
        Question.objects.visible_to_classroom(classroom)
        .values_list('question_text', flat=True)
    )


def test_class_sees_global_school_department_and_own_class(scoped):
    assert _texts(scoped['class_a']) == {
        'global q', 'school A q', 'dept A q', 'class A q',
    }


def test_other_schools_questions_are_never_visible(scoped):
    # The leak this filter exists to close: an unscoped pool handed one
    # school's private questions to every other school's homework.
    for classroom in ('class_a', 'class_other', 'class_no_dept'):
        assert 'school B q' not in _texts(scoped[classroom])


def test_sibling_class_and_sibling_department_are_excluded(scoped):
    visible = _texts(scoped['class_a'])
    assert 'other class q' not in visible      # class-scoped to a sibling class
    assert 'other dept q' not in visible       # department-scoped to a sibling dept


def test_class_with_no_department_sees_no_department_scoped_rows(scoped):
    visible = _texts(scoped['class_no_dept'])
    assert visible == {'global q', 'school A q'}
    assert 'dept A q' not in visible


def test_no_classroom_means_global_only(scoped):
    # Mirrors _get_questions_for_level's answer for an individual student.
    assert _texts(None) == {'global q'}


def test_classroom_without_a_school_means_global_only(scoped):
    schoolless = ClassRoom.objects.create(name='Schoolless')
    assert _texts(schoolless) == {'global q'}


# ── the same filter, on the coding side of the shared queryset ──────────────

def test_coding_exercises_are_scoped_by_the_same_rules(scoped, db):
    lang = CodingLanguage.objects.create(name='Python', slug='python-vtc')
    topic = CodingTopic.objects.create(language=lang, name='Basics', slug='basics-vtc')
    tl = TopicLevel.objects.create(topic=topic, level_choice=TopicLevel.BEGINNER)

    def ex(title, **scope):
        return CodingExercise.objects.create(
            topic_level=tl, title=title, description='d', is_active=True, **scope,
        )

    ex('global ex')
    ex('school A ex', school=scoped['school_a'])
    ex('school B ex', school=School.objects.get(slug='school-b'))

    visible = set(
        CodingExercise.objects.visible_to_classroom(scoped['class_a'])
        .values_list('title', flat=True)
    )
    assert visible == {'global ex', 'school A ex'}
