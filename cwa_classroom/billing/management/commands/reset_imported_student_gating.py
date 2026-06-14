"""
Re-gate school students who slipped past the first-login payment flow (CPP-300).

Background
----------
``CustomUser.profile_completed`` defaults to ``True``. Before CPP-300 the CSV
import created students without overriding it, so imported students skipped the
``CompleteProfileView`` payment/discount gate and rode their school's
(often unlimited "Platinum") plan via the ANY-school entitlement logic.

This command finds school students (``Role.STUDENT``) who currently have
``profile_completed=True`` but have **no** paid access of their own — i.e. no
``billing.Subscription`` in an active/trialing status — and sets
``profile_completed=False`` so ``ProfileCompletionMiddleware`` funnels them back
through the gate on their next login.

Predicate (authoritative = the Subscription row)
------------------------------------------------
Re-gate a Role.STUDENT iff:
  * they currently have ``profile_completed=True``, AND
  * they have NO ``Subscription`` with status in (active, trialing).

A student who redeemed a 100%-off discount code has an active free
``Subscription`` and is therefore NOT re-gated. ``stripe_customer_id`` is a
secondary signal only — any student who paid has an active/trialing
subscription, so the status check already covers them.

Never touches staff, parents, or individual students.

Idempotent: students already ``profile_completed=False`` are skipped, so a
second run changes nothing.

Usage
-----
    python manage.py reset_imported_student_gating --dry-run   # preview
    python manage.py reset_imported_student_gating             # apply
"""
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.models import CustomUser, Role
from billing.models import Subscription

logger = logging.getLogger(__name__)

_ACTIVE_SUB_STATUSES = (Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING)
_SAMPLE_SIZE = 10


class Command(BaseCommand):
    help = (
        'Re-gate imported school students with no active subscription so they '
        'pass through the first-login payment/discount flow (CPP-300).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview affected students without writing any changes.',
        )
        parser.add_argument(
            '--school',
            type=int,
            default=None,
            metavar='SCHOOL_ID',
            help=(
                'Restrict re-gating to students with an active enrolment in this '
                'school (classroom.School id). Omit to consider all schools. '
                'Use this to avoid sweeping in orphaned/no-school accounts.'
            ),
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        school_id = options['school']

        # Users who have their own active/trialing subscription already have
        # paid (or free-code) access — exclude them.
        subscribed_user_ids = set(
            Subscription.objects.filter(
                status__in=_ACTIVE_SUB_STATUSES,
            ).values_list('user_id', flat=True)
        )

        # School students only. Exclude individual students explicitly even if a
        # user somehow holds both roles.
        candidates_qs = (
            CustomUser.objects.filter(
                roles__name=Role.STUDENT,
                profile_completed=True,
            )
            .exclude(roles__name=Role.INDIVIDUAL_STUDENT)
            .exclude(id__in=subscribed_user_ids)
        )

        # Optional school scope: only students actively enrolled in the given
        # school. This deliberately excludes orphaned students whose school was
        # deleted (no active SchoolStudent row), so they are never re-gated.
        if school_id is not None:
            from classroom.models import School, SchoolStudent
            if not School.objects.filter(id=school_id).exists():
                raise CommandError(f'No School with id={school_id} exists.')
            enrolled_ids = SchoolStudent.objects.filter(
                school_id=school_id, is_active=True,
            ).values_list('student_id', flat=True)
            candidates_qs = candidates_qs.filter(id__in=enrolled_ids)

        candidate_ids = list(
            candidates_qs.distinct().values_list('id', flat=True)
        )
        candidates = CustomUser.objects.filter(id__in=candidate_ids)

        scope_note = f' in school id={school_id}' if school_id is not None else ''

        total = len(candidate_ids)
        if total == 0:
            self.stdout.write(self.style.SUCCESS(
                f'No students need re-gating{scope_note} — all school students '
                'either have an active subscription or are already gated.'
            ))
            return

        sample = list(
            candidates.values_list('username', 'email')[:_SAMPLE_SIZE]
        )

        self.stdout.write(
            f'{total} school student(s){scope_note} with no active subscription '
            f'will be re-gated (profile_completed -> False).'
        )
        self.stdout.write('Sample:')
        for username, email in sample:
            self.stdout.write(f'  - {username} <{email or "no email"}>')
        if total > len(sample):
            self.stdout.write(f'  ... and {total - len(sample)} more.')

        if dry_run:
            self.stdout.write(self.style.WARNING(
                'Dry run — no changes written.'
            ))
            logger.info(
                'reset_imported_student_gating dry-run: %d student(s) would be re-gated.',
                total,
            )
            return

        updated = candidates.update(profile_completed=False)
        logger.info(
            'reset_imported_student_gating: re-gated %d school student(s).',
            updated,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Re-gated {updated} school student(s). They will complete the '
            f'payment/discount flow on next login.'
        ))
