from django.urls import path
from . import views

urlpatterns = [
    path('signup/teacher/', views.TeacherSignupView.as_view(), name='signup_teacher'),
    path('register/teacher-center/', views.TeacherCenterRegisterView.as_view(), name='register_teacher_center'),
    path('register/individual-student/', views.IndividualStudentRegisterView.as_view(), name='register_individual_student'),
    path('register/school-student/', views.SchoolStudentRegisterView.as_view(), name='register_school_student'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('select-classes/', views.SelectClassesView.as_view(), name='select_classes'),
    path('account/change-package/', views.ChangePackageView.as_view(), name='change_package'),
    path('api/check-username/', views.CheckUsernameView.as_view(), name='check_username'),
    path('trial-expired/', views.TrialExpiredView.as_view(), name='trial_expired'),
]
