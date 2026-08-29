"""Row-level scoping.

These are the tests that matter most in the whole API: every one of them is a
way for one family's data to reach another family's phone. They assert the
negative case — that a caller who should see nothing gets nothing — because
the positive case fails loudly in manual testing and the negative case does
not fail at all.
"""

import pytest

from classroom.models import ClassStudent, Notification, ParentStudent

pytestmark = pytest.mark.django_db


def test_student_sees_only_their_own_classes(api, auth, classroom, student,
                                             other_student):
    auth(student)
    response = api.get('/api/v1/classes/')
    assert response.status_code == 200
    assert [row['id'] for row in response.data['results']] == [classroom.id]

    api.credentials()
    auth(other_student)
    response = api.get('/api/v1/classes/')
    assert response.data['results'] == []


def test_teacher_sees_the_class_they_teach(api, auth, classroom, teacher):
    auth(teacher)
    response = api.get('/api/v1/classes/')
    assert [row['id'] for row in response.data['results']] == [classroom.id]


def test_parent_sees_their_childs_class_but_not_the_roster(
        api, auth, classroom, student, parent):
    ParentStudent.objects.create(parent=parent, student=student, is_active=True)
    auth(parent)

    listed = api.get('/api/v1/classes/')
    assert [row['id'] for row in listed.data['results']] == [classroom.id]

    # Seeing that a class exists is not the same as seeing the other children
    # in it. The roster is staff-only.
    roster = api.get(f'/api/v1/classes/{classroom.id}/students/')
    assert roster.status_code == 403


def test_teacher_can_read_the_roster(api, auth, classroom, teacher, student):
    auth(teacher)
    response = api.get(f'/api/v1/classes/{classroom.id}/students/')
    assert response.status_code == 200
    assert [row['student']['id'] for row in response.data['results']] == [student.id]


def test_unlinked_parent_sees_nothing(api, auth, classroom, parent):
    """A parent with no ParentStudent link is not a parent of anyone here."""
    auth(parent)
    assert api.get('/api/v1/classes/').data['results'] == []
    assert api.get('/api/v1/children/').data['results'] == []


def test_an_inactive_parent_link_does_not_grant_access(
        api, auth, classroom, student, parent):
    ParentStudent.objects.create(parent=parent, student=student, is_active=False)
    auth(parent)
    assert api.get('/api/v1/classes/').data['results'] == []


def test_a_student_cannot_fetch_another_students_class_by_id(
        api, auth, classroom, other_student):
    """Guessing an id must 404, not 403 — a 403 confirms the class exists."""
    auth(other_student)
    assert api.get(f'/api/v1/classes/{classroom.id}/').status_code == 404


def test_notifications_are_private_to_their_owner(api, auth, student, other_student):
    Notification.objects.create(user=student, message='For student one')
    Notification.objects.create(user=other_student, message='For student two')

    auth(student)
    response = api.get('/api/v1/notifications/')
    assert [row['message'] for row in response.data['results']] == ['For student one']


def test_cannot_mark_someone_elses_notification_read(api, auth, student, other_student):
    theirs = Notification.objects.create(user=other_student, message='Private')
    auth(student)
    assert api.post(f'/api/v1/notifications/{theirs.id}/read/').status_code == 404
    theirs.refresh_from_db()
    assert theirs.is_read is False


def test_unread_count_only_counts_the_callers_own(api, auth, student, other_student):
    Notification.objects.create(user=student, message='Mine', is_read=False)
    Notification.objects.create(user=other_student, message='Theirs', is_read=False)
    auth(student)
    assert api.get('/api/v1/notifications/unread-count/').data['unread'] == 1


def test_parent_lists_only_their_own_children(api, auth, parent, student, other_student):
    ParentStudent.objects.create(parent=parent, student=student, is_active=True)
    auth(parent)
    response = api.get('/api/v1/children/')
    assert [row['student']['id'] for row in response.data['results']] == [student.id]


def test_attendance_is_scoped_to_visible_students(
        api, auth, classroom, teacher, student, other_student):
    from classroom.models import ClassSession, StudentAttendance

    session = ClassSession.objects.create(
        classroom=classroom, date='2026-03-02',
        start_time='09:00', end_time='10:00')
    StudentAttendance.objects.create(session=session, student=student, status='present')

    auth(other_student)
    assert api.get('/api/v1/attendance/').data['results'] == []

    api.credentials()
    auth(teacher)
    rows = api.get('/api/v1/attendance/').data['results']
    assert [row['student']['id'] for row in rows] == [student.id]


def test_teacher_marks_attendance_for_their_own_class(
        api, auth, classroom, teacher, student):
    from classroom.models import ClassSession

    session = ClassSession.objects.create(
        classroom=classroom, date='2026-03-02',
        start_time='09:00', end_time='10:00')

    auth(teacher)
    response = api.post(
        f'/api/v1/sessions/{session.id}/attendance/',
        [{'student_id': student.id, 'status': 'present'}], format='json')
    assert response.status_code == 200
    assert response.data[0]['status'] == 'present'


def test_marking_a_non_enrolled_student_rejects_the_whole_batch(
        api, auth, classroom, teacher, student, other_student):
    """A partly-applied roster is indistinguishable from a successful one on
    the client, so an unknown student fails the batch instead."""
    from classroom.models import ClassSession, StudentAttendance

    session = ClassSession.objects.create(
        classroom=classroom, date='2026-03-02',
        start_time='09:00', end_time='10:00')

    auth(teacher)
    response = api.post(
        f'/api/v1/sessions/{session.id}/attendance/',
        [{'student_id': student.id, 'status': 'present'},
         {'student_id': other_student.id, 'status': 'present'}],
        format='json')
    assert response.status_code == 400
    assert StudentAttendance.objects.count() == 0


def test_a_student_cannot_mark_attendance(api, auth, classroom, student):
    from classroom.models import ClassSession

    session = ClassSession.objects.create(
        classroom=classroom, date='2026-03-02',
        start_time='09:00', end_time='10:00')
    auth(student)
    response = api.post(f'/api/v1/sessions/{session.id}/attendance/',
                        [{'student_id': student.id, 'status': 'present'}],
                        format='json')
    assert response.status_code == 403


def test_page_size_cannot_be_used_to_dump_the_table(api, auth, classroom, student):
    """An uncapped page_size is a free denial-of-service."""
    auth(student)
    response = api.get('/api/v1/classes/?page_size=100000')
    assert response.status_code == 200
    assert response.data['page_size'] <= 100
