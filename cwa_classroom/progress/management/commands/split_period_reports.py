"""Split pre-CPP-395 reports into one report per subject (CPP-395 §8, M2).

Recomputes rather than relabels. A legacy row covers every subject the student
touched in the window, so marking it "mathematics" would misrepresent what a
family already received; instead its window is rebuilt once per subject.

Two properties this command exists to preserve:

* **Delivery state carries onto every child row.** Splitting one *sent* report
  into three without it would re-notify a family about a period they have
  already heard about. That is the failure this whole command is written
  around.
* **The original stays.** ``PeriodReport.data`` was frozen so a PDF downloaded
  months later still says what the notification said. The legacy row keeps its
  snapshot and is left in place; nothing a parent has opened changes.

Recomputation can legitimately disagree with the frozen snapshot — homework may
have been re-graded or deleted since. Differences are **reported, never
silently applied**, so run ``--dry-run`` first and read the diff.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from progress.models import PeriodReport
from progress.reports import build_report_data
from progress.services import _student_classrooms_for_window


class Command(BaseCommand):
    help = 'Split legacy all-subject period reports into one report per subject.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would happen and write nothing.')
        parser.add_argument('--school', type=int, default=None,
                            help='Limit to one school id.')
        parser.add_argument('--period', default=None,
                            help='Limit to weekly, monthly or term.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Stop after this many legacy reports.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        qs = PeriodReport.objects.filter(subject__isnull=True)
        if options['school']:
            qs = qs.filter(school_id=options['school'])
        if options['period']:
            qs = qs.filter(period_type=options['period'])
        qs = qs.select_related('student', 'school', 'term').order_by('id')
        if options['limit']:
            qs = qs[:options['limit']]

        legacy = list(qs)
        if not legacy:
            # Said out loud rather than exiting silently: "nothing to do" and
            # "the filter matched nothing" look identical otherwise.
            self.stdout.write(self.style.SUCCESS(
                'No unsplit reports match. Nothing to do.'
            ))
            return

        created = skipped = 0
        differences = []

        for report in legacy:
            subjects = self._subjects_for(report)
            if not subjects:
                skipped += 1
                self.stdout.write(
                    f'  skip  #{report.id} {report.student} {report.period_start}: '
                    f'no class in this window carries a subject'
                )
                continue

            for subject, class_ids in subjects.items():
                data = build_report_data(
                    report.student, report.period_type,
                    report.period_start, report.period_end,
                    term=report.term, classroom_ids=class_ids, subject=subject,
                )
                diff = self._compare(report, data, subject)
                if diff:
                    differences.append(diff)

                if dry_run:
                    created += 1
                    continue

                with transaction.atomic():
                    _, was_created = PeriodReport.objects.get_or_create(
                        student=report.student, period_type=report.period_type,
                        period_start=report.period_start, subject=subject,
                        defaults={
                            'school': report.school,
                            'term': report.term,
                            'period_end': report.period_end,
                            'data': data,
                            # The family was told about this period. Carrying
                            # the timestamps is what stops the split re-telling
                            # them once per subject.
                            'notified_at': report.notified_at,
                            'parent_emailed_at': report.parent_emailed_at,
                        },
                    )
                created += 1 if was_created else 0

        self._report(created, skipped, len(legacy), differences, dry_run)

    def _subjects_for(self, report):
        """``{Subject: [classroom_id, ...]}`` for the window this report covers."""
        stored = (report.data.get('scope') or {}).get('classroom_ids')
        classrooms = _student_classrooms_for_window(report.student, stored)
        by_subject = {}
        for classroom in classrooms:
            if classroom.subject_id is None:
                continue
            by_subject.setdefault(classroom.subject, []).append(classroom.id)
        return by_subject

    def _compare(self, report, data, subject):
        """Where the recomputed figures disagree with the frozen snapshot.

        Only reported. The snapshot is what the family saw, and this command
        is not entitled to decide the new number is the true one.
        """
        old = (report.data.get('totals') or {}).get('homework_attempted')
        new = (data.get('totals') or {}).get('homework_attempted')
        if old is None or new is None or new <= old:
            return None
        return (
            f'  diff  #{report.id} {report.student} {report.period_start} '
            f'[{subject.name}]: homework_attempted {old} -> {new} '
            f'(recomputed exceeds the frozen snapshot for one subject)'
        )

    def _report(self, created, skipped, total, differences, dry_run):
        verb = 'would create' if dry_run else 'created'
        self.stdout.write('')
        self.stdout.write(f'legacy reports examined : {total}')
        self.stdout.write(f'per-subject reports {verb}: {created}')
        if skipped:
            self.stdout.write(self.style.WARNING(
                f'skipped (no subject on any class): {skipped}'
            ))
        if differences:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'{len(differences)} recomputed figures differ from the frozen '
                f'snapshot. The snapshot is what was sent; read these before '
                f'trusting the new rows:'
            ))
            for line in differences:
                self.stdout.write(line)
        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE('Dry run — nothing written.'))
