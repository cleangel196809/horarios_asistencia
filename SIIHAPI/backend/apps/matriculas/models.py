"""SIIHAPI · Modelos de Matrículas y Estudiantes (RF-21 a RF-25)."""
from django.db import models
from django.conf import settings


class Estudiante(models.Model):
    """RF-21 · Registro de estudiantes."""

    # Fase 2 (2026-09-03): la tabla unificada 'estudiantes_perfil' usa
    # usuario_id como PK (perfil 1:1 sobre 'usuarios'), no un id_estudiante
    # autonumérico separado — se convierte 'usuario' en la PK real (mismo
    # patrón que Docente en apps.personal).
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='estudiante',
        primary_key=True,
        db_column='usuario_id',
    )
    codigo = models.CharField(max_length=20, unique=True)
    programa = models.ForeignKey('academico.Programa', on_delete=models.PROTECT)
    semestre_actual = models.IntegerField(default=1)
    fecha_ingreso = models.DateField(null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        # Fase 2 (2026-09-03): tabla compartida con planeación/SISCA.
        managed = False
        db_table = 'estudiantes_perfil'
        verbose_name = 'Estudiante'
        verbose_name_plural = 'Estudiantes'
        indexes = [
            # NO indexar 'codigo': ya tiene unique=True (Oracle ORA-01408).
            models.Index(fields=['programa', 'activo']),
        ]

    def __str__(self):
        return f'{self.codigo} - {self.usuario.nombre_completo}'


class Periodo(models.Model):
    """Periodo académico (ej: 2026-1, 2026-2)."""

    id_periodo = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=10, unique=True, help_text='Ej: 2026-2')
    nombre = models.CharField(max_length=60)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    fecha_limite_cancelacion = models.DateField(null=True, blank=True)
    activo = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'periodos'
        verbose_name = 'Periodo Académico'
        verbose_name_plural = 'Periodos Académicos'
        ordering = ['-fecha_inicio']

    def __str__(self):
        return self.codigo


class Matricula(models.Model):
    """RF-22 · Matrícula del estudiante en una materia por periodo."""

    ESTADO_CHOICES = (
        ('ACTIVA',     'Activa'),
        ('INSCRITA',   'Inscrita'),   # Fase 3 (2026-09-04): pre-registro sin confirmar aun (ver importar_inscritos)
        ('CANCELADA',  'Cancelada'),
        ('FINALIZADA', 'Finalizada'),
    )

    id_matricula = models.AutoField(primary_key=True)
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='matriculas')
    materia = models.ForeignKey('academico.Materia', on_delete=models.PROTECT)
    periodo = models.ForeignKey(Periodo, on_delete=models.PROTECT)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='ACTIVA')
    nota_final = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    fecha_matricula = models.DateTimeField(auto_now_add=True)
    fecha_cancelacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'SIIHAPI_MATRICULA'
        verbose_name = 'Matrícula'
        verbose_name_plural = 'Matrículas'
        unique_together = [('estudiante', 'materia', 'periodo')]
        indexes = [
            models.Index(fields=['periodo', 'estado']),
            models.Index(fields=['estudiante', 'periodo']),
        ]

    def __str__(self):
        return f'{self.estudiante.codigo} en {self.materia.codigo} [{self.periodo.codigo}]'
