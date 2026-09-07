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
be accepted. For "create your own pattern" questions, which have no stored
answer to submit, it builds a model pattern from the question's own wording and
requires that to be accepted.

Nothing is written. Each question's answer rows are rolled back in their own
short transaction, and the throwaway student account is deleted at the end —
per-question rather than one transaction around the whole run, so this stays
safe to point at a PRODUCTION database without holding locks or generating
replication lag. Question types whose correct
submission cannot be synthesised from stored data (geometry specs, AI/human
graded) are reported as UNSUPPORTED rather than counted as passing — a sweep
that quietly skips half the catalogue is worse than no sweep.

Usage:
    python manage.py verify_quiz_grading                  # everything
    python manage.py verify_quiz_grading --topic 75
    python manage.py verify_quiz_grading --level 7
    python manage.py verify_quiz_grading --limit 200      # smoke run
    python manage.py verify_quiz_grading --quiet
    python manage.py verify_quiz_grading --progress-seconds 0   # no heartbeat
"""
import json
import sys
import time
import uuid
from collections import Counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
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


def _allowed_host():
    """A Host header this deployment will accept.

    Django's test client sends ``Host: testserver``, which production's
    ALLOWED_HOSTS does not list — so every submission came back 400 before it
    reached any grading code, and the sweep reported 280 questions as
    mismarking a correct answer when it had in fact never graded one.
    """
    hosts = [h.strip() for h in getattr(settings, 'ALLOWED_HOSTS', []) if h.strip()]
    if not hosts or '*' in hosts:
        return 'testserver'          # ALLOWED_HOSTS accepts anything (or DEBUG).
    for host in hosts:
        # A leading dot means "this domain and its subdomains"; the bare domain
        # is itself allowed, so drop the dot rather than skipping the entry.
        host = host.lstrip('.')
        if host and '*' not in host:
            return host
    return 'testserver'


class Command(BaseCommand):
    help = 'Submit every question through the real grading endpoint and report mismarks.'

    def add_arguments(self, parser):
        parser.add_argument('--topic', type=int, default=None)
        parser.add_argument('--level', type=int, default=None)
        parser.add_argument('--limit', type=int, default=None,
                            help='Stop after N questions (smoke run).')
        parser.add_argument('--quiet', action='store_true')
        parser.add_argument(
            '--progress-seconds', type=float, default=30.0,
            help='Print a progress line at most this often (0 = never).')

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

    def _check_pattern(self, client, question):
        """A "create your own pattern" question has no stored answer, so the
        sweep submits a worked example built from the question's own wording —
        which is exactly what the student is being asked to produce."""
        from maths.pattern_grading import example_answer, parse_pattern_request

        text = example_answer(parse_pattern_request(question.question_text))
        result = self._submit(client, question, {'text_answer': text})
        if result is None:
            return [f'endpoint error submitting {text!r}']
        if not result:
            return [f'MISMARK: the model pattern {text!r} was scored WRONG']
        return []

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
        endpoint_errors = 0     # requests the app refused — not content faults
        unsupported = Counter()
        failures = []

        # A clean bank means this sweep prints NOTHING between its first line
        # and its summary — ~20k questions, tens of minutes of silence. Run
        # from CI over SSH that is not merely unhelpful: the runner network
        # drops a TCP flow that has carried no bytes for four minutes, which
        # killed every weekly run before it ever reported. So the sweep says
        # where it is at, on a clock rather than a question count — the point
        # is that no gap is long, and a slow database makes a count-based
        # heartbeat slow too.
        progress_seconds = options['progress_seconds']
        started = time.monotonic()
        last_beat = started

        # Everything this sweep writes is rolled back — but the rollback is
        # scoped to ONE QUESTION AT A TIME, not the whole run.
        #
        # A single transaction around the entire sweep would be correct and
        # still safe on a small database, but on production it means tens of
        # thousands of writes held open in one transaction for the duration:
        # lock contention, a growing undo log, and replication lag on managed
        # MySQL. Per-question savepoints keep each transaction to a handful of
        # rows and milliseconds, which is what makes this safe to point at a
        # live database.
        user = None
        try:
            password = uuid.uuid4().hex
            with transaction.atomic():
                user = User.objects.create_user(
                    username=f'quiz-grading-sweep-{uuid.uuid4().hex[:8]}',
                    email='quiz-grading-sweep@example.invalid',
                    password=password,
                )
            host = _allowed_host()
            client = Client(SERVER_NAME=host)
            client.force_login(user)

            # Prove the endpoint answers before grinding through the catalogue.
            # Without this the sweep submits thousands of requests that are all
            # rejected before reaching the grader, then reports every question
            # as mismarking a correct answer — an accusation against content
            # that was never graded. Whatever is wrong, saying it once here is
            # the honest version.
            probe = client.get('/api/health/')
            if probe.status_code >= 400:
                raise CommandError(
                    f'The grading endpoint is not reachable: GET /api/health/ '
                    f'returned {probe.status_code} with Host: {host!r}. '
                    f'Nothing was graded. If this is a 400, the host is not in '
                    f'ALLOWED_HOSTS (currently '
                    f'{list(getattr(settings, "ALLOWED_HOSTS", []))}).')

            # chunk_size is required to combine iterator() with
            # prefetch_related() — without it Django 5 raises.
            for question in questions.iterator(chunk_size=200):
                if getattr(question, 'needs_grading', False):
                    unsupported[f'{question.question_type} (needs grading)'] += 1
                    continue

                if question.question_type in CHOICE_TYPES:
                    check = self._check_choice
                elif question.answer_format == 'pattern':
                    # Before the typed-answer branch: these ARE short answers,
                    # but there is no stored answer for _check_text to submit.
                    check = self._check_pattern
                elif question.question_type in TEXT_TYPES:
                    check = self._check_text
                elif question.question_type == 'measure':
                    check = self._check_measure
                elif question.answer_format in ('algebra', 'equation'):
                    check = self._check_text
                else:
                    unsupported[question.question_type] += 1
                    continue

                with transaction.atomic():
                    problems = check(client, question)
                    # Undo this question's answer rows before moving on.
                    transaction.set_rollback(True)

                checked += 1
                now = time.monotonic()
                if progress_seconds and now - last_beat >= progress_seconds:
                    last_beat = now
                    self.stdout.write(
                        f'  … {checked} answered, {failed} mismarking, '
                        f'{(now - started) / 60:.1f} min elapsed')
                    self.stdout.flush()

                if problems:
                    # A question whose every problem is a refused request has
                    # not been shown to mismark anything.
                    if all('endpoint error' in p for p in problems):
                        endpoint_errors += 1
                    else:
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
                        self.stdout.flush()
        except Exception as exc:                       # noqa: BLE001
            self.stderr.write(self.style.ERROR(f'Sweep aborted: {exc!r}'))
            raise
        finally:
            # The account is outside the per-question savepoints, so it is
            # removed explicitly — including on abort.
            if user is not None and user.pk:
                user.delete()

        # ---- summary -------------------------------------------------------
        total_unsupported = sum(unsupported.values())
        self.stdout.write('')
        self.stdout.write(f'Answered via the real endpoint : {checked}')
        self.stdout.write(f'Questions that mismark         : {failed}')
        if endpoint_errors:
            self.stdout.write(self.style.WARNING(
                f'Questions the endpoint refused : {endpoint_errors} '
                f'(never graded — NOT a content fault)'))
        self.stdout.write(f'Not machine-answerable         : {total_unsupported}')
        for question_type, count in sorted(unsupported.items()):
            self.stdout.write(f'    {question_type:<34} {count}')
        if total_unsupported and not quiet:
            self.stdout.write(
                '  (these need the UI test or a human — they are NOT counted '
                'as passing)')

        if endpoint_errors:
            self.stdout.write(self.style.ERROR(
                f'FAILED — the endpoint refused {endpoint_errors} question(s). '
                f'Those were never graded, so nothing is known about them.'))
            sys.exit(1)
        if failed:
            self.stdout.write(self.style.ERROR(
                f'FAILED — {failed} question(s) mismark a correct answer'))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS(
            f'PASSED — {checked} question(s) grade correctly'))
