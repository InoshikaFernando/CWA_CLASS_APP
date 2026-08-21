"""
Management command: reap_stuck_uploads

When a background work-horse is hard-killed (OOM, crash, SIGKILL) mid-job, the
task's failure handler never runs, so the upload session is left in 'processing'
forever and the UI polls it indefinitely. This command marks any session stuck
in 'processing' beyond a threshold as failed, so the page self-heals to a
"failed — please try again" state.

Homework PDF sessions heartbeat while they work (progress_updated_at), so those
are judged on their last sign of life rather than raw age — a long worksheet
that is still classifying is left alone.

Installed as a cron drop-in by deploy/setup-app-prod.sh (every 5 minutes):
    */5 * * * * cwa /home/cwa/CWA_CLASS_APP/scripts/reap_stuck_uploads.sh ...
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

STUCK_MESSAGE = (
    'Processing was interrupted (the server likely ran out of memory). '
    'Please try again.'
)


class Command(BaseCommand):
    help = "Mark uploads stuck in 'processing' beyond --minutes as failed."

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=10,
                            help='Age (minutes) after which a processing session is considered stuck.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be reaped without changing anything.')

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options['minutes'])
        dry_run = options['dry_run']

        from ai_import.models import AIImportSession
        from homework.models import HomeworkUploadSession
        from worksheets.models import WorksheetUploadSession

        # (Model, processing-status, failed-status) — homework uses its own labels.
        targets = [
            (AIImportSession, AIImportSession.STATUS_PROCESSING, AIImportSession.STATUS_FAILED),
            (WorksheetUploadSession, WorksheetUploadSession.STATUS_PROCESSING, WorksheetUploadSession.STATUS_FAILED),
            (HomeworkUploadSession, HomeworkUploadSession.STATUS_PROCESSING, HomeworkUploadSession.STATUS_ERROR),
        ]

        total = 0
        for model, processing, failed in targets:
            qs = model.objects.filter(status=processing, created_at__lt=cutoff)
            # Homework PDF jobs heartbeat while they work, and a long worksheet
            # legitimately runs past --minutes. Age alone would reap a healthy
            # job; spare anything that has reported progress recently.
            if model is HomeworkUploadSession:
                qs = qs.exclude(progress_updated_at__gte=cutoff)
            n = qs.count()
            total += n
            if n and not dry_run:
                qs.update(status=failed, error_message=STUCK_MESSAGE)
            verb = 'would reap' if dry_run else 'reaped'
            self.stdout.write(f'{model.__name__}: {verb} {n} stuck session(s) → {failed}')

        self.stdout.write(self.style.SUCCESS(
            f'Done. {total} stuck upload(s) {"found" if dry_run else "reaped"} '
            f'(older than {options["minutes"]} min).'
        ))
