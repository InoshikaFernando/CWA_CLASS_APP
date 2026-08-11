"""
Second-opinion verification for AI Import (vision-enabled).

Two independent OpenAI (GPT) passes catch the failures Claude is most prone to on
figure-heavy worksheets, each flagging a suspect question ``needs_review`` (with a
short ``review_reason``) so the teacher double-checks it on the preview screen
before it enters the question bank:

- ``verify_answers`` re-examines EACH question against its source-page image,
  validating Claude's classification, answer, and transcription (below);
- ``verify_images`` looks at each question together with its *attached image* and
  flags pictures that don't belong — decorative art, a neighbour's figure, a bad
  crop, or an image on a question that needs none (further down this module).

Both are best-effort and self-gating (a no-op without ``OPENAI_API_KEY``) and
never fail the import. The answer verifier is documented first.

For each question, ``verify_answers`` reports three things:

1. the ``question_type`` it would assign — validating Claude's *classification*;
2. the final ``answer`` it independently derives — validating Claude's *answer*;
3. whether Claude's transcription faithfully matches what is printed on the page
   — catching numbers / operators / options the classifier misread.

Any disagreement — wrong type, wrong answer, or a mis-transcribed question — sets
``needs_review=True`` with a short ``review_reason`` so the teacher double-checks
it on the preview screen before it enters the question bank.

Design (unchanged in spirit from the text-only verifier it grew out of):

- Best-effort, never a hard gate. Runs only when ``OPENAI_API_KEY`` is configured
  and the verifier isn't explicitly disabled (``AI_IMPORT_VERIFY_ENABLED=0``).
  With no key the pass is skipped and imports run Claude-only, exactly as before.
- If a verifier call fails, the import proceeds with those questions unverified
  and a warning is logged — a flaky or slow second opinion must never sink a
  teacher's upload.
- It never edits answers or unflags anything; it only ROUTES uncertain questions
  to a human.
- GPT usage is reported back separately from Claude's token ledger (GPT is priced
  differently) so per-upload cost accounting stays honest.

Vision: each question is checked with its source-page screenshot attached
(resolved from ``source_page`` / ``image_page`` / the ref's page and looked up in
the ``page_images`` map). This is what lets the pass cover the types a text-only
verifier had to skip — computed (``long_division``, ``column_operation`` …) and
image-dependent / visual (``plot_*``, ``read_graph``, ``measure``,
``number_line``) — which can only be re-solved fairly when the model can see the
figure. Set ``AI_IMPORT_VERIFY_VISION=0`` to force a text-only pass (cheaper; the
transcription check is then skipped because there is no image to compare against).
"""
import json
import logging
import os
import re

from django.conf import settings

logger = logging.getLogger(__name__)


# Coarse buckets over the classifier's question_type taxonomy. The verifier only
# flags a *cross-bucket* classification disagreement — within a bucket the types
# are interchangeable enough (short_answer vs calculation, plot_points vs
# plot_line) that a mismatch is noise, and a false disagreement costs trust. Fine
# distinctions inside a bucket are caught by the answer / transcription checks
# instead, not by the type check.
_TYPE_BUCKET = {
    'multiple_choice': 'choice', 'true_false': 'choice',
    'short_answer': 'free', 'fill_blank': 'free', 'calculation': 'free',
    'column_operation': 'free', 'long_division': 'free',
    'plot_points': 'plot', 'plot_line': 'plot', 'identify_coords': 'plot',
    # read_graph / measure / number_line all "read a numeric value off a visual"
    # and are easily confused with one another — one bucket so a read_graph↔measure
    # slip isn't reported as a classification disagreement.
    'read_graph': 'readoff', 'measure': 'readoff', 'number_line': 'readoff',
}

# The full type list handed to GPT so its independent classification uses the same
# vocabulary Claude did (keeps _TYPE_BUCKET lookups meaningful on both sides).
_ALLOWED_TYPES = sorted(_TYPE_BUCKET)


def verification_enabled():
    """Whether the GPT verifier should run.

    On only when an OpenAI key is configured AND the feature isn't explicitly
    switched off. Keeping the toggle here means the caller never has to know the
    rules — a Claude-only deployment simply leaves ``OPENAI_API_KEY`` empty.
    """
    if os.environ.get('AI_IMPORT_VERIFY_ENABLED', '1') == '0':
        return False
    return bool(getattr(settings, 'OPENAI_API_KEY', ''))


def _vision_enabled():
    """Whether the verifier may attach source-page images (default on)."""
    return os.environ.get('AI_IMPORT_VERIFY_VISION', '1') != '0'


def _get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _correct_texts(q):
    """The answer strings Claude marked correct for a question (may be several).

    short_answer / fill_blank routinely carry multiple acceptable forms (e.g.
    "60 months" and "60"), all ``is_correct`` — the verifier agrees when it
    matches ANY of them. Empty for computed types whose answer is derived later.
    """
    return [
        (a.get('text') or '').strip()
        for a in (q.get('answers') or [])
        if a.get('is_correct') and (a.get('text') or '').strip()
    ]


def _expected_answers(q):
    """Every accepted correct-answer form to compare GPT against.

    Covers both storage shapes: the ``is_correct`` option texts (multiple_choice /
    short_answer / …) AND the ``numeric_answer`` used by ``read_graph`` /
    ``measure`` — whose value lives in a numeric field, not the ``answers`` array,
    so without this the verifier could never check a protractor / dial read-off.
    """
    forms = _correct_texts(q)
    na = q.get('numeric_answer')
    if na is not None and str(na).strip():
        forms = forms + [str(na).strip()]
    return forms


def _answer_tolerance(q):
    """The question's ± band as a float (read_graph / measure), or None for exact."""
    raw = q.get('answer_tolerance')
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        return abs(float(raw))
    except (TypeError, ValueError):
        return None


def _resolve_page(q):
    """The 1-based source page for a question, or None if it can't be determined.

    Tries the explicit ``source_page`` first, then ``image_page`` (set when the
    question carries a drawn figure), then the leading ``pageN`` of an embedded
    ``image_ref`` (e.g. "page3_img1.png"). None means no page screenshot can be
    attached, so the question is verified from its text alone.
    """
    for key in ('source_page', 'image_page'):
        v = q.get(key)
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and v > 0:
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
    m = re.match(r'page(\d+)', str(q.get('image_ref') or ''), re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _types_conflict(claude_type, gpt_type):
    """Whether two classifications disagree enough to flag (cross-bucket only).

    Unknown / missing type names (either side) never conflict — no vocabulary, no
    signal. Same type or same bucket never conflicts.
    """
    if not claude_type or not gpt_type or claude_type == gpt_type:
        return False
    cb = _TYPE_BUCKET.get(claude_type)
    gb = _TYPE_BUCKET.get(gpt_type)
    if cb is None or gb is None:
        return False
    return cb != gb


def _leading_number(text):
    """The first numeric value in a string as a float, or None.

    Lets "60 months" and "60" (or "$4.50" and "4.50") compare equal so a mere
    unit / currency difference isn't reported as a disagreement.
    """
    m = re.search(r'-?\d+(?:\.\d+)?', text.replace(',', ''))
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _norm(text):
    """Loose normalisation for answer comparison (case / space / punctuation)."""
    text = str(text).strip().lower()
    for ch in (',', '$', ' '):
        text = text.replace(ch, '')
    return text.rstrip('.')


def _answers_agree(gpt_answer, correct_texts, tolerance=None):
    """Whether GPT's answer matches any of Claude's accepted answer forms.

    Agreement is deliberately lenient (exact-after-normalisation OR equal leading
    number, OR within ``tolerance`` when one is given for a read-off type) because
    a disagreement only routes the question to a teacher — a missed nuance costs a
    glance, a false disagreement costs trust. When in doubt we treat it as
    agreement and stay quiet.
    """
    g = _norm(gpt_answer)
    if not g:
        return True  # no usable answer from GPT → no signal, don't flag
    gnum = _leading_number(g)
    for c in correct_texts:
        cn = _norm(c)
        if g == cn:
            return True
        cnum = _leading_number(cn)
        if gnum is not None and cnum is not None:
            if gnum == cnum:
                return True
            if tolerance is not None and abs(gnum - cnum) <= tolerance:
                return True
    return False


def _build_payload(batch):
    """Compact per-question payload for the verifier prompt.

    Multiple-choice / true-false questions carry their options so GPT picks from
    the same list Claude did (a fair like-for-like comparison); other types are
    solved open-ended. Claude's own answer is deliberately withheld so GPT solves
    blind — only the question and (for choice types) its options are shown.
    """
    payload = []
    for idx, q in batch:
        item = {
            'index': idx,
            'question_text': q.get('question_text', ''),
            'claimed_type': q.get('question_type'),
        }
        if q.get('question_type') in ('multiple_choice', 'true_false'):
            item['options'] = [
                (a.get('text') or '').strip()
                for a in (q.get('answers') or [])
                if (a.get('text') or '').strip()
            ]
        payload.append(item)
    return payload


_VERIFY_SYSTEM_PROMPT = (
    "You are a meticulous maths teacher independently auditing a colleague's "
    "answer key that was auto-extracted from a worksheet. When a page image is "
    "provided it is the ORIGINAL page the questions came from — trust the image "
    "over the extracted text. For EACH question do THREE things:\n"
    "1. classify: choose the single best question_type from this list — "
    + ", ".join(_ALLOWED_TYPES) + ".\n"
    "2. solve: work it out YOURSELF from scratch and report your final answer. "
    "Do not assume the colleague's answer is correct (it is not shown to you). "
    "For multiple_choice / true_false choose exactly one given option and copy "
    "its text verbatim; for other types give the concise final answer only (a "
    "number, word, or short phrase). If a question needs a figure you cannot "
    "read, or you cannot solve it confidently, set confident=false and leave "
    "answer empty. Never guess.\n"
    "3. check transcription: if a page image is provided, confirm the extracted "
    "question_text matches what is printed (numbers, operator, options, the "
    "value an arrow/protractor points to). If it does not, set "
    "transcription_ok=false and give a one-line issue. If NO page image is "
    "provided, set transcription_ok=true (you cannot judge it).\n"
    "Report every question via the report_answers tool."
)


_VERIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "report_answers",
        "description": (
            "Report your independent classification, answer, and transcription "
            "check for each question."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {
                                "type": "integer",
                                "description": "The question's index from the input.",
                            },
                            "question_type": {
                                "type": "string",
                                "enum": _ALLOWED_TYPES,
                                "description": "The type YOU would assign this question.",
                            },
                            "answer": {
                                "type": "string",
                                "description": "Your own final answer (empty if not confident).",
                            },
                            "confident": {
                                "type": "boolean",
                                "description": "True only if you solved it confidently.",
                            },
                            "transcription_ok": {
                                "type": "boolean",
                                "description": (
                                    "False if the extracted question_text does not match "
                                    "the page image. True when it matches or no image was "
                                    "provided."
                                ),
                            },
                            "issue": {
                                "type": "string",
                                "description": "One line on the transcription problem (empty if none).",
                            },
                        },
                        "required": [
                            "index", "question_type", "answer", "confident",
                            "transcription_ok",
                        ],
                    },
                },
            },
            "required": ["results"],
        },
    },
}


def _verify_batch(client, model, payload, image_b64=None, has_image=False):
    """One verifier request over a batch of questions sharing a source page.

    ``image_b64`` (a base64 JPEG page screenshot), when present and vision is on,
    is attached so the model can see the questions as printed. Returns
    ``(results_by_index, usage)`` where each result is
    ``{'question_type', 'answer', 'confident', 'transcription_ok', 'issue',
    'has_image'}`` and usage is ``{'input_tokens', 'output_tokens'}``. Raises on
    transport / parse failure so the orchestrator can log it and move on.
    """
    intro = (
        "Classify, solve and (if a page image is shown) transcription-check each "
        "of these questions, then report via report_answers:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    user_content = [{"type": "text", "text": intro}]
    if image_b64 and has_image:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        })

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _VERIFY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        tools=[_VERIFY_TOOL],
        tool_choice={"type": "function", "function": {"name": "report_answers"}},
    )

    message = resp.choices[0].message
    tool_calls = getattr(message, 'tool_calls', None) or []
    if not tool_calls:
        raise ValueError('verifier returned no tool call')

    data = json.loads(tool_calls[0].function.arguments)
    results = {}
    for r in data.get('results', []):
        try:
            idx = int(r['index'])
        except (KeyError, TypeError, ValueError):
            continue
        results[idx] = {
            'question_type': (r.get('question_type') or '').strip() or None,
            'answer': (r.get('answer') or '').strip(),
            'confident': bool(r.get('confident')),
            # No image → the model cannot judge transcription, so treat as OK
            # regardless of what it returned (belt-and-braces with the prompt).
            'transcription_ok': (
                bool(r.get('transcription_ok', True)) if has_image else True
            ),
            'issue': (r.get('issue') or '').strip(),
            'has_image': has_image,
        }

    usage = getattr(resp, 'usage', None)
    token_usage = {
        'input_tokens': getattr(usage, 'prompt_tokens', 0) or 0,
        'output_tokens': getattr(usage, 'completion_tokens', 0) or 0,
    }
    return results, token_usage


def verify_answers(questions, page_images=None, client=None, *, force=False):
    """Run the GPT verifier over ``questions``, flagging disagreements in place.

    Every question that isn't already flagged is re-examined. When a
    ``page_images`` map (``{page_num: base64_jpeg_screenshot}``) is supplied and
    vision is enabled, each question is checked with its source page attached so
    computed and image-dependent types are covered too; otherwise the pass falls
    back to a text-only check. A question is flagged ``needs_review`` when GPT
    confidently classifies it into a different type bucket, derives a different
    answer, or (with an image) reports the transcription doesn't match the page.
    Never unflags or edits answers — it only routes uncertain questions to a
    human.

    Args:
        questions: the classified question dicts (mutated in place).
        page_images: optional ``{page_num: base64_jpeg}`` source-page screenshots.
        client: an OpenAI client (injected in tests); built on demand otherwise.
        force: run even if ``verification_enabled()`` is False (tests only).

    Returns:
        A summary dict when the pass ran, or ``None`` when the verifier is
        disabled / there was nothing to check.
    """
    if not force and not verification_enabled():
        return None

    candidates = [
        (i, q) for i, q in enumerate(questions or []) if not q.get('needs_review')
    ]
    if not candidates:
        return None

    model = os.environ.get('AI_IMPORT_VERIFY_MODEL', 'gpt-4o')
    chunk_size = max(1, int(os.environ.get('AI_IMPORT_VERIFY_CHUNK', '40')))
    use_vision = _vision_enabled() and bool(page_images)

    try:
        client = client or _get_openai_client()
    except Exception as exc:  # missing SDK / bad key construction
        logger.warning('AI import verifier unavailable, skipping: %s', exc)
        return {'model': model, 'vision': use_vision, 'checked': 0, 'flagged': 0,
                'type_flags': 0, 'answer_flags': 0, 'transcription_flags': 0,
                'input_tokens': 0, 'output_tokens': 0, 'error': str(exc)}

    # Group by source page so each page image is sent once, shared by every
    # question on it. Questions with no resolvable page (or no screenshot) fall
    # into the text-only group under key None.
    groups = {}
    for i, q in candidates:
        pg = _resolve_page(q) if use_vision else None
        if pg is None or not page_images.get(pg):
            pg = None
        groups.setdefault(pg, []).append((i, q))

    by_index = {i: q for i, q in candidates}
    all_results = {}
    in_tok = out_tok = 0
    error = None

    for pg, items in groups.items():
        img = page_images.get(pg) if (pg is not None and page_images) else None
        has_image = img is not None
        for start in range(0, len(items), chunk_size):
            batch = items[start:start + chunk_size]
            payload = _build_payload(batch)
            try:
                results, usage = _verify_batch(
                    client, model, payload, image_b64=img, has_image=has_image)
            except Exception as exc:
                # Best-effort: a failed batch leaves its questions unverified
                # rather than sinking the whole import. Surfaced in the summary.
                logger.warning('AI import verifier batch failed: %s', exc)
                error = str(exc)
                continue
            all_results.update(results)
            in_tok += usage['input_tokens']
            out_tok += usage['output_tokens']

    flagged = type_flags = answer_flags = transcription_flags = 0
    for idx, verdict in all_results.items():
        q = by_index.get(idx)
        if q is None or q.get('needs_review'):
            continue

        reasons = []

        # 1. Transcription (only trustworthy when the model actually saw the page).
        if verdict['has_image'] and verdict['transcription_ok'] is False \
                and verdict['issue']:
            reasons.append(
                f'Second-opinion (vision) flagged a possible extraction error: '
                f'{verdict["issue"]}')
            transcription_flags += 1

        # 2. Classification — cross-bucket disagreement from a confident verifier.
        if verdict['confident'] and _types_conflict(
                q.get('question_type'), verdict['question_type']):
            reasons.append(
                f'Second-opinion classified this as "{verdict["question_type"]}", '
                f'not "{q.get("question_type")}".')
            type_flags += 1

        # 3. Answer — only where Claude has a stored answer to compare against
        # (the is_correct options, or the numeric_answer of a read-off type),
        # honouring the question's tolerance band when it has one.
        correct = _expected_answers(q)
        if verdict['confident'] and verdict['answer'] and correct \
                and not _answers_agree(verdict['answer'], correct,
                                       tolerance=_answer_tolerance(q)):
            reasons.append(
                f'Second-opinion check disagreed: verifier answered '
                f'"{verdict["answer"]}" vs "{correct[0]}".')
            answer_flags += 1

        if reasons:
            q['needs_review'] = True
            q['review_reason'] = ' '.join(reasons)
            flagged += 1

    return {
        'model': model,
        'vision': use_vision,
        'checked': len(all_results),
        'flagged': flagged,
        'type_flags': type_flags,
        'answer_flags': answer_flags,
        'transcription_flags': transcription_flags,
        'input_tokens': in_tok,
        'output_tokens': out_tok,
        'error': error,
    }


# ---------------------------------------------------------------------------
# Visual comparison guard (deterministic, no API)
# ---------------------------------------------------------------------------
#
# The answer verifier above flags a question only when the second model
# DISAGREES with Claude. That leaves one class exposed: "which of these two
# figures is larger, if any" questions, where BOTH models routinely read the
# same wrong value off a coarse figure and so agree on a wrong answer — the
# disagreement detector never fires. Deciding whether two angles / lengths drawn
# on a grid are equal is at the edge of vision-model reliability, and "equal" is
# the worst case: the true difference is zero, so any noise tips the model to one
# side. It fails BOTH ways in practice — "larger" when they are equal, "equal"
# when they are not — so the answer cannot be trusted in either direction. Rather
# than try to correct it, we route the whole class to a human. This runs
# deterministically (no OpenAI key needed) and only touches questions that carry
# a figure, so pure-text comparisons ("which is larger, 2/3 or 3/5?") — which the
# models DO handle reliably — are left alone.

# Comparative / superlative language that marks a "which figure is bigger" ask.
# Bare "equal" is deliberately NOT here (it appears in plenty of non-comparison
# prompts, e.g. "a triangle with equal sides"); the equal-as-an-option signal
# below carries that case instead.
_COMPARISON_RE = re.compile(
    r'\b(?:'
    r'larger|largest|bigger|biggest|greater|greatest|'
    r'smaller|smallest|longer|longest|shorter|shortest|'
    r'wider|widest|narrower|narrowest|taller|tallest|steeper|steepest|'
    r'same\s+size|compare|comparison'
    r')\b',
    re.IGNORECASE,
)

# Answer-option text that marks a multiple-choice question as a comparison with
# an "equal / neither" choice (e.g. "They are the same size", "Equal").
_EQUAL_OPTION_RE = re.compile(
    r'\b(?:equal|same(?:\s+size)?|neither|identical)\b', re.IGNORECASE)


def _has_figure(q):
    """Whether a question carries a drawn or embedded figure to read off."""
    return bool(q.get('image_ref') or q.get('image_page'))


def _is_visual_comparison(q):
    """A "which figure is larger / are they equal" question that has a figure.

    Requires an attached figure AND comparison language — either in the question
    text (comparative/superlative wording) or as an "equal / same / neither"
    answer option. The figure requirement keeps text-only comparisons, which the
    models answer reliably, out of the net.
    """
    if not _has_figure(q):
        return False
    if _COMPARISON_RE.search(q.get('question_text') or ''):
        return True
    for a in (q.get('answers') or []):
        if _EQUAL_OPTION_RE.search(a.get('text') or ''):
            return True
    return False


def flag_visual_comparisons(questions):
    """Route figure-comparison questions to human review, unconditionally.

    A deterministic safety net for the answer verifier's blind spot — two models
    sharing the same wrong read of a figure, so nothing disagrees and nothing is
    flagged. Sets ``needs_review`` (with a reason) on every not-already-flagged
    visual-comparison question and returns how many it flagged. Runs without an
    OpenAI key and never edits answers — it only routes.

    Args:
        questions: the classified question dicts (mutated in place).

    Returns:
        The number of questions newly flagged for review.
    """
    flagged = 0
    for q in (questions or []):
        if q.get('needs_review') or not _is_visual_comparison(q):
            continue
        q['needs_review'] = True
        q['review_reason'] = (
            'Figure-comparison question (e.g. comparing angles or lengths in a '
            'diagram): the AI cannot reliably judge these from the image, so it '
            'has been routed to you to confirm the correct answer.'
        )
        flagged += 1
    return flagged


# ---------------------------------------------------------------------------
# Image validation (vision second opinion)
# ---------------------------------------------------------------------------
#
# The answer verifier above re-solves TEXT questions. This pass tackles the other
# recurring failure: the WRONG picture attached to a question. After the classifier
# has finalised every question's image (embedded ref or a fresh crop), an
# independent vision model looks at each question together with the image the
# system attached to it and judges whether the image genuinely belongs. A confident
# "no" (decorative clip-art, a neighbouring question's figure, a bad crop, or an
# image on a question that needs none) flags the question ``needs_review`` so the
# teacher checks it on the preview screen. Like the answer verifier it is
# best-effort and self-gating — a no-op without an OpenAI key, and a failed call
# never sinks the import.


_IMAGE_MEDIA_TYPES = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'gif': 'image/gif', 'webp': 'image/webp',
}


def image_verification_enabled():
    """Whether the vision image-validator should run.

    On only when an OpenAI key is configured AND the feature isn't explicitly
    switched off (``AI_IMPORT_VERIFY_IMAGES_ENABLED=0``). Gated separately from
    the answer verifier so a deployment can run either pass without the other.
    """
    if os.environ.get('AI_IMPORT_VERIFY_IMAGES_ENABLED', '1') == '0':
        return False
    return bool(getattr(settings, 'OPENAI_API_KEY', ''))


def _image_media_type(ref):
    """MIME type for a data: URL from an image ref's extension (default PNG)."""
    ext = ref.rsplit('.', 1)[-1].lower() if '.' in (ref or '') else ''
    return _IMAGE_MEDIA_TYPES.get(ext, 'image/png')


def _image_verifiable(q):
    """A question is checkable when it carries a final attached image and isn't
    already going to the teacher for another reason."""
    if q.get('needs_review'):
        return False  # already flagged — a second reason adds nothing
    return bool(q.get('image_ref'))


_VERIFY_IMAGE_SYSTEM_PROMPT = (
    "You are a meticulous maths teacher checking that the RIGHT picture was "
    "attached to each question when a worksheet was digitised. For each item you "
    "get the question text and the single image the system attached to it. Decide "
    "whether that image is genuinely the figure this question needs.\n"
    "- matches=true when the image IS the diagram / graph / figure / picture the "
    "question refers to and needs to be answered.\n"
    "- matches=false when the image does NOT belong: it is decorative (clip-art, a "
    "photo, a header / border, a logo or mascot), it is clearly a DIFFERENT "
    "question's figure, it is the wrong crop or only a fragment of the figure, or "
    "the question can be fully answered from its text and needs no image at all.\n"
    "- Only report matches=false when you are CONFIDENT the image is wrong — set "
    "confident=false (and matches=true) whenever you are unsure, because a false "
    "alarm wastes a teacher's time. Give a one-line reason whenever matches=false.\n"
    "Report every item via the report_image_matches tool."
)


_VERIFY_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "report_image_matches",
        "description": "Report whether each question's attached image is the right one.",
        "parameters": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {
                                "type": "integer",
                                "description": "The item's index from the input.",
                            },
                            "matches": {
                                "type": "boolean",
                                "description": "True if the attached image is the figure this question needs.",
                            },
                            "confident": {
                                "type": "boolean",
                                "description": "True only if you are confident in this judgement.",
                            },
                            "reason": {
                                "type": "string",
                                "description": "One short sentence; required when matches is false.",
                            },
                        },
                        "required": ["index", "matches", "confident"],
                    },
                },
            },
            "required": ["results"],
        },
    },
}


def _verify_image_batch(client, model, batch, images_by_ref):
    """One vision request over a batch of ``(index, question)`` items.

    Interleaves each question's text with its attached image, then asks the model
    to report a match verdict per item. Returns ``(results_by_index, usage)`` where
    a result is ``{'matches': bool, 'confident': bool, 'reason': str}``. Raises on
    transport / parse failure so the orchestrator can log it and move on.
    """
    content = [{
        "type": "text",
        "text": (
            "Check each question below against the ONE image attached directly "
            "beneath it, then report every item via report_image_matches."
        ),
    }]
    for idx, q in batch:
        ref = q.get('image_ref')
        b64 = images_by_ref.get(ref)
        content.append({
            "type": "text",
            "text": (
                f"\nItem {idx} — question_type: {q.get('question_type')}\n"
                f"Question: {q.get('question_text', '')}\nAttached image:"
            ),
        })
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{_image_media_type(ref)};base64,{b64}"},
        })

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _VERIFY_IMAGE_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        tools=[_VERIFY_IMAGE_TOOL],
        tool_choice={"type": "function", "function": {"name": "report_image_matches"}},
    )

    message = resp.choices[0].message
    tool_calls = getattr(message, 'tool_calls', None) or []
    if not tool_calls:
        raise ValueError('image verifier returned no tool call')

    data = json.loads(tool_calls[0].function.arguments)
    results = {}
    for r in data.get('results', []):
        try:
            results[int(r['index'])] = {
                # Default matches=True so a malformed row never wrongly flags.
                'matches': bool(r.get('matches', True)),
                'confident': bool(r.get('confident')),
                'reason': (r.get('reason') or '').strip(),
            }
        except (KeyError, TypeError, ValueError):
            continue

    usage = getattr(resp, 'usage', None)
    token_usage = {
        'input_tokens': getattr(usage, 'prompt_tokens', 0) or 0,
        'output_tokens': getattr(usage, 'completion_tokens', 0) or 0,
    }
    return results, token_usage


def verify_images(questions, images_by_ref, client=None, *, force=False):
    """Vision-check each question's attached image, flagging mismatches in place.

    For every question with a final ``image_ref`` present in ``images_by_ref``, an
    independent vision model judges whether the image is the figure the question
    needs. A confident "no" sets ``needs_review=True`` and a ``review_reason`` so
    the teacher checks it. Never edits the image or the answer — it only routes
    questionable attachments to a human.

    Args:
        questions: the classified question dicts (mutated in place). Run this AFTER
            crop_figure_boxes so drawn figures already carry their final image_ref.
        images_by_ref: {ref: base64} for every embedded image and crop.
        client: an OpenAI client (injected in tests); built on demand otherwise.
        force: run even if ``image_verification_enabled()`` is False (tests only).

    Returns:
        A summary dict ``{'model', 'checked', 'flagged', 'input_tokens',
        'output_tokens', 'error'}`` when the pass ran, or ``None`` when the
        validator is disabled / there was nothing to check.
    """
    if not force and not image_verification_enabled():
        return None

    images_by_ref = images_by_ref or {}
    candidates = [
        (i, q) for i, q in enumerate(questions or [])
        if _image_verifiable(q) and images_by_ref.get(q.get('image_ref'))
    ]
    if not candidates:
        return None

    model = os.environ.get('AI_IMPORT_VERIFY_IMAGE_MODEL', 'gpt-4o')
    # Images are token-heavy, so batch fewer per request than the text verifier.
    chunk_size = max(1, int(os.environ.get('AI_IMPORT_VERIFY_IMAGE_CHUNK', '6')))

    try:
        client = client or _get_openai_client()
    except Exception as exc:  # missing SDK / bad key construction
        logger.warning('AI import image verifier unavailable, skipping: %s', exc)
        return {'model': model, 'checked': 0, 'flagged': 0,
                'input_tokens': 0, 'output_tokens': 0, 'error': str(exc)}

    by_index = {i: q for i, q in candidates}
    all_results = {}
    in_tok = out_tok = 0
    error = None

    for start in range(0, len(candidates), chunk_size):
        batch = candidates[start:start + chunk_size]
        try:
            results, usage = _verify_image_batch(client, model, batch, images_by_ref)
        except Exception as exc:
            # Best-effort: a failed batch leaves its images unchecked rather than
            # sinking the whole import. Surfaced in logs and the summary.
            logger.warning('AI import image verifier batch failed: %s', exc)
            error = str(exc)
            continue
        all_results.update(results)
        in_tok += usage['input_tokens']
        out_tok += usage['output_tokens']

    flagged = 0
    for idx, verdict in all_results.items():
        q = by_index.get(idx)
        if q is None or not verdict['confident'] or verdict['matches']:
            continue
        q['needs_review'] = True
        reason = verdict['reason'] or 'the attached image may not match this question'
        q['review_reason'] = f'Image check: {reason}'
        flagged += 1

    return {
        'model': model,
        'checked': len(all_results),
        'flagged': flagged,
        'input_tokens': in_tok,
        'output_tokens': out_tok,
        'error': error,
    }
