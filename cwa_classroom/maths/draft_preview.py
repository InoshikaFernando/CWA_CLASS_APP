"""Show a teacher what a not-yet-imported question will look like to a student.

The three PDF review screens (homework, worksheet, AI import) show an *editing*
form: text, a type dropdown, a grading dropdown, answer rows with tick boxes.
What they cannot show is the thing that decides whether the question is any
good — what the student SEES, what they can type into, and whether the marker
will accept a sensible answer. Parabola and measurement questions went
unuploaded for exactly that reason, and the fill-in-the-blank comma bug
(one answer row containing a comma, silently split across two gaps) was only
found after it had reached children.

Two entry points:

``preview_question(draft, ...)`` turns one draft question dict — the shape all
three flows keep in ``session.extracted_data['questions']`` — into a **real**
``Question`` row with real ``Answer`` rows, inside a transaction it rolls back
before returning. Real rows rather than an in-memory object because every
grader, and ``apply_blank_format`` itself, reads ``self.answers`` from the
database: a preview graded by different code from the student is worse than no
preview, since it would be believed. Nothing survives the request — see the
rollback contract on the function.

``grading_notes(question, draft, ...)`` says in words how that question will be
marked, and flags the traps that have actually bitten.

The field mapping here mirrors ``homework.views._save_homework_pdf_questions``
and ``ai_import.services.save_questions_from_session``. It deliberately shares
their helpers (``resolve_grading``, the ``validate_*_spec`` functions,
``apply_blank_format``) rather than re-deciding anything, and
``maths/tests/test_draft_preview_parity.py`` fails if the preview and the real
import ever disagree about a question.
"""
import contextlib
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction

from maths.models import Answer, Question

# Types whose answer is computed or graded from a structured spec. They carry no
# Answer rows (the model's clean() forbids them) and never take an image, since
# the app draws the layout itself.
SELF_DRAWING_TYPES = (
    Question.LONG_DIVISION, Question.COLUMN_OPERATION,
    Question.PLOT_POINTS, Question.PLOT_LINE, Question.IDENTIFY_COORDS,
    Question.DRAW_ON_GRID, Question.SHAPE_SELECT, Question.NUMBER_LINE,
    Question.TABLE_OF_VALUES,
)

SPEC_GRADED_TYPES = SELF_DRAWING_TYPES + (Question.READ_GRAPH, Question.MEASURE)

CHOICE_TYPES = (Question.MULTIPLE_CHOICE, Question.TRUE_FALSE)

# An accepted answer that looks like algebra: a letter used as a variable next to
# a power, an equals sign, or an explicit exponent. Matched only to warn that
# plain-text matching will reject an equivalent form a student writes differently
# — never to change how anything is graded.
_ALGEBRAIC_RE = re.compile(r'[a-zA-Z]\s*[\^²³]|[a-zA-Z]\s*=|=\s*[a-zA-Z]|[a-zA-Z]\s*\(')


class DraftNotImportable(Exception):
    """The draft cannot become a question at all — importing it would drop it.

    Raised with the same reason the importer would skip on (a spec that fails
    validation, a long division with no divisor, a choice question with no
    options). Surfaced to the teacher rather than swallowed: a question silently
    missing from a 50-question upload is the failure this whole screen exists to
    prevent.
    """


class _Rollback(Exception):
    """Internal: unwinds the preview transaction. Never escapes this module."""


# ---------------------------------------------------------------------------
# Draft -> Question
# ---------------------------------------------------------------------------
def _decimal_or_none(raw):
    if raw in (None, ''):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _preview_level(draft):
    """A Level to hang the preview question off.

    Nothing about the render or the marking depends on which one it is, so the
    draft's year level is used when it exists and any level otherwise. A site
    with no levels at all (a bare test database) gets one made inside the
    transaction that is about to be rolled back.
    """
    from classroom.models import Level

    raw = draft.get('year_level')
    level = None
    if raw not in (None, ''):
        try:
            level = Level.objects.filter(level_number=int(raw)).first()
        except (TypeError, ValueError):
            level = None
    return (
        level
        or Level.objects.order_by('level_number').first()
        or Level.objects.create(level_number=1, display_name='Year 1')
    )


def _validated_spec(draft, key, validator):
    """Return the draft's spec, or raise the reason the importer would skip it."""
    spec = draft.get(key)
    try:
        validator(spec)
    except (ValueError, TypeError) as exc:
        raise DraftNotImportable(
            f'This question would not be imported: its {key.replace("_", " ")} '
            f'is not usable — {exc}'
        ) from exc
    return spec


def build_preview_question(draft, *, promote_blanks):
    """Create the Question + Answer rows a draft would import as.

    ALWAYS creates, never ``get_or_create``: the importers dedup against the
    existing bank, which for a preview would quietly render somebody else's
    stored question instead of the draft in front of the teacher.

    ``promote_blanks`` says whether this flow turns a "___" sentence into a
    fill-in-the-blank with one box per gap. It is a per-flow fact, not a
    preference — the AI Import saver calls ``apply_blank_format`` and the
    homework saver does not — and passing it in is what stops the preview
    lying on one of the three screens.

    Raises ``DraftNotImportable`` where the importer would skip the question,
    so the teacher is told rather than shown a question that will never arrive.
    """
    from worksheets.services import accepted_question_type, resolve_grading

    text = (draft.get('question_text') or '').strip()
    if not text:
        raise DraftNotImportable(
            'This question has no text, so it would not be imported.')

    q_type = accepted_question_type(
        draft.get('question_type'), draft.get('question_type') or Question.SHORT_ANSWER)
    if q_type not in {v for v, _ in Question.QUESTION_TYPES}:
        q_type = Question.SHORT_ANSWER

    validation_type, grading_rubric = resolve_grading(draft)

    answers = [
        a for a in (draft.get('answers') or [])
        if (a.get('text') or '').strip()
    ]

    if q_type in CHOICE_TYPES and not answers:
        raise DraftNotImportable(
            'This is a pick-an-option question with no options, so it would be '
            'skipped at import — the student would see the question and nothing '
            'to choose from.')

    fields = {
        'question_type': q_type,
        'validation_type': validation_type,
        'grading_rubric': grading_rubric,
        'difficulty': draft.get('difficulty') or 1,
        'points': draft.get('points') or 1,
        'explanation': draft.get('explanation') or '',
    }

    if q_type == Question.LONG_DIVISION:
        try:
            fields['dividend'] = int(draft.get('dividend'))
            fields['divisor'] = int(draft.get('divisor'))
        except (TypeError, ValueError):
            raise DraftNotImportable(
                'This long division has no usable dividend and divisor, so it '
                'would be skipped at import.')
        if fields['divisor'] <= 0 or not fields['dividend']:
            raise DraftNotImportable(
                'This long division has no usable dividend and divisor, so it '
                'would be skipped at import.')

    if q_type == Question.COLUMN_OPERATION:
        try:
            operands = [int(o) for o in (draft.get('operands') or [])]
        except (TypeError, ValueError):
            operands = None
        operator = draft.get('operator') or ''
        if not operands or len(operands) < 2 or operator not in ('+', '-', '*'):
            raise DraftNotImportable(
                'This column arithmetic needs at least two numbers and a '
                '+, − or × operator, so it would be skipped at import.')
        fields['operands'] = operands
        fields['operator'] = operator

    if q_type in (Question.PLOT_POINTS, Question.PLOT_LINE, Question.IDENTIFY_COORDS):
        from maths.geometry_grading import validate_plane_spec
        fields['plane_spec'] = _validated_spec(draft, 'plane_spec', validate_plane_spec)

    if q_type == Question.DRAW_ON_GRID:
        from maths.geometry_grading import validate_grid_spec
        fields['grid_spec'] = _validated_spec(draft, 'grid_spec', validate_grid_spec)

    if q_type == Question.SHAPE_SELECT:
        from maths.geometry_grading import validate_shape_spec
        fields['shape_spec'] = _validated_spec(draft, 'shape_spec', validate_shape_spec)

    if q_type == Question.NUMBER_LINE:
        from maths.geometry_grading import validate_number_line_spec
        fields['number_line_spec'] = _validated_spec(
            draft, 'number_line_spec', validate_number_line_spec)

    if q_type == Question.TABLE_OF_VALUES:
        from maths.geometry_grading import validate_table_spec
        fields['table_spec'] = _validated_spec(draft, 'table_spec', validate_table_spec)

    if q_type in (Question.READ_GRAPH, Question.MEASURE):
        numeric = _decimal_or_none(draft.get('numeric_answer'))
        if numeric is None:
            raise DraftNotImportable(
                'This question has no value to measure or read off, so it would '
                'be skipped at import — there would be nothing to mark against.')
        fields['numeric_answer'] = numeric
        fields['answer_tolerance'] = _decimal_or_none(draft.get('answer_tolerance'))
        fields['answer_unit'] = (draft.get('answer_unit') or '')[:10]
        if q_type == Question.READ_GRAPH and draft.get('graph_spec'):
            from maths.geometry_grading import validate_graph_spec
            try:
                validate_graph_spec(draft['graph_spec'])
                fields['graph_spec'] = draft['graph_spec']
            except (ValueError, TypeError):
                # The importer falls back to the graph image here rather than
                # skipping the question, so the preview does too.
                fields['graph_spec'] = None

    question = Question.objects.create(
        question_text=text, level=_preview_level(draft), **fields)

    if q_type == Question.LONG_DIVISION:
        Answer.objects.create(
            question=question, answer_text=question.long_division_answer or '',
            is_correct=True, order=1)
    elif q_type == Question.COLUMN_OPERATION:
        if question.column_result is not None:
            Answer.objects.create(
                question=question, answer_text=str(question.column_result),
                is_correct=True, order=1)
    elif q_type in SPEC_GRADED_TYPES or q_type == Question.EXTENDED_ANSWER:
        # Graded by the spec, by tolerance, or by a person — never Answer rows.
        pass
    else:
        Answer.objects.bulk_create([
            Answer(
                question=question,
                answer_text=a.get('text', ''),
                is_correct=bool(a.get('is_correct')),
                order=i,
            )
            for i, a in enumerate(answers, 1)
        ])

    if promote_blanks:
        # Must run AFTER the answer rows exist — the spec is derived from them.
        changed, _reason = question.apply_blank_format()
        if changed:
            question.save(update_fields=['question_type', 'blank_spec'])

    return question


@contextlib.contextmanager
def preview_question(draft, *, promote_blanks):
    """Yield the Question a draft would import as, then undo it.

    Everything written inside is rolled back on exit — the question, its
    answers, and any row a grader touched. Two things the caller must NOT do
    inside the block: save an image (``ImageField.save`` writes to Spaces, which
    is not transactional and would leave an orphan behind), or touch the upload
    session.
    """
    try:
        with transaction.atomic():
            yield build_preview_question(draft, promote_blanks=promote_blanks)
            raise _Rollback
    except _Rollback:
        pass


# ---------------------------------------------------------------------------
# "How will this be marked?"
# ---------------------------------------------------------------------------
def _accepted_answers(question):
    """The ticked answers, read once per preview.

    Cached on the instance because several notes ask for the same list and this
    endpoint already sits close to the request query-count warning — a preview
    that fills the log with warnings hides the ones worth reading.
    """
    cached = getattr(question, '_preview_accepted', None)
    if cached is None:
        cached = [
            a.answer_text.strip()
            for a in question.answers.all()
            if a.is_correct and a.answer_text and a.answer_text.strip()
        ]
        question._preview_accepted = cached
    return cached


def _unit_suffix(unit):
    """A unit as it reads after a number: "135°" but "12 km"."""
    unit = (unit or '').strip()
    if not unit:
        return ''
    return unit if unit in ('°', '%', "'", '"') else f' {unit}'


def _note(level, text):
    return {'level': level, 'text': text}


def grading_notes(question, draft, *, promote_blanks):
    """How this question will be marked, and what is likely to go wrong.

    Returns a list of ``{'level': 'info'|'warn', 'text': str}``. The info notes
    state the rule the marker actually applies; the warnings name a trap the
    teacher would otherwise only find after a student hit it. Advisory only —
    nothing here blocks an import.
    """
    from maths.blank_grading import blank_answers, count_blanks, derive_blank_spec

    notes = []
    q_type = question.question_type

    if question.validation_type == Question.VALIDATION_HUMAN:
        notes.append(_note('info', (
            'A teacher marks this by hand. The student gets no instant '
            'right-or-wrong, and nothing below is auto-checked.')))
        return notes
    if question.validation_type == Question.VALIDATION_AI:
        notes.append(_note('info', (
            'AI marks this against the grading rubric. The student gets no '
            'instant right-or-wrong, and the mark depends on the rubric rather '
            'than on an exact answer.')))
        if not (question.grading_rubric or '').strip():
            notes.append(_note('warn', (
                'There is no grading rubric, so the AI has nothing to mark '
                'against. Add one, or set this to teacher-graded.')))
        return notes

    # --- Fill in the blanks -------------------------------------------------
    gaps = count_blanks(question.question_text)
    if q_type == Question.FILL_BLANK and question.blank_spec:
        per_gap = blank_answers(question.blank_spec)
        notes.append(_note('info', (
            f'The student gets {len(per_gap)} separate box'
            f'{"es" if len(per_gap) != 1 else ""} inside the sentence. '
            'Every gap must be right — one wrong gap marks the whole question '
            'wrong.')))
        for i, options in enumerate(per_gap, 1):
            notes.append(_note('info', f'Gap {i} accepts: {" or ".join(options)}'))

        # The comma trap: ONE typed answer row that has been cut into gaps.
        rows = _accepted_answers(question)
        if len(rows) == 1 and len(per_gap) > 1 and any(
                sep in rows[0] for sep in (',', ';')):
            notes.append(_note('warn', (
                f'Your single answer "{rows[0]}" has been split across '
                f'{len(per_gap)} gaps at its comma or semicolon — the student '
                'must type one piece per gap, shown above. If that was meant to '
                'be ONE answer, remove the separator or the gaps.')))
    elif gaps and q_type in Question.BLANK_PROMOTABLE_TYPES:
        # Only a typed answer can be moved into the gaps of a sentence. A choice
        # question whose stem happens to contain "___" is still a question you
        # pick an option for, so it gets no warning here.
        if promote_blanks:
            _spec, reason = derive_blank_spec(
                question.question_text, _accepted_answers(question))
            notes.append(_note('warn', (
                'This sentence has gaps but they could not be filled from the '
                f'answers, so the student gets one box for the whole sentence '
                f'and must type every value into it{": " + reason if reason else ""}')))
        else:
            notes.append(_note('warn', (
                'This sentence contains "___" gaps, but importing from this '
                'screen keeps it as ONE answer box — the student types the whole '
                'thing in one go, and must match the answer below exactly.')))

    # --- Tolerance-graded ---------------------------------------------------
    if q_type in (Question.MEASURE, Question.READ_GRAPH):
        unit = _unit_suffix(question.answer_unit)
        if question.answer_tolerance is None:
            notes.append(_note('warn', (
                f'Only exactly {question.numeric_answer}{unit} is accepted — '
                'there is no tolerance, so a student measuring 1 off is marked '
                'wrong. Set a tolerance unless the value really is exact.')))
        else:
            notes.append(_note('info', (
                f'Accepted: {question.numeric_answer}{unit} give or take '
                f'{question.answer_tolerance}{unit}.')))
        return notes

    # --- Spec-graded --------------------------------------------------------
    if q_type in (Question.PLOT_POINTS, Question.PLOT_LINE):
        notes.append(_note('info', (
            'The student plots on the plane below. Marked by comparing the '
            'exact set of points — an extra or missing point marks it wrong.')))
        return notes
    if q_type == Question.IDENTIFY_COORDS:
        notes.append(_note('info', (
            'The student types the coordinates. Marked as a set, so the order '
            'they type the points in does not matter.')))
        return notes
    if q_type == Question.NUMBER_LINE:
        notes.append(_note('info', (
            'Marked against the number line below. Every value must land on a '
            'tick — nothing between ticks can be marked.')))
        return notes
    if q_type == Question.TABLE_OF_VALUES:
        notes.append(_note('info', (
            'The student fills the blank cells of the table. Marked '
            'all-or-nothing: every cell must be right.')))
        return notes
    if q_type in (Question.DRAW_ON_GRID, Question.SHAPE_SELECT):
        notes.append(_note('info', (
            'Marked by comparing what the student drew or coloured against the '
            'target — an extra or missing mark makes it wrong.')))
        return notes
    if q_type == Question.LONG_DIVISION:
        notes.append(_note('info', (
            f'The answer is computed from {question.dividend} ÷ {question.divisor}, '
            f'not from the answer list: {question.long_division_answer}.')))
        return notes
    if q_type == Question.COLUMN_OPERATION:
        notes.append(_note('info', (
            f'The answer is computed from the numbers you gave: '
            f'{question.column_result}.')))
        return notes
    if q_type == Question.PRIME_FACTORIZATION:
        notes.append(_note('info', (
            'Marked by multiplying the factors the student types — any order, '
            'so long as every factor is prime and they multiply to the target.')))
        return notes

    # --- Choice -------------------------------------------------------------
    if q_type in CHOICE_TYPES:
        options = list(question.answers.all())
        correct = sum(1 for a in options if a.is_correct)
        total = len(options)
        if correct == 0:
            notes.append(_note('warn', (
                'No option is ticked correct, so every student who answers this '
                'is marked wrong. Tick the right one.')))
        elif correct > 1:
            notes.append(_note('warn', (
                f'{correct} options are ticked correct, but the student can only '
                'pick one — whichever of them they pick is marked right, and the '
                'others look wrong to them.')))
        else:
            notes.append(_note('info', (
                f'The student picks one of {total} options; the order is '
                'shuffled for each student.')))
        return notes

    if q_type == Question.EXTENDED_ANSWER:
        notes.append(_note('info', 'A written answer, marked against the rubric.'))
        return notes

    # --- Typed answers ------------------------------------------------------
    if q_type == Question.FILL_BLANK and question.blank_spec:
        # Already described per-gap above.
        return notes

    accepted = _accepted_answers(question)
    if not accepted:
        notes.append(_note('warn', (
            'There is no correct answer stored, so every answer the student '
            'types is marked wrong.')))
        return notes

    notes.append(_note('info', (
        'The student types an answer. Accepted: '
        + ' or '.join(f'"{a}"' for a in accepted)
        + '. Capitals, spaces and the ², ≥, ° and ÷ keypad forms are '
          'ignored when matching; anything else must match one of these.')))

    if len(accepted) == 1:
        notes.append(_note('warn', (
            'Only one wording is accepted. A student who writes the same answer '
            'a different way — with a unit, a word, or extra punctuation — is '
            'marked wrong. Add the alternatives you would accept.')))

    if question.answer_format == Question.ANSWER_FORMAT_TEXT and any(
            _ALGEBRAIC_RE.search(a) for a in accepted):
        notes.append(_note('warn', (
            'This answer looks algebraic, but an imported question matches text '
            'literally — an equivalent form the student writes differently '
            '(a factored vs expanded parabola, say) is marked wrong. Add each '
            'form you would accept as its own answer.')))

    return notes


# ---------------------------------------------------------------------------
# The draft's image
# ---------------------------------------------------------------------------
class _PreviewImage:
    """Stands in for ``Question.image`` on a preview question.

    A draft's image lives in the upload session as base64, not in storage, so
    there is no ``ImageField`` to render from — and writing one is exactly what
    a preview must not do (image writes are not transactional and would outlive
    the rollback).

    Assigning a plain object here rather than adding a preview-only branch to
    the student templates is deliberate: Django's file descriptor returns a
    non-str, non-File value untouched, so ``{% if q.image %}`` and
    ``{{ q.image.url }}`` keep working, and every template that draws the
    figure — the take partial, the measure tool, anything added later — shows
    the draft's image without knowing preview exists.
    """

    def __init__(self, url):
        self.url = url
        self.name = 'preview'

    def __bool__(self):
        return True

    def __str__(self):
        return self.name


def attach_preview_image(question, image_b64):
    """Point a preview question at the draft's base64 image. Never saves."""
    if image_b64:
        question.image = _PreviewImage(f'data:image/png;base64,{image_b64}')
    return question
