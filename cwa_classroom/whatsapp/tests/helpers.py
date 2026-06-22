"""Lightweight test data helpers (the codebase has no factory_boy)."""
from accounts.models import CustomUser, Role
from classroom.models import School

_counter = {'n': 0}


def _uid():
    _counter['n'] += 1
    return _counter['n']


def make_user(username=None, phone=''):
    n = _uid()
    username = username or f'wa_user{n}'
    user = CustomUser.objects.create_user(
        username, f'{username}@example.com', 'pass1!')
    if phone:
        user.phone = phone
        user.save(update_fields=['phone'])
    return user


def make_school(name=None):
    n = _uid()
    admin = make_user(f'wa_admin{n}')
    role, _ = Role.objects.get_or_create(
        name=Role.ADMIN, defaults={'display_name': 'Admin'})
    admin.roles.add(role)
    return School.objects.create(
        name=name or f'WA School {n}', slug=f'wa-school-{n}', admin=admin)
