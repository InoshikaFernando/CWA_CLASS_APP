"""Help centre API — articles and FAQs, filtered to the caller's role.

Role filtering is not cosmetic here: help articles for a head of institute
describe billing, salary slips and student administration, and an article is
published to a role group precisely so the other groups do not read it. The
mapping and the queryset both come from the existing help app rather than
being restated.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, viewsets

from api.pagination import LargePagination
from help.models import FAQ, HelpArticle, HelpCategory
from help.utils import get_role_group


class HelpCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = HelpCategory
        fields = ('id', 'name', 'slug', 'description', 'order')


class HelpArticleSummarySerializer(serializers.ModelSerializer):
    category = HelpCategorySerializer(read_only=True)

    class Meta:
        model = HelpArticle
        fields = ('id', 'title', 'slug', 'excerpt', 'category',
                  'module', 'is_featured', 'updated_at')


class HelpArticleDetailSerializer(HelpArticleSummarySerializer):
    """Detail adds the body.

    Markdown rather than the rendered HTML: the app styles it natively, and
    shipping server-rendered HTML into a mobile view is how a help page ends
    up looking like a web page bolted into an app.
    """

    class Meta(HelpArticleSummarySerializer.Meta):
        fields = HelpArticleSummarySerializer.Meta.fields + ('body_markdown',)


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ('id', 'question', 'answer_markdown', 'order')


def _role_group(user):
    return get_role_group(user.primary_role)


class HelpArticleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    """Published articles for the caller's role group."""

    pagination_class = LargePagination
    lookup_field = 'slug'
    search_fields = ('title', 'excerpt', 'body_markdown')
    ordering_fields = ('order', 'updated_at')
    queryset = HelpArticle.objects.none()  # schema generation only

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return HelpArticleDetailSerializer
        return HelpArticleSummarySerializer

    @extend_schema(parameters=[
        OpenApiParameter('category', str, description='Category slug.'),
        OpenApiParameter('module', str, description='Filter to one module.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = HelpArticle.objects.for_role_group(_role_group(self.request.user))
        params = self.request.query_params
        if params.get('category'):
            queryset = queryset.filter(category__slug=params['category'])
        if params.get('module'):
            queryset = queryset.filter(module=params['module'])
        return queryset.order_by('order', 'title', 'id')


class HelpCategoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = HelpCategorySerializer
    pagination_class = LargePagination
    queryset = HelpCategory.objects.filter(is_active=True).order_by('order', 'name')


class FAQViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """FAQs for the caller's role group."""

    serializer_class = FAQSerializer
    pagination_class = LargePagination
    queryset = FAQ.objects.none()  # schema generation only

    def get_queryset(self):
        return (FAQ.objects
                .filter(is_published=True, role_group=_role_group(self.request.user))
                .order_by('order', 'question', 'id'))
