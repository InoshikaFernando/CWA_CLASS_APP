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


def make_school(name=None, with_module=True):
    """A school that has bought the WhatsApp module.

    Notifications need two switches on: the feature enabled, and the module
    bought. These tests are about the first — normalisation, templates,
    idempotency, delivery — so the second is on by default here, and
    ``with_module=False`` gets a school that has not bought it.
    """
    n = _uid()
    admin = make_user(f'wa_admin{n}')
    role, _ = Role.objects.get_or_create(
        name=Role.ADMIN, defaults={'display_name': 'Admin'})
    admin.roles.add(role)
    school = School.objects.create(
        name=name or f'WA School {n}', slug=f'wa-school-{n}', admin=admin)
    if with_module:
        grant_whatsapp_module(school)
    return school


def grant_whatsapp_module(school):
    """Give *school* a subscription carrying the WhatsApp module."""
    from decimal import Decimal
    from billing.models import (
        InstitutePlan, ModuleSubscription, SchoolSubscription,
    )

    plan, _ = InstitutePlan.objects.get_or_create(
        slug='wa-test-plan',
        defaults={
            'name': 'WA Test', 'price': Decimal('0.00'),
            'class_limit': 0, 'student_limit': 0,
            'invoice_limit_yearly': 10000,
            'extra_invoice_rate': Decimal('0.00'),
        },
    )
    sub, _ = SchoolSubscription.objects.get_or_create(
        school=school,
        defaults={'plan': plan, 'status': SchoolSubscription.STATUS_ACTIVE},
    )
    ModuleSubscription.objects.get_or_create(
        school_subscription=sub,
        module=ModuleSubscription.MODULE_WHATSAPP,
        defaults={'is_active': True},
    )
    return sub
