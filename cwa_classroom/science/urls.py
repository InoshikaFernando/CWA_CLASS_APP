from django.urls import path
from . import views

app_name = 'science'

urlpatterns = [
    path('', views.coming_soon, name='coming_soon'),
]
