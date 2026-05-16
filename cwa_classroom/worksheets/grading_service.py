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
    Grade a student's extended answer.

    Algorithm:
      1. Normalise the answer text.
      2. Check cache (exact then fuzzy ≥ 0.85).
         → Hit: return cached result instantly (0 tokens).
      3. Cache miss: Claude evaluates the proof mathematically.
      4. Store result in cache so next similar answer is free.
      5. If the answer is a NEW correct path → append it to the
         question's grading rubric so future cache misses also
         have this path as reference.

    Returns dict:
        {
            'is_correct': bool,
            'score_fraction': float,   # 0.0–1.0
            'feedback': str,
            'cache_hit': bool,
            'input_tokens': int,
            'output_tokens': int,
        }
    """
    normalised = _normalise(answer_text)

    # ── 1. Cache check ────────────────────────────────────────────────────
    cached = _lookup_cache(question.pk, normalised, threshold=0.85)
    if cached:
        logger.info(f'AI grading cache hit for Q{question.pk}')
        result = {**cached, 'cache_hit': True, 'input_tokens': 0, 'output_tokens': 0}
        result.setdefault('is_partial', 0.1 <= result.get('score_fraction', 0.0) < 0.6)
        return result

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

    # ── 3. Claude evaluates the proof mathematically ──────────────────────
    result = _call_claude_grade(question, answer_text, normalised)

    # ── 4. Record usage ───────────────────────────────────────────────────
    if school:
        record_ai_grading_usage(school, result['input_tokens'], result['output_tokens'])

    # ── 5. Store in cache ─────────────────────────────────────────────────
    _store_cache(question.pk, normalised, result)

    # ── 6. New correct path → update rubric ──────────────────────────────
    # If Claude found a correct answer that isn't already described in the
    # rubric, append it so future evaluations have it as a reference.
    if result.get('is_correct') and not result.get('error'):
        _append_path_to_rubric(question, answer_text, result['feedback'])

    return result


def _parse_cache_feedback(raw_feedback: str) -> dict:
    """Parse a cache feedback field — may be a plain string or a JSON-encoded dict
    (new format including what_was_correct / what_to_add).

    Returns a dict with keys: feedback, what_was_correct, what_to_add.
    """
    import json as _json
    try:
        data = _json.loads(raw_feedback)
        if isinstance(data, dict):
            return {
                'feedback': data.get('feedback', raw_feedback),
                'what_was_correct': data.get('what_was_correct', ''),
                'what_to_add': data.get('what_to_add', ''),
            }
    except (ValueError, TypeError):
        pass
    return {'feedback': raw_feedback, 'what_was_correct': '', 'what_to_add': ''}


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

        def _make_result(e):
            parsed = _parse_cache_feedback(e.feedback)
            score = e.score_fraction
            return {
                'is_correct': e.is_correct,
                'score_fraction': score,
                'is_partial': 0.1 <= score < 0.6,
                **parsed,
            }

        # Exact match first
        for e in entries:
            if e.normalised_answer == normalised_text:
                e.hit_count = models.F('hit_count') + 1
                e.save(update_fields=['hit_count'])
                return _make_result(e)
        # Fuzzy match — use a tighter threshold for AI entries, standard for human-verified
        for e in entries:
            match_threshold = threshold if e.human_verified else threshold + 0.05
            ratio = _levenshtein_ratio(normalised_text, e.normalised_answer)
            if ratio >= match_threshold:
                e.hit_count = models.F('hit_count') + 1
                e.save(update_fields=['hit_count'])
                return _make_result(e)
    except Exception as exc:
        logger.warning(f'Cache lookup error: {exc}')
    return None


def _store_cache(question_pk, normalised_text, result):
    """Persist a grading result to cache.

    If the result includes what_was_correct / what_to_add, those are serialised
    into the feedback field as JSON so they survive a cache hit round-trip.
    """
    import json as _json
    try:
        Cache = _get_cache_model()
        what_was_correct = result.get('what_was_correct', '')
        what_to_add = result.get('what_to_add', '')
        if what_was_correct or what_to_add:
            feedback_stored = _json.dumps({
                'feedback': result['feedback'],
                'what_was_correct': what_was_correct,
                'what_to_add': what_to_add,
            })
        else:
            feedback_stored = result['feedback']
        Cache.objects.update_or_create(
            question_id=question_pk,
            normalised_answer=normalised_text[:500],
            defaults={
                'is_correct': result['is_correct'],
                'score_fraction': result['score_fraction'],
                'feedback': feedback_stored,
            },
        )
    except Exception as exc:
        logger.warning(f'Cache store error: {exc}')


def _append_path_to_rubric(question, answer_text, feedback):
    """
    If this correct answer represents a proof path not already in the rubric,
    append a short description of it. This makes the rubric self-updating:
    each new valid approach discovered by Claude gets recorded so future
    evaluations have it as a reference even on cache misses.
    """
    try:
        from maths.models import Question as MathsQuestion
        mq = MathsQuestion.objects.get(pk=question.pk)
        existing_rubric = mq.grading_rubric or ''

        # Normalise the new answer for comparison
        normalised_new = _normalise(answer_text)

        # Skip if the rubric already describes something very similar
        normalised_rubric = _normalise(existing_rubric)
        if _levenshtein_ratio(normalised_new[:200], normalised_rubric[:200]) > 0.6:
            return  # Already covered

        # Build a concise one-line description of this new path
        # Use the first sentence of the feedback (Claude's own description)
        path_desc = feedback.split('.')[0].strip() if feedback else answer_text[:120]

        separator = '\n\n' if existing_rubric else ''
        new_entry = f'Also valid: {answer_text[:200].strip()} ({path_desc})'
        mq.grading_rubric = existing_rubric + separator + new_entry
        mq.save(update_fields=['grading_rubric'])
        logger.info(f'Q{question.pk}: rubric updated with new valid path')
    except Exception as exc:
        logger.warning(f'Could not update rubric for Q{question.pk}: {exc}')


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
        'You are an expert teacher grading student extended answers across subjects '
        'including mathematics, science, and language arts.\n\n'

        'YOUR PRIMARY JOB: Evaluate whether the student\'s answer correctly and '
        'completely addresses the question. Credit substance and meaning, not '
        'phrasing — a student who expresses the right idea in different words '
        'should not lose marks.\n\n'

        'QUESTION TYPE GUIDANCE:\n'
        '• DEFINITIONS — Award credit for each key concept or keyword that is '
        'correctly included. A definition with 3 of 4 required elements earns ~0.75. '
        'Missing all key elements earns 0.0. Different but accurate wording is fine.\n'
        '• EXPLANATIONS / REASONING — Check whether the key ideas are present and '
        'the reasoning is logically sound. Partial explanations earn partial credit.\n'
        '• MATHEMATICAL PROOFS — Verify the argument step by step. A different valid '
        'proof path earns the same marks as the reference. Implicit trivial steps are fine.\n'
        '• SHORT ANSWERS — One or two correct key points earns near-full credit.\n\n'

        'THE RUBRIC (if provided) shows one correct approach. Students may express '
        'the same ideas differently. A different path that is correct earns full marks.\n\n'

        'THE DIAGRAM (if shown) defines labels/notation. Students need not re-state '
        'what is visible in the diagram.\n\n'

        'SCORING:\n'
        '  1.0 — Fully correct and complete.\n'
        '  0.8 — Mostly correct with very minor omission or imprecision.\n'
        '  0.6 — Correct approach, one genuine gap (still passes).\n'
        '  0.3 — Partially correct — some right ideas but missing key elements.\n'
        '  0.1 — Only a small fragment is correct.\n'
        '  0.0 — Fundamentally wrong or no attempt.\n\n'

        'CONSISTENCY: Your score_fraction and feedback MUST agree. '
        'If feedback says "correct/complete/well done", score >= 0.8. '
        'If feedback says "incorrect/missing/wrong", score <= 0.5. '
        'Never contradict yourself.\n\n'

        'Your response must be valid JSON.'
    )

    user_prompt = f"""Question: {question.question_text}

Reference answer (one valid approach — for context only):
{rubric}

{examples_text}

Student's answer:
{answer_text}

Evaluate this answer:
1. What key concepts, keywords, or reasoning steps did the student include correctly?
2. What is missing, incorrect, or needs to be added for full marks?
3. Does it earn full, partial, or no credit?

Respond with JSON only:
{{
  "score_fraction": <0.0 to 1.0>,
  "is_correct": <true if score_fraction >= 0.6>,
  "what_was_correct": "<specifically what the student got right — be concrete; 'None' if nothing>",
  "what_to_add": "<specifically what is missing or must be added for full marks — 'Nothing' if already full marks>",
  "feedback": "<1-2 sentence combined summary for the student>"
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
            max_tokens=500,
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
        what_was_correct = str(data.get('what_was_correct', ''))
        what_to_add = str(data.get('what_to_add', ''))

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
            'is_partial': 0.1 <= score_fraction < 0.6,
            'score_fraction': score_fraction,
            'feedback': feedback,
            'what_was_correct': what_was_correct,
            'what_to_add': what_to_add,
            'cache_hit': False,
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens,
        }
    except Exception as exc:
        logger.exception(f'Claude grading call failed: {exc}')
        return {
            'is_correct': False,
            'is_partial': False,
            'score_fraction': 0.0,
            'feedback': 'Automatic grading failed. Your teacher will review this answer.',
            'what_was_correct': '',
            'what_to_add': '',
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
