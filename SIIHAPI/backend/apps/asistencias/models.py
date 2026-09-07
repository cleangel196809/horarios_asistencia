"""
SIIHAPI · apps/asistencias (Sprint 2, 2026-09-06).

Modo HÍBRIDO obligatorio: si SISCA ya tiene el dato de una fecha/materia
(vía integracion_sisca.cliente.get_cliente() -> ClienteSISCA), se usa ese;
si no, se registra localmente aquí. Antes de este Sprint, docente_asistencia/
estudiante_asistencia SOLO leían de SISCA -- no existía ningún modelo propio
de asistencia en SIIHAPI (confirmado 2026-09-06, ver grounding de la
especificación Roles+Decano). Este app llena ese vacío.
"""
from django.conf import settings
from django.db import models


class AsistenciaEstudiante(models.Model):
    ESTADO_CHOICES = (('PRESENTE', 'Presente'), ('AUSENTE', 'Ausente'), ('TARDANZA', 'Tardanza'), ('JUSTIFICADO', 'Justificado'))
    ORIGEN_CHOICES = (
        ('SISCA', 'Leído de SISCA'), ('LOCAL_DOCENTE', 'Registro manual del docente'),
        ('LOCAL_QR', 'Check-in QR'), ('LOCAL_BIOMETRICO', 'Check-in biométrico'),
    )
    id_asistencia = models.AutoField(primary_key=True)
    matricula = models.ForeignKey(
        'matriculas.Matricula', on_delete=models.CASCADE, related_name='asistencias',
        help_text='Referencia a SIIHAPI_MATRICULA -- ya liga estudiante+materia+periodo, no se duplica esa info aquí')
    horario = models.ForeignKey(
        'horarios.Horario', on_delete=models.CASCADE, related_name='asistencias',
        help_text='La clase concreta (día/bloque/docente/salón) a la que corresponde este registro')
    fecha = models.DateField()
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES)
    origen = models.CharField(max_length=18, choices=ORIGEN_CHOICES, default='LOCAL_DOCENTE')
    hora_registro = models.TimeField(null=True, blank=True, help_text='Para calcular tardanza contra Bloque.hora_inicio')
    id_sisca = models.CharField(max_length=64, blank=True, help_text='Id remoto si origen=SISCA, para no releer/duplicar')
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'asistencias_estudiante'
        unique_together = [('matricula', 'horario', 'fecha')]
        indexes = [models.Index(fields=['fecha', 'estado']), models.Index(fields=['matricula', 'fecha'])]

    def __str__(self):
        return f'{self.matricula_id} · {self.fecha} · {self.estado}'


class AsistenciaDocente(models.Model):
    """Control de horas efectivamente dictadas vs. contratadas (nómina) --
    Pilar 2 función 5, y Reporte #5 del Decano (Sprint 4)."""
    ESTADO_CHOICES = (('DICTADA', 'Dictada'), ('NO_DICTADA', 'No dictada'), ('SUSTITUIDA', 'Sustituida'))
    id_asistencia = models.AutoField(primary_key=True)
    horario = models.ForeignKey('horarios.Horario', on_delete=models.CASCADE, related_name='asistencias_docente')
    docente = models.ForeignKey('personal.Docente', on_delete=models.CASCADE, related_name='asistencias')
    fecha = models.DateField()
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='DICTADA')
    hora_inicio_real = models.TimeField(null=True, blank=True)
    hora_fin_real = models.TimeField(null=True, blank=True)
    docente_sustituto = models.ForeignKey('personal.Docente', null=True, blank=True, on_delete=models.SET_NULL, related_name='sustituciones_realizadas')
    firma_digital = models.TextField(blank=True, help_text='Hash/base64 de firma de cierre de clase, para validación de nómina')
    validado_para_nomina = models.BooleanField(default=False)
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text='Secretaría Académica -- función 4 de su pilar')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'asistencias_docente'
        unique_together = [('horario', 'fecha')]
        indexes = [models.Index(fields=['docente', 'fecha']), models.Index(fields=['validado_para_nomina'])]

    def __str__(self):
        return f'{self.docente_id} · {self.fecha} · {self.estado}'


class Justificacion(models.Model):
    ESTADO_CHOICES = (('PENDIENTE', 'Pendiente'), ('APROBADA', 'Aprobada'), ('RECHAZADA', 'Rechazada'))
    id_justificacion = models.AutoField(primary_key=True)
    asistencia_estudiante = models.ForeignKey(AsistenciaEstudiante, null=True, blank=True, on_delete=models.CASCADE, related_name='justificaciones')
    asistencia_docente = models.ForeignKey(AsistenciaDocente, null=True, blank=True, on_delete=models.CASCADE, related_name='justificaciones')
    soporte_archivo = models.FileField(upload_to='justificaciones/%Y/%m/', null=True, blank=True)
    motivo = models.TextField()
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='PENDIENTE')
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='justificaciones_revisadas')
    fecha_revision = models.DateTimeField(null=True, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='justificaciones_creadas')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'asistencias_justificaciones'
        constraints = [
            models.CheckConstraint(
                check=models.Q(asistencia_estudiante__isnull=False) | models.Q(asistencia_docente__isnull=False),
                name='justificacion_requiere_un_origen'),
        ]

    def __str__(self):
        return f'Justificación #{self.id_justificacion} [{self.estado}]'


class AlertaRiesgo(models.Model):
    """Alimenta el Reporte #4 del Decano (riesgo de deserción, Sprint 4) y
    dispara decano.ReglaIntervencion 'INASISTENCIA_ESTUDIANTE_MULTIMATERIA'
    (Sprint 4) -- por ahora (Sprint 2) el umbral que la genera es fijo, ver
    management command recalcular_alertas_riesgo."""
    NIVEL_CHOICES = (('BAJO', 'Bajo'), ('MEDIO', 'Medio'), ('ALTO', 'Alto'))
    ESTADO_CHOICES = (('ABIERTA', 'Abierta'), ('EN_SEGUIMIENTO', 'En seguimiento'), ('CERRADA', 'Cerrada'))
    id_alerta = models.AutoField(primary_key=True)
    estudiante = models.ForeignKey('matriculas.Estudiante', on_delete=models.CASCADE, related_name='alertas_riesgo')
    materias_afectadas = models.ManyToManyField('academico.Materia', related_name='alertas_riesgo')
    nivel = models.CharField(max_length=6, choices=NIVEL_CHOICES)
    pct_inasistencia_calculado = models.DecimalField(max_digits=5, decimal_places=2)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='ABIERTA')
    asignada_a = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='alertas_asignadas',
        help_text='Típicamente Mentoría o Bienestar Académico')
    fecha_deteccion = models.DateTimeField(auto_now_add=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    notas_cierre = models.TextField(blank=True)

    class Meta:
        db_table = 'asistencias_alertas_riesgo'
        indexes = [models.Index(fields=['estado', 'nivel'])]

    def __str__(self):
        return f'Alerta #{self.id_alerta} · {self.estudiante_id} · {self.nivel}'
