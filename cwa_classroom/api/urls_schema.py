"""OpenAPI schema and the human-readable docs, served off /api/.

The schema is the contract the mobile client is generated from, so it is
served by the app itself rather than hand-maintained — a hand-written schema
describes the API someone meant to build.
"""

from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView,
)

urlpatterns = [
    path('schema/', SpectacularAPIView.as_view(api_version='v1'), name='api-schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api-schema'), name='api-docs'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api-schema'), name='api-redoc'),
]
