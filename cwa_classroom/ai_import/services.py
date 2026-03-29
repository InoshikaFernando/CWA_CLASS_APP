"""
AI Import services: PDF extraction (PyMuPDF) and AI classification (Claude API).
"""
import base64
import json
import os
import tempfile

from django.conf import settings
from django.utils import timezone


# ---------------------------------------------------------------------------
# PDF Extraction (PyMuPDF / fitz)
# ---------------------------------------------------------------------------

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
                ref = f'page{page_num + 1}_img{img_idx + 1}.{ext}'
                images.append({
                    'ref': ref,
                    'base64': base64.b64encode(img_bytes).decode('utf-8'),
                    'ext': ext,
                })

        # Render the full page as a screenshot (captures tables, charts, diagrams)
        # Use 150 DPI for good quality without being too large
        pix = page.get_pixmap(dpi=150)
        page_img_bytes = pix.tobytes('jpeg')
        page_screenshot_b64 = base64.b64encode(page_img_bytes).decode('utf-8')

        pages.append({
            'page_num': page_num + 1,
            'text': text,
            'images': images,
            'screenshot': page_screenshot_b64,
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
3. If a question needs an embedded image (table, chart, diagram), set image_ref to the
   embedded image reference (e.g. "page1_img1.png"). Only use embedded image refs, not screenshots.
4. Do NOT embed table/chart data as text in the question — keep question_text concise and
   reference the image instead when the question depends on a visual.

For question_type, use one of: multiple_choice, true_false, short_answer, fill_blank, calculation
For difficulty, use: 1 (Easy), 2 (Medium), 3 (Hard)

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
                            "enum": ["multiple_choice", "true_false", "short_answer", "fill_blank", "calculation"],
                        },
                        "difficulty": {"type": "integer", "enum": [1, 2, 3]},
                        "points": {"type": "integer", "default": 1},
                        "explanation": {"type": "string", "description": "Brief explanation of the answer"},
                        "image_ref": {
                            "type": "string",
                            "description": "Reference to an embedded image (e.g. page1_img1.png). Only set if this question needs a visual. Null if no image needed.",
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


def classify_questions(extracted_content, existing_topics, existing_levels):
    """
    Send extracted PDF content to Claude API for classification.

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

    # Build message content — send page screenshots so AI can see tables/charts/diagrams
    content_blocks = []
    content_blocks.append({
        "type": "text",
        "text": f"Here is a {extracted_content['page_count']}-page PDF. I'm sending each page as a screenshot so you can see all tables, charts, and diagrams. The extracted text is also provided for accuracy.",
    })

    # Send page screenshots (limit to first 20 pages to stay within token budget)
    for page in extracted_content['pages'][:20]:
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
        "text": "Please extract and classify ALL questions from this PDF. Include any context tables, data, or diagrams that belong with each question in the question_text. Use the classify_questions tool to return structured data.",
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=system_prompt,
        tools=[CLASSIFICATION_TOOL],
        messages=[{"role": "user", "content": content_blocks}],
    )

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


# ---------------------------------------------------------------------------
# Save Questions to DB
# ---------------------------------------------------------------------------

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
                    )
                    inserted += 1

                # Save image if referenced
                if image_ref and image_ref in session.extracted_images:
                    # Build per-question image path: media/questions/year{N}/{topic_slug}/{filename}
                    img_dir = os.path.join(
                        str(settings.MEDIA_ROOT), 'questions',
                        f'year{year_level}', topic_slug,
                    )
                    os.makedirs(img_dir, exist_ok=True)

                    img_b64 = session.extracted_images[image_ref]
                    img_bytes = base64.b64decode(img_b64)
                    img_path = os.path.join(img_dir, image_ref)
                    with open(img_path, 'wb') as f:
                        f.write(img_bytes)
                    # Set relative path from MEDIA_ROOT
                    question.image = os.path.join(
                        'questions', f'year{year_level}', topic_slug, image_ref,
                    )
                    question.save(update_fields=['image'])
                    images_saved += 1

                # Create answers
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
