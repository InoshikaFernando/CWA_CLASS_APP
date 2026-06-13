"""
AI Import services: PDF extraction (PyMuPDF) and AI classification (Claude API).
"""
import base64
import json
import os
import re
import tempfile

from django.conf import settings
from django.utils import timezone


# ---------------------------------------------------------------------------
# PDF Extraction (PyMuPDF / fitz)
# ---------------------------------------------------------------------------

# Claude rejects images whose longest side exceeds 2000px in a *many-image*
# request (the case for any multi-page PDF), and downsizes anything over ~1568px
# for vision regardless. Capping embedded images here both avoids an HTTP 400 on
# PDFs that embed full-page scans and trims wasted input tokens. Tune via
# AI_IMPORT_MAX_IMAGE_DIM.
MAX_EMBEDDED_IMAGE_DIM = int(os.environ.get('AI_IMPORT_MAX_IMAGE_DIM', '1568'))


def _downscale_embedded_image(img_bytes, ext):
    """Shrink an embedded image so its longest side <= MAX_EMBEDDED_IMAGE_DIM.

    Returns (bytes, ext). Leaves the image untouched if it's already small
    enough, or if PIL can't decode it (better to send the original than drop it).
    PNGs stay PNG; everything else re-encodes to JPEG to keep the payload small.
    """
    try:
        import io

        from PIL import Image

        im = Image.open(io.BytesIO(img_bytes))
        if max(im.size) <= MAX_EMBEDDED_IMAGE_DIM:
            return img_bytes, ext
        im.thumbnail((MAX_EMBEDDED_IMAGE_DIM, MAX_EMBEDDED_IMAGE_DIM))
        buf = io.BytesIO()
        if ext == 'png':
            im.save(buf, format='PNG')
            return buf.getvalue(), 'png'
        im.convert('RGB').save(buf, format='JPEG', quality=85)
        return buf.getvalue(), 'jpeg'
    except Exception:
        return img_bytes, ext


def _page_figure_regions(page):
    """Bounding boxes (percent of page) of clustered vector drawings on a page.

    Used to snap an AI-supplied figure crop onto the actual drawn figure, so a
    slightly-off box doesn't clip the diagram or swallow a neighbouring question.
    Page-sized clusters (borders / full-page rules) and tiny specks are dropped.
    Best-effort: returns [] if PyMuPDF can't provide drawings.
    """
    try:
        pw, ph = page.rect.width, page.rect.height
        if pw <= 0 or ph <= 0:
            return []
        regions = []
        for r in page.cluster_drawings():
            w, h = r.width, r.height
            area_frac = (w * h) / (pw * ph)
            if area_frac > 0.80:
                continue  # page border / full-page decoration, not a figure
            if (w / pw) < 0.02 and (h / ph) < 0.02:
                continue  # speck (stray dot / single glyph stroke)
            regions.append([
                r.x0 / pw * 100, r.y0 / ph * 100,
                r.x1 / pw * 100, r.y1 / ph * 100,
            ])
        return regions
    except Exception:
        return []

def get_pdf_page_count(pdf_file):
    """Cheaply count pages in a PDF without rendering screenshots.

    Used for the quota check before enqueuing the (slow) classification job.
    Resets the file pointer afterwards so the file can be re-read.
    """
    import fitz  # PyMuPDF

    pos = pdf_file.tell() if hasattr(pdf_file, 'tell') else None
    pdf_bytes = pdf_file.read()
    if pos is not None and hasattr(pdf_file, 'seek'):
        pdf_file.seek(pos)
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    count = doc.page_count
    doc.close()
    return count


def extract_pdf_content(pdf_file):
    """
    Extract text and images from a PDF file using PyMuPDF.

    Args:
        pdf_file: Django UploadedFile or file-like object

    Returns:
        {
            'pages': [
                {'page_num': int, 'text': str, 'images': [{'ref': str, 'base64': str, 'ext': str}]}
            ],
            'page_count': int,
            'all_text': str,  # concatenated text for AI
        }
    """
    import fitz  # PyMuPDF

    pdf_bytes = pdf_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')

    pages = []
    all_text_parts = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text('text')
        all_text_parts.append(text)

        images = []
        # Extract embedded images
        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            if base_image:
                img_bytes = base_image['image']
                ext = base_image.get('ext', 'png')
                img_bytes, ext = _downscale_embedded_image(img_bytes, ext)
                ref = f'page{page_num + 1}_img{img_idx + 1}.{ext}'
                images.append({
                    'ref': ref,
                    'base64': base64.b64encode(img_bytes).decode('utf-8'),
                    'ext': ext,
                })

        # Render the full page as a screenshot (captures tables, charts, diagrams).
        # 150 DPI is the quality sweet spot — lower makes Claude miss questions
        # (small text becomes illegible). Tune down via AI_IMPORT_SCREENSHOT_DPI
        # only if memory is tight; the pixmap is freed below to limit the spike.
        dpi = int(os.environ.get('AI_IMPORT_SCREENSHOT_DPI', '150'))
        pix = page.get_pixmap(dpi=dpi)
        page_img_bytes = pix.tobytes('jpeg')
        page_screenshot_b64 = base64.b64encode(page_img_bytes).decode('utf-8')
        pix = None
        page_img_bytes = None

        pages.append({
            'page_num': page_num + 1,
            'text': text,
            'images': images,
            'screenshot': page_screenshot_b64,
            'figure_regions': _page_figure_regions(page),
        })

    doc.close()

    return {
        'pages': pages,
        'page_count': len(pages),
        'all_text': '\n\n--- Page Break ---\n\n'.join(all_text_parts),
    }


# ---------------------------------------------------------------------------
# AI Classification (Claude API)
# ---------------------------------------------------------------------------

def _get_anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _build_classification_prompt(existing_topics, existing_levels):
    """Build the system prompt for question classification."""
    topic_names = ', '.join(t['name'] for t in existing_topics) if existing_topics else 'None yet'
    level_names = ', '.join(
        f"Year {l['level_number']} ({l['display_name']})"
        for l in existing_levels if l['level_number'] <= 12
    ) if existing_levels else 'Year 1-8'

    return f"""You are an expert educational content classifier. You extract questions from PDF documents
and classify them by grade level, subject, topic, and subtopic.

EXISTING TOPICS in the system: {topic_names}
EXISTING LEVELS in the system: {level_names}

Your task:
1. Extract each question with its text, type, difficulty, answers
2. For EACH question, classify: year_level, subject, strand, topic (PDFs may mix topics)
3. Attach a visual to a question ONLY when it genuinely DEPENDS on one that cannot be written
   as text (see IMAGE NECESSITY below). When a visual IS needed, attach it in ONE of two ways:
   a. If the visual IS one of the embedded images listed in the input (e.g. "page1_img1.png"),
      set image_ref to that reference and leave image_page/image_box null. Only use embedded
      image refs — never full-page screenshots.
   b. If the visual is DRAWN into the page and has no embedded image reference (most shapes,
      geometry figures and number lines are like this), leave image_ref null and instead set
      image_page to the page it is on and image_box to its bounding box as percentages of that
      page (see the image_box field description). Box the figure tightly.
   Do NOT invent or reuse an embedded image_ref that does not actually depict this question's
   visual — if no embedded image matches but a visual is genuinely needed, use approach (b).
   If a question has no visual, leave image_ref, image_page, and image_box all null.
4. Do NOT embed table/chart data as text in the question — keep question_text concise and
   reference the image instead when the question depends on a visual.

IMAGE NECESSITY (important — most questions need NO image):
- Set image_ref to null whenever the question can be fully understood and answered from text alone
  (plus any structured fields below). An image is needed ONLY when it carries information that
  cannot be expressed in words: a data table, a chart/graph, a geometric figure, a number line,
  a clock face, a picture/object to interpret, a map, etc.
- Worksheets are full of decorative or scaffolding graphics that carry NO information — blank answer
  boxes, grid/squared paper, working space, ruled lines, long-division brackets, column-arithmetic
  grids, page borders. NEVER attach these.
- If a graphic only shows HOW to lay out the working (long-division "bus stop" bracket, stacked
  column arithmetic), transcribe it into the structured fields/text below and set image_ref to null.
- When unsure, prefer NO image. A wrongly-attached image is worse than none.

SPLIT MULTI-PART QUESTIONS (important):
- When a single question contains multiple sub-parts labelled a), b), c) (or i, ii, iii / 1, 2, 3),
  emit ONE separate question per sub-part. Do NOT keep them combined in a single question_text
  with a single combined answer.
- Carry the shared instruction/stem into every split question so each one stands alone.
  Example: the source "Simplify the following: a) 5 × y  b) x × y × 4  c) 2 × p × 7 × q" with
  answers "a) 5y  b) 4xy  c) 14pq" must become THREE questions:
    1. question_text "Simplify: 5 × y", answer "5y"
    2. question_text "Simplify: x × y × 4", answer "4xy"
    3. question_text "Simplify: 2 × p × 7 × q", answer "14pq"
- Match each sub-part to its own answer. Never produce an answer like "a) 5y b) 4xy c) 14pq".
- Only keep parts together when they genuinely cannot be answered independently (e.g. part b
  explicitly depends on the result of part a); in that rare case, note the dependency in the text.

QUESTION TYPE RULES (important):
- If a problem is presented VERTICALLY / STACKED — numbers written one above another with an
  operator and a horizontal rule, i.e. traditional column addition, subtraction, or multiplication
  (long-hand "carry"/"borrow" layout) — use question_type "column_operation". Put the numbers
  top-to-bottom in "operands" (e.g. [90, 82]) and set "operator" to "+", "-", or "*". Set
  question_text to the instruction ONLY (e.g. "Find the difference.") — do NOT repeat the numbers in
  the text. Do NOT generate answers; the result is computed automatically.
  IMPORTANT: only use "column_operation" when the problem is actually drawn stacked/vertical. If the
  SAME arithmetic is written inline on one horizontal line (e.g. "90 - 82 =" or "90 take away 82"),
  use "short_answer" instead. Division stays "long_division", never "column_operation".
- If a DIVISION is drawn in the long-division "bus stop" layout — the divisor written to the LEFT of
  a vertical bar and the dividend UNDER a horizontal bar (e.g. "47" outside, "611" under the bar) —
  use question_type "long_division". Set "dividend" to the number under the bar (the number being
  divided) and "divisor" to the number outside it. Set question_text to
  "Solve using long division: {{dividend}} ÷ {{divisor}}". Do NOT concatenate the digits into one number
  (e.g. never "47611"), and do NOT attach the layout image — the app draws the bracket. The answer
  is computed automatically; do not generate answers.
- If the correct answer is a NUMBER ONLY (digits, decimals, fractions like "14" or "3.5" or "2/3"),
  use question_type "short_answer" with just the correct answer. Do NOT generate wrong answers.
- If the correct answer contains TEXT or WORDS (e.g. "Day 3 had the most sales", "True", "Red"),
  use question_type "multiple_choice" and generate 3-4 plausible wrong answers alongside the correct one.
- For true/false questions, use "true_false" type.
- For fill-in-the-blank, use "fill_blank" type.

ANSWER BLANK FORMATTING (important):
- When a question is an equation where the student fills in a missing value, ALWAYS represent
  the missing value with a blank line of underscores ("______"). Never leave a dangling operator.
- If the missing value is on the left of the equals sign, write the blank before the "=".
  Example: a question shown as "= 8,005 + 408" must be written as "______ = 8,005 + 408".
- If the missing value is on the right or in the middle, put the blank in that position.
  Examples: "8,005 + 408 = ______", "8,005 + ______ = 8,413".
- Apply this to question_text. Do NOT put the answer itself into the blank — the answer goes in
  the answers array as usual.

For difficulty, use: 1 (Easy), 2 (Medium), 3 (Hard)

ACCURACY — VERIFY EVERY ANSWER BEFORE RETURNING IT:
Do NOT guess answers. Re-derive each answer from the numbers and figures actually
shown in the question, then check it.
- For computational questions (arithmetic, long multiplication/division, missing-digit
  puzzles, etc.) work the problem out fully and confirm your answer reproduces EVERY
  value shown in the image — including any partial products, carried digits, or
  worked-solution steps. If a worked solution is visible (e.g. the partial products in a
  long-multiplication grid), the answer MUST be consistent with all of it; if it is not,
  recompute until it is.
- The explanation must describe the SAME numbers as the answer. Never let the answer and
  the explanation disagree with each other or with the figure.
- If you cannot determine the correct answer with confidence, leave the answer text empty
  rather than inventing one.

Map to existing topics where possible. If no match, suggest a new topic name.
Set default year_level, subject, strand, topic at the top level, then override per-question only if different.

Return your response as a JSON object."""


CLASSIFICATION_TOOL = {
    "name": "classify_questions",
    "description": "Classify and structure questions extracted from a PDF document",
    "input_schema": {
        "type": "object",
        "properties": {
            "year_level": {
                "type": "integer",
                "description": "Default year/grade level (1-12) for all questions",
            },
            "subject": {
                "type": "string",
                "description": "Default subject name, e.g. Mathematics",
            },
            "strand": {
                "type": "string",
                "description": "Default top-level topic group, e.g. Number, Measurement, Algebra",
            },
            "topic": {
                "type": "string",
                "description": "Default specific topic, e.g. Fractions, Decimals, Quadratics",
            },
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_text": {"type": "string"},
                        "question_type": {
                            "type": "string",
                            "enum": ["multiple_choice", "true_false", "short_answer", "fill_blank", "calculation", "column_operation", "long_division"],
                        },
                        "operands": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "For column_operation only: the stacked numbers top-to-bottom, e.g. [90, 82].",
                        },
                        "operator": {
                            "type": "string",
                            "enum": ["+", "-", "*"],
                            "description": "For column_operation only: the arithmetic operator.",
                        },
                        "dividend": {
                            "type": "integer",
                            "description": "For long_division only: the number being divided (under the bar), e.g. 611.",
                        },
                        "divisor": {
                            "type": "integer",
                            "description": "For long_division only: the number dividing (outside/left of the bar), e.g. 47.",
                        },
                        "difficulty": {"type": "integer", "enum": [1, 2, 3]},
                        "points": {"type": "integer", "default": 1},
                        "explanation": {"type": "string", "description": "Brief explanation of the answer"},
                        "image_ref": {
                            "type": "string",
                            "description": "Reference to an EMBEDDED image (e.g. page1_img1.png) listed in the input. Set only when the question's visual is one of those embedded images. Null otherwise.",
                        },
                        "image_page": {
                            "type": "integer",
                            "description": "1-based page number the visual is on. Set ONLY when the question needs a drawn figure (shape, geometric diagram, number line, hand-drawn grid) that is NOT an embedded image — i.e. image_ref is null. Null otherwise.",
                        },
                        "image_box": {
                            "type": "object",
                            "description": "Bounding box of the drawn figure, as PERCENTAGES of the page (0-100). Origin (0,0) is the page's top-left; x1,y1 = top-left corner of the box, x2,y2 = bottom-right corner. Set ONLY together with image_page when image_ref is null. Box the figure tightly — exclude the question text and any neighbouring questions. Null otherwise.",
                            "properties": {
                                "x1": {"type": "number"},
                                "y1": {"type": "number"},
                                "x2": {"type": "number"},
                                "y2": {"type": "number"},
                            },
                        },
                        "year_level": {
                            "type": "integer",
                            "description": "Override year level for this question if different from default",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Override subject for this question if different from default",
                        },
                        "strand": {
                            "type": "string",
                            "description": "Override strand for this question if different from default",
                        },
                        "topic": {
                            "type": "string",
                            "description": "Override topic for this question if different from default",
                        },
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
                    "required": ["question_text", "question_type", "difficulty", "answers"],
                },
            },
        },
        "required": ["year_level", "subject", "strand", "topic", "questions"],
    },
}


# Matches a question_text that begins with an "=" (optionally after whitespace),
# i.e. the answer/left operand is missing. Captures any leading whitespace to preserve it.
_LEADING_EQUALS_RE = re.compile(r'^(\s*)=')


def _normalize_answer_blank(question_text):
    """
    Safety net for the ANSWER BLANK FORMATTING prompt rule: if a question starts with
    an "=" (the left side of the equation is blank), prepend an underscore blank so the
    student sees "______ = 8,005 + 408" instead of a dangling "= 8,005 + 408".

    Idempotent and conservative — only touches text whose first non-space char is "=".
    """
    if not question_text:
        return question_text
    if _LEADING_EQUALS_RE.match(question_text):
        # Keep any leading whitespace, insert the blank, then a space before the "=".
        return _LEADING_EQUALS_RE.sub(r'\1______ =', question_text, count=1)
    return question_text


def _classify_page_batch(client, system_prompt, pages, total_page_count):
    """Run one Claude classification request over a batch of extracted pages.

    Pages keep their real (global) page_num in the screenshot labels and embedded
    image refs, so image_page / image_ref the model returns stay valid for the
    whole document regardless of which batch a page fell in.

    Returns the raw tool-result dict with a 'usage' sub-dict. Raises ValueError
    if the model returns no structured data.
    """
    first_pg = pages[0]['page_num']
    last_pg = pages[-1]['page_num']

    content_blocks = [{
        "type": "text",
        "text": (
            f"Here is a {total_page_count}-page PDF (this message covers pages "
            f"{first_pg}–{last_pg}). I'm sending each page as a screenshot so "
            f"you can see all tables, charts, and diagrams. The extracted text is "
            f"also provided for accuracy."
        ),
    }]

    for page in pages:
        # Page screenshot — captures everything including tables, charts, diagrams
        if page.get('screenshot'):
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
                "text": f"[Page {page['page_num']} screenshot above. Extracted text: {page['text'][:500]}]",
            })

        # Also include any embedded images with references for the AI to map
        for img in page.get('images', []):
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": f"image/{img['ext'] if img['ext'] != 'jpg' else 'jpeg'}",
                    "data": img['base64'],
                },
            })
            content_blocks.append({
                "type": "text",
                "text": f"[Embedded image: {img['ref']}]",
            })

    content_blocks.append({
        "type": "text",
        "text": "Please extract and classify ALL questions from these pages. Include any context tables, data, or diagrams that belong with each question in the question_text. Use the classify_questions tool to return structured data.",
    })

    # Stream the request so a long (multi-page) generation doesn't trip the SDK
    # read timeout (anthropic.APITimeoutError). get_final_message() returns the
    # same Message a non-streaming create() would.
    #
    # Default to Opus (far stronger arithmetic — it reliably solves the
    # missing-digit / worked-solution questions that Sonnet 4 guessed wrong) with
    # adaptive thinking so it works each computation out before answering. Override
    # the model via AI_IMPORT_MODEL (must be a model that supports adaptive
    # thinking — Opus/Sonnet 4.6+).
    with client.messages.stream(
        model=os.environ.get('AI_IMPORT_MODEL', 'claude-opus-4-8'),
        # Generous cap so a question-dense / multi-page PDF doesn't get its
        # extracted-question list truncated (override via AI_IMPORT_MAX_TOKENS).
        max_tokens=int(os.environ.get('AI_IMPORT_MAX_TOKENS', '32000')),
        thinking={"type": "adaptive"},
        system=system_prompt,
        tools=[CLASSIFICATION_TOOL],
        messages=[{"role": "user", "content": content_blocks}],
    ) as stream:
        response = stream.get_final_message()

    # Extract tool use result
    result = None
    for block in response.content:
        if block.type == 'tool_use' and block.name == 'classify_questions':
            result = block.input
            break

    if not result:
        # Fallback: try to parse text response as JSON
        for block in response.content:
            if block.type == 'text':
                try:
                    result = json.loads(block.text)
                    break
                except json.JSONDecodeError:
                    pass

    if not result:
        raise ValueError("AI did not return structured question data. Please try again.")

    result['usage'] = {
        'input_tokens': response.usage.input_tokens,
        'output_tokens': response.usage.output_tokens,
        'total_tokens': response.usage.input_tokens + response.usage.output_tokens,
    }
    return result


def classify_questions(extracted_content, existing_topics, existing_levels):
    """
    Send extracted PDF content to Claude API for classification.

    Long PDFs are split into batches of AI_IMPORT_PAGE_CHUNK pages (default 20)
    so nothing past page 20 is silently dropped; each batch is classified and the
    questions are merged. Top-level classification (year_level/subject/strand/
    topic) comes from the first batch — per-question overrides cover the rest.

    Args:
        extracted_content: Output from extract_pdf_content()
        existing_topics: List of dicts [{'name': str, 'slug': str}]
        existing_levels: List of dicts [{'level_number': int, 'display_name': str}]

    Returns:
        {
            'year_level': int,
            'subject': str,
            'strand': str,
            'topic': str,
            'questions': [...],
            'usage': {'input_tokens': int, 'output_tokens': int, 'total_tokens': int},
        }
    """
    client = _get_anthropic_client()
    system_prompt = _build_classification_prompt(existing_topics, existing_levels)

    pages = extracted_content.get('pages', [])
    total = extracted_content.get('page_count', len(pages))
    chunk_size = max(1, int(os.environ.get('AI_IMPORT_PAGE_CHUNK', '20')))
    batches = [pages[i:i + chunk_size] for i in range(0, len(pages), chunk_size)]

    merged = None
    in_tok = out_tok = 0
    for batch in batches:
        if not batch:
            continue
        result = _classify_page_batch(client, system_prompt, batch, total)
        in_tok += result['usage']['input_tokens']
        out_tok += result['usage']['output_tokens']
        if merged is None:
            merged = result
        else:
            merged.setdefault('questions', []).extend(result.get('questions', []))

    if merged is None:
        raise ValueError("AI did not return structured question data. Please try again.")

    # Safety net for ANSWER BLANK FORMATTING: ensure a missing left operand renders as a blank.
    for q in merged.get('questions', []):
        q['question_text'] = _normalize_answer_blank(q.get('question_text', ''))

    merged['usage'] = {
        'input_tokens': in_tok,
        'output_tokens': out_tok,
        'total_tokens': in_tok + out_tok,
    }
    return merged


# ---------------------------------------------------------------------------
# Figure cropping (drawn diagrams with no embedded raster image)
# ---------------------------------------------------------------------------

# Padding (percent of page, per side) added around a detected figure so axis
# labels / numbers sitting just outside the vector drawing aren't clipped.
FIGURE_CROP_PAD_PCT = float(os.environ.get('AI_IMPORT_FIGURE_CROP_PAD', '2.0'))


def _boxes_overlap(a, b):
    """True if two [x1, y1, x2, y2] boxes share any area."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _snap_box_to_figures(box, regions):
    """Refine an AI figure box to the actual drawn-figure bounds.

    `box` and `regions` entries are [x1, y1, x2, y2] in percent of the page.
    Returns the padded union of the drawing clusters that overlap `box` — this
    both expands a too-tight box to include the whole figure and shrinks a
    too-loose one back off neighbouring text. If no cluster overlaps, returns
    `box` unchanged (the model's box is then the only signal we have).
    """
    overlapping = [r for r in regions if _boxes_overlap(box, r)]
    if not overlapping:
        return box
    pad = FIGURE_CROP_PAD_PCT
    snapped = [
        max(0.0, min(r[0] for r in overlapping) - pad),
        max(0.0, min(r[1] for r in overlapping) - pad),
        min(100.0, max(r[2] for r in overlapping) + pad),
        min(100.0, max(r[3] for r in overlapping) + pad),
    ]

    # Guard against fragmented clusters: when cluster_drawings splits a figure
    # (e.g. a number line into separate ticks), the overlapping pieces can be far
    # smaller than the real figure. If snapping would collapse the crop to a
    # sliver of the model's box, the detection is unreliable — trust the box.
    def _area(b):
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    if _area(snapped) < 0.20 * _area(box):
        return box
    return snapped


def crop_figure_boxes(extracted_content, result):
    """Crop drawn figures from page screenshots and register them as images.

    The classifier returns image_page + image_box (percentages of the page) for
    questions whose visual is drawn into the page rather than an embedded raster
    image. For each such question we crop the box out of that page's rendered
    screenshot, rewrite the question's image_ref to a generated filename, and
    return {ref: base64_png} so the crops join the embedded-image pool and save
    through the normal image path.

    Questions that already point at a real embedded image_ref are left untouched.
    Mutates the question dicts in `result` in place.
    """
    import io

    from PIL import Image

    pages = {
        p['page_num']: p
        for p in extracted_content.get('pages', [])
        if p.get('page_num') is not None
    }
    crops = {}
    decoded = {}  # page_num -> PIL Image, so each screenshot is decoded only once

    for idx, q in enumerate(result.get('questions', []), 1):
        # An embedded image already covers this question — prefer it (raster
        # fidelity beats a screenshot crop).
        if q.get('image_ref'):
            q.pop('image_page', None)
            q.pop('image_box', None)
            continue

        box = q.get('image_box')
        page_num = q.get('image_page')
        # Clear the transient box fields regardless of outcome so they never
        # get persisted on the session / shown in the editor.
        q.pop('image_box', None)
        q.pop('image_page', None)
        if not box or not page_num:
            continue

        try:
            page = pages.get(int(page_num))
            x1, y1 = float(box['x1']), float(box['y1'])
            x2, y2 = float(box['x2']), float(box['y2'])
        except (KeyError, TypeError, ValueError):
            continue
        if not page or not page.get('screenshot'):
            continue

        # Normalise corner order and clamp to the page.
        lo_x, hi_x = sorted((x1, x2))
        lo_y, hi_y = sorted((y1, y2))
        lo_x, hi_x = max(0.0, lo_x), min(100.0, hi_x)
        lo_y, hi_y = max(0.0, lo_y), min(100.0, hi_y)

        # Snap to the actual drawn-figure bounds when we detected vector clusters
        # on the page — corrects boxes that clip the figure or grab adjacent text.
        regions = page.get('figure_regions')
        if regions:
            lo_x, lo_y, hi_x, hi_y = _snap_box_to_figures(
                [lo_x, lo_y, hi_x, hi_y], regions)

        if hi_x - lo_x < 1 or hi_y - lo_y < 1:
            continue  # degenerate / empty box

        try:
            img = decoded.get(int(page_num))
            if img is None:
                img = Image.open(io.BytesIO(base64.b64decode(page['screenshot'])))
                decoded[int(page_num)] = img
            w, h = img.size
            crop = img.crop((
                int(lo_x / 100 * w), int(lo_y / 100 * h),
                int(hi_x / 100 * w), int(hi_y / 100 * h),
            ))
            buf = io.BytesIO()
            crop.save(buf, format='PNG')
        except Exception:
            # A bad box / unreadable screenshot shouldn't sink the whole import.
            continue

        ref = f'page{int(page_num)}_figure{idx}.png'
        crops[ref] = base64.b64encode(buf.getvalue()).decode('utf-8')
        q['image_ref'] = ref

    return crops


# ---------------------------------------------------------------------------
# Save Questions to DB
# ---------------------------------------------------------------------------

def _compute_column_result(operands, operator):
    """Compute a column-arithmetic result before the Question row exists.

    Mirrors Question.column_result (which operates on a saved instance) so the
    importer can validate the answer up-front. Returns None on bad input.
    """
    try:
        nums = [int(o) for o in (operands or [])]
    except (TypeError, ValueError):
        return None
    if not nums:
        return None
    if operator == '+':
        return sum(nums)
    if operator == '-':
        result = nums[0]
        for n in nums[1:]:
            result -= n
        return result
    if operator in ('*', '×', 'x'):
        result = 1
        for n in nums:
            result *= n
        return result
    return None


def _compute_long_division_answer(dividend, divisor):
    """Canonical answer for a long-division question.

    Returns "Q" when the division is exact, otherwise "Q r R" (matching the
    seed-data format, e.g. "56 r 4"). Returns None on bad input.
    """
    try:
        dividend = int(dividend)
        divisor = int(divisor)
    except (TypeError, ValueError):
        return None
    if divisor <= 0 or dividend < 0:
        return None
    quotient, remainder = divmod(dividend, divisor)
    return str(quotient) if remainder == 0 else f"{quotient} r {remainder}"


def _resolve_image_ref(image_ref, extracted_images):
    """Match an AI-supplied image_ref to a real key in extracted_images.

    The model often returns the ref without its extension (e.g. "page3_img1" when
    the stored key is "page3_img1.png"), which would otherwise silently drop a
    perfectly good embedded figure. Tries an exact match first, then falls back to
    matching on the extension-less stem. Returns the real key, or None if nothing
    matches.
    """
    if not image_ref or not extracted_images:
        return None
    if image_ref in extracted_images:
        return image_ref
    stem = image_ref.rsplit('.', 1)[0]
    for key in extracted_images:
        if key.rsplit('.', 1)[0] == stem:
            return key
    return None


def _resolve_topic_for_question(q, default_data):
    """Resolve subject, strand, topic, level for a single question (per-question overrides)."""
    from classroom.models import Subject, Topic, Level

    subject_name = q.get('subject') or default_data.get('subject', 'Mathematics')
    strand_name = q.get('strand') or default_data.get('strand', '')
    topic_name = q.get('topic') or default_data.get('topic', '')
    year_level = q.get('year_level') or default_data.get('year_level')

    # Resolve subject
    subject_slug = subject_name.lower().replace(' ', '-')
    subject, _ = Subject.objects.get_or_create(
        slug=subject_slug, school=None,
        defaults={'name': subject_name},
    )

    # Resolve strand (parent topic)
    strand_topic = None
    if strand_name:
        strand_slug = strand_name.lower().replace(' ', '-')
        strand_topic, _ = Topic.objects.get_or_create(
            subject=subject, slug=strand_slug, parent=None,
            defaults={'name': strand_name},
        )

    # Resolve topic
    topic = None
    topic_slug = 'general'
    if topic_name:
        topic_slug = topic_name.lower().replace(' ', '-')
        topic, _ = Topic.objects.get_or_create(
            subject=subject, slug=topic_slug,
            defaults={'name': topic_name, 'parent': strand_topic},
        )

    # Get level
    level = None
    if year_level:
        try:
            level = Level.objects.get(level_number=int(year_level))
        except Level.DoesNotExist:
            pass

    # Auto-link topic and strand to the level (so they appear in topic browser)
    if level:
        if topic and not topic.levels.filter(pk=level.pk).exists():
            topic.levels.add(level)
        if strand_topic and not strand_topic.levels.filter(pk=level.pk).exists():
            strand_topic.levels.add(level)

    return subject, topic, level, topic_slug, year_level


def save_questions_from_session(session, user, overrides=None):
    """
    Save AI-classified questions from an AIImportSession to the database.
    Supports per-question topic/level/subject overrides.

    Returns:
        {'inserted': int, 'updated': int, 'failed': int, 'errors': [], 'images_saved': int}
    """
    from django.db import transaction

    from classroom.models import Subject, Topic, Level, School
    from classroom.views import _get_question_scope
    from maths.models import Question as MathsQuestion, Answer as MathsAnswer

    data = overrides if overrides else session.extracted_data
    questions_data = data.get('questions', [])

    # Get scope
    school_id, dept_id, classroom_ids = _get_question_scope(user)
    classroom_id = data.get('classroom_id')
    if classroom_id:
        classroom_id = int(classroom_id)

    inserted = 0
    updated = 0
    failed = 0
    images_saved = 0
    errors = []

    for idx, q in enumerate(questions_data, 1):
        # Skip if not included (from preview form)
        if not q.get('include', True):
            continue

        q_text = q.get('question_text', '').strip()
        if not q_text:
            errors.append(f'Q{idx}: Empty question text')
            failed += 1
            continue

        # Per-question classification
        subject, topic, level, topic_slug, year_level = _resolve_topic_for_question(q, data)
        if not level:
            yl = q.get('year_level') or data.get('year_level', '?')
            errors.append(f'Q{idx}: Level for Year {yl} not found')
            failed += 1
            continue

        q_type = q.get('question_type', 'short_answer')
        difficulty = q.get('difficulty', 1)
        points = q.get('points', 1)
        explanation = q.get('explanation', '')
        answers_data = q.get('answers', [])
        image_ref = q.get('image_ref')
        if image_ref == 'none' or image_ref == '':
            image_ref = None

        # Self-rendering types draw their own layout from structured fields, so any
        # attached worksheet graphic (division bracket, column grid) is just noise.
        if q_type in ('column_operation', 'long_division'):
            image_ref = None

        # Long-division fields (bus-stop layout)
        dividend = None
        divisor = None
        if q_type == 'long_division':
            try:
                dividend = int(q.get('dividend'))
                divisor = int(q.get('divisor'))
            except (TypeError, ValueError):
                dividend = divisor = None
            if not dividend or not divisor or divisor <= 0:
                errors.append(
                    f'Q{idx}: Invalid long_division '
                    f'(dividend={q.get("dividend")!r}, divisor={q.get("divisor")!r})'
                )
                failed += 1
                continue

        # Column-arithmetic fields (vertical/stacked operations)
        operands = None
        operator = ''
        if q_type == 'column_operation':
            raw_operands = q.get('operands') or []
            try:
                operands = [int(o) for o in raw_operands]
            except (TypeError, ValueError):
                operands = []
            operator = (q.get('operator') or '').strip()
            # Canonicalise the multiply glyphs the AI may emit to a single stored form.
            if operator in ('×', 'x'):
                operator = '*'
            if len(operands) < 2 or operator not in ('+', '-', '*'):
                errors.append(f'Q{idx}: Invalid column_operation (operands={raw_operands}, operator={operator!r})')
                failed += 1
                continue
            # A column widget has no minus-sign input, so a negative result is
            # unanswerable. Reject reversed-order subtractions rather than import
            # a question no student can ever get right.
            _col_result = _compute_column_result(operands, operator)
            if _col_result is None or _col_result < 0:
                errors.append(f'Q{idx}: column_operation result is invalid/negative (operands={operands}, operator={operator!r})')
                failed += 1
                continue

        try:
            with transaction.atomic():
                # Check for existing question (same text + topic + level + scope)
                lookup = {
                    'question_text': q_text, 'topic': topic, 'level': level,
                    'school_id': school_id, 'department_id': dept_id,
                    'classroom_id': classroom_id,
                }
                existing = MathsQuestion.objects.filter(**lookup).first()

                if existing:
                    # Update
                    existing.question_type = q_type
                    existing.difficulty = difficulty
                    existing.points = points
                    existing.explanation = explanation
                    existing.operands = operands
                    existing.operator = operator
                    existing.dividend = dividend
                    existing.divisor = divisor
                    existing.save()
                    existing.answers.all().delete()
                    question = existing
                    updated += 1
                else:
                    # Create
                    question = MathsQuestion.objects.create(
                        level=level, topic=topic,
                        school_id=school_id, department_id=dept_id,
                        classroom_id=classroom_id,
                        question_text=q_text, question_type=q_type,
                        difficulty=difficulty, points=points,
                        explanation=explanation,
                        operands=operands, operator=operator,
                        dividend=dividend, divisor=divisor,
                    )
                    inserted += 1

                # Save image if referenced — write through the storage backend
                # (ImageField.save) so the file lands on S3/Spaces in prod as well
                # as local media. The field's upload_to='questions/' is prepended
                # automatically, so the name here is year{N}/{topic_slug}/{file}.
                resolved_ref = _resolve_image_ref(image_ref, session.extracted_images)
                if resolved_ref:
                    from django.core.files.base import ContentFile

                    img_bytes = base64.b64decode(session.extracted_images[resolved_ref])
                    name = f'year{year_level}/{topic_slug}/{resolved_ref}'
                    question.image.save(name, ContentFile(img_bytes), save=False)
                    question.save(update_fields=['image'])
                    images_saved += 1

                # Create answers
                if q_type == 'column_operation':
                    # Answer is computed from the operands — ignore any AI-supplied answers.
                    result = question.column_result
                    MathsAnswer.objects.create(
                        question=question,
                        answer_text=str(result) if result is not None else '',
                        is_correct=True,
                        order=1,
                    )
                elif q_type == 'long_division':
                    # Answer is computed from dividend/divisor — ignore AI arithmetic.
                    ld_answer = _compute_long_division_answer(dividend, divisor)
                    MathsAnswer.objects.create(
                        question=question,
                        answer_text=ld_answer or '',
                        is_correct=True,
                        order=1,
                    )
                else:
                    for a_idx, ans in enumerate(answers_data):
                        MathsAnswer.objects.create(
                            question=question,
                            answer_text=ans.get('text', ''),
                            is_correct=ans.get('is_correct', False),
                            order=a_idx + 1,
                        )

        except Exception as e:
            errors.append(f'Q{idx}: {str(e)}')
            failed += 1

    # Mark session as confirmed
    session.is_confirmed = True
    session.save(update_fields=['is_confirmed'])

    return {
        'inserted': inserted,
        'updated': updated,
        'failed': failed,
        'errors': errors,
        'images_saved': images_saved,
    }
