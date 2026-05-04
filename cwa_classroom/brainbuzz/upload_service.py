"""Service for handling question uploads.

Orchestrates the workflow: parse → validate → deduplicate → save → return results
"""

from typing import Dict, List, Tuple
from django.db import transaction
from django.utils import timezone

from .upload_parsers import get_parser
from .permissions import auto_scope_question, get_user_role


class QuestionUploadService:
    """Handles question import workflow: parse → validate → save."""

    def __init__(self, user, subject_type: str = 'maths'):
        """Initialize the upload service.

        Args:
            user: Django user performing the upload
            subject_type: 'maths' or 'coding'
        """
        self.user = user
        self.subject_type = subject_type
        self.parser = None
        self.errors = []
        self.warnings = []
        self.created_count = 0
        self.skipped_count = 0
        self.results = {
            'status': 'pending',
            'created': 0,
            'skipped': 0,
            'errors': [],
            'warnings': [],
        }

    def upload_file(self, file_obj, file_format: str) -> Dict:
        """Main upload entry point.

        Args:
            file_obj: File-like object to upload
            file_format: 'json', 'csv', or 'excel'

        Returns:
            Dict with keys: status, created, skipped, errors, warnings
        """
        try:
            # Validate user can upload
            from .permissions import can_upload_questions
            if not can_upload_questions(self.user):
                self.errors.append("You do not have permission to upload questions")
                return self._result('error')

            # Get parser
            self.parser = get_parser(file_format)
            if not self.parser:
                self.errors.append(f"Unsupported file format: {file_format}")
                return self._result('error')

            # Parse file
            questions = self.parser.parse(file_obj)

            if self.parser.errors:
                self.errors.extend(self.parser.errors)

            if not questions:
                self.errors.append("No valid questions found in file")
                return self._result('error')

            # Validate and save each question
            with transaction.atomic():
                for q_dict in questions:
                    if self._process_question(q_dict):
                        self.created_count += 1
                    else:
                        self.skipped_count += 1

            return self._result('success' if self.created_count > 0 else 'warning')

        except Exception as e:
            self.errors.append(f"Upload failed: {str(e)}")
            return self._result('error')

    def _process_question(self, q_dict: Dict) -> bool:
        """Validate and save a single question.

        Args:
            q_dict: Question data dictionary

        Returns:
            True if saved, False if skipped
        """
        try:
            # Auto-scope based on user role
            q_dict = auto_scope_question(q_dict, self.user, self.subject_type)

            # Resolve topic and level names to IDs
            success, resolved_dict = self._resolve_ids(q_dict)
            if not success:
                self.skipped_count += 1
                return False

            q_dict = resolved_dict

            # Check for duplicates
            if self._duplicate_exists(q_dict):
                self.warnings.append(
                    f"Skipped duplicate: {q_dict.get('question_text', '')[:50]}..."
                )
                return False

            # Save to database
            self._save_question(q_dict)
            return True

        except Exception as e:
            self.errors.append(f"Error processing question: {str(e)}")
            return False

    def _resolve_ids(self, q_dict: Dict) -> Tuple[bool, Dict]:
        """Resolve topic/level names to database IDs.

        Args:
            q_dict: Question dict with topic_name and level_number

        Returns:
            (success, resolved_dict)
        """
        from classroom.models import Topic, Level

        if self.subject_type == 'maths':
            # Resolve topic name to ID
            topic_name = q_dict.get('topic_name')
            level_num = q_dict.get('level_number')

            if not topic_name or level_num is None:
                self.errors.append("Topic name and level number required for maths")
                return False, q_dict

            # Find topic
            topic = Topic.objects.filter(
                name=topic_name,
                subject__slug='mathematics',
                subject__school__isnull=True,  # Global topics
            ).first()

            if not topic:
                self.errors.append(
                    f"Topic '{topic_name}' not found. Available topics: "
                    f"{', '.join(Topic.objects.filter(subject__slug='mathematics').values_list('name', flat=True))}"
                )
                return False, q_dict

            # Find level
            level = Level.objects.filter(level_number=level_num).first()
            if not level:
                self.errors.append(f"Level {level_num} not found")
                return False, q_dict

            q_dict['topic_id'] = topic.id
            q_dict['level_id'] = level.id

            # Remove temporary fields
            q_dict.pop('topic_name', None)
            q_dict.pop('level_number', None)

        elif self.subject_type == 'coding':
            # For coding, resolve to TopicLevel
            from coding.models import TopicLevel, CodingTopic

            topic_name = q_dict.get('topic_name')
            level_choice = q_dict.get('level', 'beginner')

            if not topic_name:
                self.errors.append("Topic name required for coding")
                return False, q_dict

            # Find topic
            topic = CodingTopic.objects.filter(name=topic_name).first()
            if not topic:
                self.errors.append(
                    f"Coding topic '{topic_name}' not found"
                )
                return False, q_dict

            # Find TopicLevel
            topic_level = TopicLevel.objects.filter(
                topic=topic,
                level_choice=level_choice,
            ).first()

            if not topic_level:
                self.errors.append(
                    f"Topic level '{topic_name}' at '{level_choice}' not found"
                )
                return False, q_dict

            q_dict['topic_level_id'] = topic_level.id

            # Remove temporary fields
            q_dict.pop('topic_name', None)
            q_dict.pop('level', None)

        return True, q_dict

    def _duplicate_exists(self, q_dict: Dict) -> bool:
        """Check if question already exists in database.

        Args:
            q_dict: Question data dict

        Returns:
            True if duplicate exists
        """
        try:
            if self.subject_type == 'maths':
                from maths.models import Question

                return Question.objects.filter(
                    question_text=q_dict['question_text'],
                    topic_id=q_dict['topic_id'],
                    level_id=q_dict['level_id'],
                    school=q_dict.get('school'),
                    department=q_dict.get('department'),
                    classroom=q_dict.get('classroom'),
                ).exists()

            elif self.subject_type == 'coding':
                from coding.models import CodingExercise

                return CodingExercise.objects.filter(
                    title=q_dict.get('question_text', q_dict.get('title', '')),
                    topic_level_id=q_dict['topic_level_id'],
                    school=q_dict.get('school'),
                    department=q_dict.get('department'),
                    classroom=q_dict.get('classroom'),
                ).exists()

            return False

        except Exception:
            return False

    def _save_question(self, q_dict: Dict):
        """Save question and answers to database.

        Args:
            q_dict: Question data dict
        """
        if self.subject_type == 'maths':
            self._save_maths_question(q_dict)
        elif self.subject_type == 'coding':
            self._save_coding_question(q_dict)

    def _save_maths_question(self, q_dict: Dict):
        """Save a maths question and its answers."""
        from maths.models import Question, Answer

        # Extract answers before saving question
        answers = q_dict.pop('answers', [])
        # correct_short_answer is not a Question field — stored as an Answer instead
        q_dict.pop('correct_short_answer', None)

        # Create question
        question = Question.objects.create(**q_dict)

        # Create answers — parser uses 'text' key, Answer model uses 'answer_text'
        for answer_dict in answers:
            Answer.objects.create(
                question=question,
                answer_text=answer_dict.get('text') or answer_dict.get('answer_text', ''),
                is_correct=answer_dict.get('is_correct', False),
                order=answer_dict.get('order', 0),
            )

    def _save_coding_question(self, q_dict: Dict):
        """Save a coding exercise and its answers."""
        from coding.models import CodingExercise, CodingAnswer

        # Extract answers before saving
        answers = q_dict.pop('answers', [])

        # Rename question_text to title for coding exercises
        if 'question_text' in q_dict:
            q_dict['title'] = q_dict.pop('question_text')

        # Create exercise
        exercise = CodingExercise.objects.create(**q_dict)

        # Create answers if present
        for answer_dict in answers:
            answer_dict['exercise'] = exercise
            CodingAnswer.objects.create(**answer_dict)

    def _result(self, status: str) -> Dict:
        """Build and return result dict.

        Args:
            status: 'success', 'warning', or 'error'

        Returns:
            Result dictionary
        """
        return {
            'status': status,
            'created': self.created_count,
            'skipped': self.skipped_count,
            'errors': self.errors,
            'warnings': self.warnings,
            'timestamp': timezone.now().isoformat(),
        }
