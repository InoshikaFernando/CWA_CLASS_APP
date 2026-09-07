"""Regressions for the defects found reviewing PR #831.

Each of these passed review only because someone read the write path next to
the web view that owns the same rule. They are pinned here so the next change
has to break a test rather than a school's data.
"""

import pytest
from datetime import timedelta
from django.utils import timezone

from accounts.models import Role
from classroom.models import ClassSession, ClassStudent, StudentAttendance
from homework.models import Homework, HomeworkQuestion, HomeworkSubmission

pytestmark = pytest.mark.django_db


@pytest.fixture
def maths_homework(db, classroom):
    """Homework holding one real multiple-choice maths question."""
    from classroom.models import Level, Subject, Topic
    from maths.models import Answer, Question

    subject, _ = Subject.objects.get_or_create(name='Mathematics', slug='mathematics')
    level, _ = Level.objects.get_or_create(
        level_number=1, defaults={'display_name': 'Year 1'})
    topic = Topic.objects.create(subject=subject, name='Addition', slug='addition')
    question = Question.objects.create(
        topic=topic, level=level, question_text='2 + 2 = ?',
        question_type=Question.MULTIPLE_CHOICE)
    right = Answer.objects.create(question=question, answer_text='4', is_correct=True)
    Answer.objects.create(question=question, answer_text='5', is_correct=False)

    homework = Homework.objects.create(
        classroom=classroom, title='Adding up', num_questions=1,
        due_date=timezone.now() + timedelta(days=7), published_at=timezone.now(),
        subject_slug='mathematics')
    hwq = HomeworkQuestion.objects.create(
        homework=homework, subject_slug='mathematics',
        content_id=question.id, question=question, order=0)
    return homework, hwq, right


def test_a_wrong_answer_cannot_be_submitted_as_correct(api, auth, student,
                                                       maths_homework):
    """The client used to send is_correct and the server believed it, so any
    student could POST a perfect score. Marking is the server's job."""
    homework, hwq, right_answer = maths_homework
    auth(student)

    response = api.post(f'/api/v1/homework/{homework.id}/submit/', {
        'answers': [{'question_id': hwq.id, 'answer': '999'}],  # not the right id
    }, format='json')

    assert response.status_code == 201, response.data
    assert response.data['score'] == 0


def test_a_right_answer_is_marked_right_by_the_server(api, auth, student,
                                                      maths_homework):
    homework, hwq, right_answer = maths_homework
    auth(student)
    response = api.post(f'/api/v1/homework/{homework.id}/submit/', {
        'answers': [{'question_id': hwq.id, 'answer': str(right_answer.id)}],
    }, format='json')
    assert response.status_code == 201, response.data
    assert response.data['score'] == 1


def test_the_payload_cannot_smuggle_is_correct(api, auth, student, maths_homework):
    """An extra is_correct key must be ignored, not honoured."""
    homework, hwq, _ = maths_homework
    auth(student)
    response = api.post(f'/api/v1/homework/{homework.id}/submit/', {
        'answers': [{'question_id': hwq.id, 'answer': '999', 'is_correct': True}],
    }, format='json')
    assert response.status_code == 201
    assert response.data['score'] == 0


def test_a_submission_awards_leaderboard_points(api, auth, student, maths_homework):
    """An attempt made in the app has to count for the same as one made in the
    browser — otherwise the leaderboard quietly ignores app users."""
    from rewards.models import PointsAward

    homework, hwq, right_answer = maths_homework
    auth(student)
    api.post(f'/api/v1/homework/{homework.id}/submit/', {
        'answers': [{'question_id': hwq.id, 'answer': str(right_answer.id)}],
    }, format='json')

    assert PointsAward.objects.filter(student=student, source='homework').exists()
    assert HomeworkSubmission.objects.get().points > 0


def test_attempt_numbers_survive_a_pruned_attempt(api, auth, student, maths_homework):
    """attempt_number used to be count()+1, which collides with the unique
    constraint as soon as an old attempt has been pruned or deleted."""
    homework, hwq, right_answer = maths_homework
    homework.max_attempts = None
    homework.save(update_fields=['max_attempts'])

    HomeworkSubmission.objects.create(
        homework=homework, student=student, attempt_number=1,
        score=0, total_questions=1)
    HomeworkSubmission.objects.create(
        homework=homework, student=student, attempt_number=2,
        score=0, total_questions=1)
    # Simulate the pruning the web path performs after each submit.
    HomeworkSubmission.objects.filter(homework=homework, student=student,
                                      attempt_number=1).delete()

    auth(student)
    response = api.post(f'/api/v1/homework/{homework.id}/submit/', {
        'answers': [{'question_id': hwq.id, 'answer': str(right_answer.id)}],
    }, format='json')
    assert response.status_code == 201, response.data
    assert response.data['attempt_number'] == 3


def test_two_answers_for_one_question_is_a_400(api, auth, student, maths_homework):
    homework, hwq, right_answer = maths_homework
    auth(student)
    response = api.post(f'/api/v1/homework/{homework.id}/submit/', {
        'answers': [
            {'question_id': hwq.id, 'answer': str(right_answer.id)},
            {'question_id': hwq.id, 'answer': '999'},
        ],
    }, format='json')
    assert response.status_code == 400
    assert HomeworkSubmission.objects.count() == 0


def test_a_teachers_mark_clears_the_self_report_state(api, auth, classroom,
                                                      teacher, student):
    """A teacher's mark is authoritative. Left flagged as self-reported, the
    student can overwrite it again from the web."""
    session = ClassSession.objects.create(
        classroom=classroom, date='2026-03-02',
        start_time='09:00', end_time='10:00')
    StudentAttendance.objects.create(
        session=session, student=student, status='present',
        self_reported=True, approved_at=timezone.now(), approved_by=student)

    auth(teacher)
    response = api.post(f'/api/v1/sessions/{session.id}/attendance/',
                        [{'student_id': student.id, 'status': 'absent'}],
                        format='json')
    assert response.status_code == 200

    record = StudentAttendance.objects.get(session=session, student=student)
    assert record.status == 'absent'
    assert record.self_reported is False
    assert record.approved_by is None
    assert record.approved_at is None


def test_student_count_is_the_whole_roster_not_just_the_caller(
        api, auth, classroom, student, make_user):
    """classrooms_for() filters on class_students for a student, and Django
    reuses that join for a following annotate — so the count came back as 1
    for a class of many."""
    for index in range(4):
        classmate = make_user(f'classmate{index}', role=Role.STUDENT)
        ClassStudent.objects.create(classroom=classroom, student=classmate,
                                    is_active=True)

    auth(student)
    row = api.get('/api/v1/classes/').data['results'][0]
    assert row['student_count'] == 5


def test_a_non_numeric_id_filter_is_a_400_not_a_500(api, auth, student):
    auth(student)
    response = api.get('/api/v1/submissions/?student=abc')
    assert response.status_code == 400
    assert response.data['error']['code'] == 'validation_error'


def test_a_blocked_account_can_still_log_out(api, auth, student):
    """Otherwise the wall keeps the refresh token alive for thirty days."""
    tokens = auth(student)
    student.is_blocked = True
    student.block_type = 'permanent'
    student.save(update_fields=['is_blocked', 'block_type'])

    assert api.get('/api/v1/classes/').status_code == 403
    assert api.post('/api/v1/auth/logout/', {'refresh': tokens['refresh']},
                    format='json').status_code == 205


def test_a_wall_names_the_page_that_clears_it(api, auth, student):
    """A walled client that is not told where to go is a dead end wearing an
    error code."""
    auth(student)
    student.profile_completed = False
    student.save(update_fields=['profile_completed'])

    body = api.get('/api/v1/classes/').json()['error']
    assert body['code'] == 'profile_incomplete'
    assert body['resolve_path'] == '/accounts/complete-profile/'


def test_changing_a_password_revokes_existing_tokens(api, auth, student):
    """Changing a password is what someone does after losing a device."""
    tokens = auth(student)
    response = api.post('/api/v1/auth/change-password/',
                        {'current_password': 'pw-for-tests-123',
                         'new_password': 'a-much-better-pw-42'}, format='json')
    assert response.status_code == 200

    replay = api.post('/api/v1/auth/refresh/', {'refresh': tokens['refresh']},
                      format='json')
    assert replay.status_code == 401


def test_the_schema_endpoints_require_a_login(api):
    """They publish every path, field and enum, including staff-only ones."""
    assert api.get('/api/schema/').status_code in (401, 403)
    assert api.get('/api/docs/').status_code in (401, 403)
