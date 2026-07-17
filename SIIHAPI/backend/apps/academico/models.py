"""
SIIHAPI · Modelos Académicos (Programas y Materias).

27 programas del Politécnico en 4 tipos:
· TL  - Técnicos Laborales (12)
· PROF - Profesionales (10)
· TEC - Tecnologías (4)
· ING - Curso de Inglés (1, con módulos MOD1 y MOD2)
"""
from django.db import models


class Facultad(models.Model):
    """RF-12 · 6 facultades del Politécnico Internacional."""

    id_facultad = models.AutoField(primary_key=True)
    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=100)
    decano = models.CharField(max_length=120, blank=True)
    descripcion = models.TextField(blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = 'SIIHAPI_FACULTAD'
        verbose_name = 'Facultad'
        verbose_name_plural = 'Facultades'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Programa(models.Model):
    """RF-11 · 27 programas en 4 tipos institucionales."""

    TIPO_CHOICES = (
        ('TL',   'Técnico Laboral'),
        ('PROF', 'Profesional'),
        ('TEC',  'Tecnología'),
        ('ING',  'Curso de Inglés'),
    )

    MODALIDAD_CHOICES = (
        ('PRES', 'Presencial'),
        ('VIRT', 'Virtual'),
        ('HIB',  'Híbrida'),
    )

    id_programa = models.AutoField(primary_key=True)
    facultad = models.ForeignKey(Facultad, on_delete=models.PROTECT, related_name='programas')
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=200)
    tipo = models.CharField(max_length=4, choices=TIPO_CHOICES)
    modalidad = models.CharField(max_length=4, choices=MODALIDAD_CHOICES, default='PRES')
    duracion_semestres = models.IntegerField(default=6)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'SIIHAPI_PROGRAMA'
        verbose_name = 'Programa'
        verbose_name_plural = 'Programas'
        ordering = ['tipo', 'nombre']
        indexes = [
            models.Index(fields=['tipo', 'activo']),
        ]

    def __str__(self):
        return f'[{self.get_tipo_display()}] {self.nombre}'


class Materia(models.Model):
    """RF-13 · Catálogo completo de asignaturas."""

    id_materia = models.AutoField(primary_key=True)
    programa = models.ForeignKey(Programa, on_delete=models.PROTECT, related_name='materias')
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=200)
    ciclo = models.IntegerField(default=1, help_text='Semestre o ciclo')
    creditos = models.IntegerField(default=2)
    horas_semanales = models.IntegerField(default=4)
    requiere_sala_sistemas = models.BooleanField(
        default=False,
        help_text='RF-37: asignaturas que necesitan sala de sistemas'
    )
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = 'SIIHAPI_MATERIA'
        verbose_name = 'Materia'
        verbose_name_plural = 'Materias'
        unique_together = [('programa', 'codigo')]
        ordering = ['programa', 'ciclo', 'nombre']
        indexes = [
            models.Index(fields=['programa', 'ciclo']),
        ]

    def __str__(self):
        return f'{self.codigo} · {self.nombre}'


class Prerequisito(models.Model):
    """RF-15 · Árbol de prerequisitos por materia."""

    id_prereq = models.AutoField(primary_key=True)
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE, related_name='prerequisitos')
    materia_requerida = models.ForeignKey(Materia, on_delete=models.CASCADE, related_name='requerida_por')

    class Meta:
        db_table = 'SIIHAPI_PREREQUISITO'
        verbose_name = 'Prerequisito'
        verbose_name_plural = 'Prerequisitos'
        unique_together = [('materia', 'materia_requerida')]

    def __str__(self):
        return f'{self.materia.codigo} ← requiere ← {self.materia_requerida.codigo}'
