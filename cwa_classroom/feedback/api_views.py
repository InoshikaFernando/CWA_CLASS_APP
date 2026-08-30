"""Feedback API — report a bug or ask for a feature from inside the app.

Read is limited to the caller's own submissions. Triage state (assignee,
priority, the Jira key) is not exposed: it is internal workflow, and a
reporter seeing "rejected" with an engineer's name attached is not the
conversation anyone wants to have through an app.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets

from feedback.models import Feedback


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = ('id', 'category', 'title', 'description', 'page_url',
                  'status', 'created_at')
        read_only_fields = ('id', 'status', 'created_at')


class FeedbackViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                      mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The caller's own feedback."""

    serializer_class = FeedbackSerializer
    ordering_fields = ('created_at',)
    queryset = Feedback.objects.none()  # schema generation only

    def get_queryset(self):
        return (Feedback.objects
                .filter(submitted_by=self.request.user, removed_at__isnull=True)
                .order_by('-created_at', 'id'))

    def perform_create(self, serializer):
        from billing.entitlements import get_school_for_user

        # Reporter, role and school come from the session, never the payload —
        # otherwise anyone could file feedback as someone else.
        serializer.save(
            submitted_by=self.request.user,
            role=self.request.user.primary_role or '',
            school=get_school_for_user(self.request.user),
        )
