from django.apps import AppConfig


class LanguagesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'languages'
    verbose_name = 'Languages'

    def ready(self):
        from classroom.subject_registry import register
        from .plugin import LanguagesPlugin
        register(LanguagesPlugin())
