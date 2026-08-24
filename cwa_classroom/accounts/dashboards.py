"""Where each role lands after a role switch or a "view as" hand-over.

One copy, shared by ``SwitchRoleView`` and the impersonation views, so the two
can't drift into sending the same role to different places.
"""
from .models import Role

ROLE_DASHBOARDS = {
    Role.PARENT: 'parent_dashboard',
    Role.ADMIN: 'admin_dashboard',
    Role.INSTITUTE_OWNER: 'admin_dashboard',
    Role.HEAD_OF_INSTITUTE: 'admin_dashboard',
    Role.HEAD_OF_DEPARTMENT: 'hod_overview',
    Role.SENIOR_TEACHER: 'teacher_dashboard',
    Role.TEACHER: 'teacher_dashboard',
    Role.JUNIOR_TEACHER: 'teacher_dashboard',
    Role.STUDENT: 'subjects_hub',
    Role.INDIVIDUAL_STUDENT: 'subjects_hub',
    Role.ACCOUNTANT: 'invoice_list',
}


def dashboard_for_role(role):
    """URL name for a role's home screen; 'home' for an unknown/roleless user."""
    return ROLE_DASHBOARDS.get(role, 'home')
