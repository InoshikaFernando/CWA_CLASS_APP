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
        from django.conf import settings
        import os

        from maths.models import Question as MathsQuestion, Answer as MathsAnswer
        from classroom.models import (
            Topic as ClassroomTopic,
            Level as ClassroomLevel,
            Subject as ClassroomSubject,
        )

        result = UploadResult()
        result.subject = 'mathematics'

        try:
            data, extracted_images = self._read_file(uploaded_file)
        except ParseError as e:
            result.errors.append(str(e))
            result.failed = 1
            return result.to_dict()

        topic_name = data.get('topic', '').strip()
        strand_name = data.get('strand', '').strip()
        year_level = data.get('year_level')

        if not topic_name:
            result.errors.append('Missing "topic" field.')
            result.failed = 1
            return result.to_dict()

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
                f'Multiple topics named "{topic_name}" exist — please disambiguate in the database.'
            )
            result.failed = 1
            return result.to_dict()

        try:
            maths_level = ClassroomLevel.objects.get(level_number=year_level)
        except ClassroomLevel.DoesNotExist:
            result.errors.append(f'Year level {year_level} not found.')
            result.failed = 1
            return result.to_dict()

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
        for i, q_data in enumerate(data.get('questions', []), 1):
            question_text = q_data.get('question_text', '').strip()
            question_type = q_data.get('question_type', '').strip()
            answers_data = q_data.get('answers', [])

            if not question_text:
                result.errors.append(f'Q{i}: missing question_text')
                result.failed += 1
                continue
            if question_type not in dict(MathsQuestion.QUESTION_TYPES):
                result.errors.append(f'Q{i}: unknown question_type "{question_type}"')
                result.failed += 1
                continue
            if not answers_data:
                result.errors.append(f'Q{i}: no answers provided')
                result.failed += 1
                continue

            image_field = ''
            img_filename = q_data.get('image', '').strip()
            if img_filename and img_filename in extracted_images:
                safe_name = re.sub(r'[^\w.\-]', '_', img_filename)
                image_field = f'{image_rel_dir}/{safe_name}'

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
                    fields = {
                        'question_type': question_type,
                        'difficulty': q_data.get('difficulty', 1),
                        'points': q_data.get('points', 1),
                        'explanation': q_data.get('explanation', ''),
                    }
                    if image_field:
                        fields['image'] = image_field

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
            except Exception as exc:
                result.errors.append(f'Q{i}: {exc}')
                result.failed += 1

        result.images_saved = len(extracted_images)
        result.image_dir = image_rel_dir if extracted_images else ''
        result.detail = {'topic': topic_name, 'year_level': year_level}
        return result.to_dict()

    def get_template_json(self) -> dict:
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
        for i, ex in enumerate(exercises, 1):
            title = ex['title'].strip()
            try:
                with transaction.atomic():
                    existing = CodingExercise.objects.filter(
                        topic_level=topic_level,
                        title=title,
                    ).first()
                    fields = {
                        'description': ex.get('instructions', '').strip(),
                        'starter_code': ex.get('starter_code', ''),
                        'expected_output': ex.get('expected_output', '').strip(),
                        'required_code_patterns': self._normalize_required_patterns(
                            ex.get('required_code_patterns')
                        ),
                        'hints': ex.get('hints', ''),
                        'order': int(ex.get('display_order', i)),
                        'is_active': True,
                    }
                    if existing:
                        for k, v in fields.items():
                            setattr(existing, k, v)
                        existing.save()
                        result.updated += 1
                    else:
                        CodingExercise.objects.create(
                            topic_level=topic_level,
                            title=title,
                            **fields,
                        )
                        result.inserted += 1
            except Exception as exc:
                result.errors.append(f'Exercise {i} ({title!r}): {exc}')
                result.failed += 1

        result.detail = {
            'language': language.name,
            'topic': topic.name,
            'level': level,
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
