"""
upload_services.py — Subject-aware question/exercise upload parsers.

Strategy pattern: each subject has a parser that handles file reading,
validation, and DB persistence.  The view owns role-checking and scope
resolution; parsers own domain logic.

Usage::

    parser = get_upload_parser('coding')     # or 'mathematics'
    result = parser.process(uploaded_file, user, post_data,
                            school_id=school_id, dept_id=dept_id,
                            selected_classroom_id=classroom_id)
    # result is an UploadResult with .to_dict() for template context
"""
from __future__ import annotations

import json
import re
import zipfile

from django.db import transaction
from django.utils.text import slugify


# ── Result container ──────────────────────────────────────────────────────────

class UploadResult:
    """Standardised result returned by every parser's process() method."""

    def __init__(self):
        self.inserted: int = 0
        self.updated: int = 0
        self.failed: int = 0
        self.images_saved: int = 0
        self.image_dir: str = ''
        self.subject: str = ''
        self.detail: dict = {}
        self.errors: list[str] = []
        # Every created/updated content row, as {subject_slug, content_id, order}.
        # Lets a caller (e.g. the homework/worksheet JSON-upload flow) link the
        # saved questions into an assignment without re-querying by text.
        self.saved: list[dict] = []

    def to_dict(self) -> dict:
        return {
            'inserted': self.inserted,
            'updated': self.updated,
            'failed': self.failed,
            'images_saved': self.images_saved,
            'image_dir': self.image_dir,
            'subject': self.subject,
            'detail': self.detail,
            'errors': self.errors,
            'saved': self.saved,
        }


class ParseError(Exception):
    """Raised when the uploaded file cannot be read at all."""
    pass


# ── Base parser ───────────────────────────────────────────────────────────────

class BaseQuestionParser:
    """
    Abstract base.  Subclasses implement:
      - process()          → parse + validate + save, return UploadResult.to_dict()
      - get_template_json() → sample data dict for the template-download endpoint
    """

    subject_slug: str = ''

    # ------------------------------------------------------------------
    # Shared file-reading helper (JSON or ZIP)
    # ------------------------------------------------------------------

    def _read_file(self, uploaded_file) -> tuple[dict, dict]:
        """
        Read the uploaded file.

        Returns:
            (data_dict, extracted_images)
            where extracted_images is {filename: bytes} (empty for plain JSON).

        Raises:
            ParseError on unrecoverable failure.
        """
        filename = uploaded_file.name.lower()
        extracted_images: dict[str, bytes] = {}

        if filename.endswith('.zip'):
            if not zipfile.is_zipfile(uploaded_file):
                raise ParseError('Invalid ZIP file.')
            uploaded_file.seek(0)
            with zipfile.ZipFile(uploaded_file) as zf:
                json_bytes = None
                for name in zf.namelist():
                    basename = name.split('/')[-1]
                    if basename == 'questions.json':
                        json_bytes = zf.read(name)
                    elif re.search(r'\.(png|jpg|jpeg|gif|webp)$', basename, re.I):
                        extracted_images[basename] = zf.read(name)
                if json_bytes is None:
                    raise ParseError('ZIP must contain a file named questions.json at its root.')
            try:
                data = json.loads(json_bytes.decode('utf-8'))
            except json.JSONDecodeError as e:
                raise ParseError(f'Invalid JSON in ZIP: {e}')

        elif filename.endswith('.json'):
            try:
                data = json.loads(uploaded_file.read().decode('utf-8'))
            except json.JSONDecodeError as e:
                raise ParseError(f'Invalid JSON: {e}')

        else:
            raise ParseError('Please upload a .json or .zip file.')

        return data, extracted_images

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def process(self, uploaded_file, user, post_data, **kwargs) -> dict:
        raise NotImplementedError

    def get_template_json(self) -> dict:
        raise NotImplementedError


# ── Mathematics parser ────────────────────────────────────────────────────────

class MathsQuestionParser(BaseQuestionParser):
    """
    Handles the existing maths JSON / ZIP upload format.
    Logic is identical to the original inline view code, extracted here.
    """

    subject_slug = 'mathematics'

    # Type-specific data columns on maths.Question. These carry the question's
    # content (the numbers a column sum stacks, the spec a graph is graded
    # against) — leaving one out does not fail the upload, it saves a question
    # with nothing to render and nothing to grade, which is the silent failure
    # this repo does not allow. The same tuple is maintained in
    # maths/management/commands/{export_school,import_global}_questions.py; add
    # a column to all three whenever a question type gains one.
    #
    # blank_spec is deliberately absent: this parser derives it from the "___"
    # gaps in the question text via apply_blank_format() below, which runs after
    # the answers are written and would overwrite anything set here.
    TYPE_SPECIFIC_FIELDS = (
        'dividend', 'divisor', 'target_number', 'operands', 'operator',
        'numeric_answer', 'answer_tolerance', 'answer_unit',
        'grid_spec', 'shape_spec', 'plane_spec', 'graph_spec',
        'number_line_spec', 'table_spec', 'sketch_spec',
    )

    def process(
        self,
        uploaded_file,
        user,
        post_data,
        *,
        school_id=None,
        dept_id=None,
        selected_classroom_id=None,
        **_,
    ) -> dict:
        result = UploadResult()
        result.subject = 'mathematics'

        try:
            data, extracted_images = self._read_file(uploaded_file)
        except ParseError as e:
            result.errors.append(str(e))
            result.failed = 1
            return result.to_dict()

        # One file may carry several (strand, topic, year_level) sets under
        # "groups" — a Year 4 and a Year 5 bank uploaded together, say. A file
        # with the fields at the top level is the original single-group form and
        # is read as a one-entry list, so both shapes take the same path below.
        grouped = data.get('groups') is not None
        if not grouped:
            groups = [data]
        else:
            groups = data.get('groups')
            if not isinstance(groups, list) or not groups:
                result.errors.append('"groups" must be a non-empty list.')
                result.failed = 1
                return result.to_dict()
            # A file may use both shapes at once: questions listed at the top
            # level belong to the top-level topic/year and read as an implicit
            # first group. Ignoring them would drop a whole bank without saying
            # so.
            if data.get('questions'):
                groups = [data] + list(groups)

        details = []
        for gi, group in enumerate(groups, 1):
            if not isinstance(group, dict):
                result.errors.append(f'Group {gi}: expected an object.')
                result.failed += 1
                continue
            # A grouped file may still state strand/topic/year_level once at the
            # top level; a group overrides only what it names itself.
            merged = ({k: data[k] for k in ('strand', 'topic', 'year_level')
                       if k in data} if grouped else {})
            merged.update(group)
            label = self._process_group(
                merged, result, extracted_images,
                prefix='' if len(groups) == 1 else f'Group {gi} ',
                school_id=school_id, dept_id=dept_id,
                selected_classroom_id=selected_classroom_id,
            )
            if label:
                details.append(label)

        result.images_saved = len(extracted_images)
        result.image_dir = details[0]['image_dir'] if (details and extracted_images) else ''
        if len(details) == 1:
            result.detail = {'topic': details[0]['topic'],
                             'year_level': details[0]['year_level']}
        else:
            result.detail = {'groups': [{'topic': d['topic'],
                                         'year_level': d['year_level'],
                                         'questions': d['count']}
                                        for d in details]}
        return result.to_dict()

    def _process_group(
        self, data, result, extracted_images, prefix='', *,
        school_id=None, dept_id=None, selected_classroom_id=None,
    ):
        """Resolve one group's topic/level and save its questions.

        Appends to the shared ``result``; returns a small dict describing the
        group, or None if the group could not be resolved at all.
        """
        from django.conf import settings
        import os

        from maths.models import Question as MathsQuestion, Answer as MathsAnswer
        from maths.answer_verification import SELF_GRADED_ANSWER_FIELDS
        from classroom.models import (
            Topic as ClassroomTopic,
            Level as ClassroomLevel,
            Subject as ClassroomSubject,
        )

        topic_name = (data.get('topic') or '').strip()
        strand_name = (data.get('strand') or '').strip()
        year_level = data.get('year_level')

        if not topic_name:
            result.errors.append(f'{prefix}Missing "topic" field.')
            result.failed += 1
            return None

        # Ensure global Mathematics subject
        maths_subject, _ = ClassroomSubject.objects.get_or_create(
            slug='mathematics',
            school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )

        # Resolve / auto-create strand (parent topic)
        strand_topic = None
        if strand_name:
            strand_slug = slugify(strand_name)
            strand_topic, _ = ClassroomTopic.objects.get_or_create(
                subject=maths_subject,
                slug=strand_slug,
                defaults={
                    'name': strand_name,
                    'parent': None,
                    'is_active': True,
                    'order': 0,
                },
            )

        # Resolve / auto-create subtopic
        topic_qs = ClassroomTopic.objects.filter(
            subject=maths_subject, name__iexact=topic_name,
        )
        if strand_topic:
            topic_qs = topic_qs.filter(parent=strand_topic)
        try:
            maths_topic = topic_qs.get()
        except ClassroomTopic.DoesNotExist:
            base_slug = slugify(topic_name) or f'topic-{topic_name.lower()}'
            slug = base_slug
            counter = 1
            while ClassroomTopic.objects.filter(subject=maths_subject, slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            maths_topic = ClassroomTopic.objects.create(
                subject=maths_subject,
                name=topic_name,
                slug=slug,
                parent=strand_topic,
                is_active=True,
                order=0,
            )
        except ClassroomTopic.MultipleObjectsReturned:
            result.errors.append(
                f'{prefix}Multiple topics named "{topic_name}" exist — please '
                f'disambiguate in the database.'
            )
            result.failed += 1
            return None

        try:
            maths_level = ClassroomLevel.objects.get(level_number=year_level)
        except ClassroomLevel.DoesNotExist:
            result.errors.append(f'{prefix}Year level {year_level} not found.')
            result.failed += 1
            return None
        except ClassroomLevel.MultipleObjectsReturned:
            # Legacy prod has school-scoped levels sharing a number; prefer the
            # global one rather than blowing up the whole upload.
            maths_level = (
                ClassroomLevel.objects.filter(level_number=year_level, school__isnull=True).first()
                or ClassroomLevel.objects.filter(level_number=year_level).first()
            )

        # Link topic / strand to the level
        if not maths_topic.levels.filter(pk=maths_level.pk).exists():
            maths_topic.levels.add(maths_level)
        if strand_topic and not strand_topic.levels.filter(pk=maths_level.pk).exists():
            strand_topic.levels.add(maths_level)

        # Save images from ZIP
        topic_slug_dir = re.sub(r'\s+', '_', topic_name.lower())
        image_rel_dir = f'questions/year{year_level}/{topic_slug_dir}'
        if extracted_images:
            image_abs_dir = os.path.join(settings.MEDIA_ROOT, image_rel_dir)
            os.makedirs(image_abs_dir, exist_ok=True)
            for img_name, img_bytes in extracted_images.items():
                safe_name = re.sub(r'[^\w.\-]', '_', img_name)
                with open(os.path.join(image_abs_dir, safe_name), 'wb') as fh:
                    fh.write(img_bytes)

        # Process questions
        saved_here = 0
        for i, q_data in enumerate(data.get('questions', []), 1):
            question_text = q_data.get('question_text', '').strip()
            question_type = q_data.get('question_type', '').strip()
            answers_data = q_data.get('answers', [])

            if not question_text:
                result.errors.append(f'{prefix}Q{i}: missing question_text')
                result.failed += 1
                continue
            if question_type not in dict(MathsQuestion.QUESTION_TYPES):
                result.errors.append(f'{prefix}Q{i}: unknown question_type "{question_type}"')
                result.failed += 1
                continue

            fields = {
                'question_type': question_type,
                'difficulty': q_data.get('difficulty', 1),
                'points': q_data.get('points', 1),
                'explanation': q_data.get('explanation', ''),
            }
            for fname in self.TYPE_SPECIFIC_FIELDS:
                if q_data.get(fname) is not None:
                    fields[fname] = q_data[fname]

            # Types whose answer is computed from the question itself (a column
            # sum from operands/operator, a long division from dividend/divisor)
            # carry no answer rows — Question.clean() refuses them on most of
            # these. Requiring answers here rejected exactly what the model
            # mandates, so the check becomes: no answers is fine IF the question
            # actually carries the data it is graded from, and a specific error
            # naming the missing field if it does not.
            required = SELF_GRADED_ANSWER_FIELDS.get(question_type)
            if not answers_data:
                if not required:
                    result.errors.append(f'{prefix}Q{i}: no answers provided')
                    result.failed += 1
                    continue
                probe = MathsQuestion(question_text=question_text, **fields)
                missing = [f for f in required if getattr(probe, f, None) in (None, '', [])]
                if missing:
                    result.errors.append(
                        f'{prefix}Q{i}: {question_type} has no answers and no '
                        f'{"/".join(missing)} to work the answer out from'
                    )
                    result.failed += 1
                    continue

            image_field = ''
            img_filename = q_data.get('image', '').strip()
            if img_filename and img_filename in extracted_images:
                safe_name = re.sub(r'[^\w.\-]', '_', img_filename)
                image_field = f'{image_rel_dir}/{safe_name}'
            if image_field:
                fields['image'] = image_field

            try:
                with transaction.atomic():
                    existing = MathsQuestion.objects.filter(
                        question_text=question_text,
                        topic=maths_topic,
                        level=maths_level,
                        school_id=school_id,
                        department_id=dept_id,
                        classroom_id=selected_classroom_id,
                    ).first()

                    if existing:
                        for k, v in fields.items():
                            setattr(existing, k, v)
                        existing.save()
                        existing.answers.all().delete()
                        question = existing
                        result.updated += 1
                    else:
                        question = MathsQuestion.objects.create(
                            question_text=question_text,
                            topic=maths_topic,
                            level=maths_level,
                            school_id=school_id,
                            department_id=dept_id,
                            classroom_id=selected_classroom_id,
                            **fields,
                        )
                        result.inserted += 1

                    for a in answers_data:
                        MathsAnswer.objects.create(
                            question=question,
                            answer_text=a.get('answer_text') or a.get('text', ''),
                            is_correct=a.get('is_correct', False),
                            order=a.get('order') or a.get('display_order', 1),
                        )

                    # A question whose text carries "___" gaps becomes a
                    # fill-in-the-blank sentence, with an input in each gap
                    # instead of one box for the whole thing. Runs after the
                    # answers are written — the per-gap answers are derived from
                    # them. One whose answers do not map onto its gaps stays a
                    # working single box and is reported rather than guessed at.
                    changed, blank_reason = question.apply_blank_format()
                    if changed:
                        question.save(update_fields=['question_type', 'blank_spec'])
                    if blank_reason:
                        result.errors.append(
                            f'{prefix}Q{i}: has blanks but stayed a single box — {blank_reason}'
                        )

                    result.saved.append({
                        'subject_slug': 'mathematics',
                        'content_id': question.pk,
                        'order': i,
                    })
                    saved_here += 1
            except Exception as exc:
                result.errors.append(f'{prefix}Q{i}: {exc}')
                result.failed += 1

        return {'topic': topic_name, 'year_level': year_level,
                'image_dir': image_rel_dir, 'count': saved_here}


    def get_template_json(self) -> dict:
        """Sample upload file.

        Two shapes, shown together here because a file may use both at once:
        strand/topic/year_level stated once at the top level for the questions
        under "questions", and any number of further (strand, topic, year_level)
        sets under "groups" — which is how one file covers more than one topic
        or year. A file needs only one of the two.
        """
        def column(a, b, difficulty):
            # A column sum is graded from operands/operator, which is why it
            # carries no answer rows.
            return {
                'question_text': f'Work out {a} \u00d7 {b} using column multiplication.',
                'question_type': 'column_operation',
                'operands': [a, b],
                'operator': '*',
                'difficulty': difficulty,
                'points': 1,
                'explanation': f'{a} \u00d7 {b} = {a * b}',
                'answers': [],
            }

        return {
            'strand': 'Number',
            'topic': 'Fractions',
            'year_level': 4,
            'questions': [
                {
                    'question_text': 'What is 1/2 + 1/4?',
                    'question_type': 'multiple_choice',
                    'difficulty': 1,
                    'points': 1,
                    'explanation': 'Convert to a common denominator first.',
                    'answers': [
                        {'text': '3/4', 'is_correct': True},
                        {'text': '1/2', 'is_correct': False},
                        {'text': '2/6', 'is_correct': False},
                        {'text': '1/4', 'is_correct': False},
                    ],
                },
            ],
            'groups': [
                {
                    'strand': 'Number',
                    'topic': 'Multiplication',
                    'year_level': 4,
                    'questions': [column(347, 8, 2)],
                },
                {
                    'strand': 'Number',
                    'topic': 'Multiplication',
                    'year_level': 5,
                    'questions': [column(347, 68, 2)],
                },
            ],
        }


# ── Coding exercise parser ────────────────────────────────────────────────────

class CodingExerciseParser(BaseQuestionParser):
    """
    Parses and saves coding exercises from a JSON upload.

    Expected JSON format::

        {
          "subject": "coding",
          "language": "python",
          "topic": "loops",
          "level": "beginner",
          "exercises": [
            {
              "title": "Print 1–5",
              "instructions": "Use a for loop to print 1 through 5.",
              "starter_code": "# Your code here\\n",
              "expected_output": "1\\n2\\n3\\n4\\n5",
              "required_code_patterns": ["for\\\\s+\\\\w+\\\\s+in", "range\\\\("],
              "hints": "range(1, 6) generates 1–5",
              "display_order": 1
            }
          ]
        }

    Field mapping to CodingExercise model:
        instructions           → description
        display_order          → order
        level                  → level (CharField, stored directly)
        required_code_patterns → required_code_patterns (list joined with newlines, empty → NULL)
    """

    subject_slug = 'coding'
    VALID_LEVELS = frozenset({'beginner', 'intermediate', 'advanced'})

    def process(self, uploaded_file, user, post_data, **_) -> dict:
        from coding.models import CodingLanguage, CodingTopic, TopicLevel, CodingExercise

        result = UploadResult()
        result.subject = 'coding'

        try:
            data, _ = self._read_file(uploaded_file)
        except ParseError as e:
            result.errors.append(str(e))
            result.failed = 1
            return result.to_dict()

        # ── Resolve language ──────────────────────────────────────────
        language_slug = (data.get('language') or '').strip().lower()
        if not language_slug:
            result.errors.append('Missing "language" field.')
            result.failed = 1
            return result.to_dict()
        try:
            language = CodingLanguage.objects.get(slug=language_slug)
        except CodingLanguage.DoesNotExist:
            available = ', '.join(
                CodingLanguage.objects.values_list('slug', flat=True).order_by('name')
            )
            result.errors.append(
                f'Language "{language_slug}" not found. Available: {available}'
            )
            result.failed = 1
            return result.to_dict()

        # ── Resolve topic ─────────────────────────────────────────────
        topic_slug = (data.get('topic') or '').strip().lower()
        if not topic_slug:
            result.errors.append('Missing "topic" field.')
            result.failed = 1
            return result.to_dict()
        try:
            topic = CodingTopic.objects.get(slug=topic_slug, language=language)
        except CodingTopic.DoesNotExist:
            available = ', '.join(
                CodingTopic.objects.filter(language=language)
                .values_list('slug', flat=True).order_by('name')
            )
            result.errors.append(
                f'Topic "{topic_slug}" not found for {language.name}. Available: {available}'
            )
            result.failed = 1
            return result.to_dict()

        # ── Validate level ────────────────────────────────────────────
        level = (data.get('level') or '').strip().lower()
        if level not in self.VALID_LEVELS:
            result.errors.append(
                f'Level "{level}" is invalid. Must be one of: '
                f'{", ".join(sorted(self.VALID_LEVELS))}'
            )
            result.failed = 1
            return result.to_dict()

        # ── Validate exercises array ──────────────────────────────────
        exercises = data.get('exercises') or []
        if not exercises:
            result.errors.append('The "exercises" array is empty or missing.')
            result.failed = 1
            return result.to_dict()

        validation_errors = []
        for i, ex in enumerate(exercises, 1):
            if not (ex.get('title') or '').strip():
                validation_errors.append(f'Exercise {i}: missing "title"')
            if not (ex.get('instructions') or '').strip():
                validation_errors.append(f'Exercise {i}: missing "instructions"')
        if validation_errors:
            result.errors = validation_errors
            result.failed = len(validation_errors)
            return result.to_dict()

        # ── Resolve (or create) TopicLevel ───────────────────────────
        topic_level, _ = TopicLevel.get_or_create_for(topic, level)

        # ── Save exercises ────────────────────────────────────────────
        exercise_details = []
        for i, ex in enumerate(exercises, 1):
            title = ex['title'].strip()
            # Default to a failed record so any exception below (including an
            # invalid required_code_patterns type) is reported per-exercise
            # rather than crashing the whole upload.
            status = 'failed'
            patterns_list = []
            try:
                with transaction.atomic():
                    normalized = self._normalize_required_patterns(
                        ex.get('required_code_patterns')
                    )
                    patterns_list = normalized.split('\n') if normalized else []
                    existing = CodingExercise.objects.filter(
                        topic_level=topic_level,
                        title=title,
                    ).first()
                    fields = {
                        'description': ex.get('instructions', '').strip(),
                        'starter_code': ex.get('starter_code', ''),
                        'expected_output': ex.get('expected_output', '').strip(),
                        'required_code_patterns': normalized,
                        'hints': ex.get('hints', ''),
                        'order': int(ex.get('display_order', i)),
                        'is_active': True,
                    }
                    if existing:
                        for k, v in fields.items():
                            setattr(existing, k, v)
                        existing.save()
                        obj = existing
                        result.updated += 1
                        status = 'updated'
                    else:
                        obj = CodingExercise.objects.create(
                            topic_level=topic_level,
                            title=title,
                            **fields,
                        )
                        result.inserted += 1
                        status = 'new'

                    result.saved.append({
                        'subject_slug': 'coding',
                        'content_id': obj.pk,
                        'order': fields['order'],
                    })
            except Exception as exc:
                result.errors.append(f'Exercise {i} ({title!r}): {exc}')
                result.failed += 1
                status = 'failed'
            exercise_details.append({
                'title': title,
                'status': status,
                'patterns': patterns_list,
            })

        patterns_count = sum(1 for ed in exercise_details if ed['patterns'])
        result.detail = {
            'language': language.name,
            'topic': topic.name,
            'level': level,
            'patterns_count': patterns_count,
            'exercises': exercise_details,
        }
        return result.to_dict()

    @staticmethod
    def _normalize_required_patterns(value):
        """Accept list[str], str, or None; return newline-joined str or None.

        Model stores patterns as a newline-separated string (one regex per
        line); the scoring helper splits on newlines. JSON uploads are more
        readable with a list, so we accept both shapes.
        """
        if value is None:
            return None
        if isinstance(value, str):
            joined = value.strip()
            return joined or None
        if isinstance(value, list):
            lines = [str(p).strip() for p in value if str(p).strip()]
            return '\n'.join(lines) or None
        raise ValueError(
            'required_code_patterns must be a list of strings, a string, or omitted'
        )

    def get_template_json(self) -> dict:
        return {
            'subject': 'coding',
            'language': 'python',
            'topic': 'variables',
            'level': 'beginner',
            'exercises': [
                {
                    'title': 'Print Hello',
                    'instructions': "Print 'Hello' to the console.",
                    'starter_code': '# Your code here\n',
                    'expected_output': 'Hello',
                    'hints': 'Use print()',
                    'display_order': 1,
                },
                {
                    'title': 'Store Your Name',
                    'instructions': 'Create a variable called `name` and print `Hello, <name>`.',
                    'starter_code': "name = ''\nprint(name)\n",
                    'expected_output': 'Hello, Alice',
                    'required_code_patterns': [
                        r'name\s*=',
                        r'print\(',
                    ],
                    'hints': "Assign a string: name = 'Alice', then use print(f'Hello, {name}')",
                    'display_order': 2,
                },
            ],
        }


# ── Coding Problem parser ─────────────────────────────────────────────────────

class CodingProblemParser(BaseQuestionParser):
    """
    Handles uploads of coding *problems* (algorithm / logic challenges with
    test cases).  Distinct from CodingExerciseParser which handles guided
    topic exercises.

    Expected JSON format::

        {
          "subject": "coding_problem",
          "language": "python",          // language slug
          "problems": [
            {
              "title": "Reverse a String",
              "difficulty": 1,           // 1–8
              "category": "algorithm",   // see CodingProblem.CATEGORY_CHOICES
              "description": "...",
              "starter_code": "...",
              "constraints": "",
              "time_limit_seconds": 5,
              "memory_limit_mb": 256,
              "forbidden_code_patterns": [],
              "test_cases": [
                {
                  "input": "hello",
                  "expected": "olleh",
                  "visible": true,
                  "boundary": false,
                  "description": "Basic word"
                }
              ]
            }
          ]
        }
    """

    subject_slug = 'coding_problem'

    VALID_CATEGORIES = frozenset({
        'algorithm', 'logic', 'data_structures', 'dynamic_programming',
        'graph_theory', 'string_manipulation', 'mathematics', 'sorting_searching',
    })

    def process(self, uploaded_file, user, post_data, **_) -> dict:
        from coding.models import CodingLanguage, CodingProblem, ProblemTestCase

        result = UploadResult()
        result.subject = 'coding_problem'

        try:
            data, _ = self._read_file(uploaded_file)
        except ParseError as e:
            result.errors.append(str(e))
            result.failed = 1
            return result.to_dict()

        # ── Resolve language ──────────────────────────────────────────
        language_slug = (data.get('language') or '').strip().lower()
        if not language_slug:
            result.errors.append('Missing "language" field.')
            result.failed = 1
            return result.to_dict()
        try:
            language = CodingLanguage.objects.get(slug=language_slug)
        except CodingLanguage.DoesNotExist:
            available = ', '.join(
                CodingLanguage.objects.values_list('slug', flat=True).order_by('name')
            )
            result.errors.append(
                f'Language "{language_slug}" not found. Available: {available}'
            )
            result.failed = 1
            return result.to_dict()

        # ── Validate problems array ───────────────────────────────────
        problems = data.get('problems') or []
        if not problems:
            result.errors.append('The "problems" array is empty or missing.')
            result.failed = 1
            return result.to_dict()

        # ── Save problems ─────────────────────────────────────────────
        for i, prob in enumerate(problems, 1):
            title = (prob.get('title') or '').strip()
            if not title:
                result.errors.append(f'Problem {i}: missing "title"')
                result.failed += 1
                continue
            if not (prob.get('description') or '').strip():
                result.errors.append(f'Problem {i} ({title!r}): missing "description"')
                result.failed += 1
                continue

            category = (prob.get('category') or 'algorithm').strip().lower()
            if category not in self.VALID_CATEGORIES:
                result.errors.append(
                    f'Problem {i} ({title!r}): invalid category "{category}". '
                    f'Valid: {", ".join(sorted(self.VALID_CATEGORIES))}'
                )
                result.failed += 1
                continue

            try:
                with transaction.atomic():
                    problem, created = CodingProblem.objects.update_or_create(
                        language=language,
                        title=title,
                        defaults={
                            'description':             prob.get('description', '').strip(),
                            'starter_code':            prob.get('starter_code', ''),
                            'difficulty':              int(prob.get('difficulty', 1)),
                            'category':                category,
                            'constraints':             prob.get('constraints', ''),
                            'time_limit_seconds':      int(prob.get('time_limit_seconds', 5)),
                            'memory_limit_mb':         int(prob.get('memory_limit_mb', 256)),
                            'forbidden_code_patterns': prob.get('forbidden_code_patterns') or [],
                            'is_active':               True,
                        },
                    )

                    # Upsert test cases: clear existing and re-create so re-uploads
                    # always reflect the latest test suite.
                    problem.test_cases.all().delete()
                    test_cases = prob.get('test_cases') or []
                    for order, tc in enumerate(test_cases, start=1):
                        ProblemTestCase.objects.create(
                            problem=problem,
                            input_data=tc.get('input', ''),
                            expected_output=tc.get('expected', ''),
                            is_visible=bool(tc.get('visible', False)),
                            is_boundary_test=bool(tc.get('boundary', False)),
                            description=tc.get('description', ''),
                            display_order=order,
                        )

                    if created:
                        result.inserted += 1
                    else:
                        result.updated += 1

            except Exception as exc:
                result.errors.append(f'Problem {i} ({title!r}): {exc}')
                result.failed += 1

        result.detail = {
            'language': language.name,
            'problems_count': len(problems),
        }
        return result.to_dict()

    def get_template_json(self) -> dict:
        return {
            'subject': 'coding_problem',
            'language': 'python',
            'problems': [
                {
                    'title': 'Reverse a String',
                    'difficulty': 1,
                    'category': 'algorithm',
                    'description': 'Read a single line and print it reversed.\n\nExample:\n  Input:  hello\n  Output: olleh',
                    'starter_code': 's = input()\n# Print the reversed string\n',
                    'constraints': '',
                    'time_limit_seconds': 5,
                    'memory_limit_mb': 256,
                    'forbidden_code_patterns': [],
                    'test_cases': [
                        {'input': 'hello', 'expected': 'olleh', 'visible': True, 'boundary': False, 'description': 'Basic word'},
                        {'input': 'a',     'expected': 'a',     'visible': False, 'boundary': True,  'description': 'Single char'},
                    ],
                },
            ],
        }


# ── Factory ───────────────────────────────────────────────────────────────────
#
# Phase 1 of the subject-plugin refactor: the parser selection + subject list
# come from the subject registry (classroom.subject_registry) rather than the
# hard-coded dicts that used to live here.  Each subject's plugin binds a
# ``slug`` to a parser class in its own app (maths/plugin.py, coding/plugin.py).


def get_upload_parser(subject_slug: str) -> 'BaseQuestionParser | None':
    """Return the parser for *subject_slug*, or None if unknown."""
    from .subject_registry import get_upload_parser as _registry_get
    return _registry_get(subject_slug)


# Module-level proxy so existing callers (template context, tests) can still
# do ``from classroom.upload_services import AVAILABLE_SUBJECTS`` and get a
# list of ``{slug, name}`` dicts driven by the registry.
class _AvailableSubjectsProxy:
    """List-like proxy that defers to the subject registry on every access.

    We keep the name + shape stable so the upload template
    (``{% for s in subjects %}...{% endfor %}``) continues to work unchanged.
    """

    def _materialise(self) -> list[dict]:
        from .subject_registry import available_subjects
        return available_subjects()

    def __iter__(self):
        return iter(self._materialise())

    def __len__(self):
        return len(self._materialise())

    def __getitem__(self, key):
        return self._materialise()[key]

    def __bool__(self):
        return bool(self._materialise())

    def __repr__(self):
        return repr(self._materialise())


AVAILABLE_SUBJECTS = _AvailableSubjectsProxy()


# ──────────────────────────────────────────────────────────────────────────────
# Assignment (homework / worksheet) JSON-upload helpers
#
# These let a teacher attach an *authored* JSON/ZIP question file directly to a
# homework or worksheet — skipping AI extraction and the editable preview. They
# reuse the same parsers as the global question-bank upload above; the only extra
# job is to auto-detect the subject and hand back the saved content refs so the
# caller can build the assignment's question rows.
# ──────────────────────────────────────────────────────────────────────────────

def detect_assignment_subject(uploaded_file) -> str:
    """Peek at an authored JSON/ZIP upload and return its subject slug.

    ``subject: "coding"`` → ``'coding'``; ``subject: "coding_problem"`` →
    ``'coding_problem'`` (rejected by :func:`import_assignment_questions` — it
    has no homework/worksheet plugin); anything else (or unreadable) →
    ``'mathematics'``. The file pointer is rewound so the real parser can
    re-read the same upload.
    """
    try:
        data, _ = BaseQuestionParser()._read_file(uploaded_file)
    except Exception:
        data = {}
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

    subject = ''
    if isinstance(data, dict):
        subject = (data.get('subject') or '').strip().lower()
    if subject in ('coding', 'coding_problem'):
        return subject
    return 'mathematics'


def import_assignment_questions(uploaded_file, user) -> dict:
    """Parse an authored JSON/ZIP question file for a homework/worksheet.

    Auto-detects the subject, scopes Maths questions to the uploader's school
    (mirroring the PDF homework path), leaves Coding exercises global, and
    rejects ``coding_problem`` (no assignment plugin). Returns the parser's
    result dict augmented with a de-duplicated ``saved`` list of
    ``{subject_slug, content_id, order}`` refs the caller links into the
    assignment.
    """
    subject_slug = detect_assignment_subject(uploaded_file)

    if subject_slug == 'coding_problem':
        return {
            'inserted': 0, 'updated': 0, 'failed': 1, 'images_saved': 0,
            'image_dir': '', 'subject': 'coding_problem', 'detail': {},
            'errors': ['Coding-problem files cannot be attached to a homework '
                       'or worksheet. Upload them via the question bank.'],
            'saved': [],
        }

    parser = get_upload_parser(subject_slug)
    if parser is None:
        return {
            'inserted': 0, 'updated': 0, 'failed': 1, 'images_saved': 0,
            'image_dir': '', 'subject': subject_slug, 'detail': {},
            'errors': [f'Unknown subject "{subject_slug}".'], 'saved': [],
        }

    process_kwargs = {}
    # Maths questions are school-scoped exactly like PDF homework; coding
    # exercises stay global (the parser upserts by topic_level + title).
    if subject_slug == 'mathematics':
        from .views import _get_question_scope
        school_id, dept_id, _classroom_ids = _get_question_scope(user)
        process_kwargs = {'school_id': school_id, 'dept_id': dept_id}

    result = parser.process(uploaded_file, user, {}, **process_kwargs)

    # De-dup saved refs by (subject_slug, content_id) — two authored questions
    # can upsert onto the same row, and a duplicate ref would violate the
    # assignment's (… , subject_slug, content_id) unique constraint downstream.
    seen = set()
    deduped = []
    for ref in result.get('saved', []):
        key = (ref['subject_slug'], ref['content_id'])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    result['saved'] = deduped
    return result
