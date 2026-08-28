"""Number puzzles API.

``NumberPuzzle.solution`` is the answer. It is not in the serializer at all —
not deferred, not popped — because a puzzle whose solution ships with it is
not a puzzle. Students check an answer through the existing puzzle views,
which grade server-side.
"""

from rest_framework import mixins, serializers, viewsets

from api.pagination import LargePagination
from api.scoping import scope_by_student
from number_puzzles.models import (
    NumberPuzzle, NumberPuzzleLevel, StudentPuzzleProgress,
)


class NumberPuzzleLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = NumberPuzzleLevel
        fields = (
            'id', 'number', 'name', 'slug', 'description',
            'operators_allowed', 'num_operands', 'brackets_shown',
            'puzzles_per_set', 'unlock_threshold', 'order',
        )


class NumberPuzzleSerializer(serializers.ModelSerializer):
    """A puzzle to solve. ``solution`` is deliberately absent — see the module
    docstring."""

    class Meta:
        model = NumberPuzzle
        fields = ('id', 'level_id', 'operands', 'target', 'display_template',
                  'has_multiple_solutions')


class StudentPuzzleProgressSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.name', read_only=True)

    class Meta:
        model = StudentPuzzleProgress
        fields = (
            'id', 'level_id', 'level_name', 'is_unlocked', 'best_score',
            'best_time_seconds', 'total_sessions', 'total_puzzles_attempted',
            'total_puzzles_correct', 'last_played_at',
        )


class NumberPuzzleLevelViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                               viewsets.GenericViewSet):
    serializer_class = NumberPuzzleLevelSerializer
    pagination_class = LargePagination
    queryset = NumberPuzzleLevel.objects.all().order_by('order', 'number')


class NumberPuzzleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = NumberPuzzleSerializer
    pagination_class = LargePagination
    queryset = NumberPuzzle.objects.filter(is_active=True).order_by('id')

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        level = self.request.query_params.get('level')
        return queryset.filter(level_id=level) if level else queryset


class PuzzleProgressViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Puzzle progress for students the caller may read."""

    serializer_class = StudentPuzzleProgressSerializer
    queryset = StudentPuzzleProgress.objects.none()  # schema generation only

    def get_queryset(self):
        return scope_by_student(
            StudentPuzzleProgress.objects.select_related('level'),
            self.request.user,
        ).order_by('level__order', 'id')
