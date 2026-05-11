"""
AI Grading Service — grades extended/proof answers using Claude.

Caching strategy (saves ~80% of API calls for class sets):
  1. Normalise the student's answer text (lowercase, collapse whitespace).
  2. Exact-match lookup against AIGradingCache for this question — free.
  3. Fuzzy-match (Levenshtein ratio > 0.85) against all cached answers — free.
  4. If no cache hit: call Claude with the question, rubric, and up to 10
     previously-graded answers as reference examples.  Claude can classify
     "matches example #3" (cheap) or evaluate fresh (full cost).
  5. Store the result in AIGradingCache keyed by normalised text.

Token cost per question:
  Cache hit:   0 tokens
  Classify:  ~350 tokens  (sees prior examples, short output)
  Fresh:     ~780 tokens  (full evaluation)

For 30 students, ~5-8 unique answer patterns per question means only
5-8 full evaluations + ~22-25 free cache hits → ~80% token saving.
"""
import logging
import re
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

# Anthropic pricing (claude-sonnet-4 — update if pricing changes)
COST_PER_INPUT_TOKEN = Decimal('0.000003')   # $3 / 1M tokens
COST_PER_OUTPUT_TOKEN = Decimal('0.000015')  # $15 / 1M tokens

AI_GRADING_MODULES = [
    'ai_grading_starter',
    'ai_grading_professional',
    'ai_grading_enterprise',
]


# ---------------------------------------------------------------------------
# Quota helpers
# ---------------------------------------------------------------------------

def get_ai_grading_tier(school):
    """Return the active AI grading module slug for a school, or None."""
    from billing.entitlements import get_school_subscription
    sub = get_school_subscription(school)
    if not sub:
        return None
    for slug in AI_GRADING_MODULES:
        if sub.modules.filter(module=slug, is_active=True).exists():
            return slug
    return None


def check_ai_grading_quota(school):
    """
    Check whether the school can run another AI grading call.

    Returns (allowed: bool, used: int, limit: int | None)
      limit=None means unlimited (Enterprise).
    """
    # Free schools bypass all quota checks
    if school and getattr(school, 'free_ai_grading', False):
        return (True, 0, None)

    tier = get_ai_grading_tier(school)
    if not tier:
        return (False, 0, 0)

    from billing.models import ModuleProduct, AIGradingUsage
    product = ModuleProduct.objects.filter(module=tier, is_active=True).first()
    limit = product.questions_per_month if product else None  # None = unlimited

    if limit is None:
        return (True, 0, None)

    today = timezone.localdate()
    period_start = today.replace(day=1)
    usage = AIGradingUsage.objects.filter(school=school, period_start=period_start).first()
    used = usage.answers_graded if usage else 0
    return (used < limit, used, limit)


def record_ai_grading_usage(school, input_tokens, output_tokens):
    """Increment the school's monthly AI grading usage counter."""
    from billing.models import AIGradingUsage
    today = timezone.localdate()
    period_start = today.replace(day=1)
    cost = (
        Decimal(input_tokens) * COST_PER_INPUT_TOKEN
        + Decimal(output_tokens) * COST_PER_OUTPUT_TOKEN
    )
    AIGradingUsage.objects.update_or_create(
        school=school,
        period_start=period_start,
        defaults={'answers_graded': 0, 'tokens_used': 0, 'estimated_cost_usd': Decimal('0')},
    )
    AIGradingUsage.objects.filter(school=school, period_start=period_start).update(
        answers_graded=models.F('answers_graded') + 1,
        tokens_used=models.F('tokens_used') + input_tokens + output_tokens,
        estimated_cost_usd=models.F('estimated_cost_usd') + cost,
    )


# ---------------------------------------------------------------------------
# Answer normalisation
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, strip, collapse whitespace — used for cache key matching."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def _levenshtein_ratio(a: str, b: str) -> float:
    """Fast Levenshtein similarity ratio between two strings (0–1)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    len_a, len_b = len(a), len(b)
    # Skip expensive computation for very different lengths
    if max(len_a, len_b) > 0 and abs(len_a - len_b) / max(len_a, len_b) > 0.4:
        return 0.0
    # Simple DP
    prev = list(range(len_b + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    distance = prev[len_b]
    return 1 - distance / max(len_a, len_b)


# ---------------------------------------------------------------------------
# Cache model (lazy import to avoid circular imports at module load time)
# ---------------------------------------------------------------------------

def _get_cache_model():
    from django.apps import apps
    return apps.get_model('homework', 'AIGradingCache')


# ---------------------------------------------------------------------------
# Core grading function
# ---------------------------------------------------------------------------

def grade_extended_answer(question, answer_text: str, school=None):
    """
    Grade a student's extended answer against the question's rubric.

    Returns dict:
        {
            'is_correct': bool,
            'score_fraction': float,   # 0.0–1.0
            'feedback': str,
            'cache_hit': bool,         # True if result came from cache (no API cost)
            'input_tokens': int,
            'output_tokens': int,
        }

    If school is provided and has no AI grading module, returns is_correct=False
    with feedback explaining the module is not enabled.
    """
    normalised = _normalise(answer_text)

    # ── 1. Exact cache lookup ─────────────────────────────────────────────
    cached = _lookup_cache(question.pk, normalised, threshold=0.85)
    if cached:
        logger.info(f'AI grading cache hit for Q{question.pk}')
        return {**cached, 'cache_hit': True, 'input_tokens': 0, 'output_tokens': 0}

    # ── 2. Quota check ────────────────────────────────────────────────────
    if school:
        allowed, used, limit = check_ai_grading_quota(school)
        if not allowed:
            return {
                'is_correct': False,
                'score_fraction': 0.0,
                'feedback': (
                    f'AI grading quota reached ({used}/{limit} this month). '
                    'Your teacher will review this answer manually.'
                ),
                'cache_hit': False,
                'input_tokens': 0,
                'output_tokens': 0,
                'quota_exceeded': True,
            }

    # ── 3. Call Claude ────────────────────────────────────────────────────
    result = _call_claude_grade(question, answer_text, normalised)

    # ── 4. Record usage ───────────────────────────────────────────────────
    if school:
        record_ai_grading_usage(school, result['input_tokens'], result['output_tokens'])

    # ── 5. Store in cache ─────────────────────────────────────────────────
    _store_cache(question.pk, normalised, result)

    return result


def _lookup_cache(question_pk, normalised_text, threshold=0.85):
    """Check DB cache for a similar previously-graded answer. Returns result dict or None.

    Human-verified entries (teacher-graded golden examples) are checked first —
    they are ground truth and take priority over AI-generated cache entries.
    """
    try:
        Cache = _get_cache_model()
        # human_verified first, then by hit_count — golden examples take priority
        entries = list(Cache.objects.filter(question_id=question_pk)
                       .order_by('-human_verified', '-hit_count'))
        if not entries:
            return None
        # Exact match first
        for e in entries:
            if e.normalised_answer == normalised_text:
                e.hit_count = models.F('hit_count') + 1
                e.save(update_fields=['hit_count'])
                return {'is_correct': e.is_correct, 'score_fraction': e.score_fraction, 'feedback': e.feedback}
        # Fuzzy match — use a tighter threshold for AI entries, standard for human-verified
        for e in entries:
            match_threshold = threshold if e.human_verified else threshold + 0.05
            ratio = _levenshtein_ratio(normalised_text, e.normalised_answer)
            if ratio >= match_threshold:
                e.hit_count = models.F('hit_count') + 1
                e.save(update_fields=['hit_count'])
                return {'is_correct': e.is_correct, 'score_fraction': e.score_fraction, 'feedback': e.feedback}
    except Exception as exc:
        logger.warning(f'Cache lookup error: {exc}')
    return None


def _store_cache(question_pk, normalised_text, result):
    """Persist a grading result to cache."""
    try:
        Cache = _get_cache_model()
        Cache.objects.update_or_create(
            question_id=question_pk,
            normalised_answer=normalised_text[:500],
            defaults={
                'is_correct': result['is_correct'],
                'score_fraction': result['score_fraction'],
                'feedback': result['feedback'],
            },
        )
    except Exception as exc:
        logger.warning(f'Cache store error: {exc}')


def _fetch_image_block(question):
    """
    Return an Anthropic image content block for the question's diagram, or None.
    Fetches the image from Django storage (S3/Spaces) and base64-encodes it.
    """
    if not question.image:
        return None
    try:
        import base64
        from django.core.files.storage import default_storage
        # question.image.name is the storage key (e.g. 'questions/year7/...')
        with default_storage.open(question.image.name, 'rb') as f:
            raw = f.read()
        encoded = base64.standard_b64encode(raw).decode('utf-8')
        # Detect media type from extension
        name = question.image.name.lower()
        if name.endswith('.png'):
            media_type = 'image/png'
        elif name.endswith('.gif'):
            media_type = 'image/gif'
        elif name.endswith('.webp'):
            media_type = 'image/webp'
        else:
            media_type = 'image/jpeg'
        return {
            'type': 'image',
            'source': {'type': 'base64', 'media_type': media_type, 'data': encoded},
        }
    except Exception as exc:
        logger.warning(f'Could not load image for Q{question.pk}: {exc}')
        return None


def _call_claude_grade(question, answer_text, normalised_text):
    """Call the Anthropic API to grade the answer. Returns result dict."""
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=120.0)

    # Include up to 10 previously cached answers as examples so Claude can
    # classify quickly instead of always evaluating from scratch.
    examples_text = _build_examples_prompt(question.pk)

    rubric = question.grading_rubric or (
        f'Grade this answer to the question. '
        f'The model answer/explanation is: {question.explanation or "(not provided)"}'
    )

    # Fetch diagram image if available — lets Claude see exactly which angles
    # are at which intersection, eliminating ambiguity from text-only grading.
    image_block = _fetch_image_block(question)

    system = (
        'You are an expert mathematics teacher grading student proof answers. '
        'You have deep knowledge of geometry and can independently verify whether '
        'a mathematical argument is correct — you do not need a rubric to tell you '
        'if a proof is valid.\n\n'

        'YOUR PRIMARY JOB: Determine whether the student\'s reasoning is '
        'mathematically correct and complete. Ask yourself: "If I were marking this '
        'on a maths exam, is this proof valid?" — not "Does it match the sample answer?"\n\n'

        'THE RUBRIC IS A REFERENCE ONLY. It shows one possible correct approach. '
        'Students may use any valid proof path — corresponding angles, co-interior angles, '
        'vertically opposite angles, linear pairs, angles at a point, alternate angles — '
        'in any order that forms a valid logical chain. A different path that reaches the '
        'correct conclusion with correct reasoning earns the same marks as the rubric path.\n\n'

        'THE DIAGRAM (if shown) defines the angle labels. Use it to understand the geometry '
        'directly. Students do not need to re-state facts visible in the diagram.\n\n'

        'IMPLICIT STEPS ARE FINE at high school level. If a student states all the key '
        'relationships and the conclusion follows by simple substitution, that is complete. '
        'Example: "a=c (vertically opposite) and b=d (vertically opposite)" is a complete '
        'proof of a+d=b+c — the substitution is trivial and need not be written.\n\n'

        'SCORING:\n'
        '  1.0 — Mathematically valid proof, correct conclusion.\n'
        '  0.8 — Valid proof with very minor imprecision (informal wording, one implicit step).\n'
        '  0.6 — Correct approach and theorems but one genuine logical gap.\n'
        '  0.3 — Partially correct — right theorems but chain does not reach the conclusion.\n'
        '  0.0 — Fundamentally wrong or no attempt.\n\n'

        'Your score_fraction and your feedback MUST be consistent. '
        'If your feedback says the proof is correct/valid/complete, score >= 0.8. '
        'If your feedback says there is a gap, score <= 0.5. Never contradict yourself.\n\n'

        'Your response must be valid JSON.'
    )

    user_prompt = f"""Question: {question.question_text}

Reference answer (one valid approach — for context only):
{rubric}

{examples_text}

Student's answer:
{answer_text}

Verify this proof independently:
- Are the angle relationships stated mathematically correct?
- Do they form a valid chain leading to the conclusion?
- Is the conclusion correct?

If yes to all three → score 1.0 (or 0.8 for minor imprecision). Do not penalise for using a different path than the reference.

Respond with JSON only:
{{
  "score_fraction": <0.0 to 1.0>,
  "is_correct": <true if score_fraction >= 0.6>,
  "feedback": "<1-3 sentences for the student: what was correct, what (if anything) was missing>"
}}"""

    try:
        # Build user message — include diagram image if available so Claude
        # can see exactly which angles are at which intersection.
        if image_block:
            user_content = [
                {'type': 'text', 'text': 'Here is the question diagram:'},
                image_block,
                {'type': 'text', 'text': user_prompt},
            ]
        else:
            user_content = user_prompt

        response = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=400,
            system=system,
            messages=[{'role': 'user', 'content': user_content}],
        )
        import json
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        data = json.loads(text)
        score_fraction = float(data.get('score_fraction', 0.0))
        score_fraction = max(0.0, min(1.0, score_fraction))
        feedback = str(data.get('feedback', ''))

        # ── Consistency check ────────────────────────────────────────────
        # Claude sometimes writes "Excellent work, mathematically complete"
        # but returns score_fraction=0.5 — words and number contradict.
        # Detect this and trust the words, not the number.
        feedback_lower = feedback.lower()
        POSITIVE_SIGNALS = [
            'excellent', 'perfect', 'correct', 'valid', 'complete',
            'well done', 'great', 'mathematically sound', 'full marks',
            'fully correct', 'demonstrates a clear understanding',
        ]
        NEGATIVE_SIGNALS = [
            'incorrect', 'wrong', 'incomplete', 'missing', 'not shown',
            'no credit', 'does not', "doesn't", 'failed', 'error',
        ]
        positive_hit = any(s in feedback_lower for s in POSITIVE_SIGNALS)
        negative_hit = any(s in feedback_lower for s in NEGATIVE_SIGNALS)

        if positive_hit and not negative_hit and score_fraction < 0.65:
            # Feedback is clearly positive but score is too low — trust words
            logger.warning(
                f'Grading inconsistency Q{question.pk}: feedback positive but '
                f'score={score_fraction:.2f} — bumping to 0.85'
            )
            score_fraction = 0.85

        if negative_hit and not positive_hit and score_fraction >= 0.65:
            # Feedback is clearly negative but score is passing — trust words
            logger.warning(
                f'Grading inconsistency Q{question.pk}: feedback negative but '
                f'score={score_fraction:.2f} — dropping to 0.35'
            )
            score_fraction = 0.35
        # ────────────────────────────────────────────────────────────────

        return {
            'is_correct': score_fraction >= 0.6,
            'score_fraction': score_fraction,
            'feedback': feedback,
            'cache_hit': False,
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens,
        }
    except Exception as exc:
        logger.exception(f'Claude grading call failed: {exc}')
        return {
            'is_correct': False,
            'score_fraction': 0.0,
            'feedback': 'Automatic grading failed. Your teacher will review this answer.',
            'cache_hit': False,
            'input_tokens': 0,
            'output_tokens': 0,
            'error': str(exc),
        }


def _build_examples_prompt(question_pk):
    """Build a text block of up to 10 previously graded answers for context.

    Human-verified (teacher-graded) entries are shown first and labelled
    [TEACHER VERIFIED] so Claude knows to trust them as ground truth.
    """
    try:
        Cache = _get_cache_model()
        entries = Cache.objects.filter(question_id=question_pk).order_by('-human_verified', '-hit_count')[:10]
        if not entries:
            return ''
        lines = ['Previously graded answers for context (use these to classify quickly if the new answer matches):']
        for i, e in enumerate(entries, 1):
            grade = f"{e.score_fraction:.1f}/1.0"
            label = '[TEACHER VERIFIED] ' if e.human_verified else ''
            lines.append(f'  Example {i} {label}({grade}): "{e.normalised_answer[:200]}" → {e.feedback[:100]}')
        return '\n'.join(lines) + '\n'
    except Exception:
        return ''
