"""
Second-opinion verification for AI Import.

Two independent OpenAI (GPT) passes catch the two failures Claude is most prone
to on figure-heavy worksheets, each flagging a suspect question ``needs_review``
(with a short ``review_reason``) so the teacher double-checks it on the preview
screen before it enters the question bank:

- ``verify_answers`` re-solves each *text-answerable* question and flags answers
  the second model disagrees with (below);
- ``verify_images`` looks at each question together with its *attached image* and
  flags pictures that don't belong — decorative art, a neighbour's figure, a bad
  crop, or an image on a question that needs none (further down this module).

Both are best-effort and self-gating (a no-op without ``OPENAI_API_KEY``) and
never fail the import. The answer verifier is documented first:

This is a best-effort accuracy net, never a hard gate:

- It runs only when ``OPENAI_API_KEY`` is configured and the verifier isn't
  explicitly disabled (``AI_IMPORT_VERIFY_ENABLED=0``). With no key the pass is
  skipped and imports run Claude-only, exactly as before.
- If the verifier call fails, the import proceeds with unverified questions and
  a warning is logged — a flaky or slow second opinion must never sink a
  teacher's upload.
- Only questions whose correctness lives in the answer TEXT are checked
  (``multiple_choice``, ``true_false``, ``short_answer``, ``fill_blank``).
  Computed / structured types (``column_operation``, ``long_division``,
  ``plot_*``, ``measure``, ``number_line`` …) are graded deterministically
  elsewhere, and image-dependent questions can't be fairly re-solved from text
  alone, so both are skipped rather than flagged on false disagreements.

GPT usage is reported back separately from Claude's token ledger (GPT is priced
differently) so per-upload cost accounting stays honest.
"""
import json
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


# Question types whose correct answer is carried in the ``answers`` text and can
# therefore be independently re-derived by a text-only second model. Everything
# else is graded from structured specs / computed fields, so a GPT "answer" for
# it would be meaningless.
VERIFIABLE_TYPES = frozenset({
    'multiple_choice', 'true_false', 'short_answer', 'fill_blank',
})


def verification_enabled():
    """Whether the GPT verifier should run.

    On only when an OpenAI key is configured AND the feature isn't explicitly
    switched off. Keeping the toggle here means the caller never has to know the
    rules — a Claude-only deployment simply leaves ``OPENAI_API_KEY`` empty.
    """
    if os.environ.get('AI_IMPORT_VERIFY_ENABLED', '1') == '0':
        return False
    return bool(getattr(settings, 'OPENAI_API_KEY', ''))


def _get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _correct_texts(q):
    """The answer strings Claude marked correct for a question (may be several).

    short_answer / fill_blank routinely carry multiple acceptable forms (e.g.
    "60 months" and "60"), all ``is_correct`` — the verifier agrees when it
    matches ANY of them.
    """
    return [
        (a.get('text') or '').strip()
        for a in (q.get('answers') or [])
        if a.get('is_correct') and (a.get('text') or '').strip()
    ]


def _is_image_dependent(q):
    """True when the question relies on a figure the text verifier can't see.

    Runs BEFORE crop_figure_boxes, so a drawn figure still shows as
    image_page/image_box rather than a final image_ref — check all three signals
    (embedded ref, drawn box, or a shared-image group member).
    """
    return bool(
        q.get('image_ref') or q.get('image_page')
        or q.get('shares_image_with_previous')
    )


def _verifiable(q):
    """Whether a single question is a fair candidate for the text verifier."""
    if q.get('question_type') not in VERIFIABLE_TYPES:
        return False
    if q.get('needs_review'):
        return False  # already going to the teacher — a second flag adds nothing
    if _is_image_dependent(q):
        return False
    return bool(_correct_texts(q))


def _leading_number(text):
    """The first numeric value in a string as a float, or None.

    Lets "60 months" and "60" (or "$4.50" and "4.50") compare equal so a mere
    unit / currency difference isn't reported as a disagreement.
    """
    import re

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


def _answers_agree(gpt_answer, correct_texts):
    """Whether GPT's answer matches any of Claude's accepted answer forms.

    Agreement is deliberately lenient (exact-after-normalisation OR equal leading
    number) because a disagreement only routes the question to a teacher — a
    missed nuance costs a glance, a false disagreement costs trust. When in doubt
    we treat it as agreement and stay quiet.
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
        if gnum is not None and cnum is not None and gnum == cnum:
            return True
    return False


def _build_payload(verifiable):
    """Compact per-question payload for the verifier prompt.

    Multiple-choice / true-false questions carry their options so GPT picks from
    the same list Claude did (a fair like-for-like comparison); free-response
    types are solved open-ended.
    """
    payload = []
    for idx, q in verifiable:
        item = {
            'index': idx,
            'question_text': q.get('question_text', ''),
            'question_type': q.get('question_type'),
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
    "You are a meticulous maths teacher independently checking an answer key. "
    "For each question, solve it YOURSELF from scratch and report the answer you "
    "get — do not assume any provided answer is correct. Work carefully.\n"
    "- For multiple_choice / true_false questions, choose exactly one of the "
    "given options and copy its text verbatim as your answer.\n"
    "- For short_answer / fill_blank, give the concise final answer only "
    "(a number, word, or short phrase).\n"
    "- If you cannot solve a question confidently from the text alone, set "
    "confident=false and leave answer empty. Never guess.\n"
    "Report every question via the report_answers tool."
)


_VERIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "report_answers",
        "description": "Report the independently derived answer for each question.",
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
                            "answer": {
                                "type": "string",
                                "description": "Your own final answer (empty if not confident).",
                            },
                            "confident": {
                                "type": "boolean",
                                "description": "True only if you solved it confidently from the text.",
                            },
                        },
                        "required": ["index", "answer", "confident"],
                    },
                },
            },
            "required": ["results"],
        },
    },
}


def _verify_batch(client, model, payload):
    """One verifier request over a batch of questions.

    Returns ``(results_by_index, usage)`` where results_by_index maps a
    question index to ``{'answer': str, 'confident': bool}`` and usage is
    ``{'input_tokens', 'output_tokens'}``. Raises on transport / parse failure so
    the orchestrator can log it and move on.
    """
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _VERIFY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Solve each of these questions and report your answers:\n"
                    + json.dumps(payload, ensure_ascii=False)
                ),
            },
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
            results[int(r['index'])] = {
                'answer': (r.get('answer') or '').strip(),
                'confident': bool(r.get('confident')),
            }
        except (KeyError, TypeError, ValueError):
            continue

    usage = getattr(resp, 'usage', None)
    token_usage = {
        'input_tokens': getattr(usage, 'prompt_tokens', 0) or 0,
        'output_tokens': getattr(usage, 'completion_tokens', 0) or 0,
    }
    return results, token_usage


def verify_answers(questions, client=None, *, force=False):
    """Run the GPT verifier over ``questions``, flagging disagreements in place.

    For every verifiable question whose GPT answer disagrees with Claude's, sets
    ``needs_review=True`` and a ``review_reason`` so the teacher checks it. Never
    unflags or edits answers — it only routes uncertain questions to a human.

    Args:
        questions: the classified question dicts (mutated in place).
        client: an OpenAI client (injected in tests); built on demand otherwise.
        force: run even if ``verification_enabled()`` is False (tests only).

    Returns:
        A summary dict ``{'model', 'checked', 'flagged', 'input_tokens',
        'output_tokens', 'error'}`` when the pass ran, or ``None`` when the
        verifier is disabled / there was nothing to check.
    """
    if not force and not verification_enabled():
        return None

    verifiable = [(i, q) for i, q in enumerate(questions or []) if _verifiable(q)]
    if not verifiable:
        return None

    model = os.environ.get('AI_IMPORT_VERIFY_MODEL', 'gpt-4o')
    chunk_size = max(1, int(os.environ.get('AI_IMPORT_VERIFY_CHUNK', '40')))

    try:
        client = client or _get_openai_client()
    except Exception as exc:  # missing SDK / bad key construction
        logger.warning('AI import verifier unavailable, skipping: %s', exc)
        return {'model': model, 'checked': 0, 'flagged': 0,
                'input_tokens': 0, 'output_tokens': 0, 'error': str(exc)}

    by_index = {i: q for i, q in verifiable}
    all_results = {}
    in_tok = out_tok = 0
    error = None

    for start in range(0, len(verifiable), chunk_size):
        batch = verifiable[start:start + chunk_size]
        payload = _build_payload(batch)
        try:
            results, usage = _verify_batch(client, model, payload)
        except Exception as exc:
            # Best-effort: a failed batch leaves its questions unverified rather
            # than sinking the whole import. Surfaced in logs and the summary.
            logger.warning('AI import verifier batch failed: %s', exc)
            error = str(exc)
            continue
        all_results.update(results)
        in_tok += usage['input_tokens']
        out_tok += usage['output_tokens']

    flagged = 0
    for idx, verdict in all_results.items():
        q = by_index.get(idx)
        if q is None or not verdict['confident'] or not verdict['answer']:
            continue
        correct = _correct_texts(q)
        if _answers_agree(verdict['answer'], correct):
            continue
        q['needs_review'] = True
        q['review_reason'] = (
            f'Second-opinion check disagreed: verifier answered '
            f'"{verdict["answer"]}" vs "{correct[0]}".'
        )
        flagged += 1

    return {
        'model': model,
        'checked': len(all_results),
        'flagged': flagged,
        'input_tokens': in_tok,
        'output_tokens': out_tok,
        'error': error,
    }


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
