"""Re-level GLOBAL maths questions whose topic was seeded at the wrong year.

An older seed/import placed sample questions of advanced topics across *every*
year level, so e.g. quadratics and trigonometry ended up at Year 1. This moves
each such question UP to its curriculum-appropriate year, by topic name.

Only GLOBAL questions (school=NULL) currently sitting *below* the target year are
moved — questions already at the target year or higher are left untouched, so
borderline placements (e.g. quadratics already at Y8) are not churned. Basic-facts
/ custom levels (level_number >= 100) are never touched.

Idempotent and ``--dry-run``-aware. Edit ``TARGET_YEAR`` to adjust the mapping.

Usage
-----
    python manage.py relevel_global_questions --dry-run   # report only
    python manage.py relevel_global_questions             # apply
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

# Topic name (case-insensitive, exact) -> curriculum year it belongs at.
# Topics deliberately omitted (Quadratics, Surds, Algebraic Techniques) are
# already at sensible years and are left alone.
TARGET_YEAR = {
    'bodmas': 6,
    'integers': 7,
    'algebra': 7,
    'linear equations': 7,
    'indices and powers': 8,
    "pythagoras' theorem": 8,
    'expanding and factorising quadratics': 9,
    'simultaneous equations': 9,
    'trigonometry': 9,
    'factorising harder quadratics': 10,
    'quadratic formula': 10,
    'completing the square': 10,
}


class Command(BaseCommand):
    help = 'Re-level mis-leveled GLOBAL maths questions to their curriculum year.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report the moves without writing.')

    def handle(self, *args, **opts):
        from maths.models import Question
        from classroom.models import Level

        dry_run = opts['dry_run']

        # Resolve the global Level for each distinct target year.
        levels = {}
        for yr in sorted(set(TARGET_YEAR.values())):
            lvl = (Level.objects.filter(level_number=yr, school__isnull=True).first()
                   or Level.objects.filter(level_number=yr).first())
            if lvl is None:
                self.stderr.write(self.style.WARNING(f'No Level for year {yr} — skipped.'))
            levels[yr] = lvl

        total = 0
        report = []
        with transaction.atomic():
            for name, target in sorted(TARGET_YEAR.items(), key=lambda kv: kv[1]):
                target_level = levels.get(target)
                if target_level is None:
                    continue
                qs = (Question.objects
                      .filter(school__isnull=True, topic__name__iexact=name,
                              level__level_number__lt=target)
                      .exclude(level__level_number__gte=100))
                from_years = defaultdict(int)
                for ln in qs.values_list('level__level_number', flat=True):
                    from_years[ln] += 1
                n = qs.count()
                if n:
                    qs.update(level=target_level)
                    total += n
                    spread = ','.join(f'Y{y}:{c}' for y, c in sorted(from_years.items()))
                    report.append((name, target, n, spread))

            if dry_run:
                transaction.set_rollback(True)

        verb = 'Would move' if dry_run else 'Moved'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{verb} {total} global question(s) to their curriculum year"
            f"{'  [DRY RUN]' if dry_run else ''}"))
        for name, target, n, spread in report:
            self.stdout.write(f"  {name:42} {spread:24} -> Y{target}  ({n})")
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — nothing written.'))
        else:
            self.stdout.write(self.style.SUCCESS('Done.'))
