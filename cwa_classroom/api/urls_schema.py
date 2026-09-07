"""OpenAPI schema and the human-readable docs, served off /api/.

The schema is the contract the mobile client is generated from, so it is
served by the app itself rather than hand-maintained — a hand-written schema
describes the API someone meant to build.
"""

from django.urls import path
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView,
)

# drf-spectacular serves these with SERVE_PERMISSIONS = AllowAny by default,
# which would publish the full contract — every path, field and enum, including
# the staff-only ones — to anyone who asks. That contradicts the closed-by-
# default policy the rest of the API is built on, so the served copy requires a
# login. The checked-in api/schema.yml stays the source for client generation,
# so nothing needs the public endpoint.
_SCHEMA_PERMISSIONS = [IsAuthenticated]

urlpatterns = [
    path('schema/',
         SpectacularAPIView.as_view(api_version='v1',
                                    permission_classes=_SCHEMA_PERMISSIONS),
         name='api-schema'),
    path('docs/',
         SpectacularSwaggerView.as_view(url_name='api-schema',
                                        permission_classes=_SCHEMA_PERMISSIONS),
         name='api-docs'),
    path('redoc/',
         SpectacularRedocView.as_view(url_name='api-schema',
                                      permission_classes=_SCHEMA_PERMISSIONS),
         name='api-redoc'),
]
