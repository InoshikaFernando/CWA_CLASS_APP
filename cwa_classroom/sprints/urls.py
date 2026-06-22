from django.urls import path

from . import views

app_name = 'sprints'

urlpatterns = [
    path('burndown/', views.BurndownChartView.as_view(), name='burndown'),
]
