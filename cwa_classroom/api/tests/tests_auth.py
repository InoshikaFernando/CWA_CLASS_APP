"""The login exchange, and the walls that must not be redirects."""

import pytest

from accounts.models import Role

pytestmark = pytest.mark.django_db


def test_login_returns_tokens_and_profile(api, student):
    response = api.post('/api/v1/auth/login/',
                        {'username': 'student1', 'password': 'pw-for-tests-123'},
                        format='json')
    assert response.status_code == 200
    assert 'access' in response.data and 'refresh' in response.data
    assert response.data['user']['username'] == 'student1'
    assert Role.STUDENT in response.data['user']['roles']


def test_login_accepts_email(api, student):
    """The website authenticates on email or username; the app must match."""
    response = api.post('/api/v1/auth/login/',
                        {'username': 'student1@example.test',
                         'password': 'pw-for-tests-123'},
                        format='json')
    assert response.status_code == 200


def test_login_rejects_bad_password(api, student):
    response = api.post('/api/v1/auth/login/',
                        {'username': 'student1', 'password': 'wrong'},
                        format='json')
    assert response.status_code == 401
    assert response.data['error']['code'] == 'authentication_failed'


def test_blocked_account_cannot_log_in(api, student):
    student.is_blocked = True
    student.block_type = 'permanent'
    student.save(update_fields=['is_blocked', 'block_type'])

    response = api.post('/api/v1/auth/login/',
                        {'username': 'student1', 'password': 'pw-for-tests-123'},
                        format='json')
    assert response.status_code == 400
    assert 'blocked' in str(response.data['error']).lower()


def test_expired_temporary_block_is_lifted_on_login(api, student):
    from django.utils import timezone
    from datetime import timedelta

    student.is_blocked = True
    student.block_type = 'temporary'
    student.block_expires_at = timezone.now() - timedelta(hours=1)
    student.save(update_fields=['is_blocked', 'block_type', 'block_expires_at'])

    response = api.post('/api/v1/auth/login/',
                        {'username': 'student1', 'password': 'pw-for-tests-123'},
                        format='json')
    assert response.status_code == 200
    student.refresh_from_db()
    assert student.is_blocked is False


def test_me_requires_a_token(api):
    assert api.get('/api/v1/auth/me/').status_code == 401


def test_me_returns_the_caller(api, auth, student):
    auth(student)
    response = api.get('/api/v1/auth/me/')
    assert response.status_code == 200
    assert response.data['username'] == 'student1'


def test_me_patch_updates_own_profile_but_not_roles(api, auth, student):
    auth(student)
    response = api.patch('/api/v1/auth/me/',
                         {'first_name': 'Ada', 'roles': ['admin']},
                         format='json')
    assert response.status_code == 200
    assert response.data['first_name'] == 'Ada'
    # `roles` is read-only — a user cannot promote themselves by PATCHing it.
    assert response.data['roles'] == [Role.STUDENT]


def test_refresh_rotates_and_revokes_the_old_token(api, student):
    login = api.post('/api/v1/auth/login/',
                     {'username': 'student1', 'password': 'pw-for-tests-123'},
                     format='json')
    original_refresh = login.data['refresh']

    first = api.post('/api/v1/auth/refresh/', {'refresh': original_refresh},
                     format='json')
    assert first.status_code == 200
    assert first.data['refresh'] != original_refresh

    # Replaying the consumed token must fail — that is the point of rotation.
    replay = api.post('/api/v1/auth/refresh/', {'refresh': original_refresh},
                      format='json')
    assert replay.status_code == 401


def test_logout_revokes_the_refresh_token(api, auth, student):
    tokens = auth(student)
    response = api.post('/api/v1/auth/logout/', {'refresh': tokens['refresh']},
                        format='json')
    assert response.status_code == 205

    replay = api.post('/api/v1/auth/refresh/', {'refresh': tokens['refresh']},
                      format='json')
    assert replay.status_code == 401


def test_logout_reports_a_token_it_could_not_revoke(api, auth, student):
    """A logout that quietly does nothing is the silent failure this repo bans."""
    auth(student)
    response = api.post('/api/v1/auth/logout/', {'refresh': 'not-a-token'},
                        format='json')
    assert response.status_code == 400
    assert response.data['error']['code'] == 'validation_error'


def test_change_password_clears_the_must_change_flag(api, auth, make_user):
    user = make_user('newbie', role=Role.STUDENT, must_change_password=True)
    auth(user)
    response = api.post('/api/v1/auth/change-password/',
                        {'current_password': 'pw-for-tests-123',
                         'new_password': 'a-much-better-pw-42'},
                        format='json')
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.must_change_password is False


def test_blocked_user_gets_json_not_a_redirect(api, auth, student):
    """The web app walls a blocked user with a 302 to an HTML page. A phone
    cannot render that and would read the redirect as success, so /api/ must
    answer with a coded 403 instead."""
    auth(student)
    student.is_blocked = True
    student.block_type = 'permanent'
    student.save(update_fields=['is_blocked', 'block_type'])

    response = api.get('/api/v1/auth/me/')
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'account_blocked'


def test_incomplete_profile_gets_json_not_a_redirect(api, auth, student):
    auth(student)
    student.profile_completed = False
    student.save(update_fields=['profile_completed'])

    response = api.get('/api/v1/classes/')
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'profile_incomplete'


def test_incomplete_profile_can_still_reach_onboarding(api, auth, student):
    """The wall must not cover the endpoints that let the user get past it —
    otherwise a student created by a head of institute can never start."""
    auth(student)
    student.profile_completed = False
    student.save(update_fields=['profile_completed'])

    assert api.get('/api/v1/auth/me/').status_code == 200
    assert api.patch('/api/v1/auth/me/', {'city': 'Auckland'},
                     format='json').status_code == 200
