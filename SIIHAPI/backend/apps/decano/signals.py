"""
SIIHAPI · apps.decano -- signals de reaccion inmediata (Sprint 4, 2026-09-06).

Entregable 4 de la especificacion: dos vias de disparo, nunca una sola.
post_save en AsistenciaEstudiante/AsistenciaEvento/AsistenciaDocente
reacciona a un evento puntual llamando a la MISMA funcion de evaluacion
que usa Celery Beat (evaluar_reglas_intervencion_sync) -- nunca se
duplica la logica de calculo. Con USE_REDIS=False (modo dev, ver
settings.CELERY_TASK_ALWAYS_EAGER) la tarea corre sincrona en el mismo
request; con USE_REDIS=True se encola de verdad y el request no espera.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.asistencias.models import AsistenciaEstudiante, AsistenciaDocente
from apps.eventos.models import AsistenciaEvento


def _disparar_evaluacion_async():
    from .tasks import evaluar_reglas_intervencion
    evaluar_reglas_intervencion.delay()


@receiver(post_save, sender=AsistenciaEstudiante)
def _on_asistencia_estudiante_guardada(sender, instance, created, **kwargs):
    if created:
        _disparar_evaluacion_async()


@receiver(post_save, sender=AsistenciaDocente)
def _on_asistencia_docente_guardada(sender, instance, created, **kwargs):
    if created:
        _disparar_evaluacion_async()


@receiver(post_save, sender=AsistenciaEvento)
def _on_asistencia_evento_guardada(sender, instance, created, **kwargs):
    if created:
        _disparar_evaluacion_async()
