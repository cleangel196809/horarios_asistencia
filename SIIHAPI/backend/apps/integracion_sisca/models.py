"""SIIHAPI · Modelos de Integración con SISCA (RF-40, RF-42)."""
from django.db import models


class IntegracionLog(models.Model):
    """Registro de cada llamada API entre SIIHAPI y SISCA (auditoría 24 meses)."""

    OPERACION_CHOICES = (
        ('PUBLICAR_HORARIOS',   'Publicar horarios a SISCA'),
        ('ACTUALIZAR_HORARIO',  'Actualizar horario en SISCA'),
        ('CANCELAR_HORARIO',    'Cancelar horario en SISCA'),
        ('CONSULTAR_ASISTENCIA','Consultar asistencia desde SISCA'),
        ('WEBHOOK_RECIBIDO',    'Webhook recibido de SISCA'),
    )

    ESTADO_CHOICES = (
        ('EXITO',   'Éxito'),
        ('ERROR',   'Error'),
        ('REINTENTO', 'En reintento'),
    )

    id_log = models.AutoField(primary_key=True)
    operacion = models.CharField(max_length=25, choices=OPERACION_CHOICES)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES)
    endpoint = models.CharField(max_length=200, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    respuesta = models.JSONField(default=dict, blank=True)
    codigo_http = models.IntegerField(null=True, blank=True)
    intentos = models.IntegerField(default=1)
    error_msg = models.TextField(blank=True)
    fecha = models.DateTimeField(auto_now_add=True)
    duracion_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'SIIHAPI_INTEGRACION_LOG'
        verbose_name = 'Log de Integración SISCA'
        verbose_name_plural = 'Logs de Integración SISCA'
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['operacion', '-fecha']),
            models.Index(fields=['estado']),
        ]

    def __str__(self):
        return f'{self.get_operacion_display()} [{self.estado}] {self.fecha}'
