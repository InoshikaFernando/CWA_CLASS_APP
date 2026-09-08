"""
Have an independent model review questions that have never been reviewed.

Complements the deterministic audits: they prove faults from the data, this
catches questions that are merely *bad* — ambiguous, unanswerable, or whose
stated answer does not follow. See ``maths/ai_review.py`` for the design.

Incremental by construction. Each run picks up questions with no review, plus
questions edited since their last review, oldest first. Runs therefore advance
coverage instead of re-checking the same rows, and the backfill can be spread
over as many runs as the budget allows.

Costs real money, so it is bounded twice — ``--limit`` on questions and
``--max-cost`` on spend — and it will not accept ``--max-cost`` unless the
model rates are configured, because a ceiling it cannot measure is not a
ceiling. ``--dry-run`` shows what would be reviewed and writes nothing.

NEVER edits question content. It writes QuestionAIReview rows only.

Usage:
    python manage.py review_questions_ai --dry-run
    python manage.py review_questions_ai --limit 100
    python manage.py review_questions_ai --limit 500 --max-cost 5.00

Configuration (env):
    ANTHROPIC_API_KEY, OPENAI_API_KEY
    AI_REVIEW_FIRST_PASS_MODEL    cheap model, reviews everything
    AI_REVIEW_ADJUDICATOR_MODEL   stronger model, sees only doubted questions
    AI_REVIEW_RATES               JSON: {"<model>": {"input": 1.0, "output": 5.0}}
                                  USD per million tokens
"""
import sys
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Max, Q

from maths import ai_review


class Command(BaseCommand):
    help = 'Review never-reviewed questions with an independent model.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50,
                            help='Maximum questions to review this run.')
        parser.add_argument('--max-cost', type=float, default=None,
                            help='Stop once estimated spend reaches this USD amount.')
        parser.add_argument('--level', type=int, default=None)
        parser.add_argument('--topic', type=int, default=None)
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would be reviewed; write nothing, '
                                 'call nothing.')
        parser.add_argument('--quiet', action='store_true')

    # ------------------------------------------------------------------
    def _pending(self, options):
        """Questions never reviewed, or edited since their last review.

        Oldest-updated first, so a backfill works through the bank in a stable
        order and successive runs do not revisit the same rows.
        """
        from maths.models import Question

        questions = (
            Question.objects
            .filter(question_type__in=(Question.MULTIPLE_CHOICE,
                                       Question.TRUE_FALSE))
            .select_related('topic', 'level')
            .prefetch_related('answers')
            .annotate(last_reviewed_content=Max('ai_reviews__question_updated_at'))
            .filter(
                Q(last_reviewed_content__isnull=True)
                | Q(updated_at__gt=F('last_reviewed_content'))
            )
            .order_by('updated_at', 'id')
        )
        if options['level'] is not None:
            questions = questions.filter(level__level_number=options['level'])
        if options['topic'] is not None:
            questions = questions.filter(topic_id=options['topic'])
        return questions

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        from maths.models import QuestionAIReview

        quiet = options['quiet']
        dry_run = options['dry_run']
        max_cost = (Decimal(str(options['max_cost']))
                    if options['max_cost'] is not None else None)

        pending = self._pending(options)
        total_pending = pending.count()
        batch = list(pending[:options['limit']])

        if dry_run:
            self.stdout.write(
                f'{total_pending} question(s) awaiting review; this run would '
                f'take {len(batch)}.')
            if not quiet:
                for question in batch[:20]:
                    self.stdout.write(
                        f'  Q{question.id} {question.question_text[:70]}')
                if len(batch) > 20:
                    self.stdout.write(f'  ... and {len(batch) - 20} more')
            self.stdout.write('Dry run — nothing called, nothing written.')
            return

        # Self-gating: an unconfigured pass is a no-op with a warning, never a
        # failure, matching ai_import/verification.py.
        problems = ai_review.missing_configuration()
        if problems:
            self.stdout.write(self.style.WARNING(
                'AI review skipped — ' + '; '.join(problems)))
            return

        if max_cost is not None:
            unpriced = [
                model for model in (ai_review.FIRST_PASS_MODEL,
                                    ai_review.ADJUDICATOR_MODEL)
                if ai_review.cost_for(model, 1000, 1000) is None
            ]
            if unpriced:
                raise CommandError(
                    '--max-cost given but no rate is configured for: '
                    + ', '.join(unpriced)
                    + '. Set AI_REVIEW_RATES (USD per million tokens) or drop '
                      '--max-cost; a ceiling that cannot be measured is not a '
                      'ceiling.')

        reviewed = 0
        flagged = 0
        errors = 0
        escalated = 0
        spend = Decimal('0')
        unknown_cost = False
        input_tokens = 0
        output_tokens = 0

        for question in batch:
            if max_cost is not None and spend >= max_cost:
                self.stdout.write(self.style.WARNING(
                    f'Stopping: cost ceiling ${max_cost} reached.'))
                break

            outcome = ai_review.review_question(question)

            reviewed += 1
            escalated += 1 if outcome.escalated else 0
            input_tokens += outcome.input_tokens
            output_tokens += outcome.output_tokens
            if outcome.cost_usd is None:
                unknown_cost = True
            else:
                spend += outcome.cost_usd

            if outcome.verdict == QuestionAIReview.VERDICT_FLAGGED:
                flagged += 1
            elif outcome.verdict == QuestionAIReview.VERDICT_ERROR:
                errors += 1

            QuestionAIReview.objects.create(
                question=question,
                verdict=outcome.verdict,
                reason=outcome.reason,
                question_updated_at=question.updated_at,
                first_pass_model=outcome.first_pass_model,
                adjudicator_model=outcome.adjudicator_model,
                escalated=outcome.escalated,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                cost_usd=outcome.cost_usd,
            )

            if not quiet and outcome.verdict == QuestionAIReview.VERDICT_FLAGGED:
                self.stdout.write(
                    f'  FLAGGED Q{question.id}: {outcome.reason}')
                self.stdout.write(
                    f'          {question.question_text[:70]}')

        # ---- summary ---------------------------------------------------
        rate = (escalated / reviewed * 100) if reviewed else 0
        self.stdout.write('')
        self.stdout.write(f'Reviewed        : {reviewed}')
        self.stdout.write(f'Flagged         : {flagged}')
        self.stdout.write(f'Review errors   : {errors} (retried on a later run)')
        self.stdout.write(
            f'Escalated       : {escalated} ({rate:.0f}%) '
            f'— a rate near 100% means the cheap pass is not discriminating '
            f'and the two-tier split is not paying for itself')
        self.stdout.write(f'Tokens          : {input_tokens} in / {output_tokens} out')
        if unknown_cost:
            self.stdout.write(self.style.WARNING(
                'Cost            : unknown — no rate configured for one or '
                'more models (set AI_REVIEW_RATES)'))
        else:
            self.stdout.write(f'Cost            : ${spend:.4f}')
            if reviewed:
                self.stdout.write(
                    f'Per question    : ${spend / reviewed:.5f} '
                    f'— multiply by the remaining {max(total_pending - reviewed, 0)} '
                    f'to project the backfill')
        self.stdout.write(
            f'Still pending   : {max(total_pending - reviewed, 0)}')

        if flagged:
            # Non-zero so a scheduled run surfaces, without treating a flagged
            # question as a crash.
            sys.exit(1)
