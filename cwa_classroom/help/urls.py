from django.urls import path
from . import views

app_name = 'help'

urlpatterns = [
    path('', views.HelpCentreView.as_view(), name='help_centre'),
    path('search/', views.HelpSearchView.as_view(), name='help_search'),
    path('faq/', views.HelpFAQView.as_view(), name='help_faq'),
    path('context/', views.HelpContextView.as_view(), name='help_context'),
    path('category/<slug:slug>/', views.HelpCategoryView.as_view(), name='help_category'),
    path('article/<slug:slug>/', views.HelpArticleView.as_view(), name='help_article'),
]
