"""Semantic review of question content by independent models (CPP-380).

The deterministic audits in ``maths.answer_verification`` prove things about the
data. This module asks a different question — *is this a sensible question?* —
which cannot be settled by arithmetic: ambiguous wording, an answer that does
not follow from the stem, a word problem missing a number needed to solve it.

Design, inherited from ``ai_import/verification.py``:

- **Best effort, never a gate.** No API key configured means the pass no-ops.
  One provider erroring on one question logs and moves on.
- **Routes, never edits.** Nothing here writes question text, options, or the
  answer key. The output is a review row for a human to act on.
- **Two independent providers.** A single model's disagreement with the stored
  answer is not enough to flag; the two must corroborate. The reviewers are the
  same class of tool that authored some of this content, so one opinion is not
  evidence.

Two-tier by cost: a cheap model reviews everything, and only questions it
doubts are escalated to a stronger adjudicator from the *other* provider. On a
bank of thousands, reviewing everything twice with strong models costs roughly
an order of magnitude more for little extra signal.

Pricing is configuration, not code. ``AI_REVIEW_RATES`` (env, JSON) maps a
model name to USD per million tokens. A model with no configured rate reports
tokens and a cost of ``None`` rather than a guess — and ``--max-cost`` refuses
to run rather than enforce a ceiling it cannot actually measure.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)

# Model selection is env-driven, following the AI_IMPORT_VERIFY_MODEL precedent.
# No model identifiers are hard-coded as defaults that silently go stale.
FIRST_PASS_MODEL = os.environ.get('AI_REVIEW_FIRST_PASS_MODEL', '')
ADJUDICATOR_MODEL = os.environ.get('AI_REVIEW_ADJUDICATOR_MODEL', '')

_SYSTEM_PROMPT = (
    "You are checking a maths question from a children's learning platform for "
    "a school year group. You are NOT solving it for a student and you are NOT "
    "rewriting it.\n\n"
    "Decide whether the question is sound:\n"
    "  * Does the stated correct answer actually follow from the question?\n"
    "  * Is the question answerable — is any needed information missing?\n"
    "  * Is the wording unambiguous for the year level given?\n"
    "  * Could more than one of the given options reasonably be defended?\n\n"
    "Do NOT flag a question merely because a distractor is close to the answer, "
    "or because the wording is terse. Flag only a genuine fault a teacher would "
    "want to fix.\n\n"
    'Reply with JSON only: {"ok": true|false, "reason": "<= 25 words"}. '
    'When ok is true, reason may be empty.'
)


@dataclass
class ProviderResult:
    """One model's opinion, plus what it cost to get it."""
    ok: bool
    reason: str = ''
    model: str = ''
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ''

    @property
    def failed(self):
        return bool(self.error)


@dataclass
class ReviewOutcome:
    """The combined result for one question."""
    verdict: str                      # 'ok' | 'flagged' | 'error'
    reason: str = ''
    escalated: bool = False
    first_pass_model: str = ''
    adjudicator_model: str = ''
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = None
    results: list = field(default_factory=list)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def _rates():
    """Model → {'input': usd_per_mtok, 'output': usd_per_mtok}.

    Read from the AI_REVIEW_RATES env var as JSON so prices live in
    configuration and cannot go stale in the codebase.
    """
    raw = os.environ.get('AI_REVIEW_RATES', '').strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning('AI_REVIEW_RATES is not valid JSON — cost will be unknown')
        return {}


def cost_for(model, input_tokens, output_tokens):
    """USD cost, or None when the model's rate is not configured."""
    rate = _rates().get(model)
    if not rate:
        return None
    try:
        return (
            Decimal(str(rate['input'])) * Decimal(input_tokens) / Decimal(1_000_000)
            + Decimal(str(rate['output'])) * Decimal(output_tokens) / Decimal(1_000_000)
        )
    except (KeyError, TypeError, ValueError):
        return None


def anthropic_configured():
    return bool(getattr(settings, 'ANTHROPIC_API_KEY', ''))


def openai_configured():
    return bool(getattr(settings, 'OPENAI_API_KEY', ''))


def missing_configuration():
    """Human-readable list of what stops this pass running, empty when ready."""
    problems = []
    if not anthropic_configured():
        problems.append('ANTHROPIC_API_KEY is not set')
    if not openai_configured():
        problems.append('OPENAI_API_KEY is not set')
    if not FIRST_PASS_MODEL:
        problems.append('AI_REVIEW_FIRST_PASS_MODEL is not set')
    if not ADJUDICATOR_MODEL:
        problems.append('AI_REVIEW_ADJUDICATOR_MODEL is not set')
    return problems


# --------------------------------------------------------------------------
# Payload
# --------------------------------------------------------------------------
def build_payload(question):
    """The question as the reviewer sees it. Read-only projection."""
    options = [
        {'text': answer.answer_text, 'marked_correct': answer.is_correct}
        for answer in question.answers.all()
    ]
    return {
        'year_level': (question.level.level_number
                       if question.level_id else None),
        'topic': question.topic.name if question.topic_id else None,
        'question_type': question.question_type,
        'question': question.question_text,
        'options': options,
    }


def _parse_verdict(text):
    """Pull {'ok', 'reason'} out of a model reply. Raises ValueError if absent."""
    if not text:
        raise ValueError('empty reply')
    body = text.strip()
    # Tolerate a fenced block around the JSON.
    if body.startswith('```'):
        body = body.strip('`')
        body = body[body.index('{'):] if '{' in body else body
    start, end = body.find('{'), body.rfind('}')
    if start == -1 or end == -1:
        raise ValueError(f'no JSON object in reply: {text[:80]!r}')
    data = json.loads(body[start:end + 1])
    if 'ok' not in data:
        raise ValueError("reply has no 'ok' key")
    return bool(data['ok']), str(data.get('reason', ''))[:300]


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
def review_with_anthropic(payload, model):
    """Ask Anthropic. Never raises — transport failures come back as an error."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=model,
            max_tokens=300,
            system=_SYSTEM_PROMPT,
            messages=[{'role': 'user',
                       'content': json.dumps(payload, ensure_ascii=False)}],
        )
        text = ''.join(
            block.text for block in response.content
            if getattr(block, 'type', '') == 'text'
        )
        ok, reason = _parse_verdict(text)
        usage = getattr(response, 'usage', None)
        return ProviderResult(
            ok=ok, reason=reason, model=model,
            input_tokens=getattr(usage, 'input_tokens', 0) or 0,
            output_tokens=getattr(usage, 'output_tokens', 0) or 0,
        )
    except Exception as exc:                                   # noqa: BLE001
        logger.warning('Anthropic review failed: %r', exc)
        return ProviderResult(ok=True, model=model, error=repr(exc))


def review_with_openai(payload, model):
    """Ask OpenAI. Never raises — transport failures come back as an error."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model,
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content': _SYSTEM_PROMPT},
                {'role': 'user',
                 'content': json.dumps(payload, ensure_ascii=False)},
            ],
        )
        ok, reason = _parse_verdict(response.choices[0].message.content)
        usage = getattr(response, 'usage', None)
        return ProviderResult(
            ok=ok, reason=reason, model=model,
            input_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
            output_tokens=getattr(usage, 'completion_tokens', 0) or 0,
        )
    except Exception as exc:                                   # noqa: BLE001
        logger.warning('OpenAI review failed: %r', exc)
        return ProviderResult(ok=True, model=model, error=repr(exc))


# Indirection so tests can substitute providers without patching SDK internals,
# and so the escalation logic is testable with no network at all.
PROVIDERS = {
    'anthropic': review_with_anthropic,
    'openai': review_with_openai,
}


# --------------------------------------------------------------------------
# The two-tier decision
# --------------------------------------------------------------------------
def review_question(question, first_pass_model=None, adjudicator_model=None,
                    first_pass_provider='openai', adjudicator_provider='anthropic'):
    """Review one question and return a :class:`ReviewOutcome`.

    Cheap pass first. It alone can never flag: a question it doubts goes to the
    adjudicator, and only if that *also* objects is the question flagged for a
    human. Anything else is recorded as reviewed with no objection.

    A failed first pass yields verdict 'error' — recorded so the question is not
    mistaken for reviewed-and-clean, and is picked up again on a later run.
    """
    first_pass_model = first_pass_model or FIRST_PASS_MODEL
    adjudicator_model = adjudicator_model or ADJUDICATOR_MODEL
    payload = build_payload(question)

    first = PROVIDERS[first_pass_provider](payload, first_pass_model)
    outcome = ReviewOutcome(
        verdict='ok',
        first_pass_model=first_pass_model,
        input_tokens=first.input_tokens,
        output_tokens=first.output_tokens,
        results=[first],
    )

    if first.failed:
        outcome.verdict = 'error'
        outcome.reason = f'first pass failed: {first.error[:200]}'
        outcome.cost_usd = cost_for(first_pass_model, first.input_tokens,
                                    first.output_tokens)
        return outcome

    if first.ok:
        # No doubt raised — no reason to spend the adjudicator on it.
        outcome.cost_usd = cost_for(first_pass_model, first.input_tokens,
                                    first.output_tokens)
        return outcome

    # Escalate: the cheap model objects, so get an independent second opinion
    # from the other provider before troubling a human.
    second = PROVIDERS[adjudicator_provider](payload, adjudicator_model)
    outcome.escalated = True
    outcome.adjudicator_model = adjudicator_model
    outcome.input_tokens += second.input_tokens
    outcome.output_tokens += second.output_tokens
    outcome.results.append(second)

    first_cost = cost_for(first_pass_model, first.input_tokens, first.output_tokens)
    second_cost = cost_for(adjudicator_model, second.input_tokens, second.output_tokens)
    outcome.cost_usd = (
        None if first_cost is None or second_cost is None
        else first_cost + second_cost
    )

    if second.failed:
        # The cheap model's objection is unconfirmed. Not clean, not flagged.
        outcome.verdict = 'error'
        outcome.reason = f'adjudicator failed: {second.error[:200]}'
        return outcome

    if second.ok:
        # Providers disagree — one objects, one does not. Not corroborated, so
        # not flagged: a single model must never overrule authored content.
        outcome.verdict = 'ok'
        outcome.reason = ''
        return outcome

    outcome.verdict = 'flagged'
    outcome.reason = (second.reason or first.reason or 'flagged by both reviewers')
    return outcome
