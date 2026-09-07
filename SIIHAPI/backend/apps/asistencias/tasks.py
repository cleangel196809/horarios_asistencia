"""SIIHAPI · apps.asistencias -- tarea Celery (Sprint 4, 2026-09-06).

Envoltorio delgado sobre el management command ya existente
(recalcular_alertas_riesgo, Sprint 2) para que Celery Beat pueda
dispararlo periódicamente (ver siihapi.settings.CELERY_BEAT_SCHEDULE) sin
duplicar la lógica de cálculo -- el comando sigue funcionando igual si se
corre a mano (`python manage.py recalcular_alertas_riesgo [--dry-run]`)."""
from celery import shared_task
from django.core.management import call_command


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def recalcular_alertas_riesgo(self):
    call_command('recalcular_alertas_riesgo')
