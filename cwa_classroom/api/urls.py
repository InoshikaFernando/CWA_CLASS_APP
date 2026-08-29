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
from billing import api_views as billing_api
from classroom import api_views as classroom_api
from coding import api_views as coding_api
from feedback import api_views as feedback_api
from help import api_views as help_api
from homework import api_views as homework_api
from maths import api_views as maths_api
from number_puzzles import api_views as puzzles_api
from progress import api_views as progress_api
from rewards import api_views as rewards_api
from worksheets import api_views as worksheets_api

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

# --- Learning ---
router.register('homework', homework_api.HomeworkViewSet, basename='homework')
router.register('submissions', homework_api.HomeworkSubmissionViewSet,
                basename='submission')
router.register('reports', progress_api.PeriodReportViewSet, basename='report')
router.register('points', rewards_api.PointsAwardViewSet, basename='points')
router.register('worksheet-assignments', worksheets_api.WorksheetAssignmentViewSet,
                basename='worksheet-assignment')
router.register('worksheet-submissions', worksheets_api.WorksheetSubmissionViewSet,
                basename='worksheet-submission')
router.register('basic-facts-results', maths_api.BasicFactsResultViewSet,
                basename='basic-facts-result')

# --- Coding practice ---
router.register('coding/languages', coding_api.CodingLanguageViewSet,
                basename='coding-language')
router.register('coding/topics', coding_api.CodingTopicViewSet,
                basename='coding-topic')
router.register('coding/exercises', coding_api.CodingExerciseViewSet,
                basename='coding-exercise')
router.register('coding/submissions', coding_api.CodingSubmissionViewSet,
                basename='coding-submission')

# --- Number puzzles ---
router.register('puzzles/levels', puzzles_api.NumberPuzzleLevelViewSet,
                basename='puzzle-level')
router.register('puzzles/progress', puzzles_api.PuzzleProgressViewSet,
                basename='puzzle-progress')
router.register('puzzles', puzzles_api.NumberPuzzleViewSet, basename='puzzle')

# --- Billing (read-only: invoices are issued by the school's own workflow) ---
router.register('invoices', billing_api.InvoiceViewSet, basename='invoice')
router.register('payments', billing_api.InvoicePaymentViewSet, basename='payment')

# --- Help & feedback ---
router.register('help/categories', help_api.HelpCategoryViewSet,
                basename='help-category')
router.register('help/articles', help_api.HelpArticleViewSet,
                basename='help-article')
router.register('help/faqs', help_api.FAQViewSet, basename='help-faq')
router.register('feedback', feedback_api.FeedbackViewSet, basename='feedback')

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

    # --- Rewards (single-resource endpoints, not collections) ---
    path('points/total/', rewards_api.PointsTotalView.as_view(), name='points-total'),
    path('leaderboard/', rewards_api.LeaderboardView.as_view(), name='leaderboard'),
    path('maths/time-spent/', maths_api.TimeSpentView.as_view(), name='maths-time-spent'),

    path('', include(router.urls)),
]
