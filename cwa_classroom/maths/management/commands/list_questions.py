"""List the maths questions that actually exist for a year + topic.

Written for the question the bank cannot answer from the UI: *"the Year 4
Number Patterns quiz only ever shows me one question — is that all there is?"*

The student-facing topic quiz filters on ONE exact topic row
(``Question.objects.filter(topic=topic, level=level)`` in
``quiz.views.TopicQuizView``), while topics are stored as a
``strand › sub-topic`` tree and matched on ``(name, parent)`` by
``import_global_questions``. So the same human name can legitimately exist as
several ``Topic`` rows — "Number and Algebra › Number Patterns" and
"Patterns and Relationships › Number Patterns" are different rows — and a bank
holding 30 questions can still hand a student one, because the other 29 hang
off a sibling row, off the parent strand, or off another year.

This command therefore does NOT trust a single topic row: it matches every
topic whose own name, parent name or slug matches, then reports where the
questions really sit — per topic row, per year, per scope (global vs school) —
before listing them. It also flags the two ways a question goes missing from
the picker even though it is in the bank:

  * its topic row is not linked to that year (``Topic.levels``), so the year's
    topic list never offers it;
  * its topic row is a top-level strand, and the student home page only lists
    sub-topics (rows with a parent).

Read-only — it never writes.

Usage
-----
    python manage.py list_questions --year 4 --topic "number patterns"
    python manage.py list_questions --year 4 --topic "number patterns" --scope global
    python manage.py list_questions --topic "number patterns" --counts-only
    python manage.py list_questions --year 4 --school 4 --format csv -o y4.csv
"""
import csv
import json
import sys
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError

from maths.topic_lookup import matching_topics, topic_path

SCOPE_ALL = 'all'
SCOPE_GLOBAL = 'global'
SCOPE_SCHOOL = 'school'

CSV_FIELDS = (
    'id', 'level_number', 'level', 'scope', 'school', 'topic_id', 'topic_path',
    'question_type', 'difficulty', 'points', 'answer_count', 'correct_answers',
    'has_image', 'question_text',
)


def _scope_of(question):
    return SCOPE_GLOBAL if question.school_id is None else SCOPE_SCHOOL


def _one_line(text, width=70):
    flat = ' '.join((text or '').split())
    return flat if len(flat) <= width else flat[:width - 1] + '…'


class Command(BaseCommand):
    help = ('List maths questions for a year and/or topic, showing how they '
            'are split across topic rows, years and schools.')

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int,
                            help='Year level (Level.level_number), e.g. 4. '
                                 'Omit to search every year.')
        parser.add_argument('--topic', type=str,
                            help='Topic name — matched case-insensitively as a '
                                 'substring of the topic name, its parent '
                                 "strand's name, or its slug.")
        parser.add_argument('--exact-topic', action='store_true',
                            help='Match --topic as a full name instead of a substring.')
        parser.add_argument('--scope', choices=[SCOPE_ALL, SCOPE_GLOBAL, SCOPE_SCHOOL],
                            default=SCOPE_ALL,
                            help='global = the shared bank (school IS NULL); '
                                 'school = school-private questions; default all.')
        parser.add_argument('--school', type=str,
                            help='Limit to one school, by id or slug.')
        parser.add_argument('--type', dest='question_type', type=str,
                            help='Filter by question_type, e.g. multiple_choice.')
        parser.add_argument('--counts-only', action='store_true',
                            help='Print the breakdown but not the question rows.')
        parser.add_argument('--limit', type=int, default=0,
                            help='Print at most N question rows (0 = no limit). '
                                 'The counts always cover everything that matched.')
        parser.add_argument('--format', dest='fmt', choices=['text', 'csv', 'json'],
                            default='text')
        parser.add_argument('-o', '--output', type=str,
                            help='Write to this file instead of stdout '
                                 '(csv/json).')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        from classroom.models import Level, School
        from maths.models import Question

        year = opts['year']
        topic_term = (opts['topic'] or '').strip()
        fmt = opts['fmt']

        level = None
        if year is not None:
            level = Level.objects.filter(level_number=year).first()
            if level is None:
                raise CommandError(
                    f'No Level with level_number={year}. Existing years: '
                    + ', '.join(str(n) for n in Level.objects
                                .filter(level_number__lt=100)
                                .values_list('level_number', flat=True)))

        school = None
        if opts['school']:
            school = self._resolve_school(School, opts['school'])

        # ── the topic rows this name resolves to ─────────────────────────
        topics = []
        if topic_term:
            topics = matching_topics(topic_term, exact=opts['exact_topic'])
            if not topics:
                # A silent empty list here reads as "the bank has nothing",
                # when the truth is the name never existed.
                raise CommandError(
                    f'No topic matches {topic_term!r}. Try a shorter fragment, '
                    'or run without --topic to see what is there.')

        # ── the questions ────────────────────────────────────────────────
        qs = (Question.objects
              .select_related('level', 'topic', 'topic__parent', 'school')
              .prefetch_related('answers')
              .order_by('level__level_number', 'topic__name', 'id'))
        if topics:
            qs = qs.filter(topic__in=topics)
        if level is not None:
            qs = qs.filter(level=level)
        if school is not None:
            qs = qs.filter(school=school)
        elif opts['scope'] == SCOPE_GLOBAL:
            qs = qs.filter(school__isnull=True)
        elif opts['scope'] == SCOPE_SCHOOL:
            qs = qs.filter(school__isnull=False)
        if opts['question_type']:
            qs = qs.filter(question_type=opts['question_type'])

        questions = list(qs)

        # Where the same topic names have questions at OTHER years — the usual
        # reason a year looks empty when the bank is not.
        other_years = Counter()
        if topics and level is not None:
            spread = (Question.objects.filter(topic__in=topics)
                      .exclude(level=level)
                      .values_list('level__level_number', flat=True))
            other_years.update(n for n in spread if n is not None)

        payload = self._build_payload(
            questions, topics, level, school, opts, other_years)

        if fmt == 'text':
            self._render_text(payload, opts)
        elif fmt == 'csv':
            self._render_csv(payload, opts)
        else:
            self._render_json(payload, opts)

    # ------------------------------------------------------------------
    def _resolve_school(self, School, raw):
        school = None
        if raw.isdigit():
            school = School.objects.filter(pk=int(raw)).first()
        if school is None:
            school = School.objects.filter(slug=raw).first()
        if school is None:
            raise CommandError(f'No school with id or slug {raw!r}.')
        return school

    def _build_payload(self, questions, topics, level, school, opts, other_years):
        rows = []
        for q in questions:
            answers = list(q.answers.all())
            rows.append({
                'id': q.id,
                'level_number': q.level.level_number if q.level else None,
                'level': q.level.display_name if q.level else '',
                'scope': _scope_of(q),
                'school': q.school.name if q.school else '',
                'topic_id': q.topic_id,
                'topic_path': topic_path(q.topic),
                'question_type': q.question_type,
                'difficulty': q.difficulty,
                'points': q.points,
                'answer_count': len(answers),
                'correct_answers': sum(1 for a in answers if a.is_correct),
                'has_image': bool(q.image),
                'question_text': ' '.join((q.question_text or '').split()),
            })

        # Breakdown per (topic row, year, scope) — this is what explains a quiz
        # that only ever offers one question.
        breakdown = defaultdict(int)
        for q in questions:
            breakdown[(q.topic_id, topic_path(q.topic),
                       q.level.level_number if q.level else None,
                       _scope_of(q))] += 1

        # Per-topic-row health: is the row reachable from the year's picker?
        topic_info = []
        for t in topics:
            linked_years = sorted(t.levels.values_list('level_number', flat=True))
            topic_info.append({
                'id': t.id,
                'path': topic_path(t),
                'is_strand': t.parent_id is None,
                'is_active': t.is_active,
                'linked_years': linked_years,
                'linked_to_year': (level.level_number in linked_years
                                   if level is not None else None),
            })

        return {
            'filters': {
                'year': level.level_number if level else None,
                'topic': opts['topic'] or None,
                'exact_topic': opts['exact_topic'],
                'scope': opts['scope'],
                'school': school.name if school else None,
                'question_type': opts['question_type'],
            },
            'topics': topic_info,
            'total': len(rows),
            'breakdown': [
                {'topic_id': tid, 'topic_path': tpath, 'year': yr,
                 'scope': scope, 'count': n}
                for (tid, tpath, yr, scope), n in sorted(
                    breakdown.items(), key=lambda kv: (-kv[1], str(kv[0][1])))
            ],
            'other_years': dict(sorted(other_years.items())),
            'questions': rows,
        }

    # ── renderers ─────────────────────────────────────────────────────────
    def _render_text(self, payload, opts):
        f = payload['filters']
        head = f"Year {f['year']}" if f['year'] else 'All years'
        if f['topic']:
            head += f" · topic {'=' if f['exact_topic'] else '~'} {f['topic']!r}"
        head += f" · scope: {f['school'] or f['scope']}"
        if f['question_type']:
            head += f" · type: {f['question_type']}"
        self.stdout.write(self.style.MIGRATE_HEADING(head))

        if payload['topics']:
            self.stdout.write(f"\nMatched {len(payload['topics'])} topic row(s):")
            for t in payload['topics']:
                notes = []
                if t['linked_to_year'] is False:
                    notes.append(f"NOT linked to Year {f['year']} — hidden from "
                                 "that year's topic list")
                if t['is_strand']:
                    notes.append('top-level strand — the student topic list '
                                 'only offers sub-topics')
                if not t['is_active']:
                    notes.append('inactive')
                suffix = f"  [{'; '.join(notes)}]" if notes else ''
                years = ','.join(f"Y{y}" for y in t['linked_years']) or '—'
                self.stdout.write(f"  [{t['id']:>6}] {t['path']}  (years: {years}){suffix}")

        self.stdout.write(f"\n{payload['total']} question(s) matched.")
        if payload['breakdown']:
            self.stdout.write('  split by topic row / year / scope:')
            for b in payload['breakdown']:
                self.stdout.write(
                    f"    [{str(b['topic_id']):>6}] {b['topic_path']:<46} "
                    f"Y{b['year']:<4} {b['scope']:<7} {b['count']:>5}")

        if payload['other_years']:
            spread = ', '.join(f"Y{y}: {n}" for y, n in payload['other_years'].items())
            self.stdout.write(self.style.WARNING(
                f"\nSame topic(s) also hold questions at other years — {spread}"))

        if payload['total'] == 0:
            self.stdout.write(self.style.WARNING(
                '\nNothing matched. The topic rows above exist, but carry no '
                'question for these filters — widen with --scope all, drop '
                '--year, or check the years listed beside each topic row.'))
            return

        if opts['counts_only']:
            return

        rows = payload['questions']
        shown = rows[:opts['limit']] if opts['limit'] else rows
        self.stdout.write(
            f"\n{'id':>7}  {'yr':<4} {'scope':<7} {'type':<18} {'d':<2} "
            f"{'topic':<34} question")
        for r in shown:
            self.stdout.write(
                f"{r['id']:>7}  Y{str(r['level_number']):<3} {r['scope']:<7} "
                f"{r['question_type']:<18} {r['difficulty']:<2} "
                f"{_one_line(r['topic_path'], 34):<34} "
                f"{_one_line(r['question_text'])}")
        if len(shown) < len(rows):
            self.stdout.write(self.style.WARNING(
                f"… {len(rows) - len(shown)} more row(s) not shown (--limit "
                f"{opts['limit']}). Raise or drop --limit to see them all."))

    def _render_csv(self, payload, opts):
        handle = (open(opts['output'], 'w', newline='', encoding='utf-8')
                  if opts['output'] else sys.stdout)
        try:
            writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
            writer.writeheader()
            for row in payload['questions']:
                writer.writerow({k: row[k] for k in CSV_FIELDS})
        finally:
            if opts['output']:
                handle.close()
                self.stdout.write(self.style.SUCCESS(
                    f"Wrote {payload['total']} row(s) to {opts['output']}"))

    def _render_json(self, payload, opts):
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if opts['output']:
            with open(opts['output'], 'w', encoding='utf-8') as fh:
                fh.write(text + '\n')
            self.stdout.write(self.style.SUCCESS(
                f"Wrote {payload['total']} row(s) to {opts['output']}"))
        else:
            self.stdout.write(text)
