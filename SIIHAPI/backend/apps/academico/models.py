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

    id_facultad = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=100)
    # La tabla unificada 'facultades' tiene un 'decano_id' INTEGER FK a
    # usuarios(id) (para uso de planeación); en vez de forzar ese FK aquí
    # se agregó una columna adicional 'decano_nombre' TEXT (Fase 2,
    # 2026-09-03) para no cambiar cómo SIIHAPI usa este campo como texto.
    decano = models.CharField(max_length=120, blank=True, db_column='decano_nombre')
    descripcion = models.TextField(blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'facultades'
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

    id_programa = models.AutoField(primary_key=True, db_column='id')
    facultad = models.ForeignKey(Facultad, on_delete=models.PROTECT, related_name='programas')
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=200)
    tipo = models.CharField(max_length=4, choices=TIPO_CHOICES)
    modalidad = models.CharField(max_length=4, choices=MODALIDAD_CHOICES, default='PRES')
    duracion_semestres = models.IntegerField(default=6)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_column='created_at')

    class Meta:
        managed = False
        db_table = 'programas'
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

    id_materia = models.AutoField(primary_key=True, db_column='id')
    programa = models.ForeignKey(Programa, on_delete=models.PROTECT, related_name='materias')
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=200)
    # 'plan' (plan de estudios) existe en la tabla unificada 'materias' y no
    # tenía equivalente en SIIHAPI — se agrega aquí (Fase 2, 2026-09-03).
    plan = models.CharField(max_length=40, null=True, blank=True)
    # ciclo es TEXT en la tabla unificada (no siempre numérico, p.ej. datos
    # reales cargados desde Excel) — antes era IntegerField, se cambia a
    # CharField para no romper al leer valores no numéricos (Fase 2).
    ciclo = models.CharField(max_length=10, default='1', help_text='Semestre o ciclo')
    # creditos es NUMERIC en la tabla unificada (admite decimales) — antes
    # era IntegerField, se cambia a DecimalField (Fase 2, 2026-09-03).
    creditos = models.DecimalField(max_digits=4, decimal_places=1, default=2)
    horas_semanales = models.IntegerField(default=4)
    requiere_sala_sistemas = models.BooleanField(
        default=False,
        help_text='RF-37: asignaturas que necesitan sala de sistemas'
    )
    activa = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'materias'
        verbose_name = 'Materia'
        verbose_name_plural = 'Materias'
        # Restricción real de la tabla unificada (Fase 2, 2026-09-03): antes
        # era solo (programa, codigo); una misma materia puede repetirse con
        # distinto plan/ciclo, así que .get(programa=..., codigo=...) puede
        # devolver MultipleObjectsReturned — revisar en la Fase 5 (pruebas).
        unique_together = [('programa', 'codigo', 'plan', 'ciclo')]
        ordering = ['programa', 'ciclo', 'nombre']
        indexes = [
            models.Index(fields=['programa', 'ciclo']),
        ]

    def __str__(self):
        return f'{self.codigo} · {self.nombre}'


class Prerequisito(models.Model):
    """RF-15 · Árbol de prerequisitos por materia."""

    id_prereq = models.AutoField(primary_key=True, db_column='id')
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE, related_name='prerequisitos')
    materia_requerida = models.ForeignKey(Materia, on_delete=models.CASCADE, related_name='requerida_por')

    class Meta:
        managed = False
        db_table = 'prerequisitos'
        verbose_name = 'Prerequisito'
        verbose_name_plural = 'Prerequisitos'
        unique_together = [('materia', 'materia_requerida')]

    def __str__(self):
        return f'{self.materia.codigo} ← requiere ← {self.materia_requerida.codigo}'
