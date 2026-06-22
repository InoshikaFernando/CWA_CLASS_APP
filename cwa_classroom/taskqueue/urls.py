from django.urls import path

from . import views

app_name = 'taskqueue'

urlpatterns = [
    path('notifications/', views.notifications_dropdown, name='notifications'),
]
