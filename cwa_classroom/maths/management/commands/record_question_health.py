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

from maths.answer_verification import (
    Issue, verify_question, verify_question_figure,
    verify_typed_answer_question)
from maths.management.commands.verify_question_answers import ADVISORY_CODES
from maths.question_review import USER_REPORTED, ReviewState, report_detail


def _parent_topic_name(question):
    """The strand a question sits under — its topic's parent, or the topic."""
    topic = question.topic if question.topic_id else None
    if topic is None:
        return None
    return topic.parent.name if topic.parent_id else topic.name


def _subtopic_name(question):
    """The question's own topic, but only when it is a subtopic."""
    topic = question.topic if question.topic_id else None
    if topic is None or not topic.parent_id:
        return None
    return topic.name


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
            .select_related('topic', 'topic__parent', 'level')
            .prefetch_related('answers')
        )
        # Typed answers carry their own checks (CPP-378) and were previously
        # not measured at all, so the dashboard reported a bank far healthier
        # than it was.
        typed = (
            Question.objects
            .exclude(question_type__in=(Question.MULTIPLE_CHOICE,
                                        Question.TRUE_FALSE))
            .select_related('topic', 'topic__parent', 'level')
            .prefetch_related('answers')
        )
        if options['level'] is not None:
            questions = questions.filter(level__level_number=options['level'])
            typed = typed.filter(level__level_number=options['level'])
        if options['topic'] is not None:
            questions = questions.filter(topic_id=options['topic'])
            typed = typed.filter(topic_id=options['topic'])

        choice_total = 0
        verified = 0
        blocking = 0
        advisory = 0
        cleared_total = 0
        codes = Counter()
        flagged = []
        max_flagged = options['max_flagged']

        # Reports and human verdicts, loaded once for the whole run (CPP-398).
        # Both tables only grow when a person clicks something, so they stay
        # small next to the bank and cost two queries rather than two per row.
        state = ReviewState()

        for question in questions.iterator(chunk_size=200):
            choice_total += 1
            issues, was_verified = verify_question(question)
            # The figure check applies to every type: a question whose picture
            # never reaches the page cannot be answered however well-formed its
            # options are (CPP-406).
            issues = issues + verify_question_figure(question)
            if was_verified:
                verified += 1
            reports = state.open_reports(question)
            if reports:
                # A question somebody objected to is unhealthy even when every
                # deterministic check passes it — the verifier having nothing
                # to say is exactly when the complaint is worth reading.
                issues = list(issues) + [
                    Issue(USER_REPORTED, report_detail(reports))]
            if not issues:
                continue
            if state.is_cleared(question):
                # A person looked and passed it. Counted so the run says how
                # much it is not reporting and on whose authority, rather than
                # letting a suppressed question read as a sound one.
                cleared_total += 1
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
                    # Match the Global Questions picker: TOPIC is the parent
                    # ("Number"), SUBTOPIC is the question's own topic
                    # ("Addition"). Showing only the latter left the reader
                    # guessing which strand a flagged question belongs to.
                    'topic': _parent_topic_name(question),
                    'subtopic': _subtopic_name(question),
                    # Which editor the dashboard can link to: the Global
                    # Questions modal only serves school-less questions, so a
                    # school-scoped one has to go elsewhere or it 404s.
                    'is_global': question.school_id is None,
                })

        typed_total = 0
        for question in typed.iterator(chunk_size=200):
            typed_total += 1
            issues = (verify_typed_answer_question(question)
                      + verify_question_figure(question))
            reports = state.open_reports(question)
            if reports:
                issues = list(issues) + [
                    Issue(USER_REPORTED, report_detail(reports))]
            if not issues:
                continue
            if state.is_cleared(question):
                cleared_total += 1
                continue
            issue_codes = [issue.code for issue in issues]
            codes.update(issue_codes)
            # None of these codes is advisory: the typed ones mismark a
            # student, a missing figure costs them the mark outright, and a
            # user report is somebody saying it already did.
            blocking += 1
            if len(flagged) < max_flagged:
                flagged.append({
                    'id': question.id,
                    'codes': sorted(set(issue_codes)),
                    'detail': issues[0].detail[:200],
                    'text': (question.question_text or '')[:120],
                    'level': (question.level.level_number
                              if question.level_id else None),
                    'topic': _parent_topic_name(question),
                    'subtopic': _subtopic_name(question),
                    'is_global': question.school_id is None,
                })

        snapshot = QuestionHealthSnapshot.objects.create(
            typed_questions=typed_total,
            level_number=options['level'],
            topic=Topic.objects.filter(id=options['topic']).first(),
            total_questions=Question.objects.count(),
            choice_questions=choice_total,
            arithmetic_verified=verified,
            unverifiable=choice_total - verified,
            questions_blocking=blocking,
            questions_advisory=advisory,
            questions_cleared=cleared_total,
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
        if cleared_total:
            self.stdout.write(
                f'  {cleared_total} flagged question(s) not counted — reviewed '
                f'and marked correct by a person')
        if blocking + advisory > len(flagged):
            # Say so rather than let a truncated list read as the whole story.
            self.stdout.write(self.style.WARNING(
                f'  drill-down list capped at {len(flagged)} of '
                f'{blocking + advisory} flagged questions (--max-flagged)'))
