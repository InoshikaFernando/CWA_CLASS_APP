"""Fixtures shared by the API suites."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import CustomUser, Role


@pytest.fixture(autouse=True)
def _reset_throttle_cache():
    """DRF throttling counts in the cache; without a reset the counters leak
    between tests in a worker and a later test fails with a spurious 429."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(username, role=None, password='pw-for-tests-123', **kwargs):
        kwargs.setdefault('email', f'{username}@example.test')
        kwargs.setdefault('profile_completed', True)
        user = CustomUser.objects.create_user(
            username=username, password=password, **kwargs)
        if role:
            role_obj, _ = Role.objects.get_or_create(
                name=role, defaults={'display_name': role.title()})
            user.roles.add(role_obj)
        return user
    return _make


@pytest.fixture
def student(make_user):
    return make_user('student1', role=Role.STUDENT)


@pytest.fixture
def other_student(make_user):
    return make_user('student2', role=Role.STUDENT)


@pytest.fixture
def teacher(make_user):
    return make_user('teacher1', role=Role.TEACHER)


@pytest.fixture
def parent(make_user):
    return make_user('parent1', role=Role.PARENT)


@pytest.fixture
def auth(api):
    """Authenticate the client as *user* the way the mobile app does — with a
    real bearer token, not force_authenticate, so the JWT path itself is under
    test rather than mocked away."""
    def _auth(user, password='pw-for-tests-123'):
        response = api.post('/api/v1/auth/login/',
                            {'username': user.username, 'password': password},
                            format='json')
        assert response.status_code == 200, response.data
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        return response.data
    return _auth


@pytest.fixture
def school(db, make_user):
    from classroom.models import School

    owner = make_user('owner1', role=Role.HEAD_OF_INSTITUTE)
    return School.objects.create(name='Test School', slug='test-school', admin=owner)


@pytest.fixture
def classroom(db, school, teacher, student):
    """A class with one teacher and one enrolled student."""
    from classroom.models import ClassRoom, ClassStudent, ClassTeacher

    room = ClassRoom.objects.create(name='Year 5 Maths', school=school, day='monday')
    ClassTeacher.objects.create(classroom=room, teacher=teacher)
    ClassStudent.objects.create(classroom=room, student=student, is_active=True)
    return room
