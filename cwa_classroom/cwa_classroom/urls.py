"""
URL configuration for cwa_classroom project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from classroom.views import (
    PublicHomeView,
    SubjectsHubView,
    SubjectsListView,
    ContactView,
    JoinClassView,
)

urlpatterns = [
    # --- Public / Hub routes (MUST be before classroom app include) ---
    path('', PublicHomeView.as_view(), name='public_home'),
    path('hub/', SubjectsHubView.as_view(), name='subjects_hub'),
    path('subjects/', SubjectsListView.as_view(), name='subjects_list'),
    path('contact/', ContactView.as_view(), name='contact'),
    path('join/', JoinClassView.as_view(), name='join_class'),

    # --- Admin ---
    path('admin/', admin.site.urls),

    # --- Authentication ---
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/', include('accounts.urls')),

    # --- Core apps ---
    path('', include('classroom.urls')),
    path('', include('quiz.urls')),
    path('', include('progress.urls')),

    # --- Billing ---
    path('', include('billing.urls')),

    # --- API ---
    path('api/', include('quiz.api_urls')),
    path('api/', include('progress.api_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
