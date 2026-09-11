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
import os
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


# Three bands, and one place that draws the lines between them:
#
#   1.0          ✅ Correct — full marks.
#   0.75 – 0.99  🟡 Partly correct — worth that share of the marks, and shown
#                with the score, so a nearly-complete answer keeps what it
#                earned without being called right.
#   below 0.75   ❌ Wrong — no marks.
#
# The pass mark used to be 0.6, and the prompt itself called that score "one
# genuine gap (still passes)" — so an answer Claude had just written a
# paragraph of corrections about came back to the child under a green
# ✅ Correct. "Correct" now means the answer had nothing wrong with it, which
# is the only reading that can never contradict the feedback printed beside it.
#
# Everything that turns a score into a verdict reads these — the grader, the
# cache, the quiz, the worksheet and the teacher's screen — so the meaning of
# "correct" cannot drift apart between them.
FULL_MARKS = 1.0
PASS_MARK = 0.75

# Floating point: a score built as 3/3 or as 0.1 + 0.9 must still be full
# marks, so the comparison allows for the last bit of a float.
_EPSILON = 1e-6


def verdict(score_fraction):
    """(is_correct, is_partial) for a score — the one place the lines are drawn."""
    score = float(score_fraction or 0.0)
    is_correct = score >= FULL_MARKS - _EPSILON
    return is_correct, (not is_correct) and score >= PASS_MARK - _EPSILON


def credit_for(score_fraction):
    """What an AI-graded answer is WORTH, 0.0–1.0.

    Below the pass mark the answer is wrong, and a wrong answer earns nothing:
    marks are not handed out for the share of a wrong answer that happened to
    look familiar. At or above it, the answer keeps the score it was given.
    """
    score = max(0.0, min(1.0, float(score_fraction or 0.0)))
    return score if score >= PASS_MARK - _EPSILON else 0.0


# ---------------------------------------------------------------------------
# Quota helpers
# ---------------------------------------------------------------------------

def get_ai_grading_tier(school):
    """Return the active AI grading module slug for a school, or None.

    The strongest tier held, not the first found. This used to walk
    ``AI_GRADING_MODULES`` forwards and return on the first match, so a school
    left holding Starter alongside Enterprise — an upgrade that half-failed, a
    grant landing beside an existing row — was served the 1,000-answer quota it
    had stopped paying for instead of the unlimited one it had bought. Nothing
    errored; the school just ran out early.
    """
    from billing.entitlements import get_school_subscription, strongest_tier
    return strongest_tier(get_school_subscription(school), AI_GRADING_MODULES)


def student_can_be_ai_graded(user):
    """May *user* be shown, and marked on, an AI-graded question?

    Two populations, deliberately different:

    - **Individual students** — no school behind them. They pay for the app
      themselves (or are on a full discount the owner granted personally), so
      AI grading is included and unmetered. There is no school subscription to
      check and no quota to run out.
    - **School students** — AI grading is their school's paid add-on. If the
      school buys it — or the owner has granted it free via
      ``School.free_ai_grading`` — they get the questions; if not, the quiz
      does not show them, because the alternative is marking a child wrong for
      something their school did not buy.

    Note the asymmetry with AI *import*, which gates a teacher's access to a
    feature. This gates whether a question is offered at all — never whether a
    submitted answer counts.

    Before either population is considered, the student's OWN modules get a
    say (``billing.StudentModule``). A student the owner has put on **Student
    Basic** — the free promotional edition — is not AI-graded even if they are
    an individual, and a student who holds the **AI grading** add-on is, even if
    their school never bought the module. Everyone else holds neither module,
    which is every student on the site until somebody is put on a promotion, so
    the two populations below decide exactly as they always have.

    A school that has spent its monthly allowance is treated as not having the
    feature until the allowance resets or it moves up a plan. Owning the module
    is not enough on its own: offering a child a question we then can't mark is
    worse than not offering it, and that was the old behaviour — the quota was
    only consulted at grading time, so the question was asked, answered, and
    then came back "quota reached, your teacher will review this manually".
    """
    from billing.entitlements import (
        get_all_schools_for_user, student_module_ai_verdict,
    )

    by_module = student_module_ai_verdict(user)
    if by_module is not None:
        return by_module

    schools = list(get_all_schools_for_user(user))
    if not schools:
        return True
    for school in schools:
        if getattr(school, 'free_ai_grading', False):
            return True
        if not get_ai_grading_tier(school):
            continue
        allowed, _used, _limit = check_ai_grading_quota(school)
        if allowed:
            return True
    return False


def get_ai_grading_limit(school):
    """Monthly graded-answer allowance for a school's tier, or None = unlimited."""
    tier = get_ai_grading_tier(school)
    if not tier:
        return 0
    from billing.models import ModuleProduct
    product = ModuleProduct.objects.filter(module=tier, is_active=True).first()
    return product.questions_per_month if product else None


def ai_grading_offer(user):
    """Why this student sees (or doesn't see) AI-graded questions.

    ``student_can_be_ai_graded`` answers yes/no; the quiz also needs to know
    *why*, because only one of the two "no"s is worth showing a promotion for.
    A school student whose school did not buy the module cannot do anything
    about it themselves — offering them an upgrade would be pointing a child at
    a purchase they cannot make. A Student Basic student can.

    Returns ``(entitled, can_upgrade)``.
    """
    from billing.models import StudentModule
    from billing.entitlements import student_has_module

    entitled = student_can_be_ai_graded(user)
    can_upgrade = (not entitled) and student_has_module(
        user, StudentModule.MODULE_BASIC)
    return entitled, can_upgrade


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

    limit = get_ai_grading_limit(school)
    if limit is None:
        return (True, 0, None)

    from billing.models import AIGradingUsage
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

    # Warn the institute on the way up (75/80/85/90/95%) and once more when the
    # allowance is gone, so running out is never first noticed as children
    # silently stopping being marked. Each rung fires once a month; the call is
    # a no-op between thresholds and never raises. See billing/quota_alerts.py.
    limit = get_ai_grading_limit(school)
    if limit:
        from billing.quota_alerts import check_grading_quota_alerts
        used = (
            AIGradingUsage.objects
            .filter(school=school, period_start=period_start)
            .values_list('answers_graded', flat=True)
            .first()
        ) or 0
        check_grading_quota_alerts(school, used, limit)


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

def grade_extended_answer(question, answer_text: str, school=None, student=None):
    """
    Grade a student's extended answer.

    Pass ``student`` wherever the answer belongs to a known student. AI grading
    costs money per call, and a student who is not entitled to it must not have
    a call made on their behalf — the quiz already never offers them the
    question, and this is the same rule at the point where the money is spent,
    so a teacher-assigned worksheet or homework cannot route around it. Their
    answer is left for the teacher instead of being marked, exactly as a
    quota-exhausted one is.

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
        result['is_correct'], result['is_partial'] = verdict(
            result.get('score_fraction', 0.0))
        return result

    # ── 2. Is this student AI-graded at all? ─────────────────────────────
    # After the cache, deliberately: a cached verdict costs nothing and is the
    # same answer this question has already been given, so withholding it would
    # save no money and only lose the student a mark.
    if student is not None and not student_can_be_ai_graded(student):
        return {
            'is_correct': False,
            'score_fraction': 0.0,
            'feedback': (
                'This question is marked by the AI grader, which is not part '
                'of your plan. Your teacher will review this answer.'
            ),
            'cache_hit': False,
            'input_tokens': 0,
            'output_tokens': 0,
            'not_entitled': True,
        }

    # ── 3. Quota check ────────────────────────────────────────────────────
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

    # ── 4. Claude evaluates the proof mathematically ──────────────────────
    result = _call_claude_grade(question, answer_text, normalised)

    # ── 5. Record usage ───────────────────────────────────────────────────
    if school:
        record_ai_grading_usage(school, result['input_tokens'], result['output_tokens'])

    # ── 6. Store in cache ─────────────────────────────────────────────────
    # A failure is not a verdict, so it is never cached: an outage or an
    # unreadable diagram would otherwise be handed back as a cached 0.0 to
    # every later student who wrote the same answer, long after the cause
    # was fixed and without another API call to notice.
    if not result.get('error'):
        _store_cache(question.pk, normalised, result)

    # ── 7. New correct path → update rubric ──────────────────────────────
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
            # The verdict is recomputed from the stored score rather than read
            # from the stored ``is_correct``: an entry cached under the old
            # 0.6 pass mark would otherwise keep returning ✅ Correct for a
            # 0.65 answer forever, since a cache hit never re-grades.
            parsed = _parse_cache_feedback(e.feedback)
            score = e.score_fraction
            is_correct, is_partial = verdict(score)
            return {
                'is_correct': is_correct,
                'score_fraction': score,
                'is_partial': is_partial,
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


class QuestionImageUnavailable(Exception):
    """A question HAS a diagram, but it could not be handed to the grader."""


# The formats the Anthropic API accepts, by file extension. Anything else is
# an error rather than a guess: the old code labelled every unknown extension
# ``image/jpeg``, so an SVG or BMP upload was rejected by the API and surfaced
# as a generic "grading failed" with no hint of the real cause.
_SUPPORTED_IMAGE_TYPES = {
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}


def _fetch_image_block(question):
    """
    Return an Anthropic image content block for the question's diagram.
    Fetches the image from Django storage (S3/Spaces) and base64-encodes it.

    Returns None ONLY when the question has no diagram at all. A question that
    has one which cannot be read raises ``QuestionImageUnavailable`` — grading
    on the text alone would mark a child against a diagram the grader never
    saw, and would do it silently.
    """
    if not question.image:
        return None

    import base64
    from django.core.files.storage import default_storage

    # question.image.name is the storage key (e.g. 'questions/year7/...')
    name = question.image.name
    media_type = _SUPPORTED_IMAGE_TYPES.get(os.path.splitext(name.lower())[1])
    if media_type is None:
        raise QuestionImageUnavailable(
            f'unsupported diagram format for "{name}" — the grader accepts '
            f'{", ".join(sorted(_SUPPORTED_IMAGE_TYPES))}'
        )
    try:
        with default_storage.open(name, 'rb') as f:
            raw = f.read()
    except Exception as exc:
        raise QuestionImageUnavailable(
            f'could not read diagram "{name}" from storage: {exc}'
        ) from exc
    if not raw:
        raise QuestionImageUnavailable(f'diagram "{name}" is empty')

    encoded = base64.standard_b64encode(raw).decode('utf-8')
    return {
        'type': 'image',
        'source': {'type': 'base64', 'media_type': media_type, 'data': encoded},
    }


def _grading_unavailable(error, feedback):
    """The result dict for "no verdict was reached" — never a score of record.

    Callers read ``error`` and leave the answer for the teacher instead of
    counting it wrong, and ``grade_extended_answer`` keeps it out of the
    cache, so a transient failure is not served back as 0.0 for ever.
    """
    return {
        'is_correct': False,
        'is_partial': False,
        'score_fraction': 0.0,
        'feedback': feedback,
        'what_was_correct': '',
        'what_to_add': '',
        'cache_hit': False,
        'input_tokens': 0,
        'output_tokens': 0,
        'error': str(error),
    }


# Words in the FEEDBACK that mean the mark and the words disagree. Claude
# sometimes writes "Excellent work, mathematically complete" and returns
# score_fraction=0.5; where the words are unambiguous they are trusted over
# the number.
_POSITIVE_SIGNALS = (
    'excellent', 'perfect', 'correct', 'valid', 'complete',
    'well done', 'great', 'mathematically sound',
    'fully correct', 'demonstrates a clear understanding',
)

# "full marks" is deliberately NOT in that list. The prompt asks Claude to say
# what is missing "for full marks", so the phrase turns up in exactly the
# feedback that means the opposite — "…state a rule like 'subtract 3 each
# time' for full marks" was read as praise, bumped from 0.3 to 0.85, and a
# child who wrote an ADDITION pattern for a subtraction question was told
# ✅ Correct beneath feedback explaining why it was not.
_NEGATIVE_SIGNALS = (
    'incorrect', 'wrong', 'incomplete', 'missing', 'not shown',
    'no credit', 'does not', "doesn't", 'did not', "didn't",
    'instead of', 'needs to', 'should have', 'failed', 'error',
    'invalid',
)

# What Claude puts in ``what_to_add`` when nothing is missing.
_NOTHING_TO_ADD = ('', 'nothing', 'none', 'n/a', 'na', '-', '.')


def _says(words, signals):
    """True when *words* contains any of *signals* as whole words.

    Whole words, not substrings: "incorrect" contains "correct" and "invalid"
    contains "valid", so a substring test read the two plainest ways of saying
    an answer is wrong as praise — and the downward check, which needs "no
    positive words present", could then never fire on either.
    """
    return any(re.search(rf'\b{re.escape(signal)}\b', words) for signal in signals)


def reconcile_score(score_fraction, feedback, what_to_add=''):
    """Settle a score that disagrees with the words beside it.

    Returns ``(score, note)`` — *note* is empty when nothing was changed, and
    otherwise says what was done, for the log.

    A score is only raised when the answer is *not missing anything*.
    ``what_to_add`` is Claude's own structured answer to "what must be added
    for full marks", and the prompt tells it to say "Nothing" when the answer
    is complete — a far better signal than reading praise out of prose, which
    is what got this wrong: feedback naming a real gap was read as positive
    because it ended "for full marks", and the failing score it came with was
    overwritten.

    Lowering needs no such guard: feedback that says something is wrong, with
    no praise anywhere in it, is not a passing answer however it was scored —
    it drops below the pass mark, where an answer earns nothing.
    """
    words = (feedback or '').lower()
    positive = _says(words, _POSITIVE_SIGNALS)
    negative = _says(words, _NEGATIVE_SIGNALS)
    complete = (what_to_add or '').strip().lower().rstrip('.') in _NOTHING_TO_ADD

    if positive and not negative and complete and score_fraction < PASS_MARK:
        # Full marks, not a near-miss: "nothing to add" and praise with no
        # correction in it describe an answer with nothing wrong with it, and
        # anything short of 1.0 would show the student an amber "partly
        # correct" the feedback does not support.
        return FULL_MARKS, (f'feedback positive and nothing left to add, but '
                            f'score={score_fraction:.2f} — raised to '
                            f'{FULL_MARKS:.2f}')

    if negative and not positive and score_fraction >= PASS_MARK:
        return 0.35, (f'feedback negative but score={score_fraction:.2f} '
                      f'— dropped to 0.35')

    return score_fraction, ''


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
    #
    # A diagram that exists but cannot be loaded stops the grading here. The
    # answer was written against a picture, so marking it on the text alone
    # is marking it against something the grader cannot see — and the student
    # would be told a score, not that half the question went missing.
    try:
        image_block = _fetch_image_block(question)
    except QuestionImageUnavailable as exc:
        logger.error(
            'Q%s not graded: %s — the answer was left for the teacher rather '
            'than graded without the diagram.', question.pk, exc,
        )
        return _grading_unavailable(
            f'diagram unavailable: {exc}',
            "This question's diagram could not be loaded, so the answer was "
            'not marked automatically. Your teacher will review it.',
        )

    system = (
        'You are an expert teacher grading student extended answers across subjects '
        'including mathematics, science, and language arts.\n\n'

        'YOUR PRIMARY JOB: Evaluate whether the student\'s answer correctly and '
        'completely addresses the question. Credit substance and meaning, not '
        'phrasing — a student who expresses the right idea in different words '
        'should not lose marks.\n\n'

        'QUESTION TYPE GUIDANCE:\n'
        '• DEFINITIONS — Award credit for each key concept or keyword that is '
        'correctly included. A definition with 3 of 4 required elements earns ~0.75 '
        '— a missing required element is never full marks. '
        'Missing all key elements earns 0.0. Different but accurate wording is fine.\n'
        '• EXPLANATIONS / REASONING — Check whether the key ideas are present and '
        'the reasoning is logically sound. Partial explanations earn partial credit.\n'
        '• MATHEMATICAL PROOFS — Verify the argument step by step. A different valid '
        'proof path earns the same marks as the reference. Implicit trivial steps are fine.\n'
        '• SHORT ANSWERS — One or two correct key points earns near-full credit.\n'
        '• SEQUENCES, NUMBER PATTERNS, ORDERED STEPS — THE ORDER IS PART OF THE '
        'ANSWER. Check the values the student wrote against each other, in the '
        'order they wrote them: every consecutive pair must follow the rule the '
        'question asks for. A sequence that runs the wrong way (going up when the '
        'question asks for a subtraction / decreasing pattern, or down when it '
        'asks for an addition one), or the right values in the wrong order, is '
        'WRONG — score it at most 0.3 — however neat or plausible the numbers '
        'look on their own. If the question also asks for the rule, a rule that '
        'contradicts the numbers beside it is wrong too.\n\n'

        'THE RUBRIC (if provided) shows one correct approach. Students may express '
        'the same ideas differently. A different path that is correct earns full marks.\n\n'

        'THE DIAGRAM (if shown) defines labels/notation. Students need not re-state '
        'what is visible in the diagram.\n\n'

        'SCORING — what the student is shown for the score you give:\n'
        '  1.0        ✅ Correct, full marks. Give this ONLY when there is '
        'nothing to add and nothing to correct.\n'
        '  0.75-0.99  🟡 Partly correct — earns that share of the marks. This '
        'is where an answer with a real but minor gap belongs.\n'
        '  below 0.75 ❌ Wrong — earns no marks at all.\n'
        'So an answer you are writing a correction about is never 1.0, and an '
        'answer that is fundamentally wrong is never 0.75 or more. Within the '
        'bands:\n'
        '  1.0  — Fully correct and complete; nothing to add.\n'
        '  0.9  — Right, with an imprecision worth naming.\n'
        '  0.8  — Right approach carried through, one minor omission.\n'
        '  0.5  — Some right ideas, but a key element is missing or wrong.\n'
        '  0.1  — Only a small fragment is correct.\n'
        '  0.0  — Fundamentally wrong, or no attempt.\n\n'

        'CONSISTENCY: Your score_fraction and feedback MUST agree. '
        'If feedback says "correct/complete/well done" with no correction in '
        'it, score 1.0. If feedback names anything the student got wrong or '
        'left out, score below 1.0 — and below 0.75 when what is missing is '
        'part of the answer rather than a detail. '
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
  "is_correct": <true only if score_fraction is 1.0>,
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

        # claude-sonnet-4-20250514 is deprecated; default to Opus for grading
        # accuracy (it auto-marks student answers), env-overridable via
        # AI_GRADING_MODEL. Thinking is explicitly disabled: on Opus 5 (and later)
        # adaptive thinking is ON by default and would consume the tight 500-token
        # budget, truncating the JSON verdict. Disabled thinking is valid at the
        # default effort ("high").
        response = client.messages.create(
            model=os.environ.get('AI_GRADING_MODEL', 'claude-opus-5'),
            max_tokens=500,
            thinking={"type": "disabled"},
            system=system,
            messages=[{'role': 'user', 'content': user_content}],
        )
        if getattr(response, 'stop_reason', None) == 'refusal':
            # Safety refusal — hand off to the teacher rather than fabricating a
            # score. Raised here, handled by the fallback below.
            raise ValueError('grading declined by content safety')
        import json
        # Take the first text block rather than content[0]: a future model /
        # thinking setting could put a non-text block first.
        text = next(
            (b.text for b in response.content if getattr(b, 'type', None) == 'text'),
            '',
        ).strip()
        # Strip markdown code fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Opus can prepend reasoning prose to the answer when thinking is
            # off; fall back to the outermost JSON object in the text.
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if not match:
                raise
            data = json.loads(match.group(0))
        score_fraction = float(data.get('score_fraction', 0.0))
        score_fraction = max(0.0, min(1.0, score_fraction))
        feedback = str(data.get('feedback', ''))
        what_was_correct = str(data.get('what_was_correct', ''))
        what_to_add = str(data.get('what_to_add', ''))

        # ── Consistency check ────────────────────────────────────────────
        score_fraction, adjustment = reconcile_score(
            score_fraction, feedback, what_to_add)
        is_correct, is_partial = verdict(score_fraction)
        if adjustment:
            logger.warning(
                'Grading inconsistency Q%s: %s', question.pk, adjustment)
        # ────────────────────────────────────────────────────────────────

        return {
            'is_correct': is_correct,
            'is_partial': is_partial,
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
        return _grading_unavailable(
            exc,
            'Automatic grading failed. Your teacher will review this answer.',
        )


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
