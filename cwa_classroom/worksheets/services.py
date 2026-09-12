"""
Worksheet-specific PDF extraction and AI classification.

Image extraction strategy
--------------------------
We use PyMuPDF (fitz) to RENDER the question image directly from the PDF vector data,
not crop a JPEG screenshot. This gives clean, sharp images even for shapes and geometry.

Flow:
  1. Open PDF with fitz once — keep doc open throughout.
  2. Render each page as a screenshot (sent to Claude so it can see the layout).
  3. Claude returns image_bbox [x0, y0, x1, y1] in screenshot pixel space + page_num.
     page_num is pinned to the request's ABSOLUTE page numbers and any positional
     answer is remapped (worksheets/page_attribution.py) — a figure is only ever
     cropped from the page the question is really on.
  4. Convert pixel coords → PDF point coords using the known DPI.
  5. Call page.get_pixmap(clip=fitz.Rect(...), dpi=150) to render just that region
     directly from the PDF — clean vector rendering, not a crop of a compressed JPEG.
  6. Store result as PNG base64.

This avoids Pillow entirely and produces publication-quality crops.
"""
import base64
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

from maths.shape_detect import trace_shape_select_scenes

from .explanation_checks import explanation_problems, flag_explanation_problems
from .page_attribution import pin_page_enum, resolve_chunk_pages
from .pdf_geometry import displayed_rect, raster_native_dpi

logger = logging.getLogger(__name__)

# Page numbers baked into generated image_ref filenames, most-specific first:
#   worksheet_img_q4_p3.png   -> "_p3"   (worksheet / homework crops)
#   page3_img1.png / page3_figure2.png -> "page3"  (ai_import crops)
# These give a deterministic page even when the model omits per-question page info.
_REF_PAGE_PATTERNS = (
    re.compile(r'_p(\d+)(?=\.|_|$)', re.IGNORECASE),
    re.compile(r'(?:^|[^a-z])page[_-]?(\d+)', re.IGNORECASE),
)


def question_source_page(q):
    """Best-effort 1-based page a question maps to, for the "Adjust image" editor.

    The crop modal opens on this page so the teacher lands on the page the
    question actually came from. Resolution order (most reliable first):

      1. ``image_page`` — explicit crop provenance recorded when a figure was
         rendered/cropped for this question.
      2. the page encoded in the generated ``image_ref`` filename
         (e.g. ``worksheet_img_q4_p3.png`` -> 3, ``page3_img1.png`` -> 3) —
         survives even when the classifier drops the per-question page field.
      3. the classifier's per-question page (``page_num`` / ``source_page`` /
         ``page``).
      4. ``1`` as a last resort.
    """
    def _as_page(value):
        try:
            page = int(value)
        except (TypeError, ValueError):
            return None
        return page if page > 0 else None

    page = _as_page(q.get('image_page'))
    if page:
        return page

    ref = q.get('image_ref')
    if ref:
        for pattern in _REF_PAGE_PATTERNS:
            match = pattern.search(str(ref))
            if match:
                return int(match.group(1))

    for key in ('page_num', 'source_page', 'page'):
        page = _as_page(q.get(key))
        if page:
            return page

    return 1


# Phrases that betray unfinished / self-correcting reasoning the model left in an
# explanation ("The differences are: … Wait — Buenos Aires is 45 and Oslo is 44").
# Their presence means the model second-guessed itself, so the ticked answer is
# suspect even when the reasoning eventually lands on the right value.
_SCRATCH_WORK_RE = re.compile(
    r'\b(?:wait|hold on|whoops|oops|scratch that|'
    r'actually[,\s]|on second thought|i(?:\'m| am)? not sure|'
    r'let me (?:re)?(?:check|do|redo|recompute|reconsider|try)|'
    r'recompute|recalculate|correction|i made a mistake|'
    r'that(?:\'s| is) (?:wrong|incorrect)|no[,\s]+(?:wait|actually))\b',
    re.IGNORECASE,
)


def _norm_text(value):
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def answer_review_warning(q):
    """Return a short reason to flag a question's answer key for review, else None.

    Auto-graded questions are only as trustworthy as the answer key the model
    produced. Two signals reliably indicate the key may be wrong even when the
    explanation reasons its way to the right value — which is exactly the
    "explanation is correct but the ticked answer isn't" failure:

      1. The explanation contains scratch work / self-correction ("Wait —",
         "let me redo") — the model wasn't sure, so its ticked answer is suspect.
      2. (multiple choice) the explanation clearly names a DIFFERENT option than
         the one ticked correct, and never names the ticked one.

    Surfacing this in the review editor keeps a wrong key from shipping silently
    (the teacher is already reviewing the question there).
    """
    # A pick-an-option question with nothing to pick is unanswerable — the
    # student would see the stem and an empty space. It is also exactly what a
    # question whose real type the review dropdown could not offer looks like
    # after the browser fell back to its first option, so say so out loud
    # instead of rendering an empty answers box.
    if q.get('question_type') in _CHOICE_QUESTION_TYPES:
        options = [a for a in (q.get('answers') or []) if (a.get('text') or '').strip()]
        if not options:
            return ('This is a choice question with no options to pick from — '
                    'add the options, or change the question type to the one '
                    'this question really is.')

    explanation = (q.get('explanation') or '').strip()
    if not explanation:
        return None

    if _SCRATCH_WORK_RE.search(explanation):
        return ('The explanation contains second-guessing or scratch work — '
                'check the ticked answer matches its final conclusion.')

    # The explanation contradicting ITSELF — "there are 15 values: <14 numbers>",
    # "the 8th value is 25" when its own list says 27, "10 + 5 + 2 = 18". Checked
    # here as well as at import time so sessions extracted before the check
    # existed still show it on the review screen.
    problems = explanation_problems(q)
    if problems:
        return problems[0]

    if q.get('question_type') == 'multiple_choice':
        expl = _norm_text(explanation)

        def named(opt):
            # Word-boundary match so a short option ("2") isn't found inside a
            # longer number ("12"); skip trivially short option text entirely.
            opt = _norm_text(opt)
            if len(opt) < 3:
                return None
            return re.search(r'(?<!\w){}(?!\w)'.format(re.escape(opt)), expl) is not None

        answers = q.get('answers') or []
        correct = [named(a.get('text')) for a in answers if a.get('is_correct')]
        others = [named(a.get('text')) for a in answers if not a.get('is_correct')]
        # Only decide when at least one correct option was long enough to check.
        if any(c is not None for c in correct):
            correct_named = any(c for c in correct)
            other_named = any(o for o in others)
            if not correct_named and other_named:
                return ('The explanation names a different option than the one '
                        'ticked correct — verify the answer.')

    return None


# ---------------------------------------------------------------------------
# Drawing / construction questions the app has no answer surface for
# ---------------------------------------------------------------------------
#
# "Draw a tree diagram to illustrate this situation." A student cannot draw
# anything in this app: the only answer surfaces that exist are the ones the
# structured question types render (a number line to mark, a coordinate plane to
# plot on, a division bracket, a stacked sum). Every other "draw it" instruction
# — a tree or Venn diagram, a bar chart, a net, a compass construction, a shaded
# region — is paper-only work.
#
# Such a question must never be imported as ai_graded. There is no written
# answer to grade, so the grader would be marking prose the child was never
# asked to write, and would mark them wrong however well they drew it. They are
# routed to human_graded instead, which the rest of the app already handles:
# quizzes hide them from every student (``quiz.views.gradable_for``) and the
# upload preview leaves them unticked, so the teacher opts in rather than out.

# Types that DO give the student something to draw on. The app renders the
# interaction and grades it, so "draw"/"plot"/"mark"/"colour" is answerable
# there. This is every structured type in ``maths.models.Question``, which is
# WIDER than what the worksheet extractor can emit: draw_on_grid and shape_select
# only reach the bank through the question builder (and, for shape_select, the
# image tracer in maths.shape_detect), and the
# bank sweep (``maths.management.commands.fix_drawing_questions``) has to leave
# them alone — a shape_select question says "colour the triangles" and the app
# renders exactly that.
_DRAWABLE_QUESTION_TYPES = {
    'number_line', 'plot_points', 'plot_line', 'identify_coords',
    'long_division', 'column_operation', 'read_graph', 'measure',
    'draw_on_grid', 'shape_select', 'table_of_values', 'prime_factorization',
    # "Sketch the graph of y = x² + x − 2 showing the coordinates of the
    # vertex, the x-axis and y-axis intercepts and the equation of the axis of
    # symmetry" reads as a construction ("sketch … graph") and used to be routed
    # to the teacher by the patterns below. It is not one: the app draws the
    # plane and takes the key features the stem names, which is what the marks
    # were ever for. See rule 18 in the prompt.
    'sketch_graph',
}

# fill_blank is deliberately NOT on that list. It renders the question as a
# SENTENCE with an input at each "___" gap — there is no grid, so a table
# question saved as fill_blank has lost its table and the student is typing into
# a row of gaps with nothing to read them against. "Complete the table" is
# answerable only as table_of_values, which is exempt above; every other type
# still belongs to the teacher.

# Pick-an-option types: the student chooses, never draws, so a figure verb in
# the stem ("Which diagram shows the line drawn correctly?") is not a
# construction task. Requires real options — a bare type label doesn't exempt it.
_CHOICE_QUESTION_TYPES = {'multiple_choice', 'true_false'}


# Anything a question can ask a student to make a picture of. Deliberately broad
# (it includes bare shapes) because it is only ever used with a construction
# VERB in front of it — see pattern A below.
_VISUAL = (
    r'(?:tree\s+diagram|venn\s+diagram|diagram|graph|chart|histogram|'
    r'pictogram|pictograph|net|figure|picture|scale\s+drawing|plan|map|'
    r'axes|number\s+line|table|grid|shape|points?|'
    r'triangle|rectangle|square|circle|quadrilateral|polygon|pentagon|'
    r'hexagon|octagon|parallelogram|trapezium|rhombus|'
    r'angle|line|curve|region|arrow)'
)

# The narrower set: visuals a student BUILDS rather than reads off. No bare
# shapes here — patterns B-D below match on weaker verbs, and "use a square
# number" or "put the answer to the right" must not read as a construction.
_CHART = (
    r'(?:venn\s+diagram|tree\s+diagram|flow\s*chart|mind\s+map|scale\s+drawing|'
    r'stem[-\s]and[-\s]leaf(?:\s+(?:plot|diagram))?|'
    r'box(?:[-\s]and[-\s]whisker)?\s+plot|scatter\s+(?:graph|plot|diagram)|'
    r'bar\s+(?:graph|chart)|pie\s+chart|line\s+graph|tally\s+chart|'
    r'frequency\s+table|dot\s+plot|histogram|pictogram|pictograph|'
    r'number\s+line|diagram|graph|chart|table|grid|axes|net|'
    r'sketch|drawing|picture|figure|map|plan)'
)

_ARTICLE = r'(?:a|an|the|your|this|these|each|one)\s+'

# Three ways a worksheet asks for a drawing. A question matching ANY of them is
# asking the student to make a picture, which this app gives them no way to do.
#
# There used to be a fourth — placement verbs plus a preposition, meant to catch
# "add these elements to the Venn diagram". It was removed after a production dry
# run: it cannot tell writing ONTO a figure from writing an answer to what is
# shown ON one, and it swept up a dozen working read-off questions ("Write down
# the equation of Line A shown on the graph", "Write the coordinates of the ship
# shown on the grid", "Write the number shown with an arrow on the number line").
# Those are the app's own read modes. Losing "add these to the Venn diagram" is
# the cheaper mistake — a missed one stays AI-graded, where a false positive
# hides a working question from every student.
_CONSTRUCTION_PATTERNS = (
    # A. Construction verb + the visual it produces, within four words and in
    #    the same clause: "draw a tree diagram", "shade the region". BOTH halves
    #    are required — "draw a conclusion" has no visual noun, "use the diagram
    #    below" has no verb. The in-between words carry no sentence punctuation,
    #    so verb and object sit in the same clause ("Complete the sentence: a
    #    triangle has ___ sides" is not a construction), and the four-word window
    #    stops the verb reaching across a whole instruction ("Complete the
    #    calculation to find the angle" stays auto-graded).
    #
    #    "complete the square" is excluded outright: it is the algebra technique,
    #    answered by typing vertex form, and `square` is in the visual list as a
    #    shape. Production had "For the parabola y = x² + 6x − 10, complete the
    #    square to express it in vertex form" flagged as a drawing.
    re.compile(
        r'\b(?:draw|redraw|sketch|construct|shade|colou?r|plot|label|'
        r'complete(?!\s+the\s+square\b)|copy|join|mark|illustrate)\b'
        r'(?:\s+[^\s.:;?!]+){0,4}?\s+' + _VISUAL + r'\b',
        re.IGNORECASE,
    ),
    # B. Represent data ON a medium: "Illustrate on a Venn diagram the sets A and
    #    B", "represent this data in a pie chart", "display the results using a
    #    pictograph". "show" is excluded before "that" — "Show that the angle is
    #    90° using the diagram" is a proof to AI-grade, not a drawing. Every verb
    #    is matched as a bare stem, so the passive read-off forms ("the graph
    #    SHOWS", "the data is RECORDED in the table") don't match.
    re.compile(
        r'\b(?:represent|display|record|illustrate|sort|group|arrange|'
        r'organi[sz]e|summari[sz]e|show(?!\s+that))\b'
        r'[^.:;?!]{0,40}?'
        r'\b(?:on|onto|in|into|as|using|with)\s+' + _ARTICLE + _CHART + r'\b',
        re.IGNORECASE,
    ),
    # C. "Use A tree diagram to work out the probability" — the indefinite
    #    article means there is no diagram yet, so the student has to build one.
    #    "Use THE diagram below" is the opposite: read the one that is printed.
    re.compile(r'\buse\s+(?:a|an)\s+' + _CHART + r'\b', re.IGNORECASE),
)


def _has_stored_answer(q):
    """Whether *q* carries an answer the app can already mark it against.

    The decisive signal, learned from a production dry run over 19,773 bank
    questions: every false positive it produced had one. A question with a
    ticked answer is one a student types into and the grader checks — whatever
    figure its wording mentions. "Complete the table for Output = 6x" and "Write
    the coordinates of the ship shown on the grid" both read a figure and type a
    value, and both have graded correctly for as long as they have existed.

    So this outranks the patterns: the cost of a false positive is a working
    question hidden from every student, and the cost of a miss is a question
    that stays AI-graded — recoverable, and visible to a teacher.
    """
    for answer in (q.get('answers') or []):
        if not isinstance(answer, dict):
            continue
        if answer.get('is_correct') and str(answer.get('text') or '').strip():
            return True
    return False


def is_unanswerable_construction(q):
    """Whether *q* asks for a drawing the app gives the student no way to make."""
    q_type = q.get('question_type')
    if q_type in _DRAWABLE_QUESTION_TYPES:
        return False
    if _has_stored_answer(q):
        return False
    if q_type in _CHOICE_QUESTION_TYPES and len(q.get('answers') or []) >= 2:
        return False
    text = q.get('question_text') or ''
    return any(p.search(text) for p in _CONSTRUCTION_PATTERNS)


# Stands in for a rubric the model didn't write, so a teacher opening one of
# these knows why it is theirs to mark rather than finding an empty box.
CONSTRUCTION_RUBRIC = (
    'The student has to draw this answer on paper — the app cannot take a '
    'drawing, so mark their working by hand.'
)


def route_constructions_to_teacher(questions):
    """Set every draw-it-on-paper question to human_graded. Returns the count.

    Also unticks each one it routes: a question nobody can answer in the app is
    not one to import by default, so the teacher opts in rather than out. At
    classification time that matches the ``include`` default anyway (teacher-
    graded questions start unticked); on a session extracted before this rule
    existed it is the correction — those arrived ticked.

    Questions the model already marked human_graded are left exactly as they
    are, so re-running this never disturbs a teacher's own decision.
    """
    routed = 0
    for q in (questions or []):
        if q.get('validation_type') == 'human_graded':
            continue
        if not is_unanswerable_construction(q):
            continue
        q['validation_type'] = 'human_graded'
        q['include'] = False
        q['grading_rubric'] = q.get('grading_rubric') or CONSTRUCTION_RUBRIC
        routed += 1
    return routed


def resolve_grading(q):
    """The one decision on how a question gets marked. Returns (type, rubric).

    Every import path saves through this — the worksheet and homework PDF
    uploads and the AI PDF import — so a question that would be teacher-graded
    in one is teacher-graded in all of them. Before this, each saver had its own
    rules: ai_import wrote no validation_type at all (everything landed on the
    model default, ``auto``), and homework coerced anything non-extended back to
    ``auto``, which silently threw away exactly the routing this module exists
    to do.

    Order matters:

    1. A drawing the app can't accept is the teacher's, whatever its type. This
       is first because it is the only rule that overrides an explicit choice —
       an ai_graded "draw a Venn diagram" is wrong however confidently it was
       set.
    2. human_graded is never downgraded. A teacher-graded question is a standing
       decision by a person; no type rule may quietly undo it.
    3. An extended answer left on auto has no stored answer to match against, so
       it becomes ai_graded rather than being marked wrong by exact match.
    4. ai_graded on a question that is NOT an extended answer is meaningless —
       an MCQ has options to check — so it drops back to auto.
    """
    validation_type = q.get('validation_type') or 'auto'
    grading_rubric = q.get('grading_rubric') or ''
    q_type = q.get('question_type') or 'short_answer'

    if is_unanswerable_construction(q):
        return 'human_graded', grading_rubric or CONSTRUCTION_RUBRIC

    if validation_type == 'human_graded':
        return 'human_graded', grading_rubric

    if q_type == 'extended_answer':
        if validation_type == 'auto':
            return 'ai_graded', grading_rubric
        return validation_type, grading_rubric

    if validation_type == 'ai_graded':
        return 'auto', grading_rubric

    return validation_type, grading_rubric


# Marks a session's question list as already swept for drawing questions, so the
# sweep runs at most once per upload and a teacher who deliberately sets one back
# to AI graded keeps that choice.
CONSTRUCTIONS_ROUTED_KEY = 'constructions_routed'


def backfill_constructions(data):
    """Sweep one upload session's questions for drawings. Idempotent per session.

    ``extract_and_classify_worksheet`` already routes at classification time, so
    a fresh upload arrives correct and this is a no-op that just stamps the key.
    A session extracted BEFORE the rule existed still holds ai_graded drawing
    questions, and its teacher would otherwise have to spot and fix every one by
    hand in the preview — so the preview sweeps it on first open instead.

    Returns the number of questions routed, or None if this session was already
    swept (in which case the caller has nothing to persist).
    """
    if not isinstance(data, dict) or data.get(CONSTRUCTIONS_ROUTED_KEY):
        return None
    routed = route_constructions_to_teacher(data.get('questions'))
    data[CONSTRUCTIONS_ROUTED_KEY] = True
    return routed


# DPI for the page screenshots sent to Claude. 150 is the quality sweet spot —
# lower values make Claude miss questions (small text becomes illegible). Tune
# down via WORKSHEET_SCREENSHOT_DPI only if memory is tight (all page screenshots
# are held in memory at once); pixmaps are freed per page to limit the spike.
SCREENSHOT_DPI = int(os.environ.get('WORKSHEET_SCREENSHOT_DPI', '150'))

# Higher screenshot DPI used in name-the-shape mode. A shapes chart packs many small
# figures onto one page; extra pixels give Claude finer coordinates to localise each
# shape, so the per-shape bboxes come back tighter. Bbox *correctness* is DPI-independent
# (coords convert via each page's stored dims) — this only improves placement precision.
SHAPE_NAMING_DPI = int(os.environ.get('WORKSHEET_SHAPE_NAMING_DPI', '200'))

# DPI for the FINAL rendered question-image crop. This is independent of the
# page-screenshot DPI: the screenshot only needs to be legible enough for Claude
# to place a bbox, whereas the saved crop is shown to students and benefits from
# a much higher resolution. Bbox math is DPI-independent (coords convert via each
# page's stored dims), so raising this is safe and only sharpens the output —
# 300 ≈ print quality. A single small crop at 300 DPI is cheap on memory.
IMAGE_RENDER_DPI = int(os.environ.get('WORKSHEET_IMAGE_DPI', '300'))

# Longest-edge pixel cap for a rendered question image. IMAGE_RENDER_DPI alone
# is unbounded in pixels: a full-width figure (500 pt across) comes out over
# 2000 px, and every crop is held in memory, base64'd into the session row and
# then inlined into the preview page — on an image-heavy worksheet that is the
# main driver of worker memory (and an OOM-killed worker is what leaves an
# upload stuck). 1600 px stays sharper than any screen or print use of these.
IMAGE_MAX_PX = int(os.environ.get('WORKSHEET_IMAGE_MAX_PX', '1600'))

# Max output tokens for the classification call. Each extracted question is a
# sizeable structured object (text, type, answers, bbox, rubric), so a dense
# multi-page worksheet can exceed a small cap and get its question list
# truncated — i.e. only *some* questions come back. Keep this generous.
WORKSHEET_MAX_TOKENS = int(os.environ.get('WORKSHEET_MAX_TOKENS', '32000'))

# Parallel classification: a multi-page worksheet is split into page-chunks that
# are classified concurrently. Each chunk generates a fraction of the output and
# they run at the same time, so wall-clock ≈ the slowest chunk rather than the
# sum — e.g. a 13-page worksheet drops from ~6 min to ~2 min.
WORKSHEET_CHUNK_SIZE = int(os.environ.get('WORKSHEET_CHUNK_SIZE', '4'))   # pages per request
# Concurrent classification requests. A chunk is dominated by output-token
# generation (minutes for a dense chunk), so wall-clock is ~ceil(chunks/parallel)
# × chunk time: at 4-wide a 40-page worksheet (10 chunks) needs 3 waves, at
# 8-wide only 2. Raise further only if the Anthropic account's rate limits allow.
WORKSHEET_MAX_PARALLEL = int(os.environ.get('WORKSHEET_MAX_PARALLEL', '8'))  # concurrent requests
WORKSHEET_PAGE_CAP = int(os.environ.get('WORKSHEET_PAGE_CAP', '40'))      # hard ceiling on pages processed


# ---------------------------------------------------------------------------
# PDF page extraction (worksheet-specific — tracks screenshot dimensions)
# ---------------------------------------------------------------------------

def extract_worksheet_pages(doc, screenshot_dpi=None, selected_pages=None):
    """
    Render each page of an open fitz.Document.

    ``screenshot_dpi`` overrides the page-screenshot DPI (defaults to
    SCREENSHOT_DPI). Name-the-shape mode passes a higher value so Claude can
    place tighter bounding boxes around small individual shapes.

    ``selected_pages`` is an optional iterable of 1-based page numbers to render
    (see ``worksheets/page_selection.py``); ``None`` renders every page. Only the
    selected pages are rendered at all, so an excluded page costs no memory, no
    screenshot and no AI tokens. Page numbers stay ABSOLUTE — page 7 of the PDF
    is stamped ``page_num: 7`` whether or not pages 1–6 were selected — which is
    what keeps image bboxes and the re-crop tooling working on a partial run.

    Returns:
        {
            'pages': [
                {
                    'page_num': int,          # 1-based, absolute in the PDF
                    'text': str,
                    'screenshot': str,        # base64 JPEG of full page
                    'screenshot_w': int,      # pixel width  of screenshot
                    'screenshot_h': int,      # pixel height of screenshot
                    'pdf_w': float,           # page width  in PDF points
                    'pdf_h': float,           # page height in PDF points
                }
            ],
            'page_count': int,        # pages actually rendered (what gets billed)
            'total_page_count': int,  # pages in the PDF
            'selected_pages': [int],  # the absolute page numbers rendered
        }
    """
    dpi = screenshot_dpi or SCREENSHOT_DPI
    total = len(doc)
    if selected_pages is None:
        wanted = list(range(1, total + 1))
    else:
        wanted = [p for p in sorted(set(selected_pages)) if 1 <= p <= total]

    pages = []
    for page_num in (p - 1 for p in wanted):
        page = doc[page_num]
        text = page.get_text('text')

        # Render full page as JPEG screenshot for Claude
        pix = page.get_pixmap(dpi=dpi)
        screenshot_b64 = base64.b64encode(pix.tobytes('jpeg')).decode('utf-8')

        pages.append({
            'page_num': page_num + 1,
            'text': text,
            'screenshot': screenshot_b64,
            'screenshot_w': pix.width,
            'screenshot_h': pix.height,
            'pdf_w': page.rect.width,
            'pdf_h': page.rect.height,
        })
        # Release the raw pixmap buffer promptly — the base64 is already kept.
        pix = None

    return {
        'pages': pages,
        'page_count': len(pages),
        'total_page_count': total,
        'selected_pages': wanted,
    }


# ---------------------------------------------------------------------------
# Question types the extractor can emit — one list, used twice
# ---------------------------------------------------------------------------
#
# The classification schema's enum is BUILT from this list, and the three review
# previews (worksheet upload, homework upload, AI import) render their "Question
# Type" <select> from it. They must not drift apart, because the drift fails
# SILENTLY: a <select> whose options don't include the extracted type renders
# showing its FIRST option instead — "Multiple Choice" — and the preview POST
# then saves that. That is how a "complete the chart" question extracted as
# table_of_values (with a table_spec the app can draw and grade) reached the
# teacher as a multiple choice with no options to tick.
EXTRACTED_QUESTION_TYPE_CHOICES = [
    ('multiple_choice', 'Multiple Choice'),
    ('true_false', 'True / False'),
    ('short_answer', 'Short Answer'),
    ('fill_blank', 'Fill in the Blank'),
    ('calculation', 'Calculation'),
    ('extended_answer', 'Extended Answer (written)'),
    ('long_division', 'Long Division'),
    ('prime_factorization', 'Prime Factorization'),
    ('column_operation', 'Column Arithmetic'),
    ('plot_points', 'Plot Points (Cartesian plane)'),
    ('plot_line', 'Plot a Line / Shape (Cartesian plane)'),
    ('identify_coords', 'Identify Coordinates (type the point)'),
    ('read_graph', 'Read a Graph (read off a value)'),
    ('measure', 'Measure (angle/scale, tolerance-graded)'),
    ('number_line', 'Number Line (mark or read a value)'),
    ('table_of_values', 'Table of Values (fill in the table)'),
    ('shape_select', 'Shape Select (find & colour shapes)'),
    ('sketch_graph', 'Sketch a Graph (vertex / intercepts / axis of symmetry)'),
]

EXTRACTED_QUESTION_TYPES = [value for value, _label in EXTRACTED_QUESTION_TYPE_CHOICES]


# Which structured-spec panel a review card shows for a given question type.
#
# The review editor renders EVERY panel on EVERY card (hidden) so switching the
# type reveals that type's fields without a reload. Rendering them is fine;
# SUBMITTING them is not. A browser posts every enabled field it can see or not
# see, so each card was sending ~29 parts — 16 of them spec fields the view
# ignores for that question's type — and a long workbook crossed Django's
# DATA_UPLOAD_MAX_NUMBER_FIELDS in the request parser, before any view ran. That
# surfaces as a bare "Bad Request (400)" with the URL still on the review page
# (prod session 134, and session 23 before it under a lower ceiling).
#
# So the panels that don't apply are rendered DISABLED: still there for the type
# dropdown to reveal, not posted until they are. This mapping is the one source
# of truth for "which panel applies", used by the view to render the disabled
# state and mirrored by the page's own handleTypeChange().
SPEC_PANEL_BY_QUESTION_TYPE = {
    'long_division': 'longdiv',
    'prime_factorization': 'primefactor',
    'column_operation': 'column',
    'plot_points': 'plane',
    'plot_line': 'plane',
    'identify_coords': 'plane',
    'read_graph': 'graph',
    'measure': 'measure',
    'number_line': 'numberline',
    'table_of_values': 'table',
    'sketch_graph': 'sketch',
}

# Panels in the order the review card renders them. Keeping the list here (rather
# than only in the template) is what lets a test assert every panel is covered.
SPEC_PANELS = [
    'longdiv', 'primefactor', 'column', 'plane', 'graph',
    'measure', 'numberline', 'table', 'sketch',
]

# The types whose answer is computed from a spec (or that take free text), so the
# review card hides its answer-options box. Mirrored by handleTypeChange().
SPEC_GRADED_QUESTION_TYPES = frozenset(SPEC_PANEL_BY_QUESTION_TYPE) | {'extended_answer'}


def spec_panel_for_type(question_type):
    """The panel key a question of this type edits, or '' when it has none.

    '' covers the plain types (short answer, multiple choice, …) — every panel
    on their card is inactive, so none of the spec fields are posted.
    """
    return SPEC_PANEL_BY_QUESTION_TYPE.get((question_type or '').strip(), '')


def accepted_question_type(posted, stored):
    """The type a review POST should store: ``posted``, unless it is a value we
    do not recognise — then ``stored`` is kept.

    Fail towards the type the extractor worked out. A posted value that is
    neither an extractor type nor a real question type is a stale page, a
    tampered form or a renamed type; taking it would quietly replace a working
    question with one that grades as nothing.
    """
    from maths.models import Question

    posted = (posted or '').strip()
    if not posted:
        return stored
    known = set(EXTRACTED_QUESTION_TYPES) | {v for v, _ in Question.QUESTION_TYPES}
    return posted if posted in known else stored


def preview_question_type_choices(questions=None):
    """(value, label) pairs for a review preview's "Question Type" dropdown.

    Every type in ``questions`` is guaranteed to appear, even one this module
    has never heard of (an older session, another extractor, a hand-authored
    import). A type with no matching <option> is not a cosmetic problem — the
    browser shows the first option instead and the POST silently rewrites the
    question to it, losing the type AND the spec that made it gradeable.
    """
    choices = list(EXTRACTED_QUESTION_TYPE_CHOICES)
    known = {value for value, _ in choices}
    for q in questions or []:
        q_type = (q.get('question_type') or '').strip()
        if q_type and q_type not in known:
            known.add(q_type)
            choices.append((q_type, q_type.replace('_', ' ').title()))
    return choices


# ---------------------------------------------------------------------------
# AI classification tool schema
# ---------------------------------------------------------------------------

WORKSHEET_CLASSIFICATION_TOOL = {
    "name": "classify_worksheet_questions",
    "description": (
        "Extract and classify all questions from a worksheet PDF. "
        "For each question that has a visual element (shape, diagram, graph, table, "
        "number line, ruler, grid, coordinate plane, etc.), return the pixel bounding "
        "box of ONLY that visual on the page screenshot image."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "year_level": {"type": "integer", "description": "Default year/grade level (1-12)"},
            "subject": {"type": "string", "description": "e.g. Mathematics"},
            "strand": {"type": "string", "description": "e.g. Number, Geometry, Measurement"},
            "topic": {"type": "string", "description": "e.g. Fractions, Area, Angles"},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_text": {
                            "type": "string",
                            "description": (
                                "The question text ONLY. Do not include answer options here. "
                                "Do not describe the image — just state the question."
                            ),
                        },
                        "question_type": {
                            "type": "string",
                            "enum": list(EXTRACTED_QUESTION_TYPES),
                        },
                        "plane_spec": {
                            "type": "object",
                            "description": (
                                "For plot_points / plot_line / identify_coords only — a signed Cartesian "
                                "plane. bounds = visible axis range; mode 'points' (plot/identify dots) or "
                                "'segments' (a line/shape to join); target = the correct answer (points OR "
                                "segments) in SIGNED integer coords; given_points = points already drawn "
                                "for the student to read — [x, y], or [x, y, \"A\"] to NAME the point when "
                                "the question does. A DERIVED answer (a mid point, an intersection) belongs "
                                "in target only, never in given_points. The app draws the blank plane, so "
                                "set has_image=false for these types."
                            ),
                        },
                        "graph_spec": {
                            "type": "object",
                            "description": (
                                "For read_graph only and OPTIONAL — a clean re-draw of the line graph "
                                "(x_axis/y_axis with label/unit/min/max/step; series with points). Only "
                                "supply when you can read the series points confidently; otherwise omit it "
                                "and keep the graph image (has_image=true)."
                            ),
                        },
                        "number_line_spec": {
                            "type": "object",
                            "description": (
                                "For number_line only — a horizontal number line. "
                                "min/max = the scale's end values; step = the tick interval "
                                "(default 1); mode 'mark' (the app draws the blank scale and "
                                "the student marks value(s)) or 'read' (the app draws marker "
                                "arrow(s) at 'given' positions and the student types the "
                                "value(s)); target = the correct value(s) to mark/read (numbers "
                                "on the scale, each landing on a tick); given = value(s) already "
                                "marked with an arrow (read mode). For a 'graph the inequality' "
                                "question give inequality {'op': '<='|'<'|'>='|'>', 'value': number} "
                                "and NO target — the app derives every satisfying tick, boundary "
                                "included for <= and >=. The app draws the line, so set "
                                "has_image=false for this type."
                            ),
                        },
                        "sketch_spec": {
                            "type": "object",
                            "description": (
                                "For sketch_graph only — a 'sketch the graph showing the "
                                "vertex / intercepts / axis of symmetry' question. "
                                "equation = the function as printed (\"y = x^2 + x - 2\"). "
                                "bounds = the integer axis range of the grid printed on the "
                                "sheet {xmin, xmax, ymin, ymax}, wide enough to contain every "
                                "feature below. curve = the coefficients so the app can draw "
                                "the answer: {\"type\": \"quadratic\", \"a\", \"b\", \"c\"} for "
                                "y = ax^2+bx+c (expand a factored or vertex form first) or "
                                "{\"type\": \"linear\", \"m\", \"c\"}. features = ONLY the "
                                "features this question actually asks the student to show, in "
                                "the order it lists them: {\"kind\": \"vertex\", \"points\": "
                                "[[x, y]]}, {\"kind\": \"x_intercept\", \"points\": [[x, 0], "
                                "...]}, {\"kind\": \"y_intercept\", \"points\": [[0, y]]}, "
                                "{\"kind\": \"axis_of_symmetry\", \"value\": x}. Coordinates are "
                                "DECIMALS, not grid squares — the vertex of y = x^2 + x - 2 is "
                                "(-0.5, -2.25). Work every value out from the equation and "
                                "check it. The app draws the plane, so set has_image=false."
                            ),
                        },
                        "table_spec": {
                            "type": "object",
                            "description": (
                                "For table_of_values only — a table the student fills in. "
                                "headers = the column names, e.g. [\"x\", \"y\"]. rows = one list "
                                "per row with exactly one cell per header; each cell is either "
                                "{\"given\": \"-3\"} (printed on the sheet, the student reads it) "
                                "or {\"answer\": \"7\"} (a blank the student fills). Every answer "
                                "value must be NUMERIC — grading is numeric-within-tolerance — and "
                                "at least one answer cell is required. Optional tolerance (default "
                                "0). Work each answer out from the rule in the question and check "
                                "it. The app draws the table, so set has_image=false."
                            ),
                        },
                        "numeric_answer": {
                            "type": "number",
                            "description": "For read_graph and measure: the value to read off / measure (e.g. 135 for a 135° angle).",
                        },
                        "answer_tolerance": {
                            "type": "number",
                            "description": "For read_graph and measure: accepted ± band around numeric_answer (e.g. 2). Omit for exact.",
                        },
                        "answer_unit": {
                            "type": "string",
                            "description": "For read_graph and measure: unit shown after the answer box, e.g. '°', 'cm', 'km'.",
                        },
                        "shape_target_type": {
                            "type": "string",
                            "enum": ["triangle", "circle", "square", "rectangle",
                                     "ellipse", "rhombus"],
                            "description": (
                                "For shape_select only: WHICH kind of shape the question asks "
                                "the student to find/colour. Give only this — never the shapes' "
                                "positions or outlines; the app traces those from the picture."
                            ),
                        },
                        "target_number": {
                            "type": "integer",
                            "description": (
                                "For prime_factorization only: the number to break into its "
                                "prime factors, e.g. 60. The app draws the factor ladder and "
                                "computes the answer itself."
                            ),
                        },
                        "dividend": {
                            "type": "integer",
                            "description": "For long_division only: the number being divided (under the bar), e.g. 611.",
                        },
                        "divisor": {
                            "type": "integer",
                            "description": "For long_division only: the number dividing (outside/left of the bar), e.g. 47.",
                        },
                        "operands": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "For column_operation only: the stacked numbers top-to-bottom, e.g. [23, 25].",
                        },
                        "operator": {
                            "type": "string",
                            "enum": ["+", "-", "*"],
                            "description": "For column_operation only: the arithmetic operator ('+', '-' or '*').",
                        },
                        "validation_type": {
                            "type": "string",
                            "enum": ["auto", "ai_graded", "human_graded"],
                            "description": (
                                "How this answer will be validated. "
                                "auto = system checks exact answer (MCQ, T/F, numeric). "
                                "ai_graded = Claude evaluates written reasoning (proofs, explanations). "
                                "human_graded = teacher marks it on paper. Required whenever the "
                                "answer is a DRAWING the app cannot accept (draw a tree/Venn "
                                "diagram, sketch a graph, construct a triangle, shade a region, "
                                "complete a table) — the student writes nothing, so ai_graded is "
                                "wrong. Also for very open-ended / subjective questions."
                            ),
                        },
                        "grading_rubric": {
                            "type": "string",
                            "description": (
                                "Required when validation_type is ai_graded or human_graded. "
                                "List the KEY MATHEMATICAL FACTS, THEOREMS, and CONCEPTS a correct "
                                "answer must use or demonstrate — do NOT prescribe one specific proof "
                                "path. There are often multiple valid approaches; the rubric should "
                                "describe WHAT needs to be shown (e.g. which angle relationships are "
                                "relevant, what the final conclusion must be), not HOW the student "
                                "must get there. Also note common mistakes to penalise and "
                                "partial-credit criteria. Leave empty for auto-validated questions."
                            ),
                        },
                        "difficulty": {"type": "integer", "enum": [1, 2, 3]},
                        "points": {"type": "integer", "default": 1},
                        "explanation": {
                            "type": "string",
                            "description": (
                                "Clear explanation of WHY the correct answer is correct. "
                                "Be specific and educational. This is shown to students when they get it wrong."
                            ),
                        },
                        "page_num": {
                            "type": "integer",
                            "description": "1-based page number this question appears on.",
                        },
                        "source_number": {
                            "type": "integer",
                            "description": (
                                "The question's own number as printed on the paper — 46 for "
                                "'Question 46', '46.' or 'Q46'. This is the paper's numbering, "
                                "NOT the position in your list, so keep it even when you skip "
                                "something. Omit only if the question is genuinely unnumbered. "
                                "Used to match the paper's answer key onto its questions."
                            ),
                        },
                        "has_image": {
                            "type": "boolean",
                            "description": (
                                "True ONLY if this question has a shape, diagram, graph, table, "
                                "number line, ruler, grid, or any visual students need to see. "
                                "False for pure text questions."
                            ),
                        },
                        "image_bbox": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 4,
                            "maxItems": 4,
                            "description": (
                                "Required when has_image=true. "
                                "Pixel coordinates [left, top, right, bottom] of the visual element "
                                "in the PAGE SCREENSHOT image. "
                                "CRITICAL rules for the bbox:\n"
                                "- Crop ONLY the diagram/shape/graph itself.\n"
                                "- Do NOT include the question text above or below the visual.\n"
                                "- Do NOT include answer option text.\n"
                                "- Do NOT include section headings (e.g. 'Questions', 'Section A').\n"
                                "- Do NOT include question numbers (e.g. '1.', 'Q2').\n"
                                "- The top edge of the bbox must be at or below the first pixel of the actual visual — never above it.\n"
                                "- Leave a few pixels of whitespace around the visual but nothing more."
                            ),
                        },
                        "year_level": {"type": "integer"},
                        "subject": {"type": "string"},
                        "strand": {"type": "string"},
                        "topic": {"type": "string"},
                        "answers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "is_correct": {"type": "boolean"},
                                },
                                "required": ["text", "is_correct"],
                            },
                        },
                    },
                    "required": [
                        "question_text", "question_type", "validation_type",
                        "difficulty", "answers", "page_num", "has_image",
                    ],
                },
            },
        },
        "required": ["year_level", "subject", "strand", "topic", "questions"],
    },
}

WORKSHEET_SYSTEM_PROMPT = """You are an expert at reading school homework worksheets.

Rules:
1. Extract EVERY question in order. Do not skip any.
2. question_text = the question only. Never include answer options inside question_text.
   question_text MUST be SELF-CONTAINED: include the full stem/context a student needs to
   answer, even if it spans several lines above the prompt. Example: a sheet reading
   "Cars and motorbikes are parked in a street. Stefan counts 3 motorbikes and 5 cars. He
   counts 28 wheels altogether. Explain why Stefan cannot be correct." must keep ALL of that
   in question_text — not just "Explain why Stefan cannot be correct." Carry numbers, names
   and given facts into the text; do not assume the image will supply them.
   Do NOT copy the worksheet's question number or section label into question_text. Strip any
   leading enumeration such as "Question 5", "Question 5 e)", "Q154", "5.", "5)", "a)",
   "(iii)", "PART C:", "Section B", or "Exercise 3:" — start question_text at the first word
   of the actual question. Remove only the numbering/label, never the wording a student needs.
3. For questions with a VISUAL (shape, diagram, ruler, number line, graph, table,
   geometric figure, coordinate plane): set has_image=true and give image_bbox as the
   pixel bounding box of ONLY the visual in the page screenshot.
   - Do NOT include the question text in the bbox.
   - Do NOT include answer option text in the bbox.
   - Do NOT include section headings like "Questions", "Section A", "Exercise" etc.
   - Do NOT include question numbers (e.g. "1.", "Q2").
   - The TOP edge of the bbox must sit at or below the first pixel of the actual visual.
   - The bbox should tightly surround just the visual element with a small margin.
   - MATCH THE IMAGE TO THIS QUESTION'S TEXT. The bbox must be the visual that THIS
     question's text refers to. If the text says "the pictogram shows…", "from the graph…",
     "the table below", "this diagram", "name this shape" — the bbox MUST be exactly that
     pictogram/graph/table/diagram/shape, sitting next to this question.
   - NEVER attach a visual that belongs to a DIFFERENT question — a neighbouring diagram,
     another question's working grid, squared paper, or answer box. When questions sit close
     together, double-check the region you cropped is the one this text describes.
   - SELF-CHECK: if the text references a pictogram/graph/table but the region you would crop
     is squared paper, a calculation, or a blank box, you have the WRONG region — find the
     actual visual, or set has_image=false if it genuinely isn't present.
4. For numeric/calculation questions ("What is 24 ÷ 6?"), use short_answer. Do NOT invent
   wrong options. Instead, list EVERY form a student could reasonably type as a SEPARATE
   answer, each with is_correct=true (the auto-grader accepts any ticked answer). In
   particular, when the answer carries a unit, include BOTH the bare number and the
   number-with-unit, e.g. "How many months in 5 years?" → "60 months" AND "60"; a money
   answer → "$4.50" AND "4.50"; "3/4" → "3/4" AND "0.75". Do NOT add forms that are merely
   spacing/comma/hyphen variants — the grader already ignores those.
5. For multiple choice, list ALL provided answer options including the correct one.
6. Write explanations that help students understand why they got it wrong.
7. Do NOT skip questions even if they look simple.
8. MATCHING / "name each" questions: when ONE question asks the student to match or name
   SEVERAL items (e.g. "Match each diagram to the name of the dashed line" with 3 circle
   diagrams, or "Name each shape"), SPLIT it into ONE multiple_choice question PER item:
   - Emit one question per individual diagram/shape/item (3 diagrams → 3 questions).
   - Each question's image_bbox is a TIGHT crop of THAT ONE item only.
   - question_text states what to identify, e.g. "What is the name of the dashed line shown
     in this diagram?" or "Name the shape shown in this diagram."
   - answers = ALL the candidate names offered by the question (the full match list), with
     is_correct=true on the one that fits this item and the others as distractors. Example:
     the circle question offers circumference / diameter / radius → every split question uses
     those three as the options, with the correct one marked per diagram.
   - validation_type = "auto". Never merge several items into one combined answer string.
9. LONG DIVISION: if a division is drawn in the "bus stop" layout — the divisor written
   to the LEFT of a vertical bar and the dividend UNDER a horizontal bar (e.g. "47" outside,
   "611" under the bar) — set question_type="long_division", "dividend" to the number under
   the bar and "divisor" to the number outside it, and question_text to
   "Solve using long division: {dividend} ÷ {divisor}". Do NOT concatenate the digits into
   one number (never "47611") and set has_image=false — the app draws the bracket itself.
   The answer is computed automatically; leave answers=[].
9b. PRIME FACTORISATION: if the question asks the student to break a number into its
   PRIME FACTORS — "write 60 as a product of its prime factors", "find the prime
   factorisation of 84", a factor tree or factor ladder drawn around a starting number —
   set question_type="prime_factorization" and "target_number" to the number being
   factorised (60, 84). Set question_text to the instruction, e.g.
   "Write 60 as a product of its prime factors". Set has_image=false — the app draws the
   ladder itself, so a cropped factor tree would be a second, conflicting figure. The
   answer is computed from target_number; leave answers=[] and validation_type="auto".
   NOT this type: "list the factors of 24" (every factor, not just primes — that is a
   short_answer with answer_format "set"), "is 17 prime?" (true_false), and
   "find the HCF of 24 and 60" (short_answer).
10. COLUMN ARITHMETIC: if numbers are stacked vertically for addition, subtraction or
   multiplication — written one under another, right-aligned, with a +, − or × sign and a
   rule line under which the answer goes (e.g. "23" above "+ 25" with a line below) — set
   question_type="column_operation", "operands" to the stacked numbers top-to-bottom
   (e.g. [23, 25]), and "operator" to "+", "-" or "*". Set question_text to the inline form,
   e.g. "23 + 25". Do NOT concatenate the digits into one number (never "2325") and set
   has_image=false — the app draws the stacked grid itself. The answer is computed
   automatically; leave answers=[].
11. CARTESIAN PLANE: if the question shows a BLANK signed coordinate plane (numbered x/y axes,
   four quadrants) and asks the student to PLOT coordinates, use "plot_points" — put the visible
   axis range in plane_spec.bounds, mode "points", and the coordinates to plot in
   plane_spec.target.points (signed integers, e.g. [[3,-2]]). If it asks to plot AND JOIN points
   into a line/shape, use "plot_line" — mode "segments" and plane_spec.target.segments as the
   joined line ([{"x1","y1","x2","y2"}]). If the student must WRITE coordinates rather than plot
   them, use "identify_coords" — mode "points", plane_spec.target.points = the coordinates to write
   (the ANSWER), plane_spec.given_points = what is DRAWN for them to read. These are the same only
   when the answer is the plotted point itself ("write the co-ordinates of P"). When the answer is
   DERIVED — "A is (2,2), B is (8,2), C is (5,8); D is the mid point of AB, write down D" — draw
   A, B and C via given_points and put D in target.points ONLY; drawing a derived answer hands the
   child the answer. Name the given points as [x, y, "A"] whenever the question names them.
   Set has_image=false (the app draws the plane) and leave answers=[].
12. READ A GRAPH: if a PRE-DRAWN line graph (e.g. distance-vs-time) is shown and the student must
   READ a value off it, use "read_graph". Set numeric_answer to the value to read,
   answer_tolerance to a sensible ± band, answer_unit to the axis unit. Keep the graph image
   (has_image=true, image_bbox around the graph). Only add graph_spec if you can read the series
   points confidently; otherwise omit it. Leave answers=[]; validation_type="auto".
13. MEASURE (angle / scale / ruler): if the student must MEASURE a drawn figure and write the value —
   read an ANGLE with a protractor, a length with a ruler, or a value off a marked scale/dial — use
   "measure". Set numeric_answer to the true value, answer_tolerance to a sensible ± band (e.g. 2 for
   an angle), and answer_unit to the unit ("°" for angles, "cm"/"mm" for lengths). For an ANGLE the
   app draws a true-to-scale figure from numeric_answer, so set has_image=false. For a length/scale
   the pupil measures a picture, so keep it: has_image=true with image_bbox around the figure. Leave
   answers=[]; validation_type="auto".
14. NUMBER LINE: if the question shows (or asks the student to draw/use) a horizontal NUMBER LINE and
   the task is to MARK a value on it or READ the value an arrow points to, use "number_line" and fill
   number_line_spec. Set min/max to the scale's end values and step to the tick interval (usually 1).
   Use mode "mark" when the student must place/mark a value ("mark 5 on the number line", "draw a
   number line from -3 to 7 and show 2") — put the value(s) to mark in target. Use mode "read" when an
   arrow/marker is already drawn and the student reads its value — put the marked position(s) in given
   (target defaults to given). Every target/given value must land exactly on a tick. A "draw/graph the
   inequality" question ("draw a graph for the inequality k <= -2") is mode "mark", but do NOT list its
   ticks in target: give inequality {"op": "<="|"<"|">="|">", "value": -2} and leave target out. The app
   works out every tick that satisfies it, boundary included for <= and >=, so the answer cannot lose the
   boundary tick. The app draws the line, so set has_image=false. Leave answers=[];
   validation_type="auto".
14b. FIND / COLOUR THE SHAPES: if the question shows a SET of 2D shapes — a row, grid or
   scatter of them — and asks the student to find, colour, tick or circle every shape of ONE
   kind ("Colour all the triangles", "Tick each rectangle", "Circle the circles"), set
   question_type="shape_select" and shape_target_type to that kind (triangle, circle, square,
   rectangle, ellipse or rhombus). Set has_image=true with image_bbox around the WHOLE set of
   shapes — every shape the question covers, not just one. Do NOT describe the shapes, their
   positions or their outlines: the app TRACES them from the picture you box, and a traced
   outline beats a described one. Leave answers=[] and validation_type="auto".
   NOT this type: "name this shape" (one shape to identify — multiple_choice, rule 8),
   "how many triangles are there?" (a count — short_answer), and "draw a triangle"
   (rule 18).
15. TABLES: if the question depends on reading a DATA TABLE (rows/columns of values — a
   timetable, price list, tally/frequency table, results table, conversion table, etc.), set
   has_image=true and give image_bbox tightly around the WHOLE table (all its rows, columns and
   header cells — never clip a column). Do NOT transcribe the table's data into question_text —
   keep question_text to the actual instruction ("Using the table, which city had the largest
   range?") and let the cropped table image carry the figures. The app cannot redraw a table, so
   the image is the only record of it: attaching it is required whenever the answer can't be found
   without the table.
16. TABLE TO COMPLETE: if the question gives a rule and a table to fill in — "complete
   the table for y = x² - 5", a table of x values with the y row blank, an in/out or
   function table — use "table_of_values" and fill table_spec. headers = the column names
   ("x", "y"); rows = one list per row, one cell per header, each cell either
   {"given": "3"} for a value printed on the sheet or {"answer": "4"} for a blank the
   student fills. Work every answer out from the rule and verify it — they are graded
   numerically, so they must be numbers, and at least one answer cell is required. The app
   draws the table, so set has_image=false, leave answers=[] and validation_type="auto".
   This is a REAL answerable question: prefer it over sending the table to the teacher
   under rule 18. Only when you cannot express the table this way — the cells are not
   numeric, or there is no rule to compute them from — fall back to rule 18.
17. SKETCH A GRAPH SHOWING ITS KEY FEATURES: if the question gives an equation and asks the
   student to SKETCH/DRAW its graph AND to show named features of it — "Sketch the graph of
   y = x² + x - 2 showing the coordinates of the vertex, x-axis and y-axis intercepts and
   equation of the axis of symmetry", "Sketch the parabola y = x² - 3x - 4 on the axes
   provided showing clearly: the y-intercept, the x-intercepts, the vertex" — use
   "sketch_graph" and fill sketch_spec. The student plots the curve on the plane the app
   draws and types the NAMED FEATURES; both are marked. So:
   - equation = the function exactly as printed. bounds = the axis range of the grid on the
     sheet (integers), widened if needed so every feature below sits inside it.
   - curve = the coefficients of the EXPANDED form. ALWAYS give it: it is what the sketch
     the student draws is marked against, and what the app draws the answer with.
     y = 2(x+1)² - 4 is {"type": "quadratic", "a": 2, "b": 4, "c": -2};
     y = -(x-3)(x+1) is {"type": "quadratic", "a": -1, "b": 2, "c": 3}.
   - features = ONLY what this question asks for, in its order. Work each one out from the
     equation and CHECK it: vertex (-b/2a, y at that x), x_intercept (solve y = 0 — list
     every root; omit the feature entirely if there are none), y_intercept (x = 0), and
     axis_of_symmetry (the x of the vertex). Values are decimals: (-0.5, -2.25), not (0, -2).
   Set has_image=false (the app draws the plane), leave answers=[] and validation_type="auto".
   A question that only says "sketch the graph" with no features to show is NOT this type —
   there is nothing to type, so it is rule 18.
18. DRAWING / CONSTRUCTION — questions the app cannot take an answer for. A student
   answers in this app by typing, picking an option, or using one of the drawing surfaces
   the app itself renders (rules 9-14, 17, and 9b/14b). They CANNOT draw a picture. So if the task is to
   PRODUCE a visual — "Draw a tree diagram to illustrate this situation", "Draw a Venn
   diagram", "Construct a triangle with compasses", "Draw a
   bar chart", "Shade the region", "Colour the shape", "Join the
   points to form a quadrilateral" — set validation_type="human_graded". (A bare
   "Sketch the graph of y = 2x" with no features named is one of these; the same
   instruction WITH features to show is rule 17, and answerable.) This covers every
   way of asking for the same drawing, not just the ones starting with "draw": "Illustrate
   on a Venn diagram the sets A = {1, 3, 5} and B = {2, 4, 6}", "Represent this data in a
   pie chart", "Show the information on a bar graph", "Display the results using a
   pictograph", "Use a tree diagram to work out the probability", "Add these elements to
   the Venn diagram", "Record your results in a tally chart". If the finished answer is a
   picture, it is human_graded however the instruction is worded. A table to fill in is
   NOT one of these — that is rule 16, and it is answerable. NOT ai_graded:
   the student writes no prose, so there is nothing for a grader to read. Put what the
   finished drawing must show in grading_rubric so the teacher can mark it on paper. Keep
   the question (do not drop it) — the app deselects teacher-graded questions by default
   and the teacher decides.
   EXCEPTIONS, because the app draws these answer surfaces itself — keep them as their own
   question type with validation_type="auto": marking or reading a horizontal NUMBER LINE
   (rule 14), plotting/joining points on a CARTESIAN PLANE (rule 11), LONG DIVISION
   (rule 9), PRIME FACTORISATION (rule 9b), COLUMN ARITHMETIC (rule 10), a TABLE TO
   COMPLETE (rule 16), FINDING/COLOURING SHAPES IN A SET (rule 14b), and SKETCHING A
   GRAPH AND SHOWING ITS KEY FEATURES (rule 17). "Plot (3, -2) on the grid", "complete the
   table for y = 3x" and "sketch y = x² + x - 2 showing the vertex and the intercepts" are
   answerable; "Draw a tree diagram" is not.

IMAGE NECESSITY (set has_image=true ONLY when a visual carries information):
- has_image=true ONLY when the question genuinely depends on a visual that cannot be written
  as text: a shape to identify, a diagram/figure, a graph/chart, a data table, a number line,
  a ruler/protractor reading, a clock face, a coordinate plane, a picture to interpret.
- has_image=false for decorative or scaffolding graphics that carry NO information — blank
  answer boxes, working space, grid/squared paper, ruled lines, long-division brackets,
  column/stacked-arithmetic grids, page borders. Transcribe the maths into text/fields instead.
  Example: an "Explain why…" question followed by a big empty box or squared grid for the
  student's working has has_image=false — the box holds no information.
- When unsure, prefer has_image=false. A wrongly-attached image is worse than none.

ANSWER ACCURACY — VERIFY EVERY ANSWER BEFORE RETURNING IT:
Do NOT guess answers. Re-derive each answer from the numbers, figures and expressions
actually shown in the question, then check it.
- For computational questions (arithmetic, algebra, expand/simplify, fractions, etc.)
  work the problem out fully, step by step, and confirm the final result. The answer text
  you return MUST equal that verified result — never a hasty first pass.
- The explanation must be a CLEAN, FINAL explanation of why the correct answer is correct.
  Do your working silently; never put scratch work, self-corrections, or "wait, let me
  redo this" notes into the explanation. Only the verified conclusion belongs there.
- The answer and the explanation must describe the SAME result. Never let the answer text
  and the explanation disagree with each other or with the figure. If they disagree,
  recompute until they match before returning.
- COUNTING AND ARITHMETIC ARE SHOWN, NOT ASSERTED: when an answer depends on counting
  items in a figure (leaves in a stem-and-leaf plot, dots, tally marks, bars, rows of a
  table) or on adding parts, write the items or parts out in the explanation and let the
  count or sum follow from what you wrote — "stem 1: 4, 7, 8 (3 leaves); stem 2: 0, 2, 4,
  5, 7, 8, 8, 9 (8 leaves); stem 3: 0, 3, 7 (3 leaves); 3 + 8 + 3 = 14 values". For a
  median, write the FULL ordered list, state n as the number of values in THAT list, and
  take the middle value (the mean of the two middle values when n is even). Count the list
  you wrote before stating n, and re-add every sum's parts before stating its total. A
  stated count that disagrees with the list, or a sum that does not add up, is caught
  automatically and sent to the teacher as a suspect answer.
- If you cannot determine the correct answer with confidence, set validation_type to
  "human_graded" rather than inventing one.

Choosing validation_type per question:
- auto        → MCQ, T/F, short numeric answers, fill-in-the-blank. The system can check
                 the answer exactly. Most questions will be this type.
- ai_graded   → Written explanations, proofs, "show your working", "explain why" questions
                 where the student writes free text and partial credit is meaningful.
                 Write a detailed grading_rubric describing what a full-mark answer must
                 include, common errors to penalise, and partial-credit criteria.
                 NEVER ai_graded when the answer is a DRAWING (rule 18) — the student
                 types nothing, so there is no written answer to grade.
- human_graded → Two cases:
                 (a) the answer is a drawing/construction the app can't accept (rule 18) —
                     "draw a tree diagram", "illustrate on a Venn diagram", "represent this
                     data in a bar graph", "shade the region";
                 (b) highly open-ended/subjective questions where even AI cannot reliably
                     determine correctness (creative responses, complex multi-step proofs
                     that vary widely).
                 For (b) use sparingly — prefer ai_graded. For (a) human_graded is the ONLY
                 correct answer; never downgrade one of these to ai_graded or auto.

For extended_answer questions (ai_graded / human_graded):
- Set question_type = "extended_answer"
- Set answers = [] (no fixed answer options)
- Always write a grading_rubric that lists the key facts/theorems needed,
  NOT a single prescriptive proof path. Students may use different but equally
  valid reasoning chains — the rubric must accept all of them."""


SHAPE_NAMING_SYSTEM_PROMPT = """You are building "name the shape" practice questions from a worksheet that DISPLAYS shapes.

The worksheet shows one or more SHAPES — a chart, grid, row, or scattered set, possibly
already labelled. Your job is to turn EACH INDIVIDUAL shape into its OWN question.

Rules:
1. Emit ONE question PER individual shape. If the page shows 8 shapes, return 8 questions.
   - Never group multiple shapes into one question.
   - Ignore any shape names already printed on the sheet — you are generating fresh
     questions, so do not leak the answer into question_text.
2. For EVERY shape question, set exactly:
   - question_text = "What is the name of this shape?"
   - question_type = "multiple_choice"
   - validation_type = "auto"
   - has_image = true
   - image_bbox = a TIGHT pixel box around ONLY that ONE shape in the page screenshot.
       * One shape per box. Never include a neighbouring shape.
       * Do NOT include the shape's printed name/label, question numbers, or headings.
       * Leave only a few pixels of margin around the shape itself.
       * Coordinates are [left, top, right, bottom] in the page screenshot's pixel space.
   - answers = the CORRECT shape name (is_correct=true) PLUS exactly 3 plausible wrong
     shape names (is_correct=false). Distractors must be real shapes a learner might
     confuse it with (square ↔ rectangle / rhombus; circle ↔ oval / ellipse;
     triangle types; pentagon ↔ hexagon). Never repeat the correct name as a distractor.
   - difficulty = 1 for common shapes (circle, square, triangle, rectangle); 2 for
     less common ones (trapezium, parallelogram, rhombus, pentagon, hexagon, octagon);
     3 for advanced/3-D solids.
   - explanation = ONE short sentence on the defining property
     (e.g. "A triangle has 3 straight sides and 3 angles.").
3. Identify each shape yourself from the picture. Use standard names. Prefer a specific
   name only when clearly distinguishable (e.g. "Rectangle", "Equilateral triangle");
   otherwise use the general name ("Triangle", "Quadrilateral").
4. Classification: subject "Mathematics", strand "Geometry", topic "2D Shapes"
   (or "3D Shapes" for solids). Use the year level implied by the sheet, default 1.
5. In this mode emit ONLY shape-naming questions — skip any non-shape text questions."""


def _get_anthropic_client():
    import anthropic
    # PDF classification can take 60-90s for large worksheets — raise the
    # default httpx timeout (30s) so the request isn't killed mid-flight.
    # max_retries above the SDK default of 2 because chunks run WORKSHEET_MAX_PARALLEL
    # -wide: a burst can trip a rate limit, and one chunk exhausting its retries
    # fails the whole upload. Retries are backed off, so this trades a slower
    # worst case for not losing the run.
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=120.0,
        max_retries=int(os.environ.get('WORKSHEET_MAX_RETRIES', '5')),
    )


def _build_system_prompt(existing_topics, existing_levels, shape_naming=False):
    topic_names = ', '.join(t['name'] for t in existing_topics) if existing_topics else 'None yet'
    level_names = ', '.join(
        f"Year {l['level_number']}" for l in existing_levels if l['level_number'] <= 12
    ) if existing_levels else 'Year 1–8'
    base = SHAPE_NAMING_SYSTEM_PROMPT if shape_naming else WORKSHEET_SYSTEM_PROMPT
    return (
        base
        + f"\n\nExisting topics in the system: {topic_names}"
        + f"\nAvailable year levels: {level_names}"
        + "\nMap to existing topics where possible."
    )


# Leading "question number" / section labels the model sometimes copies verbatim
# from a worksheet into question_text, e.g. "Question 5 e)", "Q154", "PART C:",
# "Section B", "5)", "a)", "(iii)". These are enumeration, not part of the actual
# question. The trailing (?=\s|$) after each label prevents clobbering real words
# that merely start the same way ("No cars…", "Problems arise…", "A cat…").
_QUESTION_LABEL_RE = re.compile(
    r"""
    ^\s*
    (?:
        # Abbreviations clamped onto a number: Q7, Q154, No. 5, #5, Prob 3
        (?:q|qn|no|prob)\.?\s*\#?\s*\d+
        (?:\s*[a-z]\s*[.)])?          # optional sub-part e.g. " e)"
        \s*[.):\-]?                   # optional trailing punctuation
      |
        # Full word + separator + standalone identifier: Question 5, PART C:, Section B:
        (?:question|part|section|exercise|problem)
        [\s.:\#\-]+
        (?:
            \d+ (?:\s*[a-z]\s*[.)])?  # number, optional " e)" sub-part
          | [a-z] \s* [.):]           # a single letter must end in . ) or : so a
                                      # following article ("Problem: A train") is safe
        )
        \s*[.):\-]?                   # optional trailing punctuation
      |
        \d{1,3}\s*[.):]              # bare number label: 5. 5) 5:
      |
        \(\s*[a-z0-9]{1,4}\s*\)      # bracketed label: (a) (iii) (5)
      |
        [a-z]\s*\)                   # single-letter label: a)
    )
    (?=\s|$)
    \s*
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _strip_question_label(question_text):
    """Remove a leading question-number / section label from question_text.

    Worksheets prefix questions with enumeration ("Question 5 e)", "Q154",
    "PART C:", "5)", "a)") that the model sometimes copies into question_text.
    That prefix is not part of the question itself, so drop it. Conservative and
    idempotent: only a recognised leading label is removed, and if stripping would
    empty the text the original is kept.
    """
    if not question_text:
        return question_text
    text = question_text
    # A question may carry more than one stacked label ("5. a) ..."). Strip a few,
    # but stop as soon as nothing matches or the text would be emptied.
    for _ in range(3):
        stripped = _QUESTION_LABEL_RE.sub('', text, count=1)
        if stripped == text or not stripped.strip():
            break
        text = stripped
    return text if text.strip() else question_text


def _label_question_number(question_text):
    """The number in a leading label ("Question 46", "46.", "Q46") — or None.

    A fallback for source_number: when the model copies the paper's numbering
    into question_text we can recover it before _strip_question_label discards
    it, and the paper's answer key can still be matched to the question.
    """
    if not question_text:
        return None
    label = _QUESTION_LABEL_RE.match(question_text)
    if not label:
        return None
    digits = re.search(r'\d{1,3}', label.group(0))
    return int(digits.group()) if digits else None


# ---------------------------------------------------------------------------
# Page roles — which pages carry questions, and which are the exam's scaffolding
# ---------------------------------------------------------------------------

PAGE_ROLE_QUESTIONS = 'questions'
PAGE_ROLE_ANSWER_SHEET = 'answer_sheet'
PAGE_ROLE_ANSWER_KEY = 'answer_key'
# Not a detected role — the page selection was longer than WORKSHEET_PAGE_CAP and
# the tail was dropped. Reported through the same notice so the cap can't silently
# swallow pages the teacher explicitly asked for.
PAGE_ROLE_OVER_CAP = 'over_cap'

PAGE_ROLE_LABELS = {
    PAGE_ROLE_ANSWER_SHEET: 'multiple-choice answer sheet',
    PAGE_ROLE_ANSWER_KEY: 'answer key',
    PAGE_ROLE_OVER_CAP: f'beyond the {WORKSHEET_PAGE_CAP}-page limit for one upload',
}

# Skipping is deterministic and free (plain text, no AI call), but keep an escape
# hatch: a paper whose question pages somehow trip a detector can be imported in
# full by setting WORKSHEET_SKIP_NON_QUESTION_PAGES=0, no deploy needed.
SKIP_NON_QUESTION_PAGES = os.environ.get(
    'WORKSHEET_SKIP_NON_QUESTION_PAGES', '1') != '0'

# A bubble answer sheet repeats "12. A B C D" down the page — the letters are the
# options to shade, not questions. Whitespace is normalised first because the PDF
# text layer puts each letter on its own line.
_ANSWER_GRID_RE = re.compile(r'\d{1,3}\s*[.)]?\s+A\s+B\s+C\s+D', re.IGNORECASE)

# An answer key lists "44" then the letter, either stacked or on one line, usually
# followed by working. Both forms are anchored to the line start so a question's
# own options ("A. 194mm") can't be mistaken for them.
_ANSWER_KEY_STACKED_RE = re.compile(r'(?m)^[ \t]*(\d{1,3})[ \t]*\n[ \t]*([A-D])[ \t]*$')
_ANSWER_KEY_INLINE_RE = re.compile(r'(?m)^[ \t]*(\d{1,3})[ \t]+([A-D])\b')

# How many rows a page needs before it counts as a grid / key rather than a
# coincidence. Real sheets and keys run to dozens of rows.
_PAGE_ROLE_MIN_ROWS = 5


def detect_page_role(text):
    """Classify a page from its text alone: questions, answer sheet, or key.

    Papers routinely ship with a bubble answer sheet at the front and a worked
    answer key at the back. Neither holds questions, but both used to be sent to
    Claude and imported as nonsense "questions" the teacher had to untick — while
    being paid for. This runs before any AI call, so the pages are never sent.
    """
    if not text:
        return PAGE_ROLE_QUESTIONS

    normalised = re.sub(r'\s+', ' ', text)
    if len(_ANSWER_GRID_RE.findall(normalised)) >= _PAGE_ROLE_MIN_ROWS:
        return PAGE_ROLE_ANSWER_SHEET

    key_rows = (len(_ANSWER_KEY_STACKED_RE.findall(text))
                + len(_ANSWER_KEY_INLINE_RE.findall(text)))
    if key_rows >= _PAGE_ROLE_MIN_ROWS:
        return PAGE_ROLE_ANSWER_KEY

    return PAGE_ROLE_QUESTIONS


def describe_skipped_pages(extracted_data):
    """[{'page', 'label'}] for the preview notice, from a classification result.

    Shared by the homework and worksheet previews so a skipped page is always
    told to the teacher — a page silently missing from an import is exactly the
    kind of blank data this project doesn't ship.
    """
    return [
        {'page': skip.get('page'),
         'label': PAGE_ROLE_LABELS.get(skip.get('reason'), skip.get('reason'))}
        for skip in (extracted_data or {}).get('skipped_pages') or []
    ]


def _split_question_pages(pages):
    """(pages to classify, [(page, role)]) — set answer sheets and keys aside.

    The skipped pages come back whole rather than as bare page numbers: an
    answer key is not junk, it holds the paper's official answers, and
    answer_key.apply_answer_key needs its text.

    Never returns an empty list of pages to classify: if every page looks like
    scaffolding the detector is the thing that's wrong, so classify the lot
    rather than import nothing.
    """
    if not SKIP_NON_QUESTION_PAGES:
        return pages, []

    keep, skipped = [], []
    for page in pages:
        role = detect_page_role(page.get('text', ''))
        if role == PAGE_ROLE_QUESTIONS:
            keep.append(page)
        else:
            skipped.append((page, role))

    if not keep:
        logger.warning(
            'Every page looked like an answer sheet/key — classifying all %s '
            'pages rather than importing nothing.', len(pages),
        )
        return pages, []
    return keep, skipped


class ChunkTooDenseError(ValueError):
    """One classification call hit max_tokens — its pages need splitting.

    Recoverable, and handled by _classify_chunk_adaptive: an answer key or a
    packed question page can generate more structured output than a single call
    can return, which used to fail the entire upload with a message telling the
    teacher to change an environment variable.
    """


def _stream_classification(client, system, tools, content_blocks):
    """One classification request, streamed (a long generation must not trip the
    SDK read timeout). Returns the final Message.

    The model THINKS before it answers. This used to force the tool call
    (``tool_choice: tool``) with thinking disabled — the two are incompatible —
    and a model that cannot reason before it writes miscounts: a stem-and-leaf
    plot with 14 leaves came back as "15 values" (and a median taken as the 8th
    of 15), a sum as "10 + 5 + 2 = 18". Adaptive thinking with ``tool_choice:
    auto`` lets it count and compute first; the closing instruction still tells
    it to answer with the tool, and it does. Should a reply ever come back
    without the tool call, the request is re-issued once the old way — forced
    tool, thinking off — so an upload never fails on that alone.
    ``WORKSHEET_THINKING=0`` skips straight to the forced call.
    """
    model = os.environ.get('WORKSHEET_MODEL', 'claude-opus-5')
    common = dict(
        model=model,
        max_tokens=WORKSHEET_MAX_TOKENS,
        system=system,
        tools=tools,
        messages=[{"role": "user", "content": content_blocks}],
    )
    if os.environ.get('WORKSHEET_THINKING', '1') != '0':
        with client.messages.stream(
            thinking={"type": "adaptive"},
            tool_choice={"type": "auto"},
            **common,
        ) as stream:
            response = stream.get_final_message()
        used_tool = any(getattr(block, 'type', None) == 'tool_use'
                        for block in (response.content or []))
        if used_tool or getattr(response, 'stop_reason', None) in ('refusal', 'max_tokens'):
            return response
        logger.warning(
            'classify chunk: the model answered without calling the tool '
            '(stop_reason=%s); retrying with the tool call forced.',
            getattr(response, 'stop_reason', None))

    # Forced tool call. Thinking must be off for a forced tool_choice; disabled
    # thinking is valid at the default effort ("high") on Opus 5.
    with client.messages.stream(
        thinking={"type": "disabled"},
        tool_choice={"type": "tool", "name": "classify_worksheet_questions"},
        **common,
    ) as stream:
        return stream.get_final_message()


def _classify_page_chunk(client, system, pages, total_page_count, shape_naming=False):
    """Classify one chunk of pages in a single streamed Claude call.

    Each page carries its absolute page_num label, so the returned image_bbox
    page numbers are absolute — chunks can be merged without remapping. Raises
    ValueError if no structured result comes back.

    ``shape_naming`` swaps the user-facing instructions for the name-the-shape
    workflow (one question per individual shape).
    """
    if shape_naming:
        intro = (
            f"These pages are part of a {total_page_count}-page shapes worksheet. "
            "I'm sending each page as a screenshot. Generate one 'name the shape' "
            "question for EACH individual shape using the classify_worksheet_questions tool."
        )
    else:
        intro = (
            f"These pages are part of a {total_page_count}-page homework worksheet. "
            "I'm sending each page as a screenshot. Extract ALL questions on these "
            "pages using the classify_worksheet_questions tool."
        )
    # The model sometimes reports a page's POSITION in this request instead of
    # its number (page 7, sent third in the chunk 5–8, came back as page 3 and
    # its figure was cropped from page 3). Name the real numbers up front; the
    # tool schema below pins page_num to exactly these values as well.
    page_labels = ', '.join(str(p['page_num']) for p in pages)
    intro += (
        f" This request holds page(s) {page_labels} of the document — those are "
        f"their real page numbers, printed in the label under each screenshot. "
        f"Every question's page_num must be one of exactly these numbers, never "
        f"the screenshot's position in this request."
    )
    content_blocks = [{
        "type": "text",
        "text": intro,
    }]
    for page in pages:
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": page['screenshot'],
            },
        })
        content_blocks.append({
            "type": "text",
            "text": (
                f"[Page {page['page_num']} — {page['screenshot_w']}×{page['screenshot_h']} px. "
                f"image_bbox coordinates are in this pixel space. "
                f"Text: {page['text'][:600]}]"
            ),
        })
    if shape_naming:
        closing = (
            "Generate one question per INDIVIDUAL shape on these pages. For each shape: "
            "question_text=\"What is the name of this shape?\", question_type=multiple_choice, "
            "has_image=true, and image_bbox [left, top, right, bottom] tightly around ONLY "
            "that single shape in the page screenshot's pixel coordinates. Provide the correct "
            "shape name plus 3 plausible wrong shape names as answers. "
            "Use the classify_worksheet_questions tool now."
        )
    else:
        closing = (
            "Extract ALL questions on these pages. Set has_image=true ONLY when the question "
            "cannot be answered from its text alone — the figure carries information the wording "
            "does not (e.g. an unlabelled shape to measure, a graph to read off, a diagram whose "
            "values aren't written out). If every value needed is already in the text (e.g. "
            "'area of a circle with diameter 10 cm'), set has_image=false even if a visual sits "
            "nearby. When unsure, prefer has_image=false — a wrongly-attached image is worse than "
            "none. When has_image=true, give image_bbox [left, top, right, bottom] in the page "
            "screenshot's pixel coordinates, cropping ONLY that question's own visual — never "
            "another question's figure, the question text, or the answer options. "
            "Any question whose ANSWER IS A PICTURE — draw a tree or Venn diagram, "
            "illustrate sets on a Venn diagram, represent data in a pie chart or bar graph, "
            "a bare 'sketch this curve', a compass construction, a shaded region — "
            "must be validation_type=\"human_graded\", never "
            "ai_graded: there is no answer surface for a drawing, so the student types "
            "nothing. Number lines, Cartesian plots, long division, prime factorisation, "
            "column sums, a "
            "TABLE TO COMPLETE (question_type table_of_values, with table_spec) and a "
            "SKETCH THAT NAMES THE FEATURES TO SHOW — \"sketch the graph of y = x^2 + x - 2 "
            "showing the vertex, the intercepts and the axis of symmetry\" "
            "(question_type sketch_graph, with sketch_spec) — are the "
            "exception: the app draws those, so keep them auto. "
            "Use the classify_worksheet_questions tool now."
        )
    content_blocks.append({
        "type": "text",
        "text": closing,
    })

    tools = [pin_page_enum(WORKSHEET_CLASSIFICATION_TOOL, ('page_num',),
                           [p['page_num'] for p in pages])]
    response = _stream_classification(client, system, tools, content_blocks)

    result = None
    for block in response.content:
        if block.type == 'tool_use' and block.name == 'classify_worksheet_questions':
            result = block.input
            break
    if not result:
        for block in response.content:
            if block.type == 'text':
                try:
                    result = json.loads(block.text)
                    break
                except json.JSONDecodeError:
                    pass
    if not result:
        stop_reason = getattr(response, 'stop_reason', 'unknown')
        logger.error('classify chunk: no structured result. stop_reason=%s', stop_reason)
        if stop_reason == 'max_tokens':
            # Recoverable: the caller retries these pages in smaller pieces.
            raise ChunkTooDenseError(
                'Pages {}-{} produced more output than one call can return.'.format(
                    pages[0]['page_num'], pages[-1]['page_num'])
            )
        if stop_reason == 'refusal':
            raise ValueError(
                'The AI declined to process this worksheet (content safety). '
                'Please review the source and try again.'
            )
        raise ValueError("AI did not return structured question data. Please try again.")

    result.setdefault('questions', [])
    # Backstop for the page-position mix-up described above: a page_num that is
    # not one of this request's pages cannot be right, and one that is a valid
    # position in the request names the page at that position. Done here, per
    # request, because only this call knows which pages it sent.
    resolve_chunk_pages(result['questions'], [p['page_num'] for p in pages])
    # Safety net: strip any leading question-number/section label the model copied
    # into question_text (e.g. "Question 5 e)", "PART C:", "5)"). It's enumeration,
    # not part of the question.
    for q in result['questions']:
        if isinstance(q, dict):
            raw_text = q.get('question_text', '') or ''
            # Recover the paper's numbering from the label before it is stripped,
            # so an answer key can still be matched when the model omitted
            # source_number.
            if not q.get('source_number'):
                from_label = _label_question_number(raw_text)
                if from_label:
                    q['source_number'] = from_label
            q['question_text'] = _strip_question_label(raw_text)
    result['usage'] = {
        'input_tokens': response.usage.input_tokens,
        'output_tokens': response.usage.output_tokens,
        'total_tokens': response.usage.input_tokens + response.usage.output_tokens,
    }
    return result


def _classify_chunk_adaptive(client, system, pages, total_page_count,
                             shape_naming=False, report=None):
    """Classify a chunk, halving it and retrying if the model runs out of output.

    A chunk that overflows max_tokens returns nothing usable, and one such chunk
    used to fail the whole upload. Splitting costs an extra call for that chunk
    only — each half generates half the output — and the halves merge back
    exactly as separate chunks do, because page numbers are absolute.

    A single page that still overflows cannot be split further, so that raises
    with the page number the teacher needs to act on.
    """
    report = report or (lambda _msg: None)
    try:
        return _classify_page_chunk(client, system, pages, total_page_count,
                                    shape_naming=shape_naming)
    except ChunkTooDenseError:
        if len(pages) == 1:
            raise ValueError(
                f'Page {pages[0]["page_num"]} has more content than the AI can '
                f'return in one go. Please split that page, or remove it and '
                f'upload the rest.'
            ) from None
        mid = len(pages) // 2
        halves = [pages[:mid], pages[mid:]]
        logger.warning(
            'Chunk pages %s-%s too dense; retrying as %s + %s pages',
            pages[0]['page_num'], pages[-1]['page_num'],
            len(halves[0]), len(halves[1]),
        )
        report(f'Page {pages[0]["page_num"]}–{pages[-1]["page_num"]} is dense — '
               f'reading it in smaller pieces…')
        return _merge_chunk_results([
            _classify_chunk_adaptive(client, system, half, total_page_count,
                                     shape_naming=shape_naming, report=report)
            for half in halves
        ])


def _merge_chunk_results(results):
    """Merge per-chunk results: concatenate questions (already page-ordered),
    pick the most common worksheet-level classification, sum token usage."""
    from collections import Counter

    def pick(field, default=None):
        vals = [r.get(field) for r in results if r.get(field)]
        return Counter(vals).most_common(1)[0][0] if vals else default

    questions = []
    for r in results:
        questions.extend(r.get('questions', []))
    input_t = sum(r.get('usage', {}).get('input_tokens', 0) for r in results)
    output_t = sum(r.get('usage', {}).get('output_tokens', 0) for r in results)
    return {
        'year_level': pick('year_level'),
        'subject': pick('subject', 'Mathematics'),
        'strand': pick('strand', ''),
        'topic': pick('topic', ''),
        'questions': questions,
        'usage': {
            'input_tokens': input_t,
            'output_tokens': output_t,
            'total_tokens': input_t + output_t,
        },
    }


def classify_worksheet_questions(extracted_pages, existing_topics, existing_levels,
                                 shape_naming=False, progress=None):
    """Send page screenshots to Claude and get structured questions with image bboxes.

    Multi-page worksheets are split into page-chunks classified *concurrently*
    (CPP: speed). Each chunk generates a fraction of the output and they run at
    the same time, so wall-clock ≈ the slowest chunk rather than the sum. Single
    short worksheets fall through to one call. Results are merged in page order.

    ``shape_naming`` switches to the name-the-shape prompt: one auto-generated
    "What is the name of this shape?" question per individual shape.

    Pages that carry no questions — a bubble answer sheet, a worked answer key —
    are detected from their text and never sent, so they cost nothing and can't
    be imported as junk questions. What was skipped is reported back on the
    result as ``skipped_pages`` rather than dropped silently.

    ``progress`` is an optional ``callable(message)`` invoked as each chunk lands,
    so a caller can surface live progress (and prove the job is still alive).
    """
    report = progress or (lambda _msg: None)
    client = _get_anthropic_client()
    system = _build_system_prompt(existing_topics, existing_levels, shape_naming=shape_naming)

    with_screenshots = [p for p in extracted_pages['pages'] if p.get('screenshot')]
    pages = with_screenshots[:WORKSHEET_PAGE_CAP]
    if not pages:
        raise ValueError("No page screenshots to classify.")
    # Page numbers in the prompt and in every returned bbox are absolute, so tell
    # Claude the PDF's real length rather than how many pages this run selected.
    total = extracted_pages.get('total_page_count') or extracted_pages['page_count']

    # The cap used to drop the tail without a word. Carry the dropped pages into
    # skipped_pages so the preview notice names them.
    over_cap = [(p, PAGE_ROLE_OVER_CAP) for p in with_screenshots[WORKSHEET_PAGE_CAP:]]
    if over_cap:
        logger.warning(
            'Page cap: only the first %s of %s selected pages are being '
            'classified; dropped %s.',
            WORKSHEET_PAGE_CAP, len(with_screenshots),
            ', '.join(f'p{page["page_num"]}' for page, _role in over_cap),
        )
        report(
            f'Only the first {WORKSHEET_PAGE_CAP} pages can be read in one '
            f'upload — {len(over_cap)} page(s) will be left out…'
        )

    pages, skipped = _split_question_pages(pages)
    if skipped:
        logger.info(
            'Skipping %s non-question page(s): %s',
            len(skipped),
            ', '.join(f'p{page["page_num"]} ({role})' for page, role in skipped),
        )
        report(f'Skipping {len(skipped)} page(s) with no questions…')

    # Joined only now, after the "no questions on them" messages above: an
    # over-cap page may be full of questions — it just doesn't fit this upload.
    skipped += over_cap

    chunks = [pages[i:i + WORKSHEET_CHUNK_SIZE]
              for i in range(0, len(pages), WORKSHEET_CHUNK_SIZE)]

    # One chunk → no thread-pool overhead.
    if len(chunks) == 1:
        report(f'Reading {len(pages)} page(s)…')
        result = _classify_chunk_adaptive(
            client, system, chunks[0], total, shape_naming=shape_naming, report=report)
    else:
        report(f'Reading {len(pages)} pages in {len(chunks)} sections…')
        ordered = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=min(WORKSHEET_MAX_PARALLEL, len(chunks))) as pool:
            futures = {
                pool.submit(_classify_chunk_adaptive, client, system, chunk, total,
                            shape_naming=shape_naming, report=report): idx
                for idx, chunk in enumerate(chunks)
            }
            for done, fut in enumerate(as_completed(futures), start=1):
                ordered[futures[fut]] = fut.result()  # re-raises any chunk failure
                report(f'Read {done} of {len(chunks)} sections…')

        logger.info('Classified %s pages across %s parallel chunks', len(pages), len(chunks))
        result = _merge_chunk_results(ordered)

    result['skipped_pages'] = [
        {'page': page['page_num'], 'reason': role} for page, role in skipped
    ]

    # The paper's own answer key beats the AI's attempt at answering, so apply it
    # to the questions it names (see worksheets/answer_key.py).
    key_pages = [page for page, role in skipped if role == PAGE_ROLE_ANSWER_KEY]
    if key_pages and result.get('questions'):
        report('Applying the paper’s answer key…')
        from .answer_key import apply_answer_key
        result['answer_key'] = apply_answer_key(result['questions'], key_pages)

    return result


# ---------------------------------------------------------------------------
# Image rendering: PyMuPDF clip — render region directly from PDF vectors
# ---------------------------------------------------------------------------

def _bleeding_text_blocks(fitz_page, clip_rect):
    """Text blocks that START above *clip_rect* but hang DOWN into it.

    Only these can dirty the crop: a block that starts above the clip and ends
    above it too is outside the rendered region and invisible either way, so
    redacting it would be pure cost.

    *clip_rect* is in displayed coordinates (it came from the screenshot), so
    the comparison is made on each block's displayed rectangle; the returned
    rects are the RAW (unrotated) ones, because that is the space a redaction
    annotation is placed in. Identical on an unrotated page.
    """
    import fitz

    bleeding = []
    # (x0, y0, x1, y1, text, block_no, block_type)
    for b in fitz_page.get_text('blocks'):
        raw = fitz.Rect(b[0], b[1], b[2], b[3])
        shown = displayed_rect(fitz_page, raw)
        if shown.y0 < clip_rect.y0 < shown.y1 and shown.intersects(clip_rect):
            bleeding.append(raw)
    return bleeding


def _capped_render_dpi(clip_rect, dpi=None):
    """DPI to render *clip_rect* at, lowered so the crop stays under IMAGE_MAX_PX.

    Small figures — the common case — keep the full IMAGE_RENDER_DPI; only a
    large region is scaled back, and only as far as the cap requires.
    """
    target = dpi or IMAGE_RENDER_DPI
    longest_pt = max(clip_rect.width, clip_rect.height)
    if longest_pt <= 0:
        return target
    return max(72, min(target, int(IMAGE_MAX_PX * 72 / longest_pt)))


def _render_clean_diagram(fitz_page, clip_rect, dpi=150):
    """
    Render *clip_rect* from *fitz_page* with any text block that starts ABOVE
    the clip region and hangs into it whited out.

    This removes page headers / section titles (e.g. "Questions") that bleed
    into the top of the crop while keeping the diagram's own angle labels,
    tick marks and other text that are INSIDE the clip region.

    Strategy:
      1. Find the text blocks that straddle clip_rect's top edge — headers
         sitting above the diagram whose bottom half hangs into it.
      2. If there are none (the common case), render the page directly: copying
         the page and rewriting its content stream to redact text outside the
         rendered region cannot change a pixel of the output, and it roughly
         doubles the cost of every question image.
      3. Otherwise apply white redaction rectangles on a scratch copy of the
         page and render that, clipped to clip_rect.

    Returns a fitz.Pixmap.
    """
    import fitz

    bleeding = _bleeding_text_blocks(fitz_page, clip_rect)
    if not bleeding:
        return fitz_page.get_pixmap(clip=clip_rect, dpi=dpi)

    # Work on a scratch document so we never mutate the original.
    scratch_doc = fitz.open()
    scratch_doc.insert_pdf(fitz_page.parent, from_page=fitz_page.number, to_page=fitz_page.number)
    scratch_page = scratch_doc[0]

    for block_rect in bleeding:
        scratch_page.add_redact_annot(block_rect, fill=(1, 1, 1))

    # Redact TEXT ONLY. The defaults also rewrite the pixels of every image the
    # redaction rect touches and delete line art under it — neither is wanted
    # here (we are hiding a header, not censoring the figure), and the image
    # path aborts the whole process on some real worksheets: PyMuPDF 1.24.3
    # corrupts the heap in apply_redactions(images=PDF_REDACT_IMAGE_PIXELS) on a
    # page whose redaction rect overlaps certain embedded images ("malloc():
    # unaligned tcache chunk detected", SIGABRT). In the RQ worker that kills the
    # work-horse outright, so the upload session is never marked failed and the
    # teacher's page polls a dead job forever.
    scratch_page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
    )
    pix = scratch_page.get_pixmap(clip=clip_rect, dpi=dpi)
    scratch_doc.close()
    return pix


def _tight_drawings_rect(fitz_page, search_rect, min_area_pts=50):
    """
    Return the tight bounding rect of the vector drawing elements that BELONG to
    *search_rect* (in PDF points) — i.e. whose centre lies inside it.

    Vector drawings (lines, curves, filled shapes) are the diagram itself; text
    is never a drawing, so headers / labels are excluded automatically.

    Two safeguards keep multi-figure pages (a grid/row of diagrams) from merging:
      * the centre-inside test ignores a NEIGHBOURING figure whose edge merely
        pokes into the padded search box, and
      * the result is clamped to *search_rect*, so the crop can never extend
        beyond Claude's region onto an adjacent figure.

    Returns a fitz.Rect, or None if no qualifying drawings were found.
    """
    import fitz

    # Use clustered drawings, not raw paths: PyMuPDF groups the strokes of one
    # figure into a single rect. Raw get_drawings() rects for axis-aligned lines
    # (number lines, grids, geometry) are zero-area, so an area filter on them
    # would discard line-art figures entirely. cluster_drawings() bounds them
    # correctly.
    try:
        clusters = fitz_page.cluster_drawings()
    except Exception:
        return None
    if not clusters:
        return None

    page_rect = fitz_page.rect
    page_area = page_rect.width * page_rect.height

    picked = []
    for r in clusters:
        # Clusters are reported in unrotated coordinates; search_rect came from
        # the screenshot, so compare in displayed space (a no-op unless rotated).
        r = displayed_rect(fitz_page, r)
        if r.is_empty or r.is_infinite:
            continue
        # Skip page-border / full-page decoration and tiny specks.
        if page_area > 0 and (r.width * r.height) / page_area > 0.80:
            continue
        if r.width * r.height < min_area_pts:
            continue
        # Skip thin horizontal rules — answer-blank underlines and section
        # separators are vector "drawings" too, and a lone one would otherwise
        # make a self-contained text question render its surrounding text as a
        # spurious figure. A real line-art figure (number line, geometry) has
        # tick marks / strokes giving it height, so this only drops bare rules.
        if r.height < 2.5 and r.width > 20:
            continue
        # Belongs to this region only if its centre is inside — excludes a
        # neighbouring figure whose edge pokes into the padded search box.
        cx, cy = (r.x0 + r.x1) / 2.0, (r.y0 + r.y1) / 2.0
        if not (search_rect.x0 <= cx <= search_rect.x1 and
                search_rect.y0 <= cy <= search_rect.y1):
            continue
        picked.append(r)

    if not picked:
        return None

    margin = 6  # pts — small whitespace around the diagram
    tight = fitz.Rect(
        min(r.x0 for r in picked) - margin,
        min(r.y0 for r in picked) - margin,
        max(r.x1 for r in picked) + margin,
        max(r.y1 for r in picked) + margin,
    )
    # Never extend beyond the search region — prevents the crop from bleeding
    # onto adjacent figures on a multi-figure page.
    tight.intersect(search_rect)
    return tight if tight.is_valid and tight.width > 10 and tight.height > 10 else None


def _smart_diagram_rect(fitz_page, search_rect, min_area_pts=50, gap_tol=18):
    """
    Decide the crop rect for a diagram that lives inside *search_rect* (PDF points).

    Claude's bbox is only a rough region — it routinely includes the question
    sentence sitting below a diagram. This snaps the crop to the *actual* figure:

      1. Find the tight bounds of the vector drawings (the diagram itself).
      2. Grow that core to absorb tightly-attached *label* text — short, narrow
         blocks (e.g. the "A B C D" under each arrow) within ``gap_tol`` points of
         the diagram — while leaving wide running text (the question sentence)
         outside. Width is the key discriminator: a label is short, a sentence
         spans the page.

    Returns a ``fitz.Rect``, or ``None`` when the page has no vector drawings
    (a raster/scanned PDF) so the caller can fall back to Claude's bbox.
    """
    import fitz

    core = _tight_drawings_rect(fitz_page, search_rect, min_area_pts=min_area_pts)
    if core is None:
        return None

    page_rect = fitz_page.rect
    max_label_w = 0.5 * page_rect.width  # wider than this ⇒ running text, not a label

    grown = fitz.Rect(core)
    for b in fitz_page.get_text('blocks'):
        text = (b[4] or '').strip() if len(b) > 4 else ''
        if not text:
            continue
        br = displayed_rect(fitz_page, fitz.Rect(b[0], b[1], b[2], b[3]))
        if br.width > max_label_w:
            continue                 # running text — never an attached label
        # Gap from the diagram core (measured against the core, NOT the growing
        # rect, so one absorbed label can't chain the crop down to the sentence).
        # Labels above the core count too — e.g. a "North"/title/axis-max sitting
        # just above the drawing. They must be narrow (width filter) and close
        # (gap_tol); growing the clip up to include them also stops
        # _render_clean_diagram from redacting them. Wide section headers are
        # excluded by the width filter and stay out (redacted as before).
        dx = max(core.x0 - br.x1, br.x0 - core.x1, 0.0)
        dy = max(core.y0 - br.y1, br.y0 - core.y1, 0.0)
        if dx <= gap_tol and dy <= gap_tol:
            grown.include_rect(br)   # absorb the attached label

    margin = 4
    grown = fitz.Rect(grown.x0 - margin, grown.y0 - margin,
                      grown.x1 + margin, grown.y1 + margin)
    # Clamp to the search region so absorbing a label can't pull the crop onto a
    # neighbouring figure on a multi-figure page.
    grown.intersect(search_rect)
    return grown if grown.is_valid and grown.width > 10 and grown.height > 10 else None


def _region_has_raster_image(fitz_page, search_rect, min_overlap_frac=0.12):
    """
    Return True if an embedded raster image meaningfully overlaps *search_rect*.

    Used to tell a genuine scanned/photo figure apart from a region that is just
    text. On a born-digital PDF a "diagram" is vector drawings; on a scanned PDF
    it is an embedded image. If a region has neither, Claude has flagged a figure
    that isn't there and we should drop it rather than render text as an image.

    ``min_overlap_frac`` is the fraction of *search_rect* the image must cover to
    count — guards against an incidental clip-art or logo elsewhere on the page.
    """
    import fitz

    search_area = abs(search_rect.get_area())
    if search_area <= 0:
        return False

    try:
        images = fitz_page.get_images(full=True)
    except Exception:
        return False

    for img in images:
        xref = img[0]
        try:
            rects = fitz_page.get_image_rects(xref)
        except Exception:
            continue
        for r in rects:
            # Image placements are reported unrotated; search_rect is displayed.
            inter = displayed_rect(fitz_page, r)
            inter.intersect(search_rect)
            if inter.is_valid and abs(inter.get_area()) >= min_overlap_frac * search_area:
                return True
    return False


def _region_has_drawing(fitz_page, search_rect, min_area_pts=50):
    """
    Return True if a (non page-border) vector figure cluster overlaps *search_rect*.

    Used as a fallback signal: if the crop couldn't be snapped tightly but a real
    drawing overlaps the region, render Claude's bbox as-is rather than dropping a
    genuine figure as "spurious".
    """
    import fitz

    try:
        clusters = fitz_page.cluster_drawings()
    except Exception:
        return False
    page_rect = fitz_page.rect
    page_area = page_rect.width * page_rect.height
    for r in clusters:
        r = displayed_rect(fitz_page, r)
        if r.is_empty or r.is_infinite:
            continue
        if page_area > 0 and (r.width * r.height) / page_area > 0.80:
            continue
        if r.width * r.height < min_area_pts:
            continue
        if r.intersects(search_rect):
            return True
    return False


def _content_bounds(samples, w, h, n):
    """(top, bottom, left, right) of the non-blank content in a pixmap buffer.

    A pixel is blank when its average RGB value is >= 248 (almost white); a
    row/column is blank when every pixel in it is. Returns None when the whole
    buffer is blank (nothing to trim to).

    Vectorised to bound the worst case. The scalar scan walked the buffer a
    pixel at a time in Python and stopped at the first non-blank row, so it was
    free on a tight crop but took ~0.9 s on a 6 MP crop with wide white margins
    (and ~0.5 s on an all-white one) — per question image, that made a big
    worksheet's render phase wildly unpredictable. This costs ~0.15 s flat on
    the same input.
    """
    import numpy as np

    arr = np.frombuffer(samples, dtype=np.uint8).reshape(h, w, n)[:, :, :3]
    # Same test as before: a pixel is blank when (r + g + b) // 3 >= 248.
    blank_px = (arr.sum(axis=2, dtype=np.uint16) // 3) >= 248
    content_rows = np.flatnonzero(~blank_px.all(axis=1))
    content_cols = np.flatnonzero(~blank_px.all(axis=0))
    if not content_rows.size or not content_cols.size:
        return None
    return (int(content_rows[0]), int(content_rows[-1]),
            int(content_cols[0]), int(content_cols[-1]))


def _trim_whitespace(pix):
    """
    Remove rows/columns of near-white pixels from all four edges of a
    fitz.Pixmap.  Returns a new Pixmap (or the original if nothing to trim).

    Threshold: a row/column is considered blank if every pixel's average
    RGB value is >= 248 (almost white).
    """
    samples = pix.samples  # raw bytes: w * h * n (n=3 for RGB)
    w, h, n = pix.width, pix.height, pix.n

    if n < 3:
        return pix  # greyscale or alpha-only — skip

    bounds = _content_bounds(samples, w, h, n)
    if bounds is None:
        return pix  # nothing but whitespace — leave the crop as it is
    top, bottom, left, right = bounds

    if top == 0 and bottom == h - 1 and left == 0 and right == w - 1:
        return pix  # nothing to trim

    # Re-render only the trimmed region via a sub-rect if possible,
    # otherwise fall back to Pillow crop.
    try:
        from PIL import Image
        import io
        # pix.n may include an alpha channel (RGBA, n==4) — e.g. when the
        # diagram was rendered with header redaction. Build the image with the
        # real channel count, then normalise to RGB. Hardcoding 'RGB' on a
        # 4-channel pixmap mis-aligns the buffer and makes img.save() raise
        # "tile cannot extend outside image", dropping the whole diagram. For
        # anything other than RGB/RGBA (e.g. CMYK n==5) skip the trim rather
        # than mis-read the buffer.
        mode = {3: 'RGB', 4: 'RGBA'}.get(n)
        if mode is None:
            return pix
        img = Image.frombytes(mode, (w, h), bytes(samples))
        img = img.crop((left, top, right + 1, bottom + 1)).convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()  # return raw bytes when Pillow is available
    except ImportError:
        return pix  # Pillow not installed — return original
    except Exception:
        # Any other Pillow failure (degenerate crop, odd colorspace) must never
        # cost us the image — fall back to the untrimmed pixmap.
        logger.warning('Q image: whitespace trim failed; using untrimmed image',
                       exc_info=True)
        return pix


def _flag_missing_figure(q, reason):
    """Mark a question whose figure could not be cropped so the teacher sees why.

    ``has_image`` is cleared (there is no image to show) and the question is
    routed to review with the reason, rather than arriving looking like a
    text-only question. The preview's crop tool lets the teacher add the figure.
    """
    q['has_image'] = False
    q['needs_review'] = True
    q.setdefault('review_reason', reason)


def render_question_images(doc, extracted_pages, classified_result, progress=None):
    """
    For every question where has_image=True:
      1. Convert Claude's rough bbox from screenshot pixel space → PDF points.
      2. Use page.get_drawings() to find the tight bounds of actual vector
         elements inside that region — this excludes text (headers, labels)
         which are never drawings.  Falls back to Claude's bbox for raster PDFs.
      3. Render the clean rect at high DPI directly from PDF vectors.
      4. Trim residual whitespace from all edges.
      5. Store as PNG base64.

    ``progress`` is an optional ``callable(message)`` invoked per rendered image,
    so a caller can surface live progress during this (single-threaded) phase.

    Returns:
        (classified_result, extracted_images dict)
    """
    import fitz

    report = progress or (lambda _msg: None)
    pages_by_num = {p['page_num']: p for p in extracted_pages['pages']}
    extracted_images = {}

    questions = classified_result.get('questions', [])
    with_images = sum(1 for q in questions if q.get('has_image'))
    rendered = 0
    for idx, q in enumerate(questions):
        q.setdefault('image_ref', None)

        if not q.get('has_image'):
            continue

        rendered += 1
        report(f'Preparing question images ({rendered} of {with_images})…')

        bbox = q.get('image_bbox')
        page_num = q.get('page_num')

        if not bbox or len(bbox) != 4:
            logger.warning(f'Q{idx+1}: has_image=True but no valid image_bbox — skipping')
            _flag_missing_figure(
                q, 'The AI said this question has a figure but gave no box for it; '
                   'use "Crop image from page" to add it.')
            continue

        # No default page. This used to fall back to page 1, which cropped the
        # figure box from the cover sheet when the model left the page out —
        # a wrong image with nothing to say it was wrong. An unknown page is now
        # surfaced on the question instead.
        page_data = pages_by_num.get(page_num) if page_num is not None else None
        if not page_data:
            logger.warning(f'Q{idx+1}: page {page_num!r} not found — skipping')
            _flag_missing_figure(
                q, 'The AI did not say which page this question\'s figure is on, '
                   'so no image was cropped; use "Crop image from page" to add it.')
            continue

        try:
            # Screenshot pixel dimensions
            ss_w = page_data['screenshot_w']
            ss_h = page_data['screenshot_h']

            # PDF page dimensions in points
            pdf_w = page_data['pdf_w']
            pdf_h = page_data['pdf_h']

            # Scale factors: screenshot pixel → PDF points
            scale_x = pdf_w / ss_w
            scale_y = pdf_h / ss_h

            # Claude's rough bbox in screenshot pixel space
            px0, py0, px1, py1 = [float(v) for v in bbox]

            # Add side/bottom padding only — never expand the top edge (risks
            # pulling in section headers that sit above the diagram).
            side_pad_px = 12
            bottom_pad_px = 12
            px0 = max(0, px0 - side_pad_px)
            px1 = min(ss_w, px1 + side_pad_px)
            py1 = min(ss_h, py1 + bottom_pad_px)

            # Convert to PDF points and clamp
            pt0 = max(0.0, px0 * scale_x)
            pt1 = max(0.0, py0 * scale_y)
            pt2 = min(pdf_w, px1 * scale_x)
            pt3 = min(pdf_h, py1 * scale_y)

            if pt2 <= pt0 or pt3 <= pt1:
                logger.warning(f'Q{idx+1}: degenerate clip rect — skipping')
                continue

            fitz_page = doc[page_num - 1]
            # Claude's bbox is only a rough search region. Snap the crop to the
            # actual vector drawing plus its attached labels (e.g. A/B/C/D) so
            # stray question text below the diagram is excluded.
            search_rect = fitz.Rect(pt0, pt1, pt2, pt3)
            clip_rect = _smart_diagram_rect(fitz_page, search_rect)
            render_dpi = None
            if clip_rect is None:
                # Couldn't snap to a tight figure. Render Claude's bbox as-is when
                # there's a real figure here — an embedded raster (scanned/photo
                # PDF) or a vector cluster that overlaps the region. Only when
                # there is neither do we treat the bbox as spurious (it points at
                # plain text) and drop it — the "totally irrelevant image" case.
                if (_region_has_raster_image(fitz_page, search_rect)
                        or _region_has_drawing(fitz_page, search_rect)):
                    clip_rect = fitz.Rect(pt0, pt1, pt2, min(pdf_h, pt3 + 20))
                    # A region that is only a scan gains nothing from print DPI:
                    # rendering a 180-DPI photocopy at 300 DPI just upsamples
                    # it into a multi-megabyte PNG. Stop at the scan's own
                    # resolution (vector regions keep the full render DPI).
                    if not _region_has_drawing(fitz_page, search_rect):
                        native = raster_native_dpi(fitz_page, clip_rect)
                        if native:
                            render_dpi = max(72, min(IMAGE_RENDER_DPI, int(native)))
                else:
                    logger.info(
                        f'Q{idx+1}: has_image=True but no figure (vector or raster) '
                        f'in bbox — dropping spurious image'
                    )
                    q['has_image'] = False
                    continue

            # Render at print-quality DPI (capped in pixels for big regions) with
            # any header text bleeding into the crop redacted (whited out). This
            # removes "Questions" / section headings while keeping angle labels
            # and other text inside the diagram itself.
            pix = _render_clean_diagram(
                fitz_page, clip_rect, dpi=_capped_render_dpi(clip_rect, dpi=render_dpi))

            # Trim residual whitespace
            trimmed = _trim_whitespace(pix)
            if isinstance(trimmed, bytes):
                img_bytes = trimmed   # Pillow-trimmed PNG bytes
            else:
                img_bytes = trimmed.tobytes('png')  # original or untrimmed Pixmap

            img_b64 = base64.b64encode(img_bytes).decode('utf-8')

            ref = f'worksheet_img_q{idx+1}_p{page_num}.png'
            extracted_images[ref] = img_b64
            q['image_ref'] = ref
            # Crop provenance for the "Adjust image" editor: the final region as
            # fractions of the page, so the crop box can be pre-filled and the
            # teacher can drag it to recover cut-off detail or exclude junk.
            q['image_page'] = page_num
            q['image_bbox_frac'] = [
                round(clip_rect.x0 / pdf_w, 4), round(clip_rect.y0 / pdf_h, 4),
                round(clip_rect.x1 / pdf_w, 4), round(clip_rect.y1 / pdf_h, 4),
            ]

            logger.info(
                f'Q{idx+1}: rendered from PDF — page {page_num}, '
                f'clip=({clip_rect.x0:.1f},{clip_rect.y0:.1f},'
                f'{clip_rect.x1:.1f},{clip_rect.y1:.1f}) pts @ {IMAGE_RENDER_DPI}dpi, '
                f'output={pix.width}×{pix.height}px → {ref}'
            )

        except Exception as e:
            logger.exception(f'Q{idx+1}: image render failed — {e}')

    classified_result['questions'] = questions
    return classified_result, extracted_images


# ---------------------------------------------------------------------------
# Manual re-crop support — powers the teacher "Adjust image" tool in the
# homework / worksheet / ai_import review editors. Pipeline-agnostic: renders
# straight from the PDF page, so it works for scanned (raster) pages just as
# well as born-digital (vector) ones.
# ---------------------------------------------------------------------------

def pdf_bytes_from(pdf_source):
    """Read raw PDF bytes from a Django FieldFile, a path, or bytes."""
    if isinstance(pdf_source, (bytes, bytearray)):
        return bytes(pdf_source)
    if hasattr(pdf_source, 'read'):          # Django FieldFile / file-like
        try:
            pdf_source.open('rb')
        except Exception:
            pass
        try:
            return pdf_source.read()
        finally:
            try:
                pdf_source.close()
            except Exception:
                pass
    with open(pdf_source, 'rb') as fh:       # filesystem path
        return fh.read()


def render_pdf_page_png(pdf_bytes, page_index, dpi=150):
    """Render a full PDF page as PNG bytes for the Adjust-image modal.

    Returns ``(png_bytes, page_w_pt, page_h_pt)``. ``page_index`` is 0-based.
    The point dimensions let the client map a drag box (in displayed pixels)
    back to page fractions independent of this preview DPI.
    """
    import fitz

    doc = fitz.open(stream=bytes(pdf_bytes), filetype='pdf')
    try:
        page = doc[page_index]
        pw, ph = page.rect.width, page.rect.height
        return page.get_pixmap(dpi=dpi).tobytes('png'), pw, ph
    finally:
        doc.close()


def recrop_pdf_region(pdf_bytes, page_index, frac_box, dpi=None, snap=False):
    """Render a sub-region of a PDF page as PNG bytes for a manual re-crop.

    ``frac_box`` is ``[x0, y0, x1, y1]`` as fractions (0..1) of page width/height
    — DPI-independent, so the client can send exactly what it drew. WYSIWYG:
    renders precisely the boxed region (no header redaction) at print DPI, so
    the teacher gets what they see. ``snap=True`` first tightens to the vector
    drawing via :func:`_smart_diagram_rect` (opt-in; off by default because the
    teacher's box is authoritative). Raises ValueError on a degenerate box.
    """
    import fitz

    dpi = dpi or IMAGE_RENDER_DPI
    x0, y0, x1, y1 = (float(v) for v in frac_box)
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))

    doc = fitz.open(stream=bytes(pdf_bytes), filetype='pdf')
    try:
        page = doc[page_index]
        pw, ph = page.rect.width, page.rect.height
        clip = fitz.Rect(x0 * pw, y0 * ph, x1 * pw, y1 * ph)
        if clip.width < 2 or clip.height < 2:
            raise ValueError('crop region too small')
        if snap:
            tight = _smart_diagram_rect(page, clip)
            if tight is not None:
                clip = tight
        return page.get_pixmap(clip=clip, dpi=dpi).tobytes('png')
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def extract_and_classify_worksheet(pdf_file, existing_topics, existing_levels,
                                   shape_naming=False, progress=None,
                                   page_selection=None):
    """
    Full pipeline: PDF → page screenshots → AI classify → render image regions.

    Keeps the fitz.Document open throughout so we can render clips from
    the original PDF vectors rather than cropping JPEG screenshots.

    ``shape_naming`` enables name-the-shape mode: pages are rendered at a higher
    DPI and Claude emits one "name this shape" question per individual shape.

    ``page_selection`` is the teacher's print-dialog style page spec (``"2-7, 9"``;
    blank/``None`` means every page — see ``worksheets/page_selection.py``). Only
    the selected pages are rendered and classified, so skipping a cover sheet or a
    marking scheme costs nothing and can't be imported as junk questions. What was
    left out is recorded on ``result['page_selection']`` rather than dropped
    silently. Raises ``PageSelectionError`` if the spec doesn't fit this PDF.

    ``progress`` is an optional ``callable(message)`` called as each stage lands.
    Callers use it to show the teacher what's happening and to record a heartbeat
    proving the job is still alive.

    Returns:
        {
            'result': { year_level, subject, strand, topic, questions[], usage,
                        page_selection,
                        verification },   # second-opinion summary, or None
            'extracted_images': { ref: base64_png_str, ... },
            'page_count': int,   # pages actually extracted (what gets billed)
        }
    """
    import fitz

    from .page_selection import parse_page_selection, selection_summary

    report = progress or (lambda _msg: None)
    pdf_bytes = pdf_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')

    try:
        selected = parse_page_selection(page_selection, len(doc))
        summary = selection_summary(page_selection, selected, len(doc))

        # Step 1: render pages + collect text (higher DPI in shape mode for tighter crops)
        if summary['excluded']:
            report(
                f'Opening the PDF — reading page(s) {summary["selected_label"]} '
                f'of {len(doc)}…'
            )
        else:
            report(f'Opening the PDF ({len(doc)} page(s))…')
        extracted_pages = extract_worksheet_pages(
            doc, screenshot_dpi=SHAPE_NAMING_DPI if shape_naming else None,
            selected_pages=selected,
        )

        # Step 2: AI classification (gets question text, type, answers, image bboxes)
        result = classify_worksheet_questions(
            extracted_pages, existing_topics, existing_levels, shape_naming=shape_naming,
            progress=report,
        )
        result['page_selection'] = summary

        # Questions whose answer is a DRAWING the app can't take — "draw a tree
        # diagram", "shade the region". The model is told to mark these
        # human_graded (rule 18), but a missed one would reach students as
        # ai_graded and be marked on prose they were never asked to write, so
        # re-route deterministically. Runs before the include default below so a
        # re-routed question also arrives unticked.
        routed = route_constructions_to_teacher(result.get('questions'))
        result[CONSTRUCTIONS_ROUTED_KEY] = True
        if routed:
            logger.info(
                '%s question(s) re-routed to human_graded: they ask the student '
                'to draw something the app has no answer surface for.', routed)

        # An explanation that contradicts itself — a count that disagrees with
        # the list it wrote, an ordinal that disagrees with the list, a sum that
        # does not add up — is a wrong answer announcing itself. Flag it for the
        # teacher now; no model, image or token needed.
        contradicted = flag_explanation_problems(result.get('questions'))
        if contradicted:
            logger.info(
                '%s question(s) flagged for review: the explanation contradicts '
                'itself (miscount or arithmetic slip).', contradicted)

        for q in result.get('questions', []):
            # Teacher-graded (human_graded) questions are deselected by default so
            # the teacher opts in rather than out; everything else is included.
            q.setdefault('include', q.get('validation_type') != 'human_graded')

        # Step 3: render image regions from PDF vectors (not screenshot crops)
        result, extracted_images = render_question_images(
            doc, extracted_pages, result, progress=report,
        )

        # Step 3b: turn each "colour all the triangles" crop into a traced
        # shape_spec. Runs here because it needs the finished crops, and here
        # rather than in each caller because worksheets AND homework both come
        # through this function. A scene that will not trace is routed to the
        # teacher by the tracer itself rather than imported unanswerable.
        traced, untraceable = trace_shape_select_scenes(
            result.get('questions'), extracted_images)
        if traced or untraceable:
            logger.info(
                'shape_select: %s scene(s) traced, %s routed to the teacher.',
                traced, untraceable)

        # Step 4: independent second opinion (CPP-384).
        #
        # One model is not perfect, and a wrong answer that reaches the question
        # bank costs far more to find later than a second opinion costs now —
        # CPP-377 was 14 broken questions on one topic, found only when a Year 7
        # student complained. This pass re-examines each question with an
        # independent model and flags disagreements needs_review for the teacher;
        # it never edits an answer.
        #
        # Runs here rather than in each caller because worksheets AND homework
        # both come through this function (worksheets/tasks.py,
        # homework/tasks.py), so one insertion point covers both paths.
        #
        # Best-effort and self-gating, exactly as in ai_import: a no-op without
        # OPENAI_API_KEY, and a failure never sinks an upload that already
        # classified successfully.
        report('Double-checking the questions with a second model…')
        result['verification'] = _second_opinion(result, extracted_pages)

    finally:
        doc.close()

    return {
        'result': result,
        'extracted_images': extracted_images,
        'page_count': extracted_pages['page_count'],
    }


def _second_opinion(result, extracted_pages):
    """Run the independent verifier over ``result['questions']`` in place.

    Returns the verifier's summary dict (including its token usage, so the
    caller can bill it to the right provider and source), or None when the
    verifier is disabled or there was nothing to check.

    Deliberately swallows every failure: this is a quality aid, not a gate. An
    upload that classified successfully must not be lost because a second
    opinion was unavailable.
    """
    try:
        from ai_import.verification import flag_visual_comparisons, verify_answers

        questions = result.get('questions') or []
        if not questions:
            return None

        # Deterministic guard first, so the obvious cases are flagged without
        # paying for an API call — and so the paid pass skips them.
        flag_visual_comparisons(questions)

        # Same {page_num: base64_jpeg} shape ai_import passes. Questions
        # carrying a figure resolve to their page and are checked WITH the
        # image; the rest fall back to a text-only check.
        page_images = {
            page['page_num']: page['screenshot']
            for page in extracted_pages.get('pages', [])
            if page.get('page_num') is not None and page.get('screenshot')
        }
        return verify_answers(questions, page_images=page_images)
    except Exception:
        logger.exception(
            'Second-opinion verification failed; continuing with the '
            'unverified extraction')
        return None
