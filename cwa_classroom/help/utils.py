from accounts.models import Role

ROLE_TO_GROUP = {
    Role.HEAD_OF_INSTITUTE: 'hoi',
    Role.INSTITUTE_OWNER: 'hoi',
    Role.HEAD_OF_DEPARTMENT: 'hod',
    Role.TEACHER: 'teacher',
    Role.SENIOR_TEACHER: 'teacher',
    Role.JUNIOR_TEACHER: 'teacher',
    Role.ACCOUNTANT: 'accountant',
    Role.PARENT: 'parent',
    Role.STUDENT: 'student',
    Role.INDIVIDUAL_STUDENT: 'student',
    Role.ADMIN: 'admin',
}


def get_role_group(active_role):
    """Map an active_role string to a help role group key."""
    return ROLE_TO_GROUP.get(active_role, 'student')
