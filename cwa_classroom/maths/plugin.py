"""
Mathematics subject plugin.

Phase 1 wired this plugin to the upload router. Phase 2 adds the homework
contract — the logic is a direct lift from the previous inline helpers in
``homework/views.py`` (``_topics_with_questions``, ``_build_topic_groups``,
``_select_and_save_questions``) plus the answer-grading branch from
``StudentHomeworkTakeView.post``.
"""

from __future__ import annotations

from classroom.subject_registry import SubjectPlugin


class MathsPlugin(SubjectPlugin):
    slug = 'mathematics'
    display_name = 'Mathematics'
    order = 10
    supports_homework = True

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_parser(self):
        from classroom.upload_services import MathsQuestionParser
        return MathsQuestionParser()

    # ------------------------------------------------------------------
    # Homework — topic picker
    # ------------------------------------------------------------------

    def homework_topic_tree(self, classroom):
        """Return the 3-level (strand, mid, leaves) grouping for the selector."""
        topics = self._topics_with_questions(classroom)
        return self._build_topic_groups(topics)

    def homework_topic_field_name(self) -> str:
        return 'topics'

    def save_homework_topics(self, homework, selected_topic_ids):
        from classroom.models import Topic
        homework.topics.set(Topic.objects.filter(pk__in=selected_topic_ids))
        # Clear the alternate M2M so the homework only carries maths topics.
        homework.coding_topics.clear()

    def pick_homework_items(self, classroom, selected_topic_ids, n):
        from classroom.models import Topic
        from maths.models import Question
        from maths.views import select_questions_stratified

        topics = list(Topic.objects.filter(pk__in=selected_topic_ids))
        if not topics:
            return []

        classroom_levels = classroom.levels.all()
        qs = Question.objects.filter(topic__in=topics).select_related('topic')
        if classroom_levels.exists():
            qs = qs.filter(level__in=classroom_levels)
        all_questions = list(qs)

        if not all_questions:
            return []
        if len(all_questions) > n:
            selected = select_questions_stratified(all_questions, n)
        else:
            selected = all_questions
        return [q.pk for q in selected]

    # ------------------------------------------------------------------
    # Homework — student take / result
    # ------------------------------------------------------------------

    def take_item_template(self) -> str:
        return 'homework/partials/_maths_take_item.html'

    def take_item_context(self, content_id):
        import random
        from maths.models import Question

        q = Question.objects.prefetch_related('answers').get(pk=content_id)
        shuffled = list(q.answers.all())
        random.shuffle(shuffled)
        return {
            'question': q,
            'shuffled_answers': shuffled,
        }

    def grade_answer(self, content_id, post_data):
        """Mirrors the original branch in StudentHomeworkTakeView.post.

        Returns fields suitable for ``HomeworkStudentAnswer(**result)`` —
        plus ``points_earned`` computed as 1.0 per correct row (legacy
        behaviour — callers can override by passing question.points).
        """
        from maths.models import Answer, Question

        q = Question.objects.get(pk=content_id)
        is_correct = False
        selected_answer_obj = None
        text_answer = ''

        if q.question_type in (Question.MULTIPLE_CHOICE, Question.TRUE_FALSE):
            answer_id = post_data.get(f'answer_{q.id}')
            if answer_id:
                try:
                    selected_answer_obj = Answer.objects.get(id=answer_id, question=q)
                    is_correct = selected_answer_obj.is_correct
                except Answer.DoesNotExist:
                    pass
        else:
            text_answer = post_data.get(f'answer_{q.id}', '').strip()
            correct_answer = q.answers.filter(is_correct=True).first()
            if correct_answer and text_answer.lower() == correct_answer.answer_text.lower():
                is_correct = True

        return {
            'question_id': q.pk,                # legacy FK (written by the view)
            'selected_answer_id': selected_answer_obj.pk if selected_answer_obj else None,
            'text_answer': text_answer,
            'is_correct': is_correct,
            'points_earned': q.points if is_correct else 0,
            'answer_data': {},                  # unused for maths
        }

    def result_item_template(self) -> str:
        return 'homework/partials/_maths_result_item.html'

    def result_item_context(self, answer):
        return {'ans': answer}

    # ------------------------------------------------------------------
    # Internal helpers — lifted verbatim from homework/views.py
    # ------------------------------------------------------------------

    @staticmethod
    def _topics_with_questions(classroom):
        from django.db.models import Exists, OuterRef
        from classroom.models import Topic
        from maths.models import Question

        classroom_levels = classroom.levels.all()
        base_qs = (
            Topic.objects.filter(is_active=True)
            .select_related('subject', 'parent', 'parent__parent')
            .order_by('subject__name', 'parent__name', 'name')
        )
        if classroom_levels.exists():
            question_filter = Question.objects.filter(
                topic=OuterRef('pk'), level__in=classroom_levels,
            )
        else:
            question_filter = Question.objects.filter(topic=OuterRef('pk'))
        return base_qs.filter(Exists(question_filter))

    @staticmethod
    def _build_topic_groups(topics_qs):
        from collections import OrderedDict

        strands: 'OrderedDict' = OrderedDict()

        for topic in topics_qs:
            parent = topic.parent
            grandparent = parent.parent if parent else None

            if parent is None:
                if topic.pk not in strands:
                    strands[topic.pk] = (topic, OrderedDict())
            elif grandparent is None:
                strand = parent
                if strand.pk not in strands:
                    strands[strand.pk] = (strand, OrderedDict())
                mids = strands[strand.pk][1]
                if topic.pk not in mids:
                    mids[topic.pk] = (topic, [])
            else:
                strand = grandparent
                mid = parent
                if strand.pk not in strands:
                    strands[strand.pk] = (strand, OrderedDict())
                mids = strands[strand.pk][1]
                if mid.pk not in mids:
                    mids[mid.pk] = (mid, [])
                mids[mid.pk][1].append(topic)

        return [
            (strand, [(mid, leaves) for mid, leaves in mids.values()])
            for strand, mids in strands.values()
        ]
