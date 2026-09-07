"""SIIHAPI · apps/bienestar (Sprint 2, 2026-09-06 -- adelantado desde el
Sprint 4 original porque el criterio de aceptación del Sprint 2 exige que
una AlertaRiesgo aparezca en un dashboard de Bienestar/Mentoría). El rol
BIENESTAR_ACADEMICO ya existe (Fase 3, hoy en ROLES_SOLO_CONSULTA -- solo
lectura de horarios/docentes/programas). Este app agrega funciones de
ESCRITURA propias sin tocar ese bloqueo (ver permisos.bienestar_required,
nuevo en este Sprint)."""
from django.conf import settings
from django.db import models


class CasoBienestar(models.Model):
    """Se abre automáticamente cuando una asistencias.AlertaRiesgo llega a
    nivel ALTO (ver management command recalcular_alertas_riesgo), o
    manualmente por Bienestar."""
    ORIGEN_CHOICES = (('ALERTA_AUTOMATICA', 'Alerta automática'), ('MANUAL', 'Reporte manual'))
    ESTADO_CHOICES = (('ABIERTO', 'Abierto'), ('EN_ATENCION', 'En atención'), ('DERIVADO', 'Derivado'), ('CERRADO', 'Cerrado'))
    id_caso = models.AutoField(primary_key=True)
    estudiante = models.ForeignKey('matriculas.Estudiante', on_delete=models.CASCADE, related_name='casos_bienestar')
    alerta_origen = models.ForeignKey('asistencias.AlertaRiesgo', null=True, blank=True, on_delete=models.SET_NULL, related_name='casos_bienestar')
    origen = models.CharField(max_length=20, choices=ORIGEN_CHOICES, default='MANUAL')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='ABIERTO')
    asignado_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='casos_bienestar_asignados')
    created_at = models.DateTimeField(auto_now_add=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'bienestar_casos'
        indexes = [models.Index(fields=['estado'])]

    def __str__(self):
        return f'Caso #{self.id_caso} · {self.estudiante_id} [{self.estado}]'


class IntervencionBienestar(models.Model):
    id_intervencion = models.AutoField(primary_key=True)
    caso = models.ForeignKey(CasoBienestar, on_delete=models.CASCADE, related_name='intervenciones')
    tipo = models.CharField(max_length=40, help_text='Ej. Llamada, Cita presencial, Derivación a Mentoría, Derivación externa')
    notas = models.TextField()
    realizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='intervenciones_bienestar')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'bienestar_intervenciones'
        ordering = ['-fecha']

    def __str__(self):
        return f'Intervención #{self.id_intervencion} · caso #{self.caso_id}'
