from __future__ import annotations

import json
import random
import unicodedata
from decimal import Decimal

from classroom.subject_registry import SubjectPlugin


class LanguagesPlugin(SubjectPlugin):
    slug = 'languages'
    display_name = 'Languages'
    order = 30
    supports_homework = True
    url_prefixes = ('/languages/',)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_parser(self):
        raise NotImplementedError("Languages upload parser — future phase")

    # ------------------------------------------------------------------
    # UI / routing
    # ------------------------------------------------------------------

    def sidebar_template(self) -> str:
        return 'partials/sidebar_languages.html'

    def has_content(self, classroom=None) -> bool:
        from .models import LanguageExercise
        return LanguageExercise.objects.filter(is_active=True).exists()

    # ------------------------------------------------------------------
    # BrainBuzz
    # ------------------------------------------------------------------

    def brainbuzz_topic_choices(self) -> dict:
        from .models import Language, LanguageTopic
        languages = list(Language.objects.filter(is_active=True).order_by('order', 'name').values('id', 'name'))
        topics = list(LanguageTopic.objects.filter(is_active=True).order_by('language', 'order', 'name').values('id', 'name', 'language_id'))
        return {'languages': languages, 'language_topics': topics}

    # ------------------------------------------------------------------
    # Homework — topic picker
    # ------------------------------------------------------------------

    def homework_topic_tree(self, classroom):
        """Return 3-level tree: [(Language, [(Topic, [LanguageTopicLevel, ...]), ...]), ...]

        Matches the structure expected by the homework creation template:
        strand = Language, mid = LanguageTopic, leaves = LanguageTopicLevel.
        LanguageTopicLevel has a .name property for template rendering.
        """
        from .models import Language, LanguageTopic, LanguageTopicLevel

        result = []
        languages = Language.objects.filter(is_active=True).prefetch_related(
            'topics__levels__exercises'
        ).order_by('order', 'name')

        for lang in languages:
            mid_items = []
            for topic in lang.topics.filter(is_active=True).order_by('order', 'name'):
                level_order = ['beginner', 'intermediate', 'advanced']
                leaves = sorted(
                    [lvl for lvl in topic.levels.all() if any(ex.is_active for ex in lvl.exercises.all())],
                    key=lambda l: level_order.index(l.level_choice) if l.level_choice in level_order else 99,
                )
                if leaves:
                    mid_items.append((topic, leaves))
            if mid_items:
                result.append((lang, mid_items))
        return result

    def homework_topic_field_name(self) -> str:
        return 'language_topic_levels'

    def save_homework_topics(self, homework, selected_topic_ids):
        from .models import LanguageTopicLevel
        levels = LanguageTopicLevel.objects.filter(pk__in=selected_topic_ids)
        homework.language_topic_levels.set(levels)

    # ------------------------------------------------------------------
    # Homework — question selection
    # ------------------------------------------------------------------

    def pick_homework_items(self, classroom, selected_topic_ids, n, question_type=None):
        """Return up to n LanguageExercise pks from the selected levels.

        ``question_type`` is accepted for parity with the other subject plugins
        (the homework auto-fill caller always passes it) but ignored — language
        exercises are not filtered by question type.
        """
        from .models import LanguageExercise
        pks = list(
            LanguageExercise.objects
            .filter(topic_level__in=selected_topic_ids, is_active=True)
            .values_list('pk', flat=True)
        )
        random.shuffle(pks)
        return pks[:n]

    # ------------------------------------------------------------------
    # Homework — student take / result
    # ------------------------------------------------------------------

    def take_item_template(self) -> str:
        return 'homework/partials/_languages_take_item.html'

    def take_item_context(self, content_id):
        from .models import LanguageExercise
        ex = LanguageExercise.objects.prefetch_related('answers').get(pk=content_id)
        return {'exercise': ex, 'answers': list(ex.answers.order_by('display_order'))}

    def grade_answer(self, content_id, post_data):
        from .models import LanguageAnswer, LanguageExercise

        ex = LanguageExercise.objects.get(pk=content_id)
        field = f'answer_{ex.id}'
        is_correct = False
        selected_answer_obj = None
        text_answer = ''
        score = 0.0
        answer_data = {}

        if ex.exercise_type == LanguageExercise.LETTER_WRITING:
            # Letter-writing is a canvas exercise: the student submits stroke
            # data, not a text field. Mirror the standalone view — any strokes
            # drawn count as a completed attempt.
            raw_strokes = post_data.get('stroke_data')
            if raw_strokes is not None:
                try:
                    stroke = json.loads(raw_strokes) if isinstance(raw_strokes, str) else raw_strokes
                except (ValueError, TypeError):
                    stroke = {}
                is_correct = bool(isinstance(stroke, dict) and stroke.get('objects'))
                text_answer = raw_strokes if isinstance(raw_strokes, str) else json.dumps(raw_strokes)
                answer_data = {'stroke_data': stroke}
            else:
                text_answer = (post_data.get(field) or '').strip()
                is_correct = bool(text_answer)
            score = 100.0 if is_correct else 0.0

        elif ex.exercise_type in (
            LanguageExercise.PHONICS_MCQ,
            LanguageExercise.SPELLING_MCQ,
            LanguageExercise.GRAMMAR_FILL_BLANK,
        ):
            answer_id = post_data.get(field)
            if answer_id:
                try:
                    selected_answer_obj = LanguageAnswer.objects.get(pk=int(answer_id), exercise=ex)
                    is_correct = selected_answer_obj.is_correct
                except (LanguageAnswer.DoesNotExist, ValueError, TypeError):
                    pass
            score = 100.0 if is_correct else 0.0

        elif ex.exercise_type == LanguageExercise.SPELLING_TYPE:
            text_answer = unicodedata.normalize('NFC', (post_data.get(field) or '').strip())
            expected = unicodedata.normalize('NFC', ex.prompt.strip())
            is_correct = text_answer.lower() == expected.lower()
            score = 100.0 if is_correct else 0.0

        elif ex.exercise_type == LanguageExercise.SENTENCE_ORDER:
            raw = post_data.get(field, '[]')
            try:
                submitted = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(submitted, list):
                    submitted = []
            except (ValueError, TypeError):
                submitted = []
            word_order = ex.puzzle_data.get('word_order', [])
            n = len(word_order)
            if n > 0:
                correct_count = sum(
                    1 for i, w in enumerate(submitted[:n])
                    if unicodedata.normalize('NFC', str(w)) == unicodedata.normalize('NFC', word_order[i])
                )
                score = round(correct_count / n * 100, 1)
            is_correct = score >= 80.0
            text_answer = json.dumps(submitted)

        elif ex.exercise_type in (LanguageExercise.CROSSWORD, LanguageExercise.ADVANCED_CROSSWORD):
            text_answer = (post_data.get(field) or '').strip()
            is_correct = bool(text_answer)
            score = 50.0 if is_correct else 0.0

        else:
            text_answer = (post_data.get(field) or '').strip()
            correct = ex.answers.filter(is_correct=True).first()
            if correct and text_answer:
                is_correct = text_answer.lower() == correct.answer_text.lower()
            score = 100.0 if is_correct else 0.0

        if ex.exercise_type == LanguageExercise.SENTENCE_ORDER:
            points_earned = (Decimal(str(ex.points)) * Decimal(str(score)) / Decimal('100')).quantize(Decimal('0.01'))
        else:
            points_earned = Decimal(str(ex.points)) if is_correct else Decimal('0')

        return {
            'question_id': ex.pk,
            'selected_answer_id': selected_answer_obj.pk if selected_answer_obj else None,
            'text_answer': text_answer,
            'is_correct': is_correct,
            'points_earned': points_earned,
            'answer_data': answer_data,
        }

    def result_item_template(self) -> str:
        return 'homework/partials/_languages_result_item.html'

    def result_item_context(self, answer):
        return {'ans': answer}
