"""Custom managers for question visibility filtering.

Provides visibility-aware querysets for maths.Question and coding.CodingExercise.
"""

from django.db import models
from django.db.models import Q


class VisibleQuestionsQuerySet(models.QuerySet):
    """QuerySet mixin for filtering questions by user visibility."""

    def visible_to(self, user):
        """Filter questions visible to the given user.

        Global questions (school=None) are visible to all authenticated users.
        Local questions are visible only within their scope:
          - school_id must match
          - if department_id set: must match
          - if classroom_id set: must match

        Args:
            user: Django user object

        Returns:
            QuerySet of visible questions
        """
        if not user.is_authenticated:
            # Unauthenticated users see only global questions
            return self.filter(school__isnull=True)

        if user.is_superuser:
            return self

        # Global questions visible to all authenticated users
        global_filter = Q(school__isnull=True)

        # Resolve school via attribute or SchoolTeacher relationship
        from brainbuzz.permissions import _get_user_school
        user_school = _get_user_school(user)
        if not user_school:
            return self.filter(global_filter)

        # Local questions: must be in same school
        local_filter = Q(school=user_school)

        # If user has department, also filter by department scope
        if hasattr(user, 'department') and user.department:
            dept_filter = Q(department__isnull=True) | Q(department=user.department)
            local_filter &= dept_filter

        # If user has classroom, also filter by classroom scope
        if hasattr(user, 'classroom') and user.classroom:
            class_filter = Q(classroom__isnull=True) | Q(classroom=user.classroom)
            local_filter &= class_filter

        # Combine global and local filters
        return self.filter(global_filter | local_filter)

    def visible_to_classroom(self, classroom):
        """Filter to what a CLASS may draw on, by the same scope hierarchy as
        ``visible_to`` — global ⊃ school ⊃ department ⊃ class.

        The homework generators pick questions for a *classroom*, not for the
        teacher driving the form, so they can't use ``visible_to(user)``: a
        teacher with rights over several classes would otherwise pull another
        class's private questions into this class's homework.

        A class with no school (or no class at all) sees global content only —
        the same answer ``_get_questions_for_level`` gives an individual
        student. A class with no department cannot see department-scoped rows,
        since it is in no department to be scoped to.
        """
        if classroom is None or classroom.school_id is None:
            return self.filter(school__isnull=True)

        local = Q(school=classroom.school_id)
        if classroom.department_id:
            local &= Q(department__isnull=True) | Q(department=classroom.department_id)
        else:
            local &= Q(department__isnull=True)
        local &= Q(classroom__isnull=True) | Q(classroom=classroom.pk)

        return self.filter(Q(school__isnull=True) | local)


class VisibleQuestionsManager(models.Manager):
    """Manager for questions with visibility filtering."""

    def get_queryset(self):
        """Return base queryset (without visibility filtering)."""
        return VisibleQuestionsQuerySet(self.model, using=self._db)

    def visible_to(self, user):
        """Get questions visible to user."""
        return self.get_queryset().visible_to(user)

    def visible_to_classroom(self, classroom):
        """Get questions a classroom may draw on."""
        return self.get_queryset().visible_to_classroom(classroom)


class MathsQuestionsQuerySet(VisibleQuestionsQuerySet):
    """QuerySet for maths questions with specialized filtering."""

    def by_topic(self, topic_name):
        """Filter by topic name (case-insensitive)."""
        return self.filter(topic__name__icontains=topic_name)

    def by_level(self, level_number):
        """Filter by level number (1-12 for BrainBuzz)."""
        return self.filter(level__level_number=level_number)

    def by_type(self, question_type):
        """Filter by question type."""
        return self.filter(question_type=question_type)

    def by_difficulty(self, difficulty):
        """Filter by difficulty (1, 2, or 3)."""
        return self.filter(difficulty=difficulty)

    def for_brainbuzz(self):
        """Filter to questions suitable for BrainBuzz (MCQ, TF, short answer, fill blank)."""
        valid_types = ['multiple_choice', 'true_false', 'short_answer', 'fill_blank']
        return self.filter(question_type__in=valid_types)


class MathsQuestionsManager(VisibleQuestionsManager):
    """Manager for maths questions with visibility filtering."""

    def get_queryset(self):
        """Return base queryset (without visibility filtering)."""
        return MathsQuestionsQuerySet(self.model, using=self._db)

    def visible_to(self, user):
        """Get questions visible to user."""
        return self.get_queryset().visible_to(user)

    def by_topic(self, topic_name):
        """Filter by topic name."""
        return self.get_queryset().by_topic(topic_name)

    def by_level(self, level_number):
        """Filter by level number."""
        return self.get_queryset().by_level(level_number)

    def by_type(self, question_type):
        """Filter by question type."""
        return self.get_queryset().by_type(question_type)

    def by_difficulty(self, difficulty):
        """Filter by difficulty."""
        return self.get_queryset().by_difficulty(difficulty)

    def for_brainbuzz(self):
        """Filter to questions suitable for BrainBuzz."""
        return self.get_queryset().for_brainbuzz()


class CodingExercisesQuerySet(VisibleQuestionsQuerySet):
    """QuerySet for coding exercises with specialized filtering."""

    def by_topic(self, topic_name):
        """Filter by topic name (case-insensitive)."""
        return self.filter(topic_level__topic__name__icontains=topic_name)

    def by_level(self, level_choice):
        """Filter by level choice (beginner, intermediate, advanced)."""
        return self.filter(topic_level__level_choice=level_choice)

    def by_type(self, question_type):
        """Filter by question type."""
        return self.filter(question_type=question_type)

    def by_difficulty(self, difficulty):
        """Filter by difficulty (1, 2, or 3)."""
        return self.filter(difficulty=difficulty)

    def for_brainbuzz(self):
        """Filter to exercises suitable for BrainBuzz (MCQ, TF, short answer, fill blank)."""
        valid_types = ['multiple_choice', 'true_false', 'short_answer', 'fill_blank']
        return self.filter(question_type__in=valid_types)


class CodingExercisesManager(VisibleQuestionsManager):
    """Manager for coding exercises with visibility filtering."""

    def get_queryset(self):
        """Return base queryset (without visibility filtering)."""
        return CodingExercisesQuerySet(self.model, using=self._db)

    def visible_to(self, user):
        """Get exercises visible to user."""
        return self.get_queryset().visible_to(user)

    def by_topic(self, topic_name):
        """Filter by topic name."""
        return self.get_queryset().by_topic(topic_name)

    def by_level(self, level_choice):
        """Filter by level choice."""
        return self.get_queryset().by_level(level_choice)

    def by_type(self, question_type):
        """Filter by question type."""
        return self.get_queryset().by_type(question_type)

    def by_difficulty(self, difficulty):
        """Filter by difficulty."""
        return self.get_queryset().by_difficulty(difficulty)

    def for_brainbuzz(self):
        """Filter to exercises suitable for BrainBuzz."""
        return self.get_queryset().for_brainbuzz()
