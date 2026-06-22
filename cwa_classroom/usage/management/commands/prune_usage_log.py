"""Delete PageHit rows older than the retention window (default 90 days).

The Usage Analytics charts only need 30 days; 90 keeps a lookback buffer.
Idempotent and safe to re-run — wire it into a nightly cron on deploy.

    python manage.py prune_usage_log            # delete > 90 days old
    python manage.py prune_usage_log --days 35  # tighter retention
    python manage.py prune_usage_log --dry-run  # report only, delete nothing
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from usage.models import PageHit

DEFAULT_RETENTION_DAYS = 90
BATCH_SIZE = 5000


class Command(BaseCommand):
    help = 'Delete PageHit rows older than the retention window (default 90 days).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=DEFAULT_RETENTION_DAYS,
                            help='Retention window in days (default 90).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report the cutoff and row count without deleting.')

    def handle(self, *args, **options):
        days = options['days']
        cutoff = timezone.now() - timedelta(days=days)
        qs = PageHit.objects.filter(created_at__lt=cutoff)
        count = qs.count()

        if options['dry_run']:
            self.stdout.write(
                f'[dry-run] Would delete {count} PageHit row(s) older than '
                f'{days} days (before {cutoff.isoformat()}).')
            return

        deleted = 0
        while True:
            batch_ids = list(
                PageHit.objects.filter(created_at__lt=cutoff)
                .values_list('id', flat=True)[:BATCH_SIZE])
            if not batch_ids:
                break
            n, _ = PageHit.objects.filter(id__in=batch_ids).delete()
            deleted += n

        self.stdout.write(self.style.SUCCESS(
            f'Deleted {deleted} PageHit row(s) older than {days} days '
            f'(before {cutoff.isoformat()}).'))
