"""
convert_fill_blanks
~~~~~~~~~~~~~~~~~~~
Turn existing typed questions whose text carries "___" gaps into real
fill-in-the-blank questions, so they render as a sentence with an input in each
gap instead of one box for the whole thing.

This is the BACKFILL. Questions arriving from now on are converted as they are
saved — the AI importer, the spreadsheet/ZIP upload and the teacher form all
route through ``Question.apply_blank_format``, the same entry point this command
uses. Run this once over what was already in the database; after that it should
find nothing.

The underscores ARE the identifier — a question written

    "Out of 100 000 births, 99 231 females are expected to survive to the age
     of ___. From that age, the survivors are expected to ___ for another 67.0
     years."

is a fill-in-the-blank question no matter what question_type it was saved under,
and nothing else in the database looks like that.

Scope:
  - question_type in short_answer / calculation / fill_blank (typed answers
    only; an MCQ with a gap in its stem is a choice question and is left alone)
  - question_text contains at least --min-blanks runs of two or more underscores
  - blank_spec not already set (re-running is a no-op unless --force)

What it writes: ``blank_spec`` (the accepted answers per gap, derived from the
question's existing correct Answer rows) and ``question_type='fill_blank'``.

What it does NOT write: the Answer rows. They are left exactly as they are —
BrainBuzz still snapshots them, exports still carry them, and keeping them is
what makes this reversible: clearing blank_spec returns a question to its
single-box form with its answer intact.

Questions whose answers cannot be mapped onto their gaps unambiguously are
REPORTED, never guessed at. A gap filled from the wrong value marks a correct
student wrong and nobody would find out, so an unmappable question keeps working
exactly as it does today and is listed for a human to fix.

Start with the single-gap questions: there, every stored row becomes an accepted
spelling of the one gap, which cannot land on the wrong blank. Multi-gap
questions are only converted when their answers say unambiguously what goes in
each gap; the rest are reported for a content fix.

Usage (run from the app dir, e.g. /home/cwa/CWA_CLASS_APP_TEST):
    python manage.py convert_fill_blanks                    # dry run — report only
    python manage.py convert_fill_blanks --max-blanks 1     # the safe single-gap set
    python manage.py convert_fill_blanks --min-blanks 2     # only multi-gap ones
    python manage.py convert_fill_blanks --topic Statistics # one topic subtree
    python manage.py convert_fill_blanks --level 10
    python manage.py convert_fill_blanks --id 4021 --id 4022
    python manage.py convert_fill_blanks --apply            # actually write
    python manage.py convert_fill_blanks --revert --apply   # undo: clear the specs
"""
from django.core.management.base import BaseCommand, CommandError

from classroom.models import Topic
from maths.blank_grading import count_blanks, describe_blank_spec
from maths.models import Question

# Only typed answers. An MCQ whose stem happens to contain a gap is still a
# question you pick an option for, and rendering an input into its stem would
# break it.
TYPED_TYPES = ['short_answer', 'calculation', 'fill_blank']


class Command(BaseCommand):
    help = (
        'Convert typed questions containing "___" gaps into fill-in-the-blank '
        'questions (writes blank_spec). Dry run unless --apply.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--min-blanks', type=int, default=1, metavar='N',
            help='Only convert questions with at least N gaps. Default 1. Use 2 '
                 'to target only the sentences a single box genuinely cannot ask.',
        )
        parser.add_argument(
            '--topic', default='', metavar='NAME',
            help='Limit to a topic (name contains, case-insensitive) and every '
                 'topic beneath it.',
        )
        parser.add_argument(
            '--level', type=int, default=None, metavar='N',
            help='Limit to one year level.',
        )
        parser.add_argument(
            '--id', type=int, action='append', default=[], metavar='PK',
            help='Limit to specific question ids — repeatable.',
        )
        parser.add_argument(
            '--max-blanks', type=int, default=None, metavar='N',
            help='Only convert questions with at most N gaps. Use 1 to take the '
                 'single-gap questions on their own — the mapping there is one '
                 'row per accepted spelling, which cannot land on the wrong gap.',
        )
        parser.add_argument(
            '--map-rows-to-gaps', action='store_true',
            help='Trust N answer rows on an N-gap question to be one value per '
                 'gap, in order. OFF by default: rows on legacy questions were '
                 'written to fill a single answer box, so three of them is no '
                 'evidence there is one per gap, and mapping them positionally '
                 'marks correct students wrong. Turn it on only for content you '
                 'know was authored gap by gap.',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Rebuild blank_spec on questions that already have one.',
        )
        parser.add_argument(
            '--revert', action='store_true',
            help='Undo: clear blank_spec on the matched questions, returning them '
                 'to the single-box form. Their answers are untouched, so this '
                 'loses nothing. Leaves question_type as fill_blank.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the changes. Without this the command only reports (dry run).',
        )

    # ------------------------------------------------------------------
    def _with_descendants(self, seed_ids):
        """seed_ids plus every descendant topic id (breadth-first)."""
        ids, frontier = set(), list(seed_ids)
        while frontier:
            ids.update(frontier)
            frontier = list(
                Topic.objects.filter(parent_id__in=frontier)
                .exclude(id__in=ids)
                .values_list('id', flat=True)
            )
        return ids

    def _queryset(self, opts):
        qs = Question.objects.filter(question_type__in=TYPED_TYPES)

        if opts['id']:
            qs = qs.filter(pk__in=opts['id'])
        if opts['topic']:
            roots = Topic.objects.filter(
                name__icontains=opts['topic']).values_list('id', flat=True)
            topic_ids = self._with_descendants(list(roots))
            if not topic_ids:
                raise CommandError(f'No topic matches {opts["topic"]!r}.')
            qs = qs.filter(topic_id__in=topic_ids)
        if opts['level'] is not None:
            qs = qs.filter(level__level_number=opts['level'])

        if opts['revert']:
            return qs.filter(blank_spec__isnull=False).order_by('pk')

        # The database cannot count underscore runs, so narrow to text that has
        # any underscore at all and do the real count in Python.
        qs = qs.filter(question_text__contains='__')
        if not opts['force']:
            qs = qs.filter(blank_spec__isnull=True)
        return qs.select_related('topic', 'level').prefetch_related('answers').order_by('pk')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        apply_changes = opts['apply']
        min_blanks = opts['min_blanks']
        if min_blanks < 1:
            raise CommandError('--min-blanks must be at least 1.')

        if opts['revert']:
            return self._revert(opts, apply_changes)

        max_blanks = opts['max_blanks']
        if max_blanks is not None and max_blanks < min_blanks:
            raise CommandError('--max-blanks must not be below --min-blanks.')

        def _in_range(q):
            gaps = count_blanks(q.question_text)
            return gaps >= min_blanks and (max_blanks is None or gaps <= max_blanks)

        candidates = [q for q in self._queryset(opts) if _in_range(q)]

        if not candidates:
            self.stdout.write(self.style.WARNING(
                'No questions matched. Nothing with "___" gaps in scope — '
                'widen the filters, or lower --min-blanks.'
            ))
            return

        converted, skipped = [], []
        for q in candidates:
            was = q.question_type
            # The same entry point the AI importer, the spreadsheet upload and
            # the teacher form use, so a question converted in bulk comes out
            # identical to one that arrived already marked up.
            changed, reason = q.apply_blank_format(
                positional_rows=opts['map_rows_to_gaps'])
            if reason or not changed:
                skipped.append((q, reason or 'nothing to convert'))
                continue
            if apply_changes:
                q.save(update_fields=['blank_spec', 'question_type'])
            converted.append((q, was))

        self._report(converted, skipped, apply_changes)

    # ------------------------------------------------------------------
    def _report(self, converted, skipped, apply_changes):
        for q, was in converted:
            self.stdout.write(
                f'  Q{q.pk} [{was}] {count_blanks(q.question_text)} gap(s): '
                f'{describe_blank_spec(q.blank_spec)}'
            )
            self.stdout.write(self.style.HTTP_INFO(
                f'        {q.question_text[:110]}'))

        # Not a footnote: these are questions that LOOK like fill-in-the-blank
        # and are staying as they are. Naming each one and why is the whole
        # point — the alternative is a silent partial conversion nobody audits.
        if skipped:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'{len(skipped)} question(s) have gaps but were NOT converted — '
                f'each needs its answer fixed by hand first:'))
            for q, reason in skipped:
                self.stdout.write(self.style.WARNING(f'  Q{q.pk}: {reason}'))
                self.stdout.write(f'        {q.question_text[:110]}')

        self.stdout.write('')
        verb = 'Converted' if apply_changes else 'Would convert'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {len(converted)} question(s); {len(skipped)} skipped.'))
        if not apply_changes:
            self.stdout.write('Dry run — nothing was written. Re-run with --apply.')

    # ------------------------------------------------------------------
    def _revert(self, opts, apply_changes):
        rows = list(self._queryset(opts))
        if not rows:
            self.stdout.write(self.style.WARNING(
                'No converted questions in scope — nothing to revert.'))
            return
        for q in rows:
            self.stdout.write(f'  Q{q.pk}: clearing {describe_blank_spec(q.blank_spec)}')
            if apply_changes:
                q.blank_spec = None
                q.save(update_fields=['blank_spec'])
        verb = 'Reverted' if apply_changes else 'Would revert'
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'{verb} {len(rows)} question(s).'))
        if not apply_changes:
            self.stdout.write('Dry run — nothing was written. Re-run with --apply.')
