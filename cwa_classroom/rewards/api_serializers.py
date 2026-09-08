"""Points and leaderboard serializers."""

from rest_framework import serializers

from rewards.models import PointsAward, StudentPointsTotal


class PointsAwardSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointsAward
        fields = (
            'id', 'source', 'unit_key', 'points', 'label',
            'first_earned_at', 'updated_at',
        )


class StudentPointsTotalSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = StudentPointsTotal
        fields = (
            'total_points', 'units_completed', 'is_ranked',
            'display_name', 'last_earned_at',
        )


class PodiumEntrySerializer(serializers.Serializer):
    """One row of the leaderboard.

    Carries ``name`` — the board display name — and never the username, email
    or id of another child. A leaderboard is the one place in the app that
    deliberately shows other students, so it shows the least it can.
    """

    rank = serializers.IntegerField()
    name = serializers.CharField()
    points = serializers.FloatField()
    is_me = serializers.BooleanField()


class StandingSerializer(serializers.Serializer):
    """A rendered board — the shape ``rewards.services.Standing`` already has."""

    podium = PodiumEntrySerializer(many=True)
    rank = serializers.IntegerField()
    total_points = serializers.FloatField()
    board_size = serializers.IntegerField()
    points_to_next = serializers.FloatField()
    next_rank = serializers.IntegerField()
    message = serializers.CharField()
    scope = serializers.CharField()
    scope_label = serializers.CharField()
