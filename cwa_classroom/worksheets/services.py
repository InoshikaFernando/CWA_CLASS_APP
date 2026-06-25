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
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

logger = logging.getLogger(__name__)

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
WORKSHEET_MAX_PARALLEL = int(os.environ.get('WORKSHEET_MAX_PARALLEL', '4'))  # concurrent requests
WORKSHEET_PAGE_CAP = int(os.environ.get('WORKSHEET_PAGE_CAP', '40'))      # hard ceiling on pages processed


# ---------------------------------------------------------------------------
# PDF page extraction (worksheet-specific — tracks screenshot dimensions)
# ---------------------------------------------------------------------------

def extract_worksheet_pages(doc, screenshot_dpi=None):
    """
    Render each page of an open fitz.Document.

    ``screenshot_dpi`` overrides the page-screenshot DPI (defaults to
    SCREENSHOT_DPI). Name-the-shape mode passes a higher value so Claude can
    place tighter bounding boxes around small individual shapes.

    Returns:
        {
            'pages': [
                {
                    'page_num': int,          # 1-based
                    'text': str,
                    'screenshot': str,        # base64 JPEG of full page
                    'screenshot_w': int,      # pixel width  of screenshot
                    'screenshot_h': int,      # pixel height of screenshot
                    'pdf_w': float,           # page width  in PDF points
                    'pdf_h': float,           # page height in PDF points
                }
            ],
            'page_count': int,
        }
    """
    dpi = screenshot_dpi or SCREENSHOT_DPI
    pages = []
    for page_num in range(len(doc)):
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

    return {'pages': pages, 'page_count': len(pages)}


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
                            "enum": ["multiple_choice", "true_false", "short_answer",
                                     "fill_blank", "calculation", "extended_answer",
                                     "long_division", "column_operation",
                                     "plot_points", "plot_line", "identify_coords",
                                     "read_graph"],
                        },
                        "plane_spec": {
                            "type": "object",
                            "description": (
                                "For plot_points / plot_line / identify_coords only — a signed Cartesian "
                                "plane. bounds = visible axis range; mode 'points' (plot/identify dots) or "
                                "'segments' (a line/shape to join); target = the correct answer (points OR "
                                "segments) in SIGNED integer coords; given_points = points already drawn "
                                "(identify_coords reads these). The app draws the blank plane, so "
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
                        "numeric_answer": {
                            "type": "number",
                            "description": "For read_graph only: the value the student reads off the graph.",
                        },
                        "answer_tolerance": {
                            "type": "number",
                            "description": "For read_graph only: accepted ± band around numeric_answer (e.g. 5). Omit for exact.",
                        },
                        "answer_unit": {
                            "type": "string",
                            "description": "For read_graph only: unit shown after the answer box, e.g. 'km', 'min'.",
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
                                "human_graded = teacher reviews manually (very open-ended / subjective)."
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
4. For numeric/calculation questions ("What is 24 ÷ 6?"), use short_answer with only
   the correct answer — do NOT invent wrong options.
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
   joined line ([{"x1","y1","x2","y2"}]). If a point is ALREADY PLOTTED and the student must WRITE
   its coordinates, use "identify_coords" — mode "points", put the plotted point in BOTH
   plane_spec.given_points and plane_spec.target.points. Set has_image=false (the app draws the
   plane) and leave answers=[].
12. READ A GRAPH: if a PRE-DRAWN line graph (e.g. distance-vs-time) is shown and the student must
   READ a value off it, use "read_graph". Set numeric_answer to the value to read,
   answer_tolerance to a sensible ± band, answer_unit to the axis unit. Keep the graph image
   (has_image=true, image_bbox around the graph). Only add graph_spec if you can read the series
   points confidently; otherwise omit it. Leave answers=[]; validation_type="auto".

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
- If you cannot determine the correct answer with confidence, set validation_type to
  "human_graded" rather than inventing one.

Choosing validation_type per question:
- auto        → MCQ, T/F, short numeric answers, fill-in-the-blank. The system can check
                 the answer exactly. Most questions will be this type.
- ai_graded   → Written explanations, proofs, "show your working", "explain why" questions
                 where the student writes free text and partial credit is meaningful.
                 Write a detailed grading_rubric describing what a full-mark answer must
                 include, common errors to penalise, and partial-credit criteria.
- human_graded → Highly open-ended/subjective questions where even AI cannot reliably
                 determine correctness (e.g., creative responses, complex multi-step
                 proofs that vary widely). Use sparingly — prefer ai_graded.

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
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=120.0,
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
            "Extract ALL questions on these pages. For each question with a shape, diagram, "
            "graph, table, ruler, or number line: set has_image=true and provide image_bbox "
            "[left, top, right, bottom] in the page screenshot's pixel coordinates. "
            "Crop ONLY the visual — not the question text or answer options. "
            "Use the classify_worksheet_questions tool now."
        )
    content_blocks.append({
        "type": "text",
        "text": closing,
    })

    # Stream so a long generation doesn't trip the SDK read timeout.
    # claude-sonnet-4-20250514 is deprecated; default to Opus (env-overridable via
    # WORKSHEET_MODEL). No adaptive thinking here — it is incompatible with the
    # forced tool_choice below.
    with client.messages.stream(
        model=os.environ.get('WORKSHEET_MODEL', 'claude-opus-4-8'),
        max_tokens=WORKSHEET_MAX_TOKENS,
        system=system,
        tools=[WORKSHEET_CLASSIFICATION_TOOL],
        tool_choice={"type": "tool", "name": "classify_worksheet_questions"},
        messages=[{"role": "user", "content": content_blocks}],
    ) as stream:
        response = stream.get_final_message()

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
            raise ValueError(
                'A section of the worksheet is too dense to process in one chunk. '
                'Try a smaller WORKSHEET_CHUNK_SIZE.'
            )
        raise ValueError("AI did not return structured question data. Please try again.")

    result.setdefault('questions', [])
    result['usage'] = {
        'input_tokens': response.usage.input_tokens,
        'output_tokens': response.usage.output_tokens,
        'total_tokens': response.usage.input_tokens + response.usage.output_tokens,
    }
    return result


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
                                 shape_naming=False):
    """Send page screenshots to Claude and get structured questions with image bboxes.

    Multi-page worksheets are split into page-chunks classified *concurrently*
    (CPP: speed). Each chunk generates a fraction of the output and they run at
    the same time, so wall-clock ≈ the slowest chunk rather than the sum. Single
    short worksheets fall through to one call. Results are merged in page order.

    ``shape_naming`` switches to the name-the-shape prompt: one auto-generated
    "What is the name of this shape?" question per individual shape.
    """
    client = _get_anthropic_client()
    system = _build_system_prompt(existing_topics, existing_levels, shape_naming=shape_naming)

    pages = [p for p in extracted_pages['pages'][:WORKSHEET_PAGE_CAP] if p.get('screenshot')]
    if not pages:
        raise ValueError("No page screenshots to classify.")
    total = extracted_pages['page_count']

    chunks = [pages[i:i + WORKSHEET_CHUNK_SIZE]
              for i in range(0, len(pages), WORKSHEET_CHUNK_SIZE)]

    # One chunk → no thread-pool overhead.
    if len(chunks) == 1:
        return _classify_page_chunk(client, system, chunks[0], total, shape_naming=shape_naming)

    ordered = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=min(WORKSHEET_MAX_PARALLEL, len(chunks))) as pool:
        futures = {
            pool.submit(_classify_page_chunk, client, system, chunk, total,
                        shape_naming=shape_naming): idx
            for idx, chunk in enumerate(chunks)
        }
        for fut in as_completed(futures):
            ordered[futures[fut]] = fut.result()  # re-raises any chunk failure

    logger.info('Classified %s pages across %s parallel chunks', len(pages), len(chunks))
    return _merge_chunk_results(ordered)


# ---------------------------------------------------------------------------
# Image rendering: PyMuPDF clip — render region directly from PDF vectors
# ---------------------------------------------------------------------------

def _render_clean_diagram(fitz_page, clip_rect, dpi=150):
    """
    Render *clip_rect* from *fitz_page* with any text blocks that sit
    ABOVE the clip region whited out.

    This removes page headers / section titles (e.g. "Questions") that bleed
    into the top of the crop while keeping the diagram's own angle labels,
    tick marks and other text that are INSIDE the clip region.

    Strategy:
      1. Find all text blocks whose bottom edge is above clip_rect.y0 + a small
         tolerance — these are headers sitting above the diagram.
      2. Apply white redaction rectangles over those blocks on a scratch copy
         of the page.
      3. Render the scratch page, clipped to clip_rect.

    Returns a fitz.Pixmap.
    """
    import fitz

    # Work on a scratch document so we never mutate the original.
    scratch_doc = fitz.open()
    scratch_doc.insert_pdf(fitz_page.parent, from_page=fitz_page.number, to_page=fitz_page.number)
    scratch_page = scratch_doc[0]

    # Redact any text block whose TOP edge starts above the clip region.
    # This catches headers like "Questions" that begin above the diagram but
    # whose bottom half hangs into it. Diagram labels (a, b, c …) start
    # inside the clip so they are never redacted.
    blocks = scratch_page.get_text('blocks')  # (x0, y0, x1, y1, text, block_no, block_type)
    for b in blocks:
        bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
        block_rect = fitz.Rect(bx0, by0, bx1, by1)
        if by0 < clip_rect.y0:   # block starts above the diagram — redact it
            scratch_page.add_redact_annot(block_rect, fill=(1, 1, 1))

    scratch_page.apply_redactions()
    pix = scratch_page.get_pixmap(clip=clip_rect, dpi=dpi)
    scratch_doc.close()
    return pix


def _tight_drawings_rect(fitz_page, search_rect, min_area_pts=50):
    """
    Return the tight bounding rect of all vector drawing elements on *fitz_page*
    that fall within *search_rect* (in PDF points).

    Vector drawings (lines, curves, filled shapes) are the diagram itself.
    Text is never a drawing, so headers / labels outside the actual visual
    are excluded automatically.

    Returns a fitz.Rect, or None if no qualifying drawings were found.
    The returned rect is expanded by a small margin and clamped to *search_rect*.
    """
    import fitz

    drawings = fitz_page.get_drawings()
    if not drawings:
        return None

    xs0, ys0, xs1, ys1 = [], [], [], []
    for d in drawings:
        r = d.get('rect')
        if not r:
            continue
        r = fitz.Rect(r)
        # Must overlap the search region
        if not r.intersects(search_rect):
            continue
        # Skip tiny artefacts (e.g. single-pixel rules)
        if r.width * r.height < min_area_pts:
            continue
        xs0.append(r.x0)
        ys0.append(r.y0)
        xs1.append(r.x1)
        ys1.append(r.y1)

    if not xs0:
        return None

    margin = 6  # pts — small whitespace around the diagram
    page_rect = fitz_page.rect
    tight = fitz.Rect(
        max(search_rect.x0, min(xs0) - margin),
        max(search_rect.y0, min(ys0) - margin),
        # Right / bottom: clamp to page bounds only — drawings may legitimately
        # extend beyond the search_rect if Claude's bbox was too tight.
        min(page_rect.x1, max(xs1) + margin),
        min(page_rect.y1, max(ys1) + margin),
    )
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
        br = fitz.Rect(b[0], b[1], b[2], b[3])
        if br.width > max_label_w:
            continue                 # running text — never an attached label
        if br.y1 <= core.y0:         # sits above the diagram — leave for header redaction
            continue
        # Gap from the diagram core (measured against the core, NOT the growing
        # rect, so one absorbed label can't chain the crop down to the sentence).
        dx = max(core.x0 - br.x1, br.x0 - core.x1, 0.0)
        dy = max(core.y0 - br.y1, br.y0 - core.y1, 0.0)
        if dx <= gap_tol and dy <= gap_tol:
            grown.include_rect(br)   # absorb the attached label

    margin = 4
    grown = fitz.Rect(
        max(page_rect.x0, grown.x0 - margin),
        max(page_rect.y0, grown.y0 - margin),
        min(page_rect.x1, grown.x1 + margin),
        min(page_rect.y1, grown.y1 + margin),
    )
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
            inter = fitz.Rect(r)
            inter.intersect(search_rect)
            if inter.is_valid and abs(inter.get_area()) >= min_overlap_frac * search_area:
                return True
    return False


def _trim_whitespace(pix):
    """
    Remove rows/columns of near-white pixels from all four edges of a
    fitz.Pixmap.  Returns a new Pixmap (or the original if nothing to trim).

    Threshold: a row/column is considered blank if every pixel's average
    RGB value is >= 248 (almost white).
    """
    import fitz

    samples = pix.samples  # raw bytes: w * h * n (n=3 for RGB)
    w, h, n = pix.width, pix.height, pix.n

    if n < 3:
        return pix  # greyscale or alpha-only — skip

    def row_blank(y):
        off = y * w * n
        for x in range(w):
            r, g, b = samples[off + x * n], samples[off + x * n + 1], samples[off + x * n + 2]
            if (r + g + b) // 3 < 248:
                return False
        return True

    def col_blank(x):
        for y in range(h):
            off = y * w * n + x * n
            r, g, b = samples[off], samples[off + 1], samples[off + 2]
            if (r + g + b) // 3 < 248:
                return False
        return True

    top = 0
    while top < h and row_blank(top):
        top += 1
    bottom = h - 1
    while bottom > top and row_blank(bottom):
        bottom -= 1
    left = 0
    while left < w and col_blank(left):
        left += 1
    right = w - 1
    while right > left and col_blank(right):
        right -= 1

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


def render_question_images(doc, extracted_pages, classified_result):
    """
    For every question where has_image=True:
      1. Convert Claude's rough bbox from screenshot pixel space → PDF points.
      2. Use page.get_drawings() to find the tight bounds of actual vector
         elements inside that region — this excludes text (headers, labels)
         which are never drawings.  Falls back to Claude's bbox for raster PDFs.
      3. Render the clean rect at high DPI directly from PDF vectors.
      4. Trim residual whitespace from all edges.
      5. Store as PNG base64.

    Returns:
        (classified_result, extracted_images dict)
    """
    import fitz

    pages_by_num = {p['page_num']: p for p in extracted_pages['pages']}
    extracted_images = {}

    questions = classified_result.get('questions', [])
    for idx, q in enumerate(questions):
        q.setdefault('image_ref', None)

        if not q.get('has_image'):
            continue

        bbox = q.get('image_bbox')
        page_num = q.get('page_num', 1)

        if not bbox or len(bbox) != 4:
            logger.warning(f'Q{idx+1}: has_image=True but no valid image_bbox — skipping')
            continue

        page_data = pages_by_num.get(page_num)
        if not page_data:
            logger.warning(f'Q{idx+1}: page {page_num} not found — skipping')
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
            if clip_rect is None:
                # No vector drawing in the region. Only render if there's an
                # embedded raster figure here (scanned/photo PDF). Otherwise
                # Claude flagged a diagram that doesn't exist — the bbox points at
                # plain text — so drop the image rather than save an irrelevant
                # text crop (the "totally irrelevant image" failure mode).
                if _region_has_raster_image(fitz_page, search_rect):
                    clip_rect = fitz.Rect(pt0, pt1, pt2, min(pdf_h, pt3 + 20))
                else:
                    logger.info(
                        f'Q{idx+1}: has_image=True but no figure (vector or raster) '
                        f'in bbox — dropping spurious image'
                    )
                    q['has_image'] = False
                    continue

            # Render at print-quality DPI with any header text above the crop
            # redacted (whited out). This removes "Questions" / section headings
            # while keeping angle labels and other text inside the diagram itself.
            pix = _render_clean_diagram(fitz_page, clip_rect, dpi=IMAGE_RENDER_DPI)

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
# Full pipeline
# ---------------------------------------------------------------------------

def extract_and_classify_worksheet(pdf_file, existing_topics, existing_levels,
                                   shape_naming=False):
    """
    Full pipeline: PDF → page screenshots → AI classify → render image regions.

    Keeps the fitz.Document open throughout so we can render clips from
    the original PDF vectors rather than cropping JPEG screenshots.

    ``shape_naming`` enables name-the-shape mode: pages are rendered at a higher
    DPI and Claude emits one "name this shape" question per individual shape.

    Returns:
        {
            'result': { year_level, subject, strand, topic, questions[], usage },
            'extracted_images': { ref: base64_png_str, ... },
            'page_count': int,
        }
    """
    import fitz

    pdf_bytes = pdf_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')

    try:
        # Step 1: render pages + collect text (higher DPI in shape mode for tighter crops)
        extracted_pages = extract_worksheet_pages(
            doc, screenshot_dpi=SHAPE_NAMING_DPI if shape_naming else None,
        )

        # Step 2: AI classification (gets question text, type, answers, image bboxes)
        result = classify_worksheet_questions(
            extracted_pages, existing_topics, existing_levels, shape_naming=shape_naming,
        )

        for q in result.get('questions', []):
            # Teacher-graded (human_graded) questions are deselected by default so
            # the teacher opts in rather than out; everything else is included.
            q.setdefault('include', q.get('validation_type') != 'human_graded')

        # Step 3: render image regions from PDF vectors (not screenshot crops)
        result, extracted_images = render_question_images(doc, extracted_pages, result)

    finally:
        doc.close()

    return {
        'result': result,
        'extracted_images': extracted_images,
        'page_count': extracted_pages['page_count'],
    }
