"""
List every (year level, topic) pair that has quiz questions, as JSON.

The weekly content sweep drives a browser over the live site, but a student
only ever sees their own level, so the quiz pages are not discoverable by
crawling. This command supplies the target list from the database side; the
browser job consumes it and visits each one.

Read-only. Prints a JSON array to stdout and nothing else, so it can be piped
straight into a workflow step.

    [{"level": 7, "topic_id": 75, "topic": "Fractions", "questions": 57,
      "url": "/maths/level/7/topic/75/quiz/"}, ...]

Usage:
    python manage.py list_quiz_targets
    python manage.py list_quiz_targets --level 7
    python manage.py list_quiz_targets --min-questions 5
"""
import json

from django.core.management.base import BaseCommand
from django.db.models import Count


class Command(BaseCommand):
    help = 'List every level/topic pair that has quiz questions, as JSON.'

    def add_arguments(self, parser):
        parser.add_argument('--level', type=int, default=None,
                            help='Restrict to one Level.level_number.')
        parser.add_argument('--subject', default='maths',
                            help='Subject slug used in the quiz URL.')
        parser.add_argument('--min-questions', type=int, default=1,
                            help='Skip pairs with fewer questions than this.')

    def handle(self, *args, **options):
        from maths.models import Question

        rows = (
            Question.objects
            .filter(topic__isnull=False, level__isnull=False)
            .values('level__level_number', 'topic_id', 'topic__name')
            .annotate(questions=Count('id'))
            .order_by('level__level_number', 'topic__name')
        )
        if options['level'] is not None:
            rows = rows.filter(level__level_number=options['level'])

        subject = options['subject']
        targets = [
            {
                'level': row['level__level_number'],
                'topic_id': row['topic_id'],
                'topic': row['topic__name'],
                'questions': row['questions'],
                'url': (f"/{subject}/level/{row['level__level_number']}"
                        f"/topic/{row['topic_id']}/quiz/"),
            }
            for row in rows
            if row['questions'] >= options['min_questions']
        ]
        # stdout must stay pure JSON — the workflow pipes it into a file.
        self.stdout.write(json.dumps(targets, indent=None))
