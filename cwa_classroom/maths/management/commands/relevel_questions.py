"""Re-level questions from the class they were actually assigned to.

Why this exists
---------------
Every upload path files a question at the year level the AI guessed, and when
it guessed nothing the fallback is **Year 1**::

    # homework/views.py
    yl = q.get('year_level') or global_data.get('year_level', 1)
    data['year_level'] = int(request.POST.get('year_level', data.get('year_level', 1)))

So a Year 9 worksheet whose year the extractor could not read lands its whole
batch at Year 1. That is not cosmetic: ``maths.views.level_questions`` serves
level practice with ``_get_questions_for_level``, which filters on ``level``
alone and unions a school's own rows with global ones — so a Year 1 student
gets handed the Year 9 batch.

The homework the questions arrived with knows better. A question reaches
students through ``HomeworkQuestion -> Homework -> ClassRoom``, and the class
is linked to the level the teacher put it at. That link is made by a human at
class-creation time, before any AI sees the PDF, so it is the trustworthy
signal — not the topic name, and not ``Topic.levels`` (a strand like "Number"
is linked to every year, which arbitrates nothing).

Two Level ladders
-----------------
Prod carries two, both global, with duplicate display names:

* the **curriculum** ladder (``level_number`` 1..10) — what ``Question.level``
  points at, and the only one the student year page lists (it filters
  ``level_number__lt=100``);
* the **class** ladder (``level_number`` 300+) — what ``ClassRoom.levels``
  points at, including non-year entries like "VCE GM 1/2" or "JS".

This command bridges them. A class level is resolved to a curriculum year by,
in order: an explicit ``--map`` argument, the built-in overrides below, then a
"Year N" / "Yr N" reading of its display name. Anything left unresolved is
REPORTED, never guessed at and never moved.

Deliberately not supported
--------------------------
The curriculum ladder stops at Year 10, so classes above it (VCE General Maths
1/2 and 3/4 — Australian Years 11 and 12) have nowhere to go. They are listed
under "deliberately skipped" rather than being squashed into Year 10, which
would recreate the very bug this command fixes one year lower.

Safety
------
* Requires ``--year``: the year being cleaned up is always stated out loud.
* Moves a question only when the evidence is unambiguous. No homework link, a
  class whose level does not resolve, or a tie between two years — all are
  reported and left alone.
* Soft-deleted homework still counts as evidence: the class a question was
  assigned to is a fact about the question, whether or not that homework was
  later deleted.
* ``--dry-run`` runs the whole thing and rolls back.
* Every moved id is printed, so a move is reversible.

Usage
-----
    python manage.py relevel_questions --year 1 --school 4 --dry-run
    python manage.py relevel_questions --year 1 --school 4 --map "JS=5"
    python manage.py relevel_questions --year 1 --school-slug maths-hub-melbourne-pty-ltd
"""
import re
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from maths.topic_lookup import topic_path

# Class-ladder display names whose curriculum year cannot be read off the name.
# Keyed case-insensitively on ``Level.display_name``. Override or extend from
# the command line with ``--map "NAME=YEAR"``.
CLASS_LEVEL_OVERRIDES = {
    'js': 5,                  # Junior Scholarship
    'junior scholarship': 5,
}

# Known class levels that sit ABOVE the curriculum ladder. Listed so they are
# reported as a deliberate decision rather than as something unrecognised.
KNOWN_UNSUPPORTED = {
    'vce gm 1/2',    # Australian Year 11
    'vce gm 3/4',    # Australian Year 12
    'vce general maths 1/2 mt waverly',
}

_YEAR_NAME_RE = re.compile(r'^\s*(?:year|yr|grade)\s*(\d{1,2})\s*$', re.IGNORECASE)


class Command(BaseCommand):
    help = ('Re-level questions stranded at one year, using the year of the '
            'class each was actually assigned to.')

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True,
                            help='The year to clean up — questions currently at '
                                 'this Level.level_number are the candidates.')
        parser.add_argument('--school', type=int,
                            help='Only questions private to this school id.')
        parser.add_argument('--school-slug', type=str,
                            help='School slug, instead of --school.')
        parser.add_argument('--topic', type=str,
                            help='Only this topic — matched against the topic '
                                 "name, its parent strand's name, or its slug.")
        parser.add_argument('--exact-topic', action='store_true',
                            help='Match --topic as a full name instead of a substring.')
        parser.add_argument('--map', action='append', default=[], metavar='NAME=YEAR',
                            help='Resolve a class level by display name, e.g. '
                                 '--map "JS=5". Repeatable; overrides the built-ins.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report every move, write nothing.')

    # ── entry point ───────────────────────────────────────────────────────
    def handle(self, *args, **opts):
        from classroom.models import Level, School
        from maths.models import Question

        year, dry_run = opts['year'], opts['dry_run']

        school = None
        if opts['school'] or opts['school_slug']:
            try:
                school = (School.objects.get(pk=opts['school']) if opts['school']
                          else School.objects.get(slug=opts['school_slug']))
            except School.DoesNotExist:
                raise CommandError(
                    f"School {opts['school'] or opts['school_slug']!r} not found.")

        source = (Level.objects.filter(level_number=year, school__isnull=True).first()
                  or Level.objects.filter(level_number=year).first())
        if source is None:
            raise CommandError(f'No Level with level_number={year}.')

        # The curriculum ladder: what a question may be re-levelled ONTO.
        curriculum = {}
        for lvl in Level.objects.filter(level_number__lt=100).order_by('level_number'):
            curriculum.setdefault(lvl.level_number, lvl)
        if not curriculum:
            raise CommandError('No curriculum levels (level_number < 100) exist.')
        ladder_top = max(curriculum)

        overrides = dict(CLASS_LEVEL_OVERRIDES)
        for raw in opts['map']:
            name, _, target = raw.rpartition('=')
            if not name or not target.strip().isdigit():
                raise CommandError(f'--map expects "NAME=YEAR", got {raw!r}.')
            overrides[name.strip().lower()] = int(target)

        qs = (Question.objects.filter(level=source)
              .select_related('topic', 'topic__parent', 'level'))
        if school is not None:
            qs = qs.filter(school=school)
        if opts['topic']:
            from maths.topic_lookup import matching_topics
            topics = matching_topics(opts['topic'], exact=opts['exact_topic'])
            if not topics:
                raise CommandError(f"No topic matches {opts['topic']!r}.")
            qs = qs.filter(topic__in=topics)

        candidates = list(qs)
        scope = (f'Year {year}'
                 + (f', {school.name} (id {school.id})' if school else ', all scopes')
                 + (f', topic {opts["topic"]!r}' if opts['topic'] else ''))
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'=== Re-level from class: {scope}{"  [DRY RUN]" if dry_run else ""} ==='))
        if not candidates:
            raise CommandError('No questions match these filters — nothing to do.')

        class_years = self._class_years_by_question(
            [q.id for q in candidates], overrides, curriculum, ladder_top)

        moves = defaultdict(list)      # target level_number -> [question]
        unresolved = defaultdict(list)  # reason -> [question]
        for q in candidates:
            evidence = class_years.get(q.id)
            if not evidence['years']:
                reason = ('assigned, but no class level resolves to a year'
                          if evidence['classes'] else 'never assigned to any homework')
                unresolved[reason].append(q)
                continue
            ranked = evidence['years'].most_common()
            if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
                unresolved[f'tie between years {sorted(y for y, _ in ranked)}'].append(q)
                continue
            target = ranked[0][0]
            if target == year:
                unresolved[f'already at Year {year} per its class'].append(q)
                continue
            moves[target].append(q)

        self._report(candidates, moves, unresolved, class_years, year)

        moved_ids = [q.id for qlist in moves.values() for q in qlist]
        if not moved_ids:
            self.stdout.write(self.style.WARNING(
                '\nNothing to move — no question has unambiguous class evidence '
                'for a different year.'))
            return

        with transaction.atomic():
            from maths.models import Question as Q
            for target, qlist in moves.items():
                Q.objects.filter(id__in=[q.id for q in qlist]).update(
                    level=curriculum[target])
            if dry_run:
                transaction.set_rollback(True)

        verb = 'Would move' if dry_run else 'Moved'
        self.stdout.write(self.style.SUCCESS(
            f'\n{verb} {len(moved_ids)} question(s) off Year {year}'
            + ('  [DRY RUN — rolled back]' if dry_run else '')))
        if not dry_run:
            self.stdout.write(
                f'  to undo: Question.objects.filter(id__in=[...]).update('
                f'level_id={source.id})')
            for target, qlist in sorted(moves.items()):
                self.stdout.write(f'  -> Year {target}: '
                                  + ', '.join(str(q.id) for q in qlist))

    # ── evidence gathering ────────────────────────────────────────────────
    def _class_years_by_question(self, qids, overrides, curriculum, ladder_top):
        """For each question id, the curriculum years of the classes it went to.

        One vote per CLASS, not per homework: a question set five weeks running
        to the same Year 7 class is still one class's view of what year it is,
        and letting homework count multiply would let a single busy class
        outvote every other.

        Soft-deleted homework is included on purpose: ``Homework.objects``
        hides those rows, but the manager does not apply to a SQL join, and a
        deleted homework is still evidence of which class the question was
        written for.
        """
        from homework.models import HomeworkQuestion

        evidence = {qid: {'votes': set(), 'classes': set()} for qid in qids}
        self._unresolved_levels = Counter()
        self._skipped_levels = Counter()

        fields = ('homework__classroom_id',
                  'homework__classroom__name',
                  'homework__classroom__levels__display_name',
                  'homework__classroom__levels__level_number')
        # The same HomeworkQuestion row can surface in both passes below, since
        # it carries the legacy ``question`` FK and the newer ``content_id``.
        seen_rows = set()
        for key_field, extra in (('content_id', {'subject_slug': 'mathematics'}),
                                 ('question_id', {})):
            rows = (HomeworkQuestion.objects
                    .filter(**{f'{key_field}__in': qids}, **extra)
                    .values_list('id', key_field, *fields))
            for hq_id, qid, cls_id, cls_name, lvl_name, lvl_num in rows.iterator():
                if qid not in evidence:
                    continue
                if (hq_id, lvl_num) in seen_rows:
                    continue
                seen_rows.add((hq_id, lvl_num))
                if cls_name:
                    evidence[qid]['classes'].add(cls_name)
                if lvl_name is None:
                    continue
                target = self._resolve_class_level(
                    lvl_name, lvl_num, overrides, curriculum, ladder_top)
                if target is not None:
                    evidence[qid]['votes'].add((cls_id, target))

        for record in evidence.values():
            record['years'] = Counter(year for _, year in record['votes'])
        return evidence

    def _resolve_class_level(self, name, level_number, overrides, curriculum,
                             ladder_top):
        """The curriculum year a class level means, or None if it means none."""
        key = (name or '').strip().lower()

        if key in overrides:
            target = overrides[key]
            if target in curriculum:
                return target
            self._unresolved_levels[f'{name} (mapped to Year {target}, '
                                    f'which has no Level row)'] += 1
            return None

        if key in KNOWN_UNSUPPORTED:
            self._skipped_levels[name] += 1
            return None

        # A class level that IS already a curriculum level needs no bridging.
        if level_number is not None and level_number in curriculum:
            return level_number

        match = _YEAR_NAME_RE.match(name or '')
        if match:
            target = int(match.group(1))
            if target in curriculum:
                return target
            self._skipped_levels[f'{name} (above the Year {ladder_top} ladder)'] += 1
            return None

        self._unresolved_levels[name] += 1
        return None

    # ── reporting ─────────────────────────────────────────────────────────
    def _report(self, candidates, moves, unresolved, class_years, year):
        self.stdout.write(f'\n  candidates       : {len(candidates)}')

        if moves:
            self.stdout.write(self.style.SUCCESS('\n  Moves, by target year:'))
            for target, qlist in sorted(moves.items()):
                self.stdout.write(f'    -> Year {target}: {len(qlist)} question(s)')
                by_topic = Counter(topic_path(q.topic) for q in qlist)
                for path, n in by_topic.most_common():
                    self.stdout.write(f'         {path:<46} {n:>5}')

        if unresolved:
            self.stdout.write(self.style.WARNING('\n  Left alone:'))
            for reason, qlist in sorted(unresolved.items(),
                                        key=lambda kv: -len(kv[1])):
                self.stdout.write(f'    {len(qlist):>5}  {reason}')

        if self._skipped_levels:
            self.stdout.write(self.style.WARNING(
                '\n  Class levels deliberately skipped (no curriculum year exists):'))
            for name, n in self._skipped_levels.most_common():
                self.stdout.write(f'    {name:<46} seen on {n} question(s)')

        if self._unresolved_levels:
            # Informational, not necessarily a loss: a class can carry several
            # levels ("Year 8" + "Selective Entrance"), and one of them
            # resolving is enough. A question is only stranded when NONE did —
            # that shows up under "Left alone" above.
            self.stdout.write(self.style.WARNING(
                '\n  Class levels not recognised (harmless where another level '
                'on the same class resolved; map with --map "NAME=YEAR"):'))
            for name, n in self._unresolved_levels.most_common():
                self.stdout.write(f'    {name:<46} seen on {n} question(s)')
