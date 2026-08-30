"""Period progress report serializers."""

from rest_framework import serializers

from api.serializers import UserSummarySerializer
from progress.models import PeriodReport


class PeriodReportSummarySerializer(serializers.ModelSerializer):
    """List row — everything but the frozen snapshot.

    ``data`` is the whole report (topics, attempts, trend, awards) and can be
    large; sending it in a list would make "show me my reports" download every
    report the student has ever had.
    """

    student = UserSummarySerializer(read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    school_name = serializers.CharField(source='school.name', read_only=True, default=None)

    class Meta:
        model = PeriodReport
        fields = (
            'id', 'student', 'subject_name', 'school_name',
            'period_type', 'period_start', 'period_end', 'generated_at',
        )


class PeriodReportDetailSerializer(PeriodReportSummarySerializer):
    """Detail — adds the frozen snapshot the report was generated from."""

    class Meta(PeriodReportSummarySerializer.Meta):
        fields = PeriodReportSummarySerializer.Meta.fields + ('data',)
