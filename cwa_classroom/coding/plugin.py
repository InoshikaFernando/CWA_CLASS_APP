"""
Coding subject plugins.

Phase 1: registered for upload routing.
Phase 2b: ``CodingExercisePlugin`` now implements the full homework contract so
teachers can assign coding exercises as homework and students complete them in
a browser textarea with Piston-backed grading.

The ``CodingProblemPlugin`` stays homework-less — problems have test cases and
a richer competitive-programming grade flow that the homework model isn't
designed to carry. Problems remain available via the dedicated coding app
pages.
"""

from __future__ import annotations

from classroom.subject_registry import SubjectPlugin


# ════════════════════════════════════════════════════════════════════════════
# Helpers — shared by the topic-tree and grading methods
# ════════════════════════════════════════════════════════════════════════════

class _LanguageWrapper:
    """Minimal façade around ``CodingLanguage`` that mimics ``classroom.Topic``.

    The homework-create template iterates the 3-level
    ``(strand, [(mid, [leaves]), ...])`` shape and reads ``.pk`` / ``.name`` on
    each node. Coding's native hierarchy is Language → Topic → TopicLevel, so
    we wrap Language as the "strand" label only — it isn't selectable itself.
    """

    __slots__ = ('language',)

    def __init__(self, language):
        self.language = language

    @property
    def pk(self):
        return f'lang-{self.language.pk}'

    @property
    def name(self):
        return self.language.name


class _MidLabel:
    """Non-selectable grouping label (e.g. the level name under a topic)."""

    __slots__ = ('_label', '_pk_hint')

    def __init__(self, label, pk_hint):
        self._label = label
        self._pk_hint = pk_hint

    @property
    def pk(self):
        return f'label-{self._pk_hint}'

    @property
    def name(self):
        return self._label


# ════════════════════════════════════════════════════════════════════════════
# Exercise plugin — full homework contract
# ════════════════════════════════════════════════════════════════════════════

class CodingExercisePlugin(SubjectPlugin):
    slug = 'coding'
    display_name = 'Coding'
    order = 20
    supports_homework = True
    brainbuzz_subject_key = 'coding'

    # Phase 3 — everything under ``/coding/`` is ours (exercise listings,
    # problem challenges, language pages). The context processor uses this
    # to pick the Coding sidebar without hard-coding the branch.
    url_prefixes = ('/coding/',)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_parser(self):
        from classroom.upload_services import CodingExerciseParser
        return CodingExerciseParser()

    # ------------------------------------------------------------------
    # UI / routing  (Phase 3)
    # ------------------------------------------------------------------

    def sidebar_template(self) -> str:
        return 'partials/sidebar_coding.html'

    def has_content(self, classroom=None) -> bool:
        from coding.models import CodingLanguage
        return CodingLanguage.objects.filter(is_active=True).exists()

    # ------------------------------------------------------------------
    # BrainBuzz — flat topic-level choices for the create-session form
    # ------------------------------------------------------------------

    def brainbuzz_topic_choices(self) -> dict:
        from coding.models import TopicLevel
        topic_levels = list(
            TopicLevel.objects.filter(is_active=True)
            .select_related('topic', 'topic__language')
            .order_by('topic__language__order', 'topic__order', 'level_choice')
            .values('id', 'level_choice', 'topic__name', 'topic__language__name')
        )
        return {'coding_topic_levels': topic_levels}

    # ------------------------------------------------------------------
    # Homework — topic picker
    # ------------------------------------------------------------------

    def homework_topic_tree(self, classroom):
        """Return a (strand, [(mid, leaves)...]) grouping the template expects.

        Maps coding's Language → CodingTopic → TopicLevel structure onto:

            Language        → strand
            CodingTopic     → mid
            TopicLevel      → leaf (selectable — pk passed into pick_items)

        Only topic/level rows with at least one active CodingExercise appear,
        so the selector never lists empty branches.
        """
        from coding.models import CodingExercise, CodingLanguage, CodingTopic

        populated_level_ids = set(
            CodingExercise.objects.filter(is_active=True)
            .values_list('topic_level_id', flat=True)
            .distinct()
        )
        if not populated_level_ids:
            return []

        # Languages → topics → populated levels
        languages = (
            CodingLanguage.objects.filter(is_active=True)
            .prefetch_related('topics__topic_levels')
            .order_by('order', 'name')
        )

        result = []
        for lang in languages:
            mid_entries = []
            for topic in lang.topics.all():
                if not topic.is_active:
                    continue
                leaves = [
                    tl for tl in topic.topic_levels.all()
                    if tl.is_active and tl.pk in populated_level_ids
                ]
                if not leaves:
                    continue
                # Use the topic as the "mid" label; TopicLevels as leaves.
                # The template iterates ``leaves`` and reads .pk + .name,
                # so we just attach a display-friendly name to each TopicLevel.
                for tl in leaves:
                    # Monkey-patch a template-friendly ``name`` property.
                    # (TopicLevel.__str__ already renders well; we just need
                    # ``leaf.name`` to show the level nicely.)
                    tl.name = tl.get_level_choice_display()
                mid_entries.append((topic, leaves))
            if mid_entries:
                result.append((_LanguageWrapper(lang), mid_entries))

        return result

    def homework_topic_field_name(self) -> str:
        return 'coding_topics'

    def save_homework_topics(self, homework, selected_topic_ids):
        """Persist the selected CodingTopics onto the homework.

        The form posts ``coding_topics=<TopicLevel.pk>`` values — we back-map
        to the parent ``CodingTopic`` (M2M target) because the ``Homework``
        model tracks by topic, not by level.
        """
        from coding.models import CodingTopic, TopicLevel

        # Incoming ids are TopicLevel pks — translate to their parent topics.
        topic_pks = set(
            TopicLevel.objects.filter(pk__in=selected_topic_ids)
            .values_list('topic_id', flat=True)
        )
        homework.coding_topics.set(CodingTopic.objects.filter(pk__in=topic_pks))
        # Coding homework never uses the maths topics M2M.
        homework.topics.clear()

    def homework_question_type_choices(self):
        from coding.models import CodingExercise
        return CodingExercise.QUESTION_TYPE_CHOICES

    def pick_homework_items(self, classroom, selected_topic_ids, n, question_type=None):
        """Return up to ``n`` CodingExercise pks from the selected TopicLevels.

        Randomised but deterministic per session — callers that want strictly
        reproducible selection can seed ``random`` before calling.

        ``question_type`` optionally restricts to a single type (e.g.
        'write_code'); ``None`` selects across all types.
        """
        import random
        from coding.models import CodingExercise, TopicLevel

        tl_ids = [int(x) for x in selected_topic_ids if str(x).isdigit()]
        if not tl_ids:
            return []
        # Validate: only keep levels that still exist + are active.
        valid_tl_ids = list(
            TopicLevel.objects.filter(pk__in=tl_ids, is_active=True)
            .values_list('pk', flat=True)
        )
        if not valid_tl_ids:
            return []
        exercise_qs = CodingExercise.objects.filter(
            topic_level_id__in=valid_tl_ids, is_active=True,
        )
        if question_type:
            exercise_qs = exercise_qs.filter(question_type=question_type)
        exercise_pks = list(exercise_qs.values_list('pk', flat=True))
        if not exercise_pks:
            return []
        if len(exercise_pks) > n:
            return random.sample(exercise_pks, n)
        return exercise_pks

    # ------------------------------------------------------------------
    # Homework — student take / grade / result
    # ------------------------------------------------------------------

    def take_item_template(self) -> str:
        return 'homework/partials/_coding_take_item.html'

    def take_item_context(self, content_id):
        from coding.models import CodingExercise

        ex = (
            CodingExercise.objects
            .select_related('topic_level__topic__language')
            .get(pk=content_id)
        )
        is_choice = ex.question_type in (
            CodingExercise.MULTIPLE_CHOICE, CodingExercise.TRUE_FALSE,
        )
        return {
            'exercise': ex,
            'content_id': ex.pk,
            'language': ex.topic_level.topic.language,
            'question_type': ex.question_type,
            'is_write_code': ex.question_type == CodingExercise.WRITE_CODE,
            'is_choice': is_choice,
            'answers': list(ex.answers.order_by('order')) if is_choice else [],
        }

    def grade_answer(self, content_id, post_data):
        """Grade one coding exercise according to its ``question_type``.

        ``write_code`` (the historical default) runs the student's code via
        Piston and matches stdout to ``expected_output``. MCQ / true-false
        grade against the selected :class:`CodingAnswer`; short-answer /
        fill-blank grade against ``correct_short_answer`` (case-insensitive).
        """
        from coding.models import CodingExercise

        ex = (
            CodingExercise.objects
            .select_related('topic_level__topic__language')
            .get(pk=content_id)
        )

        if ex.question_type in (CodingExercise.MULTIPLE_CHOICE, CodingExercise.TRUE_FALSE):
            return self._grade_choice(ex, content_id, post_data)
        if ex.question_type in (CodingExercise.SHORT_ANSWER, CodingExercise.FILL_BLANK):
            return self._grade_short_answer(ex, content_id, post_data)
        return self._grade_write_code(ex, content_id, post_data)

    # ------------------------------------------------------------------
    # Quiz-type grading (MCQ / TF / short-answer / fill-blank)
    # ------------------------------------------------------------------

    def _grade_choice(self, ex, content_id, post_data):
        """Grade an MCQ / true-false exercise against the chosen CodingAnswer.

        The selected answer pk is NOT stored on the answer row's
        ``selected_answer`` FK — that points at ``maths.Answer`` — so the
        choice is recorded in ``answer_data`` for the review page instead.
        """
        raw = (
            post_data.get(f'coding_choice_{content_id}')
            or post_data.get('coding_choice')
            or ''
        )
        selected = None
        try:
            selected = ex.answers.get(pk=int(raw))
        except (ValueError, TypeError, ex.answers.model.DoesNotExist):
            selected = None

        is_correct = bool(selected and selected.is_correct)
        correct = ex.answers.filter(is_correct=True).first()
        selected_text = selected.answer_text if selected else ''
        return {
            'text_answer': selected_text[:500],
            'is_correct': is_correct,
            'points_earned': 1 if is_correct else 0,
            'answer_data': {
                'question_type': ex.question_type,
                'selected_answer_id': selected.pk if selected else None,
                'selected_text': selected_text,
                'correct_text': correct.answer_text if correct else '',
            },
        }

    def _grade_short_answer(self, ex, content_id, post_data):
        """Grade a short-answer / fill-blank exercise (case-insensitive match)."""
        submitted = (
            post_data.get(f'coding_text_{content_id}')
            or post_data.get('coding_text')
            or post_data.get('text_answer')
            or ''
        ).strip()
        expected = (ex.correct_short_answer or '').strip()
        is_correct = bool(expected) and submitted.casefold() == expected.casefold()
        return {
            'text_answer': submitted[:500],
            'is_correct': is_correct,
            'points_earned': 1 if is_correct else 0,
            'answer_data': {
                'question_type': ex.question_type,
                'submitted': submitted,
                'correct_text': expected,
            },
        }

    def _grade_write_code(self, ex, content_id, post_data):
        """Run the student's code via Piston and compare stdout to expected_output.

        Browser-sandbox languages (HTML/CSS/Scratch) have no Piston runtime
        mapping, so we mark any non-empty submission as correct for them —
        the homework flow doesn't (yet) know how to grade DOM output. The
        ``answer_data`` payload always carries the submitted code plus
        stdout/stderr for the review page.
        """
        from coding.execution import run_code

        code = (post_data.get(f'code_{content_id}') or '').strip()

        base = {
            'text_answer': code[:500],
            'answer_data': {
                'code': code,
                'expected_output': (ex.expected_output or '').rstrip(),
                'stdout': '',
                'stderr': '',
                'exit_code': None,
            },
        }

        if not code:
            return {
                **base,
                'is_correct': False,
                'points_earned': 0,
            }

        language = ex.topic_level.topic.language
        piston_lang = language.piston_language

        if piston_lang is None:
            # HTML / CSS / Scratch — graded on submission, not stdout.
            base['answer_data']['note'] = 'Browser-only runtime — marked on submission'
            return {
                **base,
                'is_correct': True,
                'points_earned': 1,
            }

        result = run_code(piston_lang, code)
        actual = (result.get('stdout') or '').rstrip()
        expected = (ex.expected_output or '').rstrip()
        is_correct = bool(expected) and actual == expected

        base['answer_data'].update({
            'stdout': result.get('stdout', ''),
            'stderr': result.get('stderr', ''),
            'exit_code': result.get('exit_code'),
        })
        return {
            **base,
            'is_correct': is_correct,
            'points_earned': 1 if is_correct else 0,
        }

    def result_item_template(self) -> str:
        return 'homework/partials/_coding_result_item.html'

    def result_item_context(self, answer):
        from coding.models import CodingExercise

        try:
            ex = (
                CodingExercise.objects
                .select_related('topic_level__topic__language')
                .get(pk=answer.content_id)
            )
        except CodingExercise.DoesNotExist:
            ex = None
        return {
            'ans': answer,
            'exercise': ex,
        }


# ════════════════════════════════════════════════════════════════════════════
# Problem plugin — upload only (no homework integration by design)
# ════════════════════════════════════════════════════════════════════════════

class CodingProblemPlugin(SubjectPlugin):
    slug = 'coding_problem'
    display_name = 'Coding Problems'
    order = 21
    supports_homework = False

    def upload_parser(self):
        from classroom.upload_services import CodingProblemParser
        return CodingProblemParser()
