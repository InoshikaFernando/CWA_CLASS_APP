from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Prefetch
from django.shortcuts import get_object_or_404, render
from django.views import View

from .models import HelpCategory, HelpArticle, FAQ
from .utils import get_role_group


class HelpCentreView(LoginRequiredMixin, View):
    def get(self, request):
        role_group = get_role_group(getattr(request, 'session', {}).get('active_role') or
                                   (request.user.primary_role if request.user.is_authenticated else None))

        articles_qs = HelpArticle.objects.for_role_group(role_group)
        featured = articles_qs.filter(is_featured=True)[:5]

        categories = HelpCategory.objects.filter(
            is_active=True,
            articles__in=articles_qs,
        ).distinct().prefetch_related(
            Prefetch('articles', queryset=articles_qs, to_attr='role_articles')
        )

        return render(request, 'help/help_centre.html', {
            'categories': categories,
            'featured': featured,
            'role_group': role_group,
        })


class HelpCategoryView(LoginRequiredMixin, View):
    def get(self, request, slug):
        category = get_object_or_404(HelpCategory, slug=slug, is_active=True)
        role_group = get_role_group(getattr(request, 'session', {}).get('active_role') or
                                   (request.user.primary_role if request.user.is_authenticated else None))
        articles = HelpArticle.objects.for_role_group(role_group).filter(category=category)
        return render(request, 'help/category_detail.html', {
            'category': category,
            'articles': articles,
            'role_group': role_group,
        })


class HelpArticleView(LoginRequiredMixin, View):
    def get(self, request, slug):
        role_group = get_role_group(getattr(request, 'session', {}).get('active_role') or
                                   (request.user.primary_role if request.user.is_authenticated else None))
        article = get_object_or_404(
            HelpArticle.objects.for_role_group(role_group).select_related('category'),
            slug=slug,
        )
        related = HelpArticle.objects.for_role_group(role_group).filter(
            category=article.category
        ).exclude(pk=article.pk)[:8]

        return render(request, 'help/article_detail.html', {
            'article': article,
            'related': related,
            'role_group': role_group,
        })


class HelpFAQView(LoginRequiredMixin, View):
    def get(self, request):
        role_group = get_role_group(getattr(request, 'session', {}).get('active_role') or
                                   (request.user.primary_role if request.user.is_authenticated else None))
        category_slug = request.GET.get('category')
        faqs = FAQ.objects.filter(role_group=role_group, is_published=True).select_related('category')
        if category_slug:
            faqs = faqs.filter(category__slug=category_slug)

        categories = HelpCategory.objects.filter(
            is_active=True,
            faqs__role_group=role_group,
            faqs__is_published=True,
        ).distinct()

        return render(request, 'help/faq.html', {
            'faqs': faqs,
            'categories': categories,
            'selected_category': category_slug,
            'role_group': role_group,
        })


class HelpSearchView(LoginRequiredMixin, View):
    def get(self, request):
        role_group = get_role_group(getattr(request, 'session', {}).get('active_role') or
                                   (request.user.primary_role if request.user.is_authenticated else None))
        query = request.GET.get('q', '').strip()
        results = []

        if len(query) >= 2:
            results = list(HelpArticle.objects.for_role_group(role_group).filter(
                Q(title__icontains=query) |
                Q(body_markdown__icontains=query) |
                Q(excerpt__icontains=query)
            ).select_related('category')[:20])

        is_htmx = request.headers.get('HX-Request')
        if is_htmx:
            return render(request, 'help/partials/search_results.html', {
                'results': results,
                'query': query,
            })

        return render(request, 'help/search.html', {
            'results': results,
            'query': query,
            'role_group': role_group,
        })


class HelpContextView(LoginRequiredMixin, View):
    def get(self, request):
        role_group = get_role_group(getattr(request, 'session', {}).get('active_role') or
                                   (request.user.primary_role if request.user.is_authenticated else None))
        url_name = request.GET.get('url_name', '')
        module = request.GET.get('module', '')

        articles = []
        if url_name:
            articles = list(HelpArticle.objects.for_page(role_group, url_name)[:5])
        if not articles and module:
            articles = list(HelpArticle.objects.for_module(role_group, module)[:5])
        if not articles:
            articles = list(HelpArticle.objects.for_role_group(role_group).filter(is_featured=True)[:5])

        faqs = FAQ.objects.filter(role_group=role_group, is_published=True)[:5]

        return render(request, 'help/partials/context_panel.html', {
            'articles': articles,
            'faqs': faqs,
            'role_group': role_group,
            'url_name': url_name,
            'module': module,
        })
