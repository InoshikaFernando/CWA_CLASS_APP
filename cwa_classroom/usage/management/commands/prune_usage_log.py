"""Prune PageHit rows: by age (retention) and/or bot-noise backlog.

The Usage Analytics charts only need 30 days; 90 keeps a lookback buffer.
Idempotent and safe to re-run — wire the age prune into a nightly cron.

    python manage.py prune_usage_log            # delete > 90 days old
    python manage.py prune_usage_log --days 35  # tighter retention
    python manage.py prune_usage_log --dry-run  # report only, delete nothing
    python manage.py prune_usage_log --noise    # delete recorded bot/scanner
                                                #   4xx noise (one-off backlog
                                                #   cleanup after the middleware
                                                #   stopped recording them)
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from usage.models import PageHit
from usage.reporting import _is_noise

DEFAULT_RETENTION_DAYS = 90
BATCH_SIZE = 5000


class Command(BaseCommand):
    help = 'Prune PageHit rows by age (retention) and/or recorded bot-noise.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=DEFAULT_RETENTION_DAYS,
                            help='Retention window in days (default 90).')
        parser.add_argument('--noise', action='store_true',
                            help='Also delete recorded bot/scanner 4xx noise hits.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report counts without deleting anything.')

    def handle(self, *args, **options):
        days = options['days']
        dry = options['dry_run']
        cutoff = timezone.now() - timedelta(days=days)

        # --- age-based retention prune ---
        old_count = PageHit.objects.filter(created_at__lt=cutoff).count()
        if dry:
            self.stdout.write(
                f'[dry-run] Would delete {old_count} row(s) older than {days} '
                f'days (before {cutoff.isoformat()}).')
        else:
            deleted = 0
            while True:
                batch_ids = list(PageHit.objects.filter(created_at__lt=cutoff)
                                 .values_list('id', flat=True)[:BATCH_SIZE])
                if not batch_ids:
                    break
                n, _ = PageHit.objects.filter(id__in=batch_ids).delete()
                deleted += n
            self.stdout.write(self.style.SUCCESS(
                f'Deleted {deleted} row(s) older than {days} days.'))

        # --- one-off bot-noise backlog cleanup ---
        if options['noise']:
            noise_ids = [
                pk for pk, path in PageHit.objects.filter(status_code__gte=400)
                .values_list('id', 'path') if _is_noise(path)
            ]
            if dry:
                self.stdout.write(
                    f'[dry-run] Would delete {len(noise_ids)} bot-noise 4xx row(s).')
            else:
                deleted = 0
                for i in range(0, len(noise_ids), BATCH_SIZE):
                    n, _ = PageHit.objects.filter(
                        id__in=noise_ids[i:i + BATCH_SIZE]).delete()
                    deleted += n
                self.stdout.write(self.style.SUCCESS(
                    f'Deleted {deleted} bot-noise 4xx row(s).'))
