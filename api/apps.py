from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'api'

    def ready(self):
        import api.schema  # noqa: F401
