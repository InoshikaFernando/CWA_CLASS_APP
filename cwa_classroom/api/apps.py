from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'
    verbose_name = 'JSON API (v1)'

    def ready(self):
        # Importing registers the drf-spectacular extensions. Without the
        # import they are never discovered and the schema loses its security
        # scheme silently.
        from api import schema_extensions  # noqa: F401
