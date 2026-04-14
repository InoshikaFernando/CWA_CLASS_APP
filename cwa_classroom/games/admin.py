from django.contrib import admin

from .models import Game, Level, LevelGenerationRequest, PlayerProgress, Stage


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'game_type', 'is_active', 'generation_threshold')
    list_filter = ('game_type', 'is_active')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ('game', 'order', 'name', 'theme', 'is_active')
    list_filter = ('game', 'theme', 'is_active')
    search_fields = ('name',)
    ordering = ('game', 'order')


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ('game', 'order', 'difficulty', 'status', 'created_at')
    list_filter = ('game', 'difficulty', 'status')
    search_fields = ('game__name',)
    ordering = ('game', 'order')


@admin.register(PlayerProgress)
class PlayerProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'level', 'completed', 'score', 'attempts', 'completed_at')
    list_filter = ('completed', 'level__game')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    raw_id_fields = ('user', 'level')


@admin.register(LevelGenerationRequest)
class LevelGenerationRequestAdmin(admin.ModelAdmin):
    list_display = ('game', 'status', 'triggered_by', 'trigger_reason', 'created_at')
    list_filter = ('game', 'status')
    search_fields = ('game__name', 'trigger_reason')
    raw_id_fields = ('triggered_by',)
