"""SIIHAPI · Modelos de Horarios (RF-26 a RF-37, RF-40)."""
from django.conf import settings
from django.db import models


class Bloque(models.Model):
    """Bloques horarios de 80 minutos (14 bloques diarios, 6:00 a 22:00)."""

    id_bloque = models.AutoField(primary_key=True, db_column='id')
    numero = models.IntegerField(unique=True, help_text='1 a 14')
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    class Meta:
        # Fase 2 (2026-09-03): tabla compartida con planeación/SISCA.
        managed = False
        db_table = 'bloques_horario'
        verbose_name = 'Bloque Horario'
        verbose_name_plural = 'Bloques Horarios'
        ordering = ['numero']

    def __str__(self):
        return f'Bloque {self.numero}: {self.hora_inicio:%H:%M} - {self.hora_fin:%H:%M}'


class Horario(models.Model):
    """RF-26, RF-28, RF-33 · Asignación de horario por matrícula."""

    DIA_CHOICES = (
        ('LU', 'Lunes'), ('MA', 'Martes'), ('MI', 'Miércoles'),
        ('JU', 'Jueves'), ('VI', 'Viernes'), ('SA', 'Sábado'),
    )

    ESTADO_CHOICES = (
        ('PROPUESTO', 'Propuesto por IA'),
        ('APROBADO',  'Aprobado'),
        ('PUBLICADO', 'Publicado en SISCA'),
        ('CANCELADO', 'Cancelado'),
    )

    id_horario = models.AutoField(primary_key=True)
    matricula = models.ForeignKey('matriculas.Matricula', on_delete=models.CASCADE, related_name='horarios')
    materia = models.ForeignKey('academico.Materia', on_delete=models.PROTECT)
    docente = models.ForeignKey('personal.Docente', on_delete=models.PROTECT)
    salon = models.ForeignKey('infraestructura.Salon', on_delete=models.PROTECT)
    bloque = models.ForeignKey(Bloque, on_delete=models.PROTECT)
    dia = models.CharField(max_length=2, choices=DIA_CHOICES)

    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='PROPUESTO')

    # Integración SISCA (RF-40)
    id_sisca = models.CharField(
        max_length=50, null=True, blank=True,
        help_text='ID de la sesión correspondiente en SISCA'
    )
    publicado_sisca_fecha = models.DateTimeField(null=True, blank=True)

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'SIIHAPI_HORARIO'
        verbose_name = 'Horario'
        verbose_name_plural = 'Horarios'
        indexes = [
            # NO indexar 'matricula' solo: es ForeignKey y Django ya lo
            # indexa automaticamente (Oracle ORA-01408).
            models.Index(fields=['docente', 'dia', 'bloque']),
            models.Index(fields=['salon', 'dia', 'bloque']),
            models.Index(fields=['estado']),
            models.Index(fields=['id_sisca']),
        ]

    def __str__(self):
        return f'{self.materia.codigo} {self.get_dia_display()} B{self.bloque.numero}'


class AsignacionIA(models.Model):
    """RF-26, RF-31 · Registro de ejecuciones del motor IA."""

    ESTADO_CHOICES = (
        ('EN_COLA',    'En cola'),
        ('EJECUTANDO', 'Ejecutando'),
        ('COMPLETADA', 'Completada'),
        ('FALLIDA',    'Fallida'),
    )

    id_asignacion = models.AutoField(primary_key=True, db_column='id')
    periodo = models.ForeignKey('matriculas.Periodo', on_delete=models.CASCADE)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='EN_COLA')
    job_id = models.CharField(max_length=80, unique=True)

    fecha_inicio = models.DateTimeField(null=True, blank=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)
    duracion_ms = models.IntegerField(null=True, blank=True)

    total_matriculas = models.IntegerField(default=0)
    asignaciones_exitosas = models.IntegerField(default=0)
    conflictos_residuales = models.IntegerField(default=0)

    parametros = models.JSONField(default=dict, blank=True)
    log = models.TextField(blank=True)

    # db_column='creado_por': en la tabla unificada la columna se llama así
    # (no 'creado_por_id', el default de Django) — Fase 2, 2026-09-03.
    creado_por = models.ForeignKey(
        'autenticacion.Usuario',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        db_column='creado_por',
    )

    class Meta:
        managed = False
        db_table = 'asignaciones_ia'
        verbose_name = 'Asignación IA'
        verbose_name_plural = 'Asignaciones IA'
        ordering = ['-fecha_inicio']

    def __str__(self):
        return f'Asignación IA {self.job_id} [{self.estado}]'


class ReglaNegocio(models.Model):
    """RF-29 · Reglas de negocio personalizadas para la IA."""

    id_regla = models.AutoField(primary_key=True, db_column='id')
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(blank=True)
    regla_json = models.JSONField(help_text='Regla declarativa para el solver CSP')
    activa = models.BooleanField(default=True)
    prioridad = models.IntegerField(default=5)

    class Meta:
        managed = False
        db_table = 'reglas_negocio'
        verbose_name = 'Regla de Negocio'
        verbose_name_plural = 'Reglas de Negocio'
        ordering = ['prioridad']

    def __str__(self):
        return self.nombre


class SolicitudReprogramacion(models.Model):
    """Sprint 1 (2026-09-06) -- RF 1.4. Reprogramaciones puntuales (una
    sola fecha) -- NO modifica el Horario base, que sigue siendo el
    horario regular del resto del ciclo. El Docente titular del Horario
    la solicita; Coordinador/Secretaria Academica/Decano/Admin la
    aprueban o rechazan (via @operacion_required, igual que el resto de
    aprobaciones de horarios)."""
    TIPO_CHOICES = (
        ('CAMBIO_AULA', 'Cambio de aula'),
        ('SUSTITUCION_DOCENTE', 'Sustitución de docente'),
        ('CAMBIO_HORARIO', 'Cambio de horario puntual'),
    )
    ESTADO_CHOICES = (('PENDIENTE', 'Pendiente'), ('APROBADA', 'Aprobada'), ('RECHAZADA', 'Rechazada'))

    id_solicitud = models.AutoField(primary_key=True)
    horario = models.ForeignKey(Horario, on_delete=models.CASCADE, related_name='solicitudes_reprogramacion')
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    fecha_afectada = models.DateField(help_text='Fecha calendario concreta afectada -- el Horario base no cambia')
    salon_propuesto = models.ForeignKey('infraestructura.Salon', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    docente_sustituto_propuesto = models.ForeignKey('personal.Docente', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    motivo = models.TextField()
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='solicitudes_reprogramacion')
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='PENDIENTE')
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    fecha_revision = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'horarios_solicitudes_reprogramacion'
        indexes = [models.Index(fields=['estado']), models.Index(fields=['fecha_afectada'])]
        ordering = ['-created_at']

    def __str__(self):
        return f'Solicitud #{self.id_solicitud} [{self.estado}] · {self.horario}'
