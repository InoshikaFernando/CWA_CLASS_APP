from django.urls import path
from django.contrib.auth.views import LogoutView
from django.views.decorators.csrf import csrf_exempt
from . import views

urlpatterns = [
    # CSRF-exempt logout: prevents 403 when CSRF token is stale due to
    # login/logout in another tab (CPP-36).  Logging out is safe to exempt.
    path('logout/', csrf_exempt(LogoutView.as_view()), name='logout'),

    # Override Django's built-in login with audit logging
    path('login/', views.AuditLoginView.as_view(), name='login'),
    # Override Django's built-in password_reset with diagnostic logging
    path('password_reset/', views.DiagnosticPasswordResetView.as_view(), name='password_reset'),
    path('signup/teacher/', views.TeacherSignupView.as_view(), name='signup_teacher'),
    path('register/teacher-center/', views.TeacherCenterRegisterView.as_view(), name='register_teacher_center'),
    path('register/individual-student/', views.IndividualStudentRegisterView.as_view(), name='register_individual_student'),
    path('register/school-student/', views.SchoolStudentRegisterView.as_view(), name='register_school_student'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('select-classes/', views.SelectClassesView.as_view(), name='select_classes'),
    path('account/change-package/', views.ChangePackageView.as_view(), name='change_package'),
    path('api/check-username/', views.CheckUsernameView.as_view(), name='check_username'),
    path('trial-expired/', views.TrialExpiredView.as_view(), name='trial_expired'),
    path('blocked/', views.AccountBlockedView.as_view(), name='account_blocked'),
]
