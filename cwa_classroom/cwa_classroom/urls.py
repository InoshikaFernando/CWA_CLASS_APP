"""
URL configuration for cwa_classroom project.
"""

from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

from classroom.views import (
    PublicHomeView,
    SubjectsHubView,
    SubjectsListView,
    ContactView,
    JoinClassView,
)
from classroom.views_email import UnsubscribeView


def robots_txt(request):
    lines = [
        "User-Agent: *",
        "Allow: /",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


urlpatterns = [
    # --- Bare-root files requested by browsers / crawlers ---
    path('robots.txt', robots_txt, name='robots_txt'),
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'images/logo.png', permanent=True)),

    # --- Public / Hub routes (MUST be before classroom app include) ---
    path('', PublicHomeView.as_view(), name='public_home'),
    path('hub/', SubjectsHubView.as_view(), name='subjects_hub'),
    path('subjects/', SubjectsListView.as_view(), name='subjects_list'),
    path('contact/', ContactView.as_view(), name='contact'),
    path('join/', JoinClassView.as_view(), name='join_class'),

    # --- Email unsubscribe (public, no login required) ---
    path('email/unsubscribe/<uuid:token>/', UnsubscribeView.as_view(), name='email_unsubscribe'),

    # --- Admin ---
    path('admin/', admin.site.urls),

    # --- Authentication ---
    path('accounts/', include('accounts.urls')),  # custom overrides first
    path('accounts/', include('django.contrib.auth.urls')),

    # --- Core apps ---
    path('', include('classroom.urls')),
    path('', include('number_puzzles.urls')),  # before quiz — quiz has catch-all basic-facts/<str>/
    path('', include('quiz.urls')),
    path('', include('progress.urls')),

    # --- Billing ---
    path('', include('billing.urls')),

    # --- Subject apps ---
    path('maths/', include('maths.urls', namespace='maths')),
    path('coding/', include('coding.urls', namespace='coding')),
    path('music/', include('music.urls', namespace='music')),
    path('science/', include('science.urls', namespace='science')),

    # --- API ---
    path('api/', include('quiz.api_urls')),
    path('api/', include('progress.api_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
