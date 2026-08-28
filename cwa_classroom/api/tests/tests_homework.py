"""Homework: visibility, attempt limits, and handing work in."""

import pytest
from django.utils import timezone
from datetime import timedelta

from classroom.models import ClassStudent
from homework.models import Homework, HomeworkQuestion, HomeworkSubmission

pytestmark = pytest.mark.django_db


@pytest.fixture
def published_homework(db, classroom):
    homework = Homework.objects.create(
        classroom=classroom, title='Fractions', num_questions=2,
        due_date=timezone.now() + timedelta(days=7),
        published_at=timezone.now(),
    )
    for order in range(2):
        HomeworkQuestion.objects.create(
            homework=homework, subject_slug='mathematics',
            content_id=order + 1, order=order)
    return homework


def test_student_sees_published_homework_for_their_class(
        api, auth, student, published_homework):
    auth(student)
    response = api.get('/api/v1/homework/')
    assert response.status_code == 200
    assert [row['id'] for row in response.data['results']] == [published_homework.id]


def test_student_does_not_see_scheduled_homework(api, auth, student, classroom):
    """Homework scheduled to go live later is invisible until it does.

    Note Homework.save() publishes immediately unless publish_at is set, so a
    genuine draft is one scheduled for the future.
    """
    Homework.objects.create(
        classroom=classroom, title='Scheduled', num_questions=1,
        due_date=timezone.now() + timedelta(days=7),
        publish_at=timezone.now() + timedelta(days=1))
    auth(student)
    assert api.get('/api/v1/homework/').data['results'] == []


def test_teacher_sees_homework_that_has_not_gone_live_yet(api, auth, teacher, classroom):
    Homework.objects.create(
        classroom=classroom, title='Scheduled', num_questions=1,
        due_date=timezone.now() + timedelta(days=7),
        publish_at=timezone.now() + timedelta(days=1))
    auth(teacher)
    assert len(api.get('/api/v1/homework/').data['results']) == 1


def test_a_student_in_another_class_sees_nothing(
        api, auth, other_student, published_homework):
    auth(other_student)
    assert api.get('/api/v1/homework/').data['results'] == []


def test_soft_deleted_homework_disappears(api, auth, student, published_homework):
    published_homework.deleted_at = timezone.now()
    published_homework.save(update_fields=['deleted_at'])
    auth(student)
    assert api.get('/api/v1/homework/').data['results'] == []


def test_a_moved_student_keeps_their_old_classes_homework(
        api, auth, student, classroom, published_homework):
    """Leaving a class while staying in the school keeps the homework — the web
    app's rule, which a plain is_active filter would silently break."""
    membership = ClassStudent.objects.get(classroom=classroom, student=student)
    membership.is_active = False
    membership.moved_at = timezone.now()
    membership.save(update_fields=['is_active', 'moved_at'])

    auth(student)
    assert [row['id'] for row in api.get('/api/v1/homework/').data['results']] \
        == [published_homework.id]


def test_a_student_removed_from_the_school_loses_access(
        api, auth, student, classroom, published_homework):
    membership = ClassStudent.objects.get(classroom=classroom, student=student)
    membership.is_active = False
    membership.moved_at = None
    membership.save(update_fields=['is_active', 'moved_at'])

    auth(student)
    assert api.get('/api/v1/homework/').data['results'] == []


def test_submitting_records_the_attempt_and_score(
        api, auth, student, published_homework):
    questions = list(published_homework.homework_questions.order_by('order'))
    auth(student)
    response = api.post(
        f'/api/v1/homework/{published_homework.id}/submit/',
        {'answers': [
            {'question_id': questions[0].id, 'answer': '1/2', 'is_correct': True},
            {'question_id': questions[1].id, 'answer': '3', 'is_correct': False},
        ], 'time_taken_seconds': 90},
        format='json')
    assert response.status_code == 201
    assert response.data['score'] == 1
    assert response.data['total_questions'] == 2
    assert response.data['attempt_number'] == 1


def test_attempt_limit_is_enforced(api, auth, student, published_homework):
    published_homework.max_attempts = 1
    published_homework.save(update_fields=['max_attempts'])
    questions = list(published_homework.homework_questions.order_by('order'))
    payload = {'answers': [
        {'question_id': questions[0].id, 'answer': 'x', 'is_correct': True}]}

    auth(student)
    first = api.post(f'/api/v1/homework/{published_homework.id}/submit/',
                     payload, format='json')
    assert first.status_code == 201

    second = api.post(f'/api/v1/homework/{published_homework.id}/submit/',
                      payload, format='json')
    assert second.status_code == 400
    assert HomeworkSubmission.objects.filter(homework=published_homework).count() == 1


def test_an_answer_for_another_homework_rejects_the_whole_attempt(
        api, auth, student, classroom, published_homework):
    """A partial attempt still burns a limited try, so it is refused outright."""
    other = Homework.objects.create(
        classroom=classroom, title='Other', num_questions=1,
        due_date=timezone.now() + timedelta(days=7), published_at=timezone.now())
    foreign = HomeworkQuestion.objects.create(
        homework=other, subject_slug='mathematics', content_id=99, order=0)
    mine = published_homework.homework_questions.first()

    auth(student)
    response = api.post(
        f'/api/v1/homework/{published_homework.id}/submit/',
        {'answers': [
            {'question_id': mine.id, 'answer': 'a', 'is_correct': True},
            {'question_id': foreign.id, 'answer': 'b', 'is_correct': True},
        ]}, format='json')
    assert response.status_code == 400
    assert HomeworkSubmission.objects.count() == 0


def test_a_student_cannot_submit_to_a_class_they_are_not_in(
        api, auth, other_student, published_homework):
    question = published_homework.homework_questions.first()
    auth(other_student)
    response = api.post(
        f'/api/v1/homework/{published_homework.id}/submit/',
        {'answers': [{'question_id': question.id, 'answer': 'a', 'is_correct': True}]},
        format='json')
    # They cannot even see the homework, so it is a 404 rather than a 403.
    assert response.status_code == 404


def test_questions_endpoint_does_not_leak_the_answer_key(
        api, auth, student, published_homework):
    auth(student)
    response = api.get(f'/api/v1/homework/{published_homework.id}/questions/')
    assert response.status_code == 200
    body = str(response.data)
    for leaked in ('is_correct', 'correct_answer', 'explanation'):
        assert leaked not in body


def test_submissions_are_scoped_to_visible_students(
        api, auth, student, other_student, teacher, published_homework):
    HomeworkSubmission.objects.create(
        homework=published_homework, student=student,
        attempt_number=1, score=1, total_questions=2)

    auth(other_student)
    assert api.get('/api/v1/submissions/').data['results'] == []

    api.credentials()
    auth(teacher)
    rows = api.get('/api/v1/submissions/').data['results']
    assert [row['student']['id'] for row in rows] == [student.id]
