from django.contrib import admin

from .models import NumberPuzzle, NumberPuzzleLevel


@admin.register(NumberPuzzleLevel)
class NumberPuzzleLevelAdmin(admin.ModelAdmin):
    list_display = ('number', 'name', 'operators_allowed', 'num_operands', 'max_result')
    ordering = ('number',)


@admin.register(NumberPuzzle)
class NumberPuzzleAdmin(admin.ModelAdmin):
    list_display = ('level', 'display_template', 'solution', 'target', 'is_active')
    list_filter = ('level', 'is_active')
    search_fields = ('display_template', 'solution')
