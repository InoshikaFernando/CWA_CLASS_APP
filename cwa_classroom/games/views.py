import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from .models import Game, Level, PlayerProgress, Stage

# ── Theme config referenced in templates ────────────────────────────────────

THEME_CONFIG = {
    'forest':  {'icon': '🌿', 'color': '#22c55e', 'gradient': 'from-green-500 to-emerald-600',  'bg': 'from-green-900 via-emerald-800 to-teal-700'},
    'ocean':   {'icon': '🌊', 'color': '#0ea5e9', 'gradient': 'from-blue-500 to-cyan-600',      'bg': 'from-blue-900 via-blue-800 to-cyan-700'},
    'space':   {'icon': '🚀', 'color': '#8b5cf6', 'gradient': 'from-violet-600 to-purple-700',  'bg': 'from-slate-900 via-purple-900 to-indigo-900'},
    'volcano': {'icon': '🌋', 'color': '#ef4444', 'gradient': 'from-red-500 to-orange-600',     'bg': 'from-red-900 via-red-800 to-orange-700'},
    'crystal': {'icon': '💜', 'color': '#a78bfa', 'gradient': 'from-purple-400 to-violet-600',  'bg': 'from-purple-900 via-violet-800 to-fuchsia-800'},
}

LEVEL_ICONS = ['🍄', '🌸', '🦋', '🌳', '🦊', '🏰', '⭐', '🎯', '🌟', '💎']


# ── Games index (3 game-type cards) ─────────────────────────────────────────

class GamesIndexView(TemplateView):
    template_name = 'games/index.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['games'] = [
            {
                'slug': 'maths-crossnumber',
                'name': 'Maths Cross Number',
                'tagline': 'Solve number clues in a crossword grid',
                'description': 'Fill in the grid using maths clues — addition, subtraction, multiplication and more. Each level unlocks a new challenge!',
                'icon': '🔢',
                'gradient': 'from-blue-500 to-indigo-600',
                'badge_bg': 'bg-blue-100',
                'badge_text': 'text-blue-700',
                'badge_label': 'Maths',
                'level_count': 5,
                'stages': 5,
            },
            {
                'slug': 'english-crossword',
                'name': 'English Crossword',
                'tagline': 'Build vocabulary with word puzzles',
                'description': 'Sharpen your spelling and vocabulary by completing crosswords filled with fun English clues across topics and themes.',
                'icon': '📝',
                'gradient': 'from-emerald-500 to-teal-600',
                'badge_bg': 'bg-emerald-100',
                'badge_text': 'text-emerald-700',
                'badge_label': 'English',
                'level_count': 5,
                'stages': 5,
            },
            {
                'slug': 'science-crossword',
                'name': 'Science Crossword',
                'tagline': 'Discover science through clues & passages',
                'description': 'Read a short science passage then answer crossword clues based on what you learned — biology, space, physics and more.',
                'icon': '🔬',
                'gradient': 'from-purple-500 to-violet-600',
                'badge_bg': 'bg-purple-100',
                'badge_text': 'text-purple-700',
                'badge_label': 'Science',
                'level_count': 5,
                'stages': 5,
            },
        ]
        return ctx


# ── Stage map ─────────────────────────────────────────────────────────────

class StageMapView(View):
    """Animated stage map for a game — shows all stages + level paths."""

    def get(self, request, game_slug):
        game = get_object_or_404(Game, slug=game_slug, is_active=True)
        stages = Stage.objects.filter(game=game, is_active=True).prefetch_related('levels')

        # Build progress lookup for logged-in users
        progress_map = {}
        if request.user.is_authenticated:
            progs = PlayerProgress.objects.filter(
                user=request.user,
                level__game=game,
            ).select_related('level')
            progress_map = {p.level_id: p for p in progs}

        stages_data = []
        found_current = False

        for stage in stages:
            theme = THEME_CONFIG.get(stage.theme, THEME_CONFIG['forest'])
            levels_data = []
            published = stage.levels.filter(status='published').order_by('order')

            for i, lvl in enumerate(published):
                prog = progress_map.get(lvl.id)
                stars = 0
                if prog and prog.completed:
                    # Stars: 3 = perfect, 2 = good, 1 = completed
                    if prog.score >= 90:
                        stars = 3
                    elif prog.score >= 60:
                        stars = 2
                    else:
                        stars = 1

                if stars > 0:
                    state = 'done'
                elif not found_current:
                    state = 'current'
                    found_current = True
                else:
                    state = 'locked'

                levels_data.append({
                    'level': lvl,
                    'state': state,
                    'stars': stars,
                    'icon': LEVEL_ICONS[i % len(LEVEL_ICONS)],
                })

            stages_data.append({
                'stage': stage,
                'theme': theme,
                'levels': levels_data,
            })

        return render(request, 'games/stage_map.html', {
            'game': game,
            'stages_data': stages_data,
        })


# ── Level player ─────────────────────────────────────────────────────────────

class LevelPlayView(View):
    """Renders the interactive crossword/cross-number player."""

    def get(self, request, game_slug, stage_order, level_order):
        game = get_object_or_404(Game, slug=game_slug, is_active=True)
        stage = get_object_or_404(Stage, game=game, order=stage_order)
        level = get_object_or_404(Level, stage=stage, order=level_order, status='published')

        # Load saved progress
        saved_cells = {}
        if request.user.is_authenticated:
            prog, _ = PlayerProgress.objects.get_or_create(
                user=request.user,
                level=level,
                defaults={'attempts': 0},
            )
            saved_cells = prog.cell_data or {}
        else:
            prog = None

        theme = THEME_CONFIG.get(stage.theme, THEME_CONFIG['forest'])

        return render(request, 'games/play.html', {
            'game': game,
            'stage': stage,
            'level': level,
            'theme': theme,
            'progress': prog,
            'saved_cells_json': json.dumps(saved_cells),
            'grid_data_json': json.dumps(level.grid_data),
            'clues_json': json.dumps(level.clues),
            # Answers sent to client for in-browser checking (educational game — acceptable)
            'answers_json': json.dumps(level.answers),
        })


# ── Save progress (HTMX POST) ─────────────────────────────────────────────

class SaveProgressView(View):
    """HTMX endpoint: save partially-filled cells for logged-in users."""

    def post(self, request, game_slug, stage_order, level_order):
        if not request.user.is_authenticated:
            return JsonResponse({'saved': False, 'reason': 'anonymous'})

        game = get_object_or_404(Game, slug=game_slug)
        stage = get_object_or_404(Stage, game=game, order=stage_order)
        level = get_object_or_404(Level, stage=stage, order=level_order)

        try:
            data = json.loads(request.body)
        except (ValueError, KeyError):
            return JsonResponse({'saved': False, 'reason': 'bad_json'}, status=400)

        cell_data = data.get('cells', {})
        completed = data.get('completed', False)
        score = data.get('score', 0)

        prog, _ = PlayerProgress.objects.get_or_create(
            user=request.user,
            level=level,
            defaults={'attempts': 0},
        )
        prog.cell_data = cell_data
        if completed and not prog.completed:
            prog.completed = True
            prog.score = score
            prog.attempts += 1
            prog.completed_at = timezone.now()
        prog.save()

        return JsonResponse({'saved': True})
