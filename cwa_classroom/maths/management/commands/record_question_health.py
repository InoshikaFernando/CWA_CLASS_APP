"""
Record a QuestionHealthSnapshot for the super-admin dashboard.

Runs the same checks as ``verify_question_answers`` but, instead of printing
and exiting non-zero, persists the result so health can be read as a trend
rather than a one-off number. Mirrors ``record_ops_metrics`` → ops dashboard.

Read-only with respect to question content; the only row it writes is the
snapshot itself.

Usage (cron, daily):
    python manage.py record_question_health
    python manage.py record_question_health --level 7 --topic 75
    python manage.py record_question_health --max-flagged 500
"""
from collections import Counter

from django.core.management.base import BaseCommand

from maths.answer_verification import verify_question
from maths.management.commands.verify_question_answers import ADVISORY_CODES


class Command(BaseCommand):
    help = 'Record a question-bank health snapshot for the admin dashboard.'

    def add_arguments(self, parser):
        parser.add_argument('--level', type=int, default=None)
        parser.add_argument('--topic', type=int, default=None)
        parser.add_argument(
            '--max-flagged', type=int, default=300,
            help='Cap the drill-down list stored on the snapshot. The counts '
                 'are always complete; only the detail list is capped.')
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **options):
        from classroom.models import Topic
        from maths.models import Question, QuestionHealthSnapshot

        questions = (
            Question.objects
            .filter(question_type__in=(Question.MULTIPLE_CHOICE,
                                       Question.TRUE_FALSE))
            .select_related('topic', 'level')
            .prefetch_related('answers')
        )
        if options['level'] is not None:
            questions = questions.filter(level__level_number=options['level'])
        if options['topic'] is not None:
            questions = questions.filter(topic_id=options['topic'])

        choice_total = 0
        verified = 0
        blocking = 0
        advisory = 0
        codes = Counter()
        flagged = []
        max_flagged = options['max_flagged']

        for question in questions.iterator(chunk_size=200):
            choice_total += 1
            issues, was_verified = verify_question(question)
            if was_verified:
                verified += 1
            if not issues:
                continue

            issue_codes = [issue.code for issue in issues]
            codes.update(issue_codes)
            if any(code not in ADVISORY_CODES for code in issue_codes):
                blocking += 1
            else:
                advisory += 1

            # The counts above are complete; only this drill-down list is
            # capped, so a very broken bank cannot bloat the row.
            if len(flagged) < max_flagged:
                flagged.append({
                    'id': question.id,
                    'codes': sorted(set(issue_codes)),
                    'detail': issues[0].detail[:200],
                    'text': (question.question_text or '')[:120],
                    'level': (question.level.level_number
                              if question.level_id else None),
                    'topic': (question.topic.name
                              if question.topic_id else None),
                })

        snapshot = QuestionHealthSnapshot.objects.create(
            level_number=options['level'],
            topic=Topic.objects.filter(id=options['topic']).first(),
            total_questions=Question.objects.count(),
            choice_questions=choice_total,
            arithmetic_verified=verified,
            unverifiable=choice_total - verified,
            questions_blocking=blocking,
            questions_advisory=advisory,
            issue_counts=dict(codes),
            flagged_questions=flagged,
        )

        if options['quiet']:
            return

        self.stdout.write(
            f'Snapshot #{snapshot.id}: {choice_total} choice question(s), '
            f'{blocking} blocking, {advisory} advisory, '
            f'{snapshot.health_percent}% healthy, '
            f'{snapshot.coverage_percent}% machine-verified')
        if blocking + advisory > len(flagged):
            # Say so rather than let a truncated list read as the whole story.
            self.stdout.write(self.style.WARNING(
                f'  drill-down list capped at {len(flagged)} of '
                f'{blocking + advisory} flagged questions (--max-flagged)'))
