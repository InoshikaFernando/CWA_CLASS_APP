"""Apply the agreed maths topic consolidation, by PATH rather than by id.

Why a command and not a shell script
------------------------------------
The plan was worked out against ``cwa_test`` and has to run on production too,
and topic ids do not match between the two databases — id 176 is "Fractions and
Percentages" on one and something unrelated on the other. A script full of ids
is therefore safe on exactly one database and dangerous everywhere else.

So every topic here is named by its PATH: ``('Number', 'Division',
'Division (3×)')``. That is what makes the plan portable, and it is also the
only thing that can tell the two times-table sets apart — both are called
"Division (3×)", one under ``Number > Division`` and one under the ``Division``
strand, and no name-only lookup can distinguish them.

What it does NOT do
-------------------
It does not decide anything. Every pair here was read off ``topic_doctor``'s
report and agreed one by one; this command is the transcription, so that the
same decisions reach the second database without being retyped.

Safety
------
* ``--dry-run`` rolls the whole run back, like ``topic_doctor``.
* A survivor that does not resolve SKIPS that merge and says so loudly.
  Nothing is deleted when it is absent — the merge just does not run — but the
  plan has then done less than it claims, and the operator has to be told.
* An absorbed row that does not resolve is SKIPPED and reported — that is the
  normal state on a second run, or on a database that never had it.
* A path that matches more than one topic is a hard error rather than a guess.
* Merging goes through ``classroom.topic_merge.merge_topics``, so it carries
  year links, rescues dependents of colliding rows and recomputes statistics
  exactly as the interactive tool does.

Usage
-----
    python manage.py merge_maths_topics --dry-run
    python manage.py merge_maths_topics
    python manage.py merge_maths_topics --only fractions --dry-run
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

#: (group, survivor path, [absorbed path, ...]) — a path is the chain of names
#: from the strand down, so ('Number', 'Division', 'Division (3×)') is the
#: times table under Number, not the one under the Division strand.
PLAN = [
    # Times tables first: they empty the duplicate Division and Multiplication
    # strands, which is what makes those strands safe to merge away afterwards.
    ('times-tables', ('Number', 'Division', 'Division (3×)'),
     [('Division', 'Division (3×)')]),
    ('times-tables', ('Number', 'Division', 'Division (4×)'),
     [('Division', 'Division (4×)')]),
    ('times-tables', ('Number', 'Division', 'Division (5×)'),
     [('Division', 'Division (5×)')]),
    ('times-tables', ('Number', 'Division', 'Division (6×)'),
     [('Division', 'Division (6×)')]),
    ('times-tables', ('Number', 'Division', 'Division (7×)'),
     [('Division', 'Division (7×)')]),
    ('times-tables', ('Number', 'Division', 'Division (8×)'),
     [('Division', 'Division (8×)')]),
    ('times-tables', ('Number', 'Division', 'Division (9×)'),
     [('Division', 'Division (9×)')]),
    ('times-tables', ('Number', 'Division', 'Division (12×)'),
     [('Division', 'Division (12×)')]),
    ('times-tables', ('Number', 'Multiplication', 'Multiplication (7×)'),
     [('Multiplication', 'Multiplication (7×)')]),
    ('times-tables', ('Number', 'Multiplication', 'Multiplication (8×)'),
     [('Multiplication', 'Multiplication (8×)')]),
    ('times-tables', ('Number', 'Multiplication', 'Multiplication (9×)'),
     [('Multiplication', 'Multiplication (9×)')]),

    # Rows sharing a name exactly, split across two strands.
    ('duplicates', ('Number', 'BODMAS'), [('Algebra', 'BODMAS')]),
    ('duplicates', ('Number', 'Integers'), [('Algebra', 'Integers')]),
    ('duplicates', ('Statistics and Probability', 'Probability'),
     [('Statistics', 'Probability')]),
    ('duplicates', ('Statistics', 'Data Handling'),
     [('Statistics and Probability', 'Data Handling')]),
    ('duplicates', ('Geometry', 'Trigonometry'),
     [('Measurement & Geometry', 'Trigonometry')]),

    # Names that differ only in spelling.
    ('near-duplicates', ('Number', 'Place Value'), [('Number', 'Place Values')]),
    ('near-duplicates', ('Geometry', "Pythagoras' Theorem"),
     [('Geometry', 'Pythagoras Theorem'),
      ('Measurement & Geometry', "Pythagoras' Theorem")]),
    ('near-duplicates', ('Measurement', 'Measurements'),
     [('Measurement', 'Measurement'),
      ('Measurement & Geometry', 'Measurement'),
      ('Geometry', 'Measurement')]),

    # Topics that mean the same thing under different words.
    ('groups', ('Geometry', 'Area and Perimeter'),
     [('Measurement', 'Area'), ('Measurement', 'Perimeter')]),
    ('groups', ('Number', 'Rates & Ratios'),
     [('Number', 'Ratio and Proportion'), ('Number', 'Ratios'),
      ('Number', 'Rates and Speed'), ('Measurement', 'Rates')]),
    ('groups', ('Number', 'Indices'),
     [('Number', 'Indices & Scientific Notation'),
      ('Algebra', 'Index Laws'), ('Algebra', 'Indices and Powers')]),
    ('groups', ('Number', 'Number Patterns'),
     [('Number', 'Number Properties and Patterns'),
      ('Number', 'Number Properties')]),
    ('groups', ('Number', 'Finance'),
     [('Number', 'Money'), ('Number', 'Profit and Loss'),
      ('Number', 'Financial Mathematics'), ('Number', 'GST')]),
    ('groups', ('Algebra', 'Quadratics'),
     [('Algebra', 'Expanding and Factorising Quadratics'),
      ('Algebra', 'Quadratic Equations'), ('Algebra', 'Quadratic Formula'),
      ('Algebra', 'Factorising Harder Quadratics')]),
    ('groups', ('Algebra', 'Solving Linear Equations'),
     [('Algebra', 'Equations'), ('Algebra', 'Forming and Solving Equations'),
      ('Algebra', 'Linear Equations')]),
    ('groups', ('Algebra', 'Factorising'),
     [('Algebra', 'Algebraic Expressions & Factorisation')]),
    ('groups', ('Geometry', 'Angles'),
     [('Geometry', 'Angles and Geometry'),
      ('Measurement & Geometry', 'Angles & Quadrilaterals')]),
    ('groups', ('Number', 'Decimals'),
     [('Number', 'Rounding and Decimals'), ('Number', 'Estimation and Rounding'),
      ('Number', 'Number Skills & Estimation')]),
    ('groups', ('Number', 'Percentages'),
     [('Number', 'Percentage Word Problems'),
      ('Number', 'Percentage Increase and Decrease')]),
    ('groups', ('Number', 'Factors'),
     [('Number', 'Divisibility and Primes'), ('Number', 'Factors and Multiples'),
      ('Number', 'Prime Numbers'), ('Number', 'HCF and LCM')]),

    ('fractions', ('Number', 'Fractions and Percentages'),
     [('Number', 'Fractions'),
      ('Number', 'Fractions Decimals and Percentages'),
      ('Number', 'Fractions & Percentages')]),
]

SUBJECT_SLUG = 'mathematics'


class Command(BaseCommand):
    help = ('Apply the agreed maths topic consolidation. Topics are resolved '
            'by path, so the same plan runs on test and on production.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would happen, write nothing.')
        parser.add_argument('--only', type=str,
                            help='One group: times-tables, duplicates, '
                                 'near-duplicates, groups, fractions.')

    def handle(self, *args, **opts):
        from classroom.models import Subject
        from classroom.topic_merge import merge_topics

        subject = (Subject.objects.filter(slug=SUBJECT_SLUG).first()
                   or Subject.objects.filter(name__iexact='Mathematics').first())
        if subject is None:
            raise CommandError('No Mathematics subject in this database.')

        only = (opts['only'] or '').strip().lower()
        plan = [row for row in PLAN if not only or row[0] == only]
        if only and not plan:
            raise CommandError(
                f'No group named {only!r}. Groups: '
                + ', '.join(sorted({row[0] for row in PLAN})))

        dry = opts['dry_run']
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'=== merge_maths_topics — {subject.name} — {len(plan)} merge(s)'
            f'{"  [DRY RUN]" if dry else ""} ==='))

        merged = skipped = absorbed_total = 0
        missing, no_survivor = [], []

        with transaction.atomic():
            for group, keep_path, absorb_paths in plan:
                keep = self._resolve(subject, keep_path)
                if keep is None:
                    # Not fatal, and not silent. Nothing is deleted when the
                    # survivor is absent — the merge simply does not run — but
                    # the plan has then done less than it says, which the
                    # operator has to be told rather than left to infer.
                    no_survivor.append(self._show(keep_path))
                    continue

                absorbed = []
                for path in absorb_paths:
                    topic = self._resolve(subject, path)
                    if topic is None:
                        missing.append(self._show(path))
                    elif topic.id == keep.id:
                        missing.append(f'{self._show(path)} (is the survivor)')
                    else:
                        absorbed.append(topic)

                if not absorbed:
                    skipped += 1
                    continue

                summary = merge_topics(keep, absorbed)
                merged += 1
                absorbed_total += len(summary['absorbed'])
                self.stdout.write(
                    f"  [{group}] {self._show(keep_path)}  ← "
                    + ', '.join(a['name'] for a in summary['absorbed']))
                for label, n in sorted(summary.get('carried', {}).items()):
                    self.stdout.write(f'      {label} {n} carried')
                for label, n in sorted(summary.get('dropped_dependents', {}).items()):
                    self.stdout.write(self.style.WARNING(
                        f"      {label} {n} dependent(s) clashed — "
                        f"the survivor's was kept"))

            if dry:
                transaction.set_rollback(True)

        self.stdout.write('')
        if no_survivor:
            self.stdout.write(self.style.WARNING(
                f'{len(no_survivor)} merge(s) did NOT run — the survivor is '
                f'not in this database, so nothing was moved into it:'))
            for path in no_survivor:
                self.stdout.write(f'    {path}')
            self.stdout.write('')
        if missing:
            self.stdout.write(self.style.WARNING(
                f'{len(missing)} row(s) not found — already merged, or never '
                f'present in this database:'))
            for path in missing:
                self.stdout.write(f'    {path}')
        self.stdout.write(self.style.SUCCESS(
            f"\n{'Would merge' if dry else 'Merged'} {absorbed_total} topic(s) "
            f'into {merged} survivor(s); {skipped} merge(s) had nothing left '
            f'to absorb.'))
        if dry:
            self.stdout.write('Nothing was written.  [DRY RUN]')

    # ── helpers ───────────────────────────────────────────────────────────
    def _resolve(self, subject, path):
        """Walk a path of names down from a strand. None if it is not there."""
        from classroom.models import Topic

        parent_id, topic = None, None
        for name in path:
            matches = list(Topic.objects.filter(
                subject=subject, parent_id=parent_id, name__iexact=name)[:2])
            if not matches:
                return None
            if len(matches) > 1:
                raise CommandError(
                    f'{self._show(path)}: {len(matches)} topics named {name!r} '
                    f'in the same place. Refusing to guess — merge those first.')
            topic = matches[0]
            parent_id = topic.id
        return topic

    def _show(self, path):
        return ' › '.join(path)
