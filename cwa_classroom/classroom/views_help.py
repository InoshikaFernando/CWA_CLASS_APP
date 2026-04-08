from django.views.generic import ListView, DetailView
from django.http import Http404

from .models import HelpCategory, HelpArticle


class HelpIndexView(ListView):
    template_name = 'public/help_index.html'
    context_object_name = 'categories'

    def get_queryset(self):
        return (
            HelpCategory.objects
            .prefetch_related('articles')
            .order_by('order', 'name')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Attach only published articles to each category
        for category in ctx['categories']:
            category.published_articles = (
                category.articles.filter(is_published=True).order_by('order', 'title')
            )
        return ctx


class HelpArticleDetailView(DetailView):
    template_name = 'public/help_article.html'
    context_object_name = 'article'

    def get_object(self):
        try:
            return HelpArticle.objects.select_related('category').get(
                slug=self.kwargs['slug'],
                is_published=True,
            )
        except HelpArticle.DoesNotExist:
            raise Http404

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        article = ctx['article']
        # Sidebar: all published articles in same category
        ctx['sibling_articles'] = (
            HelpArticle.objects
            .filter(category=article.category, is_published=True)
            .order_by('order', 'title')
        )
        ctx['all_categories'] = (
            HelpCategory.objects
            .prefetch_related('articles')
            .order_by('order', 'name')
        )
        return ctx
