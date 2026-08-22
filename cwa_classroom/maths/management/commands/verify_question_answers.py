"""
Verify every question's answers — structurally, and where possible by actually
doing the maths.

Checks applied to each choice question:

    NO-CORRECT         no option is flagged is_correct
    MULTI-CORRECT      more than one option is flagged correct
    DUPLICATE-OPTION   the same option text appears twice
    EQUIVALENT-OPTION  a distractor is numerically equal to the answer (CPP-377)
    TOO-FEW-OPTIONS    fewer than --min-options options
    BLANK-OPTION       an option with no text
    WRONG-ANSWER-KEY   the question's own arithmetic disagrees with the answer
    DUPLICATE-VALUE    two distractors are worth the same number (advisory)

Checks applied to each typed-answer (short answer / calculation) question:

    UNMARKED-SET       asks for a collection but grades in order (CPP-378)
    FRAGMENT-ROW       a correct row is one value of another correct row's list

Typed answers used to be skipped entirely, which is how 559 questions came to
accept a fragment of a list answer as the whole thing. Both codes describe
authoring only a human can resolve, so they are reported and fail the run
rather than being silently repaired.

All but DUPLICATE-VALUE mean a student can be marked wrongly, and fail the run.
DUPLICATE-VALUE cannot mismark anyone — both options are wrong — it just means
the question offers fewer real choices than it appears to. It is reported but
does not fail the run unless --strict is given, so the weekly job does not cry
wolf over a presentation issue.

WRONG-ANSWER-KEY is the only check that can catch a wrong answer key, and it
only applies to self-contained expressions ("Calculate: 9/10 - 3/5"). Word
problems cannot be machine-verified, so the summary reports how many questions
were actually checked arithmetically rather than implying full coverage.

Read-only. Exits non-zero when any non-advisory issue is found (same CI/cron
contract as audit_question_image_paths).

Usage:
    python manage.py verify_question_answers                     # whole DB
    python manage.py verify_question_answers --topic 75
    python manage.py verify_question_answers --level 7
    python manage.py verify_question_answers --check WRONG-ANSWER-KEY
    python manage.py verify_question_answers --unverified        # coverage gaps
    python manage.py verify_question_answers --quiet
"""
import sys
from collections import Counter

from django.core.management.base import BaseCommand

from maths.answer_verification import (
    DUPLICATE_OPTION, DUPLICATE_VALUE, TOO_MANY_OPTIONS, verify_question,
    verify_typed_answer_question)

# Codes that cannot mismark a student. They are reported, but they do not fail
# the run (without --strict) and they stay out of the dashboard's headline —
# padding that number with cosmetic faults is how a real backlog gets ignored.
ADVISORY_CODES = {DUPLICATE_VALUE, DUPLICATE_OPTION, TOO_MANY_OPTIONS}


class Command(BaseCommand):
    help = 'Verify question answers: structure, plus arithmetic where readable.'

    def add_arguments(self, parser):
        parser.add_argument('--topic', type=int, default=None,
                            help='Restrict to a single Topic id.')
        parser.add_argument('--level', type=int, default=None,
                            help='Restrict to a single Level.level_number.')
        parser.add_argument('--check', action='append', default=None,
                            metavar='CODE',
                            help='Only report these issue codes (repeatable).')
        parser.add_argument('--min-options', type=int, default=2,
                            help='Minimum options a choice question must have.')
        parser.add_argument('--unverified', action='store_true',
                            help='List questions whose maths could NOT be '
                                 'machine-verified, instead of the issues.')
        parser.add_argument('--quiet', action='store_true',
                            help='Print only the summary.')
        parser.add_argument('--strict', action='store_true',
                            help='Fail on advisory issues (DUPLICATE-VALUE) too.')

    def handle(self, *args, **options):
        from maths.models import Question

        only = set(options['check']) if options['check'] else None
        quiet = options['quiet']

        questions = (
            Question.objects
            .filter(question_type__in=(Question.MULTIPLE_CHOICE,
                                       Question.TRUE_FALSE))
            .select_related('topic', 'level')
            .prefetch_related('answers')
        )
        # Typed answers are a separate population with separate checks — they
        # have no options to count and no distractors to compare (CPP-378).
        typed = (
            Question.objects
            .exclude(question_type__in=(Question.MULTIPLE_CHOICE,
                                        Question.TRUE_FALSE))
            .select_related('topic', 'level')
            .prefetch_related('answers')
        )
        if options['topic'] is not None:
            questions = questions.filter(topic_id=options['topic'])
            typed = typed.filter(topic_id=options['topic'])
        if options['level'] is not None:
            questions = questions.filter(level__level_number=options['level'])
            typed = typed.filter(level__level_number=options['level'])

        scanned = 0
        advisory_only = 0
        arithmetic_checked = 0
        unverified = []
        flagged = 0
        by_code = Counter()

        for question in questions.order_by('id'):
            scanned += 1
            issues, verified = verify_question(
                question, min_options=options['min_options'])
            if verified:
                arithmetic_checked += 1
            else:
                unverified.append(question)

            if only:
                issues = [i for i in issues if i.code in only]
            if not issues:
                continue

            if any(i.code not in ADVISORY_CODES for i in issues) or options['strict']:
                flagged += 1
            else:
                advisory_only += 1
            for issue in issues:
                by_code[issue.code] += 1

            if quiet or options['unverified']:
                continue

            topic = question.topic.name if question.topic_id else '(no topic)'
            year = question.level.level_number if question.level_id else '?'
            self.stdout.write(
                f'  Q{question.id} [year {year} / {topic}] '
                f'{question.question_text[:70]}')
            for issue in issues:
                self.stdout.write(f'      {issue.code}: {issue.detail}')

        typed_scanned = 0
        for question in typed.order_by('id'):
            typed_scanned += 1
            issues = verify_typed_answer_question(question)
            if only:
                issues = [i for i in issues if i.code in only]
            if not issues:
                continue
            flagged += 1
            for issue in issues:
                by_code[issue.code] += 1
            if quiet or options['unverified']:
                continue
            topic = question.topic.name if question.topic_id else '(no topic)'
            year = question.level.level_number if question.level_id else '?'
            self.stdout.write(
                f'  Q{question.id} [year {year} / {topic}] '
                f'{question.question_text[:70]}')
            for issue in issues:
                self.stdout.write(f'      {issue.code}: {issue.detail}')

        if options['unverified'] and not quiet:
            self.stdout.write(
                'Questions NOT machine-verified (need human review):')
            for question in unverified:
                self.stdout.write(
                    f'  Q{question.id} {question.question_text[:80]}')

        # ---- summary -------------------------------------------------------
        self.stdout.write('')
        self.stdout.write(f'Scanned            : {scanned} choice question(s)')
        self.stdout.write(f'                     {typed_scanned} typed-answer question(s)')
        self.stdout.write(
            f'Maths verified     : {arithmetic_checked} '
            f'({(arithmetic_checked / scanned * 100) if scanned else 0:.0f}%) '
            f'— the rest are word problems needing human review')
        self.stdout.write(f'Questions flagged  : {flagged}')
        if advisory_only:
            self.stdout.write(
                f'Advisory only      : {advisory_only} '
                f'(no student is mismarked — pass --strict to fail on these)')
        for code, count in sorted(by_code.items()):
            self.stdout.write(f'    {code:<18} {count}')

        if flagged:
            self.stdout.write(self.style.ERROR(
                f'FAILED — {flagged} question(s) with issues'))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS('PASSED — no issues found'))
