"""The whole /api/v1/ surface, in one place.

One router rather than an include per app: the point of an API is that a
client can see all of it, and a single registry is the only version of that
list which cannot go stale. Each app still owns its own ``api_views`` and
``api_serializers`` modules — only the routing is centralised.
"""

from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter

from api import views_auth
from classroom import api_views as classroom_api

router = DefaultRouter()

# --- Reference data (cacheable by the client; changes rarely) ---
router.register('subjects', classroom_api.SubjectViewSet, basename='subject')
router.register('levels', classroom_api.LevelViewSet, basename='level')
router.register('topics', classroom_api.TopicViewSet, basename='topic')

# --- Classroom ---
router.register('classes', classroom_api.ClassRoomViewSet, basename='class')
router.register('sessions', classroom_api.ClassSessionViewSet, basename='session')
router.register('attendance', classroom_api.AttendanceViewSet, basename='attendance')
router.register('notifications', classroom_api.NotificationViewSet, basename='notification')
router.register('children', classroom_api.ChildrenViewSet, basename='child')

app_name = 'api'

urlpatterns = [
    # --- Auth ---
    path('auth/login/', views_auth.LoginView.as_view(), name='auth-login'),
    path('auth/refresh/', views_auth.RefreshView.as_view(), name='auth-refresh'),
    path('auth/verify/', views_auth.VerifyView.as_view(), name='auth-verify'),
    path('auth/logout/', views_auth.LogoutView.as_view(), name='auth-logout'),
    path('auth/me/', views_auth.MeView.as_view(), name='auth-me'),
    path('auth/change-password/', views_auth.ChangePasswordView.as_view(),
         name='auth-change-password'),

    path('', include(router.urls)),
]
