from django.contrib import admin

from .models import (
    WhatsAppConfig, WhatsAppMessageLog, WhatsAppPreference, WhatsAppTemplate,
)


@admin.register(WhatsAppConfig)
class WhatsAppConfigAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'school', 'is_enabled', 'notify_on_publish',
                    'notify_on_submission', 'updated_at')
    list_filter = ('is_enabled',)
    search_fields = ('school__name',)


@admin.register(WhatsAppPreference)
class WhatsAppPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'opted_in', 'receive_publish',
                    'receive_results', 'opted_in_at')
    list_filter = ('opted_in', 'receive_publish', 'receive_results')
    search_fields = ('user__username', 'user__email', 'phone')


@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(admin.ModelAdmin):
    list_display = ('key', 'meta_template_name', 'language_code', 'category',
                    'is_active')
    list_filter = ('is_active', 'category')
    search_fields = ('key', 'meta_template_name')


@admin.register(WhatsAppMessageLog)
class WhatsAppMessageLogAdmin(admin.ModelAdmin):
    list_display = ('recipient_phone', 'event_type', 'status', 'school',
                    'created_at', 'status_updated_at')
    list_filter = ('status', 'event_type')
    search_fields = ('recipient_phone', 'provider_message_id',
                     'recipient__username')
    readonly_fields = ('created_at', 'sent_at', 'delivered_at', 'read_at',
                       'failed_at', 'status_updated_at')
