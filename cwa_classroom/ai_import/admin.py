from django.contrib import admin

from .models import AIImportUsage, AIImportSession


@admin.register(AIImportUsage)
class AIImportUsageAdmin(admin.ModelAdmin):
    list_display = ('school', 'period_start', 'pages_processed', 'tokens_used')
    list_filter = ('period_start',)
    search_fields = ('school__name',)


@admin.register(AIImportSession)
class AIImportSessionAdmin(admin.ModelAdmin):
    list_display = ('pdf_filename', 'user', 'school', 'page_count', 'is_confirmed', 'created_at')
    list_filter = ('is_confirmed', 'created_at')
    search_fields = ('pdf_filename', 'user__username')
