from __future__ import annotations

import json

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
        # Phase 2: return structured language/topic/level tree
        return []

    def homework_topic_field_name(self) -> str:
        return 'language_topics'

    def save_homework_topics(self, homework, selected_topic_ids):
        # Phase 2: wire to homework M2M
        pass

    # ------------------------------------------------------------------
    # Homework — question selection
    # ------------------------------------------------------------------

    def pick_homework_items(self, classroom, selected_topic_ids, n):
        # Phase 2: select exercises from chosen topics
        return []

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
        is_correct = False
        selected_answer_obj = None
        text_answer = ''

        if ex.exercise_type == LanguageExercise.LETTER_WRITING:
            raw = post_data.get('stroke_data', '{}')
            try:
                stroke_data = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                stroke_data = {}
            is_correct = bool(stroke_data.get('objects'))
            return {
                'question_id': ex.pk,
                'selected_answer_id': None,
                'text_answer': '',
                'is_correct': is_correct,
                'points_earned': ex.points if is_correct else 0,
                'answer_data': {'stroke_data': stroke_data},
            }
        elif ex.exercise_type in (LanguageExercise.PHONICS_MCQ, LanguageExercise.SPELLING_MCQ):
            answer_id = post_data.get(f'answer_{ex.id}')
            if answer_id:
                try:
                    selected_answer_obj = LanguageAnswer.objects.get(id=answer_id, exercise=ex)
                    is_correct = selected_answer_obj.is_correct
                except LanguageAnswer.DoesNotExist:
                    pass
        else:
            text_answer = post_data.get(f'answer_{ex.id}', '').strip()
            correct = ex.answers.filter(is_correct=True).first()
            if correct and text_answer.lower() == correct.answer_text.lower():
                is_correct = True

        return {
            'question_id': ex.pk,
            'selected_answer_id': selected_answer_obj.pk if selected_answer_obj else None,
            'text_answer': text_answer,
            'is_correct': is_correct,
            'points_earned': ex.points if is_correct else 0,
            'answer_data': {},
        }

    def result_item_template(self) -> str:
        return 'homework/partials/_languages_result_item.html'

    def result_item_context(self, answer):
        return {'ans': answer}
