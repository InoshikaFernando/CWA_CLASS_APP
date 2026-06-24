"""Export one school's maths questions to a rich JSON grouped by year / title /
sub-title — the live-DB twin of ``scripts/export_school_questions_from_dump.py``.

The output is consumed by ``manage.py import_global_questions`` to promote the
questions into the global bank (school=NULL).

Usage
-----
    python manage.py export_school_questions --school 4 -o mhm.json
    python manage.py export_school_questions --school-slug maths-hub-melbourne-pty-ltd -o mhm.json
"""
import json
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

SCALAR_FIELDS = (
    'question_text', 'question_type', 'difficulty', 'points', 'explanation',
    'validation_type', 'answer_format', 'grading_rubric',
    'dividend', 'divisor', 'target_number', 'operands', 'operator',
    'numeric_answer', 'answer_tolerance', 'answer_unit', 'grid_spec', 'shape_spec',
)


def _jsonable(v):
    return float(v) if isinstance(v, Decimal) else v


class Command(BaseCommand):
    help = "Export a school's maths questions to JSON grouped by year/title/subtitle."

    def add_arguments(self, parser):
        parser.add_argument('--school', type=int, help='School id to export.')
        parser.add_argument('--school-slug', type=str, help='School slug to export.')
        parser.add_argument('-o', '--output', required=True, help='Output JSON path.')

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
            },
            'groups': groups,
        }
        with open(opts['output'], 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS(
            f"Exported {out['meta']['question_count']} questions in "
            f"{len(groups)} groups -> {opts['output']}"))
