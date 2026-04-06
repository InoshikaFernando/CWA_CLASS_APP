"""
URL configuration for cwa_classroom project.
"""

from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.contrib.sitemaps.views import sitemap
from .sitemaps import StaticViewSitemap, AuthenticatedViewSitemap

from classroom.views import (
    PublicHomeView,
    SubjectsHubView,
    SubjectsListView,
    ContactView,
    JoinClassView,
    PrivacyPolicyView,
    TermsConditionsView,
)
from classroom.views_email import UnsubscribeView


sitemaps = {
    "static": StaticViewSitemap,
    "authenticated": AuthenticatedViewSitemap,
}


def robots_txt(request):
    lines = [
        "User-Agent: *",
        "Allow: /",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


urlpatterns = [
    # --- Bare-root files requested by browsers / crawlers ---
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'images/logo.png', permanent=True)),

    # --- Public / Hub routes (MUST be before classroom app include) ---
    path('', PublicHomeView.as_view(), name='public_home'),
    path('hub/', SubjectsHubView.as_view(), name='subjects_hub'),
    path('subjects/', SubjectsListView.as_view(), name='subjects_list'),
    path('contact/', ContactView.as_view(), name='contact'),
    path('join/', JoinClassView.as_view(), name='join_class'),
    path('privacy/', PrivacyPolicyView.as_view(), name='privacy_policy'),
    path('terms/', TermsConditionsView.as_view(), name='terms_conditions'),

    # --- Email unsubscribe (public, no login required) ---
    path('email/unsubscribe/<uuid:token>/', UnsubscribeView.as_view(), name='email_unsubscribe'),

    # --- Admin ---
    path('admin/', admin.site.urls),

    # --- Authentication ---
    path('accounts/', include('accounts.urls')),  # custom overrides first
    path('accounts/', include('django.contrib.auth.urls')),

    # --- AI tools (before core apps — core apps use root prefix) ---
    path('ai-import/', include('ai_import.urls', namespace='ai_import')),

    # --- Help & Documentation ---
    path('help/', include('help.urls', namespace='help')),

    # --- Core apps ---
    path('', include('classroom.urls')),
    path('maths/', include('number_puzzles.urls')),
    path('', include('progress.urls')),
    path('', include('quiz.subject_urls')),  # /<subject>/level/<n>/topic/<id>/quiz/ etc.

    # --- Homework ---
    path('', include('homework.urls', namespace='homework')),

    # --- Billing ---
    path('', include('billing.urls')),

    # --- Audit ---
    path('', include('audit.urls')),

    # --- Subject apps ---
    path('maths/', include('maths.urls', namespace='maths')),
    path('maths/', include('quiz.urls')),          # basic-facts, times-tables (maths-specific)
    path('maths/', include('quiz.level_urls')),    # level/<n>/... quiz routes under maths/
    path('coding/', include('coding.urls', namespace='coding')),
    path('music/', include('music.urls', namespace='music')),
    path('science/', include('science.urls', namespace='science')),

    # --- API ---
    path('api/', include('quiz.api_urls')),
    path('api/', include('progress.api_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
