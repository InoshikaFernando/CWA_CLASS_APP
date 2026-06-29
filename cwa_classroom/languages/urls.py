from django.urls import path

from . import views

app_name = 'languages'

urlpatterns = [
    path('', views.languages_index, name='index'),
    path('exercise/<int:exercise_id>/', views.exercise_detail, name='exercise_detail'),
]
