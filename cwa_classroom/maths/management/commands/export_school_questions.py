"""Export one school's maths questions to a rich JSON grouped by year / title /
sub-title — the live-DB twin of ``scripts/export_school_questions_from_dump.py``.

The output is consumed by ``manage.py import_global_questions`` to promote the
questions into the global bank (school=NULL).

``--year`` / ``--topic`` narrow the export to one slice of the school's bank.
Promoting a whole school in one go is a large, hard-to-review content change;
the filters let a promotion be scoped to the gap that was actually found (e.g.
"Year 4 Number Patterns is empty in global").

Usage
-----
    python manage.py export_school_questions --school 4 -o mhm.json
    python manage.py export_school_questions --school-slug maths-hub-melbourne-pty-ltd -o mhm.json
    python manage.py export_school_questions --school 4 --year 4 \
        --topic "Number Patterns" -o mhm_y4_patterns.json
"""
import json
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from maths.topic_lookup import matching_topics, topic_path

SCALAR_FIELDS = (
    'question_text', 'question_type', 'difficulty', 'points', 'explanation',
    'validation_type', 'answer_format', 'grading_rubric',
    'dividend', 'divisor', 'target_number', 'operands', 'operator',
    'numeric_answer', 'answer_tolerance', 'answer_unit', 'grid_spec', 'shape_spec',
    # Newer self-drawing types. Every type-specific column on maths.Question
    # belongs in this tuple — one left out is silently dropped, and the import's
    # dedup then SKIPS the half-built global copy on a re-run instead of
    # repairing it. Add the column here whenever a question type gains one.
    'plane_spec', 'graph_spec', 'number_line_spec', 'table_spec', 'blank_spec',
)


def _jsonable(v):
    return float(v) if isinstance(v, Decimal) else v


class Command(BaseCommand):
    help = "Export a school's maths questions to JSON grouped by year/title/subtitle."

    def add_arguments(self, parser):
        parser.add_argument('--school', type=int, help='School id to export.')
        parser.add_argument('--school-slug', type=str, help='School slug to export.')
        parser.add_argument('-o', '--output', required=True, help='Output JSON path.')
        parser.add_argument('--year', type=int,
                            help='Only export this year level (Level.level_number).')
        parser.add_argument('--topic', type=str,
                            help='Only export this topic — matched case-insensitively '
                                 "against the topic name, its parent strand's name, "
                                 'or its slug, so a strand pulls in its sub-topics.')
        parser.add_argument('--exact-topic', action='store_true',
                            help='Match --topic as a full name instead of a substring.')

    def handle(self, *args, **opts):
        from classroom.models import School
        from maths.models import Question

        if not opts['school'] and not opts['school_slug']:
            raise CommandError('Provide --school <id> or --school-slug <slug>.')

        try:
            school = (School.objects.get(pk=opts['school']) if opts['school']
                      else School.objects.get(slug=opts['school_slug']))
        except School.DoesNotExist:
            raise CommandError('School not found.')

        qs = (
            Question.objects.filter(school=school)
            .select_related('level', 'topic', 'topic__parent')
            .prefetch_related('answers')
        )

        topics = []
        if opts['topic']:
            topics = matching_topics(opts['topic'], exact=opts['exact_topic'])
            # An unmatched name would otherwise export zero questions and read
            # as "the school has none of these", which is a different fact.
            if not topics:
                raise CommandError(f"No topic matches {opts['topic']!r}.")
            qs = qs.filter(topic__in=topics)
            self.stdout.write('Topic filter matches %d topic row(s): %s' % (
                len(topics), '; '.join(topic_path(t) for t in topics)))
        if opts['year'] is not None:
            qs = qs.filter(level__level_number=opts['year'])

        if not qs.exists():
            raise CommandError(
                f"No questions for school '{school.name}'"
                + (f" at year {opts['year']}" if opts['year'] is not None else '')
                + (f" on topic {opts['topic']!r}" if opts['topic'] else '')
                + ' — nothing to export.')

        grouped = defaultdict(list)
        for q in qs:
            level = q.level
            level_number = level.level_number if level else None
            year = level.display_name if level else None
            if q.topic and q.topic.parent_id:
                title, subtitle = q.topic.parent.name, q.topic.name
            elif q.topic:
                # No sub-topic: mirror the topic name as its own sub-title so the
                # global hierarchy is always title › sub-title.
                title, subtitle = q.topic.name, q.topic.name
            else:
                title, subtitle = '(no topic)', ''

            rec = {'source_id': q.id}
            rec.update({f: _jsonable(getattr(q, f)) for f in SCALAR_FIELDS})
            rec['image'] = str(q.image) if q.image else None
            rec['video'] = str(q.video) if q.video else None
            rec['answers'] = [
                {
                    'answer_text': a.answer_text or '',
                    'is_correct': bool(a.is_correct),
                    'order': a.order or 0,
                    'answer_image': str(a.answer_image) if a.answer_image else None,
                }
                for a in sorted(q.answers.all(), key=lambda a: (a.order or 0, a.id))
            ]
            grouped[(level_number, year, title, subtitle)].append(rec)

        groups = []
        for (level_number, year, title, subtitle) in sorted(
                grouped, key=lambda k: (k[0] or 0, k[2] or '', k[3] or '')):
            groups.append({
                'year': year, 'level_number': level_number,
                'title': title, 'subtitle': subtitle,
                'questions': grouped[(level_number, year, title, subtitle)],
            })

        out = {
            'meta': {
                'source_school_id': school.id,
                'source_school': school.name,
                'generated_from': 'live-db',
                'question_count': qs.count(),
                'group_count': len(groups),
                'filter_year': opts['year'],
                'filter_topic': opts['topic'] or None,
            },
            'groups': groups,
        }
        with open(opts['output'], 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS(
            f"Exported {out['meta']['question_count']} questions in "
            f"{len(groups)} groups -> {opts['output']}"))
