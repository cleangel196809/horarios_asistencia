"""SIIHAPI · Modelos de Horarios (RF-26 a RF-37, RF-40)."""
from django.db import models


class Bloque(models.Model):
    """Bloques horarios de 80 minutos (14 bloques diarios, 6:00 a 22:00)."""

    id_bloque = models.AutoField(primary_key=True)
    numero = models.IntegerField(unique=True, help_text='1 a 14')
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    class Meta:
        db_table = 'SIIHAPI_BLOQUE'
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

    id_asignacion = models.AutoField(primary_key=True)
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

    creado_por = models.ForeignKey(
        'autenticacion.Usuario',
        on_delete=models.SET_NULL,
        null=True, blank=True
    )

    class Meta:
        db_table = 'SIIHAPI_ASIGNACION_IA'
        verbose_name = 'Asignación IA'
        verbose_name_plural = 'Asignaciones IA'
        ordering = ['-fecha_inicio']

    def __str__(self):
        return f'Asignación IA {self.job_id} [{self.estado}]'


class ReglaNegocio(models.Model):
    """RF-29 · Reglas de negocio personalizadas para la IA."""

    id_regla = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(blank=True)
    regla_json = models.JSONField(help_text='Regla declarativa para el solver CSP')
    activa = models.BooleanField(default=True)
    prioridad = models.IntegerField(default=5)

    class Meta:
        db_table = 'SIIHAPI_REGLA_NEGOCIO'
        verbose_name = 'Regla de Negocio'
        verbose_name_plural = 'Reglas de Negocio'
        ordering = ['prioridad']

    def __str__(self):
        return self.nombre
