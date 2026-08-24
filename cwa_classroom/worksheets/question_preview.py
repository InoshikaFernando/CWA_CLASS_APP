"""The "Preview as student" endpoint, shared by all three PDF review screens.

Homework, Worksheets and AI Import each own their upload session model and their
own access check, so each keeps a three-line view. Everything those views do —
read one question card out of the POST, build the question it would import as,
mark a trial answer, render the fragment — happens here, once, so the three
screens cannot drift into previewing three different things.

The contract with the browser:

* The review page POSTs the ``q_<idx>_*`` fields of ONE card, plus
  ``preview_index``. The teacher's unsaved edits are what gets previewed, so the
  posted fields win over the stored draft; anything the card does not carry
  (an image the crop modal stored, a spec the card does not expose) falls back
  to the stored draft.
* Nothing is written. The question, its answers, and anything a grader touched
  are rolled back before the response is returned — see
  ``maths.draft_preview.preview_question`` — and the upload session is only ever
  read.
* Adding ``preview_answer`` marks that answer through the real student grader
  and the fragment comes back with the result on it.

Why the answer comes back as a *value* and not as the id the take page posts:
each preview builds a fresh question with fresh row ids, so an id from the
previous render means nothing to this one. A typed answer and every widget
payload (they all serialise into one ``answer_<id>`` field) travel as their own
value. A pick-an-option answer travels as ``preview_answer_index`` — its
position in the option list — which is why the preview deliberately does NOT
shuffle the options the way the student page does.
"""
import json

from django.http import HttpResponseBadRequest
from django.shortcuts import render

from maths.draft_preview import (
    DraftNotImportable,
    attach_preview_image,
    grading_notes,
    preview_question,
)
from maths.models import Question

# The preview form posts at most this many answer rows per card, matching the
# review POST handlers.
MAX_ANSWER_ROWS = 20

_JSON_SPEC_FIELDS = (
    ('plane_spec', ('plot_points', 'plot_line', 'identify_coords')),
    ('graph_spec', ('read_graph',)),
    ('number_line_spec', ('number_line',)),
    ('table_spec', ('table_of_values',)),
)


def _int_or(raw, fallback):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def draft_from_post(post, idx, base=None, defaults=None):
    """One question card's POST fields as a draft dict.

    ``base`` is the stored draft, so fields the card does not carry survive;
    ``defaults`` are the upload's whole-file defaults (year level, topic).
    Deliberately mirrors the ``_apply_question_fields`` blocks in the three
    review POST handlers, field for field — ``test_preview_matches_the_import``
    fails the build if a card ever previews as something other than what
    confirming it would import.
    """
    from worksheets.services import accepted_question_type

    draft = dict(base or {})
    defaults = defaults or {}
    prefix = f'q_{idx}_'

    def posted(name, fallback=''):
        return post.get(f'{prefix}{name}', fallback)

    draft['question_text'] = posted('text', draft.get('question_text', ''))
    draft['question_type'] = accepted_question_type(
        posted('type'), draft.get('question_type', 'short_answer'))
    draft['validation_type'] = posted(
        'validation_type', draft.get('validation_type', 'auto'))
    draft['grading_rubric'] = posted('grading_rubric', draft.get('grading_rubric', ''))
    draft['difficulty'] = _int_or(posted('difficulty'), draft.get('difficulty', 1))
    draft['points'] = _int_or(posted('points'), draft.get('points', 1))
    draft['explanation'] = posted('explanation', draft.get('explanation', ''))
    draft['year_level'] = _int_or(
        posted('year_level'), draft.get('year_level', defaults.get('year_level', 1)))

    q_type = draft['question_type']

    if q_type == 'long_division':
        for field in ('dividend', 'divisor'):
            raw = posted(field).strip()
            if raw:
                draft[field] = _int_or(raw, draft.get(field))

    if q_type == 'column_operation':
        raw_operands = posted('operands').strip()
        if raw_operands:
            try:
                draft['operands'] = [
                    int(tok) for tok in raw_operands.replace(',', ' ').split()
                ]
            except ValueError:
                pass
        operator = posted('operator').strip()
        if operator in ('+', '-', '*'):
            draft['operator'] = operator

    for field, types in _JSON_SPEC_FIELDS:
        if q_type not in types:
            continue
        raw = posted(field).strip()
        if not raw:
            continue
        try:
            draft[field] = json.loads(raw)
        except (ValueError, TypeError):
            # A half-typed spec keeps the stored one, exactly as the review POST
            # does — the import-time validator is what reports a bad spec.
            pass

    # read_graph and measure post the same three field names; measure's carry a
    # `measure_` prefix because the review page renders both panels at once.
    numeric_prefix = {'read_graph': '', 'measure': 'measure_'}.get(q_type)
    if numeric_prefix is not None:
        for field in ('numeric_answer', 'answer_tolerance'):
            raw = posted(f'{numeric_prefix}{field}').strip()
            if raw:
                draft[field] = raw
        unit = posted(f'{numeric_prefix}answer_unit').strip()
        if unit:
            draft['answer_unit'] = unit

    if post.get(f'{prefix}remove_image') == 'on':
        draft['image_ref'] = None
    else:
        image_ref = posted('image_ref')
        draft['image_ref'] = image_ref if image_ref and image_ref != 'none' else None

    answers = []
    for a_idx in range(MAX_ANSWER_ROWS):
        text = post.get(f'{prefix}answer_{a_idx}_text', '')
        if text.strip():
            answers.append({
                'text': text,
                'is_correct': post.get(f'{prefix}answer_{a_idx}_correct') == 'on',
            })
    if answers:
        draft['answers'] = answers

    return draft


def _trial_answer(post, question):
    """The teacher's trial answer as the student grader expects to receive it.

    Returns ``(post_data, shown)`` or ``(None, '')`` when nothing was tried.
    ``shown`` is what to echo back to the teacher, which for a picked option is
    the option text rather than a row id.
    """
    field = f'answer_{question.pk}'

    if question.question_type in (Question.MULTIPLE_CHOICE, Question.TRUE_FALSE):
        raw_index = post.get('preview_answer_index', '')
        if raw_index == '':
            return None, ''
        options = list(question.answers.all())
        index = _int_or(raw_index, -1)
        if not (0 <= index < len(options)):
            return None, ''
        picked = options[index]
        return {field: str(picked.pk)}, picked.answer_text

    raw = post.get('preview_answer')
    if raw is None or raw == '':
        return None, ''
    return {field: raw}, question.display_text_answer(raw)


def preview_response(request, *, extracted_data, extracted_images, promote_blanks,
                     template='partials/_student_preview_body.html'):
    """Render one draft question as the student will meet it.

    Callers pass their own session's data after checking that the user owns it.
    ``promote_blanks`` says whether this flow turns a "___" sentence into gaps
    — the AI Import saver does, the homework PDF saver does not — so each screen
    previews its own truth rather than a shared guess.
    """
    idx = _int_or(request.POST.get('preview_index'), None)
    if idx is None:
        return HttpResponseBadRequest('preview_index is required')

    stored = extracted_data.get('questions') or []
    base = stored[idx] if 0 <= idx < len(stored) else {}
    draft = draft_from_post(request.POST, idx, base=base, defaults=extracted_data)

    context = {
        'preview_index': idx,
        'question_number': idx + 1,
        'total_questions': len(stored),
    }

    try:
        with preview_question(draft, promote_blanks=promote_blanks) as question:
            # One read of the answer rows, shared by the notes, the rendered
            # options and the result panel.
            answers = list(question.answers.all())
            image_ref = draft.get('image_ref')
            attach_preview_image(
                question, (extracted_images or {}).get(image_ref) if image_ref else None)

            post_data, shown = _trial_answer(request.POST, question)
            result = None
            if post_data is not None:
                from maths.plugin import MathsPlugin
                graded = MathsPlugin().grade_answer(question.pk, post_data)
                result = {
                    'is_correct': graded['is_correct'],
                    'given': shown,
                    'correct_answer': question.correct_answer_display(),
                    'points_earned': graded['points_earned'],
                    # Part-graded types only (fill_blank, table_of_values): the
                    # gap-by-gap breakdown, so a teacher trialling the question
                    # sees the same explanation — and the same fraction of a
                    # point — their student would get.
                    'answer_data': graded.get('answer_data') or {},
                }

            context.update({
                'question': question,
                # The take partial's own context key. Options are NOT shuffled:
                # the browser identifies a picked option by position, and the
                # student-facing shuffle is called out in the notes instead.
                'ctx': {
                    'question': question,
                    'shuffled_answers': answers,
                },
                'notes': grading_notes(
                    question, draft, promote_blanks=promote_blanks),
                'result': result,
                'auto_marked': question.validation_type == Question.VALIDATION_AUTO,
            })
            # Rendered inside the transaction: the template reads the answer
            # rows, which only exist until this block exits.
            return render(request, template, context)
    except DraftNotImportable as exc:
        context['not_importable'] = str(exc)
        return render(request, template, context)
