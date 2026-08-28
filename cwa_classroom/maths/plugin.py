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

    def content_topic_names(self, content_ids):
        """maths.Question -> its Topic name."""
        from maths.models import Question

        return {
            row['id']: row['topic__name']
            for row in Question.objects
            .filter(id__in=content_ids, topic__isnull=False)
            .values('id', 'topic__name')
        }
    brainbuzz_subject_key = 'maths'

    # Phase 3 — URL routing + sidebar wiring. Maths owns the plain
    # ``/maths/`` app plus the legacy ``/number-puzzles/`` mini-app that
    # lives alongside quiz views. The quiz app's basic-facts / times-tables
    # routes sit under ``/maths/`` (see maths/urls.py), so a single prefix
    # is enough.
    url_prefixes = ('/maths/', '/number-puzzles/')

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_parser(self):
        from classroom.upload_services import MathsQuestionParser
        return MathsQuestionParser()

    # ------------------------------------------------------------------
    # UI / routing  (Phase 3)
    # ------------------------------------------------------------------

    def sidebar_template(self) -> str | None:
        # Maths has no standalone sidebar partial: the maths student nav is
        # rendered inline by the unified ``sidebar_student.html`` (its
        # ``subject_sidebar == 'maths'`` branch). Returning None keeps this in
        # sync with base.html, which dispatches on role + subject_sidebar and
        # never calls this hook for maths.
        return None

    def has_content(self, classroom=None) -> bool:
        from maths.models import Question
        return Question.objects.exists()

    # ------------------------------------------------------------------
    # BrainBuzz — flat topic/level choices for the create-session form
    # ------------------------------------------------------------------

    def brainbuzz_topic_choices(self) -> dict:
        from classroom.models import Topic, Level
        topics = list(
            Topic.objects.filter(subject__slug='mathematics', subject__school__isnull=True)
            .order_by('name')
            .values('id', 'name')
        )
        # Only show levels 1-12 that have MCQ/TF/short-answer questions in maths
        levels = list(
            Level.objects.filter(
                level_number__gte=1,
                level_number__lte=12,
                maths_questions_by_level__question_type__in=[
                    'multiple_choice', 'true_false', 'short_answer', 'fill_blank'
                ],
                maths_questions_by_level__school__isnull=True,  # Global questions only
                maths_questions_by_level__topic__subject__slug='mathematics',
            )
            .distinct()
            .order_by('level_number')
            .values('id', 'level_number')
        )
        return {'maths_topics': topics, 'maths_levels': levels}

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

    def homework_question_type_choices(self):
        from maths.models import Question
        return Question.QUESTION_TYPES

    def pick_homework_items(self, classroom, selected_topic_ids, n, question_type=None):
        from classroom.models import Topic
        from maths.models import Question
        from maths.views import select_questions_stratified

        topics = list(Topic.objects.filter(pk__in=selected_topic_ids))
        if not topics:
            return []

        classroom_levels = classroom.levels.all()
        # Scope to what this CLASS may draw on. Unscoped, homework generated for
        # one school pulled in every other school's private questions.
        qs = (Question.objects.visible_to_classroom(classroom)
              .filter(topic__in=topics).select_related('topic'))
        if classroom_levels.exists():
            qs = qs.filter(level__in=classroom_levels)
        if question_type:
            qs = qs.filter(question_type=question_type)
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

        The multi-part types (fill_blank, table_of_values) are the exception:
        they are marked part by part, so ``points_earned`` is the share of
        gaps/cells the student got right and ``answer_data`` carries the
        breakdown the result page needs to say which one was wrong.
        ``is_correct`` still means *every* part right.
        """
        from maths.models import Answer, Question
        from maths.partial_credit import points_for

        q = Question.objects.get(pk=content_id)
        is_correct = False
        selected_answer_obj = None
        text_answer = ''
        # Set only by the part-graded types below (fill_blank, table_of_values);
        # None everywhere else means "one answer, marked all or nothing".
        partial = None

        if q.question_type in (Question.MULTIPLE_CHOICE, Question.TRUE_FALSE):
            answer_id = post_data.get(f'answer_{q.id}')
            if answer_id:
                try:
                    selected_answer_obj = Answer.objects.get(id=answer_id, question=q)
                    is_correct = selected_answer_obj.is_correct
                except Answer.DoesNotExist:
                    pass
        elif q.question_type == 'prime_factorization' and q.target_number:
            # Order-independent: every token must be prime and product == target_number.
            import re as _re
            text_answer = post_data.get(f'answer_{q.id}', '').strip()
            tokens = [t for t in _re.split(r'[x×*,\s]+', text_answer) if t]

            def _is_prime(n):
                if n < 2:
                    return False
                if n < 4:
                    return True
                if n % 2 == 0:
                    return False
                i = 3
                while i * i <= n:
                    if n % i == 0:
                        return False
                    i += 2
                return True

            try:
                nums = [int(t) for t in tokens]
                product = 1
                for x in nums:
                    product *= x
                is_correct = bool(nums) and product == q.target_number and all(_is_prime(x) for x in nums)
            except ValueError:
                is_correct = False
        elif q.question_type == 'long_division' and q.dividend is not None and q.divisor:
            # Accept "12", "12 r 0", "12r0" equivalents; canonicalise both sides.
            text_answer = post_data.get(f'answer_{q.id}', '').strip()
            quot, rem = divmod(q.dividend, q.divisor)
            import re as _re
            m = _re.match(r'^\s*(-?\d+)\s*(?:r\s*(-?\d+))?\s*$', text_answer.lower())
            if m:
                got_q = int(m.group(1))
                got_r = int(m.group(2)) if m.group(2) is not None else 0
                is_correct = (got_q == quot and got_r == rem)
        elif q.question_type == Question.COLUMN_OPERATION and q.column_result is not None:
            # Answer is computed from operands/operator — compare the student's
            # number to the computed result (tolerant of spaces / leading zeros)
            # so manually-created questions grade without a stored answer row.
            text_answer = post_data.get(f'answer_{q.id}', '').strip()
            import re as _re
            m = _re.match(r'^\s*(-?\d+)\s*$', text_answer.replace(' ', ''))
            if m:
                is_correct = (int(m.group(1)) == q.column_result)
        elif q.question_type == Question.MEASURE and q.numeric_answer is not None:
            # Tolerance-graded numeric answer (e.g. "measure angle a").
            from maths.geometry_grading import grade_measure
            text_answer = post_data.get(f'answer_{q.id}', '').strip()
            is_correct = grade_measure(q, text_answer)
        elif q.question_type == Question.DRAW_ON_GRID and q.grid_spec:
            # Set-comparison of grid segments/points (e.g. lines of symmetry).
            # The client serialises the drawn marks to JSON in answer_{id}.
            from maths.geometry_grading import grade_draw_on_grid
            text_answer = post_data.get(f'answer_{q.id}', '')
            is_correct = grade_draw_on_grid(q.grid_spec, text_answer)
        elif q.question_type == Question.SHAPE_SELECT and q.shape_spec:
            # Set-comparison of coloured shapes (e.g. "colour all the triangles").
            # The client serialises the coloured ids to JSON in answer_{id} as
            # {"selected": [...]}; the target set is derived from the spec.
            from maths.geometry_grading import grade_shape_select
            text_answer = post_data.get(f'answer_{q.id}', '')
            is_correct = grade_shape_select(q.shape_spec, text_answer)
        elif q.question_type in (Question.PLOT_POINTS, Question.PLOT_LINE) and q.plane_spec:
            # Set-comparison of plotted points / auto-connected segments on a
            # signed Cartesian plane. The client serialises the marks to JSON in
            # answer_{id} as {"points":[...]} or {"segments":[...]}.
            from maths.geometry_grading import grade_plane
            text_answer = post_data.get(f'answer_{q.id}', '')
            is_correct = grade_plane(q.plane_spec, text_answer)
        elif q.question_type == Question.IDENTIFY_COORDS and q.plane_spec:
            # Student types the coordinates of the plotted point(s); parsed and
            # compared as a set against the spec's target.points.
            from maths.geometry_grading import grade_identify_coords
            text_answer = post_data.get(f'answer_{q.id}', '').strip()
            is_correct = grade_identify_coords(q.plane_spec, text_answer)
        elif q.question_type == Question.READ_GRAPH and q.numeric_answer is not None:
            # Read a value off a graph: tolerance-graded numeric answer, reusing
            # the measure grader (numeric_answer + answer_tolerance).
            from maths.geometry_grading import grade_measure
            text_answer = post_data.get(f'answer_{q.id}', '').strip()
            is_correct = grade_measure(q, text_answer)
        elif q.question_type == Question.NUMBER_LINE and q.number_line_spec:
            # Mark a value on / read a value off a number line. Mark mode serialises
            # {"marks":[...]} to JSON in answer_{id}; read mode posts the typed value.
            from maths.geometry_grading import grade_number_line
            text_answer = post_data.get(f'answer_{q.id}', '')
            is_correct = grade_number_line(q.number_line_spec, text_answer)
        elif ((q.question_type == Question.TABLE_OF_VALUES and q.table_spec)
              or (q.question_type == Question.FILL_BLANK and q.blank_spec)):
            # Several answers in one question: a fill-in table of values
            # (cells serialised as {"cells":{"r,c":"value"}}) or a
            # fill-in-the-blank sentence ({"blanks":[...]}), both posted in
            # answer_{id}. Marked part by part, so nine of ten right earns nine
            # tenths of the points and answer_data names the tenth — see
            # maths.partial_credit.
            text_answer = post_data.get(f'answer_{q.id}', '')
            partial = q.grade_text_answer_parts(text_answer)
            if partial is None:
                # No verdict part by part (spec and payload don't line up) —
                # fall back to the all-or-nothing grader.
                is_correct = q.grade_text_answer(text_answer.strip())
            else:
                is_correct = partial.is_correct
        else:
            text_answer = post_data.get(f'answer_{q.id}', '').strip()
            # Routes to algebra grading when q.answer_format == 'algebra',
            # otherwise case/space-insensitive exact match.
            is_correct = q.grade_text_answer(text_answer)

        return {
            'question_id': q.pk,                # legacy FK (written by the view)
            'selected_answer_id': selected_answer_obj.pk if selected_answer_obj else None,
            'text_answer': text_answer,
            'is_correct': is_correct,
            # A part-graded answer is worth the share of its parts that are
            # right (0.9 of a 1-point money chart for nine of ten cells);
            # everything else is still all-or-nothing.
            'points_earned': (points_for(q.points, partial) if partial is not None
                              else (q.points if is_correct else 0)),
            # The per-part breakdown for the result page — which cell was
            # wrong, what was typed, what was wanted. Empty for the
            # single-answer types, which have nothing to break down.
            'answer_data': partial.as_answer_data() if partial is not None else {},
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
        visible = Question.objects.visible_to_classroom(classroom)
        if classroom_levels.exists():
            question_filter = visible.filter(
                topic=OuterRef('pk'), level__in=classroom_levels,
            )
        else:
            question_filter = visible.filter(topic=OuterRef('pk'))
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
