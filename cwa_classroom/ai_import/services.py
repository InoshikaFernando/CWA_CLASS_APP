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

# A photographic / painted illustration (a clip-art header, a scanned photo, a
# decorative drawing) is continuous-tone: it fills its frame edge-to-edge with
# many subtly-different colours and almost no pure-white background. A maths
# figure — a line diagram, chart, number line, geometry drawing — is the
# opposite: it sits on white with a handful of flat colours. These two knobs
# separate the former from the latter so a decorative illustration is never
# attached in place of a question's real diagram. Tune via env if needed.
PHOTO_MAX_WHITE_FRACTION = float(os.environ.get('AI_IMPORT_PHOTO_MAX_WHITE', '0.55'))
PHOTO_MIN_DISTINCT_COLOURS = int(os.environ.get('AI_IMPORT_PHOTO_MIN_COLOURS', '180'))


def _looks_photographic(img_bytes):
    """Best-effort guess: is this embedded image a decorative photo/illustration
    rather than a maths line-figure?

    Line diagrams, charts and geometry drawings sit on a white page with a few
    flat colours; a photographic or painted illustration fills the frame with
    continuous tone and little pure white. We downsample to a tiny thumbnail and
    flag an image as photographic only when it is BOTH light on white AND rich in
    distinct colours — so a colourful bar chart (flat fills on white) or a shaded
    diagram (few colours) is spared, while a full-bleed illustration is caught.

    Returns False on any decode error (never fatal — an unknown image is treated
    as a normal figure, exactly as before this check existed).
    """
    try:
        import io

        from PIL import Image

        im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        im = im.resize((64, 64))
        px = list(im.getdata())
        if not px:
            return False
        white = sum(1 for r, g, b in px if r >= 235 and g >= 235 and b >= 235)
        white_fraction = white / len(px)
        # Quantise to 4 bits/channel so near-identical tones collapse together;
        # a continuous-tone photo still leaves hundreds of buckets, flat art a few.
        distinct = len({(r >> 4, g >> 4, b >> 4) for r, g, b in px})
        return (white_fraction < PHOTO_MAX_WHITE_FRACTION
                and distinct >= PHOTO_MIN_DISTINCT_COLOURS)
    except Exception:
        return False


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
        page_area = pw * ph
        # A near-full-page rectangle is a page border / background panel, not a
        # figure. Left in the input it BRIDGES otherwise-separate diagrams, so
        # cluster_drawings merges the whole page into one blob that the >80% filter
        # below then discards — losing every figure on the page (a grid of labelled
        # triangles came back with zero regions). Drop those border strokes first,
        # then cluster only the real content. On a page with no such border this is
        # a no-op (content == all drawings), so existing pages are unaffected.
        content = [
            d for d in page.get_drawings()
            if d.get('rect') is not None
            and (d['rect'].width * d['rect'].height) / page_area <= 0.80
        ]
        clusters = (page.cluster_drawings(drawings=content)
                    if content else page.cluster_drawings())
        regions = []
        for r in clusters:
            w, h = r.width, r.height
            area_frac = (w * h) / page_area
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

def _embedded_image_bbox_pct(page, xref):
    """Bounding box (percent of page) of an embedded image's placement(s).

    The classifier's hardest failure mode is a page holding several near-identical
    figures (e.g. a 2x2 grid of angle diagrams): given only bare refs it guesses
    which embedded image goes with which question and often picks the wrong one.
    Surfacing each image's position lets it map a question to the figure sitting at
    the matching spot on the page instead. Returns ``[x0, y0, x1, y1]`` in percent
    (the union when an image is placed more than once), or ``None`` when PyMuPDF
    can't locate the image — best-effort, never fatal.
    """
    try:
        pw, ph = page.rect.width, page.rect.height
        if pw <= 0 or ph <= 0:
            return None
        rects = page.get_image_rects(xref)
        if not rects:
            return None
        x0 = min(r.x0 for r in rects)
        y0 = min(r.y0 for r in rects)
        x1 = max(r.x1 for r in rects)
        y1 = max(r.y1 for r in rects)
        return [
            round(x0 / pw * 100, 1), round(y0 / ph * 100, 1),
            round(x1 / pw * 100, 1), round(y1 / ph * 100, 1),
        ]
    except Exception:
        return None


def _position_hint(cx, cy):
    """Human-readable region of a page for a centre point (cx, cy) in percent.

    Turns raw coordinates into an anchor the classifier can line up against a
    question's own position, e.g. "top-left", "bottom-right", "centre".
    """
    vert = 'top' if cy < 45 else ('bottom' if cy > 55 else 'middle')
    horiz = 'left' if cx < 45 else ('right' if cx > 55 else 'centre')
    if vert == 'middle' and horiz == 'centre':
        return 'centre'
    if vert == 'middle':
        return horiz
    if horiz == 'centre':
        return vert
    return f'{vert}-{horiz}'


def _embedded_image_label(ref, page_num, bbox_pct, photo_like=False):
    """Build the descriptive text block that accompanies an embedded image.

    Without position the model can only tell look-alike figures apart by guessing;
    with it, it can map each question to the image in the matching region. Small
    images are flagged as probable decorative markers (angle arcs, right-angle
    squares), and continuous-tone photos / illustrations are flagged as probable
    decoration, so the model doesn't attach one in place of the real diagram.
    """
    photo_note = (
        "; looks like a photo / decorative illustration, not a maths line-figure - "
        "do NOT attach unless the question genuinely depends on interpreting a "
        "photograph or picture"
    )
    if not bbox_pct:
        label = f"[Embedded image: {ref}"
        if photo_like:
            label += photo_note
        return label + "]"
    x0, y0, x1, y1 = bbox_pct
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = x1 - x0, y1 - y0
    label = (
        f"[Embedded image: {ref} — on page {page_num} at "
        f"x {x0:.0f}-{x1:.0f}%, y {y0:.0f}-{y1:.0f}% "
        f"({_position_hint(cx, cy)}; {w:.0f}%x{h:.0f}% of the page)"
    )
    if w < 12 and h < 8:
        label += "; small - likely a decorative marker (arc / right-angle), not a full figure"
    elif w >= 85 and h >= 85:
        label += "; covers the whole page - a scanned page / background, not a single question's figure"
    elif photo_like:
        label += photo_note
    return label + "]"


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


def extract_pdf_content(pdf_file, page_selection=None):
    """
    Extract text and images from a PDF file using PyMuPDF.

    Args:
        pdf_file: Django UploadedFile or file-like object
        page_selection: the teacher's print-dialog style page spec ("2-7, 9");
            blank/None extracts every page. See ``worksheets/page_selection.py``.
            Only the selected pages are read at all, so skipping a cover sheet or
            a marking scheme costs no screenshots and no AI tokens. Page numbers
            stay ABSOLUTE, keeping image refs and bboxes valid on a partial run.

    Returns:
        {
            'pages': [
                {'page_num': int, 'text': str, 'images': [{'ref': str, 'base64': str, 'ext': str}]}
            ],
            'page_count': int,        # pages actually extracted (what gets billed)
            'total_page_count': int,  # pages in the PDF
            'page_selection': {...},  # what was read / left out, for the preview
            'all_text': str,  # concatenated text for AI
        }
    """
    import fitz  # PyMuPDF

    from worksheets.page_selection import parse_page_selection, selection_summary

    pdf_bytes = pdf_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')

    total_pages = len(doc)
    selected = parse_page_selection(page_selection, total_pages)
    summary = selection_summary(page_selection, selected, total_pages)

    pages = []
    all_text_parts = []

    for page_num in (p - 1 for p in selected):
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
                    # Where this image sits on the page — lets the classifier map a
                    # question to the figure in the matching region instead of
                    # guessing between look-alike diagrams. May be None.
                    'bbox_pct': _embedded_image_bbox_pct(page, xref),
                    # Whether it looks like a decorative photo/illustration rather
                    # than a maths line-figure — surfaced to the model so it isn't
                    # attached in place of a question's real diagram.
                    'photo_like': _looks_photographic(img_bytes),
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
        'total_page_count': total_pages,
        'page_selection': summary,
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
      image refs — never full-page screenshots. Pick the RIGHT ref by POSITION (see
      MATCHING THE RIGHT IMAGE below), not by how the figure looks.
   b. If the visual is DRAWN into the page and has no embedded image reference (most shapes,
      geometry figures and number lines are like this), leave image_ref null and instead set
      image_page to the page it is on and image_box to its bounding box as percentages of that
      page (see the image_box field description). Box THIS question's own figure tightly —
      never a neighbouring question's figure, the question text, or the answer options.
   Do NOT invent or reuse an embedded image_ref that does not actually depict this question's
   visual — if no embedded image matches but a visual is genuinely needed, use approach (b).
   If a question has no visual, leave image_ref, image_page, and image_box all null.
4. Do NOT embed table/chart data as text in the question — keep question_text concise and
   reference the image instead when the question depends on a visual.
5. Set source_page on EVERY question to the 1-based page number it appears on (the page whose
   screenshot shows it). This is separate from image_page — source_page is always the question's
   own page and is required even for text-only questions that carry no figure, while image_page
   is only for a drawn figure's bounding box. The answer verifier uses it to pull up the right
   page, and the review editor opens the crop tool on it.

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
- BUT when the question TEXT itself explicitly points at a figure it depends on — "the diagram
  shows…", "the plan of…", "this shape", "the shape below", "the graph/table/spinner shown",
  "use the diagram", or any answer that cannot be worked out without seeing it (e.g. "find the area
  of this shape", "what is the shaded angle shown") — you MUST attach that figure: an embedded
  image_ref if one matches, otherwise image_page + image_box for the drawn figure. Do NOT leave such
  a question imageless. This is the ONE case where you must not default to null: the "prefer NO
  image" rule above is for questions whose text does NOT reference a figure. If the referenced
  figure is drawn into the page (an L-shaped plan, a shape on a grid, a spinner, a number line,
  a data TABLE), box it with image_page + image_box even though it has no embedded image_ref.
  The referenced figure is ALWAYS on the SAME page as the question — set image_page to the
  question's own page (its source_page) and box the figure THERE. NEVER box or attach a figure
  from a different page; if you cannot find the referenced figure on the question's own page,
  leave the question with no image rather than grabbing a figure from elsewhere.
- A page that is a GRID or ROW of small labelled diagrams — e.g. right-angled triangles labelled
  a, b, c, … each drawn with its own side lengths and angles, or a set of shapes/graphs one per
  part — is MANY separate questions, one per diagram, NOT one question. For EACH labelled diagram
  create its own question and attach THAT diagram with image_page + image_box (box just the one
  diagram and its labels, excluding the neighbours). These bare geometry prompts ("Find x", "Find
  the angle θ", "Find all unknown sides and angles") are unanswerable without their triangle, so
  the figure is mandatory — never emit such a question with no image because the page held a whole
  grid of them. The triangles are drawn as vector lines (no embedded image_ref), so you must box
  them with image_page + image_box.

MATCHING THE RIGHT IMAGE TO EACH QUESTION (important — this is the #1 cause of wrong figures):
- Every embedded image is listed with its POSITION on the page: its x/y bounding box in
  percentages plus a region hint like "top-left" or "bottom-right", and its size.
- When a page holds several similar-looking figures (a 2x2 grid of angle diagrams, a row of
  shapes, etc.) do NOT decide which is which from appearance — the diagrams look alike and you
  WILL mismatch them. Map by POSITION: a question's figure sits in the same region of the page
  as that question's number and text, almost always directly below or beside it.
- So: locate where the question's own text/number is on the page, then attach the embedded image
  whose box is in that same region. Question 1 (top-left) → the top-left image; question 4
  (bottom-right) → the bottom-right image; and so on.
- Never attach a figure whose region does not match the question's region. Each distinct figure
  belongs to exactly one question — EXCEPT for a group of consecutive questions that genuinely share
  ONE visual (see GROUP QUESTIONS SHARING ONE IMAGE below).
- Ignore images flagged "small — likely a decorative marker" (angle arcs / right-angle squares)
  and any flagged "covers the whole page" (a scanned page or poster background) when choosing a
  question's figure — neither is that question's diagram. Pick the main figure for the region.
- An image flagged "looks like a photo / decorative illustration" is almost never a maths
  question's figure (it is clip-art, a header picture, or a decorative drawing). Do NOT attach it
  in place of a real diagram — if the question needs a diagram that is DRAWN into the page (a
  shape, geometry figure, number line, angle-turn figure), use approach (b) with image_page +
  image_box instead. Attach a photo-flagged image ONLY when the question genuinely depends on
  interpreting that photograph / picture.
- If two candidate images share a region, prefer the larger one (the full diagram) and the one
  directly adjacent to the question text.

GROUP QUESTIONS SHARING ONE IMAGE (important):
- Sometimes several CONSECUTIVE questions all refer to the SAME single visual — e.g. a heading like
  "Use the diagram below to answer questions 3–6", or a graph/table/figure followed by several
  questions about it. Treat these as an image group.
- Attach the shared visual to the FIRST question of the group only, the normal way (image_ref if it
  is an embedded image, otherwise image_page + image_box). That first question must have
  shares_image_with_previous null/false.
- For every FOLLOWING question in the same group, set shares_image_with_previous to true and leave
  image_ref, image_page and image_box all null — the shared image is carried over from the previous
  question automatically. Do NOT re-box or re-reference the same figure on each question.
- This applies ONLY to a consecutive run of questions on the SAME visual. Do NOT set
  shares_image_with_previous for scattered questions that merely happen to look alike or sit near
  similar figures — only for a true shared-image group.

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

QUESTION NUMBERING (important):
- question_text is the QUESTION ONLY. Do NOT copy the worksheet's question number or section
  label into it. Strip any leading enumeration such as "Question 5", "Question 5 e)", "Q154",
  "5.", "5)", "a)", "(iii)", "PART C:", "Section B", or "Exercise 3:" — start question_text at
  the first word of the actual question.
- Keep the shared instruction/stem (see SPLIT MULTI-PART) — remove only the numbering/label,
  never the wording a student needs to answer.

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
  use question_type "short_answer". Do NOT generate wrong answers. List EVERY form a student could
  reasonably type as a SEPARATE answer, each with is_correct=true (the auto-grader accepts any
  ticked answer). In particular, when the answer carries a unit, include BOTH the bare number and
  the number-with-unit, e.g. "60 months" AND "60"; "$4.50" AND "4.50"; "3/4" AND "0.75". Do NOT add
  forms that are merely spacing/comma/hyphen variants — the grader already ignores those.
- If the correct answer contains TEXT or WORDS (e.g. "Day 3 had the most sales", "True", "Red"),
  use question_type "multiple_choice" and generate 3-4 plausible wrong answers alongside the correct one.
- For true/false questions, use "true_false" type.
- For fill-in-the-blank, use "fill_blank" type. Mark EVERY gap in question_text with three
  underscores "___" — that is how the app finds the gaps and lays an input into each one — and
  keep the rest of the sentence exactly as printed. Give the answers as ONE answer entry whose
  text lists the gaps in order separated by "; " (e.g. "15; live"), or as one answer entry per
  gap in gap order. Where a gap accepts more than one wording, separate the alternatives with
  "|" inside that gap's value (e.g. "15; live|survive"). A sentence with several gaps must NOT
  be typed "short_answer" — one box for a whole sentence cannot be graded.
- If the question shows a BLANK Cartesian plane (numbered x/y axes, four quadrants) and asks the
  student to PLOT given coordinates, use "plot_points". Put the visible axis range in
  plane_spec.bounds, set mode "points", and put the coordinates to plot in plane_spec.target.points
  (signed integers, e.g. [[3,-2],[1,4]]). Do NOT generate answers.
- If it asks the student to PLOT points AND JOIN them into a line/shape, use "plot_line": mode
  "segments" and plane_spec.target.segments as a list of {"x1","y1","x2","y2"} for the joined line
  (consecutive points). Do NOT generate answers.
- If a point (or points) is ALREADY PLOTTED on the plane and the student must WRITE the coordinates,
  use "identify_coords": mode "points", put the plotted point(s) in BOTH plane_spec.given_points
  (so they are drawn) and plane_spec.target.points (the answer). Do NOT generate answers.
- If the question shows a PRE-DRAWN line graph (e.g. distance-vs-time) and asks the student to READ a
  value off it, use "read_graph". Set numeric_answer to the value to read, answer_tolerance to a
  sensible ± band, and answer_unit to the axis unit. Keep the graph image (set image_page/image_box
  so the original graph is attached). Only add graph_spec if you can read the plotted series points
  confidently; otherwise omit it. Do NOT generate answers.
- If the student must MEASURE a drawn figure and write the value — read an ANGLE with a protractor, a
  length with a ruler, or a value off a marked scale/dial — use "measure". Set numeric_answer to the
  true value, answer_tolerance to a sensible ± band (e.g. 2 for an angle), and answer_unit to the unit
  ("°" for angles, "cm"/"mm" for lengths). For an ANGLE the app draws a true-to-scale figure, so do NOT
  attach an image; for a length/scale the pupil measures the picture, so keep it. Do NOT generate answers.
- If the question shows (or asks the student to draw/use) a horizontal NUMBER LINE and the task is to
  MARK a value on it or READ the value an arrow points to, use "number_line" and fill number_line_spec.
  Set min/max to the scale's end values and step to the tick interval (usually 1). Use mode "mark" when
  the student must place/mark value(s) ("mark 5 on the number line", "draw a number line from -3 to 7
  and show 2") — put the value(s) in target. Use mode "read" when an arrow is already drawn and the
  student reads its value — put the marked position(s) in given. Every target/given value must land on a
  tick. The app draws the line, so do NOT attach an image. Do NOT generate answers.

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

ANGLE-RELATIONSHIP QUESTIONS — DO NOT NAME THE PAIR YOURSELF (important):
When a figure shows two parallel lines cut by a transversal and asks you to LABEL a marked
pair of angles (corresponding, alternate interior / alt. int., alternate exterior / alt. ext.,
or consecutive interior / co-interior), you are UNRELIABLE at naming it directly — so DON'T.
Instead PERCEIVE the geometry and let the app compute the answer:
- Keep question_type "multiple_choice" and still list the options shown (all four standard
  labels when present). You do NOT need to tick the correct one — the app derives it from the
  spec below and overrides is_correct.
- Fill angle_relationship_spec (see its schema): the TWO parallel lines, the SINGLE transversal,
  and the printed position of each marked angle's letter (x, y, ...), all as page-percentage
  [x, y] coordinates.
- Read those positions CAREFULLY off the figure — the whole answer hinges on whether each letter
  sits BETWEEN the two lines (interior) or OUTSIDE them (exterior), and on which SIDE of the
  transversal it lies. Do not approximate loosely; a letter above the top line or below the
  bottom line is exterior.
- If the figure has MORE THAN ONE transversal, or the two marked angles are not on the same
  transversal cutting the same pair of parallel lines, the standard labels do NOT apply: leave
  angle_relationship_spec null, set needs_review=true with a short review_reason, and do not
  force a label.

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
- The explanation must be CLEAN and FINAL: do your working silently and write only the
  verified conclusion. Never leave scratch work, self-corrections, or "wait, let me redo
  this" notes in it. For multiple choice, the option you mark is_correct MUST be the exact
  option the explanation concludes is right — if the explanation ends up favouring a
  different option, change which option is ticked, not the explanation.
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
                            "enum": ["multiple_choice", "true_false", "short_answer", "fill_blank", "calculation", "column_operation", "long_division", "plot_points", "plot_line", "identify_coords", "read_graph", "measure", "number_line"],
                        },
                        "plane_spec": {
                            "type": "object",
                            "description": (
                                "For plot_points / plot_line / identify_coords only — a signed Cartesian "
                                "plane. bounds = the visible axis range; mode 'points' for plotting/identifying "
                                "dots, 'segments' for a line/shape to join; target = the correct answer "
                                "(points OR segments) in SIGNED integer coords; given_points = points already "
                                "drawn on the plane (used by identify_coords so the student reads them)."
                            ),
                            "properties": {
                                "bounds": {
                                    "type": "object",
                                    "properties": {
                                        "xmin": {"type": "integer"}, "xmax": {"type": "integer"},
                                        "ymin": {"type": "integer"}, "ymax": {"type": "integer"},
                                    },
                                },
                                "mode": {"type": "string", "enum": ["points", "segments"]},
                                "given_points": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}},
                                "target": {"type": "object"},
                            },
                        },
                        "graph_spec": {
                            "type": "object",
                            "description": (
                                "For read_graph only and OPTIONAL — a clean re-draw of the line graph "
                                "(x_axis/y_axis with label, unit, min, max, step; series with points). "
                                "Only supply when you can read the series points confidently; otherwise omit "
                                "it and the original graph image is kept instead."
                            ),
                        },
                        "number_line_spec": {
                            "type": "object",
                            "description": (
                                "For number_line only — a horizontal number line. min/max = the "
                                "scale's end values; step = the tick interval (default 1); mode 'mark' "
                                "(app draws the blank scale, student marks value(s)) or 'read' (app "
                                "draws marker arrow(s) at 'given' positions, student types the value(s)); "
                                "target = correct value(s) to mark/read (each landing on a tick); given = "
                                "value(s) already marked with an arrow (read mode). The app draws the line."
                            ),
                        },
                        "angle_relationship_spec": {
                            "type": "object",
                            "description": (
                                "For 'label the marked pair of angles' questions ONLY (corresponding / "
                                "alternate interior / alternate exterior / consecutive interior). Do NOT "
                                "name the pair yourself — the app computes the correct option from this "
                                "geometry and overrides is_correct. Coordinates are page percentages "
                                "[x, y] (0-100, origin top-left). lines = the TWO parallel lines, each "
                                "{p1, p2}; transversal = the SINGLE crossing line {p1, p2}; angles = the "
                                "two MARKED angles, each {label, pos} where pos is where that angle's "
                                "letter is printed. Leave null (and set needs_review) when the figure has "
                                "more than one transversal or the two marked angles are not on the same "
                                "transversal cutting the same pair of lines."
                            ),
                            "properties": {
                                "lines": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "p1": {"type": "array", "items": {"type": "number"}},
                                            "p2": {"type": "array", "items": {"type": "number"}},
                                        },
                                    },
                                },
                                "transversal": {
                                    "type": "object",
                                    "properties": {
                                        "p1": {"type": "array", "items": {"type": "number"}},
                                        "p2": {"type": "array", "items": {"type": "number"}},
                                    },
                                },
                                "angles": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {"type": "string"},
                                            "pos": {"type": "array", "items": {"type": "number"}},
                                        },
                                    },
                                },
                            },
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
                            "description": "For read_graph and measure: unit shown after the answer box, e.g. '°', 'cm', 'km', 'min'.",
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
                        "needs_review": {
                            "type": "boolean",
                            "description": (
                                "Set true when this question's answer could NOT be determined with "
                                "confidence and a teacher should double-check it before use — e.g. an "
                                "angle-relationship figure with multiple transversals, an unreadable or "
                                "ambiguous diagram, or a pair with no standard name. Prefer flagging over "
                                "guessing."
                            ),
                        },
                        "review_reason": {
                            "type": "string",
                            "description": "When needs_review is true, one short sentence on what is uncertain.",
                        },
                        "source_page": {
                            "type": "integer",
                            "description": "1-based page number on which this question appears (the page whose screenshot shows it). Set this for EVERY question — it lets the answer verifier pull up the exact page.",
                        },
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
                        "shares_image_with_previous": {
                            "type": "boolean",
                            "description": (
                                "Set true ONLY when this question belongs to a GROUP that shares ONE "
                                "visual with the question IMMEDIATELY BEFORE it — e.g. 'Use the diagram "
                                "below to answer questions 3–6', or several sub-questions hanging off a "
                                "single shared graph/table/figure. When true, leave image_ref, image_page "
                                "and image_box all null: the shared image is carried over from the "
                                "previous question automatically. The FIRST question in the group still "
                                "carries the image normally (image_ref OR image_page+image_box) and must "
                                "have shares_image_with_previous false/null. Only use this for a "
                                "consecutive run of questions on the SAME shared visual — never for "
                                "unrelated questions that merely happen to look similar."
                            ),
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
                    "required": ["question_text", "question_type", "difficulty", "answers", "source_page"],
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
                "text": _embedded_image_label(
                    img['ref'], page['page_num'], img.get('bbox_pct'),
                    img.get('photo_like', False)),
            })

    content_blocks.append({
        "type": "text",
        "text": "Please extract and classify ALL questions from these pages. Include any context tables, data, or diagrams that belong with each question in the question_text. Use the classify_questions tool to return structured data.",
    })

    # Stream the request so a long (multi-page) generation doesn't trip the SDK
    # read timeout (anthropic.APITimeoutError). get_final_message() returns the
    # same Message a non-streaming create() would.
    #
    # Default to Opus (far stronger arithmetic and vision — it reliably solves the
    # missing-digit / worked-solution questions that Sonnet 4 guessed wrong, and
    # reads diagrams more reliably) with adaptive thinking so it works each
    # computation out before answering. Override the model via AI_IMPORT_MODEL
    # (must be a model that supports adaptive thinking — Opus/Sonnet 4.6+).
    with client.messages.stream(
        model=os.environ.get('AI_IMPORT_MODEL', 'claude-opus-5'),
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
        # A safety refusal (stop_reason "refusal") returns no tool_use and no
        # parseable text — surface it clearly instead of the generic message so a
        # blocked document is distinguishable from a parse failure.
        if getattr(response, 'stop_reason', None) == 'refusal':
            raise ValueError(
                "The AI declined to process this document (content safety). "
                "Please review the PDF and try again."
            )
        raise ValueError("AI did not return structured question data. Please try again.")

    result['usage'] = {
        'input_tokens': response.usage.input_tokens,
        'output_tokens': response.usage.output_tokens,
        'total_tokens': response.usage.input_tokens + response.usage.output_tokens,
    }
    return result


def _apply_computed_angle_answer(q):
    """Derive an angle-relationship question's correct option from its geometry.

    For "label the marked pair of angles" questions the model fills
    ``angle_relationship_spec`` (line/transversal/label positions) but does NOT
    name the pair — naming proved unreliable. Here we compute the label
    deterministically, tick the matching multiple-choice option (overriding the
    model's is_correct guesses), and rewrite the explanation so it can never
    contradict the answer.

    Anything the geometry can't resolve — a malformed spec, an ambiguous mark, a
    multi-transversal figure the model flagged, or a pair with no standard name —
    sets ``needs_review`` so the teacher checks it in preview rather than a wrong
    answer being saved silently. Mutates ``q`` in place; no-op when there is no
    spec.
    """
    spec = q.get('angle_relationship_spec')
    if not spec:
        return

    from maths.angle_relationship import (
        build_explanation, canonical_label, classify_angle_pair,
    )

    try:
        result = classify_angle_pair(spec)
    except ValueError as exc:
        q['needs_review'] = True
        q['review_reason'] = f'angle diagram could not be read: {exc}'
        return

    if result['needs_review']:
        q['needs_review'] = True
        q['review_reason'] = result['reason']
        return

    label = result['label']
    answers = q.get('answers') or []
    matched = False
    for ans in answers:
        is_match = canonical_label(ans.get('text')) == label
        ans['is_correct'] = is_match
        matched = matched or is_match

    if not matched:
        # The computed answer isn't among the extracted options — add it rather
        # than lose it, and flag so the teacher can fix the option list.
        answers.append({'text': label, 'is_correct': True})
        q['answers'] = answers
        q['needs_review'] = True
        q['review_reason'] = (
            f'computed answer "{label}" was not among the extracted options; '
            'added it — please verify the options.'
        )

    explanation = build_explanation(result)
    if explanation:
        q['explanation'] = explanation


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
    # Page labels are absolute, so quote the PDF's real length even when only
    # some of its pages were selected for extraction.
    total = (extracted_content.get('total_page_count')
             or extracted_content.get('page_count', len(pages)))
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

        # Stamp each batch's questions with THAT batch's top-level defaults before
        # merging. Each batch is classified independently and the model only sets
        # per-question fields when they differ from its (per-batch) default, so
        # without this a later batch's questions would inherit the first batch's
        # year/subject/strand/topic at save time and be mis-classified.
        for q in result.get('questions', []):
            for field in ('year_level', 'subject', 'strand', 'topic'):
                if not q.get(field) and result.get(field) is not None:
                    q[field] = result[field]

        if merged is None:
            merged = result
        else:
            merged.setdefault('questions', []).extend(result.get('questions', []))

    if merged is None:
        raise ValueError("AI did not return structured question data. Please try again.")

    # Safety nets: strip any leading question-number/section label the model copied
    # in, then ensure a missing left operand renders as a blank. Then, for
    # angle-relationship figures, DERIVE the correct option from the model's
    # perceived geometry instead of trusting the label it guessed.
    for q in merged.get('questions', []):
        q['question_text'] = _normalize_answer_blank(
            _strip_question_label(q.get('question_text', ''))
        )
        _apply_computed_angle_answer(q)

    merged['usage'] = {
        'input_tokens': in_tok,
        'output_tokens': out_tok,
        'total_tokens': in_tok + out_tok,
    }

    # Second opinion: an independent GPT verifier re-examines each question
    # against its source-page screenshot — validating Claude's classification and
    # answer and checking the transcription — and flags disagreements
    # needs_review for the teacher. Best-effort and self-gating: a no-op when
    # OPENAI_API_KEY isn't configured, and it never fails the import. Kept out of
    # merged['usage'] (the Claude token ledger) because GPT is priced
    # separately; reported under merged['verification'], from where
    # ai_import.tasks records it as its own OpenAI row in the usage ledger so it
    # reaches the finance dashboard (CPP-382).
    page_images = {
        p['page_num']: p['screenshot']
        for p in pages
        if p.get('page_num') is not None and p.get('screenshot')
    }
    from .verification import verify_answers, flag_visual_comparisons

    # Deterministic guard first (no API): "which figure is larger / are they
    # equal" questions are routed to review unconditionally. Both Claude and the
    # GPT verifier read these coarse figures the same wrong way, so they agree on
    # a wrong answer and the disagreement-based verifier below never catches it.
    # Running this first also means those questions are already flagged, so the
    # paid GPT pass skips them.
    comparison_flags = flag_visual_comparisons(merged.get('questions', []))

    verification = verify_answers(merged.get('questions', []), page_images=page_images)
    if verification is not None:
        verification['comparison_flags'] = comparison_flags
        merged['verification'] = verification
    elif comparison_flags:
        # Verifier disabled (no OpenAI key) but the deterministic guard still ran.
        merged['verification'] = {'comparison_flags': comparison_flags}

    return merged


# ---------------------------------------------------------------------------
# Figure cropping (drawn diagrams with no embedded raster image)
# ---------------------------------------------------------------------------

# Padding (percent of page, per side) added around a detected figure so axis
# labels / numbers sitting just outside the vector drawing aren't clipped.
FIGURE_CROP_PAD_PCT = float(os.environ.get('AI_IMPORT_FIGURE_CROP_PAD', '2.0'))

# DPI for re-rendering a figure crop straight from the PDF vectors. The page
# screenshot is only 150 DPI (kept small for the vision request); rendering the
# final crop from the PDF at a higher DPI gives a noticeably sharper image. Tune
# via AI_IMPORT_FIGURE_DPI. A single small region at 300 DPI is cheap on memory.
FIGURE_RENDER_DPI = int(os.environ.get('AI_IMPORT_FIGURE_DPI', '300'))


def _render_pdf_region(doc, page_num, box_pct, dpi=None):
    """Render a percent-of-page region straight from the PDF vectors as PNG bytes.

    Sharper than cropping the 150-DPI screenshot. ``box_pct`` is
    ``[lo_x, lo_y, hi_x, hi_y]`` in percent of the page. Returns PNG bytes, or
    ``None`` on any failure so the caller can fall back to the screenshot crop.
    """
    try:
        import fitz

        page = doc[page_num - 1]
        pw, ph = page.rect.width, page.rect.height
        lo_x, lo_y, hi_x, hi_y = box_pct
        clip = fitz.Rect(lo_x / 100 * pw, lo_y / 100 * ph,
                         hi_x / 100 * pw, hi_y / 100 * ph)
        if clip.width < 1 or clip.height < 1:
            return None
        pix = page.get_pixmap(clip=clip, dpi=dpi or FIGURE_RENDER_DPI)
        return pix.tobytes('png')
    except Exception:
        return None


def _box_has_drawing(doc, page_num, box_pct):
    """Whether any vector drawing on the page overlaps the percent-of-page box.

    Unlike ``figure_regions`` (which drops page-sized clusters >80% area), this
    sees *all* drawings, so a large diagram that was filtered out of the regions
    list is still detected. ``box_pct`` is ``[lo_x, lo_y, hi_x, hi_y]`` in percent.
    Returns True / False, or None when it can't be determined (no PDF / error) so
    the caller can stay conservative and keep the crop.
    """
    if doc is None:
        return None
    try:
        import fitz

        page = doc[page_num - 1]
        pw, ph = page.rect.width, page.rect.height
        lo_x, lo_y, hi_x, hi_y = box_pct
        box = fitz.Rect(lo_x / 100 * pw, lo_y / 100 * ph,
                        hi_x / 100 * pw, hi_y / 100 * ph)
        for d in page.get_drawings():
            r = d.get('rect')
            if r and fitz.Rect(r).intersects(box):
                return True
        return False
    except Exception:
        return None


def _boxes_overlap(a, b):
    """True if two [x1, y1, x2, y2] boxes share any area."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _box_area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap_area(a, b):
    """Area of the intersection of two [x1, y1, x2, y2] boxes (0 if disjoint)."""
    ox = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    oy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ox * oy


def _snap_box_to_figures(box, regions):
    """Refine an AI figure box to the actual drawn-figure bounds.

    `box` and `regions` entries are [x1, y1, x2, y2] in percent of the page.
    Returns the padded union of the drawing clusters the box is genuinely aligned
    with — this both expands a too-tight box to include the whole figure and
    shrinks a too-loose one back off neighbouring text. If nothing aligns, returns
    `box` unchanged (the model's box is then the only signal we have).

    A region is only unioned in when the box mostly covers it, or it mostly covers
    the box. A region the box merely CLIPS at the edge — typically a neighbouring
    question's figure in a 2x2 grid when the model drew a slightly-too-wide box —
    is left out, so a crop never swallows the question next door.
    """
    box_area = _box_area(box) or 1.0
    overlapping = []
    for r in regions:
        ov = _overlap_area(box, r)
        if ov <= 0:
            continue
        # Aligned when the smaller of {box, region} is at least half-covered by the
        # overlap: box-inside-figure (too tight) and figure-inside-box (too loose /
        # fragment) both pass; an edge-clipped neighbour does not.
        if ov / (min(_box_area(r), box_area) or 1.0) >= 0.5:
            overlapping.append(r)
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
    if _box_area(snapped) < 0.20 * box_area:
        return box
    return snapped


def crop_figure_boxes(extracted_content, result, pdf_bytes=None):
    """Crop drawn figures and register them as images.

    The classifier returns image_page + image_box (percentages of the page) for
    questions whose visual is drawn into the page rather than an embedded raster
    image. For each such question we render the box — preferably straight from the
    PDF vectors at high DPI when ``pdf_bytes`` is supplied, otherwise cropped from
    that page's 150-DPI screenshot — rewrite the question's image_ref to a
    generated filename, and return {ref: base64_png} so the crops join the
    embedded-image pool and save through the normal image path.

    A box that overlaps no detected vector figure and sits on a page with no
    embedded raster image is treated as spurious (the model pointed at plain
    text) and dropped rather than saved as an irrelevant text crop.

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

    doc = None
    if pdf_bytes:
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        except Exception:
            doc = None

    try:
        return _crop_figure_boxes_inner(result, pages, crops, decoded, doc, Image, io)
    finally:
        if doc is not None:
            doc.close()


def _crop_figure_boxes_inner(result, pages, crops, decoded, doc, Image, io):
    # Track the image assigned to the immediately-preceding question so a group of
    # consecutive questions that share ONE visual (e.g. "use the diagram below to
    # answer questions 3–6") reuses that image instead of re-cropping it. prev_image
    # is reset to None the moment a question ends up with no image, so "previous"
    # only ever means the question directly before this one — never a scattered
    # earlier figure.
    prev_image = None
    for idx, q in enumerate(result.get('questions', []), 1):
        shares = bool(q.pop('shares_image_with_previous', False))

        # Explicit group signal, or an unflagged question that boxed essentially the
        # same region as the previous question's crop (a shared figure the model
        # re-boxed instead of flagging) → reuse the previous image verbatim.
        if prev_image is not None and (
                shares or _reuses_prev_figure(q, prev_image)):
            q.pop('image_box', None)
            q.pop('image_page', None)
            q['image_ref'] = prev_image['ref']
            if prev_image.get('page') is not None:
                q['image_page'] = prev_image['page']
            if prev_image.get('bbox_frac') is not None:
                q['image_bbox_frac'] = prev_image['bbox_frac']
            # prev_image is unchanged so the whole group keeps sharing it.
            continue

        _assign_figure_to_question(q, idx, pages, crops, decoded, doc, Image, io)

        if q.get('image_ref'):
            prev_image = {
                'ref': q['image_ref'],
                'page': q.get('image_page'),
                'bbox_frac': q.get('image_bbox_frac'),
            }
        else:
            # No image on this question breaks the run — a following
            # shares_image_with_previous has nothing to carry over.
            prev_image = None

    return crops


def _reuses_prev_figure(q, prev_image):
    """Safety net for group images the model boxed on every question instead of
    setting shares_image_with_previous.

    Returns True only when this question's drawn box sits on the same page as the
    previous question's crop AND overlaps it almost completely (IoU ≥ 0.7) — a
    strong signal it is the SAME shared figure, not a different figure that merely
    sits nearby. Embedded-image refs and cross-page boxes never match here.
    """
    if not prev_image.get('bbox_frac') or prev_image.get('page') is None:
        return False
    box = q.get('image_box')
    page_num = q.get('image_page')
    if not box or page_num is None:
        return False
    try:
        if int(page_num) != int(prev_image['page']):
            return False
        cur = [float(box['x1']) / 100, float(box['y1']) / 100,
               float(box['x2']) / 100, float(box['y2']) / 100]
    except (KeyError, TypeError, ValueError):
        return False
    return _frac_box_iou(cur, prev_image['bbox_frac']) >= 0.7


def _frac_box_iou(a, b):
    """Intersection-over-union of two [x1, y1, x2, y2] boxes (any shared unit)."""
    ax1, ay1 = min(a[0], a[2]), min(a[1], a[3])
    ax2, ay2 = max(a[0], a[2]), max(a[1], a[3])
    bx1, by1 = min(b[0], b[2]), min(b[1], b[3])
    bx2, by2 = max(b[0], b[2]), max(b[1], b[3])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _expand_box_for_clipped_labels(doc, page_num, box_pct,
                                   max_grow=6.0, min_inside=0.35):
    """Grow a crop box just enough to include text labels it clips at the edge.

    A figure crop that slices through an axis number or a shape's side label loses
    information the question needs. Using the PDF's own text layout, any word that
    overlaps the box but is not fully inside it — and is *mostly* inside (at least
    ``min_inside`` of its area), i.e. a label the box clips rather than a
    neighbour's word merely touching the edge — is unioned into the box. Growth is
    capped at ``max_grow`` percent per side, so a run of adjacent text can never
    balloon the crop into the next question. ``box_pct`` and the return value are
    ``[lo_x, lo_y, hi_x, hi_y]`` in percent of the page. Best-effort: returns the
    box unchanged on any failure or when the PDF isn't available.
    """
    if doc is None:
        return box_pct
    try:
        page = doc[int(page_num) - 1]
        pw, ph = page.rect.width, page.rect.height
        if pw <= 0 or ph <= 0:
            return box_pct
        lo_x, lo_y, hi_x, hi_y = box_pct
        # Box and the maximum grown envelope, in absolute (point) coordinates.
        bx0, by0, bx1, by1 = (lo_x / 100 * pw, lo_y / 100 * ph,
                              hi_x / 100 * pw, hi_y / 100 * ph)
        gx0 = max(0.0, lo_x - max_grow) / 100 * pw
        gy0 = max(0.0, lo_y - max_grow) / 100 * ph
        gx1 = min(100.0, hi_x + max_grow) / 100 * pw
        gy1 = min(100.0, hi_y + max_grow) / 100 * ph
        nx0, ny0, nx1, ny1 = bx0, by0, bx1, by1
        for word in page.get_text('words'):
            wx0, wy0, wx1, wy1 = word[0], word[1], word[2], word[3]
            wa = max(0.0, wx1 - wx0) * max(0.0, wy1 - wy0)
            if wa <= 0:
                continue
            inter = (max(0.0, min(bx1, wx1) - max(bx0, wx0))
                     * max(0.0, min(by1, wy1) - max(by0, wy0)))
            if inter <= 0:
                continue                     # word doesn't touch the box
            if inter >= wa - 1e-6:
                continue                     # already fully inside
            if inter / wa < min_inside:
                continue                     # sliver only → a neighbour's word
            # A clipped label: union it in, clamped to the grown envelope.
            nx0 = min(nx0, max(wx0, gx0))
            ny0 = min(ny0, max(wy0, gy0))
            nx1 = max(nx1, min(wx1, gx1))
            ny1 = max(ny1, min(wy1, gy1))
        return [nx0 / pw * 100, ny0 / ph * 100, nx1 / pw * 100, ny1 / ph * 100]
    except Exception:
        return box_pct


def _assign_figure_to_question(q, idx, pages, crops, decoded, doc, Image, io):
    """Resolve one question's own figure: keep an embedded image_ref, or crop the
    drawn image_box into a new image. Mutates ``q`` in place; ``crops`` gains any
    new crop. No-op when the question needs no figure."""
    # An embedded image already covers this question — prefer it (raster
    # fidelity beats a screenshot crop).
    if q.get('image_ref'):
        q.pop('image_page', None)
        q.pop('image_box', None)
        return

    box = q.get('image_box')
    page_num = q.get('image_page')
    # Clear the transient box fields regardless of outcome so they never
    # get persisted on the session / shown in the editor.
    q.pop('image_box', None)
    q.pop('image_page', None)
    if not box or not page_num:
        return

    # A drawn figure lives on the question's OWN page. A box pointing at a
    # different page is a wrong-page grab — e.g. a neighbouring question's chart on
    # another page cropped onto this one (a "table shows…" question ending up with
    # a bar chart from two pages back). Refuse it so a wrong figure is never
    # cropped in; the missing-figure guard then surfaces the question if it needs
    # one. Same-page crops are unaffected. Toggle off with
    # AI_IMPORT_DROP_CROSS_PAGE_CROPS=0.
    if os.environ.get('AI_IMPORT_DROP_CROSS_PAGE_CROPS', '1') != '0':
        source_page = q.get('source_page')
        try:
            if source_page is not None and int(page_num) != int(source_page):
                return
        except (TypeError, ValueError):
            pass

    try:
        page = pages.get(int(page_num))
        x1, y1 = float(box['x1']), float(box['y1'])
        x2, y2 = float(box['x2']), float(box['y2'])
    except (KeyError, TypeError, ValueError):
        return
    if not page or not page.get('screenshot'):
        return

    # Normalise corner order and clamp to the page.
    lo_x, hi_x = sorted((x1, x2))
    lo_y, hi_y = sorted((y1, y2))
    lo_x, hi_x = max(0.0, lo_x), min(100.0, hi_x)
    lo_y, hi_y = max(0.0, lo_y), min(100.0, hi_y)

    # Snap to the actual drawn-figure bounds when we detected vector clusters
    # on the page — corrects boxes that clip the figure or grab adjacent text.
    regions = page.get('figure_regions') or []
    overlapping = [r for r in regions
                   if _boxes_overlap([lo_x, lo_y, hi_x, hi_y], r)]
    if overlapping:
        lo_x, lo_y, hi_x, hi_y = _snap_box_to_figures(
            [lo_x, lo_y, hi_x, hi_y], regions)
    elif not page.get('images'):
        # No detected figure cluster overlaps the box and there's no embedded
        # raster image. The box may still cover a real figure that was filtered
        # out of figure_regions (e.g. a page-sized diagram >80% area), so when
        # the PDF is available confirm against the page's actual drawings and
        # drop only when there is genuinely nothing drawn there (the model
        # pointed at plain text — the "totally irrelevant image" failure mode).
        has_drawing = _box_has_drawing(doc, int(page_num),
                                       [lo_x, lo_y, hi_x, hi_y])
        if has_drawing is False:
            return              # confirmed: no figure here → spurious text crop
        if has_drawing is None and regions:
            # No PDF to check; fall back to the cluster heuristic — figures
            # exist on the page but none overlap the box → treat as spurious.
            return
        # else: a real drawing (incl. large filtered figures) or unknown
        # without regions → keep cropping.

    # Grow the box to swallow any text label it CLIPS at the edge — an axis number,
    # a shape's side length ("23.9 km"), a graph key — so the crop keeps ALL of the
    # figure's information with no half-cut labels. Bounded per side so a run of
    # text can't balloon the crop into the neighbouring question. Toggle off with
    # AI_IMPORT_CROP_INCLUDE_LABELS=0.
    if doc is not None and os.environ.get('AI_IMPORT_CROP_INCLUDE_LABELS', '1') != '0':
        lo_x, lo_y, hi_x, hi_y = _expand_box_for_clipped_labels(
            doc, int(page_num), [lo_x, lo_y, hi_x, hi_y])

    if hi_x - lo_x < 1 or hi_y - lo_y < 1:
        return  # degenerate / empty box

    img_bytes = None
    # Prefer a crisp re-render straight from the PDF vectors at high DPI;
    # falls back to cropping the 150-DPI screenshot when the PDF isn't
    # available or the render fails.
    if doc is not None:
        img_bytes = _render_pdf_region(doc, int(page_num),
                                       [lo_x, lo_y, hi_x, hi_y])
    if img_bytes is None:
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
            img_bytes = buf.getvalue()
        except Exception:
            # A bad box / unreadable screenshot shouldn't sink the whole import.
            return

    ref = f'page{int(page_num)}_figure{idx}.png'
    crops[ref] = base64.b64encode(img_bytes).decode('utf-8')
    q['image_ref'] = ref
    # Crop provenance for the "Adjust image" editor (box was in % of page).
    q['image_page'] = int(page_num)
    q['image_bbox_frac'] = [round(lo_x / 100, 4), round(lo_y / 100, 4),
                            round(hi_x / 100, 4), round(hi_y / 100, 4)]


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
    from maths.blank_grading import count_blanks

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
    # Questions turned into fill-in-the-blank sentences, and the ones that carry
    # blanks but could not be — reported separately from errors: nothing failed,
    # they simply came in as a single box and stayed one.
    blanks_built = 0
    errors = []
    warnings = []

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
        # attached worksheet graphic (division bracket, column grid, blank plane) is
        # just noise. read_graph is the exception — it KEEPS its graph image.
        if q_type in ('column_operation', 'long_division', 'plot_points', 'plot_line',
                      'identify_coords', 'draw_on_grid', 'shape_select', 'number_line'):
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

        # Cartesian-plane fields (plot_points / plot_line / identify_coords).
        plane_spec = None
        if q_type in ('plot_points', 'plot_line', 'identify_coords'):
            from maths.geometry_grading import validate_plane_spec
            plane_spec = q.get('plane_spec')
            try:
                validate_plane_spec(plane_spec)
            except (ValueError, TypeError) as exc:
                errors.append(f'Q{idx}: Invalid plane_spec ({exc})')
                failed += 1
                continue

        # Read-a-graph / measure fields: numeric answer (+ tolerance/unit).
        # read_graph may also carry an optional clean graph_spec (else the graph
        # image is kept); measure grades the same numeric fields (angle/length).
        graph_spec = None
        numeric_answer = None
        answer_tolerance = None
        answer_unit = ''
        if q_type in ('read_graph', 'measure'):
            from decimal import Decimal, InvalidOperation
            try:
                numeric_answer = Decimal(str(q.get('numeric_answer')))
            except (InvalidOperation, TypeError, ValueError):
                numeric_answer = None
            if numeric_answer is None:
                errors.append(f'Q{idx}: {q_type} needs a numeric_answer')
                failed += 1
                continue
            raw_tol = q.get('answer_tolerance')
            if raw_tol not in (None, ''):
                try:
                    answer_tolerance = Decimal(str(raw_tol))
                except (InvalidOperation, ValueError):
                    answer_tolerance = None
            answer_unit = (q.get('answer_unit') or '')[:10]
            if q_type == 'read_graph':
                graph_spec = q.get('graph_spec') or None
                if graph_spec:
                    from maths.geometry_grading import validate_graph_spec
                    try:
                        validate_graph_spec(graph_spec)
                    except (ValueError, TypeError):
                        graph_spec = None  # fall back to the image; don't fail the import

        # Draw-on-grid / shape-select / number-line: validate the structured spec;
        # skip a malformed one rather than import a question that can't be graded.
        grid_spec = None
        shape_spec = None
        number_line_spec = None
        if q_type == 'draw_on_grid':
            from maths.geometry_grading import validate_grid_spec
            grid_spec = q.get('grid_spec')
            try:
                validate_grid_spec(grid_spec)
            except (ValueError, TypeError) as exc:
                errors.append(f'Q{idx}: Invalid grid_spec ({exc})')
                failed += 1
                continue
        elif q_type == 'shape_select':
            from maths.geometry_grading import validate_shape_spec
            shape_spec = q.get('shape_spec')
            try:
                validate_shape_spec(shape_spec)
            except (ValueError, TypeError) as exc:
                errors.append(f'Q{idx}: Invalid shape_spec ({exc})')
                failed += 1
                continue
        elif q_type == 'number_line':
            from maths.geometry_grading import validate_number_line_spec
            number_line_spec = q.get('number_line_spec')
            try:
                validate_number_line_spec(number_line_spec)
            except (ValueError, TypeError) as exc:
                errors.append(f'Q{idx}: Invalid number_line_spec ({exc})')
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
                    existing.plane_spec = plane_spec
                    existing.graph_spec = graph_spec
                    existing.grid_spec = grid_spec
                    existing.shape_spec = shape_spec
                    existing.number_line_spec = number_line_spec
                    existing.numeric_answer = numeric_answer
                    existing.answer_tolerance = answer_tolerance
                    existing.answer_unit = answer_unit
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
                        plane_spec=plane_spec, graph_spec=graph_spec,
                        grid_spec=grid_spec, shape_spec=shape_spec,
                        number_line_spec=number_line_spec,
                        numeric_answer=numeric_answer,
                        answer_tolerance=answer_tolerance, answer_unit=answer_unit,
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
                elif q_type in ('plot_points', 'plot_line', 'identify_coords', 'read_graph',
                                'measure', 'draw_on_grid', 'shape_select', 'number_line'):
                    # Graded by the structured spec (plane / grid / shapes / number
                    # line) or numeric tolerance (measure / read_graph) — never Answer
                    # rows. The model's clean() also forbids answer options here.
                    pass
                else:
                    for a_idx, ans in enumerate(answers_data):
                        MathsAnswer.objects.create(
                            question=question,
                            answer_text=ans.get('text', ''),
                            is_correct=ans.get('is_correct', False),
                            order=a_idx + 1,
                        )

                # Fill in the blanks: a question whose text carries "___" gaps
                # is built into a blank_spec (one set of accepted answers per
                # gap) so it renders as a sentence with an input in each gap
                # instead of one box for the whole thing. Detected here rather
                # than trusted from the extractor's question_type, because a
                # two-gap sentence routinely comes back typed short_answer.
                # Runs after the Answer rows are written — the spec is derived
                # FROM them — and leaves them in place.
                if (count_blanks(q_text)
                        and q_type in ('fill_blank', 'short_answer', 'calculation')):
                    applied, reason = question.rebuild_blank_spec()
                    if applied:
                        question.question_type = MathsQuestion.FILL_BLANK
                        question.save(update_fields=['question_type', 'blank_spec'])
                        blanks_built += 1
                    else:
                        # Left as it came in — still a working question, just a
                        # single box. Said out loud rather than swallowed, so the
                        # teacher can fix the answer and re-import.
                        warnings.append(
                            f'Q{idx}: has blanks but stayed a single box — {reason}'
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
        'warnings': warnings,
        'images_saved': images_saved,
        'blanks_built': blanks_built,
    }
