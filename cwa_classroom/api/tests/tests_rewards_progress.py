"""Points, leaderboard and progress reports."""

import pytest

from progress.models import PeriodReport
from rewards.models import PointsAward, StudentPointsTotal

pytestmark = pytest.mark.django_db


def test_points_total_defaults_to_zero_for_a_new_student(api, auth, student):
    """No points yet is a zero, not a 404 — the app must render a real screen."""
    auth(student)
    response = api.get('/api/v1/points/total/')
    assert response.status_code == 200
    assert response.data['total_points'] == 0.0


def test_points_total_reports_the_running_total(api, auth, student):
    StudentPointsTotal.objects.create(student=student, total_points=42.0,
                                      units_completed=7)
    auth(student)
    assert api.get('/api/v1/points/total/').data['total_points'] == 42.0


def test_a_student_cannot_read_another_students_total(api, auth, student, other_student):
    StudentPointsTotal.objects.create(student=other_student, total_points=99.0)
    auth(student)
    response = api.get(f'/api/v1/points/total/?student={other_student.id}')
    # 404, not 403: a 403 would confirm the other student exists.
    assert response.status_code == 404


def test_a_parent_can_read_their_own_childs_total(api, auth, parent, student):
    from classroom.models import ParentStudent

    ParentStudent.objects.create(parent=parent, student=student, is_active=True)
    StudentPointsTotal.objects.create(student=student, total_points=12.0)

    auth(parent)
    response = api.get(f'/api/v1/points/total/?student={student.id}')
    assert response.status_code == 200
    assert response.data['total_points'] == 12.0


def test_points_awards_are_scoped(api, auth, student, other_student):
    PointsAward.objects.create(student=student, source='quiz',
                               unit_key='a', points=5, label='Mine')
    PointsAward.objects.create(student=other_student, source='quiz',
                               unit_key='b', points=5, label='Theirs')
    auth(student)
    rows = api.get('/api/v1/points/').data['results']
    assert [row['label'] for row in rows] == ['Mine']


def test_leaderboard_shows_only_the_boards_display_name(
        api, auth, student, other_student):
    """The board spans every school, so it shows a first name and a last
    initial for other children — never a full name, email or id. That rule
    lives in StudentPointsTotal.display_name; this pins the API to it."""
    other_student.first_name = 'Riko'
    other_student.last_name = 'Samarasinghe'
    other_student.save(update_fields=['first_name', 'last_name'])

    StudentPointsTotal.objects.create(student=student, total_points=10.0)
    StudentPointsTotal.objects.create(student=other_student, total_points=20.0)

    auth(student)
    response = api.get('/api/v1/leaderboard/')
    assert response.status_code == 200

    top = response.data['podium'][0]
    assert top['name'] == 'Riko S.'
    assert top['is_me'] is False

    body = str(response.data)
    assert other_student.email not in body
    assert 'Samarasinghe' not in body
    assert str(other_student.id) not in [row.get('id') for row in response.data['podium']]


def test_leaderboard_marks_the_caller(api, auth, student, other_student):
    StudentPointsTotal.objects.create(student=student, total_points=10.0)
    StudentPointsTotal.objects.create(student=other_student, total_points=20.0)
    auth(student)
    response = api.get('/api/v1/leaderboard/')
    assert response.data['rank'] == 2
    assert [row['is_me'] for row in response.data['podium']] == [False, True]


def test_school_leaderboard_says_so_when_there_is_no_school(api, auth, student):
    """Silently returning the global board under a school label would be a lie."""
    auth(student)
    response = api.get('/api/v1/leaderboard/?scope=school')
    assert response.status_code == 404
    assert response.data['error']['code'] == 'no_school_board'


def test_progress_reports_are_scoped_to_visible_students(
        api, auth, student, other_student, parent):
    from classroom.models import ParentStudent

    PeriodReport.objects.create(
        student=student, period_type='weekly',
        period_start='2026-03-02', period_end='2026-03-08', data={'total': 1})
    PeriodReport.objects.create(
        student=other_student, period_type='weekly',
        period_start='2026-03-02', period_end='2026-03-08', data={'total': 2})

    auth(student)
    rows = api.get('/api/v1/reports/').data['results']
    assert [row['student']['id'] for row in rows] == [student.id]

    api.credentials()
    ParentStudent.objects.create(parent=parent, student=student, is_active=True)
    auth(parent)
    rows = api.get('/api/v1/reports/').data['results']
    assert [row['student']['id'] for row in rows] == [student.id]


def test_report_list_omits_the_heavy_snapshot(api, auth, student):
    PeriodReport.objects.create(
        student=student, period_type='weekly',
        period_start='2026-03-02', period_end='2026-03-08',
        data={'topics': ['a'] * 100})
    auth(student)
    listed = api.get('/api/v1/reports/').data['results'][0]
    assert 'data' not in listed

    detail = api.get(f"/api/v1/reports/{listed['id']}/")
    assert 'data' in detail.data


def test_a_student_cannot_open_another_students_report(api, auth, student, other_student):
    report = PeriodReport.objects.create(
        student=other_student, period_type='weekly',
        period_start='2026-03-02', period_end='2026-03-08', data={})
    auth(student)
    assert api.get(f'/api/v1/reports/{report.id}/').status_code == 404
