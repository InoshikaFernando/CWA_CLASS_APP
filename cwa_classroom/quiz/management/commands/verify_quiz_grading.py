"""
Answer every question the way a student would, through the real grading
endpoint, and report any question that mismarks correct work.

This is the full-coverage weekly sweep. Unlike ``verify_question_answers``
(which inspects stored data), this drives the actual view — session handling,
routing by question type, and the grader — over real HTTP. A question passes
here only if a student submitting the right answer is actually scored right.

For multiple choice it submits EVERY option, not just the correct one, and
checks the outcome against the maths:

  * exactly one option must score correct
  * an option numerically EQUAL to the correct answer must not score wrong
    (the CPP-377 defect: '2/6' rejected when the answer is '1/3')

For typed questions it submits each stored correct answer and requires it to
be accepted.

Nothing is written: everything runs inside a transaction that is rolled back,
including the throwaway student account. Question types whose correct
submission cannot be synthesised from stored data (geometry specs, AI/human
graded) are reported as UNSUPPORTED rather than counted as passing — a sweep
that quietly skips half the catalogue is worse than no sweep.

Usage:
    python manage.py verify_quiz_grading                  # everything
    python manage.py verify_quiz_grading --topic 75
    python manage.py verify_quiz_grading --level 7
    python manage.py verify_quiz_grading --limit 200      # smoke run
    python manage.py verify_quiz_grading --quiet
"""
import json
import sys
import time
import uuid
from collections import Counter

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import Client
from django.urls import reverse

from maths.answer_values import parse_answer_value

CHOICE_TYPES = ('multiple_choice', 'true_false')
# Typed answers graded against the stored Answer rows.
TEXT_TYPES = (
    'short_answer', 'fill_blank', 'calculation',
    'long_division', 'prime_factorization', 'column_operation',
)


class Command(BaseCommand):
    help = 'Submit every question through the real grading endpoint and report mismarks.'

    def add_arguments(self, parser):
        parser.add_argument('--topic', type=int, default=None)
        parser.add_argument('--level', type=int, default=None)
        parser.add_argument('--limit', type=int, default=None,
                            help='Stop after N questions (smoke run).')
        parser.add_argument('--quiet', action='store_true')

    # -- submission helpers ------------------------------------------------
    def _session_for(self, client, question):
        """Inject a topic-quiz session so the endpoint accepts a submission.

        The question is listed twice so the submission is never 'last', which
        keeps the quiz-completion machinery (final results, points) out of the
        way of a pure grading check.
        """
        session_id = str(uuid.uuid4())
        session = client.session
        session[f'tq_{session_id}'] = {
            'current': 0,
            'questions': [{'id': question.id}, {'id': question.id}],
            'correct': 0,
            'start_time': time.time(),
            'topic_id': question.topic_id,
            'level_number': (
                question.level.level_number if question.level_id else 1),
            'subject': 'mathematics',
        }
        session.save()
        return session_id

    def _submit(self, client, question, payload):
        """POST one answer. Returns is_correct, or None if the view errored."""
        session_id = self._session_for(client, question)
        body = {'session_id': session_id, 'question_id': question.id}
        body.update(payload)
        response = client.post(
            reverse('api_submit_topic_answer'),
            data=json.dumps(body), content_type='application/json',
        )
        if response.status_code != 200:
            return None
        try:
            return bool(response.json().get('is_correct'))
        except ValueError:
            return None

    # -- per-question checks -----------------------------------------------
    def _check_choice(self, client, question):
        """Submit every option; compare outcomes to the maths."""
        problems = []
        options = list(question.answers.all())
        if not options:
            return ['no options to submit']

        flagged = [a for a in options if a.is_correct]
        if not flagged:
            return ['no option flagged correct']

        correct_values = [
            v for v in (parse_answer_value(a.answer_text) for a in flagged)
            if v is not None
        ]

        scored_correct = []
        for option in options:
            result = self._submit(client, question, {'answer_id': option.id})
            if result is None:
                problems.append(f'endpoint error submitting A{option.id}')
                continue
            if result:
                scored_correct.append(option)
                continue

            # Rejected. Was it actually the right value?
            value = parse_answer_value(option.answer_text)
            if value is not None and value in correct_values:
                problems.append(
                    f'MISMARK: option {option.answer_text!r} equals the '
                    f'correct answer {flagged[0].answer_text!r} but was '
                    f'scored WRONG')

        if not scored_correct:
            problems.append('no option scored correct — unanswerable question')
        elif len(scored_correct) > 1:
            problems.append(
                'several options scored correct: '
                f'{[a.answer_text for a in scored_correct]}')
        return problems

    def _check_text(self, client, question):
        """Every stored correct answer must be accepted when typed."""
        problems = []
        correct_texts = [
            a.answer_text for a in question.answers.filter(is_correct=True)
            if (a.answer_text or '').strip()
        ]
        if not correct_texts:
            return ['no stored correct answer to submit']

        for text in correct_texts:
            result = self._submit(client, question, {'text_answer': text})
            if result is None:
                problems.append(f'endpoint error submitting {text!r}')
            elif not result:
                problems.append(
                    f'MISMARK: the stored correct answer {text!r} was scored '
                    f'WRONG when typed')
        return problems

    def _check_measure(self, client, question):
        if question.numeric_answer is None:
            return ['measure question with no numeric_answer']
        text = f'{question.numeric_answer.normalize():f}'
        result = self._submit(client, question, {'text_answer': text})
        if result is None:
            return [f'endpoint error submitting {text!r}']
        if not result:
            return [f'MISMARK: the true value {text!r} was scored WRONG']
        return []

    # -- main --------------------------------------------------------------
    def handle(self, *args, **options):
        from maths.models import Question

        quiet = options['quiet']
        User = get_user_model()

        questions = (
            Question.objects
            .select_related('topic', 'level')
            .prefetch_related('answers')
            .order_by('id')
        )
        if options['topic'] is not None:
            questions = questions.filter(topic_id=options['topic'])
        if options['level'] is not None:
            questions = questions.filter(level__level_number=options['level'])
        if options['limit']:
            questions = questions[:options['limit']]

        checked = 0
        failed = 0
        unsupported = Counter()
        failures = []

        # Everything below is rolled back: the throwaway student, every
        # StudentAnswer row the endpoint writes, all of it.
        try:
            with transaction.atomic():
                password = uuid.uuid4().hex
                user = User.objects.create_user(
                    username=f'quiz-grading-sweep-{uuid.uuid4().hex[:8]}',
                    email='quiz-grading-sweep@example.invalid',
                    password=password,
                )
                client = Client()
                client.force_login(user)

                # chunk_size is required to combine iterator() with
                # prefetch_related() — without it Django 5 raises.
                for question in questions.iterator(chunk_size=200):
                    if getattr(question, 'needs_grading', False):
                        unsupported[f'{question.question_type} (needs grading)'] += 1
                        continue

                    if question.question_type in CHOICE_TYPES:
                        problems = self._check_choice(client, question)
                    elif question.question_type in TEXT_TYPES:
                        problems = self._check_text(client, question)
                    elif question.question_type == 'measure':
                        problems = self._check_measure(client, question)
                    elif question.answer_format in ('algebra', 'equation'):
                        problems = self._check_text(client, question)
                    else:
                        unsupported[question.question_type] += 1
                        continue

                    checked += 1
                    if problems:
                        failed += 1
                        failures.append((question, problems))
                        if not quiet:
                            topic = (question.topic.name
                                     if question.topic_id else '(no topic)')
                            year = (question.level.level_number
                                    if question.level_id else '?')
                            self.stdout.write(
                                f'  Q{question.id} [year {year} / {topic}] '
                                f'{question.question_text[:65]}')
                            for problem in problems:
                                self.stdout.write(f'      {problem}')

                # Undo everything this sweep touched.
                transaction.set_rollback(True)
        except Exception as exc:                       # noqa: BLE001
            self.stderr.write(self.style.ERROR(f'Sweep aborted: {exc!r}'))
            raise

        # ---- summary -------------------------------------------------------
        total_unsupported = sum(unsupported.values())
        self.stdout.write('')
        self.stdout.write(f'Answered via the real endpoint : {checked}')
        self.stdout.write(f'Questions that mismark         : {failed}')
        self.stdout.write(f'Not machine-answerable         : {total_unsupported}')
        for question_type, count in sorted(unsupported.items()):
            self.stdout.write(f'    {question_type:<34} {count}')
        if total_unsupported and not quiet:
            self.stdout.write(
                '  (these need the UI test or a human — they are NOT counted '
                'as passing)')

        if failed:
            self.stdout.write(self.style.ERROR(
                f'FAILED — {failed} question(s) mismark a correct answer'))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS(
            f'PASSED — {checked} question(s) grade correctly'))
