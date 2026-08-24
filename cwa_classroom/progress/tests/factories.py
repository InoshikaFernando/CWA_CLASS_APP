"""Shared fixtures for the period-report tests (CPP-388).

The report builder reads across four apps, so a test that sets up one homework
by hand ends up 40 lines long before it asserts anything. These helpers make
the *interesting* part of each test — the submission pattern — the part that is
visible.
"""

from datetime import timedelta

from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Department, Level, ParentStudent,
    School, SchoolTeacher, Subject, Topic,
)
from homework.models import (
    Homework, HomeworkStudentAnswer, HomeworkSubmission,
)
from maths.models import Question


def role(name, display=None):
    obj, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': display or name.title()},
    )
    return obj


def make_user(username, role_name='student', **kwargs):
    user = CustomUser.objects.create_user(
        username, f'{username}@example.test', 'pass1234', **kwargs,
    )
    user.roles.add(role(role_name))
    return user


def make_school(admin=None, name='Test School', slug='test-school'):
    # The admin username is derived from the slug so a test that needs a second
    # school does not collide on CustomUser.email, which is unique.
    return School.objects.create(
        name=name, slug=slug,
        admin=admin or make_user(f'admin-{slug}', 'admin'),
    )


def make_classroom(school, name='Year 5 Maths', code='RPT00001'):
    return ClassRoom.objects.create(name=name, code=code, school=school)


def enrol(classroom, student, joined_days_ago=90):
    link = ClassStudent.objects.create(
        classroom=classroom, student=student, is_active=True,
    )
    # ``joined_at`` is auto_now_add, which lands after any back-dated due date
    # and would make every student look like a late joiner.
    ClassStudent.objects.filter(pk=link.pk).update(
        joined_at=timezone.now() - timedelta(days=joined_days_ago),
    )
    link.refresh_from_db()
    return link


def add_teacher(classroom, teacher):
    ClassTeacher.objects.create(classroom=classroom, teacher=teacher)
    if classroom.school_id:
        SchoolTeacher.objects.get_or_create(
            school=classroom.school, teacher=teacher, defaults={'role': 'teacher'},
        )


def link_parent(parent, student, school=None):
    return ParentStudent.objects.create(
        parent=parent, student=student, school=school, is_active=True,
    )


def make_topic(name='Fractions'):
    subject, _ = Subject.objects.get_or_create(
        slug='mathematics', school=None, defaults={'name': 'Mathematics'},
    )
    return Topic.objects.create(
        name=name, slug=name.lower().replace(' ', '-'),
        subject=subject, is_active=True,
    )


def make_question(topic=None, level=None, text='2 + 2 = ?'):
    if level is None:
        level, _ = Level.objects.get_or_create(
            level_number=5, defaults={'display_name': 'Level 5'},
        )
    return Question.objects.create(
        question_text=text, level=level, topic=topic,
    )


def make_homework(classroom, due, title='Fractions 1', published=True):
    homework = Homework.objects.create(
        classroom=classroom, title=title, due_date=due, num_questions=10,
    )
    if not published:
        Homework.objects.filter(pk=homework.pk).update(published_at=None)
        homework.refresh_from_db()
    return homework


def submit(homework, student, attempt, score, total=10, when=None, seconds=300):
    """One attempt. ``submitted_at`` is auto_now_add, so it is set afterwards."""
    submission = HomeworkSubmission.objects.create(
        homework=homework, student=student, attempt_number=attempt,
        score=score, total_questions=total, points=score,
        time_taken_seconds=seconds,
    )
    if when is not None:
        HomeworkSubmission.objects.filter(pk=submission.pk).update(submitted_at=when)
        submission.refresh_from_db()
    return submission


def answer(submission, question, correct):
    return HomeworkStudentAnswer.objects.create(
        submission=submission, question=question,
        is_correct=correct, points_earned=1.0 if correct else 0.0,
    )


def make_department(school, name='Mathematics', slug='maths'):
    return Department.objects.create(school=school, name=name, slug=slug)


def enable_reports(school, scope=None, kind='school', **flags):
    """Switch report flags on at one level of the cascade.

    ``kind`` is 'school', 'department' or 'class'; unspecified flags stay
    ``None`` (inherit), which is what makes the cascade tests meaningful.
    """
    from progress import report_settings

    fields = (
        report_settings.PERIOD_FIELDS + report_settings.DELIVERY_FIELDS
    )
    values = {field: flags.get(field) for field in fields}
    return report_settings.set_for(
        scope if scope is not None else school, kind, school, values,
    )
