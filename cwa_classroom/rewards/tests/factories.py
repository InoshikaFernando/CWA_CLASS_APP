"""Shared helpers for the rewards tests."""

from accounts.models import CustomUser, Role


def role(name, display=None):
    obj, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': display or name.title()},
    )
    return obj


def make_student(username, role_name=Role.STUDENT, **kwargs):
    user = CustomUser.objects.create_user(
        username, f'{username}@example.test', 'pass1234', **kwargs,
    )
    user.roles.add(role(role_name))
    return user
