from django.urls import path

from .views import GamesIndexView, LevelPlayView, SaveProgressView, StageMapView

app_name = 'games'

urlpatterns = [
    path('', GamesIndexView.as_view(), name='index'),
    path('<slug:game_slug>/', StageMapView.as_view(), name='stage_map'),
    path('<slug:game_slug>/stage/<int:stage_order>/level/<int:level_order>/', LevelPlayView.as_view(), name='play'),
    path('<slug:game_slug>/stage/<int:stage_order>/level/<int:level_order>/save/', SaveProgressView.as_view(), name='save_progress'),
]
