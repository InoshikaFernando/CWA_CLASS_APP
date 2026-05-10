from django.apps import AppConfig


class MathsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'maths'
    verbose_name = 'Maths'

    def ready(self):
        from classroom.subject_registry import register
        from .plugin import MathsPlugin
        register(MathsPlugin())
