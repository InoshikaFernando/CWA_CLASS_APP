from django.urls import path

from . import views

urlpatterns = [
    path(
        'basic-facts/number-puzzles/',
        views.NumberPuzzlesHomeView.as_view(),
        name='number_puzzles_home',
    ),
    path(
        'basic-facts/number-puzzles/play/<slug:slug>/',
        views.NumberPuzzlesPlayView.as_view(),
        name='number_puzzles_play',
    ),
    path(
        'basic-facts/number-puzzles/results/<uuid:session_id>/',
        views.NumberPuzzlesResultsView.as_view(),
        name='number_puzzles_results',
    ),
]
