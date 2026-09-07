from django.apps import AppConfig


class DecanoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.decano'
    verbose_name = 'Módulo del Decano'

    def ready(self):
        # Conecta los signals post_save que disparan la evaluación
        # INMEDIATA de ReglaIntervencion (ver apps/decano/signals.py) --
        # la evaluación PERIÓDICA (ventana_dias) corre aparte vía
        # Celery Beat (siihapi/celery.py CELERY_BEAT_SCHEDULE).
        from . import signals  # noqa: F401
