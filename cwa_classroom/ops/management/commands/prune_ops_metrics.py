"""Delete OpsSnapshot rows older than the retention window.

Default 400 days so the 6-month dashboard window always has data with margin.
Idempotent; safe to run daily via cron.

    python manage.py prune_ops_metrics [--days N]
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ops.models import OpsSnapshot


class Command(BaseCommand):
    help = 'Prune OpsSnapshot rows older than --days (default 400).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=400)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options['days'])
        deleted, _ = OpsSnapshot.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(
            f'Pruned {deleted} ops snapshot(s) older than {options["days"]}d.'
        ))
