"""
Management command to grant free (永久 active) subscriptions to:
  - All active individual students with no subscription or an expired/cancelled one.
  - All schools with no subscription or an expired/cancelled one.

Usage:
    python manage.py grant_free_access            # apply
    python manage.py grant_free_access --dry-run  # preview only
"""
from django.core.management.base import BaseCommand

from accounts.models import CustomUser, Role
from billing.models import InstitutePlan, Package, SchoolSubscription, Subscription
from classroom.models import School


class Command(BaseCommand):
    help = (
        'Grant a permanent free subscription to individual students and schools '
        'that have no active/trialing subscription.'
    )

    # Statuses that count as "already covered" — skip these users/schools.
    ACTIVE_STATUSES = {Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING}

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would happen without saving any changes.',
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create_free_package(self, dry_run):
        """Return the 'Free' individual-student Package (price=0, is_active=True)."""
        pkg, created = Package.objects.get_or_create(
            name='Free',
            defaults={
                'price': 0,
                'is_active': True,
                'class_limit': 0,  # unlimited
                'order': 0,
            },
        )
        if created:
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    '[DRY RUN] Would create Package "Free" (price=0)'
                ))
                # Roll back the creation so the DB stays clean during dry-run.
                pkg.delete()
                # Return a dummy unsaved instance so callers can still reference it.
                pkg = Package(name='Free', price=0, is_active=True)
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'Created Package "Free" (id={pkg.pk})'
                ))
        else:
            self.stdout.write(f'Using existing Package "Free" (id={pkg.pk})')
        return pkg

    def _get_or_create_free_institute_plan(self, dry_run):
        """Return the 'Free' InstitutePlan (price=0, is_active=True)."""
        plan, created = InstitutePlan.objects.get_or_create(
            slug='free',
            defaults={
                'name': 'Free',
                'price': 0,
                'is_active': True,
                'class_limit': 999,
                'student_limit': 0,           # unlimited
                'invoice_limit_yearly': 9999,
                'extra_invoice_rate': 0,
                'order': 0,
            },
        )
        if created:
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    '[DRY RUN] Would create InstitutePlan "Free" (price=0)'
                ))
                plan.delete()
                plan = InstitutePlan(name='Free', slug='free', price=0, is_active=True)
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'Created InstitutePlan "Free" (id={plan.pk})'
                ))
        else:
            self.stdout.write(f'Using existing InstitutePlan "Free" (id={plan.pk})')
        return plan

    # ------------------------------------------------------------------
    # Main handler
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('--- DRY RUN: no changes will be saved ---'))

        # ---- Individual students ----------------------------------------
        free_package = self._get_or_create_free_package(dry_run)

        students_granted = 0
        students_skipped = 0

        individual_students = CustomUser.objects.filter(
            is_active=True,
            roles__name=Role.INDIVIDUAL_STUDENT,
        ).distinct()

        for user in individual_students:
            try:
                sub = user.subscription  # OneToOne accessor
                if sub.status in self.ACTIVE_STATUSES:
                    students_skipped += 1
                    continue
                # Expired / cancelled — upgrade to free active.
                if dry_run:
                    self.stdout.write(self.style.WARNING(
                        f'  [DRY RUN] Would update subscription for user '
                        f'"{user.username}" (id={user.pk}) '
                        f'from status={sub.status} to active (Free package)'
                    ))
                else:
                    sub.status = Subscription.STATUS_ACTIVE
                    sub.package = free_package
                    sub.trial_end = None
                    sub.current_period_end = None
                    sub.save(update_fields=[
                        'status', 'package', 'trial_end', 'current_period_end', 'updated_at',
                    ])
                    self.stdout.write(
                        f'  [UPDATED] {user.username} (id={user.pk}) — subscription set to active/Free'
                    )
                students_granted += 1
            except Subscription.DoesNotExist:
                # No subscription at all — create one.
                if dry_run:
                    self.stdout.write(self.style.WARNING(
                        f'  [DRY RUN] Would create active Free subscription for '
                        f'user "{user.username}" (id={user.pk})'
                    ))
                else:
                    Subscription.objects.create(
                        user=user,
                        package=free_package,
                        status=Subscription.STATUS_ACTIVE,
                        trial_end=None,
                        current_period_end=None,
                    )
                    self.stdout.write(
                        f'  [CREATED] {user.username} (id={user.pk}) — new active Free subscription'
                    )
                students_granted += 1

        # ---- Schools ----------------------------------------------------
        free_plan = self._get_or_create_free_institute_plan(dry_run)

        schools_granted = 0
        schools_skipped = 0

        for school in School.objects.all():
            try:
                school_sub = school.subscription  # OneToOne via related_name='subscription'
                if school_sub.status in self.ACTIVE_STATUSES:
                    schools_skipped += 1
                    continue
                # Expired / cancelled — upgrade to free active.
                if dry_run:
                    self.stdout.write(self.style.WARNING(
                        f'  [DRY RUN] Would update SchoolSubscription for school '
                        f'"{school.name}" (id={school.pk}) '
                        f'from status={school_sub.status} to active (Free plan)'
                    ))
                else:
                    school_sub.status = SchoolSubscription.STATUS_ACTIVE
                    school_sub.plan = free_plan
                    school_sub.trial_end = None
                    school_sub.current_period_end = None
                    school_sub.save(update_fields=[
                        'status', 'plan', 'trial_end', 'current_period_end', 'updated_at',
                    ])
                    self.stdout.write(
                        f'  [UPDATED] School "{school.name}" (id={school.pk}) '
                        f'— subscription set to active/Free'
                    )
                schools_granted += 1
            except SchoolSubscription.DoesNotExist:
                if dry_run:
                    self.stdout.write(self.style.WARNING(
                        f'  [DRY RUN] Would create active Free SchoolSubscription '
                        f'for school "{school.name}" (id={school.pk})'
                    ))
                else:
                    SchoolSubscription.objects.create(
                        school=school,
                        plan=free_plan,
                        status=SchoolSubscription.STATUS_ACTIVE,
                        trial_end=None,
                        current_period_end=None,
                    )
                    self.stdout.write(
                        f'  [CREATED] School "{school.name}" (id={school.pk}) '
                        f'— new active Free SchoolSubscription'
                    )
                schools_granted += 1

        # ---- Summary ----------------------------------------------------
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Individual students: {students_granted} granted, {students_skipped} skipped'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'Schools:             {schools_granted} granted, {schools_skipped} skipped'
        ))

        if dry_run:
            self.stdout.write(self.style.WARNING('--- DRY RUN complete — no changes saved ---'))
