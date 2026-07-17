"""SIIHAPI · Modelos de Personal Docente (RF-16 a RF-20)."""
from django.db import models
from django.conf import settings


class Especialidad(models.Model):
    """RF-19 · Especialidades académicas."""

    id_especialidad = models.AutoField(primary_key=True)
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=120)

    class Meta:
        db_table = 'SIIHAPI_ESPECIALIDAD'
        verbose_name = 'Especialidad'
        verbose_name_plural = 'Especialidades'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Docente(models.Model):
    """RF-16 · Registro de docentes con tipo de contrato y especialidades."""

    TIPO_CONTRATO_CHOICES = (
        ('TC',       'Tiempo Completo'),
        ('MT',       'Medio Tiempo'),
        ('CATEDRA',  'Catedrático'),
    )

    id_docente = models.AutoField(primary_key=True)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='docente'
    )
    especialidades = models.ManyToManyField(Especialidad, related_name='docentes')
    tipo_contrato = models.CharField(max_length=10, choices=TIPO_CONTRATO_CHOICES, default='CATEDRA')
    carga_horaria_max = models.IntegerField(
        default=20,
        help_text='RF-18: Horas semanales máximas según contrato'
    )
    activo = models.BooleanField(default=True)
    fecha_vinculacion = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'SIIHAPI_DOCENTE'
        verbose_name = 'Docente'
        verbose_name_plural = 'Docentes'

    def __str__(self):
        return self.usuario.nombre_completo


class DisponibilidadDocente(models.Model):
    """RF-17 · Bloques NO disponibles declarados por cada docente."""

    DIA_CHOICES = (
        ('LU', 'Lunes'), ('MA', 'Martes'), ('MI', 'Miércoles'),
        ('JU', 'Jueves'), ('VI', 'Viernes'), ('SA', 'Sábado'),
    )

    id_disponibilidad = models.AutoField(primary_key=True)
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE, related_name='restricciones')
    dia = models.CharField(max_length=2, choices=DIA_CHOICES)
    bloque = models.IntegerField(help_text='Bloque horario (1-14)')
    motivo = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'SIIHAPI_DISPONIBILIDAD_DOCENTE'
        verbose_name = 'Restricción de disponibilidad'
        verbose_name_plural = 'Restricciones de disponibilidad'
        unique_together = [('docente', 'dia', 'bloque')]

    def __str__(self):
        return f'{self.docente} - {self.get_dia_display()} bloque {self.bloque}'
