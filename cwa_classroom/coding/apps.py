from django.apps import AppConfig


class CodingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'coding'
    verbose_name = 'Coding'

    def ready(self):
        from classroom.subject_registry import register
        from .plugin import CodingExercisePlugin, CodingProblemPlugin
        register(CodingExercisePlugin())
        register(CodingProblemPlugin())
