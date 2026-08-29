"""Negative-case coverage for the scoped endpoints the first pass missed.

Every endpoint here narrows its queryset through ``api.scoping`` or filters by
the caller. The rule is shared, so the risk is not a broken rule but a viewset
that forgot to apply it — and that mistake is silent: the endpoint returns 200
with somebody else's rows and no test notices. So each test asserts the
NEGATIVE: a caller who should see nothing gets nothing.

404 rather than 403 throughout, deliberately. A 403 confirms the row exists,
which is itself a leak about another family's child.
"""

import pytest
from datetime import timedelta
from django.utils import timezone

from accounts.models import Role
from classroom.models import ClassSession, Notification, ParentStudent

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(db, classroom):
    return ClassSession.objects.create(
        classroom=classroom, date='2026-03-02',
        start_time='09:00', end_time='10:00')


# --- Class sessions / timetable -------------------------------------------

def test_sessions_list_is_scoped_to_the_callers_classes(
        api, auth, session, student, other_student):
    auth(student)
    assert [row['id'] for row in api.get('/api/v1/sessions/').data['results']] \
        == [session.id]

    api.credentials()
    auth(other_student)
    assert api.get('/api/v1/sessions/').data['results'] == []


def test_a_stranger_cannot_fetch_a_session_by_id(api, auth, session, other_student):
    auth(other_student)
    assert api.get(f'/api/v1/sessions/{session.id}/').status_code == 404


def test_teacher_sees_the_sessions_of_the_class_they_teach(
        api, auth, session, teacher):
    auth(teacher)
    assert api.get(f'/api/v1/sessions/{session.id}/').status_code == 200


def test_nested_class_sessions_are_scoped(api, auth, classroom, session,
                                          student, other_student):
    auth(student)
    listed = api.get(f'/api/v1/classes/{classroom.id}/sessions/')
    assert listed.status_code == 200
    assert [row['id'] for row in listed.data['results']] == [session.id]

    api.credentials()
    auth(other_student)
    # They cannot see the class at all, so the nested route 404s with it.
    assert api.get(f'/api/v1/classes/{classroom.id}/sessions/').status_code == 404


# --- Coding submissions ----------------------------------------------------

@pytest.fixture
def coding_submission(db, student):
    from coding.models import (
        CodingExercise, CodingLanguage, CodingTopic, StudentExerciseSubmission,
        TopicLevel,
    )

    language = CodingLanguage.objects.create(name='Python', slug='python')
    topic = CodingTopic.objects.create(language=language, name='Loops', slug='loops')
    level = TopicLevel.objects.create(topic=topic, level_choice='beginner')
    exercise = CodingExercise.objects.create(
        topic_level=level, title='Count', description='d',
        solution_code='secret', order=0)
    return StudentExerciseSubmission.objects.create(
        student=student, exercise=exercise, code_submitted='print(1)')


def test_coding_submissions_are_scoped(api, auth, coding_submission,
                                       student, other_student):
    auth(student)
    assert len(api.get('/api/v1/coding/submissions/').data['results']) == 1

    api.credentials()
    auth(other_student)
    assert api.get('/api/v1/coding/submissions/').data['results'] == []


def test_a_students_code_is_not_readable_by_another_student(
        api, auth, coding_submission, other_student):
    """The submitted source is the student's own work, not shared."""
    auth(other_student)
    response = api.get(f'/api/v1/coding/submissions/{coding_submission.id}/')
    assert response.status_code == 404
    assert 'print(1)' not in str(response.data)


def test_teacher_can_read_their_students_coding_submission(
        api, auth, classroom, coding_submission, teacher):
    """The `classroom` fixture is what links this teacher to this student —
    without an enrolment there is no relationship and 404 is correct."""
    auth(teacher)
    assert api.get(
        f'/api/v1/coding/submissions/{coding_submission.id}/').status_code == 200


# --- Notifications ---------------------------------------------------------

def test_cannot_retrieve_another_users_notification(api, auth, student,
                                                    other_student):
    theirs = Notification.objects.create(user=other_student, message='Private')
    auth(student)
    response = api.get(f'/api/v1/notifications/{theirs.id}/')
    assert response.status_code == 404
    assert 'Private' not in str(response.data)


def test_read_all_only_touches_the_callers_own(api, auth, student, other_student):
    mine = Notification.objects.create(user=student, message='Mine', is_read=False)
    theirs = Notification.objects.create(user=other_student, message='Theirs',
                                         is_read=False)
    auth(student)
    response = api.post('/api/v1/notifications/read-all/')
    assert response.status_code == 200
    assert response.data['marked_read'] == 1

    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.is_read is True
    assert theirs.is_read is False, "read-all reached another user's rows"


# --- Puzzle progress -------------------------------------------------------

def test_puzzle_progress_is_scoped(api, auth, student, other_student):
    from number_puzzles.models import NumberPuzzleLevel, StudentPuzzleProgress

    level = NumberPuzzleLevel.objects.create(
        number=1, name='One', slug='one', operators_allowed='+-')
    StudentPuzzleProgress.objects.create(student=student, level=level,
                                         best_score=9)

    auth(student)
    rows = api.get('/api/v1/puzzles/progress/').data['results']
    assert [row['best_score'] for row in rows] == [9]

    api.credentials()
    auth(other_student)
    assert api.get('/api/v1/puzzles/progress/').data['results'] == []


# --- Homework submissions and their graded answers -------------------------

@pytest.fixture
def submission_with_answers(db, classroom, student):
    from homework.models import (
        Homework, HomeworkQuestion, HomeworkStudentAnswer, HomeworkSubmission,
    )

    homework = Homework.objects.create(
        classroom=classroom, title='Fractions', num_questions=1,
        due_date=timezone.now() + timedelta(days=7), published_at=timezone.now())
    HomeworkQuestion.objects.create(
        homework=homework, subject_slug='mathematics', content_id=1, order=0)
    submission = HomeworkSubmission.objects.create(
        homework=homework, student=student, attempt_number=1,
        score=1, total_questions=1)
    HomeworkStudentAnswer.objects.create(
        submission=submission, subject_slug='mathematics', content_id=1,
        text_answer='one half', is_correct=True,
        teacher_feedback='Careful with the denominator')
    return submission


def test_cannot_retrieve_another_students_submission(
        api, auth, submission_with_answers, other_student):
    auth(other_student)
    assert api.get(
        f'/api/v1/submissions/{submission_with_answers.id}/').status_code == 404


def test_cannot_read_another_students_graded_answers(
        api, auth, submission_with_answers, other_student):
    """The answer rows carry the student's work and their teacher's feedback."""
    auth(other_student)
    response = api.get(
        f'/api/v1/submissions/{submission_with_answers.id}/answers/')
    assert response.status_code == 404
    body = str(response.data)
    assert 'one half' not in body
    assert 'denominator' not in body


def test_a_parent_can_read_their_own_childs_answers(
        api, auth, submission_with_answers, student, parent):
    ParentStudent.objects.create(parent=parent, student=student, is_active=True)
    auth(parent)
    response = api.get(
        f'/api/v1/submissions/{submission_with_answers.id}/answers/')
    assert response.status_code == 200
    assert response.data[0]['text_answer'] == 'one half'


# --- Worksheet assignments -------------------------------------------------

@pytest.fixture
def worksheet_assignment(db, school, classroom, teacher):
    from worksheets.models import Worksheet, WorksheetAssignment

    worksheet = Worksheet.objects.create(
        school=school, name='Fractions sheet', original_filename='f.pdf',
        created_by=teacher, question_count=10)
    return WorksheetAssignment.objects.create(
        worksheet=worksheet, classroom=classroom, assigned_by=teacher,
        question_start=1, question_end=10, is_active=True)


def test_worksheet_assignments_are_scoped_to_visible_classes(
        api, auth, worksheet_assignment, student, other_student):
    auth(student)
    assert len(api.get('/api/v1/worksheet-assignments/').data['results']) == 1

    api.credentials()
    auth(other_student)
    assert api.get('/api/v1/worksheet-assignments/').data['results'] == []


def test_cannot_fetch_a_worksheet_assignment_for_another_class(
        api, auth, worksheet_assignment, other_student):
    auth(other_student)
    assert api.get(
        f'/api/v1/worksheet-assignments/{worksheet_assignment.id}/'
    ).status_code == 404
