"""
Management command to create SchoolSubscription records for schools
that existed before the billing system was added.

Usage:
    python manage.py backfill_subscriptions          # apply
    python manage.py backfill_subscriptions --dry-run # preview
"""
from django.core.management.base import BaseCommand

from billing.models import SchoolSubscription, InstitutePlan
from classroom.models import School


class Command(BaseCommand):
    help = 'Create SchoolSubscription records for schools missing them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview without saving.',
        )
        parser.add_argument(
            '--status',
            default='trialing',
            choices=['trialing', 'active'],
            help='Initial status for new subscriptions (default: trialing).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        status = options['status']

        # Get default plan (cheapest active plan)
        default_plan = InstitutePlan.objects.filter(is_active=True).order_by('price').first()
        if not default_plan:
            self.stderr.write(self.style.ERROR('No active InstitutePlan found.'))
            return

        schools_without_sub = School.objects.exclude(
            id__in=SchoolSubscription.objects.values_list('school_id', flat=True)
        )

        if not schools_without_sub.exists():
            self.stdout.write(self.style.SUCCESS('All schools already have subscriptions.'))
            return

        self.stdout.write(f'Found {schools_without_sub.count()} school(s) without subscriptions:')
        created = 0

        for school in schools_without_sub:
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'  [DRY RUN] Would create subscription for: {school.name} (ID: {school.id})'
                ))
            else:
                SchoolSubscription.objects.create(
                    school=school,
                    plan=default_plan,
                    status=status,
                )
                self.stdout.write(self.style.SUCCESS(
                    f'  [OK] Created subscription for: {school.name} (ID: {school.id}) '
                    f'- plan={default_plan.name}, status={status}'
                ))
            created += 1

        action = 'would create' if dry_run else 'created'
        self.stdout.write(f'\n{action.capitalize()} {created} subscription(s) with plan: {default_plan.name}')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run -- no changes saved.'))
