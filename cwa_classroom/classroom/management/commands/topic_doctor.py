"""Report what is wrong with the topic tree, and fix the two things safely fixable.

Why
---
Topics are a two-level ``strand > sub-topic`` tree, and every importer creates
rows in it. They disagree about how: the AI import and the JSON upload
``get_or_create`` a strand and a topic under it, while the homework PDF path
matches on the bare name and, when nothing matches, files the question on
``Topic.objects.filter(subject=subject).first()`` instead of creating anything
(``homework/views.py``). That first row is a strand, so the question lands
somewhere the student topic picker never looks: the year page keeps only
strands that HAVE sub-topics, and the quiz filters on one exact topic row.

The result on a live bank is a tree with duplicate names ("Indices" beside
"Indices & Scientific Notation", "Place Value" beside "Place Values"), mirrored
rows ("Measurement > Measurement"), and strands quietly holding questions
nobody can reach through the picker.

This command reports all of that from ``classroom.topic_merge`` — a service
that has been in the tree, complete and unused, and deliberately does NOT guess
which topics mean the same thing. Fuzzy matching ("Fraction" ~ "Fractions")
reads well in a demo and is wrong often enough to be dangerous, and a merge is
not reversible. So the report states facts and a human picks the survivor.

NEAR-DUPLICATE-NAME keeps that rule while catching the twins exact matching
misses. It is normalisation, not similarity: case, punctuation, ``&`` versus
``and``, filler words, plurals and word order are discarded, and two names
either reduce to the same string or they do not. There is no threshold to
tune and no ranking, and a group is still only a question for a human —
"Mass"/"Masses" is probably one topic, "Time"/"Times" may well not be.

``--list`` prints the tree strand by strand. Normalisation cannot see a
duplicate written in different words ("Times Tables" beside "Multiplication
Facts"); somebody reading the sub-topics side by side can.

Actions
-------
``--keep``/``--absorb`` merges topics: everything pointing at the absorbed rows
is re-pointed at the survivor (walking ``_meta.related_objects``, so a topic FK
added by a later app is carried too), their sub-topics are re-parented, then
they are deleted.

``--reparent``/``--under`` moves one row in the tree — the fix for a parentless
topic like "Subtraction" that should sit under "Number". ``--under 0`` promotes
a row to a strand.

Both refuse anything that would move questions out of their subject or make the
tree three levels deep, and both honour ``--dry-run``.

Usage
-----
    python manage.py topic_doctor                          # full report
    python manage.py topic_doctor --list                   # the tree, to read
    python manage.py topic_doctor --subject mathematics    # one subject
    python manage.py topic_doctor --only NEAR-DUPLICATE-NAME
    python manage.py topic_doctor --only TOP-LEVEL-HOLDS-QUESTIONS
    python manage.py topic_doctor --keep 207 --absorb 154 --dry-run
    python manage.py topic_doctor --reparent 70 --under 4 --dry-run
"""
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

TOP_LEVEL_CODE = 'TOP-LEVEL-HOLDS-QUESTIONS'
NEAR_DUPLICATE_CODE = 'NEAR-DUPLICATE-NAME'


class Command(BaseCommand):
    help = ('Report duplicate, empty and unreachable topic rows; merge or '
            're-parent the ones a human has decided on.')

    def add_arguments(self, parser):
        parser.add_argument('--subject', type=str,
                            help='Limit to one subject, by slug or name.')
        parser.add_argument('--only', type=str,
                            help='Show only this finding code, e.g. '
                                 f'{TOP_LEVEL_CODE} or DUPLICATE-NAME.')
        parser.add_argument('--limit', type=int, default=20,
                            help='Rows to list per finding code (0 = all). '
                                 'Counts always cover everything found.')
        parser.add_argument('--keep', type=int,
                            help='Topic id to keep when merging.')
        parser.add_argument('--absorb', type=str,
                            help='Comma-separated topic ids to merge into '
                                 '--keep and then delete.')
        parser.add_argument('--reparent', type=int,
                            help='Topic id to move in the tree.')
        parser.add_argument('--under', type=int,
                            help='New parent topic id for --reparent; 0 '
                                 'promotes the row to a top-level strand.')
        parser.add_argument('--list', action='store_true', dest='list_tree',
                            help='Print the topic tree, strand by strand, and '
                                 'stop. Reading the sub-topics side by side is '
                                 'how a duplicate gets spotted.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what an action would do, write nothing.')

    def handle(self, *args, **opts):
        subject_ids = self._resolve_subject(opts['subject'])

        if opts['keep'] or opts['absorb']:
            if opts['reparent'] is not None:
                raise CommandError('Do one thing at a time: --keep/--absorb or '
                                   '--reparent, not both.')
            return self._merge(opts)
        if opts['reparent'] is not None:
            return self._reparent(opts)
        if opts['list_tree']:
            return self._list(subject_ids)
        return self._report(subject_ids, opts)

    # ── helpers ───────────────────────────────────────────────────────────
    def _resolve_subject(self, raw):
        from classroom.models import Subject

        if not raw:
            return None
        subjects = list(Subject.objects.filter(slug__iexact=raw.strip())
                        or Subject.objects.filter(name__iexact=raw.strip()))
        if not subjects:
            raise CommandError(
                f'No subject matches {raw!r}. Existing: '
                + ', '.join(sorted(s.slug for s in Subject.objects.all())))
        return [s.id for s in subjects]

    def _get_topic(self, topic_id):
        from classroom.models import Topic
        try:
            return Topic.objects.select_related('subject', 'parent').get(pk=topic_id)
        except Topic.DoesNotExist:
            raise CommandError(f'No topic with id {topic_id}.')

    def _path(self, summary):
        return (f"{summary['parent']} > {summary['name']}" if summary['parent']
                else summary['name'])

    # ── report ────────────────────────────────────────────────────────────
    def _report(self, subject_ids, opts):
        from classroom.topic_merge import (near_duplicate_names,
                                           structural_issues,
                                           subject_name_clashes,
                                           top_level_topics_with_questions,
                                           topic_inventory)

        only, limit = (opts['only'] or '').strip().upper(), opts['limit']

        inventory = topic_inventory(subject_ids)
        total_topics = sum(len(s['topics']) for s in inventory)
        total_questions = sum(s['questions'] for s in inventory)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'=== Topic doctor: {total_topics} topic(s) across '
            f'{len(inventory)} subject(s), {total_questions} question(s) ==='))
        for subject in inventory:
            self.stdout.write(f"  {subject['subject']:<24} "
                              f"{len(subject['topics']):>4} topics  "
                              f"{subject['questions']:>6} questions")

        # The finding that motivated this command, and the one the existing
        # service did not have: questions the topic picker cannot reach.
        stranded = top_level_topics_with_questions(subject_ids)
        if stranded and (not only or only == TOP_LEVEL_CODE):
            n = sum(s['questions'] for s in stranded)
            self.stdout.write(self.style.WARNING(
                f'\n[{TOP_LEVEL_CODE}] {len(stranded)} strand(s) hold {n} '
                f'question(s) directly'))
            self.stdout.write(
                '  The year page lists sub-topics only, so these are offered by '
                'no topic quiz —\n  they surface only in level practice. '
                'Move them under a sub-topic, or give the\n  strand one with '
                '--reparent.')
            for s in self._capped(stranded, limit):
                self.stdout.write(
                    f"    [{s['id']:>6}] {s['name']:<40} "
                    f"{s['questions']:>5} questions, {s['subtopics']} sub-topic(s)"
                    + self._year_spread(s['id']))

        issues = structural_issues(subject_ids)
        by_code = defaultdict(list)
        for issue in issues:
            by_code[issue['code']].append(issue)

        if not by_code and not stranded:
            self.stdout.write(self.style.SUCCESS('\nNothing to report.'))
            return

        for code, found in sorted(by_code.items(), key=lambda kv: -len(kv[1])):
            if only and only != code:
                continue
            self.stdout.write(self.style.WARNING(
                f'\n[{code}] {len(found)} finding(s)'))
            for issue in self._capped(found, limit):
                topics = issue['topics']
                self.stdout.write(f"    {issue['detail']}")
                for t in topics:
                    self.stdout.write(
                        f"      [{t['id']:>6}] {self._path(t):<44} "
                        f"{t['questions']:>5} questions, "
                        f"{t['subtopics']} sub-topic(s)"
                        + ('' if t['is_active'] else '  (inactive)'))

        near = near_duplicate_names(subject_ids)
        if near and (not only or only == NEAR_DUPLICATE_CODE):
            n = sum(len(c['members']) for c in near)
            self.stdout.write(self.style.WARNING(
                f'\n[{NEAR_DUPLICATE_CODE}] {len(near)} group(s), {n} topic(s) '
                f'whose names differ only by case, punctuation, filler words, '
                f'plurals or word order'))
            self.stdout.write(
                '  A group is a question, not a verdict: "Mass"/"Masses" is '
                'probably one topic,\n  "Time"/"Times" may well not be. Read '
                'the rows, then merge the ones that agree.')
            for cluster in self._capped(near, limit):
                self.stdout.write(
                    f"    {cluster['subject']}: " + ' | '.join(cluster['names']))
                for m in cluster['members']:
                    self.stdout.write(
                        f"      [{m['id']:>6}] {self._path(m):<44} "
                        f"{m['questions']:>5} questions, "
                        f"{m['subtopics']} sub-topic(s)"
                        + ('' if m['is_active'] else '  (inactive)'))

        clashes = subject_name_clashes()
        if clashes and not only:
            self.stdout.write(self.style.WARNING(
                f'\n[DUPLICATE-SUBJECT] {len(clashes)} name(s) used by more '
                f'than one subject'))
            for members in clashes:
                for m in members:
                    self.stdout.write(
                        f"    [{m['id']:>6}] {m['name']:<24} slug={m['slug']:<20} "
                        f"school={m['school'] or 'GLOBAL':<18} "
                        f"{m['topics']:>4} topics")

        self.stdout.write(
            '\nNothing was changed. Decide a survivor, then:\n'
            '  python manage.py topic_doctor --keep <id> --absorb <id>[,<id>] --dry-run\n'
            '  python manage.py topic_doctor --reparent <id> --under <parent id> --dry-run')

    def _list(self, subject_ids):
        """The tree as a human reads it: strand, then its sub-topics indented.

        The findings above name duplicates the normalisation can see. This is
        for the ones it cannot — a name that means the same thing in different
        words is only visible to somebody reading the list.
        """
        from classroom.topic_merge import normalised_name, topic_inventory

        inventory = topic_inventory(subject_ids)
        if not inventory:
            self.stdout.write(self.style.WARNING('No topics.'))
            return

        for subject in inventory:
            topics = subject['topics']
            strands = [t for t in topics if not t['parent_id']]
            children = defaultdict(list)
            for t in topics:
                if t['parent_id']:
                    children[t['parent_id']].append(t)

            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n=== {subject['subject']} — {len(topics)} topic(s), "
                f"{subject['questions']} question(s) ==="))
            for strand in sorted(strands, key=lambda t: (t['name'] or '').lower()):
                self.stdout.write(self._list_row(strand, indent=''))
                for child in sorted(children.pop(strand['id'], []),
                                    key=lambda t: (t['name'] or '').lower()):
                    self.stdout.write(self._list_row(child, indent='    '))

            # Rows left over because their parent is not a strand of this
            # subject. Printing them nowhere would hide them from the list, and
            # printing them straight after the last strand would read as its
            # children, so they get a heading of their own.
            orphans = [t for rows in children.values() for t in rows]
            if orphans:
                self.stdout.write(self.style.WARNING(
                    '  -- under no strand of this subject --'))
            for orphan in sorted(orphans, key=lambda t: (t['name'] or '').lower()):
                self.stdout.write(self._list_row(orphan, indent='    ')
                                  + f'  ({self._why_orphaned(orphan)})')

        self.stdout.write(
            '\nSpotted two rows that mean the same thing?\n'
            '  python manage.py topic_doctor --keep <id> --absorb <id>[,<id>] --dry-run')

    def _why_orphaned(self, summary):
        """Say which of the two reasons this is — they need different fixes.

        A parent in another subject is a mis-filed row. A parent that is itself
        a sub-topic is a THREE-LEVEL-TOPIC: the parent is right here, one level
        too deep. Printing one guess for both sends a reader looking in the
        wrong subject.
        """
        from classroom.models import Topic

        parent = Topic.objects.select_related('subject', 'parent').filter(
            pk=summary['parent_id']).first()
        if parent is None:
            return 'parent row is gone'
        if parent.subject_id != summary['subject_id']:
            return (f'parent {parent.name!r} belongs to '
                    f'{parent.subject.name if parent.subject_id else "no subject"}')
        return (f'parent {parent.name!r} [{parent.id}] is itself a sub-topic '
                f'of {parent.parent.name!r} — three levels deep')

    def _list_row(self, summary, indent):
        return (f"{indent}[{summary['id']:>6}] {summary['name']:<44} "
                f"{summary['questions']:>5} questions"
                + ('' if summary['is_active'] else '  (inactive)'))

    def _capped(self, rows, limit):
        if limit and len(rows) > limit:
            shown = rows[:limit]
            self.stdout.write(f'    (showing {limit} of {len(rows)}; '
                              '--limit 0 for all)')
            return shown
        return rows

    def _year_spread(self, topic_id):
        """Which years this topic's questions sit at — where to move them to."""
        from maths.models import Question
        years = Counter(
            n for n in Question.objects.filter(topic_id=topic_id)
            .values_list('level__level_number', flat=True) if n is not None)
        if not years:
            return ''
        return '  years: ' + ','.join(f'Y{y}:{n}' for y, n in sorted(years.items()))

    # ── merge ─────────────────────────────────────────────────────────────
    def _merge(self, opts):
        from classroom.topic_merge import merge_topics, topic_summary, validate_merge

        if not opts['keep'] or not opts['absorb']:
            raise CommandError('A merge needs both --keep <id> and --absorb <id>[,<id>].')
        keep = self._get_topic(opts['keep'])
        try:
            absorb_ids = [int(part) for part in opts['absorb'].split(',') if part.strip()]
        except ValueError:
            raise CommandError(f"--absorb expects comma-separated ids, got {opts['absorb']!r}.")
        if not absorb_ids:
            raise CommandError('--absorb listed no ids.')
        absorbed = [self._get_topic(i) for i in absorb_ids]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'=== Merge into [{keep.id}] {keep}'
            f'{"  [DRY RUN]" if opts["dry_run"] else ""} ==='))
        for topic in absorbed:
            ok, err = validate_merge(keep, topic)
            summary = topic_summary(topic)
            self.stdout.write(
                f"  [{topic.id:>6}] {self._path(summary):<44} "
                f"{summary['questions']:>5} questions, "
                f"{summary['subtopics']} sub-topic(s)")
            if not ok:
                raise CommandError(f'Refusing: {err}')

        with transaction.atomic():
            summary = merge_topics(keep, absorbed)
            if opts['dry_run']:
                transaction.set_rollback(True)

        verb = 'Would re-point' if opts['dry_run'] else 'Re-pointed'
        self.stdout.write(self.style.SUCCESS(f'\n{verb}:'))
        for label, n in sorted(summary['repointed'].items()):
            self.stdout.write(f'    {label:<40} {n:>5}')
        for label, n in sorted(summary['skipped_collisions'].items()):
            self.stdout.write(self.style.WARNING(
                f'    {label:<40} {n:>5}  (survivor already had an equivalent row)'))
        for label, n in sorted(summary.get('rescued', {}).items()):
            self.stdout.write(f'    {label:<40} {n:>5}  '
                              f"(dependents moved off a colliding row)")
        for label, n in sorted(summary.get('dropped_dependents', {}).items()):
            self.stdout.write(self.style.WARNING(
                f'    {label:<40} {n:>5}  '
                f"(dependent clashed too — the survivor's was kept)"))
        for label, n in sorted(summary.get('carried', {}).items()):
            self.stdout.write(f'    {label:<40} {n:>5}  (link carried to the survivor)')
        if summary['reparented']:
            self.stdout.write(f"    sub-topics re-parented{'':<18} "
                              f"{summary['reparented']:>5}")
        if summary.get('statistics_refreshed'):
            self.stdout.write(
                f"    topic-level statistics recomputed{'':<7} "
                f"{summary['statistics_refreshed']:>5}")
        self.stdout.write(self.style.SUCCESS(
            f"\n{'Would delete' if opts['dry_run'] else 'Deleted'} "
            f"{len(summary['absorbed'])} topic(s): "
            + ', '.join(f"[{a['id']}] {a['name']}" for a in summary['absorbed'])
            + ('  [DRY RUN — rolled back]' if opts['dry_run'] else '')))

    # ── reparent ──────────────────────────────────────────────────────────
    def _reparent(self, opts):
        from classroom.topic_merge import topic_summary, validate_reparent

        if opts['under'] is None:
            raise CommandError('--reparent needs --under <parent id> '
                               '(or --under 0 to promote it to a strand).')
        topic = self._get_topic(opts['reparent'])
        parent = None if opts['under'] == 0 else self._get_topic(opts['under'])

        was_id = topic.parent_id
        was = topic.parent.name if topic.parent_id else '(top level)'
        now = parent.name if parent else '(top level)'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'=== Re-parent [{topic.id}] {topic.name}: {was} -> {now}'
            f'{"  [DRY RUN]" if opts["dry_run"] else ""} ==='))
        summary = topic_summary(topic)
        self.stdout.write(f"  {summary['questions']} question(s), "
                          f"{summary['subtopics']} sub-topic(s)")

        ok, err = validate_reparent(topic, parent)
        if not ok:
            raise CommandError(f'Refusing: {err}')

        with transaction.atomic():
            topic.parent = parent
            topic.save(update_fields=['parent'])
            if opts['dry_run']:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"\n{'Would move' if opts['dry_run'] else 'Moved'} "
            f'[{topic.id}] {topic.name} under {now}'
            + ('  [DRY RUN — rolled back]' if opts['dry_run'] else '')))
        if not opts['dry_run']:
            self.stdout.write(
                f'  to undo: python manage.py topic_doctor --reparent {topic.id} '
                f'--under {was_id if was_id else 0}')
