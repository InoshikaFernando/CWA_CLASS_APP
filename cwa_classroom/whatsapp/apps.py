from django.apps import AppConfig


class WhatsappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'whatsapp'
    verbose_name = 'WhatsApp Notifications'

    def ready(self):
        # Receivers live in whatsapp.signals (homework hooks wired in Sprint 2).
        import whatsapp.signals  # noqa: F401
