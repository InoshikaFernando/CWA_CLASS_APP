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

from django.conf import settings

logger = logging.getLogger(__name__)

SCREENSHOT_DPI = 150  # DPI used when rendering page screenshots sent to Claude


# ---------------------------------------------------------------------------
# PDF page extraction (worksheet-specific — tracks screenshot dimensions)
# ---------------------------------------------------------------------------

def extract_worksheet_pages(doc):
    """
    Render each page of an open fitz.Document.

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
    pages = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text('text')

        # Render full page as JPEG screenshot for Claude
        pix = page.get_pixmap(dpi=SCREENSHOT_DPI)
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
                                     "fill_blank", "calculation", "extended_answer"],
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
                                "Describe: what a correct answer must include, "
                                "common mistakes to penalise, and partial-credit criteria. "
                                "Leave empty for auto-validated questions."
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
3. For questions with a VISUAL (shape, diagram, ruler, number line, graph, table, grid,
   geometric figure, coordinate plane): set has_image=true and give image_bbox as the
   pixel bounding box of ONLY the visual in the page screenshot.
   - Do NOT include the question text in the bbox.
   - Do NOT include answer option text in the bbox.
   - Do NOT include section headings like "Questions", "Section A", "Exercise" etc.
   - Do NOT include question numbers (e.g. "1.", "Q2").
   - The TOP edge of the bbox must sit at or below the first pixel of the actual visual.
   - The bbox should tightly surround just the visual element with a small margin.
4. For numeric/calculation questions ("What is 24 ÷ 6?"), use short_answer with only
   the correct answer — do NOT invent wrong options.
5. For multiple choice, list ALL provided answer options including the correct one.
6. Write explanations that help students understand why they got it wrong.
7. Do NOT skip questions even if they look simple.

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
- Always write a grading_rubric"""


def _get_anthropic_client():
    import anthropic
    # PDF classification can take 60-90s for large worksheets — raise the
    # default httpx timeout (30s) so the request isn't killed mid-flight.
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=120.0,
    )


def classify_worksheet_questions(extracted_pages, existing_topics, existing_levels):
    """
    Send page screenshots to Claude and get structured questions with image bboxes.
    """
    client = _get_anthropic_client()

    topic_names = ', '.join(t['name'] for t in existing_topics) if existing_topics else 'None yet'
    level_names = ', '.join(
        f"Year {l['level_number']}" for l in existing_levels if l['level_number'] <= 12
    ) if existing_levels else 'Year 1–8'

    system = (
        WORKSHEET_SYSTEM_PROMPT
        + f"\n\nExisting topics in the system: {topic_names}"
        + f"\nAvailable year levels: {level_names}"
        + "\nMap to existing topics where possible."
    )

    content_blocks = [{
        "type": "text",
        "text": (
            f"This is a {extracted_pages['page_count']}-page homework worksheet. "
            "I'm sending each page as a screenshot. Please extract all questions "
            "using the classify_worksheet_questions tool."
        ),
    }]

    for page in extracted_pages['pages'][:20]:  # cap at 20 pages
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
                "text": (
                    f"[Page {page['page_num']} — {page['screenshot_w']}×{page['screenshot_h']} px. "
                    f"image_bbox coordinates are in this pixel space. "
                    f"Text: {page['text'][:600]}]"
                ),
            })

    content_blocks.append({
        "type": "text",
        "text": (
            "Extract ALL questions. For each question with a shape, diagram, graph, table, "
            "ruler, or number line: set has_image=true and provide image_bbox [left, top, right, bottom] "
            "in the page screenshot's pixel coordinates. "
            "Crop ONLY the visual — not the question text or answer options. "
            "Use the classify_worksheet_questions tool now."
        ),
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=system,
        tools=[WORKSHEET_CLASSIFICATION_TOOL],
        messages=[{"role": "user", "content": content_blocks}],
    )

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
        raise ValueError("AI did not return structured question data. Please try again.")

    result['usage'] = {
        'input_tokens': response.usage.input_tokens,
        'output_tokens': response.usage.output_tokens,
        'total_tokens': response.usage.input_tokens + response.usage.output_tokens,
    }

    return result


# ---------------------------------------------------------------------------
# Image rendering: PyMuPDF clip — render region directly from PDF vectors
# ---------------------------------------------------------------------------

def render_question_images(doc, extracted_pages, classified_result):
    """
    For every question where has_image=True:
      1. Convert the bbox from screenshot pixel space → PDF point space.
      2. Call page.get_pixmap(clip=rect, dpi=150) to render that region
         directly from the PDF — clean vector output, no JPEG artefacts.
      3. Store as PNG base64 in extracted_images.

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

            # Bbox in screenshot pixel space (Claude's coordinates)
            px0, py0, px1, py1 = [float(v) for v in bbox]

            # Add padding in screenshot space before converting.
            # Do NOT expand the top edge — that risks pulling in headers/question text
            # sitting above the diagram. Only pad sides and bottom.
            side_pad_px = 12
            bottom_pad_px = 12
            px0 = max(0, px0 - side_pad_px)
            # py0 intentionally unchanged — top stays exactly where Claude placed it
            px1 = min(ss_w, px1 + side_pad_px)
            py1 = min(ss_h, py1 + bottom_pad_px)

            # Convert to PDF points
            pt0 = px0 * scale_x
            pt1 = py0 * scale_y
            pt2 = px1 * scale_x
            pt3 = py1 * scale_y

            # Clamp to page bounds
            pt0 = max(0, pt0)
            pt1 = max(0, pt1)
            pt2 = min(pdf_w, pt2)
            pt3 = min(pdf_h, pt3)

            if pt2 <= pt0 or pt3 <= pt1:
                logger.warning(f'Q{idx+1}: degenerate clip rect — skipping')
                continue

            clip_rect = fitz.Rect(pt0, pt1, pt2, pt3)
            fitz_page = doc[page_num - 1]

            # Render ONLY this region directly from PDF vectors at 150 DPI
            pix = fitz_page.get_pixmap(clip=clip_rect, dpi=SCREENSHOT_DPI)
            img_bytes = pix.tobytes('png')
            img_b64 = base64.b64encode(img_bytes).decode('utf-8')

            ref = f'worksheet_img_q{idx+1}_p{page_num}.png'
            extracted_images[ref] = img_b64
            q['image_ref'] = ref

            logger.info(
                f'Q{idx+1}: rendered from PDF — page {page_num}, '
                f'clip=({pt0:.1f},{pt1:.1f},{pt2:.1f},{pt3:.1f}) pts, '
                f'output={pix.width}×{pix.height}px → {ref}'
            )

        except Exception as e:
            logger.exception(f'Q{idx+1}: image render failed — {e}')

    classified_result['questions'] = questions
    return classified_result, extracted_images


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def extract_and_classify_worksheet(pdf_file, existing_topics, existing_levels):
    """
    Full pipeline: PDF → page screenshots → AI classify → render image regions.

    Keeps the fitz.Document open throughout so we can render clips from
    the original PDF vectors rather than cropping JPEG screenshots.

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
        # Step 1: render pages + collect text
        extracted_pages = extract_worksheet_pages(doc)

        # Step 2: AI classification (gets question text, type, answers, image bboxes)
        result = classify_worksheet_questions(extracted_pages, existing_topics, existing_levels)

        for q in result.get('questions', []):
            q.setdefault('include', True)

        # Step 3: render image regions from PDF vectors (not screenshot crops)
        result, extracted_images = render_question_images(doc, extracted_pages, result)

    finally:
        doc.close()

    return {
        'result': result,
        'extracted_images': extracted_images,
        'page_count': extracted_pages['page_count'],
    }
